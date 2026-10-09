"""Real, disposable Windows application action cohort for the C1b driver.

Runs only in windows attributed to a launch by this script. Latency samples are
observe -> act -> verify, including failed attempts, never read-only snapshots.
Use --freeze to write the identical task/check manifest for other driver arms.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.cua_native import NativeWorker
from c1_native_benchmark import CATALOG, launch_args, selected_path

MANIFEST = ROOT / "scripts/evidence/C1-tasks.json"
RECEIPT = ROOT / "scripts/evidence/C1c-apps.json"
SCRATCH = ROOT / ".agent_control/c1c-apps"

# Utility tasks change the application's session view, never OS configuration.
# Their scope is reported separately from document edits and local form tasks.
TASKS = {
    "Notepad": ("draft_edit", "Write five distinct notes in a disposable document", "value", "Edit|Document", "", None),
    "Calculator": ("calculation", "Enter five distinct digits and verify the displayed result", "calculator", "Button", "", None),
    "Paint": ("tool_selection", "Select five drawing tools in a fresh blank canvas", "select", "RadioButton|TabItem|ListItem", "", None),
    "Character Map": ("symbol_composition", "Compose five distinct character strings in Characters to copy", "value", "Edit", "cop|Copy|caract|character", None),
    "File Explorer": ("folder_search", "Enter five searches in a disposable folder", "value", "Edit", "search|recherch", None),
    "Control Panel": ("settings_search", "Enter five settings searches without changing any setting", "value", "Edit", "search|recherch", None),
    "Management Console": ("console_navigation", "Expand/collapse the fresh console tree without saving", "expand", "TreeItem", "", None),
    "Task Manager": ("process_search", "Enter five process filters without ending any process", "value", "Edit", "search|recherch", None),
    "Performance Monitor": ("report_navigation", "Select five report categories without starting collectors", "select", "TreeItem", "", None),
    "System Information": ("system_search", "Enter five Find queries in the new report window", "value", "Edit", "", None),
    "Git GUI": ("commit_draft", "Write five draft messages in a disposable empty repository; never commit", "value", "Edit|Document", "", None),
    "Visual Studio Code": ("document_search", "Search five fixture phrases in a disposable editor profile", "value", "Edit|Document", "find|recherch|search", "CTRL+F"),
    "Microsoft Edge": ("local_form", "Fill the local C1 note form five times in a disposable browser profile", "value", "Edit", "C1 note", None),
    "Google Chrome": ("local_form", "Fill the same local C1 note form five times in a disposable browser profile", "value", "Edit", "C1 note", None),
    "Mozilla Firefox": ("local_form", "Fill the same local C1 note form five times in a disposable browser profile", "value", "Edit", "C1 note", None),
    "Microsoft Excel": ("cell_navigation", "Enter five cell addresses in the disposable workbook Name box", "value", "Edit|ComboBox", "name|nom", None),
    "Microsoft Word": ("document_search", "Search five fixture phrases in a disposable document", "value", "Edit", "find|search|recherch", "CTRL+F"),
    "Microsoft PowerPoint": ("slide_search", "Search five fixture phrases in a disposable presentation", "value", "Edit", "find|search|recherch", "CTRL+F"),
    "Color Management": ("report_navigation", "Switch five device/profile report tabs without changing defaults", "select", "TabItem", "", None),
    "ODBC Data Sources": ("report_navigation", "Switch five data-source report tabs without creating/deleting sources", "select", "TabItem", "", None),
    "DirectX Diagnostic Tool": ("report_navigation", "Switch five diagnostic report tabs without saving/exporting", "select", "TabItem", "", None),
    "Optimize Drives": ("drive_selection", "Select five listed drives without Analyze/Optimize", "select", "ListItem|DataItem", "", None),
}


def freeze() -> dict:
    catalog = {name: (path, kind) for name, path, kind in CATALOG}
    apps = []
    for name, (scope, purpose, action, roles, pattern, setup) in TASKS.items():
        path, kind = catalog[name]
        found = selected_path(name, path)
        apps.append({"app": name, "exe": str(found or path), "available": bool(found),
                     "category": kind, "scope": scope, "task": purpose,
                     "repetitions": 5, "action": action,
                     "target": {"rolesRegex": roles, "nameRegex": pattern},
                     "setupKey": setup,
                     "values": ["A1", "B1", "A2", "B2", "C1"] if name == "Microsoft Excel"
                               else [f"C1 note {i}" for i in range(1, 6)],
                     "check": "Fresh observed target value equals typed value; selection/toggle/expand checks require a changed state. Calculator display must contain the entered digit.",
                     "mutationBoundary": "Only new window, owned fixture document or disposable profile; no user documents/settings.",
                     "competitorPolicy": "allowed"})
    data = {"schema": "neyvia.c1b.matched-tasks.v1", "createdAt": datetime.now(timezone.utc).isoformat(),
            "fixtureRoot": str(SCRATCH), "repetitions": 5,
            "timing": "Atomic fresh target observation -> action -> verified readback. Include unsuccessful attempts in per-app p50/p95; startup/setup excluded and separately reported.",
            "cleanup": "Close only launched HWNDs; never kill an existing process. Leave generated fixtures recoverable.",
            "arms": {"neyvia": "scripts/verify_c1b_apps.py", "claude": "Lead runs same tasks/checks; record exact attempts, failures, latency and screenshots.",
                     "openai": "Documented @oai/sky through provided node_repl; no custom helper protocol."},
            "apps": apps}
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def win32_windows(*, include_rejected: bool = False) -> list[dict]:
    """No desktop UIA calls and no property queries to unresponsive windows."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsHungAppWindow.argtypes = [wintypes.HWND]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    rows = []
    @callback_type
    def visit(hwnd, _):
        visible = bool(user.IsWindowVisible(hwnd))
        hung = bool(user.IsHungAppWindow(hwnd))
        if not include_rejected and (not visible or hung):
            return True
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        text = ctypes.create_unicode_buffer(user.GetWindowTextLengthW(hwnd) + 1)
        user.GetWindowTextW(hwnd, text, len(text))
        cls = ctypes.create_unicode_buffer(260)
        user.GetClassNameW(hwnd, cls, len(cls))
        if text.value or include_rejected:
            rows.append({"windowId": str(hwnd), "pid": pid.value, "title": text.value, "class": cls.value,
                         "visible": visible, "hung": hung})
        return True
    user.EnumWindows(visit, 0)
    return rows


