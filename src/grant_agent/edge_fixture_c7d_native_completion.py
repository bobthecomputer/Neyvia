"""Exact Native completion effects in disposable state, without model execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from .edge_fixture_local import require, refused, _parallel, sha
from .edge_fixture_c7d_local import _isolate, _deny_child_creation, CATEGORIES
from .edge_fixture_missions import exclusive
from .subprocess_utils import hidden_windows_subprocess_kwargs


def _hooks(root, category):
    from .native_hooks import NativeHook, NativeHookRunner, _hash
    for argv in ("echo unsafe", [], [sys.executable, ""], [17]):
        refused(lambda: NativeHook.from_mapping({"id": "invalid", "event": "run.before", "argv": argv}), ValueError)
    script = root / "owned-hook.py"
    source = "import os,json; from pathlib import Path; value=json.loads(os.environ['NEYVIA_HOOK_CONTEXT']); Path('effect-'+str(value['id'])+'.json').write_text(json.dumps(value),encoding='utf8'); print('actual child completed')"
    script.write_text(source, encoding="utf8")
    config = root / ".neyvia/hooks.json"
    config.parent.mkdir()
    mapping = {"id": "owned", "event": "run.before", "argv": [sys.executable, str(script)], "allowMutations": True, "blocking": True, "timeoutSeconds": 20}
    config.write_text(json.dumps({"hooks": [mapping]}), encoding="utf8")
    denied = NativeHookRunner(root).run("run.before", {"id": "denied"})
    require(denied["blocked"] and denied["receipts"][0]["status"] == "approval_required" and not (root / "effect-denied.json").exists(), "Unapproved Native hook executed")
    runner = NativeHookRunner(root, mutations_allowed=True)
    def execute(index):
        result = runner.run("run.before", {"id": index})
        receipt = result["receipts"][0]
        durable = json.loads(Path(receipt["receiptPath"]).read_text(encoding="utf8"))
        require(durable == {k: v for k, v in receipt.items() if k != "receiptPath"} and durable["receiptHash"] == _hash({k: v for k, v in durable.items() if k != "receiptHash"}), "Actual hook receipt differs from durable result/hash")
        require(receipt["returnCode"] == 0 and receipt["passed"] and json.loads((root / f"effect-{index}.json").read_text(encoding="utf8")) == {"id": index}, "Native hook completion differs from actual child effect")
        return receipt["receiptPath"]
    paths = _parallel(execute, range(8)) if category == "concurrency" else [execute(0)]
    require(len(paths) == len(set(paths)), "Concurrent hook receipt identities collided")
    if category == "permissions":
        with exclusive(script):
            result = runner.run("run.before", {"id": "denied-source"})
        receipt = result["receipts"][0]
        require(not receipt["passed"] and receipt["returnCode"] != 0 and not (root / "effect-denied-source.json").exists(), "OS-denied hook source claimed a successful effect")
        previous = {p.name: sha(p.read_bytes()) for p in runner.receipt_root.iterdir()}
        with _deny_child_creation(runner.receipt_root, root):
            refused(lambda: runner.run("run.before", {"id": "unacknowledged"}), OSError)
        require((root / "effect-unacknowledged.json").exists() and {p.name: sha(p.read_bytes()) for p in runner.receipt_root.iterdir()} == previous, "Denied hook publisher fabricated a receipt or changed previous receipts")
        execute(99)
    if category == "interrupted":
        script.write_text("from pathlib import Path; import time; Path('started').write_text('actual child'); time.sleep(30); Path('incorrectly-finished').write_text('wrong')", encoding="utf8")
        config.write_text(json.dumps({"hooks": [{**mapping, "timeoutSeconds": 2}]}), encoding="utf8")
        result = NativeHookRunner(root, mutations_allowed=True).run("run.before", {"id": "timeout"})
        receipt = result["receipts"][0]
        require((root / "started").exists() and not (root / "incorrectly-finished").exists() and receipt["timedOut"] and receipt["status"] == "timed_out" and not receipt["passed"], "Actual timed-out hook invented completed effect")
        require(json.loads(Path(receipt["receiptPath"]).read_text(encoding="utf8")) == {k: v for k, v in receipt.items() if k != "receiptPath"}, "Actual timeout receipt was not exact/durable")
        script.write_text(source, encoding="utf8")
        config.write_text(json.dumps({"hooks": [mapping]}), encoding="utf8")
        execute(100)
    if category == "stale":
        previous = {p.name: sha(p.read_bytes()) for p in runner.receipt_root.iterdir()}
        config.write_text(json.dumps({"hooks": [{**mapping, "event": "run.after"}]}), encoding="utf8")
        fresh = NativeHookRunner(root, mutations_allowed=True)
        require(fresh.run("run.before", {"id": "stale"})["receipts"] == [] and not (root / "effect-stale.json").exists(), "Fresh hook runner reused stale event configuration")
        require({p.name: sha(p.read_bytes()) for p in runner.receipt_root.iterdir()} == previous, "Stale event read changed completed receipts")
        receipt = fresh.run("run.after", {"id": "fresh"})["receipts"][0]
        require(receipt["passed"] and (root / "effect-fresh.json").exists(), "Current hook event failed actual child execution")
    return {"actualCompletedChildren": len(paths), "distinctDurableReceipts": len(set(paths)), "unapprovedChildAbsent": True, "modelExecuted": False}


def _learning(root, category):
    from .native_learning import NativeLearningStore
    store = NativeLearningStore(root)
    prior = {"runId": "prior", "status": "completed", "proofAudit": {"status": "verified"}, "behaviorPlan": {"capsule": {"taskKinds": ["owned"]}}}
    store.record_run(prior)
    def snapshot():
        db = sqlite3.connect(store.path)
        try:
            return [list(row) for row in db.execute("SELECT run_id,verified,status,proof_status FROM native_runs ORDER BY run_id")]
        finally:
            db.close()
    before = snapshot()
    if category == "permissions":
        with exclusive(store.path):
            refused(lambda: store.record_run({**prior, "runId": "denied"}), (OSError, sqlite3.Error))
            refused(lambda: store.recommend("owned", minimum_samples=10), (OSError, sqlite3.Error))
        require(snapshot() == before, "OS-denied learning admission changed durable observations")
    if category == "interrupted":
        program = """import os,sys,sqlite3
from pathlib import Path
from contextlib import contextmanager
from grant_agent.edge_fixture_c7d_local import _isolate
from grant_agent.native_learning import NativeLearningStore
root=Path(sys.argv[1]);_isolate(root,int(sys.argv[2]));store=NativeLearningStore(root);original=store.connection
@contextmanager
def interrupted():
 with original() as db:
  db.set_trace_callback(lambda sql: os._exit(23) if sql=='COMMIT' else None)
  yield db
store.connection=interrupted
store.record_run({'runId':'interrupted','status':'completed','proofAudit':{'status':'verified'},'behaviorPlan':{'capsule':{'taskKinds':['owned']}}})
raise AssertionError('worker missed real SQLite commit')
"""
        completed = subprocess.run([sys.executable, "-c", program, str(root), os.environ["NEYVIA_C7_PORT"]], capture_output=True, text=True, timeout=30, **hidden_windows_subprocess_kwargs())
        require(completed.returncode == 23 and snapshot() == before, "Interrupted actual learning transaction became a completed observation")
    store.record_run({**prior, "runId": "failed", "status": "failed"})
    store.record_run({**prior, "runId": "unaudited", "proofAudit": {"status": "not_audited"}})
    require(snapshot() == [["failed", 0, "failed", "verified"], ["prior", 1, "completed", "verified"], ["unaudited", 0, "completed", "not_audited"]], "Failed/unaudited learning states were promoted to verified success")
    result = store.recommend("owned", minimum_samples=10)
    require(not result["eligible"] and not result["applied"] and result["evidenceRuns"] == 3, "Learning recommendation invented samples or applied itself")
    return {"durableObservedRuns": 3, "verifiedRuns": 1, "sampleFloor": 10, "applied": False, "boundary": "actual local SQLite admission/readback; supplied observation records are not model runs or rendered proof"}


def _goals(root, category):
    from .native_goals import NativeGoalStore
    store = NativeGoalStore(root)
    store.create("Owned actual completion", goal_id="owned", schedule_seconds=60)
    pending = store.create("Still scheduled", goal_id="pending", schedule_seconds=60)
    with store.connection() as db:
        db.execute("UPDATE native_goals SET next_due_at='2000-01-01T00:00:00Z'")
    require({row["goalId"] for row in store.due()} == {"owned", "pending"}, "Initial due observer lost actual scheduled goals")
    program = """from pathlib import Path
