"""Seal small C11 receipts and recompute scores from dispatched actions only.

No launches, credentials, network calls or desktop mutations. Raw failed runs
remain raw; their older summary metrics are never silently repaired in place.
"""
from datetime import datetime, timezone
import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "scripts/evidence"
SOURCES = (
    "src/grant_agent/cua_desktop.py", "src/grant_agent/cua_guard.py",
    "src/grant_agent/cua_native.py", "src/grant_agent/cua_fast.py",
    "src/grant_agent/cua_adaptation.py", "src/grant_agent/neyvia_cua.py",
    "src/grant_agent/cua_launch.py", "src/grant_agent/neyvia_cua_mcp.py",
    "config/cua-desktop-contract.json", "scripts/prove_c11_preview.py",
    "scripts/c11_preview_ui.py", "scripts/run_c11_cohort.py",
    "scripts/spike_c11_desktop.py", "scripts/seal_c11_receipt.py",
    "scripts/prove_c1c_native.py", "scripts/verify_c1c_apps.py",
    "web/src/neyvia/next/NxPreviewPane.jsx", "web/src/neyvia/next/nxCuaApi.js",
    "web/src/neyvia/next/nxCuaModel.js", "tools/cua-driver-win/c1-probe.cs",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_hashes(paths):
    """Bind checkout bytes separately from Git's configured text normalization."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    fields = subprocess.check_output(["git", "check-attr", "-z", "text", "eol", "--", *paths],
        cwd=ROOT, creationflags=flags).decode().split("\0")
    attributes = {}
    for i in range(0, len(fields) - 1, 3):
        path, key, value = fields[i:i + 3]
        attributes.setdefault(path, {})[key] = value
    config = subprocess.run(["git", "config", "--get", "core.autocrlf"], cwd=ROOT,
        capture_output=True, text=True, creationflags=flags, check=False)
    normalize_default = config.stdout.strip().lower() in {"true", "input"}
    hashes, normalized = {}, []
    for path in paths:
        data = (ROOT / path).read_bytes()
        attrs = attributes[path]
        normalize = attrs["text"] != "unset" and (attrs["text"] in {"set", "auto"}
            or attrs["eol"] in {"lf", "crlf"} or normalize_default)
        blob = data.replace(b"\r\n", b"\n") if normalize else data
        if blob != data:
            normalized.append(path)
        hashes[path] = hashlib.sha256(blob).hexdigest()
    return hashes, normalized


def quantile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    return round(ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower])
                 * (position - lower), 6)


def run():
    raw_names = ("C11-spike.json", "C11-guard.json", "C11-cohort-full.json",
                 "C11-cohort-native-second.json", "C11-preview.json")
    descriptors, raw = [], {}
    immutable = AREA / "C11-runs"
    immutable.mkdir(exist_ok=True)
    for name in raw_names:
        source = AREA / name
        data = source.read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        sealed = immutable / (checksum + ".json")
        if not sealed.exists():
            sealed.write_bytes(data)
        assert sealed.read_bytes() == data
        descriptors.append({"id": name.removesuffix(".json"), "path": str(sealed.relative_to(ROOT)).replace("\\", "/"),
                            "originalPath": str(source.relative_to(ROOT)).replace("\\", "/"),
                            "sha256": checksum, "kind": "raw"})
        raw[name] = json.loads(data)
    spike, cohort, preview = (raw[n] for n in ("C11-spike.json", "C11-cohort-full.json", "C11-preview.json"))
    earlier_engine = []
    for path in sorted((AREA / "C11-preview-runs").glob("*.json")):
        trial = json.loads(path.read_text(encoding="utf-8"))
        descriptors.append({"id": "preview-trial-" + path.stem[:12], "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                            "sha256": sha(path), "kind": "raw"})
        if trial.get("engineJourneyPassed") and trial.get("guard", {}).get("ok"):
            earlier_engine.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"),
                                 "at": trial["at"], "guard": trial["guard"],
                                 "sourceDrift": [p for p, digest in trial.get("sourceSha256", {}).items() if sha(ROOT / p) != digest],
                                 "renderedPreviewPassed": bool(trial.get("renderedPreview", {}).get("ok"))})
    apps, timings = [], []
    for row in cohort["apps"]:
        sent = [a for a in row["attempts"] if a.get("actionSent")]
        times = [a["atomicMs"] for a in sent]
        timings.extend(times)
        apps.append({"app": row["app"], "status": row["status"], "reason": row.get("reason"),
                     "verifiedActions": sum(bool(a.get("passed")) for a in sent), "dispatchedAttempts": len(sent),
                     "observationsWithoutAction": len(row["attempts"]) - len(sent),
                     "firstObservationMs": row.get("firstObservationMs"),
                     "p50Ms": quantile(times, .5), "p95Ms": quantile(times, .95)})
    completed = sum(a["verifiedActions"] == 5 for a in apps)
    preview_source_drift = [p for p, digest in preview.get("sourceSha256", {}).items() if sha(ROOT / p) != digest]
    gates = {
        "privateDesktopNativeMechanism": bool(spike.get("ok")),
        "previewHttpMcpNativeJourney": bool(preview.get("engineJourneyPassed") and preview.get("guard", {}).get("ok")),
        "renderedPreviewTypingAndClick": bool(preview.get("renderedPreview", {}).get("ok") and preview.get("guard", {}).get("ok")),
        "currentPreviewSourceBound": not preview_source_drift,
        "fullCohortZeroDisturbance": bool(cohort["guardAfter"]["ok"]),
        "atLeast15InstalledApps": completed >= 15,
        "cohortActionP50Under150Ms": bool(timings) and quantile(timings, .5) < 150,
        "successfulAppsFirstObservationUnder500Ms": bool(completed) and all(a["firstObservationMs"] < 500 for a in apps if a["verifiedActions"] == 5),
        "fallbackLadderImplementedAndProven": False,
        "C8IsolatedInceptionRun": False,
        "matchedPublicSuiteAndCompetitorArms": False,
    }
    limitations = [
        "C11 and C1 remain partial. Brokered/singleton, elevated and opaque apps still refuse or lack safe actionable controls.",
        "Hidden/minimized and offscreen fallbacks are declared, disabled and unproven. Input-desktop consent delivery is disabled under this session's absolute prohibition.",
        "The full 22-app raw summary counted observations without actions; only the recomputed dispatched-action figures here are action latency metrics.",
        "The installed cohort has a frozen manifest hash but lacks a complete runtime source manifest; preview separately binds its complete relevant source set.",
        "No C8 inception run, matched public Windows suite, competitor score or metered cost was produced.",
        "A strict guard fails on physical or unattributed input as well as agent interference; failing guard receipts cannot certify zero disturbance.",
        "The native fixture is one disposable real WinForms application, not a universal app result. UIA provider fallback is reported as Win32/MSAA, not successful UIA patterns.",
        "Authored manual and broader UI fallback messaging need the frontend/manual owner to integrate this contract; public services were untouched.",
    ]
    report = {"schema": "neyvia.c11.result.v1", "at": datetime.now(timezone.utc).isoformat(),
              "status": "partial", "complete": all(gates.values()), "gates": gates,
              "sourceSha256": {p: sha(ROOT / p) for p in SOURCES}, "previewSourceDrift": preview_source_drift,
              "receipts": descriptors, "nativeFixture": spike["latency"],
              "cohort": {"manifestApps": 22, "reportedApps": len(apps), "appsWithFiveVerifiedActions": completed,
                         "verifiedActions": sum(a["verifiedActions"] for a in apps), "dispatchedAttempts": len(timings),
                         "actionP50Ms": quantile(timings, .5), "actionP95Ms": quantile(timings, .95),
                         "apps": apps},
              "preview": {k: preview.get(k) for k in ("ok", "engineJourneyPassed", "mcp", "clState", "staleFrameRefused", "forwardedInput", "stream", "renderedPreview", "error")},
              "earlierZeroDisturbanceEngineTrials": earlier_engine,
              "zeroDisturbance": {"cohort": cohort["guardAfter"], "preview": preview.get("guard"), "spike": spike["guard"]},
              "registration": {"newCommands": [], "existingSurface": "cua.* / cua_*_command / HTTP /api/ui/cua / MCP",
                               "workspace": "neyvia_workspace_tools imports CUA_DEFINITIONS",
                               "bridge": "desktop_bridge imports CUA_COMMANDS; existing Tauri generic forwarder",
                               "explicitProofPort": preview.get("port"), "harnessSpecBound": preview.get("mcp", {}).get("harnessSpecBound")},
              "limitations": limitations}
    # These existing frontend files use Git's LF normalization. Record both
    # the actual runtime bytes and their unchanged repository blob bytes.
    normalized = [p for p in SOURCES if p.startswith("web/")]
    report["sourceGitBlobSha256"] = {p: hashlib.sha256((ROOT / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                                      for p in normalized}
    report["sourceLineEndingNormalization"] = {"paths": normalized, "rule": "CRLF to LF only; runtime bytes remain in sourceSha256"}
    python_sources = [p for p in SOURCES if p.endswith(".py")]
    for path in python_sources:
        ast.parse((ROOT / path).read_text(encoding="utf-8-sig"), filename=path)
    report["verification"] = {"syntax": "passed", "pythonFilesParsed": len(python_sources),
                              "artifacts": {p: sha(ROOT / p) for p in ("scripts/evidence/C11-preview.png", "scripts/evidence/C11-ui.png")},
                              "artifactBoundary": "Native and rendered captures from recorded attempts; latest rendered input journey remains unproven"}
    (AREA / "C11.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "gates": gates, "cohortDispatchedP50Ms": quantile(timings, .5)}))
    return report


def run_c11c(variant="C11c"):
    names = (variant + "-cohort-final.json", variant + "-preview.json" if variant in {"C11d","C11e"} else "C11-preview.json",
             variant + "-bureau.json", variant + "-attribution.json")
    raw, receipts = {}, []
    immutable = AREA / (variant + "-runs")
    immutable.mkdir(exist_ok=True)
    historical = sorted(p.name for p in AREA.glob(variant+"-*.json") if p.name not in names) if variant in {"C11d","C11e"} else []
    for name in (*names, *historical):
        source = AREA / name
        data = source.read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        sealed = immutable / (checksum + ".json")
        if not sealed.exists():
            sealed.write_bytes(data)
        assert sealed.read_bytes() == data
        raw[name] = json.loads(data)
        receipts.append({"id": name.removesuffix(".json"), "kind": "raw", "sha256": checksum,
            "path": sealed.relative_to(ROOT).as_posix(), "originalPath": source.relative_to(ROOT).as_posix()})
    cohort, preview, bureau, attribution = (raw[n] for n in names)
    if variant in {"C11d","C11e"}:
        recorded = {r["sha256"] for r in receipts}
        for path in sorted(immutable.glob("*.json")):
            digest = sha(path)
            if path.stem != digest:
                raise ValueError("Historical receipt filename differs from exact bytes")
            if digest not in recorded:
                receipts.append({"id": variant + "-history-" + digest, "kind": "raw", "sha256": digest,
                    "path": path.relative_to(ROOT).as_posix(), "historical": True})
                recorded.add(digest)
    apps, timings = [], []
    for row in cohort["apps"]:
        sent = [a for a in row["attempts"] if a.get("actionSent")]
        timings.extend(a["atomicMs"] for a in sent)
        states = row.get("connectedLanguage", [])
        flow = row.get("learnedFlow", {})
        apps.append({"app": row["app"], "status": row["status"], "reason": row.get("reason"),
            "verifiedActions": 0 if row["status"] in {"native_process_failed","receipt_uncertified"} else sum(bool(a.get("passed")) for a in sent),
            "dispatchedAttempts": len(sent), "draftManual": bool(row.get("firstUseManual", {}).get("patchId")),
            "clSnapshotAndDiff": any(s["state"].get("mode") in {"snapshot", "handle"} for s in states)
                and any(s["state"].get("mode") == "diff" and s["state"].get("diff") for s in states),
            "compiledZeroTokenFlow": flow.get("status") == "passed" and bool(flow.get("compiledReplay"))
                and flow.get("tokens") == 0})
    completed = sum(a["verifiedActions"] == 5 and a["status"] == "passed" for a in apps)
    trials = ((names[0], cohort), (names[1], preview))
    if variant in {"C11d","C11e"}:
        trials += ((names[2], bureau),)
        if variant+"-parked.json" in raw:
            trials += ((variant+"-parked.json", raw[variant+"-parked.json"]),)
    drift = {name: [p for p, digest in trial.get("sourceSha256", {}).items() if sha(ROOT / p) != digest]
             for name, trial in trials}
    gates = {"all22AppsReported": len(apps) == 22,
        "atLeast15AppsWithFiveVerifiedActions": completed >= 15,
        "atLeast15DraftManuals": sum(a["draftManual"] for a in apps) >= 15,
        "atLeast15ClSnapshotsAndDiffs": sum(a["clSnapshotAndDiff"] for a in apps) >= 15,
        "atLeast15CompiledZeroTokenFlows": sum(a["compiledZeroTokenFlow"] for a in apps) >= 15,
        "dispatchedActionP50Under150Ms": bool(timings) and quantile(timings, .5) < 150,
        "renderedRightPaneForwardedInput": bool(preview.get("renderedPreview", {}).get("ok")),
        "previewNativeHttpMcpFlow": bool(preview.get("engineJourneyPassed", preview.get("ok"))),
        "bureauHiddenMembershipAndBrokerLaunch": bool(bureau.get("success")),
        "attributionGuardPolicy": bool(attribution.get("ok")),
        "zeroAttributedDisturbance": bool(cohort["guardAfter"]["ok"] and preview.get("guard", {}).get("ok")
            and bureau.get("guard", {}).get("ok")),
        "cohortAndPreviewCurrentSourceBound": all(not paths for paths in drift.values())}
    if variant in {"C11d","C11e"}:
        gates.pop("bureauHiddenMembershipAndBrokerLaunch")
        gates.pop("attributionGuardPolicy")
        gates["bureauHiddenMembership"] = bool(bureau.get("success") and bureau.get("membershipVerified"))
        gates["brokerOwnershipBeforeVisibility"] = bool(bureau.get("brokerGate", {}).get("previsibilityOwned"))
        gates["realInputDesktopObserver"] = bool(attribution.get("ok") and attribution.get("final", {}).get("input_hooks_installed"))
        gates["bureauLifecycleAndCleanup"] = bool(bureau.get("lifecycleWorks") and bureau.get("bureauCleanup", {}).get("removed"))
        gates["nativePrevisibilityContainment"] = bool(raw.get(variant+"-parked.json", {}).get("success"))
        if variant=="C11e":
            frozen=json.loads((AREA/'C1-tasks.json').read_text(encoding='utf-8'))
            expanded=json.loads((AREA/'C11e-tasks.json').read_text(encoding='utf-8'))
            gates['all22AppsReported']=len(apps)>=22 and [a['app'] for a in apps[:22]]==[a['app'] for a in frozen['apps']]
            gates['frozen22TasksUnchanged']=expanded['apps'][:22]==frozen['apps'] and expanded['frozenManifestSha256']==sha(AREA/'C1-tasks.json')
            gates['publicDisposableTargetLaunchBound']=bool(preview.get('publicFixtureBinding'))
            gates['successfulAppsFirstObservationUnder500Ms']=bool(completed) and all(
                row.get('firstObservationMs',500)>=0 and row.get('firstObservationMs',500)<500
                for row in cohort['apps'] if row.get('status')=='passed' and row.get('passed')==5)
    extra_sources = ("src/grant_agent/cua_bureau.py", "src/grant_agent/cua_parked.py",
        "scripts/prove_c11_bureau.py", "scripts/prove_c11_parked.py", "scripts/c11_cohort_learning.py",
        "scripts/verify_cua_guard_attribution.py", "scripts/setup_c11_bureau.ps1", "scripts/build_c11_parked.ps1",
        "tools/cua-driver-win/parked-hook.cpp", "tools/cua-driver-win/parked-probe.cpp",
        "manuals/computer-use.manual.json", "manuals/cl/computer-use.cl")
    sources = tuple(dict.fromkeys((*SOURCES, *extra_sources,
        *(("scripts/prove_c11e_bureau_app.py",) if variant == "C11e" else ()),
        *(p for _, trial in trials for p in trial.get("sourceSha256", {})))))
    syntax_files = [p for p in sources if p.endswith(".py")]
    for p in syntax_files:
        ast.parse((ROOT / p).read_text(encoding="utf-8-sig"), filename=p)
    limitations = [
        "Only independently verified completed tasks count; refused and uncertain actions remain failures. No union of different trials is presented as one successful cohort.",
        "Bureau lifecycle works without switching desktops, but hidden HWND membership fails on Windows 26200.9457. No show/activation was attempted.",
        "The external window guard treats DWM-cloaked WS_VISIBLE windows as violations. A coordinated cloak-aware lifecycle is required before trying compositing-only show; broker ownership before visibility remains unresolved.",
        "Preview is one disposable native fixture in the actual NxShell; it does not establish universal app coverage. Public trees and services were untouched.",
        "Latency covers dispatched frozen actions and their fresh observation/readback, including dispatched failures; startup, compilation and read-only no-action observations are separate.",
        "Bureau and passive attribution diagnostics lack original full source manifests; their exact raw bytes are sealed, not retroactively source-bound."]
    if variant in {"C11d","C11e"}:
        limitations = [
            "C11 and C1 remain incomplete while any declared gate is unmet. Refusals and uncertain actions remain failures.",
            "Current scores come from one full frozen22 run; targeted trials are retained separately and never unioned into a cohort.",
            "Owned in-process DWM cloak, zero-opacity and minimized registration probes fail shell membership on Windows 26200.9457. Production launch does not enable these opt-in diagnostics.",
            "Broker and singleton routes remain refused before activation; previsibility AppContainer/RuntimeBroker ownership is unproven. Microsoft documents the global-hook restriction for Store/RuntimeBroker processes without UIAccess (https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowshookexw).",
            "Preview proves one disposable native fixture through the real NxShell/HTTP/MCP path, not universal app coverage or C8 inception.",
            "Timing includes failed action calls plus fresh inspect/readback; startup, no-action observations and additional compiled-flow replays are separate.",
            "Earlier exploratory receipts are exact-byte archives, not current-source-bound trials. The final cohort, preview and Bureau manifests are checked against current source.",
            "Passive attribution proof executes no synthetic policy cases; real native refusals and app journeys provide the runtime boundary."]
        limitations.append("Native UIA access violations occurred in earlier in-process panels. The final panel isolates each app in a child process under one continuous lead guard; uncertified child results cannot count as completed tasks.")
        if variant=="C11e":
            limitations[1]=f"One full {len(apps)}-app panel retains the exact frozen 22 tasks and adds installed apps. MMC utilities share a host executable; they are distinct snap-ins, not independent application families. Earlier subsets are retained separately and never unioned into the final score."
            limitations[2]="Cloak, zero-opacity, offscreen and successful Shell-collection refresh diagnostics still failed membership on Windows 26200.9457. The opt-in registration diagnostics are not enabled by production launch."
    artifacts = {}
    child_artifacts = []
    if variant in {"C11d","C11e"}:
        for row in cohort["apps"]:
            for kind in ("receipt", "log"):
                original = row.get("childProcess", {}).get(kind)
                if not original:
                    continue
                path = (ROOT / original).resolve()
                if not path.is_relative_to(ROOT / ".agent_control/c11-cohort"):
                    raise ValueError("Child evidence escaped its task-local directory")
                if not path.exists():
                    child_artifacts.append({"app": row["app"], "kind": kind, "missing": True})
                    continue
                data = path.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                target = immutable / (digest + path.suffix)
                if not target.exists():
                    target.write_bytes(data)
                assert target.read_bytes() == data
                child_artifacts.append({"app": row["app"], "kind": kind, "sha256": digest,
                    "path": target.relative_to(ROOT).as_posix(), "originalPath": original})
        captures = [preview.get("finalFrame", {}).get("file"), preview.get("renderedPreview", {}).get("screenshot")]
        for p in captures:
            if p:
                artifacts[Path(p).as_posix()] = sha(ROOT / p)
    else:
        artifacts = {p: sha(ROOT / p) for p in ("scripts/evidence/C11-preview.png", "scripts/evidence/C11-ui.png")}
    report = {"schema": "neyvia." + variant.lower() + ".result.v1", "at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if all(gates.values()) else "partial", "complete": all(gates.values()), "gates": gates,
        "receipts": receipts, "sourceSha256": {p: sha(ROOT / p) for p in sources}, "runSourceDrift": drift,
        "cohort": {"reportedApps": len(apps), "appsWithFiveVerifiedActions": completed,
            "verifiedActions": sum(a["verifiedActions"] for a in apps), "dispatchedAttempts": len(timings),
            "draftManuals": sum(a["draftManual"] for a in apps),
            "clSnapshotsAndDiffs": sum(a["clSnapshotAndDiff"] for a in apps),
            "compiledZeroTokenFlows": sum(a["compiledZeroTokenFlow"] for a in apps),
            "actionP50Ms": quantile(timings, .5), "actionP95Ms": quantile(timings, .95), "apps": apps},
        "preview": {k: preview.get(k) for k in ("ok", "engineJourneyPassed", "error", "learning", "clState", "forwardedInput", "stream", "renderedPreview", "unlockVerified", "fixtureOwnership", "publicFixtureBinding", "staleFrameRefused", "changedControlRefused")},
        "bureau": {k: bureau.get(k) for k in ("success", "windowsBuild", "lifecycleWorks", "assignmentError", "documentedGuidMatches", "cloakContinuation", "brokerGate", "membershipVerified", "bureauCleanup")},
        "zeroDisturbance": {"cohort": cohort["guardAfter"], "preview": preview.get("guard"), "bureau": bureau.get("guard")},
        "childArtifacts": child_artifacts,
        "verification": {"syntax": "passed", "pythonFilesParsed": len(syntax_files),
            "captures": artifacts},
        "limitations": limitations}
    report["sourceGitBlobSha256"], normalized = git_blob_hashes(sources)
    report["sourceLineEndingNormalization"] = {"paths": normalized,
        "rule": "Git text/eol attributes and core.autocrlf; CRLF to LF only. Exact runtime bytes remain sourceSha256."}
    (AREA / (variant + ".json")).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "gates": gates,
        "cohort": {k: v for k, v in report["cohort"].items() if k != "apps"}}, ensure_ascii=False))
    return report


def record_c11c(report, variant="C11c"):
    from efficiency_log import append
    cohort = json.loads((AREA / (variant + "-cohort-final.json")).read_text(encoding="utf-8"))
    samples = [{"receipt": variant + "-cohort-final", "pointer": f"/apps/{i}/attempts",
                "where": {"/actionSent": True}, "field": "/atomicMs"}
               for i, row in enumerate(cohort["apps"]) if any(a.get("actionSent") for a in row["attempts"])]
    ci = {"method": "not-estimable", "reason": "One frozen task per installed app; this panel does not establish a population guarantee"}
    metrics = [{"name": "installed_dispatched_atomic_p50", "unit": "ms",
                "calculation": {"op": "quantile", "args": [samples, .5]}, "ci_request": ci}]
    metrics.extend({"name": name, "unit": "events", "calculation": {
        "receipt": variant + "-cohort-final", "pointer": "/guardAfter/" + name}, "ci_request": ci}
        for name in ("new_visible_windows", "foreground_changes", "injected_mouse_events", "injected_keyboard_events"))
    row = append({"schema": "neyvia.efficiency-result.v1", "id": variant + "-" + cohort["runId"],
        "study": variant + " attributed private-desktop tasks, hidden Bureau frontier and rendered preview",
        "method": "Frozen real disposable tasks, production native readback/CL/manual compiler, actual NxShell HTTP/MCP/SSE forwarding; LL input hooks and agent-process attribution; every refusal retained",
        "models": ["No model in measured native action path"],
        "tasks": {"description": (f"{report['cohort']['reportedApps']} installed-app tasks preserving the frozen 22 and a separate disposable native preview fixture" if variant == "C11e" else "22 installed-app frozen tasks and a separate disposable native preview fixture"),
            "repetitions": 5, "independent_unit": "one task per installed app"},
        "limitations": report["limitations"], "evidence_status": "raw-verified",
        "receipts": [{k: r[k] for k in ("id", "path", "sha256", "kind")} for r in report["receipts"]],
        "metrics": metrics}, report=None)
    print(json.dumps({"ledgerAppended": row["id"], "metrics": len(row["metrics"])}))


def record(report):
    from efficiency_log import append
    cohort = json.loads((AREA / "C11-cohort-full.json").read_text(encoding="utf-8"))
    samples = [{"receipt": "C11-cohort-full", "pointer": f"/apps/{index}/attempts",
                "where": {"/actionSent": True}, "field": "/atomicMs"}
               for index, row in enumerate(cohort["apps"]) if any(a.get("actionSent") for a in row["attempts"])]
    ci = {"method": "not-estimable", "reason": "Only one installed app completed five actions; fixture repetitions do not establish a population guarantee"}
    metrics = [{"name": "installed_dispatched_atomic_p50", "unit": "ms",
                "calculation": {"op": "quantile", "args": [samples, .5]}, "ci_request": ci},
               {"name": "native_fixture_atomic_p50", "unit": "ms",
                "calculation": {"op": "median", "args": [{"receipt": "C11-spike", "pointer": "/apps/0/actions", "field": "/roundTripMs"}]}, "ci_request": ci}]
    metrics.extend({"name": "cohort_" + name, "unit": "events", "calculation": {
        "receipt": "C11-cohort-full", "pointer": "/guardAfter/" + name}, "ci_request": ci}
        for name in ("new_visible_windows", "foreground_changes", "cursor_moves"))
    specification = {"schema": "neyvia.efficiency-result.v1", "id": "C11-private-desktop-2026-10-04",
                     "study": "C11 real private-desktop mechanism; C1 and rendered-input completion blocked",
                     "method": "Private CreateDesktop/job launches, bound UIA/MSAA/capture lanes, fresh native actions and app-written effects; strict hooks plus input-desktop samples. Every failure retained; dispatched-only timing independently recomputed.",
                     "models": ["No model in measured native action path; configured T18 failures reported separately"],
                     "tasks": {"description": "Frozen 22 installed-app tasks plus a real disposable WinForms workflow and owner-authenticated HTTP/MCP/SSE preview attempts",
                               "repetitions": 5, "independent_unit": "one task per installed app; only one app completed; one separate native fixture"},
                     "limitations": report["limitations"] + ["Final source-bound rendered input rerun was blocked before GUI launch by continuous physical/unattributed input; earlier successful HTTP/native runs predate the final input repairs."],
                     "evidence_status": "raw-verified", "receipts": [{k: r[k] for k in ("id", "path", "sha256", "kind")} for r in report["receipts"]],
                     "metrics": metrics}
    row = append(specification, report=None)
    print(json.dumps({"ledgerAppended": row["id"], "metrics": len(row["metrics"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="Append the receipt-backed partial result to the existing research ledger")
    parser.add_argument("--c11c", action="store_true", help="Seal the current attributed cohort, preview and Bureau frontier")
    parser.add_argument("--c11d", action="store_true", help="Seal the owned invisible-registration continuation and its current-source runs")
    parser.add_argument("--c11e", action="store_true", help="Seal disposable targets, expanded frozen cohort and isolation frontiers")
    args = parser.parse_args()
    variant = "C11e" if args.c11e else "C11d" if args.c11d else "C11c"
    report = run_c11c(variant) if args.c11c or args.c11d or args.c11e else run()
    if args.record:
        if args.c11c or args.c11d or args.c11e:
            record_c11c(report, variant)
        else:
            record(report)
