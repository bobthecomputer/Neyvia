"""Compare persistent native-COM C# and comtypes MTA window-scoped cache clients.

No desktop-root reads, app actions, install, or foreign-process termination.
The 100 ms caller deadline includes cached traversal; late workers stay isolated.
"""
from __future__ import annotations

import sys
sys.coinit_flags = 0
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import statistics
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def windows(limit, classes):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = user32.IsHungAppWindow.argtypes = [wintypes.HWND]
    rows, skipped = [], []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, unused):
        if not user32.IsWindowVisible(hwnd):
            return True
        title, cls = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd, title, len(title))
        user32.GetClassNameW(hwnd, cls, len(cls))
        if classes and cls.value not in classes:
            return True
        if not title.value or "neyvia" in title.value.lower():
            return True
        row = {"hwnd": int(hwnd), "class": cls.value}
        if user32.IsHungAppWindow(hwnd):
            skipped.append(row)
        elif len(rows) < limit:
            rows.append(row)
        return True
    user32.EnumWindows(visit, 0)
    return rows, skipped


class PythonClient:
    def __init__(self, scope):
        self.scope = scope
        self.requests = queue.Queue(maxsize=1)
        self.ready = threading.Event()
        self.busy = threading.Event()
        self.error = None
        threading.Thread(target=self.worker, name="c1-comtypes-MTA", daemon=True).start()
        if not self.ready.wait(45):
            self.error = "initialization_timeout"

    def worker(self):
        try:
            import comtypes
            import comtypes.client
            comtypes.CoInitializeEx(0)
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as U
            uia = comtypes.CoCreateInstance(U.CUIAutomation8._reg_clsid_, interface=U.IUIAutomation2, clsctx=1)
            uia.ConnectionTimeout, uia.TransactionTimeout = 50, 80
            cache = uia.CreateCacheRequest()
            for prop in (30003, 30005, 30011, 30001, 30020):
                cache.AddProperty(prop)
            cache.TreeScope, cache.TreeFilter = self.scope, uia.ControlViewCondition
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.ready.set()
            return
        self.ready.set()
        while True:
            hwnd, response = self.requests.get()
            start = time.perf_counter()
            try:
                stack, nodes = [uia.ElementFromHandleBuildCache(hwnd, cache)], 0
                while stack:
                    element = stack.pop()
                    nodes += 1
                    children = element.GetCachedChildren()
                    if children:
                        stack.extend(children.GetElement(i) for i in range(children.Length))
                result = {"status": "ok", "nodes": nodes}
            except Exception as exc:
                result = {"status": "error", "error": type(exc).__name__, "hresult": getattr(exc, "hresult", None)}
            result["worker_ms"] = (time.perf_counter() - start) * 1000
            self.busy.clear()
            response.put(result)

    def request(self, hwnd):
        start = time.perf_counter()
        if self.error:
            return {"status": "unavailable", "error": self.error, "caller_ms": 0}
        if self.busy.is_set():
            return {"status": "busy", "caller_ms": (time.perf_counter() - start) * 1000}
        response = queue.Queue(maxsize=1)
        self.busy.set()
        self.requests.put((hwnd, response))
        try:
            result = response.get(timeout=.1)
        except queue.Empty:
            result = {"status": "deadline"}
        result["caller_ms"] = (time.perf_counter() - start) * 1000
        return result


def summary(rows):
    times = sorted(row["caller_ms"] for row in rows)
    completed = sorted(row["caller_ms"] for row in rows if row["status"] == "ok")
    attempts = sorted(row["caller_ms"] for row in rows if row["status"] != "busy")
    return {"samples": len(rows), "ok": sum(row["status"] == "ok" for row in rows),
            "deadline": sum(row["status"] == "deadline" for row in rows),
            "busy": sum(row["status"] == "busy" for row in rows),
            "p50_ms": statistics.median(times), "p95_ms": times[min(len(times)-1, int(len(times)*.95))],
            "attempt_p50_ms": statistics.median(attempts) if attempts else None,
            "completed_p50_ms": statistics.median(completed) if completed else None,
            "completed_p95_ms": completed[min(len(completed)-1, int(len(completed)*.95))] if completed else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--scope", choices=("element", "subtree"), default="subtree")
    parser.add_argument("--classes", default="", help="Optional comma-separated Win32 class filter")
    args = parser.parse_args()
    source = ROOT / "scripts/evidence/c1_csharp_probe.cs"
    binary = ROOT / ".agent_control/c1-cua/probe/c1_csharp_probe.exe"
    binary.parent.mkdir(parents=True, exist_ok=True)
    compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    compile_run = subprocess.run([str(compiler), "/nologo", "/target:exe", "/out:" + str(binary), str(source)],
                                 capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    if compile_run.returncode:
        raise RuntimeError(compile_run.stdout + compile_run.stderr)
    scope = 1 if args.scope == "element" else 7
    proc = subprocess.Popen([str(binary), str(scope)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
    responses = queue.Queue()
    threading.Thread(target=lambda: [responses.put(json.loads(line)) for line in proc.stdout], daemon=True).start()
    try:
        csharp_ready = responses.get(timeout=45)
        python = PythonClient(scope)
        targets, skipped = windows(args.windows, set(filter(None, args.classes.split(","))))
        if not targets:
            raise RuntimeError("No nonhung visible titled target windows")
        raw = {"csharp": [], "python": []}
        for repeat in range(args.repeats):
            for target in targets:
                for name in ("csharp", "python"):
                    start = time.perf_counter()
                    if name == "csharp":
                        proc.stdin.write(str(target["hwnd"]) + "\n")
                        proc.stdin.flush()
                        try:
                            result = responses.get(timeout=.3)
                        except queue.Empty:
                            result = {"status": "transport_deadline", "caller_ms": 300}
                        result["transport_ms"] = (time.perf_counter()-start)*1000
                    else:
                        result = python.request(target["hwnd"])
                    raw[name].append({"repeat": repeat, **target, **result})
        receipt = {"schema": "c1-client-comparison/v1", "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "deadline_ms": 100, "connection_timeout_ms": 50, "transaction_timeout_ms": 80,
                   "cache": {"scope": "target-window-" + args.scope, "properties": [30003,30005,30011,30001,30020]},
                   "targets": targets, "hung_skipped": skipped, "csharp_ready": csharp_ready,
                   "python_error": python.error, "summary": {name: summary(rows) for name, rows in raw.items()}, "raw": raw,
                   "limitation": "Read-only client microbenchmark, not an observe-act-verify app benchmark. Busy results are not successful cache observations."}
        output = ROOT / "scripts/evidence/C1-client-comparison.json"
        prior = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
        arms = prior.get("arms", {})
        if "cache" in prior:
            arms[prior["cache"]["scope"]] = prior
        arms[receipt["cache"]["scope"] + (":" + args.classes if args.classes else "")] = receipt
        output.write_text(json.dumps({"schema": "c1-client-comparison-arms/v1", "arms": arms}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"receipt": str(output), "summary": receipt["summary"]}))
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.terminate()  # Owned probe only; no application is stopped.
            proc.wait(timeout=3)


if __name__ == "__main__":
    main()
