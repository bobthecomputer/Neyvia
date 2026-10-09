"""Run the frozen C1 action cohort exclusively on private agent desktops.

No input-desktop launch, enumeration, capture, restoration, or fallback exists.
Each application has a new kill-on-close job; the shared guard spans all jobs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.cua_guard import ZeroDisturbanceGuard
from grant_agent.cua_native import NativeWorker
from grant_agent.cua_desktop import DesktopIsolationError
from verify_c1c_apps import app_launch, choose, selector, percentile
from c11_cohort_learning import CohortLearning

MANIFEST = ROOT / "config/cua-everyday-tasks.json"
RECEIPT = ROOT / "scripts/evidence/C11-cohort.json"
SOURCE_PATHS = [*sorted((ROOT / "src/grant_agent").glob("cua_*.py")),
    ROOT / "src/grant_agent/neyvia_cua.py", ROOT / "manuals/computer-use.manual.json",
    ROOT / "manuals/cl/computer-use.cl", Path(__file__), ROOT / "scripts/c11_cohort_learning.py",
    ROOT / "scripts/verify_c1c_apps.py", ROOT / "scripts/verify_c1b_apps.py", ROOT / "scripts/c1_native_benchmark.py",
    ROOT / "src/grant_agent/manual_compiler.py", ROOT / "src/grant_agent/manual_versions.py",
    ROOT / "config/cua-desktop-contract.json", ROOT / "config/cua-everyday-tasks.json",
    ROOT / "scripts/build_c11f_panel.py",
    *sorted((ROOT / "tools/cua-driver-win").glob("*.cs")),
    ROOT / "tools/cua-driver-win/parked-hook.cpp"]


def source_hashes():
    return {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in SOURCE_PATHS}


def write_receipt(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        previous = path.read_bytes()
        # Preserve prior trials once, rather than copying the growing receipt
        # after every app. All failures in this run remain in the final record.
        if not result.get("runId") or json.loads(previous).get("runId") != result.get("runId"):
            archive = path.parent / (path.stem.split("-", 1)[0] + "-runs")
            archive.mkdir(exist_ok=True)
            saved = archive / (hashlib.sha256(previous).hexdigest() + ".json")
            if not saved.exists():
                saved.write_bytes(previous)
            if saved.read_bytes() != previous:
                raise RuntimeError("Previous receipt archive differs from its exact bytes")
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def compact_observation(value):
    return {"source": value.get("source"), "nodeCount": len(value.get("tree", [])),
            "truncated": value.get("truncated"), "elapsedMs": value.get("elapsedMs"),
            "degradedReason": value.get("degradedReason")}


def compact_guard(value):
    return {key: value.get(key) for key in ("ok", "samples", "violations",
        "new_visible_windows", "foreground_changes", "cursor_moves",
        "owned_escaped_windows_hidden", "external_guard_entries")}


def owned_window(worker, deadline, required_token=None, minimum_size=(250, 150)):
    while time.monotonic() < deadline:
        windows = worker.request("windows", timeout=4)
        admitted = [w for w in windows if not w.get("minimized")
            and (not required_token or required_token in w.get("title", ""))
            and worker.desktop.owns(int(w["windowId"]))
            and worker.desktop.owns_pid(int(w["pid"]))
            and w.get("className") not in {"UAC_InputIndicatorOverlayWnd", "MSCTFIME UI", "IME", "MsoSplash"}
            and w.get("bounds", {}).get("width", 0) >= minimum_size[0]
            and w.get("bounds", {}).get("height", 0) >= minimum_size[1]]
        if admitted:
            return max(admitted, key=lambda w: w.get("bounds", {}).get("width", 0)
                       * w.get("bounds", {}).get("height", 0))
        time.sleep(.05)
    return None


def stable_owned_editor(worker, window, token):
    """Wait for a freshly launched editor's final task window, not its splash."""
    stable_since = time.monotonic()
    deadline = stable_since + 6
    while time.monotonic() < deadline:
        current = owned_window(worker, time.monotonic() + .5, token)
        if not current:
            continue
        if current['windowId'] != window['windowId']:
            window, stable_since = current, time.monotonic()
        if time.monotonic() - stable_since >= 1.25:
            return window
        time.sleep(.1)
    return window