import os,sys,json
from grant_agent.edge_fixture_c7d_local import _isolate
from grant_agent.native_goals import NativeGoalStore
root=Path(sys.argv[1]);_isolate(root,int(sys.argv[2]));receipt=root/'producer-receipt.json';receipt.write_text(json.dumps({'producer':'actual owned Python child','result':323}),encoding='utf8');NativeGoalStore(root).complete('owned',str(receipt));os._exit(23)
"""
    completed = subprocess.run([sys.executable, "-c", program, str(root), os.environ["NEYVIA_C7_PORT"]], capture_output=True, text=True, timeout=30, **hidden_windows_subprocess_kwargs())
    receipt = root / "producer-receipt.json"
    require(completed.returncode == 23 and json.loads(receipt.read_text(encoding="utf8"))["result"] == 323, "Owned completion child did not exit after actual receipt publication")
    saved = NativeGoalStore(root).get("owned")
    require(saved["status"] == "completed" and saved["nextDueAt"] is None and saved["completionReceipt"] == str(receipt), "Lost completion acknowledgement lost durable terminal receipt/state")
    require([row["goalId"] for row in NativeGoalStore(root).due()] == ["pending"], "Completion worker exit revived completed goal in due observer")
    with store.connection() as db:
        event = db.execute("SELECT event_type,payload_json FROM native_goal_events WHERE goal_id='owned' ORDER BY event_id DESC LIMIT 1").fetchone()
    require(event[0] == "goal.completed" and json.loads(event[1])["completionReceipt"] == str(receipt), "Completed goal omitted exact durable event receipt")
    return {"childExit": completed.returncode, "terminalGoal": "owned", "dueGoals": ["pending"], "receiptSha256": sha(receipt.read_bytes())}


def _events(root, category):
    from .native_event_stream import NativeEventStream
    stream = NativeEventStream(root, "owned")
    stream.emit("owned.observation", {"value": 323})
    before = stream.path.read_bytes()
    require(stream.verify()["valid"] and stream.verify()["events"] == 1, "Initial actual event chain failed independent verification")
    with exclusive(stream.path):
        denied = stream.verify()
        require(not denied["valid"] and denied["events"] == 0 and denied["failures"], "OS-denied event reader claimed verified chain")
    require(stream.path.read_bytes() == before and stream.verify()["valid"], "Denied event observer changed durable chain or failed fresh read")
    return {"realDeniedRead": True, "chainBytesPreserved": len(before), "freshChainValid": True}


def _skill(root, category):
    from .skill_iteration import read_codex_skill_file, iterate_codex_skill_file
    from . import skill_iteration
    from .edge_fixture_local import replacement_fault
    old_home = os.environ["CODEX_HOME"]
    home = root / "owned-codex-home"
    target = home / "skills/owned/SKILL.md"
    target.parent.mkdir(parents=True)
    original = "---\nname: owned\ndescription: Generated owned fixture\n---\nOriginal source\n"
    target.write_text(original, encoding="utf8")
    digest = sha(target.read_bytes())
    prefix = "---\nname: owned\ndescription: Generated owned fixture\n---\n"
    body = "x" * 400000 if category == "huge" else "雪🙂e\u0301 العربية" if category == "unicode" else "Actual local revision"
    revised = prefix + body + "\n"
    payload = {"path": str(target), "content": revised, "expectedSha256": digest, "request": "Owned fixture revision"}
    os.environ["CODEX_HOME"] = str(home)
    try:
        require(read_codex_skill_file({"path": str(target)})["content"] == original, "Generated skill read lost exact original bytes")
        for invalid in (root / "foreign/SKILL.md", target.with_name("other.md")):
            refused(lambda: read_codex_skill_file({"path": str(invalid)}), RuntimeError)
        if category in {"empty", "huge"}:
            refused(lambda: iterate_codex_skill_file({**payload, "content": "" if category == "empty" else prefix + "x" * 512001}, root), RuntimeError)
            require(target.read_text(encoding="utf8") == original, "Invalid skill body changed original bytes")
        if category == "permissions":
            with exclusive(target):
                refused(lambda: read_codex_skill_file({"path": str(target)}), OSError)
                refused(lambda: iterate_codex_skill_file(payload, root), OSError)
            require(target.read_text(encoding="utf8") == original, "Native denied skill read/revision changed source")
        if category == "interrupted":
            with replacement_fault(skill_iteration, target, KeyboardInterrupt) as stopped:
                refused(lambda: iterate_codex_skill_file(payload, root), KeyboardInterrupt)
            require(stopped and target.read_text(encoding="utf8") == original and not list((root / ".agent_control/skill_revisions").rglob("*.json")), "Interrupted skill publisher changed source or fabricated completed version receipt")
        if category == "concurrency":
            program = """from pathlib import Path
import os,sys,json,time
from grant_agent.edge_fixture_c7d_local import _isolate
from grant_agent.skill_iteration import iterate_codex_skill_file
root=Path(sys.argv[1]);_isolate(root,int(sys.argv[2]));os.environ['CODEX_HOME']=sys.argv[3];index=sys.argv[5];(root/('ready-'+index)).write_text('ready')
while not (root/'go').exists():time.sleep(.005)
try:
 value=iterate_codex_skill_file({'path':sys.argv[4],'content':'---\\nname: owned\\ndescription: Generated owned fixture\\n---\\nWriter '+index+'\\n','expectedSha256':sys.argv[6]},root);print(json.dumps({'index':index,'status':'passed','receipt':value}))
