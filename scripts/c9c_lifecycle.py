"""Real Luna feedback -> paired executable trial -> HTTP revert proof.

No caller-supplied scores, model/provider substitution, browser or visible app.
The scoped fixture proves scanner lookup compatibility, fidelity and versioning.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
for key in ("NEYVIA_TOOL_AUTO_UPDATE", "FLUXIO_WATCHDOG_AUTOSTART", "NEYVIA_COORDINATOR_AUTOSTART"):
    os.environ[key] = "0"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
ROOT = REPO / "scripts/evidence/C9c-runs/runtime"
RECEIPT = REPO / "scripts/evidence/C9c-lifecycle.json"

def guard():
    from grant_agent.proof_credential_guard import check_access, _ROOTS
    _ROOTS.add(ROOT.resolve())
    def audit(event, args):
        if event in {"open", "sqlite3.connect"} and args:
            check_access(args[0])
        if event == "socket.connect":
            host, port = args[1][:2]
            if host not in {"127.0.0.1", "::1", "localhost"} or not 48761 <= port <= 48769:
                raise PermissionError("C9c Python authority permits only owned proof ports")
    sys.addaudithook(audit)

def serve(port):
    guard()
    os.environ["NEYVIA_PROOF_CREDENTIAL_GUARD"] = "1"
    from grant_agent.web_backend import FluxioWebBackend, make_handler, _HandshakeSafeThreadingHTTPServer
    from grant_agent.connected_sessions.broker import ConnectedBroker, _BROKERS
    static = ROOT / "empty-web"
    static.mkdir(parents=True, exist_ok=True)
    backend = FluxioWebBackend(ROOT, static)
    from grant_agent.neyvia_workspace_tools import workspace_for
    workspace_for(ROOT, backend)
    broker = ConnectedBroker(ROOT, backend=backend, autostart=False)
    _BROKERS[os.path.normcase(str(ROOT.resolve()))] = broker
    server = _HandshakeSafeThreadingHTTPServer(("127.0.0.1", port), make_handler(backend))
    print(json.dumps({"serving": port, "root": str(ROOT)}), flush=True)
    try:
        server.serve_forever()
    finally:
        broker.close()
        server.server_close()

VALIDATOR = '''import importlib.util, json, sys
from pathlib import Path
criteria={name:False for name in ["briefFidelity","efficientLookup","scannerCompatibility","realDeliverable","naming","nothingBroken"]}
comparisons=0
try:
    spec=importlib.util.spec_from_file_location("actual_lookup", "lookup.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows=[{"id":"a","enabled":False,"value":1},{"id":"b","enabled":True,"value":2},{"id":"a","enabled":True,"value":3},{"id":"b","enabled":True,"value":4}]
    expected=[rows[1],rows[2],rows[1]]
    criteria["briefFidelity"]=module.lookup(rows,["b","a","missing","b"])==expected
    criteria["nothingBroken"]=criteria["briefFidelity"] and module.lookup([], ["missing"])==[] and module.lookup(rows,[])==[] and module.lookup([{"id":"old","value":7}],["old"])[0]["value"]==7
    scan_rows=[{"id":"A-17","enabled":True,"value":17},{"id":"B-23","enabled":False,"value":23},{"id":"SPACE ","enabled":True,"value":42}]
    criteria["scannerCompatibility"]=module.lookup(scan_rows,["A-17"+chr(8203),"B-23"+chr(8203),"A-17"+chr(8203)])==[scan_rows[0],scan_rows[0]] and module.lookup(scan_rows,["SPACE "])==[scan_rows[2]] and module.lookup(scan_rows,["SPACE"])==[]
    criteria["realDeliverable"]=bool(Path("lookup.py").read_text().strip())
    criteria["naming"]=callable(module.lookup)
    class Key(str):
        def __eq__(self,other):
            global comparisons
            comparisons+=1
            return str.__eq__(self,other)
        __hash__=str.__hash__
    catalog=[{"id":Key(str(i)),"enabled":True,"value":i} for i in range(2000)]
    requested=[Key(str(i)) for i in range(1999,999,-2)]
    result=module.lookup(catalog,requested)
    criteria["nothingBroken"]=criteria["nothingBroken"] and [row["value"] for row in result]==list(range(1999,999,-2))
    criteria["efficientLookup"]=comparisons<=10000
except Exception as error:
    failure=type(error).__name__+": "+str(error)
print(json.dumps({"criteria":criteria,"comparisons":comparisons,"failure":locals().get("failure")}))
sys.exit(0 if all(v for k,v in criteria.items() if k not in {"efficientLookup","scannerCompatibility"}) else 1)
'''

LOOKUP = '''def lookup(rows, requested):
    result = []
    for identity in requested:
        for row in rows:
            if row["id"] == identity:
                result.append(row)
                break
    return result
'''

def manifest(regression=False):
    implementation = LOOKUP
    if regression:
        implementation = '''def lookup(rows, requested):
    by_id = {}
    for row in rows:
        if row.get("enabled", True):
            by_id.setdefault(row["id"], row)
    return [by_id[identity] for identity in requested if identity in by_id]
'''
    return {"task": "Fix lookup.py for our inventory scanner: lookup(rows, requested) must omit disabled catalog rows. Return the first enabled row for each requested ID in requested order, retain repeated requests and omit unknown IDs. A row without an enabled field is enabled. Preserve the public function. Make the smallest maintainable repair to the existing code.",
            "inputs": {"lookup.py": implementation, "score.py": VALIDATOR}, "modelInputs": ["lookup.py"], "outputs": ["lookup.py"], "validator": "score.py",
            "executableChecks": ["briefFidelity", "efficientLookup", "scannerCompatibility", "realDeliverable", "naming", "nothingBroken"]}
def register_run(identity, task, result, directory):
    from grant_agent.connected_sessions.runs import RunStore, iso
    from grant_agent.connected_sessions.registry import make_session_id
    from grant_agent.external_chat_inventory import _host
    from grant_agent.task_feedback import capture_outputs
    from grant_agent.lesson_evolver import service_for
    outputs, snapshots, warnings = capture_outputs(directory, task["outputs"])
    data = {"runId": identity, "sessionId": make_session_id("neyvia", _host()["deviceId"], identity), "app": "neyvia", "state": "queued",
            "startedAt": iso(time.time()), "updatedAt": iso(time.time()), "taskText": task["task"], "workspaceRoot": str(directory),
            "outputs": outputs, "outputSnapshots": snapshots, "evidenceWarnings": warnings, "doneStatus": result.get("doneStatus"),
            "skillReceipts": result.get("skillReceipts", {}), "provenance": {"route": result["route"], "modelRuns": result["modelRuns"]}}
    store = RunStore(ROOT / ".agent_control/connected_chats.sqlite3", "c9c-lifecycle-recorder", lambda value: False)
    store.claim(data, identity, None, is_free=lambda value: True, register=lambda: None, unregister=lambda: None)
    data["state"] = "completed"
    store.save(data)
    service_for(ROOT).register_replay(identity, task)
    return data

def run(port):
    guard()
    from grant_agent.durability import atomic_write_json
    from grant_agent.lesson_evolver import service_for, LessonService
    from grant_agent.lesson_replay import replay, digest
    service = service_for(ROOT)
    evidence = {"schema": "neyvia.c9c-lifecycle.v1", "at": time.time(), "passed": False, "checks": [], "limitations": ["Scoped inventory lookup fixture, not general taste or held-out user preference proof."], "root": str(ROOT)}
    if RECEIPT.exists():
        previous = json.loads(RECEIPT.read_text())
        evidence["priorAttempts"] = previous.get("priorAttempts", []) + [{"passed": previous.get("passed"), "error": previous.get("error"), "checks": previous.get("checks", [])}]
    def save():
        atomic_write_json(RECEIPT, evidence)
    def check(name, passed, **detail):
        evidence["checks"].append({"name": name, "passed": bool(passed), **detail})
        save()
        print(json.dumps({"check": name, "passed": bool(passed)}), flush=True)
        if not passed:
            raise ValueError(name)
    cookie = ""
    def http(path, payload):
        request = Request(f"http://127.0.0.1:{port}" + path, json.dumps(payload).encode(), {"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})})
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.load(response), response.headers
        except HTTPError as error:
            return error.code, json.load(error), error.headers
    def api(command, payload):
        status, body, headers = http("/api/backend", {"command": command, "payload": payload})
        if status != 200:
            raise ValueError(f"{command}: {status} {body.get('code')}")
        return body["data"]
    def draft(run_data, reason):
        data = api("task_feedback_submit_command", {"runId": run_data["runId"], "sessionId": run_data["sessionId"], "verdict": "not_quite", "reason": reason, "reasonSource": "typed", "requestId": uuid.uuid4().hex})
        identity = data["feedback"]["id"]
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            job = service.job(identity)
            if job and job["state"] in {"completed", "failed"}:
                break
            time.sleep(.5)
        check("real Luna feedback draft completed", job and job["state"] == "completed", job=job)
        candidates = [row for row in service.list_lessons({"runId": run_data["runId"]}) if row["evidence"]["feedbackId"] == identity]
        check("feedback created a typed quarantined lesson", bool(candidates), candidates=[{"id": row["id"], "line": row["line"], "kind": row["kind"], "draft": row["draft"]} for row in candidates])
        return candidates
    try:
        status, body, headers = http("/api/auth/local-session", {})
        cookie = "; ".join(value.split(";", 1)[0] for value in headers.get_all("Set-Cookie", []))
        check("production local owner authenticated", status == 200 and bool(cookie), status=status)
        task, regression = manifest(), manifest(True)
        directory = REPO / "scripts/evidence/C9c-runs/lifecycle" / uuid.uuid4().hex
        source = replay(task, directory / "source")
        check("source real Luna output passed frozen hard checks", source["valid"], criteria=source["executableCriteria"], modelRuns=source["modelRuns"])
        evidence["source"] = source
        data = register_run("c9c-source-" + uuid.uuid4().hex, task, source, directory / "source")
        evidence["sourceRun"] = data["runId"]
        suite = service.freeze_suite([regression])
        evidence["suiteSha256"] = suite
        candidates = draft(data, "The ordinary lookup is correct but our inventory scanner appends U+200B zero-width space at the END of scanned IDs. For this inventory scanner only, remove trailing U+200B from REQUESTED IDs before matching. Preserve exact stored IDs, normal spaces, request order/repetitions, disabled-row filtering and first-enabled-match behavior. Do not trim any other character or generalize to unrelated apps.")
        selected = next((row for row in candidates if row["kind"] == "guidance" and ("200b" in row["line"].lower() or "zero-width" in row["line"].lower())), candidates[0])
        tested = selected
        deadline = time.monotonic() + 900
        while tested["state"] in {"quarantined", "testing"} and time.monotonic() < deadline:
            time.sleep(.5)
            tested = next(row for row in service.list_lessons({"runId": data["runId"]}) if row["id"] == selected["id"])
            if tested["state"] == "quarantined" and tested.get("reason"):
                raise ValueError(tested["reason"])
        evidence["beneficialTrial"] = tested
        check("beneficial lesson promoted from real paired executable improvement", tested["state"] == "promoted", state=tested["state"], deltas=tested["evolver"]["criterionDeltas"])
        active = service.active_lines()
        promoted = replay(task, directory / "promoted", lines=[row["line"] for row in active], lessons=active)
        check("next real Luna replay consumes promoted lesson", promoted["valid"] and promoted["executableCriteria"]["scannerCompatibility"], criteria=promoted["executableCriteria"])
        evidence["promotedReplay"] = promoted
        parent = tested["lineage"]["parent"]
        request = {"lessonId": selected["id"], "requestId": uuid.uuid4().hex}
        reverted = api("lesson_revert_command", request)["lesson"]
        retry = api("lesson_revert_command", request)["lesson"]
        durable = LessonService(ROOT)
        with durable.db() as db:
            restored, members = durable._head(db, tested["manual"])
        check("one-click production HTTP revert restores exact parent durably and idempotently", reverted["state"] == "reverted" and retry == reverted and restored == parent and selected["id"] not in members and not any(row["id"] == selected["id"] for row in durable.active_lines()), restored=restored, parent=parent)
        evidence["revert"] = reverted
        after_revert = replay(task, directory / "reverted", lines=[row["line"] for row in durable.active_lines()], lessons=durable.active_lines())
        check("post-revert real run restores baseline scanner behavior with instruction absent", after_revert["valid"] and not after_revert["executableCriteria"]["scannerCompatibility"] and not durable.active_lines(), criteria=after_revert["executableCriteria"])
        evidence["revertedReplay"] = after_revert
        # Explicit host-authored adverse candidate. It is not attributed to Paul
        # or passed off as a model draft; only its actual trial is model-produced.
        from copy import deepcopy
        from grant_agent.lesson_evolver import _kind_line
        harmful_row = deepcopy(selected)
        harmful_row.update(id=uuid.uuid4().hex, title="Controlled harmful repeated catalog scan", state="quarantined", evolver=None, lineage=None,
                           kind="guidance", line='M deliverables "For inventory lookup tasks do not build a dictionary or other index. Use a nested loop over all catalog rows for every requested ID, retaining the first enabled match and all original behavior." src:controlled-adverse-fixture state:quarantine',
                           fixtureOrigin="Host-authored harmful candidate; not Paul feedback or a Luna draft")
        _kind_line(harmful_row["kind"], harmful_row["line"], harmful_row["manual"])
        harmful_row["cl"] = "CL 1\nL lesson." + harmful_row["id"] + " v1 manual:" + harmful_row["manual"] + " state:quarantined src:controlled-adverse-fixture\n" + harmful_row["line"] + "\n"
        with service.db() as db:
            service._save(db, harmful_row)
        harmful_row = service.test_lesson(harmful_row["id"])
        evidence["harmfulTrial"] = harmful_row
        check("harmful lesson rejected by real executable trial and never active", harmful_row["state"] == "rejected" and not any(row["id"] == harmful_row["id"] for row in service.active_lines()), state=harmful_row["state"], evolver=harmful_row.get("evolver"))
        evidence["sourceHashes"] = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in ["src/grant_agent/lesson_evolver.py", "src/grant_agent/lesson_replay.py", "scripts/c9c_lifecycle.py"]}
        evidence["passed"] = True
        save()
    except Exception as error:
        evidence["error"] = str(error)
        save()
        raise

def native(port):
    """Verify the actual agent tool route against an already measured lifecycle."""
    guard()
    from grant_agent.durability import atomic_write_json
    from grant_agent.lesson_evolver import LessonService
    from grant_agent.lesson_replay import digest
    evidence = json.loads(RECEIPT.read_text(encoding="utf-8"))
    lesson_id = evidence["revert"]["id"]
    with LessonService(ROOT).db() as db:
        request_id = db.execute("SELECT id FROM requests WHERE intent=?", (digest(["revert", lesson_id]),)).fetchone()[0]
        frozen_manifest, frozen_hash = db.execute("SELECT manifest,hash FROM replays WHERE run=?", (evidence["sourceRun"],)).fetchone()
    evidence["sourceManifest"] = json.loads(frozen_manifest)
    evidence["regressionSuite"] = json.loads((ROOT / ".neyvia/lessons/suite.json").read_text(encoding="utf-8"))
    frozen_inputs_match = digest(evidence["sourceManifest"]) == frozen_hash == evidence["source"]["manifestSha256"] and digest(evidence["regressionSuite"]) == evidence["suiteSha256"]
    with urlopen(Request(f"http://127.0.0.1:{port}/api/auth/local-session", b"{}", {"Content-Type": "application/json"}), timeout=30) as response:
        cookie = "; ".join(value.split(";", 1)[0] for value in response.headers.get_all("Set-Cookie", []))
    records = []
    for tool, args in [("neyvia.lessons.list", {"runId": evidence["sourceRun"]}), ("neyvia.lessons.revert", {"lessonId": lesson_id, "requestId": request_id})]:
        payload = {"tool": tool, "arguments": args, "_expectedStateRoot": str(ROOT.resolve())}
        try:
            with urlopen(Request(f"http://127.0.0.1:{port}/api/ui/tools/call", json.dumps(payload).encode(), {"Content-Type": "application/json", "Cookie": cookie}), timeout=60) as response:
                records.append({"tool": tool, "status": response.status, "body": json.load(response)})
        except HTTPError as error:
            records.append({"tool": tool, "status": error.code, "body": json.load(error)})
    evidence["nativeToolProof"] = records
    native_passed = all(row["status"] == 200 and row["body"]["data"]["ok"] for row in records) and records[1]["body"]["data"]["result"]["lesson"] == evidence["revert"]
    behavioral_revert = evidence["revertedReplay"]["valid"] and not evidence["revertedReplay"]["executableCriteria"]["scannerCompatibility"]
    evidence["checks"].append({"name": "native registered agent list/revert tools return the same durable lifecycle", "passed": native_passed})
    evidence["checks"].append({"name": "independent post-revert behavior restores missing scanner convention", "passed": behavioral_revert})
    evidence["checks"].append({"name": "frozen source manifest and regression suite match all recorded trial identities", "passed": frozen_inputs_match})
    evidence["passed"] = evidence["passed"] and native_passed and behavioral_revert and frozen_inputs_match
    evidence["sourceHashes"] = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in ["src/grant_agent/lesson_evolver.py", "src/grant_agent/lesson_replay.py", "scripts/c9c_lifecycle.py"]}
    atomic_write_json(RECEIPT, evidence)
    print(json.dumps({"nativePassed": native_passed, "behavioralRevert": behavioral_revert}), flush=True)
    if not evidence["passed"]:
        raise ValueError("Native tool or behavioral revert proof failed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["serve", "run", "native"])
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not 48761 <= args.port <= 48769:
        raise ValueError("Use an explicit assigned C9c proof port")
    {"serve": serve, "run": run, "native": native}[args.phase](args.port)