def task_ready(worker, task, window, seconds):
    """Startup readiness is separate from fresh timed action attempts."""
    started = time.perf_counter()
    deadline = time.monotonic() + seconds
    observations = 0
    transient_errors = []
    while True:
        try:
            observed = worker.request("inspect", {"windowId": window["windowId"],
                "maxDepth": 12, "maxNodes": 500}, timeout=4)
        except (TimeoutError, OSError) as exc:
            transient_errors.append(type(exc).__name__ + ': ' + str(exc))
            if time.monotonic() >= deadline:
                raise
            time.sleep(.1)
            continue
        observations += 1
        node = choose_task(observed.get("tree", []), task, 0)
        if node or time.monotonic() >= deadline:
            return observed, {"ready": node is not None, "observations": observations,
                "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
                "transientErrors": transient_errors}
        time.sleep(.1)


def dismiss_owned_startup_prompt(worker, task, window, observed, fixture_token=None):
    """Only known read-only recovery prompts; never recover user documents."""
    if task["app"] not in {"Microsoft Word", "DirectX Diagnostic Tool", "Device Manager"}:
        return window, observed, None
    text = " ".join(n.get("name", "") for n in observed.get("tree", []))
    known = (task["app"] == "Microsoft Word" and ("mode sans échec" in text.casefold() or "safe mode" in text.casefold())) or (
        task["app"] == "DirectX Diagnostic Tool" and ("Voulez-vous ignorer" in text or "skip" in text.casefold())) or (
        task["app"] == "Device Manager" and
        ("utilisateur standard" in text.casefold() or "standard user" in text.casefold()) and
        ("afficher les paramètres" in text.casefold() or "view device settings" in text.casefold()))
    buttons = [n for n in observed.get("tree", []) if n.get("role") == "Button"
        and n.get("name", "").replace("&", "").casefold() in ({"ok"} if task["app"] == "Device Manager" else {"no", "non", "cancel", "annuler"})
        and n.get("className") == "Button" and n.get("nativeWindowHandle")]
    if not known or len(buttons) != 1:
        return window, observed, None
    response = worker.request("action", {"windowId": window["windowId"],
        "elementId": buttons[0]["id"], "action": "buttonClick", "allowForeground": False}, timeout=4)
    updated = owned_window(worker, time.monotonic() + 10,
        fixture_token if task["app"] == "Microsoft Word" else None)
    if updated:
        window = updated
        observed = worker.request("inspect", {"windowId": window["windowId"], "maxDepth": 12, "maxNodes": 500}, timeout=4)
    return window, observed, {"target": selector(buttons[0]), "response": response}


def task_fixture_launch(task, exe, scratch):
    token = scratch.name.rsplit("-", 1)[-1]
    (scratch / ("ownership-" + token + ".json")).write_text(json.dumps({
        "token": token, "app": task["app"], "values": task["values"],
        "scope": task["scope"]}), encoding="utf-8")
    launch = app_launch(task["app"], exe, scratch)
    if task['app'] in {'Cursor', 'Antigravity'}:
        port = 48706 if task['app'] == 'Cursor' else 48707
        profile = scratch / 'editor-profile'
        settings = profile / 'User/settings.json'
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({'workbench.startupEditor': 'none', 'security.workspace.trust.enabled': False,
            'telemetry.telemetryLevel': 'off', 'update.mode': 'none'}), encoding='utf-8')
        document = scratch / ('c11-' + token + '.txt')
        document.write_text(token + '\n' + '\n'.join(task['values']), encoding='utf-8')
        launch = [str(exe), '--user-data-dir=' + str(profile), '--extensions-dir=' + str(scratch / 'extensions'),
            '--disable-extensions', '--new-window', '--disable-gpu', '--force-renderer-accessibility',
            '--skip-welcome', '--skip-release-notes', '--remote-debugging-port=' + str(port),
            '--remote-allow-origins=http://127.0.0.1:' + str(port), str(document)]
    if task['app']=='File Explorer':
        launch=[str(exe),'/n,'+str(scratch),'/separate']
    if task['app'] in {'Photos','Paint','Snipping Tool'}:
        from PIL import Image, ImageDraw
        image=scratch/('c11-'+token+'.png')
        bitmap=Image.new('RGB',(640,480),'white')
        ImageDraw.Draw(bitmap).text((30,30),'Disposable image '+token,fill='black')
        bitmap.save(image)
        launch=[str(exe),str(image)]
    if task['app']=='Sticky Notes':
        raise DesktopIsolationError('Installed Sticky Notes uses the personal note store; no disposable profile argument was found')
    if task['app']=='Windows Terminal':
        launch=[str(exe),'-w','new','new-tab','--title',token,'--suppressApplicationTitle',
                '-d',str(scratch),'powershell.exe','-NoLogo','-NoProfile','-NoExit']
    if task.get("consoleFile"):
        source = Path(task["consoleFile"])
        if source.parent != exe.parent or source.suffix.casefold() != ".msc" or not source.is_file():
            raise ValueError("Console fixture must copy an installed adjacent MSC")
        console = scratch / ("c11-" + token + ".msc")
        copy_console(source, console, token)
        launch = [str(exe), "/a", str(console)]
    if task["app"] == "Management Console":
        console = scratch / ("c11-" + token + ".msc")
        copy_console(Path(task["exe"]).parent / "eventvwr.msc", console, token)
        launch.append(str(console))
    if task["app"] == "Performance Monitor":
        console = scratch / ("c11-" + token + ".msc")
        copy_console(exe.parent / "perfmon.msc", console, token)
        launch = [str(exe.parent / "mmc.exe"), "/a", str(console)]
    if task["app"] in {"Services", "Computer Management"}:
        source = "services.msc" if task["app"] == "Services" else "compmgmt.msc"
        console = scratch / ("c11-" + token + ".msc")
        copy_console(exe.parent / source, console, token)
        launch = [str(exe), "/a", str(console)]
    if task["app"] == "Microsoft Word":
        launch.insert(1, "/x")
        from docx import Document
        book = Document()
        book.add_paragraph(token)
        for value in task["values"]:
            book.add_paragraph(value)
        book.save(scratch / ("c11-" + token + ".docx"))
    if task["app"] == "Microsoft PowerPoint":
        from pptx import Presentation
        deck = Presentation()
        for value in [token, *task["values"]]:
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            slide.shapes.add_textbox(100000, 100000, 7000000, 1000000).text = value
        deck.save(scratch / ("c11-" + token + ".pptx"))
    if task["app"] == "Microsoft Excel":
        from openpyxl import load_workbook
        document = scratch / ("c11-" + token + ".xlsx")
        book = load_workbook(document)
        book.active["D1"] = token
        book.save(document)
    if task["app"] == "Visual Studio Code":
        settings = scratch / "vscode-profile/User/settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"workbench.startupEditor": "none", "security.workspace.trust.enabled": False,
            "telemetry.telemetryLevel": "off", "update.mode": "none"}), encoding="utf-8")
        launch += ["--disable-gpu", "--force-renderer-accessibility", "--skip-welcome", "--skip-release-notes"]
    return launch


