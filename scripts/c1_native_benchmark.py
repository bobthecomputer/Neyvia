"""Bounded C1 Windows app benchmark using only windows launched by this run.

The cohort is deliberately conservative: a single-instance app that hands its
window to a pre-existing process is skipped, never inspected. No desktop-wide
capture or user-window tree is retained. Run with the system Python.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.cua_native import NativeWorker

SYSTEM = Path(os.environ.get("WINDIR", "C:/Windows"))
SCRATCH = ROOT / ".agent_control" / "c1-native-benchmark"
RECEIPT = ROOT / "scripts" / "evidence" / "C1-native-benchmark.json"
PUBLIC_RECEIPT = ROOT / "scripts" / "evidence" / "C1-public-freeze.json"
PUBLIC_TASK = "4188d3a4-077d-46b7-9c86-23e1a036f6c1"
PUBLIC_TASK_SHA256 = "d682104aa50b97e32e42574a9a589c56e718711368a0e61279b5e437f513e5d7"
PUBLIC_TASK_URL = f"https://raw.githubusercontent.com/xlang-ai/OSWorld/main/evaluation_examples/examples_windows/excel/{PUBLIC_TASK}.json"

# Explicit executable paths avoid PATH aliases, application URLs and profile reuse.
# The cohort spans editors, utilities, shells, file management and system tools.
CATALOG = (
    ("Notepad", SYSTEM / "System32/notepad.exe", "editor"),
    ("Calculator", SYSTEM / "System32/calc.exe", "calculator"),
    ("Paint", SYSTEM / "System32/mspaint.exe", "graphics"),
    ("Character Map", SYSTEM / "System32/charmap.exe", "accessory"),
    ("On-Screen Keyboard", SYSTEM / "System32/osk.exe", "accessibility"),
    ("Command Prompt", SYSTEM / "System32/cmd.exe", "shell"),
    ("Windows PowerShell", SYSTEM / "System32/WindowsPowerShell/v1.0/powershell.exe", "shell"),
    ("File Explorer", SYSTEM / "explorer.exe", "file_manager"),
    ("Control Panel", SYSTEM / "System32/control.exe", "system"),
    ("Management Console", SYSTEM / "System32/mmc.exe", "system"),
    ("Task Manager", SYSTEM / "System32/Taskmgr.exe", "system"),
    ("Performance Monitor", SYSTEM / "System32/perfmon.exe", "system"),
    ("System Information", SYSTEM / "System32/msinfo32.exe", "system"),
    ("About Windows", SYSTEM / "System32/winver.exe", "system"),
    ("Git GUI", Path("C:/Program Files/Git/cmd/git-gui.exe"), "developer"),
    ("Visual Studio Code", Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe", "developer"),
    ("Microsoft Edge", Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"), "browser"),
    ("Google Chrome", Path("C:/Program Files/Google/Chrome/Application/chrome.exe"), "browser"),
    ("Mozilla Firefox", Path("C:/Program Files/Mozilla Firefox/firefox.exe"), "browser"),
    ("Microsoft Excel", Path("C:/Program Files/Microsoft Office/root/Office16/EXCEL.EXE"), "office"),
    ("Microsoft Word", Path("C:/Program Files/Microsoft Office/root/Office16/WINWORD.EXE"), "office"),
    ("Microsoft PowerPoint", Path("C:/Program Files/Microsoft Office/root/Office16/POWERPNT.EXE"), "office"),
    ("Windows Features", SYSTEM / "System32/optionalfeatures.exe", "system"),
    ("Color Management", SYSTEM / "System32/colorcpl.exe", "system"),
    ("Private Character Editor", SYSTEM / "System32/eudcedit.exe", "graphics"),
    ("Font Viewer", SYSTEM / "System32/fontview.exe", "accessory"),
    ("ODBC Data Sources", SYSTEM / "System32/odbcad32.exe", "system"),
    ("DirectX Diagnostic Tool", SYSTEM / "System32/dxdiag.exe", "system"),
    ("Optimize Drives", SYSTEM / "System32/dfrgui.exe", "system"),
    ("PowerShell 7", Path("C:/Program Files/PowerShell/7/pwsh.exe"), "shell"),
    ("7-Zip File Manager", Path("C:/Program Files/7-Zip/7zFM.exe"), "archive"),
    ("VLC", Path("C:/Program Files/VideoLAN/VLC/vlc.exe"), "media"),
    ("Inkscape", Path("C:/Program Files/Inkscape/bin/inkscape.exe"), "graphics"),
)


def quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    return round(ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (position - low), 2)


def summary(values: list[float]) -> dict:
    return {"n": len(values), "p50Ms": quantile(values, .5), "p95Ms": quantile(values, .95)}


def selected_path(name: str, path: Path) -> Path | None:
    # Two Windows inbox programs moved to Store aliases on some installations.
    if path.is_file():
        return path
    aliases = {
        "Paint": Path.home() / "AppData/Local/Microsoft/WindowsApps/mspaint.exe",
        "PowerShell 7": Path.home() / "AppData/Local/Microsoft/WindowsApps/pwsh.exe",
    }
    candidate = aliases.get(name)
    return candidate if candidate and candidate.is_file() else None


def launch_args(name: str, exe: Path, scratch: Path) -> list[str]:
    if name == "Microsoft Excel":
        from openpyxl import Workbook
        document = scratch / "c1-office.xlsx"
        book = Workbook()
        book.active["A1"] = "C1 disposable benchmark"
        book.save(document)
        return [str(exe), "/x", str(document)]
    if name == "Microsoft Word":
        from docx import Document
        document = scratch / "c1-office.docx"
        book = Document()
        book.add_paragraph("C1 disposable benchmark")
        book.save(document)
        return [str(exe), "/n", str(document)]
    if name == "Microsoft PowerPoint":
        from pptx import Presentation
        document = scratch / "c1-office.pptx"
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(0, 0, 1000000, 400000).text = "C1 disposable benchmark"
        deck.save(document)
        return [str(exe), str(document)]
    page = scratch / "c1-browser.html"
    if name in {"Microsoft Edge", "Google Chrome", "Mozilla Firefox"}:
        page.write_text("<!doctype html><title>C1 disposable browser</title><h1>C1 local benchmark</h1>", encoding="utf-8")
        if name == "Mozilla Firefox":
            return [str(exe), "-no-remote", "-profile", str(scratch / "firefox-profile"),
                    "-new-window", page.as_uri()]
        return [str(exe), "--user-data-dir=" + str(scratch / ("edge-profile" if name == "Microsoft Edge" else "chrome-profile")),
                "--no-first-run", "--disable-sync", "--disable-background-networking", page.as_uri()]
    if name == "Notepad":
        document = scratch / "c1-notepad.txt"
        document.write_text("C1 disposable native benchmark.\n", encoding="utf-8")
        return [str(exe), str(document)]
    if name == "File Explorer":
        return [str(exe), str(scratch)]
    if name == "Font Viewer":
        return [str(exe), str(SYSTEM / "Fonts/arial.ttf")]
    if name == "Command Prompt":
        return [str(exe), "/k", "title C1 Disposable Command Prompt"]
    if name == "Windows PowerShell" or name == "PowerShell 7":
        return [str(exe), "-NoLogo", "-NoProfile", "-NoExit", "-Command", "$Host.UI.RawUI.WindowTitle='C1 Disposable PowerShell'"]
    if name == "Management Console":
        return [str(exe), "/a"]
    if name == "Git GUI":
        return [str(exe)]
    if name == "Visual Studio Code":
        return [str(exe), "--user-data-dir", str(scratch / "vscode-profile"),
                "--extensions-dir", str(scratch / "vscode-extensions"), "--disable-extensions", str(scratch)]
    return [str(exe)]


def owned_window(worker: NativeWorker, name: str, pid: int, expected_exe: Path, started: float,
                 before_ids: set[int], before_app_present: bool, marker: str | None,
                 seconds: float = 9) -> dict | None:
    deadline = time.monotonic() + seconds
    known_exes = {
        "Calculator": {"calc.exe", "calculatorapp.exe"},
        "Paint": {"mspaint.exe"},
        "PowerShell 7": {"pwsh.exe"},
    }.get(name, {expected_exe.name.casefold()})
    while time.monotonic() < deadline:
        for window in worker.request("windows", timeout=8):
            if int(window.get("windowId") or 0) in before_ids:
                continue
            exe = window.get("exe")
            stamp = window.get("processStartTime")
            if not exe or not stamp or Path(exe).name.casefold() not in known_exes:
                continue
            try:
                from datetime import datetime
                fresh_process = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() >= started - 1
            except ValueError:
                continue
            exact_pid = int(window.get("pid") or 0) == pid
            # Scratch path/title is an unguessable ownership marker for apps
            # which explicitly open the disposable file or folder. Otherwise
            # admit only a new HWND in a newly created known app process.
            marked = bool(marker and marker.casefold() in (window.get("title") or "").casefold())
            if name.startswith("Microsoft ") and name in {"Microsoft Excel", "Microsoft Word", "Microsoft PowerPoint"} and not marked:
                continue
            if not (marked or fresh_process and (exact_pid or not before_app_present)
                    and name not in {"Notepad", "File Explorer"}):
                continue
            if not window.get("minimized") and window.get("title"):
                return window
        time.sleep(.15)
    return None


def compact_window(window: dict) -> dict:
    return {key: window.get(key) for key in ("windowId", "pid", "processName", "exe", "title", "processStartTime", "minimized")}


def cleanup_child(window: dict | None, launcher_pid: int, launched_at: float) -> str:
    if not window or int(window["pid"]) == launcher_pid:
        return "launcher_only"
    # psutil is available in this local runtime; its Process object retains
    # identity across PID reuse. Never terminate a pre-existing app process.
    try:
        import psutil
        child = psutil.Process(int(window["pid"]))
        if child.create_time() < launched_at - 1:
            return "preexisting_process_preserved"
        if os.path.normcase(child.exe()) != os.path.normcase(window.get("exe") or ""):
            return "identity_mismatch_preserved"
        child.terminate()
        child.wait(timeout=3)
        return "owned_child_terminated"
    except (ImportError, OSError, Exception) as exc:
        return "child_cleanup_unavailable: " + type(exc).__name__


def native_status(worker: NativeWorker) -> dict:
    status = worker.request("status", timeout=8)
    return {key: status.get(key) for key in ("foregroundWindowId", "foregroundGeneration", "cursor", "inputGeneration", "hooksReady")}


def preserved(before: dict, after: dict) -> dict:
    return {
        "foreground": before.get("foregroundWindowId") == after.get("foregroundWindowId")
        and before.get("foregroundGeneration") == after.get("foregroundGeneration"),
        "cursor": before.get("cursor") == after.get("cursor"),
        "physicalInput": before.get("inputGeneration") == after.get("inputGeneration"),
    }


def inspect_owned(worker: NativeWorker, window: dict) -> tuple[dict, float]:
    started = time.perf_counter()
    observation = worker.request("inspect", {"windowId": str(window["windowId"]), "maxDepth": 5, "maxNodes": 80}, timeout=15)
    elapsed = (time.perf_counter() - started) * 1000
    if int(observation["window"]["pid"]) != int(window["pid"]):
        raise RuntimeError("Window owner changed during inspection")
    return observation, round(elapsed, 2)


def scratch_action(worker: NativeWorker, name: str, window: dict, observation: dict) -> dict:
    """Only edit the disposable Notepad document when a suitable UIA field exists."""
    if name != "Notepad":
        return {"status": "not_attempted", "reason": "Read-only application cohort"}
    choices = [node for node in observation.get("tree", []) if not node.get("isPassword")
               and node.get("enabled") and "value" in (node.get("patterns") or [])
               and node.get("role") in {"Edit", "Document"}]
    if not choices:
        return {"status": "unavailable", "reason": "No safe UIA editable document"}
    node = choices[0]
    marker = " C1 probe " + str(time.time_ns())
    old = node.get("value") or ""
    before = native_status(worker)
    start = time.perf_counter()
    result = worker.request("action", {"windowId": str(window["windowId"]), "elementId": node["id"],
        "action": "value", "text": old + marker}, timeout=15)
    action_ms = round((time.perf_counter() - start) * 1000, 2)
    check, verify_ms = inspect_owned(worker, window)
    after = native_status(worker)
    verified = any(item.get("id") == node["id"] and item.get("value") == old + marker for item in check["tree"])
    return {"status": "passed" if verified else "failed", "actionMs": action_ms,
        "verifyMs": verify_ms, "roundTripMs": round(action_ms + verify_ms, 2),
        "driverEffect": result.get("effect"), "delivery": result.get("delivery"),
        "preservation": preserved(before, after), "markerSha256": hashlib.sha256(marker.encode()).hexdigest()}


def run(names: set[str] | None, receipt: Path, observation_repeats: int) -> dict:
    scratch = SCRATCH / str(time.time_ns())
    scratch.mkdir(parents=True, exist_ok=True)
    worker = NativeWorker()
    rows: list[dict] = []
    cold, warm, roundtrips = [], [], []
    try:
        worker.request("status", timeout=30)  # Worker startup is outside per-app timing.
        for name, intended, category in CATALOG:
            if names is not None and name not in names:
                continue
            row = {"app": name, "category": category, "requestedExe": str(intended), "status": "skipped"}
            rows.append(row)
            exe = selected_path(name, intended)
            if exe is None:
                row["reason"] = "Executable absent"
                continue
            row["exe"] = str(exe)
            process = None
            window = None
            started = 0.0
            try:
                if name == "Git GUI":
                    git = Path("C:/Program Files/Git/cmd/git.exe")
                    if not git.is_file():
                        row["reason"] = "Git executable absent"
                        continue
                    subprocess.run([str(git), "init", "--quiet", str(scratch)], check=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 4  # SW_SHOWNOACTIVATE
                launch_before = native_status(worker)
                before_windows = worker.request("windows", timeout=8)
                before_ids = {int(w["windowId"]) for w in before_windows}
                stems = {exe.stem.casefold()}
                if name == "Calculator":
                    stems.add("calculatorapp")
                before_app_present = any((w.get("processName") or "").casefold() in stems
                                         for w in before_windows)
                started = time.time()
                flags = subprocess.CREATE_NEW_CONSOLE if category == "shell" else 0
                process = subprocess.Popen(launch_args(name, exe, scratch), cwd=scratch,
                    startupinfo=startup, creationflags=flags)
                marker = ("c1-notepad.txt" if name == "Notepad" else
                          scratch.name if name == "File Explorer" else
                          "c1-office" if category == "office" else None)
                window = owned_window(worker, name, process.pid, exe, started, before_ids,
                                      before_app_present, marker)
                launch_after = native_status(worker)
                row["launchPreservation"] = preserved(launch_before, launch_after)
                row["launcherPid"] = process.pid
                if window is None:
                    row["reason"] = "No visible window owned by launched PID; existing-process handoff or no UI"
                    continue
                row["window"] = compact_window(window)
                before = native_status(worker)
                observation, first_ms = inspect_owned(worker, window)
                after = native_status(worker)
                row["firstObserveMs"] = first_ms
                row["firstObservePreservation"] = preserved(before, after)
                row["nodeCount"] = len(observation.get("tree", []))
                row["truncated"] = observation.get("truncated", False)
                # Never persist raw text/value or a screenshot from a native app.
                row["roles"] = sorted({item.get("role") for item in observation["tree"] if item.get("role")})
                row["uiaPatternCount"] = sum(bool(item.get("patterns")) for item in observation["tree"])
                if name == "Calculator":
                    row["controls"] = [{"name": item.get("name"), "automationId": item.get("automationId"),
                                        "role": item.get("role"), "patterns": item.get("patterns")}
                                       for item in observation["tree"] if item.get("role") in {"Button", "Text"}][:60]
                row["observationSha256"] = hashlib.sha256(json.dumps(observation, sort_keys=True).encode()).hexdigest()
                selected_ids = [item["id"] for item in observation["tree"]
                                if item.get("patterns") and item.get("id")][:8]
                if selected_ids:
                    try:
                        element_start = time.perf_counter()
                        fresh = worker.request("inspectElements", {"windowId": str(window["windowId"]),
                                               "elementIds": selected_ids}, timeout=15)
                        row["selectedObserveMs"] = round((time.perf_counter() - element_start) * 1000, 2)
                        row["selectedNodeCount"] = len(fresh.get("tree", []))
                    except Exception as exc:
                        row["selectedObserveUnavailable"] = type(exc).__name__ + ": " + str(exc)[:120]
                times = []
                for _ in range(observation_repeats):
                    _, elapsed = inspect_owned(worker, window)
                    times.append(elapsed)
                row["warmObserveMs"] = times
                row["action"] = scratch_action(worker, name, window, observation)
                row["status"] = "observed"
                cold.append(first_ms)
                warm.extend(times)
                if row["action"].get("status") == "passed":
                    roundtrips.append(row["action"]["roundTripMs"])
            except Exception as exc:
                row["status"] = "failed"
                row["reason"] = type(exc).__name__ + ": " + str(exc)[:250]
            finally:
                if process:
                    row["childCleanup"] = cleanup_child(window, process.pid, started)
                if process and process.poll() is None:
                    # Terminate only the process this script spawned. No tree kill.
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
    finally:
        worker.close()
    result = {
        "schema": "neyvia.c1.native-benchmark.v1", "at": datetime.now(timezone.utc).isoformat(),
        "method": "Direct Windows UIA driver; freshly spawned PID plus executable plus process-start admission; no private window observation",
        "apps": rows, "observed": sum(row["status"] == "observed" for row in rows),
        "requested": len(rows), "firstObserve": summary(cold), "warmObserve": summary(warm),
        "observeActVerify": summary(roundtrips),
        "preservation": {"firstObserveForeground": sum(row.get("firstObservePreservation", {}).get("foreground") is True for row in rows),
                         "firstObserveCursor": sum(row.get("firstObservePreservation", {}).get("cursor") is True for row in rows)},
        "publicSuite": {"name": "OSWorld Windows Excel candidate plus local OSWorld-style probe",
                        "officialHarnessRun": False,
                        "localProbe": "Open disposable local note, append marker, verify text by UIA",
                        "localProbeSuccess": sum(row.get("action", {}).get("status") == "passed" for row in rows),
                        "officialTaskCandidates": [{
                            "id": "4188d3a4-077d-46b7-9c86-23e1a036f6c1",
                            "source": "https://github.com/xlang-ai/OSWorld/blob/main/evaluation_examples/examples_windows/excel/4188d3a4-077d-46b7-9c86-23e1a036f6c1.json",
                            "sha256": "d682104aa50b97e32e42574a9a589c56e718711368a0e61279b5e437f513e5d7",
                            "instruction": "Freeze range A1:B1 on supplied Excel sheet",
                            "fixtureHeadBytes": 11151,
                            "status": "source-and-fixture-available; task not run",
                        }]},
        "comparisons": {"Claude computer use": "unavailable: no matched local run", "OpenAI computer-use model": "unavailable: no matched local run"},
        "cost": {"driverUsd": 0, "modelUsd": None, "basis": "No model invoked by this direct driver benchmark"},
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def fetch_bounded(url: str, limit: int) -> bytes:
    request = Request(url, headers={"User-Agent": "Neyvia-C1-public-benchmark"})
    with urlopen(request, timeout=10) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > limit:
            raise ValueError("Public fixture exceeds download bound")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Public fixture exceeds download bound")
    return data


def public_freeze(receipt: Path) -> dict:
    """Attempt an exact OSWorld Windows task on a disposable Excel instance.

    The official VM harness is not run here. A score is emitted only when UIA
    delivers the actions and the workbook's saved freeze pane changes to C2.
    """
    scratch = SCRATCH / ("public-freeze-" + str(time.time_ns()))
    scratch.mkdir(parents=True, exist_ok=True)
    result = {"taskId": PUBLIC_TASK, "taskSource": PUBLIC_TASK_URL,
              "taskSha256": PUBLIC_TASK_SHA256, "officialHarnessRun": False,
              "status": "unavailable", "steps": [], "at": datetime.now(timezone.utc).isoformat()}
    worker = NativeWorker()
    process = None
    window = None
    started = 0.0
    try:
        raw = fetch_bounded(PUBLIC_TASK_URL, 100_000)
        if hashlib.sha256(raw).hexdigest() != PUBLIC_TASK_SHA256:
            raise ValueError("Public task hash changed")
        task = json.loads(raw)
        fixture_url = task["config"][0]["parameters"]["files"][0]["url"]
        raw_fixture = fetch_bounded(fixture_url, 1_000_000)
        document = scratch / "Freeze_row_column2.xlsx"
        document.write_bytes(raw_fixture)
        result.update(fixtureBytes=len(raw_fixture), fixtureSha256=hashlib.sha256(raw_fixture).hexdigest(),
                      localWorkbook=str(document), instruction=task["instruction"])
        from openpyxl import load_workbook
        result["initialFreezePane"] = str(load_workbook(document, read_only=False).active.freeze_panes)
        worker.request("status", timeout=30)
        pre = worker.request("windows", timeout=10)
        before = native_status(worker)
        exe = next(path for name, path, _ in CATALOG if name == "Microsoft Excel")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 4
        started = time.time()
        process = subprocess.Popen([str(exe), "/x", "/safe", str(document)],
                                   cwd=scratch, startupinfo=startup)
        window = owned_window(worker, "Microsoft Excel", process.pid, exe, started,
                              {int(w["windowId"]) for w in pre},
                              any((w.get("processName") or "").casefold() == "excel" for w in pre),
                              "Freeze_row_column2", seconds=55)
        after = native_status(worker)
        result["launchPreservation"] = preserved(before, after)
        if not window:
            result["reason"] = "No fresh owned Excel workbook window within 55 seconds"
            return result
        result["window"] = compact_window(window)
        before = native_status(worker)
        tree, observed_ms = inspect_owned(worker, window)
        result["firstObserveMs"] = observed_ms
        result["nodeCount"] = len(tree["tree"])
        result["observationPreservation"] = preserved(before, native_status(worker))
        # Public workbook only: control metadata is enough to plan UIA actions.
        result["controls"] = [{"id": node.get("id"), "name": node.get("name"),
                               "automationId": node.get("automationId"), "role": node.get("role"),
                               "patterns": node.get("patterns")}
                              for node in tree["tree"] if node.get("patterns")][:150]
        result["status"] = "observed_unfinished"
        result["reason"] = "No verified background UIA freeze-and-save procedure for this Excel build"
        return result
    except Exception as exc:
        result["status"] = "failed"
        result["reason"] = type(exc).__name__ + ": " + str(exc)[:250]
        return result
    finally:
        if process:
            result["childCleanup"] = cleanup_child(window, process.pid, started)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        worker.close()
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true", help="Read-only executable inventory; no app launches")
    parser.add_argument("--public-freeze", action="store_true", help="Attempt one official OSWorld Windows Excel task in task-local scratch")
    parser.add_argument("--apps", nargs="*", help="Exact cohort names to run (default: all)")
    parser.add_argument("--receipt", type=Path, default=RECEIPT)
    parser.add_argument("--warm-repeats", type=int, default=2)
    args = parser.parse_args()
    if args.public_freeze:
        result = public_freeze(PUBLIC_RECEIPT)
        print(json.dumps({key: result.get(key) for key in ("taskId", "status", "reason", "firstObserveMs", "initialFreezePane")}, indent=2))
        return 0 if result["status"] == "passed" else 1
    if args.inventory:
        print(json.dumps([{"app": name, "category": category, "exe": str(selected_path(name, path)) if selected_path(name, path) else None}
                          for name, path, category in CATALOG], indent=2))
        return 0
    known = {row[0] for row in CATALOG}
    names = set(args.apps) if args.apps else None
    if names is not None and names - known:
        parser.error("Unknown apps: " + ", ".join(sorted(names - known)))
    if args.warm_repeats < 0 or args.warm_repeats > 10:
        parser.error("--warm-repeats must be 0..10")
    result = run(names, args.receipt, args.warm_repeats)
    print(json.dumps({key: result[key] for key in ("observed", "requested", "firstObserve", "warmObserve", "observeActVerify", "preservation")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
