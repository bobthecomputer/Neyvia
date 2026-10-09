"""Observe actual owned children under competing production watchdog invocations."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import threading
import time
import uuid

from grant_agent.edge_fixture_c7d_sessions import REPO, _isolate
from grant_agent.edge_fixture_sessions import _run_data
from grant_agent.connected_sessions.broker import ConnectedBroker, _LiveRun
from grant_agent.proof_contracts import source_digest

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = REPO / ".agent_control/proofs/c7d-sessions" / ("watchdog-race-" + uuid.uuid4().hex)
    _isolate(root, args.port)
    broker = ConnectedBroker(root, adapters={}, load_defaults=False, autostart=False, idle_watchdog_seconds=1)
    calls, children, facts = [], [], []
    class OwnedChild:
        def __init__(self, index):
            marker = root / (str(index) + "-child.json")
            program = "import os,sys,time,json;from pathlib import Path;p=Path(sys.argv[1]);t=p.with_suffix('.tmp');t.write_text(json.dumps({'pid':os.getpid(),'startedNs':time.time_ns()}));os.replace(t,p);time.sleep(30)"
            self.child = subprocess.Popen([sys.executable, "-c", program, str(marker)])
            children.append(self.child)
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline: time.sleep(.01)
            facts.append(json.loads(marker.read_text()))
        def interrupt(self, run):
            calls.append({"runId": run, "invokedNs": time.time_ns(), "pid": self.child.pid})
            if self.child.poll() is None: self.child.terminate()
            self.child.wait(timeout=5)
    before = source_digest(REPO / "src/grant_agent/connected_sessions/broker.py")
    try:
        for index in range(8):
            data = _run_data("owned-" + str(index), "session-" + str(index), "owned")
            data["state"] = "running"
            live = _LiveRun(data, OwnedChild(index), "turn"); live.last_output = time.monotonic() - 2
            broker._live[data["runId"]] = live
        now = time.monotonic(); barrier = threading.Barrier(8)
        def watchdog(_): barrier.wait(5); broker._watchdog(now)
        with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(watchdog, range(8)))
        deadline = time.monotonic() + 5
        while len(calls) < 8 and time.monotonic() < deadline: time.sleep(.01)
        for child in children: child.wait(timeout=5)
        broker._watchdog(now + 5)
        result = {"root": str(root), "explicitPort": args.port, "writers": 8, "actualInterrupts": len(calls),
                  "uniqueInterrupts": len({row['runId'] for row in calls}), "calls": calls, "actualChildStarts": facts,
                  "states": [run.data["state"] for run in broker._live.values()],
                  "allChildrenExited": all(child.poll() is not None for child in children),
                  "sourceBindings": {"src/grant_agent/connected_sessions/broker.py": before},
                  "sourceStable": before == source_digest(REPO / "src/grant_agent/connected_sessions/broker.py"),
                  "proofScope": "local_semantic", "installedProviderExecuted": False}
        result["ok"] = result["actualInterrupts"] == result["uniqueInterrupts"] == 8 and result["allChildrenExited"] and result["sourceStable"]
        output = (REPO / args.output).resolve(); output.relative_to(REPO)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
        print(json.dumps({key: result[key] for key in ("actualInterrupts", "uniqueInterrupts", "allChildrenExited", "sourceStable", "ok")}))
        if not result["ok"]: raise SystemExit(1)
    finally:
        broker.close()
        for child in children:
            if child.poll() is None: child.terminate(); child.wait(timeout=5)

if __name__ == "__main__": main()