except RuntimeError as error:print(json.dumps({'index':index,'status':'refused','error':str(error)}))
"""
            children = [subprocess.Popen([sys.executable, "-c", program, str(root), os.environ["NEYVIA_C7_PORT"], str(home), str(target), str(i), digest], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf8", **hidden_windows_subprocess_kwargs()) for i in range(8)]
            import time
            deadline = time.monotonic() + 30
            while len(list(root.glob("ready-*"))) < 8 and time.monotonic() < deadline:
                time.sleep(.01)
            require(len(list(root.glob("ready-*"))) == 8, "Owned simultaneous skill writers failed admission")
            (root / "go").write_text("go")
            outcomes = []
            for child in children:
                out, error = child.communicate(timeout=30)
                require(child.returncode == 0 and out, "Owned skill writer failed outside expected CAS refusal: " + error[-500:])
                outcomes.append(json.loads(out))
            winners = [row for row in outcomes if row["status"] == "passed"]
            require(len(winners) == 1 and sum(row["status"] == "refused" and "changed since" in row["error"] for row in outcomes) == 7, "Crossprocess skill CAS did not produce one exact winner and seven stale refusals")
            result = winners[0]["receipt"]
            revised = prefix + "Writer " + winners[0]["index"] + "\n"
        else:
            result = iterate_codex_skill_file(payload, root)
        require(target.read_text(encoding="utf8") == revised and Path(result["backupPath"]).read_text(encoding="utf8") == original and json.loads(Path(result["receiptPath"]).read_text(encoding="utf8"))["afterSha256"] == sha(target.read_bytes()), "Completed skill revision lost exact source/before-image/durable version hash")
        if category == "stale":
            before = target.read_bytes()
            refused(lambda: iterate_codex_skill_file({**payload, "content": prefix + "stale\n"}, root), RuntimeError)
            require(target.read_bytes() == before, "Stale skill CAS overwrote current source")
            fresh = iterate_codex_skill_file({**payload, "content": prefix + "current\n", "expectedSha256": sha(before)}, root)
            require(target.read_text(encoding="utf8") == prefix + "current\n" and fresh["beforeSha256"] == sha(before), "Fresh skill CAS failed current source revision")
        return {"sourceSha256": sha(target.read_bytes()), "originalPreservedSha256": sha(Path(result["backupPath"]).read_bytes()), "simultaneousWriters": 8 if category == "concurrency" else 1, "sourceBytes": target.stat().st_size, "actualOperatorSkillsTouched": False}
    finally:
        os.environ["CODEX_HOME"] = old_home


def _catalog(root, category):
    from .native_tools import NativeToolRegistry
    from dataclasses import asdict
    registry = NativeToolRegistry(root, nas_root=root / "owned-unmounted-route")
    specs = registry._specs
    def observe(_=None):
        rows = registry.list_tools(include_schemas=True)
        require({row["name"] for row in rows} == set(specs), "Catalog lost or duplicated actual Native declarations")
        for row in rows:
            declared = asdict(specs[row["name"]]); declared.pop("input_schema")
            require(all(row[k] == v for k, v in declared.items()) and row["inputSchema"] == specs[row["name"]].input_schema and isinstance(row["available"], bool), "Native catalog differs from exact typed declarations/schema/availability")
            require(registry.describe(row["name"]) == row, "Actual describe differs from exact catalog declaration/authority")
        return rows
    rows = observe()
    if category == "concurrency":
        require(all(value == rows for value in _parallel(observe, range(8))), "Concurrent Native metadata observers disagreed")
    if category == "stale":
        old_home = os.environ["CODEX_HOME"]
        current = root / "new-codex-home"
        try:
            os.environ["CODEX_HOME"] = str(current)
            require(not registry.describe("skill.live.read")["available"], "Missing current skill root inherited stale availability")
            current.mkdir()
            require(registry.describe("skill.live.read")["available"] and next(row for row in registry.list_tools() if row["name"] == "skill.live.read")["available"], "Native catalog reused stale missing skill availability after actual root creation")
        finally:
            os.environ["CODEX_HOME"] = old_home
    return {"exactDeclarations": len(specs), "concurrentObservers": 8 if category == "concurrency" else 1, "actualHandlersExecuted": 0, "renderedProof": False, "nasContacted": False}


def _preview(root, category):
    """Exercise production preview dispatch against an owned loopback HTTP server."""
    from .native_tools import NativeToolRegistry
    port = int(os.environ["NEYVIA_C7_PORT"])
    from .proof_ports import c7_port_block
    c7_port_block(port)
    state = {"body": b"<html><title>owned old</title><body>Alpha owned marker</body></html>", "status": 200}
    hit, release = threading.Event(), threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hit.set()
            if category == "interrupted":
                release.wait(12)
            body = state["body"]
            try:
                self.send_response(state["status"])
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    registry = NativeToolRegistry(root, nas_root=root / "owned-unmounted-route")
    url = f"http://127.0.0.1:{port}/owned-preview"
    def inspect():
        return registry.call("preview.inspect", {"url": url, "query": "owned marker"})
    child = None
    try:
        if category == "permissions":
            state["status"] = 403
            denied = inspect()
            require(not denied["ok"] and "403" in denied["error"], "HTTP 403 was reported as a successful preview")
            state["status"] = 200
        if category == "interrupted":
            program = "from pathlib import Path; import sys; sys.path.insert(0, sys.argv[3]); from c7_dependencies import configure; configure(); from grant_agent.proof_credential_guard import install; root=Path(sys.argv[1]); install(root); from grant_agent.native_tools import NativeToolRegistry; NativeToolRegistry(root, nas_root=root/'owned-unmounted-route').call('preview.inspect', {'url':sys.argv[2], 'query':'owned marker'})"
            before_receipts = {p.name: sha(p.read_bytes()) for p in registry.receipt_root.glob('*.json')}
            child_env = dict(os.environ)
            child_env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            child = subprocess.Popen([sys.executable, "-c", program, str(root), url, str(Path(__file__).resolve().parents[2] / 'scripts')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env, **hidden_windows_subprocess_kwargs())
            if not hit.wait(30):
                if child.poll() is not None:
                    raise AssertionError('Preview child failed before HTTP: ' + child.stderr.read().decode('utf8', errors='replace')[-3000:])
                raise AssertionError('Preview child did not reach the actual HTTP handler')
            child.terminate()
            require(child.wait(timeout=8) != 0, "terminated preview child unexpectedly completed normally")
            require({p.name: sha(p.read_bytes()) for p in registry.receipt_root.glob('*.json')} == before_receipts,
                    'Interrupted HTTP inspection fabricated a completed native tool receipt')
            release.set()
        result = inspect()
        require(result["ok"] and result["result"]["status"] == 200 and result["result"]["matches"]
                and "owned marker" in result["result"]["matches"][0]["excerpt"],
                "Native preview dispatch lost actual HTTP response or query match")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=6) as pool:
                rows = list(pool.map(lambda _: inspect(), range(6)))
            require(all(row["ok"] and row["result"]["contentSha256"] == rows[0]["result"]["contentSha256"] for row in rows),
                    "Concurrent native preview calls disagreed on actual response digest")
        if category == "stale":
            previous = result["result"]["contentSha256"]
            state["body"] = "<html><body>Fresh owned marker 雪</body></html>".encode("utf-8")
            fresh = registry.call("preview.inspect", {"url": url + "-fresh", "query": "owned marker"})
            require(fresh["ok"] and fresh["result"]["contentSha256"] != previous and "Fresh owned marker" in fresh["result"]["text"],
                    "Fresh preview reused stale HTTP bytes or digest")
        return {"dispatch": "preview.inspect", "origin": url, "category": category,
                "responseSha256": result["result"]["contentSha256"], "httpPermissionDenied": category == "permissions",
                "childInterruptedInRequest": category == "interrupted", "renderedProof": False}
    finally:
        release.set()
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=8)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _checkpoint(root, category):
    from .native_checkpoints import NativeCheckpointStore
    from .edge_fixture_native import _sharing_denied, TEXT
    text = TEXT.get(category, "owned checkpoint bytes")
    first, second = root / "a-雪.txt", root / "b.txt"
    captured = [text.encode("utf8"), b"captured second"]
    current = [b"current first", b"current second"]
    for path, data in zip((first, second), captured):
        path.write_bytes(data)
    store = NativeCheckpointStore(root)
    capture = store.create([first.name, second.name], reason=text, run_id="owned")
    for entry in capture["entries"]:
        path = root / entry["path"]
        digest = entry["sha256"]
        require(entry["size"] == path.stat().st_size and sha(path.read_bytes()) == digest and (store.blob_root / digest[:2] / digest).read_bytes() == path.read_bytes(), "Checkpoint capture differs from actual manifest/blob/source bytes")
    require(json.loads(Path(capture["manifestPath"]).read_text(encoding="utf8")) == {k:v for k,v in capture.items() if k != "manifestPath"}, "Actual checkpoint manifest differs from result")
    refused(lambda: store.create(["../foreign.txt"]), ValueError)
    for path, data in zip((first, second), current):
        path.write_bytes(data)
    def exact_current():
        return [p.read_bytes() for p in (first, second)] == current
    require(store.restore(capture["checkpointId"])["status"] == "approval_required" and exact_current(), "Unapproved checkpoint restore changed workspace")
    manifest_path = Path(capture["manifestPath"])
    original_manifest = manifest_path.read_bytes()
    bad = json.loads(original_manifest)
    bad["entries"][0]["path"] = "../foreign.txt"
    manifest_path.write_text(json.dumps(bad), encoding="utf8")
    require(store.restore(capture["checkpointId"], approved=True)["status"] == "failed_preflight" and exact_current(), "Foreign/corrupt checkpoint mutated before full preflight")
    manifest_path.write_bytes(original_manifest)
    if category == "permissions":
        with exclusive(first):
            refused(lambda: store.create([first.name]), OSError)
        with exclusive(manifest_path):
            denied = store.restore(capture["checkpointId"], approved=True)
        require(denied["status"] == "failed_preflight" and exact_current(), "OS-denied manifest changed workspace or invented restore")
    with _sharing_denied(second, allow_read=True):
        rolled = store.restore(capture["checkpointId"], approved=True)
    require(rolled["status"] == "failed_rolled_back" and rolled["workspaceSafe"] and exact_current(), "Actual second-write denial lost checkpoint before-images")
    require(json.loads(Path(rolled["receiptPath"]).read_text(encoding="utf8")) == {k:v for k,v in rolled.items() if k != "receiptPath"}, "Actual rollback receipt differs from durable result")
    program = """import os,sys
from pathlib import Path
from grant_agent.edge_fixture_c7d_local import _isolate
from grant_agent.native_checkpoints import NativeCheckpointStore
root=Path(sys.argv[1]);_isolate(root,int(sys.argv[2]))
class Interrupted(NativeCheckpointStore):
 def _apply_entries(self,entries):
  value=super()._apply_entries(entries[:1]);os._exit(23)