def copy_console(source, destination, token):
    """Keep the installed snap-in, but give this disposable console its title."""
    from xml.etree import ElementTree
    document = ElementTree.parse(source)
    identity = document.find("ConsoleFileID")
    if identity is not None:
        identity.text = "{" + str(uuid.uuid4()).upper() + "}"
    title = document.find("VisualAttributes/String[@Name='ApplicationTitle']")
    if title is not None:
        for text in document.findall("StringTables/StringTable/Strings/String"):
            if text.get("ID") == title.get("ID"):
                text.text = "C11 " + token
    document.write(destination, encoding="utf-8", xml_declaration=True)


def choose_task(tree, task, repetition):
    if task["action"] == "expand":
        tree = [node for node in tree if node.get("expandable") is True
            or "expandCollapse" in node.get("patterns", [])]
    found = choose(tree, task, repetition)
    if found is None and task["app"] in {"Character Map", "Remote Desktop Connection"}:
        # Win32 exposes the label as a separate Static control. Character Map
        # has one editable Characters-to-copy field; require that uniqueness,
        # never substitute a different labelled field or a protected control.
        fields = [n for n in tree if n.get("role") == "Edit" and not n.get("name")
            and re.fullmatch(r"(?:Edit|RichEdit.*)", n.get("className", ""), re.I) and n.get("nativeWindowHandle")
            and n.get("enabled", True) and not n.get("readOnly")
            and not n.get("isPassword") and not n.get("protectionUnknown")]
        all_fields = [n for n in tree if n.get("role") == "Edit"]
        if len(fields) == len(all_fields) == 1:
            found = fields[0]
        elif task["app"] == "Remote Desktop Connection":
            # /edit loads our sentinel host in Computer, while the separate
            # Username field can inherit an empty label. Identify Computer by
            # the exact seeded invalid-domain value, then the five task values.
            hosts = [n for n in fields if n.get("value") in task["values"]
                or re.fullmatch(r"c11-[a-f0-9]{32}\.invalid", n.get("value", ""))]
            if len(hosts) == 1:
                found = hosts[0]
    return found


