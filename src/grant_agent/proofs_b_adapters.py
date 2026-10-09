"""Action contracts and bounded real procedures for the PROOFS-b adapter chapter.

No provider impersonation: local manifests, files and Git objects are the
observed boundary. A separately prepared pinned Syncthing provides native local
configuration proof. OCR checks prove text repair, never an OCR model invocation.
"""
from __future__ import annotations

from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proof_ports import proof_port, proof_text

import functools
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict
from pathlib import Path


CONTRACTS = (
    "adapters.release.selection", "adapters.release.update", "adapters.release.staging",
    "adapters.git.objects", "adapters.git.safety", "adapters.ocr.boundaries",
    "adapters.handoff.progress", "adapters.comparison.grading", "adapters.comparison.leader",
    "adapters.html.scoring", "adapters.workflow.publication", "adapters.sync.compatibility",
    "adapters.git.readiness", "adapters.git.artifact-registration",
    "adapters.sync.policy",
    "adapters.sync.native-runtime", "adapters.sync.plan-activation",
    "adapters.sync.stale", "adapters.sync.rollback", "adapters.sync.recovery",
    "adapters.sync.discovery",
)
FRONTIER = [
    "Syncthing detailed health/cache/events, route/error summaries, per-folder status soft degradation and structured endpoint-unavailable behavior remain unproven and partly absent from production. Native proofs cover one isolated local service; no remote device synchronization is claimed.",
    "GLM redesign jobs, changed UI artifact verification and OpenClaw reply/handoff paths require the real selected provider; no provider is substituted.",
    "The repository Git manifest declares a launcher pin and typed object operations, but no production workflow admission; scratch pinning proves local registration/readiness without changing that manifest. Concurrent mutation/deadline and unavailable symlink creation remain uncovered.",
    "Local HTTP protocol specimens prove 429 uncertainty and premature EOF rejection; actual GitHub connectivity/publication remains unobserved.",
    "HTML scoring proves a static rubric and browser score gate; rendering, keyboard behavior, mobile overflow and visual quality remain separate browser evidence.",
    "Harness comparison checks score existing observations; they do not prove any provider produced those observations.",
]


def require(ok, contract, detail):
    if not ok:
        raise ValueError(f"Contract {contract}: {detail}")