Interrupted(root).restore(sys.argv[3],approved=True)
"""
    child = subprocess.run([sys.executable,"-c",program,str(root),os.environ["NEYVIA_C7_PORT"],capture["checkpointId"]], capture_output=True, text=True, encoding="utf8", timeout=30, **hidden_windows_subprocess_kwargs())
    require(child.returncode == 23 and first.read_bytes() == captured[0] and second.read_bytes() == current[1], "Owned checkpoint worker did not exit after exact first mutation")
    journals = list(store.transaction_root.glob("*.json"))
    applying = next(p for p in journals if json.loads(p.read_text(encoding="utf8"))["status"] == "applying")
    prior_journal = applying.read_bytes()
    if category == "permissions":
        with exclusive(applying):
            denied = NativeCheckpointStore(root)
            require(denied.recovery_error and not denied.restore(capture["checkpointId"],approved=True)["workspaceSafe"], "OS-denied recovery journal invented a safe restore")
        require(applying.read_bytes() == prior_journal and first.read_bytes() == captured[0] and second.read_bytes() == current[1], "Denied recovery changed journal or partially restored before-image")
    if category == "stale":
        first.write_bytes(b"legitimate newer outside transaction edit")
        blocked = NativeCheckpointStore(root)
        require(blocked.recovery_error and first.read_bytes() == b"legitimate newer outside transaction edit" and not blocked.restore(capture["checkpointId"],approved=True)["workspaceSafe"], "Stale checkpoint rollback overwrote a newer legitimate edit")
        require(json.loads(applying.read_text(encoding="utf8"))["status"] == "recovery_failed" and NativeCheckpointStore(root).recovery_error, "Conflicting checkpoint recovery failed to retain its manual-recovery boundary")
        return {"actualInterruptedExit":child.returncode,"actualWriteFailureRolledBack":True,"newerEditPreserved":True,"manualRecoveryRequired":True,"workspaceSafe":False,"renderedProof":False}
    recovered = NativeCheckpointStore(root)
    require(not recovered.recovery_error and exact_current() and json.loads(applying.read_text(encoding="utf8"))["status"] == "rolled_back", "Interrupted restore did not recover exact before-images before new mutation")
    if category == "concurrency":
        captures = _parallel(lambda i: recovered.create([first.name, second.name], run_id="reader-"+str(i)), range(8))
        require(len({r["checkpointId"] for r in captures}) == 8 and all(r["entries"] == captures[0]["entries"] for r in captures), "Concurrent checkpoint captures lost distinct actual manifests")
        results = _parallel(lambda _: NativeCheckpointStore(root).restore(capture["checkpointId"],approved=True), range(8))
    else:
        results = [recovered.restore(capture["checkpointId"], approved=True)]
    for result in results:
        require(result["status"] == "completed" and result["restored"] and json.loads(Path(result["receiptPath"]).read_text(encoding="utf8")) == {k:v for k,v in result.items() if k != "receiptPath"}, "Recovered checkpoint result lacks exact terminal durable receipt")
    require([p.read_bytes() for p in (first,second)] == captured, "Recovered successful checkpoint restoration differs from captured bytes")
    return {"actualInterruptedExit":child.returncode,"actualWriteFailureRolledBack":True,"restoredSourceBytes":sum(map(len,captured)),"terminalRestoreReceipts":len(results),"workspaceSafe":True,"renderedProof":False}


def _spawn(root, category):
    from .native_spawn_contracts import NativeSpawnRegistry, SpecialistRoute
    from .native_spawn_evaluator import evaluate_spawn_receipt
    from .edge_fixture_native import TEXT
    text = TEXT.get(category, "owned child output 雪")
    registry = NativeSpawnRegistry(root, "parent:owned")
    route = SpecialistRoute.from_mapping("verifier", {"provider":"local-fixture","allowMutations":False,"requiredEvidence":[]}, default_model="no-model-invoked")
    plan = sha(b"actual owned child fixture plan")
    source = root / "owned-child.py"
    source.write_text("import sys;from pathlib import Path;sys.stdout.write(Path(sys.argv[1]).read_text(encoding='utf8'))", encoding="utf8")
    payload = root / "payload.txt"; payload.write_text(text, encoding="utf8")
    def observe(index):
        contract = registry.start(route, text + str(index), plan)
        child = subprocess.run([sys.executable,str(source),str(payload)],capture_output=True,text=True,encoding="utf8",timeout=30,env={**os.environ,"PYTHONIOENCODING":"utf-8"},**hidden_windows_subprocess_kwargs())
        require(child.returncode == 0 and child.stdout == text, "Owned spawn child output differs from actual process")
        result = registry.finish(contract,status="completed",output=child.stdout,run_items=["actual-owned-process-output"])
        durable = json.loads(Path(result["receiptPath"]).read_text(encoding="utf8"))
        require(durable == {k:v for k,v in result.items() if k != "receiptPath"} and result["outputHash"] == sha(child.stdout.encode("utf8")), "Spawn terminal receipt changed actual output/hash")
        row = next(r for r in registry.snapshot()["children"] if r["spawn_id"] == contract["spawnId"])
        require(row["status"] == result["status"] and row["parent_session_id"] == contract["parentSessionId"] and row["child_session_id"] == contract["childSessionId"] and row["plan_hash"] == plan and row["output_hash"] == result["outputHash"] and row["receipt_path"] == result["receiptPath"], "Actual spawn durable registry/lineage differs from receipt")
        evaluation = evaluate_spawn_receipt(result["receiptPath"],expected_parent_session_id="parent:owned",expected_plan_hash=plan)
        require(evaluation["accepted"] == bool(text.strip()), "Spawn evaluator accepted empty actual child output or refused nonempty exact lineage")
        for altered in ({**durable,"status":"failed","output":"pleasant successful prose"},{**durable,"parentSessionId":"foreign"},{**durable,"planHash":"foreign"},{**durable,"outputHash":"f"*64},{**durable,"route":{**durable["route"],"allowMutations":True}}):
            require(not evaluate_spawn_receipt(altered,expected_parent_session_id="parent:owned",expected_plan_hash=plan)["accepted"], "Spawn evaluator masked explicit status/lineage/hash/authority failure")
        return result
    if category == "permissions":
        with exclusive(registry.db_path):
            refused(lambda: registry.start(route,"denied",plan),(OSError,sqlite3.Error))
        require(registry.snapshot()["children"] == [], "OS-denied spawn admission created a child")
        unfinished = registry.start(route,"publisher denied",plan)
        with _deny_child_creation(registry.receipt_root,root):
            refused(lambda: registry.finish(unfinished,status="completed",output="must not be acknowledged"),OSError)
        row = registry.snapshot()["children"][0]
        require(row["status"] == "running" and not row["receipt_path"] and not list(registry.receipt_root.glob("*.json")), "OS-denied spawn publisher fabricated terminal durable completion")
        failed = registry.finish(unfinished,status="failed",error="Actual publisher denied before acknowledgement")
        require(not evaluate_spawn_receipt(failed["receiptPath"])["accepted"], "Publisher refusal accepted as successful child")
    if category == "interrupted":
        program = """import os,sys,json
from pathlib import Path
from grant_agent.edge_fixture_c7d_local import _isolate
from grant_agent.native_spawn_contracts import NativeSpawnRegistry,SpecialistRoute
root=Path(sys.argv[1]);_isolate(root,int(sys.argv[2]));store=NativeSpawnRegistry(root,'parent:owned');route=SpecialistRoute.from_mapping('verifier',{'provider':'local-fixture','allowMutations':False},default_model='no-model-invoked');contract=store.start(route,'actual child interrupted before terminal output',sys.argv[3]);(root/'interrupted-contract.json').write_text(json.dumps(contract),encoding='utf8');os._exit(23)
"""
        child = subprocess.run([sys.executable,"-c",program,str(root),os.environ["NEYVIA_C7_PORT"],plan],capture_output=True,text=True,encoding="utf8",timeout=30,**hidden_windows_subprocess_kwargs())
        require(child.returncode == 23, "Owned spawn child failed to reach actual interruption")
        contract = json.loads((root/"interrupted-contract.json").read_text(encoding="utf8"))
        row = registry.snapshot()["children"][0]
        require(row["status"] == "running" and not row["receipt_path"], "Interrupted child invented terminal completion before output")
        terminal = registry.finish(contract,status="failed",error="Observed actual child exit23 before terminal output")
        require(not evaluate_spawn_receipt(terminal["receiptPath"],expected_parent_session_id="parent:owned",expected_plan_hash=plan)["accepted"], "Actual child interruption was hidden by receipt acceptance")
    if category == "concurrency":
        receipts = _parallel(observe,range(8))
        require(len({r["spawnId"] for r in receipts}) == 8 and len({r["childSessionId"] for r in receipts}) == 8, "Concurrent actual spawned children lost unique lineage")
    else:
        receipts = [observe(0)]
    if category == "stale":
        prior = receipts[0]
        require(not evaluate_spawn_receipt(prior["receiptPath"],expected_parent_session_id="new-current-parent",expected_plan_hash=plan)["accepted"] and not evaluate_spawn_receipt(prior["receiptPath"],expected_parent_session_id="parent:owned",expected_plan_hash=sha(b"new current plan"))["accepted"], "Old spawn receipt inherited new current parent/plan authority")
    return {"actualCompletedChildren":len(receipts),"durableChildren":len(registry.snapshot()["children"]),"actualOutputCharacters":len(text),"modelCalls":0,"renderedProof":False,"receiptIntegrityOnly":True}


def _compact(root, category):
    from .proof_credential_guard import prepare_broker_fixture
    from .neyvia_mcp_stdio import CompactNeyviaMCPServer
    from .manual_first import core_tools
    from .edge_fixture_native import TEXT
    prepare_broker_fixture(root)
    server = CompactNeyviaMCPServer(root, read_only=True)
    text = TEXT.get(category,"workspace")
    def call(name,arguments):
        return server.handle({"jsonrpc":"2.0","id":"owned","method":"tools/call","params":{"name":name,"arguments":arguments}})
    def observe(_=None):
        catalog = server.handle({"jsonrpc":"2.0","id":"catalog","method":"tools/list","params":{}})
        require(catalog["result"]["tools"] == core_tools() and catalog["result"]["catalogPolicy"]["mode"] == "manual-first" and not {"neyvia.workspace.browser","neyvia.workspace.prove"}.intersection(t["name"] for t in catalog["result"]["tools"]), "Compact actual catalog differs from deferred manual-first authority surface")
        query = call("neyvia.tools.search",{"query":text,"limit":20})
        require("error" not in query and isinstance(query["result"]["structuredContent"].get("tools"),list), "Compact progressive search failed actual caller query")
        described = call("neyvia.tools.describe",{"name":"neyvia.workspace.prove"})["result"]["structuredContent"]
        require(described["callTarget"] == "neyvia.tools.invoke" and "operation" in described["inputSchema"]["properties"], "Deferred exact compact discovery lost callable schema/target")
        for name,args in ((described["callTarget"],{**described["callArguments"],"arguments":{"operation":"click"}}),("neyvia.workspace.browser",{"operation":"click"}),("unknown.tool"+text,{}),("model.tools.run",{"calls":[{"callTarget":"neyvia.workspace.browser","arguments":{"operation":"click"}}]})):
            denied = call(name,args)
            require(denied.get("error",{}).get("code") == -32003, "Compact direct/deferred/nested mutation bypassed effective read-only permission")
        denied = call("neyvia.native.call",{"toolId":"workspace.write","arguments":{"path":"must-not-exist.txt","content":text},"actionId":"owned-denied"})
        refusal = denied.get("result",{}).get("structuredContent",{})
        require(not (root/"must-not-exist.txt").exists() and ("error" in denied or refusal.get("ok") is False and refusal.get("status") == "approval_required"), "Compact Native gateway bypassed effective read-only permission")
        return len(query["result"]["structuredContent"]["tools"])
    observations = _parallel(observe,range(8)) if category == "concurrency" else [observe()]
    if category == "stale":
        old = CompactNeyviaMCPServer(root,read_only=False)
        descriptor = old.handle({"jsonrpc":"2.0","id":"old","method":"tools/call","params":{"name":"neyvia.tools.describe","arguments":{"name":"neyvia.workspace.prove"}}})["result"]["structuredContent"]
        fresh = CompactNeyviaMCPServer(root,read_only=True)
        result = fresh.handle({"jsonrpc":"2.0","id":"fresh","method":"tools/call","params":{"name":descriptor["callTarget"],"arguments":{**descriptor["callArguments"],"arguments":{"operation":"click"}}}})
        require(result.get("error",{}).get("code") == -32003, "Old deferred schema transferred mutation authority to fresh read-only run")
    for instance in ([server,old,fresh] if category == "stale" else [server]):
        instance.server.mcp_broker.close()
        if getattr(instance.server.capability_os,"_model_tool_broker",None) is not None:
            instance.server.capability_os._model_tool_broker.close()
    return {"actualCatalogQueries":len(observations),"progressiveResultCounts":observations,"directDeferredNestedRefusals":True,"workspaceMutationAbsent":True,"renderedProof":False}


def _pairing_interrupt(root, category):
    from .native_pairing import NativePairingStore
    store = NativePairingStore(root)
    prior = store.create("phone",scopes=["device.commands"])
    program = """import os,sys
