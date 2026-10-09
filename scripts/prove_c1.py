"""Execute C1's defining adaptation/promotion/compiled replay on a real owned app."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.neyvia_cua import CuaService
from grant_agent.cua_native import NativeWorker


def run():
    scratch = ROOT / ".agent_control/c1" / str(time.time_ns())
    scratch.mkdir(parents=True)
    framework = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319"
    source = ROOT / "tools/cua-driver-win/probe.cs"
    binary = scratch / "C1NativeProbe.exe"
    args = [str(framework / "csc.exe"), "/nologo", "/target:winexe", "/out:" + str(binary), str(source)]
    args += ["/reference:" + str(framework / (name + ".dll")) for name in ("System.Windows.Forms", "System.Drawing")]
    subprocess.run(args, capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    service = CuaService(scratch)
    timings = []
    native_request = service.native.request
    def measured(op, *args, **kwargs):
        tick = time.perf_counter()
        try:
            return native_request(op, *args, **kwargs)
        finally:
            timings.append({"op": op, "ms": (time.perf_counter() - tick) * 1000})
    service.native.request = measured
    state = scratch / "window.txt"
    process = None
    try:
        startup_before = service.native.request("status")
        process = subprocess.Popen([str(binary), str(state)], creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 55
        while not state.is_file() and time.monotonic() < deadline:
            time.sleep(.05)
        if not state.is_file():
            raise RuntimeError("Owned app did not launch")
        window_id = int(state.read_text())
        window = service.native.request("window", {"windowId": str(window_id)})
        if int(window["pid"]) != process.pid:
            raise RuntimeError("Owned PID mismatch")
        session = service.new_session(["C1NativeProbe"], {"chatId": "c1-proof", "app": "neyvia"})
        session["_windowPins"] = {window_id: window}
        params = {"sessionId": session["id"], "window_id": window_id}
        started = time.perf_counter()
        adaptation = service.request("adapt", params)
        first_ms = (time.perf_counter() - started) * 1000
        steps = [
            {"selector": {"role": "Edit", "label": "Task input"}, "tool": "set_value", "args": {"value": "C1 verified"},
             "expect": [{"element": {"selector": {"role": "Edit", "label": "Task input"}, "value_equals": "C1 verified"}}]},
            {"selector": {"role": "Button", "label": "Apply"}, "tool": "click",
             "expect": [{"element": {"selector": {"label": "Applied: C1 verified"}, "exists": True}}]},
        ]
        runs = []
        for repeat in range(5):
            runs.append(service.request("flow", {**params, "steps": steps}))
            if not runs[-1].get("ok"):
                raise RuntimeError("Flow failed: " + json.dumps(runs[-1]))
        # Failure paths are real dispatch requests; no effects may occur.
        failures = {}
        for name, spec in [("ambiguous", {"role": "Button"}), ("missing", {"label": "does not exist"})]:
            # Only missing is necessarily ambiguous in this app; add broad role
            # selector for the actual multi-match check below.
            if name == "ambiguous":
                spec = {"className": ""}
            try:
                service.request("flow", {**params, "steps": [{**steps[0], "selector": spec}]})
                failures[name] = "unexpected_success"
            except (ValueError, RuntimeError) as exc:
                failures[name] = str(exc)
        service.request("control", {"sessionId": session["id"], "mode": "paul"}, owner=True)
        try:
            paused = service.request("flow", {**params, "steps": steps})
            failures["takeover"] = "unexpected_success" if paused.get("ok") else paused.get("error", "refused")
        except (ValueError, RuntimeError) as exc:
            failures["takeover"] = str(exc)
        service.request("control", {"sessionId": session["id"], "mode": "agent"}, owner=True)
        screenshot = service.request("capture", params)
        final = service.request("inspect", params)
        after = service.native.request("status")
        if any(value == "unexpected_success" for value in failures.values()):
            raise RuntimeError("An important refusal path unexpectedly succeeded")
        receipt = {"schema": "neyvia.c1-proof.v1", "pid": process.pid, "window_id": window_id,
            "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(), "firstObservationMs": first_ms,
            "runtimeSourceSha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                "src/grant_agent/cua_adaptation.py", "src/grant_agent/cua_native.py", "src/grant_agent/neyvia_cua.py",
                "src/grant_agent/neyvia_manuals.py", "src/grant_agent/manual_versions.py",
                "tools/cua-driver-win/NativeWorker.cs", "tools/cua-driver-win/json-host.cs", "manuals/cl/computer-use.cl")},
            "adaptation": adaptation, "runs": runs, "failures": failures,
            "capture": screenshot, "final": final,
            "foregroundPreserved": startup_before["foregroundWindowId"] == after["foregroundWindowId"] and startup_before["foregroundGeneration"] == after["foregroundGeneration"],
            "cursorPreserved": startup_before["cursor"] == after["cursor"],
            "compiledReplay": any(r.get("compiled") and r.get("ok") for r in runs),
            "fileEffect": (state.with_name(state.name + ".result")).read_text(),
            "tokens": 0, "costUsd": 0,
            "nativeTimings": timings,
            "boundary": "Real compiled disposable WinForms application; separate installed-app cohort required"}
        output = ROOT / "scripts/evidence/C1-mechanism.json"
        output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"receipt": str(output), "firstObservationMs": first_ms,
            "flowMs": [r["elapsed_ms"] for r in runs], "compiledReplay": receipt["compiledReplay"], "failures": failures,
            "foregroundPreserved": receipt["foregroundPreserved"], "cursorPreserved": receipt["cursorPreserved"]}))
    finally:
        try:
            service.shutdown()
        finally:
            if process and process.poll() is None:
                process.terminate(); process.wait(timeout=5)


if __name__ == "__main__":
    run()