def app_launch(name: str, exe: Path, scratch: Path) -> list[str]:
    token = scratch.name.rsplit("-", 1)[-1]
    if name == "Git GUI":
        subprocess.run(["C:/Program Files/Git/cmd/git.exe", "init", "--quiet", str(scratch)],
                       check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    args = launch_args(name, exe, scratch)
    # Every launched document has a run-specific title as well as content.
    # The original filenames are only temporary fixture-generator outputs.
    for original in ("c1-notepad.txt", "c1-office.xlsx", "c1-office.docx", "c1-office.pptx", "c1-browser.html"):
        source = scratch / original
        if source.is_file():
            target = scratch / ("c11-" + token + source.suffix)
            source.rename(target)
            args = [str(target) if arg == str(source) else target.as_uri() if arg == source.as_uri() else arg for arg in args]
    if name in {"Microsoft Edge", "Google Chrome", "Mozilla Firefox"}:
        page = scratch / ("c11-" + token + ".html")
        page.write_text('<!doctype html><meta charset="utf-8"><title>C11 ' + token + '</title><h1>C11 ' + token + '</h1>'
                        '<label>C1 note <input id="note" aria-label="C1 note"></label>'
                        '<button onclick="document.querySelector(\'output\').textContent=note.value">Apply note</button><output></output>', encoding="utf-8")
        if name != "Mozilla Firefox":
            args += ["--force-renderer-accessibility", "--disable-gpu", "--disable-features=Translate", "--new-window",
                "--remote-debugging-port=48703", "--remote-allow-origins=http://127.0.0.1:48703"]
        else:
            profile = scratch / "firefox-profile"
            profile.mkdir(exist_ok=True)
            (profile / "user.js").write_text('user_pref("accessibility.force_disabled", -1);\nuser_pref("browser.shell.checkDefaultBrowser", false);\nuser_pref("browser.startup.homepage_override.mstone", "ignore");\n', encoding="utf-8")
    if name == "Visual Studio Code":
        document = scratch / ("c11-" + token + ".txt")
        document.write_text(token + "\n" + "\n".join(f"C1 note {i}" for i in range(1, 6)), encoding="utf-8")
        args += ["--new-window", "--remote-debugging-port=48704",
            "--remote-allow-origins=http://127.0.0.1:48704", str(document)]
    if name == "Notepad":
        Path(args[-1]).write_text(token + "\nC1 disposable native benchmark.\n", encoding="utf-8")
    if name == "Windows PowerShell ISE":
        document = scratch / ("c11-" + token + ".ps1")
        document.write_text("# " + token + "\n# Disposable command-search fixture.\n", encoding="utf-8")
        args = [str(exe), "-NoProfile", "-File", str(document)]
    if name == "Remote Desktop Connection":
        document = scratch / ("c11-" + token + ".rdp")
        document.write_text("full address:s:c11-" + token + ".invalid\n", encoding="utf-8")
        args = [str(exe), "/edit", str(document)]
    return args


def launched_window(pid: int, exe: Path, before: set[str], marker: str | None, timeout: float) -> dict | None:
    import psutil
    until = time.monotonic() + timeout
    launched_at = time.time()
    known = {"calc.exe": {"calc.exe", "calculatorapp.exe"}, "mspaint.exe": {"mspaint.exe"}}.get(exe.name.casefold(), {exe.name.casefold()})
    while time.monotonic() < until:
        descendants = {pid}
        try:
            descendants.update(p.pid for p in psutil.Process(pid).children(recursive=True))
        except psutil.Error:
            pass
        matches = []
        for window in win32_windows():
            if window["windowId"] in before:
                continue
            owned = window["pid"] in descendants
            if not owned:
                try:
                    target = psutil.Process(window["pid"])
                    owned = Path(target.exe()).name.casefold() in known and target.create_time() >= launched_at - 2
                except psutil.Error:
                    pass
            # A unique fixture filename also proves a fresh single-instance
            # app window, but never grants authority over its older siblings.
            if marker and marker.casefold() in window["title"].casefold():
                try:
                    owner = Path(psutil.Process(window["pid"]).exe()).name.casefold()
                    owned = owner == exe.name.casefold() or owner in {"notepad.exe", "explorer.exe"}
                except psutil.Error:
                    pass
            if owned:
                matches.append(window)
        if matches:
            # Largest owned HWND tends to be the work surface, not a splash.
            user = ctypes.WinDLL("user32")
            user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            def area(window):
                bounds = wintypes.RECT()
                user.GetWindowRect(int(window["windowId"]), ctypes.byref(bounds))
                return max(0, bounds.right-bounds.left)*max(0, bounds.bottom-bounds.top)
            return max(matches, key=area)
        time.sleep(.1)
    return None


def choose(tree: list[dict], task: dict, repeat: int) -> dict | None:
    roles = task["target"]["rolesRegex"]
    labels = task["target"]["nameRegex"]
    candidates = [node for node in tree if re.fullmatch(roles, node.get("role", ""))
                  and node.get("enabled", True) and not node.get("isPassword")
                  and not node.get("offscreen")
                  and not node.get("protectionUnknown")]
    if labels:
        preferred = [node for node in candidates if re.search(labels, node.get("name", ""), re.I)]
        # Never fall back to an unrelated editable field (address bar, settings).
        candidates = preferred
    action = task["action"]
    if action == "value":
        return next((node for node in candidates if not node.get("readOnly")
                     and ("value" in [str(p).lower() for p in node.get("patterns", [])]
                     or node.get("id", "").startswith("win32:"))), None)
    if action == "select":
        # A changed-state task needs a known unselected starting state, not
        # an omitted provider property interpreted as False.
        candidates = [node for node in candidates
                      if node.get("selected", node.get("isSelected")) is False]
        return candidates[repeat % len(candidates)] if candidates else None
    if action == "calculator":
        digit = str(repeat + 1)
        return next((n for n in candidates if n.get("name") == digit
                     or n.get("automationId") == "num" + digit + "Button"), None)
    return candidates[0] if candidates else None


def selector(node: dict) -> dict:
    # Runtime IDs are exact and stay scoped to the admitted window.
    return {"id": node["id"], "role": node.get("role", ""), "name": node.get("name", "")}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    pos = (len(data) - 1) * q
    a = int(pos)
    return round(data[a] + (data[min(a + 1, len(data)-1)] - data[a]) * (pos-a), 2)


def run(args, manifest):
    raise RuntimeError("Historical input-desktop runner disabled. Use scripts/run_c11_cohort.py")
    run_id = uuid.uuid4().hex
    root = SCRATCH / run_id
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    worker = None
    result = {"schema": "neyvia.c1b.app-actions.v1", "at": datetime.now(timezone.utc).isoformat(),
              "runId": run_id, "taskManifestSha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
              "timingIncludes": "Fresh inspect + cycle(action+check), including failures; startup/setup excluded",
              "apps": rows, "limitations": ["Navigation/search preparation tasks are labelled by scope, not claimed as document save or system configuration."]}
    try:
        for task in manifest["apps"]:
            if args.apps and task["app"] not in args.apps:
                continue
            row = {"app": task["app"], "scope": task["scope"], "task": task["task"], "attempts": [], "status": "unavailable"}
            rows.append(row)
            exe = Path(task["exe"])
            if not exe.is_file():
                row["reason"] = "Installed executable absent"
                continue
            scratch = root / re.sub(r"[^a-zA-Z0-9]", "-", task["app"])
            scratch.mkdir()
            window = None
            process = None
            try:
                worker = NativeWorker()
                row["foregroundBeforeLaunch"] = worker.request("status", timeout=30)
                before = {w["windowId"] for w in win32_windows()}
                launch = app_launch(task["app"], exe, scratch)
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 4
                start = time.perf_counter()
                process = subprocess.Popen(launch, cwd=scratch, startupinfo=startup,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                row["launcherPid"] = process.pid
                marker = {"Notepad": "c1-notepad.txt", "File Explorer": scratch.name,
                          "Microsoft Excel": "c1-office.xlsx", "Microsoft Word": "c1-office.docx",
                          "Microsoft PowerPoint": "c1-office.pptx"}.get(task["app"])
                window = launched_window(process.pid, exe, before, marker, args.launch_timeout)
                row["startupMs"] = round((time.perf_counter() - start) * 1000, 2)
                if window is None:
                    row["reason"] = "No fresh visible nonhung window attributed to launch; existing windows preserved"
                    row["launchExitCode"] = process.poll()
                    row["rejectedOwnedWindows"] = [w for w in win32_windows(include_rejected=True) if w["pid"] == process.pid]
                    continue
                row["window"] = window
                # Some inbox launchers ignore SW_SHOWNOACTIVATE. Restore only
                # if the launch owns foreground and no physical input occurred.
                after_launch = worker.request("status", timeout=3)
                prior = row["foregroundBeforeLaunch"]
                row["launchPreservedForeground"] = after_launch["foregroundWindowId"] == prior["foregroundWindowId"]
                if not row["launchPreservedForeground"] and after_launch["foregroundWindowId"] == window["windowId"] and after_launch["inputGeneration"] == prior["inputGeneration"]:
                    user = ctypes.WinDLL("user32")
                    user.SetForegroundWindow.argtypes = [wintypes.HWND]
                    user.SetForegroundWindow(int(prior["foregroundWindowId"]))
                    row["launchForegroundRestored"] = worker.request("status")["foregroundWindowId"] == prior["foregroundWindowId"]
                if task["setupKey"]:
                    worker.request("action", {"windowId": window["windowId"], "action": "key",
                                              "key": task["setupKey"], "allowForeground": False}, timeout=3)
                # First observation includes cache warm-up readiness separately.
                first_start = time.perf_counter()
                for _ in range(10):
                    obs = worker.request("inspect", {"windowId": window["windowId"], "maxDepth": 10, "maxNodes": 300}, timeout=4)
                    if choose(obs.get("tree", []), task, 0):
                        break
                    time.sleep(.15)
                row["firstObservation"] = {"source": obs.get("source"), "nodeCount": len(obs.get("tree", [])),
                                           "truncated": obs.get("truncated"), "tree": obs.get("tree", [])}
                row["firstObservationMs"] = round((time.perf_counter() - first_start) * 1000, 2)
                row["status"] = "attempted"
                for repetition in range(args.repeats):
                    attempt = {"repetition": repetition + 1, "passed": False, "actionSent": False}
                    row["attempts"].append(attempt)
                    start = time.perf_counter()
                    try:
                        obs = worker.request("inspect", {"windowId": window["windowId"], "maxDepth": 10, "maxNodes": 300}, timeout=4)
                        node = choose(obs.get("tree", []), task, repetition)
                        if node is None:
                            attempt["error"] = "No safe fresh actionable target; no mutation sent"
                            continue
                        action = task["action"]
                        check = {"selector": selector(node)}
                        request = {"windowId": window["windowId"], "elementId": node["id"], "allowForeground": False}
                        if action == "value":
                            request.update(action="value", text=task["values"][repetition % 5])
                            check["value_equals"] = request["text"]
                        elif action == "select":
                            request["action"] = "select"
                            check["selected_equals"] = True
                        elif action == "expand":
                            is_expanded = node.get("expanded", node.get("expandState") == 1)
                            request["action"] = "collapse" if is_expanded else "expand"
                            check["expand_equals"] = 0 if is_expanded else 1
                        elif action == "calculator":
                            request["action"] = "click"
                            check = {"selector": {"automationId": "CalculatorResults"}, "name_contains": str(repetition + 1)}
                        request["expect"] = [check]
                        attempt["actionSent"] = True
                        response = worker.request("cycle", request, timeout=4)
                        if "observation" in response:
                            observation = response["observation"]
                            response["observation"] = {k: observation.get(k) for k in ("source", "revision", "events", "eventsSubscribed", "degradedReason", "elapsedMs")}
                        attempt.update(target=selector(node), request=request, response=response,
                                       passed=response.get("effect") == "confirmed"
                                       and response.get("check", {}).get("status") == "satisfied"
                                       and response.get("foregroundPreserved") is True)
                    except Exception as exc:
                        attempt["error"] = f"{type(exc).__name__}: {exc}"
                    finally:
                        attempt["atomicMs"] = round((time.perf_counter() - start) * 1000, 2)
                values = [a["atomicMs"] for a in row["attempts"] if a["actionSent"]]
                row["latency"] = {"n": len(values), "p50Ms": percentile(values, .5), "p95Ms": percentile(values, .95),
                                  "includesFailures": True, "excludesNoActionObservations": True}
                row["passed"] = sum(a["passed"] for a in row["attempts"])
                row["status"] = "passed" if row["passed"] == args.repeats else "partial" if row["passed"] else "failed"
            except Exception as exc:
                row["reason"] = f"{type(exc).__name__}: {exc}"
                row["status"] = "failed"
            finally:
                if window:
                    # WM_CLOSE is sent only to the exact new HWND. No process
                    # termination, so older windows/sessions cannot be killed.
                    user = ctypes.WinDLL("user32", use_last_error=True)
                    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                    user.PostMessageW(int(window["windowId"]), 0x0010, 0, 0)
                    row["cleanup"] = "WM_CLOSE sent to newly launched HWND; unsaved prompts/fixtures retained"
                if worker:
                    row["foregroundAfter"] = worker.request("status", timeout=3)
                    worker.close()
                    worker = None
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                args.receipt.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                print(json.dumps({"app": row["app"], "status": row["status"], "passed": row.get("passed", 0),
                                  "p50Ms": row.get("latency", {}).get("p50Ms"), "reason": row.get("reason")}), flush=True)
    finally:
        if worker:
            worker.close()
        result["summary"] = {"appsAttempted": sum(any(a.get("actionSent") for a in r["attempts"]) for r in rows),
                             "appsWithVerifiedAction": sum(r.get("passed", 0) > 0 for r in rows),
                             "verifiedActions": sum(r.get("passed", 0) for r in rows),
                             "attempts": sum(a.get("actionSent", False) for r in rows for a in r["attempts"]),
                             "observationsWithoutAction": sum(not a.get("actionSent", False) for r in rows for a in r["attempts"])}
        args.receipt.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true", help="Write task/check manifest without launching apps")
    parser.add_argument("--apps", nargs="*")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--launch-timeout", type=float, default=10)
    parser.add_argument("--receipt", type=Path, default=RECEIPT)
    args = parser.parse_args()
    if args.freeze:
        parser.error("C1-tasks.json is frozen; this runner cannot rewrite it")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if args.freeze:
        print(json.dumps({"manifest": str(MANIFEST), "apps": len(manifest["apps"]), "installed": sum(t["available"] for t in manifest["apps"])}))
    else:
        print(json.dumps(run(args, manifest)["summary"]))