def action_request(task, node, repetition, window_id, tree=None):
    action = task["action"]
    request = {"windowId": window_id, "elementId": node["id"], "allowForeground": False,
        "expectedName": node.get("name", ""), "expectedRole": node.get("role", ""),
        "expectedClass": node.get("className", "")}
    check = {"selector": selector(node)}
    if action == "value":
        request.update(action="value", text=task["values"][repetition % 5])
        check["selector"] = {"id": node["id"], "role": node["role"]}
        # Runtime IDs can change on a browser render or Office search update.
        # Admit a semantic readback selector only when this fresh observation
        # proves it identifies exactly one field in the owned target window.
        for key in ("automationId", "name"):
            value = node.get(key)
            if value and tree is not None and sum(n.get(key) == value and n.get("role") == node["role"] for n in tree) == 1:
                check["selector"] = {key: value, "role": node["role"]}
                break
        check["value_equals"] = request["text"]
    elif action == "select":
        request["action"] = "select"
        check["selected_equals"] = True
    elif action == "expand":
        expanded = node.get("expanded", node.get("expandState") == 1)
        request["action"] = "collapse" if expanded else "expand"
        check["expand_equals"] = 0 if expanded else 1
    elif action == "calculator":
        request["action"] = "click"
        check = {"selector": {"automationId": "CalculatorResults"},
                 "name_contains": str(repetition + 1)}
    else:
        raise ValueError("Unsupported frozen task action")
    request["expect"] = [check]
    return request


def run_actions(worker, task, window_id, row, learning):
    for repetition in range(5):
        attempt = {"repetition": repetition + 1, "passed": False, "actionSent": False}
        row["attempts"].append(attempt)
        tick = time.perf_counter()
        try:
            observed = worker.request("inspect", {"windowId": window_id,
                "maxDepth": 12, "maxNodes": 500}, timeout=4)
            node = choose_task(observed.get("tree", []), task, repetition)
            if node is None:
                # One fresh read can resolve a truncated/transitional tree.
                # No action or weaker selector is used during this retry.
                observed = worker.request("inspect", {"windowId": window_id,
                    "maxDepth": 12, "maxNodes": 500}, timeout=4)
                attempt["observationRetries"] = 1
                node = choose_task(observed.get("tree", []), task, repetition)
            if node is None:
                attempt['freshCandidates'] = [{key: item.get(key) for key in ('role', 'name', 'className', 'offscreen', 'enabled', 'value')}
                    for item in observed.get('tree', []) if item.get('role') in {'Edit', 'Document'}]
                attempt["error"] = "No safe fresh actionable target; no mutation"
                continue
            request = action_request(task, node, repetition, window_id, observed.get("tree", []))
            attempt["actionSent"] = True
            response = worker.request("cycle", request, timeout=4)
            attempt.update(target=selector(node), request=request,
                response={key: response.get(key) for key in ("effect", "mechanism", "check",
                    "foregroundPreserved", "cursorPreserved", "preservationObservable", "elapsedMs")},
                passed=response.get("effect") == "confirmed"
                    and response.get("check", {}).get("status") == "satisfied"
                    and response.get("foregroundPreserved") is True
                    and response.get("cursorPreserved") is True)
            attempt["observedState"] = response.get("observation")
            attempt["nativeNode"] = node
        except Exception as exc:
            attempt["error"] = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            attempt["atomicMs"] = round((time.perf_counter() - tick) * 1000, 2)
        if learning:
            try:
                row["connectedLanguage"].append(learning.observe())
            except Exception as exc:
                row["learningError"] = f"{type(exc).__name__}: {exc}"[:400]
    times = [a["atomicMs"] for a in row["attempts"] if a.get("actionSent")]
    row["latency"] = {"n": len(times), "p50Ms": percentile(times, .5),
        "p95Ms": percentile(times, .95), "includesFailures": True,
        "includesNoActionAttempts": False,
        "observationsWithoutAction": sum(not a.get("actionSent") for a in row["attempts"])}
    row["passed"] = sum(a["passed"] for a in row["attempts"])
    row["status"] = "passed" if row["passed"] == 5 else "partial" if row["passed"] else "failed"
    if row["passed"] != 5:
        row["reason"] = next((a.get("error") or str(a.get("response", {}).get("check"))
            for a in row["attempts"] if not a["passed"]), "Frozen task postcondition unsatisfied")
    if row["passed"] == 5 and learning:
        try:
            row["learnedFlow"] = learning.compile_task(task, row["attempts"])
        except Exception as exc:
            row["learnedFlow"] = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"[:500]}