def checked(kind):
    """Evaluate the named postcondition on every successful real action."""
    def decorate(fn):
        signature = inspect.signature(fn)
        @functools.wraps(fn)
        def action(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            result = fn(*args, **kwargs)
            check_result(kind, bound.arguments, result)
            return result
        return action
    return decorate


def check_result(kind, a, result):
    if kind == "reference":
        text = str(a["value"] or "").strip()
        if result is not None:
            require(all(part and all(c.isalnum() or c in "-_." for c in part) for part in (result.owner, result.repo)), CONTRACTS[0], "invalid repository name accepted")
            require(not ("://" in text or "@" in text) or text.startswith(("https://github.com/", "http://github.com/", "git@github.com:")), CONTRACTS[0], "non GitHub host accepted")
    elif kind == "version":
        text = str(a["value"] or "").strip()
        require(result == (text[1:] if text[:1].lower() == "v" and text[1:2].isdigit() else text), CONTRACTS[0], "version normalization differs")
    elif kind == "platform":
        if result is not None:
            require(result in a["release"].get("assets", []) and a["platform_tag"].strip().casefold() in str(result.get("name") or "").casefold(), CONTRACTS[0], "platform asset differs")
    elif kind == "checksum":
        if result is not None:
            name = str(a["asset"].get("name") or "")
            require(result in a["release"].get("assets", []) and result.get("name") in {name + ".sha256", name + ".sha256sum", "checksums.txt", "SHA256SUMS"}, CONTRACTS[0], "checksum sidecar differs")
    elif kind == "selection":
        if result is not None:
            require(result in a["releases"] and not result.get("draft"), CONTRACTS[0], "unpublished release offered")
            require(a["channel"] == "beta" or not result.get("prerelease"), CONTRACTS[0], "prerelease offered as stable")
            if a["version"]:
                require(str(result.get("tag_name", "")).lstrip("vV") == str(a["version"]).lstrip("vV"), CONTRACTS[0], "wrong requested version")
    elif kind == "update":
        require(result["state"] in {"current", "update_available", "unknown"}, CONTRACTS[1], "unrecognized observation state")
        require(result.get("downloadedBytes", 0) == 0, CONTRACTS[1], "metadata check downloaded a package")
        if result["state"] != "unknown":
            from .github_release_source import compare_versions
            relation = compare_versions(a["installed_version"], result["latestVersion"])
            require(relation is not None, CONTRACTS[1], "unknown version ordering represented as certain")
            require((relation >= 0) == (result["state"] == "current"), CONTRACTS[1], "update/downgrade state contradicts version relation")
            if result["state"] == "update_available" and a["platform_tag"]:
                require(result.get("asset") is not None, CONTRACTS[1], "platform has no installable asset")
    elif kind == "staging":
        target = Path(a["destination"])
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        require(digest == result["sha256"] and target.stat().st_size == result["bytes"], CONTRACTS[2], "staged bytes differ from receipt")
        expected = a["expected_sha256"]
        require(result["verified"] is bool(expected), CONTRACTS[2], "checksum authority label incorrect")
        if expected:
            require(digest.casefold() == expected.strip().casefold(), CONTRACTS[2], "publisher checksum differs")
        require(bool(result["warning"]) == (isinstance(a["asset"].get("size"), int) and a["asset"]["size"] != result["bytes"]), CONTRACTS[2], "declared byte mismatch warning missing")
    elif kind == "git":
        root = a["self"].root
        receipt = result["receipt"]
        path = (root / receipt["path"]).resolve()
        path.relative_to(root.resolve())
        raw = path.read_bytes()
        observed = json.loads(raw)
        require(hashlib.sha256(raw).hexdigest() == receipt["sha256"], CONTRACTS[3], "receipt byte digest differs")
        require(observed["lineage"]["sources"][0]["head"] == result["head"], CONTRACTS[3], "HEAD lineage differs")
        require(observed["resultHash"] == result["artifacts"][0]["derivedFrom"], CONTRACTS[3], "output lineage differs")
        require(result["networkAccessed"] is False and result["policy"]["network"] == "denied", CONTRACTS[4], "network scope escaped")
        require(result["consistency"]["before"] == result["consistency"]["after"], CONTRACTS[4], "unstable object observation accepted")
    elif kind.startswith("ocr-"):
        original = a["value"]
        text, evidence = result
        if evidence is None:
            require(text == original, CONTRACTS[5], "unproven repair changed text")
            return
        require(evidence["applied"] is True and text in original and evidence["removedCharacters"] == len(original) - len(text), CONTRACTS[5], "repair evidence disagrees with bytes")
        if kind == "ocr-renderer":
            before, after = original.split("\n```markdown\n", 1)
            repeated = after.lstrip()[:128]
            require(text == before.strip() and len(repeated) >= 32 and text.startswith(repeated), CONTRACTS[5], "renderer discarded genuine markdown")
        elif kind == "ocr-table":
            require(text.startswith("<table") and text.endswith("</table>") and "<tr" in text and "<td" in text, CONTRACTS[5], "incomplete table was repaired")
        else:
            first_end = original.find("$$", original.find("$$") + 2) + 2
            require(text.startswith("$$") and text.endswith("$$") and original[first_end:].strip().startswith(text), CONTRACTS[5], "nonduplicate formula discarded")
    elif kind == "handoff":
        state = a["state"]
        require(result.session_id == a["session_id"] and result.parent_session_id == a["parent_session_id"], CONTRACTS[6], "session identity lost")
        require(result.progress["completed_steps"] == state.completed_steps and result.progress["remaining_steps"] == [s for s in state.plan_steps if s not in state.completed_steps], CONTRACTS[6], "remaining progress differs")
        require(result.objective == state.objective and result.next_actions == state.next_actions and result.prompt_stack == asdict(a["prompt_stack"]), CONTRACTS[6], "resume authority or prompt differs")
    elif kind == "grade":
        from .harness_comparison import task_by_id
        expected = task_by_id(a["task_id"])["expected"]
        parsed = result["parsed"]
        matches = {key: bool(parsed is not None and parsed.get(key) == value) for key, value in expected.items()}
        require(result["checks"] == matches and result["points"] == sum(matches.values()) and result["maxPoints"] == len(expected) and result["correct"] == all(matches.values()), CONTRACTS[7], "protocol field scores differ")
    elif kind == "eligibility":
        h = a["harness"]
        eligible = bool(not h.get("securityOnly") and h.get("installed") and h.get("detected") and str(h.get("readiness") or "").strip().lower() not in {"provider-setup-required", "provider-unverified", "blocked", "not-installed"})
        require(result[0] is eligible and bool(result[1]), CONTRACTS[8], "candidate readiness differs")
    elif kind == "capabilities":
        require(result["count"] == len(result["supported"]) and 0 <= result["count"] <= result["total"], CONTRACTS[8], "coverage cardinality differs")
    elif kind == "summaries":
        import statistics
        for summary in result:
            attempts = [r for r in a["attempts"] if str(r.get("harnessId") or "") == summary["harnessId"]]
            measured = [int((r.get("metrics") or {}).get("executionDurationMs")) for r in attempts if isinstance((r.get("metrics") or {}).get("executionDurationMs"), (int, float)) and (r.get("metrics") or {})["executionDurationMs"] >= 0]
            require(summary["attemptCount"] == len(attempts) and summary["medianExecutionMs"] == (round(statistics.median(measured)) if measured else None), CONTRACTS[8], "attempt count or execution latency lost")
    elif kind == "leader":
        candidates = [r for r in a["summaries"] if r.get("eligible") and r.get("attemptCount") == r.get("expectedAttemptCount") and all(r.get(k) == 100 for k in ("correctnessRate", "completionRate", "receiptCoverage", "routeIntegrity", "readOnlyCoverage"))]
        if not candidates:
            require(result["status"] == "inconclusive" and result["harnessId"] is None, CONTRACTS[8], "unmeasured candidate won")
        else:
            selected = next((r for r in candidates if r["harnessId"] == result["harnessId"]), None)
            require(selected is not None and selected["capabilityCoverage"]["count"] == max(r["capabilityCoverage"]["count"] for r in candidates), CONTRACTS[8], "incomplete or lower coverage candidate won")
    elif kind == "html":
        from .html_site_benchmark import FROZEN_PROMPT
        require(all(s in FROZEN_PROMPT for s in ("index.html", "no external", "390px")), CONTRACTS[9], "frozen benchmark requirements changed")
        require(result["maximum"] == 80 and 0 <= result["score"] <= 80, CONTRACTS[9], "static score exceeds rubric")
        require(result["score"] == sum(c["points"] for c in result["checks"]), CONTRACTS[9], "score disagrees with check ledger")
        require(all(c["points"] == (c["maximum"] if c["passed"] else 0) for c in result["checks"]), CONTRACTS[9], "failed check contributed points")
    elif kind == "html-combined":
        require(result["score"] == int(a["static"].get("score") or 0) + int(a["browser"].get("score") or 0), CONTRACTS[9], "combined score differs")
        require(result["passed"] == (result["score"] >= 75 and int(a["browser"].get("score") or 0) >= 12), CONTRACTS[9], "static score bypassed browser gate")
    elif kind == "sync-discovery":
        payload = a["payload"]
        tool_id = str(payload.get("toolId") or payload.get("tool_id") or "").strip().lower()
        operation_id = str(payload.get("operationId") or payload.get("operation_id") or "").strip().lower()
        if (tool_id, operation_id) != ("tool.neyvia-folder-sync", "sync.compatibility"):
            return
        contract = "adapters.sync.discovery"
        require(result["toolId"] == tool_id and result["operationId"] == operation_id,
                contract, "typed operation receipt differs from requested identity")
        if result.get("ok") is True:
            from .capability_contracts import canonical_hash
            tool = a["self"].tool_manifests.tools[tool_id]
            operation = next(row for row in tool.operations if row.operation_id == operation_id)
            selected = str(payload.get("capabilityId") or operation.metadata.get("capabilityId") or "").strip().lower()
            expected_capability = selected or (tool.capabilities[0] if tool.capabilities else f"tool.{operation_id}")
            require(result["capabilityId"] == expected_capability
                    and result["toolReceipt"]["toolManifestHash"] == canonical_hash(tool.as_dict(include_operations=True))
                    and result["result"]["transport"]["credentialsExposed"] is False,
                    contract, "typed capability binding or secret boundary differs")
    elif kind == "sync-plan":
        service = a["self"]
        require(result["desiredFolder"]["paused"] is True and result["summary"]["appliesDataChanges"] is False,
                "adapters.sync.plan-activation", "planning enabled data movement")
        require(result["planHash"] == service._plan_hash(result)
                and json.loads((service.plan_root / (result["planId"] + ".json")).read_bytes()) == result,
                "adapters.sync.plan-activation", "persisted plan differs from returned authority")
    elif kind in {"sync-apply", "sync-activation", "sync-recovery"}:
        contract = {"sync-apply": "adapters.sync.plan-activation", "sync-activation": "adapters.sync.plan-activation", "sync-recovery": "adapters.sync.recovery"}[kind]
        admitted = bool(a["approved"])
        if kind == "sync-activation":
            admitted = admitted and bool(a["approved_deletion_propagation"])
        elif kind == "sync-recovery":
            admitted = admitted and str(a["confirmation"]) == str(a["folder_id"])
        if not admitted:
            require(result["ok"] is False and result["status"] == "approval_required", contract, "action bypassed approval")
            return
        if result["status"] == "stale_plan":
            require(kind == "sync-apply" and result["ok"] is False and result["expectedBaseStateHash"] != result["actualBaseStateHash"],
                    "adapters.sync.stale", "stale refusal lacks changed authority")
            return
        persisted = a["self"].receipt_root / (result["receiptId"] + ".json")
        require(json.loads(persisted.read_bytes()) == result and result["ok"] is True and result["credentialsExposed"] is False,
                contract, "action receipt differs from persisted observation")
        detail = result["details"]
        if kind == "sync-apply":
            require(result["status"] == "configured_paused" and detail["activationRequired"] is True
                    and detail["dataMovementStarted"] is False and detail["planHash"] == a["plan"]["planHash"], contract, "apply lost paused plan authority")
        elif kind == "sync-activation":
            require(result["status"] == "active" and detail["deletionPropagationApproved"] is True, contract, "activation lost deletion approval")
        else:
            require(result["status"] == a["action"] + "_requested" and detail["mode"] == a["required_type"]
                    and detail["exactFolderConfirmation"] is True, contract, "recovery authority differs")
    elif kind == "sync-restore":
        service = a["self"]
        if a["folder"] is None:
            folders = service._request("GET", "/rest/config/folders")
            require(all(item.get("id") != a["folder_id"] for item in folders), "adapters.sync.rollback", "failed creation survived rollback")
        else:
            restored = service._folder_config(a["folder_id"])
            ignores = service._request("GET", "/rest/db/ignores", query={"folder": a["folder_id"]})
            require(all(restored.get(key) == value for key, value in a["folder"].items())
                    and ignores.get("ignore", []) == a["ignores"], "adapters.sync.rollback", "previous relationship differs after rollback")
    elif kind == "sync-path":
        allowed = a["self"]._allowed_roots()
        require(result == result.resolve() and any(result.is_relative_to(path) for path in allowed),
                "adapters.sync.policy", "accepted folder escaped configured roots")
    elif kind == "sync-versioning":
        policy = a["self"].policy
        choice = result.get("type", "")
        allowed = set(policy.get("versioningTypes") or [])
        require(not choice or choice in allowed, "adapters.sync.policy", "unsupported versioner accepted")
        require(a["folder_type"] not in set(policy.get("inboundVersioningRequiredFor") or []) or choice in allowed,
                "adapters.sync.policy", "inbound folder lost required versioning")
    elif kind == "sync-ignores":
        require(len(result) == len(set(result)) and not any(line.lstrip().casefold().startswith("#include") for line in result),
                "adapters.sync.policy", "ignore normalization accepted recursive includes")
    elif kind == "sync":
        binary = result["binary"]
        require(binary["hashVerified"] is bool(binary["installed"] and binary["expectedSha256"] and binary["actualSha256"] == binary["expectedSha256"]), CONTRACTS[11], "binary identity guessed")
        require(result["transport"]["credentialsExposed"] is False and not any(k in result["transport"] for k in ("apiKey", "token", "password")), CONTRACTS[11], "credential escaped public compatibility")
    elif kind == "readiness":
        runtime = a["runtime_readiness"] or {}
        blocked = result["blockedPrerequisites"]
        execution = bool(runtime.get("evaluated") and runtime.get("ready") and a["self"].contract_ready and not any("execution" in r.get("requiredFor", []) for r in blocked))
        production = bool(execution and a["self"].readiness.get("productionValidated") and not any("production" in r.get("requiredFor", []) for r in blocked))
        require(result["executionReady"] is execution and result["productionReady"] is production and result["executionReadinessEvaluated"] is bool(runtime.get("evaluated")), CONTRACTS[12], "runtime readiness bypassed prerequisites")
    elif kind == "registration":
        for item in result["artifacts"]:
            metadata = item["metadata"]
            declared = metadata.get("declaredSha256")
            if declared:
                require(item["sha256"] == declared, CONTRACTS[13], "registered artifact digest differs")
            if metadata["role"] == "git-reference-receipt":
                require(bool(metadata["derivedFrom"]), CONTRACTS[13], "registered Git receipt has no lineage")


def _verified_native_executable(executable):
    expected = "36a0f7bc372f64fa7cc4f5654fa324c0dd9f7fef2e07565e00c6e1cf73f50344"
    require(executable.is_file(), "adapters.sync.native-runtime", "task-local Syncthing missing; preparation required, no automatic download")
    require(hashlib.sha256(executable.read_bytes()).hexdigest() == expected, "adapters.sync.native-runtime", "task-local executable pin differs")
    return expected


NATIVE_SYNC_CONTRACTS = ("adapters.sync.native-runtime", "adapters.sync.plan-activation", "adapters.sync.stale",
                         "adapters.sync.rollback", "adapters.sync.recovery", "adapters.sync.discovery")


def native_sync_executable(repository):
    """The separately prepared, hash-pinned Syncthing binary for native proofs.

    Task-local by default; NEYVIA_PROOF_SYNCTHING_EXE may name an explicitly
    prepared copy elsewhere. Either way the pin below is verified before use.
    """
    override = os.environ.get("NEYVIA_PROOF_SYNCTHING_EXE", "").strip()
    if override:
        return Path(override)
    return Path(repository) / ".agent_control/proofs-b/native-syncthing/syncthing-windows-amd64-v2.1.5/syncthing.exe"


def _native_sync_check(repository, scratch_root):
    """Observe a pinned native service with isolated files and explicit ports.

    The executable must be prepared separately. Startup never downloads it and
    never reads generated configuration, certificate or key files.
    """
    import secrets
    import urllib.error
    import urllib.request
    from .folder_sync import FolderSyncService
    from .capability_service import CapabilityService

    contract = "adapters.sync.native-runtime"
    executable = native_sync_executable(repository)
    expected = _verified_native_executable(executable)
    # The binary is a verified read-only task dependency. All mutable native
    # state belongs to this particular verification's already-isolated root.
    root = scratch_root / "native-sync"
    home = root / "native-home"
    home.mkdir(parents=True)
    # This owned seed is written before Syncthing generates its configuration.
    # After generate, no configuration/key/certificate file is read by this code.
    (home / "config.xml").write_text(proof_text('''<configuration version="52">
<gui enabled="true" tls="false"><address>127.0.0.1:48473</address></gui>
<options><listenAddress>tcp://127.0.0.1:48474</listenAddress>
<globalAnnounceEnabled>false</globalAnnounceEnabled><localAnnounceEnabled>false</localAnnounceEnabled>
<localAnnouncePort>48474</localAnnouncePort><relaysEnabled>false</relaysEnabled><natEnabled>false</natEnabled>
<startBrowser>false</startBrowser><autoUpgradeIntervalH>0</autoUpgradeIntervalH><urAccepted>-1</urAccepted>
<crashReportingEnabled>false</crashReportingEnabled></options></configuration>'''), encoding="utf-8")
    key = secrets.token_hex(32)
    environment = {**os.environ, "STGUIAPIKEY": key, "GOMAXPROCS": "2"}
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    native = None
    if os.name == "nt" and os.environ.get("NEYVIA_PROOF_AGENT_DESKTOP") == "1":
        from .cua_native import NativeWorker
        native = NativeWorker()
        try:
            prepare = [str(executable), "generate", "--home", str(home), "--no-port-probing"]
            native.isolation().admit_pinned_console(prepare, expected)
            generated = native.launch(prepare, env=environment)
            if generated.wait(timeout=30) != 0:
                raise RuntimeError("Pinned native service preparation failed on agent desktop")
        except Exception:
            native.close()
            raise
    else:
        subprocess.run([str(executable), "generate", "--home", str(home), "--no-port-probing"],
                   env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=True, timeout=30, creationflags=flags)
    argv = [str(executable), "serve", "--home", str(home), "--gui-address", proof_text("127.0.0.1:48473"),
            "--no-port-probing", "--no-browser", "--no-console", "--no-restart", "--no-upgrade", "--log-level", "ERROR"]
    try:
        if native:
            native.desktop.admit_pinned_console(argv, expected)
        process = native.launch(argv, env=environment) if native else subprocess.Popen(argv,
            env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    except Exception:
        if native:
            native.close()
        raise
    checks, rejections = [], []
    receipt = {"executableSha256": expected, "guiPort": proof_port(48473), "tcpPort": proof_port(48474), "pid": process.pid,
               "boundary": "actual isolated Syncthing REST/configuration actions; no remote device or provider", "checks": checks, "rejections": rejections}

    def request(path, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(proof_text("http://127.0.0.1:48473") + path, data=data, method=method,
                                     headers={"X-API-Key": key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as response:
            raw = response.read()
        return json.loads(raw) if raw else None

    def record(identity, **details):
        checks.append({"contract": identity, **details})

    def rejected(fn, exception, identity):
        try:
            fn()
        except exception:
            rejections.append({"contract": identity, "exception": exception.__name__})
        else:
            require(False, identity, "unsafe action accepted")

    try:
        rejected(lambda: _verified_native_executable(root / "missing.exe"), ValueError, contract)
        mismatch = root / "mismatched-native-pin.specimen"
        mismatch.write_bytes(b"not the authorized executable")
        rejected(lambda: _verified_native_executable(mismatch), ValueError, contract)
        deadline = time.monotonic() + 30
        while True:
            require(process.poll() is None, contract, "owned service exited before startup")
            try:
                status = request("/rest/system/status")
                break
            except (OSError, urllib.error.URLError):
                require(time.monotonic() < deadline, contract, "owned service startup exceeded budget")
                time.sleep(0.1)
        options = request("/rest/config/options")
        require(options["listenAddresses"] == [proof_text("tcp://127.0.0.1:48474")]
                and all(options[name] is False for name in ("globalAnnounceEnabled", "localAnnounceEnabled", "relaysEnabled", "natEnabled", "startBrowser", "crashReportingEnabled"))
                and options["autoUpgradeIntervalH"] == 0, contract, "owned native service has unexpected external listeners/options")
        require(request("/rest/config/folders") == [], contract, "fresh service has preexisting folders")
        record(contract, executable=str(executable), executableSha256=expected, guiPort=proof_port(48473), tcpPort=proof_port(48474), discovery=False, relays=False, nat=False,
               missingAndMismatchedPinsRejected=True, receiptPath=str(root / "receipt.json"))
        config = {"transport": {"endpoint": proof_text("http://127.0.0.1:48473"), "apiKeyRef": "proofs:in-memory", "timeoutSeconds": 3},
                  "binary": {"installPath": str(executable), "executableSha256": expected, "version": "2.1.5"},
                  "policy": {"allowedRoots": ["${workspace}"], "folderTypes": ["sendonly", "receiveonly", "sendreceive"],
                             "versioningTypes": ["trashcan", "simple", "staggered"], "inboundVersioningRequiredFor": ["receiveonly", "sendreceive"],
                             "defaultVersioning": {"type": "staggered"}}}
        config_path = root / "config/neyvia_folder_sync.json"
        config_path.parent.mkdir()
        config_path.write_text(json.dumps(config), encoding="utf-8")
        service = FolderSyncService(root, config_path=config_path, credential_resolver=lambda _reference: key)
        shared = root / "shared"
        shared.mkdir()
        plan = service.build_folder_plan(folder_id="docs", path=shared, device_ids=[status["myID"]],
                                         label="Documents", folder_type="sendreceive", ignore_patterns=[".git", "node_modules"])
        require(plan["summary"]["versioning"] == "staggered" and plan["risk"]["deletionPropagation"] is True,
                "adapters.sync.plan-activation", "inbound plan lost versioning/risk")
        require(service.apply_folder_plan(plan)["status"] == "approval_required" and request("/rest/config/folders") == [],
                "adapters.sync.plan-activation", "unapproved configuration mutated native state")
        applied = service.apply_folder_plan(plan, approved=True)
        require(applied["status"] == "configured_paused" and request("/rest/config/folders/docs")["paused"] is True
                and request("/rest/db/ignores?folder=docs")["ignore"] == [".git", "node_modules"],
                "adapters.sync.plan-activation", "actual paused configuration/ignores differ")
        require(service.resume_folder("docs", approved=True)["status"] == "approval_required"
                and request("/rest/config/folders/docs")["paused"] is True,
                "adapters.sync.plan-activation", "missing deletion approval activated native folder")
        active = service.resume_folder("docs", approved=True, approved_deletion_propagation=True)
        require(request("/rest/config/folders/docs")["paused"] is False and key not in json.dumps(active),
                "adapters.sync.plan-activation", "native activation/readback or secret redaction differs")
        record("adapters.sync.plan-activation", planId=plan["planId"], planHash=plan["planHash"], applyReceipt=applied["receiptId"], activationReceipt=active["receiptId"], ignoredPatterns=[".git", "node_modules"], remoteDevices=0)

        stale_dir = root / "stale"
        stale_dir.mkdir()
        stale = service.build_folder_plan(folder_id="stale", path=stale_dir, device_ids=[status["myID"]])
        external = {**stale["desiredFolder"], "label": "Independent local change"}
        request("/rest/config/folders", "POST", external)
        before = request("/rest/config/folders/stale")
        refused = service.apply_folder_plan(stale, approved=True)
        require(refused["status"] == "stale_plan" and request("/rest/config/folders/stale") == before,
                "adapters.sync.stale", "stale refusal overwrote actual independent change")
        record("adapters.sync.stale", expectedBaseStateHash=refused["expectedBaseStateHash"], actualBaseStateHash=refused["actualBaseStateHash"], nativeFolderUnchanged=True)

        collision = root / "rollback"
        collision.mkdir()
        (collision / ".stignore").mkdir()
        rollback = service.build_folder_plan(folder_id="rollback", path=collision, device_ids=[status["myID"]], ignore_patterns=["*.tmp"])
        rejected(lambda: service.apply_folder_plan(rollback, approved=True), RuntimeError, "adapters.sync.rollback")
        require(all(item["id"] != "rollback" for item in request("/rest/config/folders")) and (collision / ".stignore").is_dir(),
                "adapters.sync.rollback", "real ignore-write failure left configured relationship or altered collision")
        record("adapters.sync.rollback", failure="owned .stignore directory prevents actual native ignore-file replacement", restoredAbsent=True, collisionPreserved=True)

        recovery_dir = root / "recovery"
        recovery_dir.mkdir()
        recovery = service.build_folder_plan(folder_id="recovery", path=recovery_dir, device_ids=[status["myID"]], folder_type="sendonly")
        service.apply_folder_plan(recovery, approved=True)
        service.resume_folder("recovery", approved=True, approved_deletion_propagation=True)
        require(service.override_folder("recovery", confirmation="wrong", approved=True)["status"] == "approval_required",
                "adapters.sync.recovery", "incorrect confirmation admitted")
        rejected(lambda: service.revert_folder("recovery", confirmation="recovery", approved=True), ValueError, "adapters.sync.recovery")
        deadline = time.monotonic() + 10
        while request("/rest/db/status?folder=recovery").get("state") != "idle":
            require(time.monotonic() < deadline, "adapters.sync.recovery", "native folder did not initialize within budget")
            time.sleep(0.1)
        recovered = service.override_folder("recovery", confirmation="recovery", approved=True)
        record("adapters.sync.recovery", receiptId=recovered["receiptId"], status=recovered["status"], wrongConfirmationRejected=True, wrongModeRejected=True, boundary="native override request accepted; no remote deletion or file recovery claimed")

        capability = CapabilityService(_fixture_root(root))
        discovered = capability.execute_tool_operation({"toolId": "tool.neyvia-folder-sync", "operationId": "sync.compatibility", "arguments": {}, "permissionMode": "workspace_safe"})
        require(discovered["ok"] is True and discovered["capabilityId"] == "sync.health"
                and discovered["result"]["binary"]["hashVerified"] is True and discovered["result"]["transport"]["credentialsExposed"] is False,
                "adapters.sync.discovery", "actual capability registry lost typed local compatibility operation")
        record("adapters.sync.discovery", toolId="tool.neyvia-folder-sync", operationId="sync.compatibility", capabilityId="sync.health", executableSha256=expected, boundary="typed operation and real executable hashing, no credential-file reads")
        receipt["ok"] = True
    finally:
        try:
            request("/rest/system/shutdown", "POST")
        except (OSError, urllib.error.URLError):
            pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        receipt["ownedProcessStopped"] = process.poll() is not None
        if native:
            receipt["desktop"] = native.desktop.name
            guard = native.guard
            native.close()
            receipt["guard"] = guard.close()
        (root / "receipt.json").write_bytes((json.dumps(receipt, indent=2) + "\n").encode())
        require(receipt["ownedProcessStopped"], contract, "owned native process survived cleanup")
        if native:
            require(receipt["guard"]["ok"], contract, "native service violated agent desktop containment")
    return {"checks": checks, "rejections": rejections, "receipt": str(root / "receipt.json")}


def self_check(root):
    from . import github_release_source as release
    from .git_reference_adapter import GitReferenceAdapter, GitReferenceError
    from .capability_adapters import CapabilityAdapterRegistry
    from . import harness_comparison as comparison
    from .html_site_benchmark import grade_html, combine_score, FROZEN_PROMPT
    from .handoff import create_handoff_packet, save_handoff_packet
    from .models import RunState, PromptStack, PersonaProfile
    from .context_manager import ContextWindowManager
    # Load the fixed host-owned policy file independently of the CLI's sys.path.
    # Neither a manual nor an action argument supplies this executable path.
    import importlib.util
    policy_path = Path(__file__).resolve().parents[2] / "scripts/check_workflow_publication_integrity.py"
    specification = importlib.util.spec_from_file_location("neyvia_publication_policy", policy_path)
    policy = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(policy)
    audit_workflows, LEGACY_NATIVE_BRANCH = policy.audit_workflows, policy.LEGACY_NATIVE_BRANCH
    started = time.perf_counter()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    checks, rejections = [], []
    def record(contract, **details):
        checks.append({"contract": contract, "ok": True, **details})
    def refuse(fn, exceptions, contract):
        try:
            fn()
        except exceptions as exc:
            rejections.append({"contract": contract, "rejected": True, "reason": str(exc)[:180]})
        else:
            raise ValueError(f"Contract {contract}: failure path unexpectedly succeeded")

    # Read release manifests from actual local files, then stream actual files
    # through urlopen. These are explicit file transports, never fake GitHub.
    package = root / "publisher-package.zip"
    package.write_bytes(b"PROOFS-b local publisher bytes\n")
    asset = {"name": "package-windows-x64.zip", "size": package.stat().st_size, "browser_download_url": package.as_uri()}
    stable = {"tag_name": "v2.1.0", "draft": False, "prerelease": False, "assets": [asset, {"name": asset["name"] + ".sha256"}]}
    listing = root / "publisher-releases.json"
    listing.write_text(json.dumps([{"tag_name": "v3.0.0", "draft": True}, {"tag_name": "v2.2.0-rc1", "prerelease": True}, stable]), encoding="utf-8")
    reads = []
    def local_manifest(_url, **_limits):
        reads.append(str(listing))
        return listing.read_bytes()
    for ref in ("publisher/tool", "https://github.com/publisher/tool", "https://github.com/publisher/tool.git", "git@github.com:publisher/tool.git"):
        require(release.parse_github_ref(ref).slug == "publisher/tool", CONTRACTS[0], "common reference failed")
    for ref in (None, "", "not-a-ref", "https://example.invalid/thing"):
        require(release.parse_github_ref(ref) is None, CONTRACTS[0], "non GitHub reference guessed")
    require(release.select_release(json.loads(listing.read_text())) == stable, CONTRACTS[0], "draft or beta selected")
    require(release.find_checksum_for(stable, asset)["name"].endswith(".sha256") and release.select_platform_asset(stable, platform_tag="linux-arm64") is None, CONTRACTS[0], "platform or checksum pairing differs")
    record(CONTRACTS[0], manifest=str(listing), boundary="local release metadata parsing")
    observed = []
    for installed, platform, state in (("2.0.0", "windows-x64", "update_available"), ("v2.1.0", "windows-x64", "current"), ("2.3.0", "windows-x64", "current"), ("local-build", "windows-x64", "unknown"), ("2.0.0", "linux-arm64", "unknown")):
        result = release.check_for_update(installed, release.GitHubSource("publisher", "tool"), platform_tag=platform, fetch=local_manifest)
        require(result["state"] == state and result["downloadedBytes"] == 0, CONTRACTS[1], "metadata observation goal failed")
        observed.append(result["state"])
    missing = root / "nonexistent-manifest.json"
    result = release.check_for_update("2.0.0", release.GitHubSource("publisher", "tool"), fetch=lambda _url, **_args: missing.read_bytes())
    require(result["state"] == "unknown", CONTRACTS[1], "unreachable source claimed current")
    record(CONTRACTS[1], manifestReads=len(reads), states=observed + [result["state"]], networkAccessed=False)
    target = root / "staged-package.zip"
    checksum = hashlib.sha256(package.read_bytes()).hexdigest()
    result = release.download_asset(asset, target, expected_sha256=checksum)
    require(target.read_bytes() == package.read_bytes(), CONTRACTS[2], "file transport changed archive")
    refuse(lambda: release.download_asset(asset, target, expected_sha256="0" * 64), release.GitHubReleaseError, CONTRACTS[2])
    require(target.read_bytes() == package.read_bytes() and not list(root.glob("*.partial")), CONTRACTS[2], "rejected replacement damaged valid target")
    bad_target = root / "rejected-package.zip"
    refuse(lambda: release.download_asset(asset, bad_target, expected_sha256="0" * 64), release.GitHubReleaseError, CONTRACTS[2])
    require(not bad_target.exists(), CONTRACTS[2], "corrupt new package remained staged")
    unverified = release.download_asset({**asset, "size": 999}, root / "unverified-package.zip")
    require(not unverified["verified"] and "999" in unverified["warning"], CONTRACTS[2], "unverified or short package mislabeled")
    record(CONTRACTS[2], path=str(target), sha256=checksum, transport="file", verified=result["verified"])

    # This owned server exercises HTTP protocol faults. Its endpoints are
    # explicitly local specimens; they do not impersonate a GitHub account.
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class ProtocolFaults(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_GET(self):
            if self.path == "/rate-limited":
                self.send_response(429)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Length", "1024")
                self.end_headers()
                self.wfile.write(b"part")
                self.wfile.flush()
                self.close_connection = True
    # Multiple isolated verifiers may run concurrently. Reserve an explicit
    # owned port atomically; never borrow the public service or an ephemeral port.
    server = None
    for port in (proof_port(48473), proof_port(48474)):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), ProtocolFaults)
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("No owned PROOFS-b HTTP fixture port is available")
    protocol_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        limited = release.check_for_update("2.0.0", release.GitHubSource("publisher", "tool"), fetch=lambda _url, **limits: release._default_fetch(protocol_url + "/rate-limited", **limits))
        require(limited["state"] == "unknown" and "rate limit" in limited["detail"], CONTRACTS[1], "HTTP429 was claimed current")
        refuse(lambda: release.download_asset({"name": "broken.zip", "browser_download_url": protocol_url + "/premature-eof"}, target), release.GitHubReleaseError, CONTRACTS[2])
        require(target.read_bytes() == package.read_bytes() and not list(root.glob("*.partial")), CONTRACTS[2], "premature HTTP close replaced a valid target")
        checks[1].update(http429State=limited["state"], transportBoundary="actual local HTTP protocol", port=port)
        checks[2].update(prematureHttpEofRejected=True, priorTargetPreserved=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # Create actual object history in a confined disposable repository. Git's
    # global/system configuration and hooks are disabled for every setup call.
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Git is required for local object proofs")
    repo = root / "repository"
    repo.mkdir()
    def command(*args):
        env = GitReferenceAdapter._env()
        result = subprocess.run([git, "-c", "core.hooksPath=" + os.devnull, "-C", str(repo), *args], env=env, capture_output=True, text=True, timeout=15, check=True, **hidden_windows_subprocess_kwargs())
        return result.stdout.strip()
    command("init")
    command("config", "user.name", "PROOFS-b")
    command("config", "user.email", "proofs@example.invalid")
    tracked = repo / "tracked.txt"
    tracked.write_text("first\n", encoding="utf-8")
    command("add", "tracked.txt")
    command("commit", "-m", "first local proof object")
    first = command("rev-parse", "HEAD")
    tracked.write_text("first\nsecond\n", encoding="utf-8")
    command("commit", "-am", "second local proof object")
    second = command("rev-parse", "HEAD")
    command("remote", "add", "origin", "https://proof-user:synthetic-secret@example.invalid:bad/repo?token=synthetic-private#fragment")
    adapter = GitReferenceAdapter(root, executable=git)
    results = [adapter.execute({"repository": "repository", "operation": op, **args}) for op, args in (("repository.inspect", {}), ("repository.history", {"maxCommits": 2}), ("repository.show", {"ref": "HEAD", "paths": ["tracked.txt"]}), ("commit.ancestry-verify", {"ancestor": first, "descendant": second}))]
    require(results[0]["head"] == second and [r["commit"] for r in results[1]["commits"]] == [second, first] and "+second" in results[2]["content"] and results[3]["isAncestor"], CONTRACTS[3], "real object workflow differs")
    require("synthetic-secret" not in json.dumps(results) and "synthetic-private" not in json.dumps(results), CONTRACTS[4], "remote credentials escaped")
    record(CONTRACTS[3], operations=[r["operation"] for r in results], receipts=[r["receipt"] for r in results], boundary="real local Git objects")

    from .capability_service import CapabilityService
    from .tool_manifest_registry import ToolManifest, ToolManifestRegistry
    repository = Path(__file__).resolve().parents[2]
    current_service = CapabilityService(_fixture_root(root), catalog_path=repository / "config/capability_packs.json")
    current_manifest = current_service.tool_manifests.describe("tool.git")
    require(current_manifest["executionReadinessEvaluated"] and not current_manifest["productionReady"], CONTRACTS[12], "repository launcher pin represented as production ready without workflow admission")
    tool = next(r for r in json.loads((repository / "config/tool_suite_lock.json").read_text())["tools"] if r["toolId"] == "tool.git")
    expected_contract = tool["state"] == "verified" and bool(tool.get("packageSha256")) and bool(tool.get("operations"))
    require(current_manifest["contractReady"] == expected_contract, CONTRACTS[12], "repository contract readiness differs from its declared pin and operations")
    pin = GitReferenceAdapter.probe_executable_identity(git)
    operations = [dict(operationId=identity, name=identity, description="Bounded object-only " + identity, permissions=["workspace.read", "workspace.write", "artifact.write"], inputSchema={"type": "object", "properties": {"repository": {"type": "string"}}, "required": ["repository"]}, outputSchema={"type": "object", "required": ["ok", "head", "receipt"]}, metadata={"adapterOperation": identity}) for identity in ("repository.inspect", "repository.history", "repository.show", "commit.ancestry-verify")]
    tool.update(state="verified", workers=["windows"] if os.name == "nt" else ["container"], selectedVersion=pin["version"].removeprefix("git version "), installPath=str(Path(git).resolve()), packageSha256=pin["sha256"], health={"status": "healthy"}, operations=operations, readiness={"productionValidated": True, "productionEvidence": "Local object workflow receipts under this isolated proof root", "prerequisites": []})
    config_dir = root / "config"
    config_dir.mkdir(exist_ok=True)
    lock_path = config_dir / "tool_suite_lock.json"
    lock_path.write_text(json.dumps({"schema": "neyvia.tool_suite_lock.v1", "tools": [tool]}), encoding="utf-8")
    local_service = CapabilityService(_fixture_root(root), catalog_path=repository / "config/capability_packs.json")
    execution = local_service.execute_tool_operation({"toolId": "tool.git", "operationId": "repository.inspect", "arguments": {"repository": "repository"}, "permissionMode": "workspace_safe"})
    require(execution["ok"] and execution["outputValidation"]["valid"] and execution["result"]["head"] == second, CONTRACTS[13], "pinned service did not execute actual Git")
    registered = execution["artifactReceipt"]["artifacts"]
    require(len(registered) == 1 and registered[0]["metadata"]["role"] == "git-reference-receipt" and registered[0]["metadata"]["declaredSha256"] and registered[0]["metadata"]["derivedFrom"], CONTRACTS[13], "verified service receipt did not register")
    before_artifacts = local_service.artifacts.snapshot()
    declaration = results[0]["artifacts"][0]
    for patch in ({"sha256": "0" * 64}, {"derivedFrom": "0" * 64}):
        refuse(lambda patch=patch: local_service._register_adapter_artifacts({"result": {"artifacts": [{**declaration, **patch}]}}, capability_id="software.application-engineering", run_id="local-proof", adapter_id="code.git"), ValueError, CONTRACTS[13])
    require(local_service.artifacts.snapshot() == before_artifacts, CONTRACTS[13], "bad declarations changed the artifact graph")
    record(CONTRACTS[13], registered=registered, actualServiceExecution=True, invalidHashAndLineageRejected=True)
    policy_tools = [{**tool, "toolId": "tool.ready"}]
    unprovisioned = ToolManifest.from_payload({**tool, "state": "planned", "packageSha256": "", "operations": []})
    require(not unprovisioned.contract_ready, CONTRACTS[12], "unprovisioned manifest represented as contract ready")
    for kind in ("trust", "service", "device", "worker"):
        policy_tools.append({**tool, "toolId": "tool.blocked-" + kind, "readiness": {**tool["readiness"], "prerequisites": [{"id": kind + "-required", "kind": kind, "status": "unprovisioned", "requiredFor": ["execution", "production"], "reason": "Isolated readiness policy refusal", "evidence": ""}]}})
    policy_path = root / "readiness-policy.json"
    policy_path.write_text(json.dumps({"schema": "neyvia.tool_suite_lock.v1", "tools": policy_tools}), encoding="utf-8")
    registry = ToolManifestRegistry(policy_path)
    require(not registry.describe("tool.ready")["executionReady"], CONTRACTS[12], "unbound readiness guessed a runtime")
    registry.bind_adapters(local_service.adapters)
    ready = registry.describe("tool.ready")
    require(ready["agentReady"] and ready["executionReady"] and ready["productionReady"] and ready["readiness"]["runtimeEvidence"]["runtimeIdentityVerified"], CONTRACTS[12], "actual pinned runtime was not admitted")
    for kind in ("trust", "service", "device", "worker"):
        blocked = registry.describe("tool.blocked-" + kind)
        require(blocked["agentReady"] and not blocked["executionReady"] and not blocked["productionReady"] and kind in {r["kind"] for r in blocked["blockedPrerequisites"]}, CONTRACTS[12], "prerequisite bypassed live readiness")
    require([r["toolId"] for r in registry.search("", execution_ready_only=True)["results"]] == ["tool.ready"] and len(registry.search("", agent_ready_only=True)["results"]) == 5, CONTRACTS[12], "discovery filters confused contract/live readiness")
    refuse(lambda: ToolManifest.from_payload({**tool, "readiness": {"productionValidated": "false"}}), ValueError, CONTRACTS[12])
    record(CONTRACTS[12], actualGitVersion=pin["version"], actualGitSha256=pin["sha256"], blockedKinds=["trust", "service", "device", "worker"], repositoryManifestContractReady=current_manifest["contractReady"], boundary="actual native Git with isolated manifest pin; repository pin unchanged")
    for key, value in (("filter.unsafe.process", "helper"), ("diff.unsafe.command", "helper"), ("diff.unsafe.textconv", "helper"), ("protocol.file.allow", "always"), ("core.sshCommand", "helper"), ("remote.origin.promisor", "true"), ("remote.origin.partialCloneFilter", "blob:none"), ("include.path", "../external-config")):
        command("config", key, value)
        refuse(lambda: adapter.execute({"repository": "repository", "operation": "repository.inspect"}), GitReferenceError, CONTRACTS[4])
        command("config", "--unset", key)
    for name in (".gitattributes", "nested/.gitattributes", ".git/info/attributes", ".git/objects/info/alternates", ".git/objects/info/http-alternates", ".git/objects/pack/unsafe.promisor"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("../external filter=unsafe\n", encoding="utf-8")
        refuse(lambda: adapter.execute({"repository": "repository", "operation": "repository.inspect"}), GitReferenceError, CONTRACTS[4])
        path.rename(path.with_name(path.name + ".rejected-proof"))
    linked = root / "linked-worktree"
    command("worktree", "add", "--detach", str(linked), "HEAD")
    refuse(lambda: adapter.execute({"repository": "linked-worktree", "operation": "repository.inspect"}), GitReferenceError, CONTRACTS[4])
    record(CONTRACTS[4], unsafeConfigurations=8, unsafeStoragePaths=6, linkedWorktreeRejected=True, networkAccessed=False)

    page = "Local report generated from a full page of documented text.\n\nRetain the complete result."
    table = "<table><tr><td>Local report</td></tr></table>"
    formula = "$$\nx = 1 + 2\n$$"
    repair_procedures = (("renderer", page + "\n```markdown\n\n" + page[:40], page), ("renderer", "Different markdown\n```markdown\n\n| Genuine | table |", None), ("table", table + "\nExtraneous text", table), ("table", "<table><tr><td>unfinished", None), ("formula", formula + "\n" + formula, formula), ("formula", formula + "\n$$\nx = 4\n$$", None))
    for kind, raw, expected in repair_procedures:
        fn = getattr(CapabilityAdapterRegistry, "_repair_glm_" + {"renderer": "renderer_duplicate", "table": "table_boundary", "formula": "formula_boundary"}[kind])
        output, evidence = fn(raw)
        require(output == (raw if expected is None else expected) and (evidence is None) == (expected is None), CONTRACTS[5], "repair boundary goal differs")
    record(CONTRACTS[5], procedures=len(repair_procedures), boundary="text repair only; no OCR runtime")

    state = RunState(objective="Resume a local artifact", plan_steps=["Inspect", "Implement"], completed_steps=["Inspect"], acceptance_checks=["Inspect artifact"], next_actions=["Implement"])
    stack = PromptStack(base_constitution="Local rules", project_profile="PROOFS-b", persona=PersonaProfile(name="proof", tone="plain", risk_tolerance="low", creativity_level="low", coding_style="small", verbosity="short"), task_brief="Resume", step_policy="Observe before changes")
    manager = ContextWindowManager(max_tokens=100)
    manager.record("user", "Resume local artifact")
    packet = create_handoff_packet("local-proof", None, "context_rollover", state, stack, manager)
    saved = save_handoff_packet(packet, root, 1)
    require(json.loads(saved.read_text())["progress"]["remaining_steps"] == ["Implement"], CONTRACTS[6], "persisted handoff lost progress")
    record(CONTRACTS[6], path=str(saved), sha256=hashlib.sha256(saved.read_bytes()).hexdigest())

    # Protocol scoring is a deterministic transformation of observations.
    # Deliberate observation specimens are never represented as model runs.
    catalog = []
    attempts = []
    for identity, capabilities, duration in (("complete", ["agent_loop", "sessions", "tools", "subagents", "proof", "approvals"], 2000), ("fast", ["headless_json", "sessions", "tools", "subagents"], 500)):
        catalog.append({"harnessId": identity, "installed": True, "detected": True, "readiness": "ready", "instructionFiles": ["AGENTS.md"], "capabilities": [{"key": c, "support": "native", "available": True} for c in capabilities]})
        for task in comparison.TASKS:
            output = comparison.RESULT_MARKER + json.dumps(task["expected"])
            grade = comparison.grade_output(task["id"], output)
            require(grade["correct"], CONTRACTS[7], "exact specimen failed scoring")
            attempts.append({"harnessId": identity, "taskId": task["id"], "status": "completed", "grade": grade, "receiptPresent": True, "providerSubstitution": False, "readOnlyEnforced": True, "metrics": {"executionDurationMs": duration}})
            require(not comparison.grade_output(task["id"], comparison.RESULT_MARKER + "{}")["correct"], CONTRACTS[7], "missing fields scored exact")
            altered = {**task["expected"], next(iter(task["expected"])): "wrong-field-value"}
            require(not comparison.grade_output(task["id"], comparison.RESULT_MARKER + json.dumps(altered))["correct"], CONTRACTS[7], "altered field scored exact")
    for patch in ({"installed": False}, {"detected": False}, {"readiness": "provider-unverified"}, {"securityOnly": True}):
        require(not comparison.eligibility({**catalog[0], **patch})[0], CONTRACTS[8], "unready candidate admitted")
    summaries = comparison.summarize_attempts(catalog, attempts)
    require(comparison.select_leader(summaries)["harnessId"] == "complete" and summaries[1]["medianExecutionMs"] == 500 and comparison.capability_coverage(catalog[0])["count"] == 7, CONTRACTS[8], "coverage preference or speed observation lost")
    partial = comparison.summarize_attempts(catalog, attempts[:1])
    require(comparison.select_leader(partial)["status"] == "inconclusive", CONTRACTS[8], "partial sample won")
    failed = [{**r, "correctnessRate": 0, "completionRate": 0} for r in summaries]
    require(comparison.select_leader(failed)["status"] == "inconclusive", CONTRACTS[8], "failed sample won")
    record(CONTRACTS[7], taskCount=len(comparison.TASKS), boundary="deterministic protocol scoring")
    record(CONTRACTS[8], winner="complete", observedFastMedianMs=500, providerRuns=0)

    html = root / "index.html"
    html.write_text("<h1>Lumen Notes</h1>", encoding="utf-8")
    require(not combine_score(grade_html(html), {"score": 0})["passed"], CONTRACTS[9], "empty artifact passed")
    html.write_text('<!doctype html><html><head><style>:focus-visible{outline:2px solid red}@media(max-width:600px){main{width:100%}}@media(prefers-reduced-motion:reduce){*{transition:none}}</style></head><body><header><nav>Nav</nav></header><main><h1>Lumen Notes</h1><button type="button" data-filter="all" aria-pressed="true">All</button><button type="button" aria-pressed="false">Ideas</button><button type="button" aria-pressed="false">Tasks</button><button type="button" aria-label="Toggle theme">Theme</button><section data-category="ideas">' + 'Local feature notes. ' * 200 + '</section></main><footer>Footer</footer><script>document.querySelectorAll("[data-filter]").forEach(b=>b.addEventListener("click",()=>{document.body.dataset.category=b.dataset.filter}))</script></body></html>', encoding="utf-8")
    static = grade_html(html)
    require(static["score"] >= 70 and not combine_score(static, {"score": 0})["passed"], CONTRACTS[9], "static rubric or browser gate differs")
    require(all(s in FROZEN_PROMPT for s in ("index.html", "no external", "390px")), CONTRACTS[9], "frozen benchmark protocol changed")
    record(CONTRACTS[9], artifact=str(html), staticScore=static["score"], browserScore=0, passed=False, boundary="static rubric only")

    repository = Path(__file__).resolve().parents[2]
    require(audit_workflows(repository) == [], CONTRACTS[10], "repository publication audit failed")
    workflow_root = root / "workflow-policy" / ".github/workflows"
    workflow_root.mkdir(parents=True)
    workflow = workflow_root / "candidate.yml"
    conditions = (("git-push", "git push origin HEAD:main", "contents: read"), ("git-push", "git \\\n            push origin HEAD:main", "contents: read"), ("write-api-call", "gh api --method POST /repos/o/r/actions/runs/1/cancel", "actions: write"), ("pull-request-mutation", "gh pr merge 45 --squash", "contents: read"), ("write-all-permissions", "echo validation", "write-all"), ("legacy-self-mutating-branch", "echo " + LEGACY_NATIVE_BRANCH, "contents: read"))
    for rule, body, permissions in conditions:
        permission_block = "permissions: write-all\n" if permissions == "write-all" else "permissions:\n  " + permissions + "\n"
        workflow.write_text("name: local-policy-proof\non: workflow_dispatch\n" + permission_block + "jobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - run: |\n          " + body + "\n", encoding="utf-8")
        require(rule in {r["rule"] for r in audit_workflows(root / "workflow-policy")}, CONTRACTS[10], "unsafe publication pattern escaped")
    workflow.write_text("name: safe\non: pull_request\npermissions:\n  contents: read\njobs:\n  audit:\n    steps:\n      - run: python check.py\n", encoding="utf-8")
    require(audit_workflows(root / "workflow-policy") == [], CONTRACTS[10], "safe validation refused")
    record(CONTRACTS[10], actualRepository=str(repository), unsafePatterns=len(conditions), actualWorkflowCount=len(list((repository / ".github/workflows").glob("*.y*ml"))))

    from .folder_sync import FolderSyncService
    local_config = root / "folder-sync-local.json"
    # A local text artifact proves hashing, explicitly not a Syncthing executable.
    local_config.write_text(json.dumps({"transport": {"endpoint": proof_text("http://127.0.0.1:48476"), "apiKeyRef": "proofs:no-key"}, "binary": {"installPath": str(package), "executableSha256": checksum}, "policy": {"allowedRoots": ["${workspace}"], "folderTypes": ["sendonly", "receiveonly", "sendreceive"], "versioningTypes": ["trashcan", "simple", "staggered"], "inboundVersioningRequiredFor": ["receiveonly", "sendreceive"], "defaultVersioning": {"type": "staggered"}}}), encoding="utf-8")
    service = FolderSyncService(root, config_path=local_config, credential_resolver=lambda _reference: "proofs-memory-only-synthetic-key")
    compatibility = service.compatibility_snapshot()
    require(compatibility["binary"]["hashVerified"] and compatibility["transport"]["credentialAvailable"] and "proofs-memory-only-synthetic-key" not in json.dumps(compatibility), CONTRACTS[11], "local compatibility or credential redaction differs")
    record(CONTRACTS[11], boundary="hash observation only, no service call; synthetic in-memory key", credentialAvailable=True, actualSha256=checksum)
    shared = root / "selected-sync-folder"
    shared.mkdir()
    device = "AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"
    common = {"folder_id": "docs", "path": shared, "device_ids": [device]}
    refuse(lambda: service.build_folder_plan(**common, ignore_patterns=["#include another.ignore"]), ValueError, "adapters.sync.policy")
    refuse(lambda: service.build_folder_plan(**common, folder_type="sendreceive", versioning={"type": "external", "params": {"command": "untrusted"}}), ValueError, "adapters.sync.policy")
    refuse(lambda: service.build_folder_plan(**{**common, "path": root.parent}), ValueError, "adapters.sync.policy")
    require(service._allowed_folder_path(shared) == shared and service._validated_versioning("sendreceive", None)["type"] == "staggered"
            and service._validate_ignore_patterns([".git", ".git"]) == [".git"], "adapters.sync.policy", "safe policy choices lost")
    record("adapters.sync.policy", rejectedBeforeProviderRequests=True, boundary="local path, ignore and versioning preconditions; no Syncthing service")
    if not native_sync_executable(repository).is_file():
        # The native service is an optional, separately prepared dependency that
        # startup never downloads. Without it, its contracts are not claimed:
        # they are reported as skipped with the reason, never as passed.
        reason = ("Pinned Syncthing v2.1.5 is not prepared on this host (task-local .agent_control/proofs-b/native-syncthing "
                  "or NEYVIA_PROOF_SYNCTHING_EXE); native sync contracts were not exercised")
        skipped = [{"contract": identity, "status": "skipped", "reason": reason} for identity in NATIVE_SYNC_CONTRACTS]
        return {"ok": True, "contracts": [identity for identity in CONTRACTS if identity not in NATIVE_SYNC_CONTRACTS],
                "skipped": skipped, "checks": checks, "rejections": rejections,
                "elapsedMs": round((time.perf_counter() - started) * 1000, 3), "frontier": [*FRONTIER, reason]}
    native = _native_sync_check(repository, root)
    checks.extend(native["checks"])
    rejections.extend(native["rejections"])
    return {"ok": True, "contracts": list(CONTRACTS), "checks": checks, "rejections": rejections, "elapsedMs": round((time.perf_counter() - started) * 1000, 3), "frontier": FRONTIER}


def _fixture_root(root):
    """Bind the real consumer to an empty broker config in disposable state."""
    from .proof_credential_guard import prepare_broker_fixture
    root = Path(root).resolve()
    if not (root / "config/neyvia_secret_broker.json").exists():
        prepare_broker_fixture(root)
    return root


def self_check_chapters(root, chapters):
    """Run explicitly selected chapter owners; full default self_check is unchanged.

    Returned contracts identify only observed chapter effects. Native/provider
    chapters and startup completeness remain outside this partial invocation.
    """
    from scripts.c8e_extra_effects import adapter_chapters
    result = adapter_chapters(root, chapters)
    if 'sync' in chapters and os.environ.get('NEYVIA_PROOF_AGENT_DESKTOP') == '1':
        native = _native_sync_check(Path(__file__).resolve().parents[2], Path(root) / 'selected-native')
        result['checks'].extend({**row, 'ok': True} for row in native['checks'])
        result['rejections'].extend(native['rejections'])
        result['contracts'] = sorted(set(result['contracts']) | {row['contract'] for row in native['checks']})
        result['nativeReceipt'] = native['receipt']
    return result
