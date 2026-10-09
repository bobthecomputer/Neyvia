"""Real Luna replay and source-bound C9b feedback evidence (never pytest)."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
for key in ("NEYVIA_TOOL_AUTO_UPDATE", "FLUXIO_WATCHDOG_AUTOSTART", "NEYVIA_COORDINATOR_AUTOSTART"):
    os.environ[key] = "0"
from grant_agent.lesson_replay import replay
from grant_agent.lesson_evolver import service_for, LearnedJudge
from grant_agent.durability import atomic_write_json

ROOT = REPO / "scripts/evidence/C9b-runs/runtime"
BASE = "http://127.0.0.1:48761"

def api(command, payload, cookie):
    req = Request(BASE + "/api/backend", json.dumps({"command": command, "payload": payload}).encode(),
                  {"Content-Type": "application/json", "Cookie": cookie})
    with urlopen(req, timeout=30) as response:
        return json.load(response)

def manifests():
    tasks = json.loads((REPO / "proof/r5-blind/tasks.json").read_text())
    result = []
    for task in tasks:
        folder = REPO / "proof/r5-blind/fixtures" / task["id"]
        inputs = {p.name: p.read_text(encoding="utf-8") for p in sorted(folder.glob("*")) if p.is_file()}
        validator = "bench.py" if "bench.py" in inputs else "score.py" if "score.py" in inputs else None
        result.append({"id": task["id"], "task": task["task"], "inputs": inputs, "outputs": task["files"], "validator": validator})
    return result

def record_run(identity, manifest, result, directory):
    from grant_agent.connected_sessions.runs import RunStore, iso
    from grant_agent.connected_sessions.registry import make_session_id
    from grant_agent.external_chat_inventory import _host
    from grant_agent.task_feedback import capture_outputs
    from grant_agent.cl.host import HostContext
    tool = {"name": "files.stat", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, "annotations": {"readOnlyHint": True}}
    host = HostContext([tool], lambda name, args, **kw: {"exists": (directory / args["path"]).is_file()}, root=directory,
                       goals="files.stat(path=" + repr(manifest["outputs"][0]) + ").exists == True", task_text=manifest["task"])
    host.lesson_root = ROOT
    host.task_id = identity
    host.started = 0
    done = host.execute("done(" + repr(manifest["outputs"][0] + " was written and read back.") + ")")["results"][0]
    outputs, snapshots, warnings = capture_outputs(directory, manifest["outputs"])
    store = RunStore(ROOT / ".agent_control/connected_chats.sqlite3", "c9b-replay-recorder", lambda run_id: False)
    data = {"runId": identity, "sessionId": make_session_id("neyvia", _host()["deviceId"], identity), "app": "neyvia", "state": "queued",
            "startedAt": iso(time.time()), "updatedAt": iso(time.time()), "taskText": manifest["task"], "workspaceRoot": str(directory),
            "outputs": outputs, "outputSnapshots": snapshots, "evidenceWarnings": warnings, "doneStatus": done["status"], "skillReceipts": done.get("skillReceipts", {}),
            "provenance": {"route": result["route"], "modelRuns": result["modelRuns"], "manifestSha256": result["manifestSha256"]}}
    store.claim(data, identity, None, is_free=lambda run_id: True, register=lambda: None, unregister=lambda: None)
    data["state"] = "completed" if result["valid"] else "failed"
    store.save(data)
    service_for(ROOT).register_replay(identity, manifest)
    return data

def source():
    task = next(m for m in manifests() if m["id"] == "in2-dishes")
    directory = REPO / "scripts/evidence/C9b-runs/source" / uuid.uuid4().hex
    result = replay(task, directory)
    data = record_run("c9b-source-" + uuid.uuid4().hex, task, result, directory)
    atomic_write_json(REPO / "scripts/evidence/C9b-source.json", {"runId": data["runId"], "sessionId": data["sessionId"], "task": task,
                       "resultPath": str(directory / "replay.json"), "outputs": data["outputs"], "doneStatus": data["doneStatus"], "skillReceipts": data["skillReceipts"]})
    print(json.dumps({"sourceRun": data["runId"], "valid": result["valid"], "doneStatus": data["doneStatus"]}), flush=True)

def paired(lesson, task_id=None):
    tasks = [m for m in manifests() if task_id is None or m["id"] == task_id]
    if not tasks:
        raise ValueError("Unknown frozen R5 task")
    receipt = "C9b-r5-targeted.json" if task_id else "C9b-r5.json"
    run_root = REPO / "scripts/evidence/C9b-runs/r5" / uuid.uuid4().hex
    records = []
    def one(task):
        outputs = {}
        for arm in (["before", "after"] if tasks.index(task) % 2 else ["after", "before"]):
            print(json.dumps({"task": task["id"], "arm": arm, "state": "started"}), flush=True)
            try:
                outputs[arm] = replay(task, run_root / task["id"] / arm, lines=[lesson] if arm == "after" else [])
            except Exception as exc:
                outputs[arm] = {"valid": False, "error": str(exc)}
            print(json.dumps({"task": task["id"], "arm": arm, "valid": outputs[arm]["valid"]}), flush=True)
        return {"task": task["id"], "runs": outputs}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(one, task) for task in tasks]):
            records.append(future.result())
            atomic_write_json(REPO / "scripts/evidence" / receipt, {"route": "real bounded Luna output/measurement replay", "lesson": lesson,
                               "lessonState": "quarantined candidate, trial only", "records": records, "allTasks": [t["id"] for t in tasks]})
    print(json.dumps({"pairedTasks": len(records), "validRuns": sum(r["valid"] for c in records for r in c["runs"].values())}), flush=True)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["source", "r5", "freeze"])
    p.add_argument("--lesson", default='M deliverables "Use a specific title on the first line, put the result first, and use a small table for 3 or more comparable facts. Keep within the task word limit." src:feedback state:quarantine')
    p.add_argument("--task", help="Rerun one frozen R5 task, preserving the full-round receipt")
    args = p.parse_args()
    if args.phase == "source":
        source()
    elif args.phase == "r5":
        paired(args.lesson, args.task)
    else:
        service = service_for(ROOT)
        print(json.dumps({"suite": service.freeze_suite(manifests())}), flush=True)