def finish_result(result, manifest, guard, args):
    result["guardAfter"] = guard.close()
    rows = result["apps"]
    times = [a["atomicMs"] for row in rows for a in row["attempts"] if a.get("actionSent")]
    passed = [row for row in rows if row.get("passed") == 5 and row.get("status") == "passed"]
    result["summary"] = {"manifestApps": len(manifest["apps"]), "reportedApps": len(rows),
        "appsWithFiveVerifiedActions": len(passed),
        "appsWithDraftManual": sum(bool(row.get("firstUseManual", {}).get("patchId")) for row in rows),
        "appsWithConnectedLanguageSnapshotAndDiff": sum(
                any(item["state"].get("mode") in {"snapshot", "handle"} for item in row.get("connectedLanguage", []))
            and any(item["state"].get("mode") == "diff" and item["state"].get("diff") for item in row.get("connectedLanguage", []))
            for row in rows),
        "appsWithVerifiedCompiledZeroTokenFlow": sum(
            row.get("learnedFlow", {}).get("status") == "passed"
            and row["learnedFlow"].get("compiledReplay")
            and row["learnedFlow"].get("tokens") == 0 for row in rows),
        "verifiedActions": sum(row.get("passed", 0) for row in rows),
        "observationsWithoutAction": sum(not a.get("actionSent") for row in rows for a in row["attempts"]),
        "attempts": len(times), "p50Ms": percentile(times, .5), "p95Ms": percentile(times, .95),
        "appsWithFirstObservationUnder500Ms": sum(row.get("firstObservationMs", 501) < 500 for row in rows),
        "zeroDisturbance": result["guardAfter"]["ok"]}
    summary = result["summary"]
    result["gates"] = {"allFrozenAppsReported": len(rows) == len(manifest["apps"]),
        "atLeast15AppsWithFiveVerifiedActions": len(passed) >= 15,
        "actionP50Under150MsIncludingFailures": summary["p50Ms"] is not None and summary["p50Ms"] < 150,
        "successfulAppsFirstObservationUnder500Ms": bool(passed) and all(row["firstObservationMs"] < 500 for row in passed),
        "atLeast15AppsWithDraftManual": summary["appsWithDraftManual"] >= 15,
        "atLeast15AppsWithConnectedLanguageSnapshotAndDiff": summary["appsWithConnectedLanguageSnapshotAndDiff"] >= 15,
        "atLeast15AppsWithVerifiedCompiledZeroTokenFlow": summary["appsWithVerifiedCompiledZeroTokenFlow"] >= 15,
        "zeroDisturbance": result["guardAfter"]["ok"]}
    result["complete"] = all(result["gates"].values())
    result["sourceDrift"] = [path for path, digest in result["sourceSha256"].items()
                             if source_hashes().get(path) != digest]
    result["gates"]["sourceBound"] = not result["sourceDrift"]
    result["complete"] = all(result["gates"].values())
    write_receipt(args.receipt, result)


def result_header(args, manifest_bytes, run_id):
    return {"schema": "neyvia.c11.isolated-cohort.v1", "runId": run_id,
        "at": datetime.now(timezone.utc).isoformat(),
        "taskManifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "sourceSha256": source_hashes(),
        "timingIncludes": "Fresh inspect + cycle(action + verified readback), including every failed attempt; startup and setup reported separately",
        "mutationBoundary": "Only process-job-attributed isolated windows; private desktop or verified inactive Bureau",
        "environment": args.environment,
        "fallback": "Both layers are checked before needs-permission; broker launch requires exclusive attribution and is otherwise refused",
        "apps": [], "limitations": ["Frozen tasks are five draft/search/selection actions, not document save or system configuration."]}


