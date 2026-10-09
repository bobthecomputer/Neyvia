"""Real C11 desktop feasibility, without ever showing an input-desktop app."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.cua_desktop import AgentDesktop, DesktopIsolationError
from grant_agent.cua_guard import ZeroDisturbanceGuard
from grant_agent.cua_native import NativeWorker


def compact(result):
    return {"mechanism": result.get("mechanism"), "effect": result.get("effect"),
            "check": result.get("check", {}).get("status"), "elapsedMs": result.get("elapsedMs"),
            "foregroundPreserved": result.get("foregroundPreserved"),
            "cursorPreserved": result.get("cursorPreserved")}


def run(only_probe=False):
    scratch = ROOT / ".agent_control/c11-spike" / str(time.time_ns())
    scratch.mkdir(parents=True)
    source = ROOT / "tools/cua-driver-win/c1-probe.cs"
    framework = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319"
    binary = scratch / "C11DesktopProbe.exe"
    subprocess.run([str(framework / "csc.exe"), "/nologo", "/target:winexe", "/out:" + str(binary),
                    str(source), "/reference:" + str(framework / "System.Windows.Forms.dll"),
                    "/reference:" + str(framework / "System.Drawing.dll")],
                   capture_output=True, check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    manifest = json.loads((ROOT / "scripts/evidence/C1-tasks.json").read_text(encoding="utf-8"))
    apps = {a["app"]: a for a in manifest["apps"]}
    state = scratch / "window.txt"
    form = scratch / "form.html"
    form.write_text('<!doctype html><title>C11 isolated form</title><label>C1 note <input aria-label="C1 note"></label>', encoding="utf-8")
    text = scratch / "fixture.txt"; text.write_text("C1 note 1\nC1 note 2\n", encoding="utf-8")
    rtf = scratch / "fixture.rtf"; rtf.write_text(r"{\rtf1\ansi C1 note 1\par C1 note 2}", encoding="ascii")
    csv = scratch / "fixture.csv"; csv.write_text("C1 note 1,C1 note 2\n", encoding="utf-8")
    for name in ("chrome", "edge", "code", "extensions"):
        (scratch / name).mkdir()
    receipt = {"schema": "neyvia.c11.desktop-spike.v1", "ok": False,
               "boundary": "CreateDesktop private desktop, lpDesktop suspended job-contained launches, bound UIA/MSAA/capture lanes",
               "apps": [], "scratch": str(scratch.relative_to(ROOT)),
               "noSwitchDesktop": True, "guard": None,
               "sourceSha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                 [source, Path(__file__), ROOT / "src/grant_agent/cua_desktop.py"]}}
    output = ROOT / "scripts/evidence/C11-spike.json"
    if output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        receipt["previousRuns"] = (previous.get("previousRuns", []) + [{"ok": previous.get("ok"),
            "error": previous.get("error"), "scratch": previous.get("scratch"),
            "latency": previous.get("latency"), "apps": [{k: a.get(k) for k in (
                "app", "launched", "private", "error", "refused", "reason", "observation")} for a in previous.get("apps", [])],
            "guard": {k: previous.get("guard", {}).get(k) for k in ("ok", "violations", "samples", "external_guard_entries")}}])[-6:]
    guard = ZeroDisturbanceGuard().start()
    desktop = None; worker = None
    try:
        if not guard.check()["ok"]:
            raise RuntimeError("Input guard not healthy before CreateDesktop")
        desktop = AgentDesktop(); worker = NativeWorker(desktop=desktop, guard=guard)
        receipt["desktop"] = desktop.name
        # Initialization never launches a GUI app. Keep its own guard receipt;
        # physical input during preparation must not be claimed as a zero run.
        from grant_agent.cua_fast import FastClient
        worker.fast_client = FastClient(worker)
        for lane in (worker.fast_client.uia, worker.fast_client.msaa, worker.fast_client.capture):
            if not lane.ready.wait(5):
                raise RuntimeError("Invisible driver lane initialization deadline")
        worker.request("status", timeout=10)
        receipt["preparationGuard"] = guard.close()
        if receipt["preparationGuard"]["owned_escaped_windows_hidden"] or receipt["preparationGuard"]["external_guard_entries"]:
            raise RuntimeError("Owned window escaped during invisible initialization")
        idle_at = time.monotonic()
        tick = worker.fast_client.win.last_input_tick()
        quiet_at = time.monotonic()
        while time.monotonic() - quiet_at < .5:
            current_tick = worker.fast_client.win.last_input_tick()
            if current_tick != tick:
                tick, quiet_at = current_tick, time.monotonic()
            if time.monotonic() - idle_at > 15:
                raise RuntimeError("No half-second idle interval; no GUI launch admitted")
            time.sleep(.02)
        receipt["idleWaitMs"] = round((time.monotonic() - idle_at) * 1000, 2)
        guard = ZeroDisturbanceGuard().start()
        worker.guard = guard
        if not guard.check()["ok"]:
            raise RuntimeError("Fresh actual-run guard not healthy; no GUI launch admitted")
        cases = [("Disposable WinForms", [str(binary), str(state)], "Task input")]
        if not only_probe:
            cases.extend([
                ("Notepad", [apps["Notepad"]["exe"]], None),
                ("Character Map", [apps["Character Map"]["exe"]], "Characters to copy:"),
                ("Microsoft Word", [apps["Microsoft Word"]["exe"], "/x", "/q", "/n", str(rtf)], None),
                ("Microsoft Excel", [apps["Microsoft Excel"]["exe"], "/x", str(csv)], None),
                ("Google Chrome", [apps["Google Chrome"]["exe"], "--user-data-dir=" + str(scratch / "chrome"),
                                   "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--force-renderer-accessibility", form.as_uri()], "C1 note"),
                ("Microsoft Edge", [apps["Microsoft Edge"]["exe"], "--user-data-dir=" + str(scratch / "edge"),
                                    "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--force-renderer-accessibility", form.as_uri()], "C1 note"),
                ("Visual Studio Code", [apps["Visual Studio Code"]["exe"], "--user-data-dir=" + str(scratch / "code"),
                                        "--extensions-dir=" + str(scratch / "extensions"), "--disable-extensions", "--disable-gpu", "--new-window", str(text)], None),
                ("Calculator (UWP)", [apps["Calculator"]["exe"]], None),
            ])
        for app, argv, edit_name in cases:
            item = {"app": app, "launched": False, "private": False, "observation": None,
                    "actions": [], "capture": None, "refused": False}
            receipt["apps"].append(item)
            process = None
            try:
                before = {w["windowId"] for w in desktop.windows()}
                began = time.perf_counter(); process = worker.launch(argv, cwd=scratch)
                item.update(launched=True, pid=process.pid)
                until = time.monotonic() + 12
                windows = []
                while time.monotonic() < until:
                    if not guard.check()["ok"]:
                        raise RuntimeError("Input guard failed while app was starting")
                    windows = [w for w in desktop.windows() if w["visible"] and w["windowId"] not in before]
                    if windows:
                        break
                    time.sleep(.05)
                if not windows:
                    raise RuntimeError("No private visible app window within 12 s")
                # Largest actual app window, rather than a transient splash.
                time.sleep(.25)
                windows = [w for w in desktop.windows() if w["visible"] and w["windowId"] not in before]
                candidates = []
                for window in windows:
                    metadata = worker.request("window", {"windowId": window["windowId"]})
                    bounds = metadata["bounds"]
                    candidates.append((bounds["width"] * bounds["height"], window))
                window = max(candidates, key=lambda x: x[0])[1]; hwnd = window["windowId"]
                item.update(private=desktop.owns(hwnd), windowId=hwnd, startupMs=(time.perf_counter()-began)*1000)
                began = time.perf_counter()
                observed = worker.request("inspect", {"windowId": hwnd, "maxNodes": 600, "maxDepth": 12})
                item["observation"] = {"elapsedMs": (time.perf_counter()-began)*1000, "source": observed["source"],
                                       "nodes": len(observed["tree"]), "degradedReason": observed.get("degradedReason")}
                if app == "Disposable WinForms":
                    for repeat in range(5):
                        value = "C11 isolated " + str(repeat)
                        observed = worker.request("inspect", {"windowId": hwnd})
                        edit = next(r for r in observed["tree"] if r["name"] == "Task input")
                        button = next(r for r in observed["tree"] if r["name"] == "Apply")
                        for args in [{"elementId": edit["id"], "action": "value", "text": value,
                                      "expect": [{"selector": {"id": edit["id"]}, "value_equals": value}]},
                                     {"elementId": button["id"], "action": "click",
                                      "expect": [{"selector": {"role": "Text", "name": "Applied: " + value}, "name_contains": value}]}]:
                            began = time.perf_counter()
                            result = compact(worker.request("cycle", {"windowId": hwnd, **args}))
                            result["roundTripMs"] = (time.perf_counter()-began)*1000
                            item["actions"].append(result)
                        item["fileEffect"] = state.with_suffix(".txt.result").read_text()
                        if item["fileEffect"] != "Applied: " + value:
                            raise RuntimeError("Probe app-written file did not match")
                    # Exercise forwarded preview coordinates through PostMessage,
                    # with the app-written result as independent verification.
                    value = "C11 forwarded click"
                    worker.request("action", {"windowId": hwnd, "elementId": edit["id"], "action": "value", "text": value})
                    result = worker.request("cycle", {"windowId": hwnd, "elementId": button["id"], "action": "pointClick",
                        "expect": [{"selector": {"role": "Text", "name": "Applied: " + value}, "name_contains": value}]})
                    item["forwardedPostMessage"] = compact(result)
                    item["forwardedFileEffect"] = state.with_suffix(".txt.result").read_text()
                elif edit_name:
                    edits = [r for r in observed["tree"] if r["role"] == "Edit" and r["name"] == edit_name
                             and not r.get("isPassword") and not r.get("readOnly")]
                    if len(edits) == 1:
                        edit = edits[0]; value = "C11 isolated form"
                        item["actions"].append(compact(worker.request("cycle", {"windowId": hwnd, "elementId": edit["id"],
                            "action": "value", "text": value, "expect": [{"selector": {"id": edit["id"]}, "value_equals": value}]})))
                    else:
                        item["actionMissing"] = "Unique safe edit was not exposed"
                try:
                    captured = worker.request("capture", {"windowId": hwnd})
                    raw = base64.b64decode(captured["pngBase64"])
                    item["capture"] = {k: captured[k] for k in ("method", "width", "height", "mimeType")}
                    item["capture"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                    if app == "Disposable WinForms":
                        screenshot = scratch / "probe.png"; screenshot.write_bytes(raw)
                        item["capture"]["file"] = str(screenshot.relative_to(ROOT))
                except Exception as exc:
                    item["captureError"] = type(exc).__name__ + ": " + str(exc)[:250]
                item["guard"] = guard.check()
            except DesktopIsolationError as exc:
                item.update(refused=True, reason=str(exc))
            except Exception as exc:
                item["error"] = type(exc).__name__ + ": " + str(exc)[:300]
            finally:
                if process and process.poll() is None:
                    process.terminate(); process.wait(3)
            if not guard.check()["ok"]:
                raise RuntimeError("Zero-disturbance failed; no further launches admitted")
        probe = receipt["apps"][0]
        latencies = [a["roundTripMs"] for a in probe["actions"]]
        receipt["latency"] = {"count": len(latencies), "p50Ms": statistics.median(latencies) if latencies else None,
                              "targetP50Ms": 150, "timing": "NativeWorker atomic observe-act-fresh-check including guard checks"}
        receipt["ok"] = bool(probe["private"] and probe["capture"] and len(probe["actions"]) == 10
            and all(a["check"] == "satisfied" for a in probe["actions"])
            and probe.get("forwardedPostMessage", {}).get("check") == "satisfied"
            and probe.get("forwardedFileEffect") == "Applied: C11 forwarded click"
            and guard.check()["ok"])
    except Exception as exc:
        receipt["error"] = type(exc).__name__ + ": " + str(exc)[:350]
    finally:
        if worker: worker.close()
        if desktop: receipt["cleanup"] = desktop.close()
        receipt["guard"] = guard.close()
        receipt["ok"] = receipt["ok"] and receipt["guard"]["ok"]
        output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": receipt["ok"], "error": receipt.get("error"), "latency": receipt.get("latency"),
                      "guardOk": receipt["guard"]["ok"], "apps": [{k: a.get(k) for k in
                         ("app", "launched", "private", "refused", "error", "captureError", "reason")} for a in receipt["apps"]]}))
    return receipt["ok"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--only-probe", action="store_true")
    sys.exit(0 if run(parser.parse_args().only_probe) else 1)