from pathlib import Path
from contextlib import contextmanager
from grant_agent.edge_fixture_c7d_local import _isolate
from grant_agent.native_pairing import NativePairingStore
root=Path(sys.argv[1]);_isolate(root,int(sys.argv[2]));store=NativePairingStore(root);original=store.connection
@contextmanager
def interrupted():
 with original() as db:
  db.set_trace_callback(lambda sql:os._exit(23) if sql.strip().upper()=='COMMIT' else None)
  yield db
store.connection=interrupted
store.redeem(sys.argv[3],sys.argv[4],'actual interrupted redemption')
"""
    child = subprocess.run([sys.executable,"-c",program,str(root),os.environ["NEYVIA_C7_PORT"],prior["pairingId"],prior["pairingToken"]],capture_output=True,text=True,encoding="utf8",timeout=30,**hidden_windows_subprocess_kwargs())
    require(child.returncode == 23 and store.list_devices() == [], "Interrupted pairing redemption committed a partial device or consumed its request")
    result = store.redeem(prior["pairingId"],prior["pairingToken"],"Recovered one actual device")
    require(store.authenticate(result["deviceId"],result["deviceSecret"],"device.commands"), "Recovered actual paired device lost scoped authentication")
    refused(lambda:store.redeem(prior["pairingId"],prior["pairingToken"],"duplicate"),ValueError)
    with store.connection() as db:
        row = dict(db.execute("SELECT * FROM pairing_requests WHERE pairing_id=?",(prior["pairingId"],)).fetchone())
        device = dict(db.execute("SELECT * FROM paired_devices WHERE device_id=?",(result["deviceId"],)).fetchone())
    raw = json.dumps([row,device])
    require(prior["pairingToken"] not in raw and result["deviceSecret"] not in raw and row["token_hash"] == sha((row["token_salt"]+":"+prior["pairingToken"]).encode("utf8")), "Actual recovered pairing persisted plaintext or altered digest")
    store.revoke(result["deviceId"])
    require(not store.authenticate(result["deviceId"],result["deviceSecret"],"device.commands"), "Revoked recovered paired device retained authority")
    return {"actualInterruptedExit":child.returncode,"oneRecoveredDevice":True,"duplicateRedemptionRefused":True,"plaintextSecretsPersisted":False,"physicalDeviceContacted":False}


def _tool_receipt(root,category):
    from . import native_tools
    from .native_tools import NativeToolRegistry
    registry = NativeToolRegistry(root,nas_root=root/"owned-unmounted-route")
    source = root/"owned.txt"; source.write_text("owned exact source 雪",encoding="utf8")
    arguments = {"path":source.name,"maxChars":1000}
    previous = registry.call("workspace.read",arguments)
    require(previous["ok"] and previous["result"]["content"] == source.read_text(encoding="utf8") and previous["arguments"] == arguments and previous["receiptHash"], "Actual Native source reader returned different bytes or omitted admitted argument/digest binding")
    prior = {p.name:sha(p.read_bytes()) for p in registry.receipt_root.glob("*.json")}
    original = native_tools.os.replace
    attempted = []
    def interrupted(before,after,*args,**kwargs):
        if Path(after).parent == registry.receipt_root:
            attempted.append(str(after));raise KeyboardInterrupt("Owned actual tool receipt publication cut")
        return original(before,after,*args,**kwargs)
    native_tools.os.replace = interrupted
    try:
        refused(lambda:registry.call("workspace.read",arguments),KeyboardInterrupt)
    finally:
        native_tools.os.replace = original
    require(attempted and {p.name:sha(p.read_bytes()) for p in registry.receipt_root.glob("*.json")} == prior and source.read_text(encoding="utf8") == "owned exact source 雪", "Interrupted tool receipt publisher fabricated completion or changed existing receipts/source")
    fresh = registry.call("workspace.read",arguments)
    require(fresh["ok"] and fresh["result"] == previous["result"] and json.loads(Path(fresh["receipt_path"]).read_text(encoding="utf8")) == fresh, "Fresh actual Native tool read lacks exact durable receipt")
    return {"actualPublicationCuts":len(attempted),"completedReceiptCount":len(list(registry.receipt_root.glob("*.json"))),"actualSourceUnchanged":True,"renderedProof":False}


def _inspiration(root,category):
    from .native_tools import NativeToolRegistry
    from .edge_fixture_native import TEXT,_offline
    import copy
    registry=NativeToolRegistry(root,nas_root=root/"owned-unmounted-route")
    text=TEXT.get(category,"owned inspiration query")
    arguments={"query":text,"surface":text,"platform":text,"style":text,"color":text,"layout":text,"limit":24 if category=="huge" else 1}
    original=copy.deepcopy(arguments)
    query,facets,enriched,search=registry._inspiration_request(arguments)
    expected={"surface":text.strip() or "product interface","platform":text.strip() or "desktop web app","style":text.strip(),"color":text.strip(),"layout":text.strip()}
    require(query==text.strip() and facets==expected and search=={"query":enriched,"limit":arguments["limit"],"safeSearch":"moderate","color":expected["color"],"layout":expected["layout"]} and arguments==original,"Actual inspiration query transform lost typed caller facets/defaults or changed source")
    require(enriched==" ".join(v for v in (query,expected["surface"],expected["platform"],expected["style"],"UI UX interface screenshot design inspiration") if v),"Inspiration enrichment changed requested surface/platform/style")
    records=[{"title":text.strip(),"image":f"http://127.0.0.1:{os.environ['NEYVIA_C7_PORT']}/owned-observation-{i}.png","source":"caller-provided assembler input","observedAt":"2000-01-01T00:00:00Z"} for i in range(512 if category=="huge" else 0 if category=="empty" else 3)]
    payload={"provider":"owned-caller-supplied-records","results":records}
    prior=copy.deepcopy(payload)
    def observe(_=None):
        board=registry._inspiration_board(query,facets,enriched,payload)
        require(board=={"query":query,"searchQuery":enriched,"provider":payload["provider"],"facets":facets,"results":records,"resultCount":len(records),"boardType":"ui-inspiration"} and payload==prior,"Actual inspiration board assembly changed supplied record identity/age or invented provider freshness")
        require("fresh" not in board and "verified" not in board and "rendered" not in board,"Inspiration assembly manufactured observed freshness/rendering")
        return board
    boards=_parallel(observe,range(8)) if category=="concurrency" else [observe()]
    if category=="stale":
        newer={"provider":"newer-caller-supplied-records","results":[{"title":"current caller record 雪","observedAt":"2026-10-05T00:00:00Z"}]}
        current=registry._inspiration_board(query,facets,enriched,newer)
        require(current["results"]==newer["results"] and current["provider"]==newer["provider"] and boards[0]["results"]==records and records[0]["observedAt"]=="2000-01-01T00:00:00Z","New inspiration assembly silently reused or rewrote older observations")
    if category=="offline":
        import socket
        key="NEYVIA_SEARXNG_URL";old=os.environ.get(key)
        os.environ[key]="http://127.0.0.1:"+os.environ["NEYVIA_C7_PORT"]
        resolver=socket.getaddrinfo;resolutions=[]
        def unavailable(host,port,*args,**kwargs):
            resolutions.append((host,port));raise OSError("Owned actual image-search resolver unavailable")
        socket.getaddrinfo=unavailable
        try:
            with _offline() as attempts:
                refused(lambda:registry._ui_inspiration_search(arguments),(OSError,RuntimeError))
            require((resolutions or attempts) and payload==prior,"Actual unavailable image-search transport fabricated a fresh board")
        finally:
            socket.getaddrinfo=resolver
            if old is None:os.environ.pop(key,None)
            else:os.environ[key]=old
    return {"actualQueryCharacters":len(query),"callerProvidedRecords":len(records),"assemblerObservations":len(boards),"offlineTransportRefused":category=="offline","upstreamProviderResultsClaimed":False,"callerRecordsNotRenderedProof":True,"imagesDownloaded":0}


def _core_mcp_interrupt(root,category):
    from .proof_credential_guard import prepare_broker_fixture
    from .neyvia_mcp import NeyviaMCPServer
    prepare_broker_fixture(root)
    server = NeyviaMCPServer(root)
    parent = server.conversations.create_conversation(kind="chat",title="Owned parent")
    def snapshot():
        db = sqlite3.connect(server.store.database_path)
        try:
            return {table: sorted(db.execute('SELECT * FROM "'+table+'"').fetchall(),key=repr) for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%fts%' AND name NOT LIKE 'sqlite_%'")}
        finally:db.close()
    before = snapshot()
    program = """import os,sys