def run_isolated(args):
    """Bound provider faults to one app while the lead guard remains alive."""
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    run_id = uuid.uuid4().hex
    area = ROOT / ".agent_control/c11-cohort" / run_id
    area.mkdir(parents=True)
    result = result_header(args, manifest_bytes, run_id)
    result["runnerMode"] = "one child process per app; continuous lead input guard"
    result["idleWaitRequired"] = False
    guard = ZeroDisturbanceGuard().start()
    result["guardBefore"] = guard.snapshot()
    try:
        for task in manifest["apps"]:
            row = {"app": task["app"], "category": task["category"], "scope": task["scope"],
                   "task": task["task"], "status": "not_selected", "attempts": []}
            result["apps"].append(row)
            if args.apps and task["app"] not in args.apps:
                row["reason"] = "Explicit subset run"
                continue
            if not guard.check()["ok"]:
                row.update(status="guard_refused", reason="Lead input guard failed; no child launch")
                continue
            child_receipt = area / (re.sub(r"[^a-zA-Z0-9]", "-", task["app"]) + ".json")
            log = child_receipt.with_suffix(".log")
            command = [sys.executable, "-B", str(Path(__file__).resolve()), "--single-process",
                       "--apps", task["app"], "--environment", args.environment,
                       "--launch-timeout", str(args.launch_timeout), "--receipt", str(child_receipt)]
            command += ["--manifest", str(args.manifest)]
            try:
                with log.open("wb") as stream:
                    process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                               creationflags=subprocess.CREATE_NO_WINDOW)
                    guard.register_pid(process.pid)
                    try:
                        code = process.wait(timeout=args.launch_timeout + 120)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        code = process.returncode
                        row["reason"] = "Owned app worker deadline; its kill-on-close job closes with it"
                if child_receipt.exists():
                    raw = json.loads(child_receipt.read_text(encoding="utf-8"))
                    selected = next((item for item in raw["apps"] if item["app"] == task["app"]), {})
                    row.update(selected)
                    row["childGuard"] = raw.get("guardAfter")
                    row["childSourceDrift"] = raw.get("sourceDrift")
                complete_child = bool(child_receipt.exists() and raw.get("summary")
                    and raw.get("guardAfter", {}).get("ok") and not raw.get("sourceDrift"))
                row["childProcess"] = {"pid": process.pid, "exitCode": code,
                    "receipt": child_receipt.relative_to(ROOT).as_posix(),
                    "log": log.relative_to(ROOT).as_posix(), "finalReceiptReturned": complete_child}
                if code not in {0, 2}:
                    row["verifiedBeforeCrash"] = row.get("passed", 0)
                    row.update(status="native_process_failed", passed=0,
                        reason=row.get("reason") or "Native app worker failed before a final certified receipt")
                elif not complete_child:
                    row["verifiedBeforeCertificationFailure"] = row.get("passed", 0)
                    row.update(status="receipt_uncertified", passed=0,
                        reason="Child receipt certification failed: " + (
                            "source changed during run" if row.get("childSourceDrift") else
                            "final summary or successful guard receipt missing"))
            except Exception as exc:
                row.update(status="failed", reason=f"{type(exc).__name__}: {exc}"[:300])
            row["leadGuardAfter"] = compact_guard(guard.snapshot())
            write_receipt(args.receipt, result)
            print(json.dumps({"app": row["app"], "status": row["status"], "passed": row.get("passed", 0),
                              "p50Ms": row.get("latency", {}).get("p50Ms"), "reason": row.get("reason")}), flush=True)
    finally:
        finish_result(result, manifest, guard, args)
    return result


