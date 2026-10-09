"""Bounded live native transport diagnostic without enumerating user windows."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.cua_native import NativeWorker

started = time.perf_counter()
assembly = NativeWorker.assembly()
host = NativeWorker.json_host()
print("compiled", flush=True)
process = None
row = {"schema": "neyvia.c1-transport.v1", "compiled": True}
try:
    process = subprocess.Popen([str(host), str(assembly)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    print("spawned", flush=True)
    request = json.dumps({"id": "c1-live", "op": "status", "args": {}}).encode() + b"\n"
    out, err = process.communicate(request, timeout=15)
    response = json.loads(out.decode("utf-8"))
    row.update(ok=response.get("ok"), hooksReady=response.get("data", {}).get("hooksReady"), exitCode=process.returncode)
except Exception as exc:
    row.update(ok=False, error=type(exc).__name__, hint="Live host did not complete the bounded status request")
finally:
    if process and process.poll() is None:
        process.terminate(); process.wait(timeout=5)
row["elapsedMs"] = (time.perf_counter() - started) * 1000
(ROOT / "scripts/evidence/C1-transport.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
print(json.dumps(row), flush=True)