from pathlib import Path
from contextlib import contextmanager
from grant_agent.edge_fixture_c7d_local import _isolate
from grant_agent.neyvia_mcp import NeyviaMCPServer
root=Path(sys.argv[1]);_isolate(root,int(sys.argv[2]));server=NeyviaMCPServer(root);family=sys.argv[3];owner=server.conversations if family=='conversation' else server.store;original=owner._connection
@contextmanager
def interrupted():
 with original() as db:
  db.set_trace_callback(lambda sql:os._exit(23) if sql.strip().upper()=='COMMIT' else None)
  yield db
owner._connection=interrupted
if family=='task':params={'name':'neyvia.research.start','arguments':{'missionId':'owned','query':'actual interrupted work','idempotencyKey':'owned-interrupted-task'},'task':{'ttl':60000}}
elif family=='autonomy':params={'name':'neyvia.autonomy.grant','arguments':{'allowedActions':['file_write'],'allowedRoots':[str(root)],'durationSeconds':300}}
else:params={'name':'neyvia.question.branch','arguments':{'parentConversationId':sys.argv[4],'question':'actual interrupted durable question'}}
server._call_tool(params)
"""
    for family in ("task","autonomy","conversation"):
        child = subprocess.run([sys.executable,"-c",program,str(root),os.environ["NEYVIA_C7_PORT"],family,parent["conversationId"]],capture_output=True,text=True,encoding="utf8",timeout=40,**hidden_windows_subprocess_kwargs())
        require(child.returncode == 23 and snapshot() == before, "Interrupted actual MCP "+family+" admission changed durable state: "+child.stderr[-500:])
    task = server._call_tool({"name":"neyvia.research.start","arguments":{"missionId":"owned","query":"fresh recovered work","idempotencyKey":"owned-fresh-task"},"task":{"ttl":60000}})
    lease = server._call_tool({"name":"neyvia.autonomy.grant","arguments":{"allowedActions":["file_write"],"allowedRoots":[str(root)],"durationSeconds":300}})["structuredContent"]
    branch = server._call_tool({"name":"neyvia.question.branch","arguments":{"parentConversationId":parent["conversationId"],"question":"fresh recovered read-only question"}})["structuredContent"]
    require(task.get("task",{}).get("taskId") and len(server.store.list_tasks()) == 1 and server.store.autonomy_allows(lease["leaseId"],action="file_write",context={"path":str(root/"owned.txt")})["allowed"] and branch["capabilityPolicy"]["readOnly"] and branch["parentConversationId"] == parent["conversationId"], "Recovered MCP task/grant/branch lost actual durable identity/scope")
    server.mcp_broker.close()
    if getattr(server.capability_os,"_model_tool_broker",None) is not None:server.capability_os._model_tool_broker.close()
    return {"actualInterruptedChildren":3,"eachExit":23,"uncommittedDurableChanges":0,"freshSavedTask":task["task"]["taskId"],"freshReadOnlyBranch":branch["conversationId"],"modelCalls":0,"renderedProof":False}


def _core_rpc_current(root,category):
    from .neyvia_native_rpc import NativeRpcServer,RpcError
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    workspace=root/"workspace";workspace.mkdir()
    private=Ed25519PrivateKey.generate();public=private.public_key()
    public_path=root/"owned-public.pem";public_path.write_bytes(public.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    key_id="sha256:"+sha(public.public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw))
    server=NativeRpcServer(workspace,device_operator_public_key_path=public_path,device_operator_key_id=key_id)
    authority=server.capabilities({})["authority"]
    require(authority["deviceCommandOperatorVerifierReady"] and authority["deviceCommandOperatorKeyId"]==key_id and authority["default"]=="read-only" and not authority["deviceCommandHumanIdentityCryptographicallyVerified"] and not authority["deviceCommandAutomaticRetry"],"RPC verifier readiness or authority projection differs from actual pinned public verifier")
    for method in ("native.device.approvals.decide","native.device.commands.cancel"):
        result=refused(lambda:server.dispatch({"jsonrpc":"2.0","id":"owned","method":method,"params":{"humanConfirmed":True}}),RpcError)
        require("method not found" in result["message"],"Agent RPC exposed external operator authority")
    if category=="permissions":
        with exclusive(public_path):
            refused(lambda:NativeRpcServer(workspace,device_operator_public_key_path=public_path,device_operator_key_id=key_id),ValueError)
        require(not NativeRpcServer(workspace).capabilities({})["authority"]["deviceCommandOperatorVerifierReady"],"Missing public verifier acquired operator authority")
        require(NativeRpcServer(workspace,device_operator_public_key_path=public_path,device_operator_key_id=key_id).capabilities({})["authority"]["deviceCommandOperatorVerifierReady"],"Released public verifier failed fresh initialization")
    else:
        new=Ed25519PrivateKey.generate().public_key();public_path.write_bytes(new.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
        refused(lambda:NativeRpcServer(workspace,device_operator_public_key_path=public_path,device_operator_key_id=key_id),ValueError)
        new_id="sha256:"+sha(new.public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw))
        fresh=NativeRpcServer(workspace,device_operator_public_key_path=public_path,device_operator_key_id=new_id)
        require(fresh.capabilities({})["authority"]["deviceCommandOperatorKeyId"]==new_id and server.capabilities({})["authority"]["deviceCommandOperatorKeyId"]==key_id,"Fresh RPC reused stale verifier pin rather than actual loaded public authority")
        old=server.dispatch({"jsonrpc":"2.0","id":"old-request","method":"native.plan.compile","params":{"task":"Diagnose previous failure","behaviorCapsule":"diagnosis-repair","resourceMode":"eco","useLearning":False}})
        current=fresh.dispatch({"jsonrpc":"2.0","id":"current-request-雪","method":"native.plan.compile","params":{"task":"Diagnose current failure 雪","behaviorCapsule":"diagnosis-repair","resourceMode":"balanced","useLearning":False}})
        require(old["id"]=="old-request" and current["id"]=="current-request-雪" and old["result"]["resourceProfile"]["mode"]=="eco" and current["result"]["resourceProfile"]["mode"]=="balanced" and current["result"]["capsule"]["id"]=="diagnosis-repair" and current["result"]["compiledSkillPlan"],"Fresh RPC request inherited old identity/resource/compiled plan")
        require(fresh.dispatch({"jsonrpc":"2.0","method":"native.alive"}) is None and fresh.dispatch({"jsonrpc":"2.0","id":"latest-request","method":"native.alive"})["id"]=="latest-request","RPC notification/current identity reused a stale reply")
    return {"actualPinnedVerifier":True,"privateKeyPersisted":False,"operatorRpcAbsent":True,"freshAuthorityAndRequestBinding":category=="stale","physicalDeviceAction":False}


def _core_rpc_device(root,category):
    import base64
    from .neyvia_native_rpc import NativeRpcServer,RpcError
    from .native_device_operator_signing_wire import prepare_signing_request,inspect_signing_request,submit_operator_signature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from .edge_fixture_native import TEXT
    workspace=root/"workspace";workspace.mkdir()
    private=Ed25519PrivateKey.generate();public=private.public_key()
    public_path=root/"owned-public.pem";public_path.write_bytes(public.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    key_id="sha256:"+sha(public.public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw))
    server=NativeRpcServer(workspace,device_operator_public_key_path=public_path,device_operator_key_id=key_id)
    def call(method,params):
        response=server.dispatch({"jsonrpc":"2.0","id":"owned:"+method,"method":method,"params":params})
        require(response["id"]=="owned:"+method,"Actual device RPC response changed request identity")
        return response["result"]
    pair=call("native.pairing.create",{"target":"phone","scopes":["device.commands","mission.read","proof.read"]})
    device=call("native.pairing.redeem",{"pairingId":pair["pairingId"],"pairingToken":pair["pairingToken"],"displayName":"Owned actual control-plane fixture"})
    credential={"deviceId":device["deviceId"],"deviceSecret":device["deviceSecret"]}
    call("native.device.capabilities.publish",{**credential,"capabilities":["app.open"]})
    context={"actorId":"agent:rpc","sessionId":"session:rpc","runId":"run:rpc"}
    arguments={"route":"agent","ownedLiteral":TEXT.get(category,"owned") if category!="huge" else "bounded "*512}
    if category=="huge":
        refused(lambda:call("native.device.approvals.request",{"deviceId":device["deviceId"],"action":"app.open","arguments":{"route":"agent","ownedLiteral":TEXT[category]},**context}),ValueError)
    approval=call("native.device.approvals.request",{"deviceId":device["deviceId"],"action":"app.open","arguments":arguments,**context})
    refused(lambda:call("native.device.approvals.decide",{"approvalId":approval["approvalId"],"decision":"approved","humanConfirmed":True}),RpcError)
    request=prepare_signing_request(server.device_commands,approval["approvalId"],decided_by="human:local")
    inspected=inspect_signing_request(request)
    refused(lambda:submit_operator_signature(server.device_commands,request,signature_base64=""),ValueError)
    signed=submit_operator_signature(server.device_commands,request,signature_base64=base64.b64encode(private.sign(inspected["signingBytes"])).decode("ascii"))
    require(signed["status"]=="approved" and signed["operatorDecisionSignatureVerified"] and not signed["humanIdentityCryptographicallyVerified"],"Actual external scratch signature did not bind approval or invented physical operator proof")
    params={"deviceId":device["deviceId"],"action":"app.open","arguments":arguments,"idempotencyKey":"owned-exact-rpc-key-0001","approvalId":approval["approvalId"],**context}
    for altered in ({**params,"arguments":{**arguments,"route":"settings"}},{**params,"actorId":"agent:foreign"},{**params,"sessionId":"session:foreign"},{**params,"runId":"run:foreign"}):
        refused(lambda value=altered:call("native.device.commands.enqueue",value),PermissionError)
    if category=="permissions":
        with exclusive(server.device_commands.path):
            refused(lambda:call("native.device.commands.enqueue",params),(OSError,sqlite3.Error))
        require(server.device_commands.list()==[] and server.device_commands.get_approval(approval["approvalId"])["status"]=="approved","OS-denied RPC enqueue consumed authority or persisted work")
    if category=="interrupted":
        program="""import os,sys,json