def run(args):
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    run_id = uuid.uuid4().hex
    root = ROOT / ".agent_control/c11-cohort" / run_id
    root.mkdir(parents=True, exist_ok=True)
    result = result_header(args, manifest_bytes, run_id)
    # Paul may continue working: the guard attributes agent effects instead
    # of using a quiet input desktop as an acceptance precondition.
    result["idleWaitRequired"] = False
    guard = ZeroDisturbanceGuard().start()
    result["guardBefore"] = guard.snapshot()
    try:
        for task in manifest["apps"]:
            row = {"app": task["app"], "category": task["category"],
                   "scope": task["scope"], "task": task["task"],
                   "status": "unavailable", "attempts": []}
            result["apps"].append(row)
            worker = learning = None
            try:
                if args.apps and task["app"] not in args.apps:
                    row.update(status="not_selected", reason="Explicit subset run")
                    continue
                if not guard.check()["ok"]:
                    row.update(status="guard_refused", reason="Strict input desktop guard has failed; no launch")
                    continue
                exe = Path(task["exe"])
                if not exe.is_file():
                    row["reason"] = "Installed frozen executable absent"
                    continue
                fixture_token = uuid.uuid4().hex
                scratch = root / (re.sub(r"[^a-zA-Z0-9]", "-", task["app"]) + "-" + fixture_token)
                scratch.mkdir()
                row["fixture"] = {"path": str(scratch), "token": fixture_token,
                    "createdByAgent": True, "values": task["values"]}
                worker = NativeWorker(guard=guard)
                effective_environment = task.get('route', args.environment)
                process = None
                early_launch_at = None
                if effective_environment == 'agent-bureau':
                    # Worker lanes bind their desktop once. Establish Default
                    # Bureau containment before starting the UIA/MSAA threads.
                    launch = task_fixture_launch(task, exe, scratch)
                    row['launchPolicy'] = worker.launch_policy(launch)
                    early_launch_at = time.perf_counter()
                    process = worker.launch(launch, cwd=scratch, environment=effective_environment)
                warm_at = time.perf_counter()
                worker.request("windows", timeout=3)  # Only the empty private desktop.
                warm_deadline = time.monotonic() + 10
                lanes = {"uia": worker.fast_client.uia, "msaa": worker.fast_client.msaa,
                         "fieldPolicy": worker.fast_client.policy, "capture": worker.fast_client.capture}
                row["laneInitialization"] = {}
                for name, lane in lanes.items():
                    ready = lane.ready.wait(max(0, warm_deadline - time.monotonic()))
                    row["laneInitialization"][name] = {"ready": ready, "error": lane.error}
                row["driverStartupMs"] = round((time.perf_counter() - warm_at) * 1000, 2)
                if not guard.check()["ok"]:
                    row.update(status="guard_refused", reason="Guard failed during lane initialization; no app launch")
                    continue
                if process is None:
                    launch = task_fixture_launch(task, exe, scratch)
                row["launchPolicy"] = worker.launch_policy(launch)
                for index, arg in enumerate(launch):
                    profile = arg.split("=", 1)[1] if arg.startswith("--user-data-dir=") else (
                        launch[index + 1] if arg in {"--user-data-dir", "-profile"} and index + 1 < len(launch) else None)
                    if profile:
                        profile_path = Path(profile).resolve()
                        if not profile_path.is_relative_to(root):
                            raise ValueError("Disposable profile escaped the cohort root")
                        profile_path.mkdir(parents=True, exist_ok=True)
                started = early_launch_at or time.perf_counter()
                process_env = None
                if task.get("consoleFile") or task["app"] in {"Management Console", "Performance Monitor", "ODBC Data Sources", "Services", "Computer Management"}:
                    process_env = {"__COMPAT_LAYER": "RunAsInvoker"}
                    row["processCompatibility"] = {"layer": "RunAsInvoker", "scope": "task process only",
                        "privilege": "inherited unelevated token; no elevation request",
                        "taskBoundary": "Frozen read-only navigation; no configuration mutations"}
                if effective_environment == 'hidden-com':
                    raise DesktopIsolationError('Office document tasks use the hidden COM runner; UI is reserved for preview')
                if effective_environment == 'hidden-shell':
                    raise DesktopIsolationError('Disposable file tasks use scripts/prove_c11f_shell.py with CREATE_NO_WINDOW')
                if process is None:
                    process = worker.launch(launch, cwd=scratch, env=process_env, environment=effective_environment)
                row['transportPreparationMs'] = round(process.transport_initialization_ms, 3)
                row.update(launcherPid=process.pid, desktop=worker.desktop.name)
                title_token = fixture_token if task["app"] in {
                    "Notepad", "Paint", "Photos", "Snipping Tool", "Windows Terminal",
                    "Visual Studio Code", "Cursor", "Antigravity", "Microsoft Edge", "Google Chrome", "Mozilla Firefox", "Windows PowerShell ISE"} else None
                # ISE's small Windows Forms splash is not its WPF editor.
                minimum_size = (650, 450) if task["app"] == "Windows PowerShell ISE" else (250, 150)
                window = owned_window(worker, time.monotonic() + args.launch_timeout, title_token, minimum_size)
                row["startupMs"] = round((time.perf_counter() - started) * 1000, 2)
                if not window:
                    row['ownedWindowsAtDeadline'] = [
                        {key: candidate.get(key) for key in ('windowId', 'pid', 'title', 'className', 'bounds')}
                        for candidate in worker.request('windows', timeout=4)
                        if worker.desktop.owns(int(candidate['windowId']))
                        and worker.desktop.owns_pid(int(candidate['pid']))]
                    row.update(status="no_private_window", reason="No visible own-job window on private desktop before deadline",
                               launchExitCode=process.poll())
                    continue
                if task['app'] in {'Cursor', 'Antigravity'}:
                    window = stable_owned_editor(worker, window, fixture_token)
                window_id = window["windowId"]
                row["fixtureOwnership"] = worker.desktop.register_fixture(window_id, scratch, fixture_token)
                row["window"] = {key: window.get(key) for key in ("windowId", "pid", "className", "bounds")}
                row["window"]["ownJob"] = True
                row["window"]["privateDesktop"] = effective_environment == "agent-desktop"
                row["window"]["environment"] = effective_environment
                first_at = time.perf_counter()
                row["startupObservationErrors"] = []
                for read_attempt in range(3):
                    try:
                        observed = worker.request("inspect", {"windowId": window_id,
                            "maxDepth": 10, "maxNodes": 300}, timeout=4)
                        break
                    except (TimeoutError, OSError) as exc:
                        row["startupObservationErrors"].append(type(exc).__name__ + ": " + str(exc))
                        if read_attempt == 2:
                            raise
                        time.sleep(.01)
                row["firstObservationMs"] = round((time.perf_counter() - first_at) * 1000, 2)
                row["firstObservation"] = compact_observation(observed)
                row["initialNativeState"] = observed
                window, observed, prompt = dismiss_owned_startup_prompt(worker, task, window, observed, fixture_token)
                if prompt:
                    row["startupPrompt"] = prompt
                    window_id = window["windowId"]
                    row["window"] = {**window, "ownJob": True, "privateDesktop": args.environment == "agent-desktop", "environment": args.environment}
                    row["fixtureOwnership"] = worker.desktop.register_fixture(window_id, scratch, fixture_token)
                if task.get("setupKey"):
                    row['startupStage'] = 'before_setup_inspect'
                    row['beforeSetupErrors'] = []
                    for cold_read in range(8):
                        try:
                            row["beforeSetupNativeState"] = worker.request("inspect", {"windowId": window_id,
                                "maxDepth": 12, "maxNodes": 500}, timeout=4)
                            break
                        except (TimeoutError, OSError) as exc:
                            row['beforeSetupErrors'].append(type(exc).__name__ + ': ' + str(exc))
                            if cold_read == 7:
                                raise
                            time.sleep(.15)
                    row['startupStage'] = 'setup_action'
                    setup_at = time.perf_counter()
                    already_open = choose_task(row["beforeSetupNativeState"].get("tree", []), task, 0)
                    toolbar_find = [n for n in row["beforeSetupNativeState"].get("tree", [])
                        if n.get("role") in {"Button", "MenuItem"} and n.get("enabled", True)
                        and n.get("name", "").replace("&", "").strip().casefold() in {"find", "rechercher"}
                        and "invoke" in n.get("patterns", [])]
                    if task["app"] == "Microsoft Word" and len(toolbar_find) == 1:
                        find = toolbar_find[0]
                        setup = worker.request("action", {"windowId": window_id, "elementId": find["id"],
                            "action": "click", "expectedName": find["name"], "expectedRole": find["role"],
                            "allowForeground": False}, timeout=3)
                        row["setupTarget"] = selector(find)
                    else:
                        setup = worker.request("action", {"windowId": window_id, "action": "key",
                            "key": task["setupKey"], "allowForeground": False}, timeout=3)
                    row["setup"] = {"key": task["setupKey"], "effect": setup.get("effect"),
                        "mechanism": setup.get("mechanism"),
                        "elapsedMs": round((time.perf_counter() - setup_at) * 1000, 2)}
                row['startupStage'] = 'task_ready'
                observed, row["taskReadiness"] = task_ready(worker, task, window, args.launch_timeout)
                if row["taskReadiness"]["ready"]:
                    try:
                        learning = CohortLearning(worker, scratch, observed["window"])
                        row["firstUseManual"] = learning.adapt()
                        row["connectedLanguage"] = []
                        row["connectedLanguage"].append(learning.observe())
                    except Exception as exc:
                        row["learningError"] = f"{type(exc).__name__}: {exc}"[:400]
                run_actions(worker, task, window_id, row, learning)
            except DesktopIsolationError as exc:
                failures = row.get("launchPolicy", {}).get("layerFailures")
                status="isolation_unavailable" if row.get("launchPolicy",{}).get("status")=="isolation-unavailable" else "needs_permission" if failures else "isolation_refused"
                row.update(status=status, reason=str(exc)[:300])
            except Exception as exc:
                row.update(status="failed", reason=f"{type(exc).__name__}: {exc}"[:300])
            finally:
                if learning:
                    learning.close()
                elif worker:
                    worker.close()
                if worker:
                    row["cleanup"] = "Closed only own job/private desktop; fixtures retained"
                row["guardAfter"] = compact_guard(guard.snapshot())
                write_receipt(args.receipt, result)
                print(json.dumps({"app": row["app"], "status": row["status"], "passed": row.get("passed", 0),
                    "p50Ms": row.get("latency", {}).get("p50Ms"), "reason": row.get("reason")}), flush=True)
    finally:
        finish_result(result, manifest, guard, args)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apps", nargs="*")
    parser.add_argument("--manifest", type=Path, default=MANIFEST,
        help="Everyday disposable tasks by default; historical frozen manifests remain selectable")
    parser.add_argument("--single-process", action="store_true",
        help="Internal child lane; the default lead runner contains native provider faults per app")
    parser.add_argument("--environment", choices=("agent-desktop", "agent-bureau"), default="agent-desktop")
    parser.add_argument("--launch-timeout", type=float, default=10,
        help="Startup only, reported separately from action latency; override for slower apps")
    parser.add_argument("--receipt", type=Path, default=RECEIPT)
    args = parser.parse_args()
    if not 0 < args.launch_timeout <= 120:
        parser.error("Launch deadline must be > 0 and <= 120 seconds")
    result = run(args) if args.single_process else run_isolated(args)
    print(json.dumps({"summary": result["summary"], "gates": result["gates"], "complete": result["complete"]}))
    raise SystemExit(0 if result["complete"] else 2)