from pathlib import Path
from contextlib import contextmanager
from grant_agent.edge_fixture_c7d_local import _isolate
from grant_agent.neyvia_native_rpc import NativeRpcServer
payload=json.loads(sys.stdin.read());root=Path(sys.argv[1]);_isolate(root,int(sys.argv[2]));server=NativeRpcServer(root,device_operator_public_key_path=payload['public'],device_operator_key_id=payload['keyId']);original=server.device_commands.connection
@contextmanager
def interrupted(*,immediate=False):
 with original(immediate=immediate) as db:
  db.set_trace_callback(lambda sql:os._exit(23) if sql.strip().upper()=='COMMIT' else None)
  yield db
server.device_commands.connection=interrupted
server.dispatch({'jsonrpc':'2.0','id':'actual-interrupted','method':'native.device.commands.enqueue','params':payload['params']})
"""
        child=subprocess.run([sys.executable,"-c",program,str(workspace),os.environ["NEYVIA_C7_PORT"]],input=json.dumps({"public":str(public_path),"keyId":key_id,"params":params}),capture_output=True,text=True,encoding="utf8",timeout=40,**hidden_windows_subprocess_kwargs())
        require(child.returncode==23 and server.device_commands.list()==[] and server.device_commands.get_approval(approval["approvalId"])["status"]=="approved","Interrupted exact RPC transaction half-consumed approval or persisted command: "+child.stderr[-500:])
    queued=_parallel(lambda _:call("native.device.commands.enqueue",params),range(8)) if category=="concurrency" else [call("native.device.commands.enqueue",params)]
    require(len({r["commandId"] for r in queued})==1 and server.device_commands.get_approval(approval["approvalId"])["status"]=="consumed","Actual concurrent RPC enqueue minted multiple commands or failed to consume exact authority once")
    claims=_parallel(lambda _:call("native.device.commands.claim",credential)["command"],range(8)) if category=="concurrency" else [call("native.device.commands.claim",credential)["command"]]
    claimed=[r for r in claims if r is not None]
    require(len(claimed)==1 and claimed[0]["arguments"]==arguments and all(claimed[0][k]==v for k,v in context.items()),"Actual device RPC claim lost single flight or exact arguments/context")
    claim=claimed[0]
    refused(lambda:call("native.device.commands.complete",{**credential,"deviceSecret":"foreign","commandId":claim["commandId"],"claimId":claim["claimId"],"status":"succeeded","result":{"handled":True}}),PermissionError)
    result={"handled":True,"observedControlFixture":category,"ownedLiteral":arguments["ownedLiteral"]}
    settled=call("native.device.commands.complete",{**credential,"commandId":claim["commandId"],"claimId":claim["claimId"],"status":"succeeded","result":result})
    require(settled["status"]=="succeeded" and settled["result"]==result and server.device_commands.get(claim["commandId"])["result"]==result,"Authenticated RPC completion changed terminal actual reported result")
    with server.device_commands.connection() as db:
        durable=dict(db.execute("SELECT * FROM device_commands WHERE command_id=?",(claim["commandId"],)).fetchone())
    require(durable["status"]=="succeeded" and json.loads(durable["result_json"])==result and durable["actor_id"]==context["actorId"] and durable["session_id"]==context["sessionId"] and durable["run_id"]==context["runId"],"RPC terminal receipt differs from independent SQLite binding/result")
    if category=="stale":
        refused(lambda:call("native.device.commands.enqueue",{**params,"idempotencyKey":"owned-replayed-rpc-key-0002"}),PermissionError)
        require(len(server.device_commands.list())==1,"Stale consumed signed approval minted new command")
    return {"actualSignedRpcPath":["pair","request","sign","enqueue","claim","complete"],"terminalStatus":durable["status"],"concurrentEnqueues":len(queued),"uniqueCommands":1,"privateKeyPersisted":False,"physicalDeviceActionObserved":False,"renderedProof":False,"receiptScope":"authenticated owned local RPC control fixture"}


FAMILIES = {
    "inspiration": (_inspiration,{"native.tools.inspiration"},{"empty","huge","unicode","concurrency","offline","stale"}),
    "preview": (_preview,{"native.tools.preview"},{"concurrency","interrupted","permissions","stale"}),
    "core-rpc-current": (_core_rpc_current,{"neyvia-core.rpc-authority","neyvia-core.rpc-plan","neyvia-core.rpc-protocol"},{"permissions","stale"}),
    "core-rpc-device": (_core_rpc_device,{"neyvia-core.rpc-device-binding"},{"empty","huge","unicode","concurrency","interrupted","permissions","stale"}),
    "pairing-interrupt": (_pairing_interrupt,{"native.pairing.digest","native.pairing.single-use","native.pairing.authority"},{"interrupted"}),
    "tool-receipt": (_tool_receipt,{"native.tools.receipt"},{"interrupted"}),
    "core-mcp-interrupt": (_core_mcp_interrupt,{"neyvia-core.mcp-task-durable","neyvia-core.mcp-autonomy","neyvia-core.mcp-conversation"},{"interrupted"}),
    "spawn": (_spawn,{"native.spawn.lineage","native.spawn.evaluate"},{"empty","huge","unicode","concurrency","interrupted","permissions","stale"}),
    "compact": (_compact,{"native.mcp.discovery","native.mcp.read-only"},{"empty","huge","unicode","concurrency","permissions","stale"}),
    "checkpoints": (_checkpoint, {"native.checkpoints.capture", "native.checkpoints.scope", "native.checkpoints.authority", "native.checkpoints.preflight", "native.checkpoints.restore", "native.checkpoints.recovery", "native.checkpoints.rollback"}, {"empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "stale"}),
    "hooks": (_hooks, {"native.hooks.argv", "native.hooks.authority", "native.hooks.receipt"}, {"concurrency", "interrupted", "permissions", "stale"}),
    "learning": (_learning, {"native.learning.receipt-gate", "native.learning.sample-floor"}, {"interrupted", "permissions"}),
    "goals": (_goals, {"native.goals.complete", "native.goals.due"}, {"interrupted"}),
    "events": (_events, {"native.events.integrity"}, {"permissions"}),
    "catalog": (_catalog, {"native.tools.catalog"}, {"concurrency", "stale"}),
    "skill": (_skill, {"native.tools.skill-revision"}, {"empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "stale"}),
}


def run(root, contracts, categories):
    root = Path(root).resolve()
    rows = []
    for family, (builder, intended, supported) in FAMILIES.items():
        if not intended.intersection(contracts):
            continue
        for category in categories:
            if category not in supported:
                continue
            scratch = Path(root) / family / category
            scratch.mkdir(parents=True, exist_ok=False)
            ids = sorted(intended.intersection(contracts))
            if family == "learning" and category == "permissions":
                ids = [i for i in ids if i.endswith("receipt-gate")]
            if family == "checkpoints" and category in {"empty", "huge", "unicode", "stale"}:
                ids = [i for i in ids if i.endswith(("recovery", "rollback"))]
            if family == "core-rpc-current" and category == "permissions":
                ids=[i for i in ids if i.endswith("rpc-authority")]
            if not ids:
                continue
            row = {"id": f"native-completion:{family}:{category}", "category": category, "contracts": ids, "scratchRoot": str(scratch), "boundary": "actual owned Native process/SQLite operations and independent durable observations; no rendered/model proof"}
            try:
                row.update(status="passed", detail=builder(scratch, category))
            except Exception as error:
                row.update(status="failed", detail={"type": type(error).__name__, "error": str(error)})
            rows.append(row)
    return rows


def blocker(contract, category):
    if contract["id"] == "native.tools.inspiration" and category in {"interrupted","permissions"}:
        return {"kind":"not_applicable","reason":"The invariant-specific inspiration owners normalize caller query/facets and assemble an already supplied image-result payload without granting mutations, reading protected state or publishing an asynchronous worker result. Exact caller-provided records/ages are independently preserved and explicitly are not upstream/rendered observations. Unavailable image-search transport is separately invoked and refused; generic tool receipt publication has its own actual interruption/OS-denial contracts."}
    if contract["id"] in {"neyvia-core.rpc-authority","neyvia-core.rpc-plan","neyvia-core.rpc-protocol"} and category == "interrupted":
        return {"kind":"not_applicable","reason":"Audited RPC capabilities/JSON envelope/current explicitly unlearned plan compilation are synchronous metadata or pure request projections; they do not accept a task or publish durable completion. Their actual operator verifier, identity/resource and current pin checks are exercised separately. The signed RPC enqueue transaction is killed before SQLite COMMIT and proves authority/command conservation at the real mutating boundary."}
    if contract["id"] in {"neyvia-core.rpc-plan","neyvia-core.rpc-protocol"} and category == "permissions":
        return {"kind":"not_applicable","reason":"Audited RPC reply envelopes and explicit useLearning=False plan compilation apply request identity, behavior/resource resolution and compiled declarations without executing a tool or acquiring mutation/device authority. They contain no per-request permission grant/writer. OS-denied public verifier loading and command SQLite admission exercise the exact RPC authority and signed-device invariants separately."}
    if contract["id"] == "neyvia-core.rpc-device-binding" and category == "offline":
        return {"kind":"not_applicable","reason":"The exact audited claim is explicitly the scratch host RPC pairing/sign/request/enqueue/claim/complete control path with an authenticated durable local result, and expressly excludes physical-device actions. The in-process JSON-RPC path and SQLite operations use no network transport. Physical device connectivity/remote execution is a separately authorized boundary and is never inferred from this signed local control receipt."}
    if contract["id"] == "native.tools.workspace" and category == "interrupted":
        return {"kind":"not_applicable","reason":"Audited NativeToolRegistry._workspace_read/_workspace_search are bounded synchronous file observations. They do not mutate selected workspace bytes, accept asynchronous work or publish completion; their caller's actual durable receipt publisher is separately cut before replacement and prior receipts/source bytes are conserved. Native OS denial, containment and fresh digest checks are handled by their file-read fixtures."}
    if contract["id"] in {"neyvia-core.mcp-protocol","neyvia-core.mcp-sync-budget"} and category == "interrupted":
        return {"kind":"not_applicable","reason":"Audited MCP initialization/catalog negotiation and neyvia.time.budget return local synchronous metadata/decisions without durable task wrapping or an asynchronous worker. There is no accepted task/result publisher to interrupt. Real CrashProof/Conversation transactions for durable task, scoped authority and question branches are interrupted before COMMIT in separate exact MCP completion rows."}
    if contract["id"] in {"native.spawn.lineage","native.spawn.evaluate"} and category == "offline":
        return {"kind":"not_applicable","reason":"Audited NativeSpawnRegistry and evaluate_spawn_receipt persist/read local SQLite lineage and local receipt/output bytes. They do not invoke a provider or transport. Real owned Python children supply observed outputs, actual exit23 produces a rejected failed terminal record, OS denial blocks admission/publication, and current parent/plan mismatches refuse stale receipts. Receipt/evaluator integrity never counts as rendered or model execution proof."}
    if contract["id"] in {"native.mcp.discovery","native.mcp.read-only"} and category in {"interrupted","offline"}:
        return {"kind":"not_applicable","reason":"Audited CompactNeyviaMCPServer catalog/search/describe and direct/deferred/nested read-only rejection are synchronous local metadata and permission decisions. They create no asynchronous tool worker and contact no provider/network. Actual calls exercise changed query text, concurrent queries, effective read-only grants and a fresh denied run receiving an older deferred descriptor. Permitted tools with effects/transports have separate execution contracts."}
    if contract["id"] in {"native.checkpoints.recovery", "native.checkpoints.rollback"} and category == "offline":
        return {"kind":"not_applicable","reason":"Audited checkpoint restore recovery and rollback consume local content-addressed blobs, confined workspace entries and durable before-image journals under a crossprocess filesystem lease. They have no transport/provider/device dependency. Actual child exits after first write, OS-denied second writes and journal reads, concurrent manifests/restores and newer-edit conflicts exercise conservation without substituting a network model."}
    if contract["id"] == "native.tools.skill-revision" and category == "offline":
        return {"kind": "not_applicable", "reason": "Audited skill_iteration resolves an explicit CODEX_HOME skills root and reads, CAS-checks, revises, backs up and records local SKILL.md bytes. No transport/provider/download operation exists. Generated owned skill roots exercise native OS denial, atomic interruption, seven stale refusals in eight real writer processes and fresh expected digests. Actual operator skills and rendered/model proof are outside these fixtures."}
    if contract["id"] == "native.tools.catalog" and category in {"permissions", "interrupted"}:
        return {"kind": "not_applicable", "reason": "Audited NativeToolRegistry.list_tools/search/describe project typed Native declarations, schemas, mutability/approval properties and detected availability without invoking a tool handler, acquiring mutation authority or spawning a worker. Concurrent exact projections and current missing/created owned skill roots exercise availability. Catalog authority metadata is not an authority grant or execution/rendered proof; tool dispatch and receipts have separate fixtures."}
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--family", choices=sorted(FAMILIES))
    args = parser.parse_args()
    _isolate(args.root.resolve(), args.port)
    from .proof_contracts import source_digest, REPO
    names = ["src/grant_agent/" + n + ".py" for n in ("edge_fixture_c7d_native_completion", "edge_fixture_c7d_local", "edge_fixture_local", "edge_fixture_missions", "proof_credential_guard", "folder_sync", "native_hooks", "native_learning", "native_goals", "native_event_stream", "native_tools", "skill_iteration", "native_checkpoints", "edge_fixture_native", "native_spawn_contracts", "native_spawn_evaluator", "neyvia_mcp_stdio", "neyvia_mcp", "manual_first", "native_pairing", "crashproof", "neyvia_conversations", "neyvia_native_rpc", "native_device_commands", "native_device_operator_authority", "native_device_operator_signing_wire", "proofs_d_native", "proofs_d_neyvia", "durability", "harness_jobs")]
    before = {n: source_digest(REPO / n) for n in names}
    contracts = {i: {} for family, (_, ids, _) in FAMILIES.items() if not args.family or family == args.family for i in ids}
    rows = run(args.root / "cases", contracts, CATEGORIES)
    stable = before == {n: source_digest(REPO / n) for n in names}
    report = {"sourceStable": stable, "sourceBindings": before, "explicitPort": args.port, "rows": rows, "ok": stable and all(r["status"] == "passed" for r in rows), "passedPairs": len({(i, r["category"]) for r in rows if r["status"] == "passed" for i in r["contracts"]})}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"rows", "sourceBindings"}}))
    print(json.dumps([r for r in rows if r["status"] != "passed"]))
