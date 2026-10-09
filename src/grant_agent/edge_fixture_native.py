"""Generative Native store fixtures with independently read durable effects.

Only exact audited invariants are bound. Child interruption and OS sharing
denial operate on disposable workspace state, never the operator's stores.
"""
from __future__ import annotations
from .subprocess_utils import hidden_windows_subprocess_kwargs

import ctypes
import hashlib
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

TEXT = {"empty": "", "huge": "bounded " * 10000, "unicode": "雪🙂e\u0301 العربية\u202e"}
MAP = {
    "events": {"native.events.append", "native.events.integrity"},
    "goals": {"native.goals.durable", "native.goals.complete", "native.goals.due"},
    "pairing": {"native.pairing.digest", "native.pairing.single-use", "native.pairing.authority", "native.pairing.scope-input"},
    "hooks": {"native.hooks.argv", "native.hooks.authority", "native.hooks.receipt"},
    "learning": {"native.learning.receipt-gate", "native.learning.sample-floor"},
    "checkpoints": {"native.checkpoints.capture", "native.checkpoints.scope", "native.checkpoints.authority", "native.checkpoints.preflight", "native.checkpoints.restore", "native.checkpoints.recovery", "native.checkpoints.rollback"},
    "resources": {"native.resources.mode", "native.resources.admission", "native.spawn.routes", "native.learning.usage"},
    "runtime-pure": {"d.runtime.handback.identity", "d.runtime.handback.transcript", "d.runtime.openai.tools", "d.runtime.openai.request", "d.runtime.version.order"},
    "runtime-files": {"d.runtime.wrapper.spec", "d.runtime.wrapper.state", "d.runtime.wrapper.event", "d.runtime.wrapper.receipt", "d.runtime.wrapper.replay", "d.runtime.lineage.source"},
}


def _check(ok, message):
    if not ok:
        raise AssertionError(message)


def _reject(action, types=(ValueError, KeyError, OSError)):
    try:
        action()
    except types:
        return
    raise AssertionError("invalid feature operation was admitted")


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@contextmanager
def _offline():
    original = socket.socket.connect
    calls = []
    def denied(instance, address):
        calls.append(str(address))
        raise OSError("fixture network unavailable")
    socket.socket.connect = denied
    try:
        yield calls
    finally:
        socket.socket.connect = original


@contextmanager
def _sharing_denied(path, *, allow_read=False):
    if os.name != "nt":
        raise RuntimeError("requires Windows file sharing authority")
    kernel = ctypes.windll.kernel32
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                 ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path.resolve()), 0x80000000, 1 if allow_read else 0, None, 3, 0, None)
    _check(handle not in (None, ctypes.c_void_p(-1).value), "exclusive OS handle unavailable")
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def _events(root, category, text):
    from .native_event_stream import NativeEventStream
    output = io.StringIO()
    stream = NativeEventStream(root, "owned", output=output)
    if category == "permissions":
        stream.emit("seed", {"text": "before"})
        before = stream.path.read_bytes()
        with _sharing_denied(stream.path):
            _reject(lambda: stream.emit("denied", {"text": text}), (OSError,))
        _check(before == stream.path.read_bytes(), "sharing-denied append changed durable bytes")
        return {"sharingDenied": True}, {"native.events.append"}
    if category == "concurrency":
        # One runtime stream instance is shared by concurrent tool workers.
        with ThreadPoolExecutor(max_workers=8) as pool:
            emitted = list(pool.map(lambda index: stream.emit("worker", {"index": index}), range(32)))
    else:
        emitted = [stream.emit("input", {"text": text}), stream.emit("next", {"text": text})]
    rows = [json.loads(line) for line in stream.path.read_text(encoding="utf-8").splitlines()]
    previous = "0" * 64
    for index, event in enumerate(rows, 1):
        digest = event["eventHash"]
        unsigned = {k: v for k, v in event.items() if k != "eventHash"}
        _check(event["sequence"] == index and event["previousHash"] == previous and digest == _hash(unsigned), "durable chain identity/hash differs")
        previous = digest
    _check(sorted(e["sequence"] for e in emitted) == list(range(1, len(rows)+1)), "emitted slots lost")
    _check(stream.verify()["valid"], "actual stream observer refuses intact chain")
    if category != "concurrency":
        _check(all(row["payload"]["text"] == text for row in rows), "payload changed")
        _check(output.getvalue().encode() == stream.path.read_bytes(), "streamed bytes differ from disk")
    # Each corruption is applied to real durable bytes and independently refused.
    original = stream.path.read_bytes()
    for field, value in (("payload", {"changed": True}), ("previousHash", "f"*64), ("sequence", 900)):
        corrupt = [dict(row) for row in rows]
        corrupt[-1][field] = value
        stream.path.write_text("\n".join(json.dumps(r) for r in corrupt)+"\n", encoding="utf-8")
        _check(not stream.verify()["valid"], "corrupted durable chain accepted")
    stream.path.write_bytes(b"{malformed\n")
    _check(not stream.verify()["valid"], "malformed durable chain accepted")
    stream.path.write_bytes(original)
    return {"events": len(rows), "bytes": len(original), "corruptionsRefused": 4}, MAP["events"]


def _goals(root, category, text):
    from .native_goals import NativeGoalStore
    store = NativeGoalStore(root)
    if category == "empty":
        _reject(lambda: store.create(""))
        _check(store.list() == [] and store.due() == [], "empty objective created goal or empty due query invented work")
        admitted=store.create("owned objective",goal_id="empty-receipt")
        _reject(lambda:store.complete(admitted["goalId"],""))
        _check(store.get(admitted["goalId"])==admitted,"empty completion receipt changed valid goal")
        return {"emptyObjectiveRefused": True,"emptyReceiptRefused":True,"emptyDue":[]}, MAP["goals"]
    objective = text or "owned goal"
    def cycle(index):
        goal = store.create(objective, goal_id=f"g{index}", success_checks=[objective], milestones=[objective], schedule_seconds=60)
        gid = goal["goalId"]
        observed = store.heartbeat(gid, run_id=f"r{index}", next_action=objective, evidence={"text": objective})
        _check(observed["objective"] == objective.strip() and observed["successChecks"] == [objective.strip()] and observed["nextAction"] == objective[:4000], "goal projection changed request")
        store.update_milestone(gid, observed["milestones"][0]["milestoneId"], status="completed", evidence=[{"text": objective}])
        before = store.get(gid)
        _reject(lambda: store.complete(gid, ""))
        _check(store.get(gid) == before, "receipt-less completion changed goal")
        receipt = root/f"receipt-{index}.json"
        receipt.write_text(json.dumps({"observed": objective}), encoding="utf-8")
        result = store.complete(gid, str(receipt))
        _check(result["status"] == "completed" and result["nextDueAt"] is None and result["completionReceipt"] == str(receipt), "completion durable state differs")
        with sqlite3.connect(store.path) as connection:
            events = connection.execute("SELECT event_type,payload_json FROM native_goal_events WHERE goal_id=? ORDER BY event_id", (gid,)).fetchall()
        _check([r[0] for r in events] == ["goal.created", "goal.heartbeat", "milestone.updated", "goal.completed"], "goal transitions omitted/reordered")
        _check(json.loads(events[1][1])["evidence"] == {"text": objective}, "heartbeat evidence changed")
        return gid
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(cycle, range(8)))
    else:
        ids = [cycle(0)]
    due = store.create("due", goal_id="due", schedule_seconds=60)
    paused = store.create("paused", goal_id="paused", schedule_seconds=60)
    with store.connection() as connection:
        connection.execute("UPDATE native_goals SET next_due_at='2000-01-01T00:00:00Z' WHERE goal_id IN ('due','paused')")
    store.heartbeat("paused", status="paused")
    _check([g["goalId"] for g in store.due()] == ["due"], "due observer included inactive/future/completed goal")
    _reject(lambda: store.heartbeat("missing", status="active"))
    _check(len(store.list()) == len(ids)+2, "stale goal mutation invented row")
    return {"completedGoals": len(ids), "due": ["due"], "staleRefused": True}, MAP["goals"]


def _pairing(root, category, text):
    from .native_pairing import NativePairingStore
    store = NativePairingStore(root)
    for target, scopes in ((text, ["mission.read"]), ("computer", [text or "unknown"]), ("not-a-device", ["mission.read"])):
        if target == "computer" and scopes == ["mission.read"]:
            continue
        _reject(lambda: store.create(target, scopes=scopes))
    _check(store.list_devices() == [], "invalid pairing created device")
    pair = store.create("computer", scopes=["mission.read", "proof.read", "mission.read"])
    with sqlite3.connect(store.path) as connection:
        row = connection.execute("SELECT token_salt,token_hash,scopes_json FROM pairing_requests WHERE pairing_id=?", (pair["pairingId"],)).fetchone()
    _check(row[1] == hashlib.sha256((row[0]+":"+pair["pairingToken"]).encode()).hexdigest() and json.loads(row[2]) == ["mission.read", "proof.read"], "pairing digest/scopes differ")
    def redeem(index):
        try:
            return store.redeem(pair["pairingId"], pair["pairingToken"], text or "owned")
        except ValueError:
            return None
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            devices = [d for d in pool.map(redeem, range(8)) if d]
        _check(len(devices) == 1, "one-time token admitted multiple devices")
        device = devices[0]
    else:
        device = redeem(0)
        _reject(lambda: store.redeem(pair["pairingId"], pair["pairingToken"], "again"))
    _check(store.authenticate(device["deviceId"], device["deviceSecret"], "mission.read"), "real scoped device denied")
    _check(not store.authenticate(device["deviceId"], device["deviceSecret"], "workspace.write") and not store.authenticate(device["deviceId"], text, "mission.read"), "foreign scope/secret admitted")
    store.revoke(device["deviceId"])
    _check(not store.authenticate(device["deviceId"], device["deviceSecret"], "mission.read"), "stale revoked device admitted")
    expire = store.create("computer")
    with store.connection() as connection:
        connection.execute("UPDATE pairing_requests SET expires_at='2000-01-01T00:00:00Z' WHERE pairing_id=?", (expire["pairingId"],))
    _reject(lambda: store.redeem(expire["pairingId"], expire["pairingToken"], "expired"))
    raw = store.path.read_bytes()
    _check(pair["pairingToken"].encode() not in raw and device["deviceSecret"].encode() not in raw, "ephemeral pairing secret persisted")
    return {"devices": len(store.list_devices()), "oneTime": True, "revokedAndExpiredRefused": True, "secretsAtRest": False}, MAP["pairing"]


def _hooks(root, category, text):
    from .native_hooks import NativeHook, NativeHookRunner
    for argv in ("echo unsafe", [], [sys.executable, ""], [17]):
        _reject(lambda: NativeHook.from_mapping({"id": "bad", "event": "run.before", "argv": argv}))
    marker = root/"effect.json"
    payload = root/"input.json"
    payload.write_text(json.dumps({"text": text}), encoding="utf-8")
    if category=="interrupted":
        argv=[sys.executable,"-c","import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text('started');time.sleep(60);pathlib.Path(sys.argv[2]).write_text('incorrectly finished')",str(root/"started"),str(marker)]
        path=root/".neyvia"/"hooks.json";path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({"hooks":[{"id":"timeout","event":"run.before","argv":argv,"timeoutSeconds":1,"allowMutations":True,"blocking":True}]}),encoding="utf-8")
        result=NativeHookRunner(root,mutations_allowed=True).run("run.before")
        receipt=result["receipts"][0]
        _check((root/"started").is_file() and not marker.exists() and receipt["status"]=="timed_out" and receipt["timedOut"] and not receipt["passed"],"actual timed-out hook invented completion or finished effect")
        durable=json.loads(Path(receipt["receiptPath"]).read_text(encoding="utf-8"))
        _check(durable=={k:v for k,v in receipt.items() if k!="receiptPath"},"timeout receipt differs from durable bytes")
        return {"childStarted":True,"completionEffectAbsent":True,"timedOut":True},{"native.hooks.receipt"}
    script = "import json,pathlib,sys; data=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')); pathlib.Path(sys.argv[2]).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8'); print('actual exit');sys.exit(int(sys.argv[3]))"
    config = {"hooks": [{"id": "effect", "event": "run.before", "argv": [sys.executable, "-c", script, str(payload), str(marker), "0"], "allowMutations": True, "blocking": True}]}
    path = root/".neyvia"/"hooks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    denied = NativeHookRunner(root).run("run.before")
    _check(denied["blocked"] and denied["receipts"][0]["status"] == "approval_required" and not marker.exists(), "unapproved hook executed")
    runner = NativeHookRunner(root, mutations_allowed=True)
    result = runner.run("run.before")
    _check(json.loads(marker.read_text(encoding="utf-8")) == {"text": text}, "real hook output changed input")
    receipt = result["receipts"][0]
    durable = json.loads(Path(receipt["receiptPath"]).read_text(encoding="utf-8"))
    _check(durable == {k:v for k,v in receipt.items() if k != "receiptPath"} and durable["receiptHash"] == _hash({k:v for k,v in durable.items() if k != "receiptHash"}), "hook receipt hash/exact durable result differs")
    _check(receipt["returnCode"] == 0 and receipt["passed"], "actual zero exit reported failure")
    config["hooks"][0]["argv"][-1] = "23"
    path.write_text(json.dumps(config), encoding="utf-8")
    failed = NativeHookRunner(root, mutations_allowed=True).run("run.before")["receipts"][0]
    _check(failed["returnCode"] == 23 and not failed["passed"] and failed["status"] == "failed", "real nonzero exit hidden")
    return {"zeroExit": 0, "failureExit": 23, "unapprovedEffectAbsent": True, "observedBytes": marker.stat().st_size}, MAP["hooks"]


def _learning(root, category, text):
    from .native_learning import NativeLearningStore
    store = NativeLearningStore(root)
    def record(index):
        receipt = {"runId": "r"+str(index), "status": "completed" if index%2==0 else "failed", "proofAudit": {"status": "verified"}, "model": text, "behaviorPlan": {"capsule": {"taskKinds": ["owned"]}}}
        store.record_run(receipt)
        with sqlite3.connect(store.path) as connection:
            row = connection.execute("SELECT verified,status,proof_status FROM native_runs WHERE run_id=?", (receipt["runId"],)).fetchone()
        _check(row == (int(index%2==0), receipt["status"], "verified"), "learning admitted failed or changed observation")
        return row
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(record, range(8)))
    else:
        for i in range(8): record(i)
    recommendation = store.recommend("owned", minimum_samples=20)
    _check(not recommendation["eligible"] and not recommendation["applied"] and recommendation["evidenceRuns"] == 8, "recommendation crossed sample floor or promoted itself")
    store.record_run({"runId": "r0", "status": "completed", "proofAudit": {"status": "not_audited"}})
    with sqlite3.connect(store.path) as connection:
        _check(connection.execute("SELECT verified FROM native_runs WHERE run_id='r0'").fetchone()[0] == 0, "stale audited bit retained")
    return {"runs": 8, "minimumSamples": 20, "applied": False, "staleVerifiedCleared": True}, MAP["learning"]


def _checkpoints(root, category, text):
    from .native_checkpoints import NativeCheckpointStore
    store = NativeCheckpointStore(root)
    if category == "permissions":
        first,locked=root/"a.txt",root/"b.txt"
        first.write_bytes(b"captured-a");locked.write_bytes(b"captured-b")
        capture=store.create([first.name,locked.name])
        first.write_bytes(b"current-a");locked.write_bytes(b"current-b")
        with _sharing_denied(locked,allow_read=True):
            result=store.restore(capture["checkpointId"],approved=True)
        _check(result["status"]=="failed_rolled_back" and result["workspaceSafe"] and first.read_bytes()==b"current-a" and locked.read_bytes()==b"current-b", "real write-sharing failure did not roll back first changed file")
        _check(result["rollbackRestoredPaths"]==[first.name,locked.name],"rollback did not report both exact restored before-images")
        return {"sharingDeniedWrite":True,"status":result["status"],"workspaceSafe":True,"rollbackRestoredPaths":result["rollbackRestoredPaths"]}, {"native.checkpoints.rollback"}
    source = root/"雪🙂.txt"
    before = text.encode()
    source.write_bytes(before)
    missing = root/"missing.txt"
    capture = store.create([source.name, missing.name], run_id="owned")
    entries = {e["path"]: e for e in capture["entries"]}
    entry = entries[source.name]
    _check(entry["size"] == len(before) and entry["sha256"] == hashlib.sha256(before).hexdigest() and not entries[missing.name]["existed"], "capture manifest differs from files")
    _check(json.loads(Path(capture["manifestPath"]).read_text(encoding="utf-8")) == {k:v for k,v in capture.items() if k != "manifestPath"}, "manifest bytes differ")
    _reject(lambda: store.create(["../escape.txt"]))
    source.write_bytes(b"changed")
    missing.write_bytes(b"created later")
    denied = store.restore(capture["checkpointId"])
    _check(source.read_bytes() == b"changed" and missing.read_bytes() == b"created later" and denied["status"] == "approval_required", "unapproved restoration changed file")
    result = store.restore(capture["checkpointId"], approved=True)
    _check(source.read_bytes() == before and not missing.exists() and result["status"] == "completed" and result["restored"], "approved restoration did not match captured file/deletion")
    receipt_path = result.get("receiptPath", "")
    _check(receipt_path and json.loads(Path(receipt_path).read_text(encoding="utf-8")) == {k:v for k,v in result.items() if k != "receiptPath"}, "restore durable receipt differs")
    # A real changed manifest is refused before touching the currently changed file.
    source.write_bytes(b"current")
    manifest_path = Path(capture["manifestPath"])
    changed = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed["entries"][0]["sha256"] = "f"*64
    manifest_path.write_text(json.dumps(changed), encoding="utf-8")
    refused = store.restore(capture["checkpointId"], approved=True)
    _check(refused["status"] == "failed_preflight" and not refused["restored"], "stale manifest admitted")
    _check(source.read_bytes() == b"current", "stale manifest rejection changed file")
    return {"bytesCapturedAndRestored": len(before), "scopeEscapeRefused": True, "staleManifestRefusedBeforeMutation": True}, MAP["checkpoints"]-{"native.checkpoints.recovery","native.checkpoints.rollback"}


def _resources(root, category, text):
    from .native_resource_profiles import normalize_resource_mode, _profile_for_memory
    from .native_spawn_contracts import build_specialist_routes
    from .native_learning import usage_payload
    if not text:
        _check(normalize_resource_mode(text) == "auto", "empty mode not auto")
    else:
        _reject(lambda: normalize_resource_mode(text))
    for value, expected in (("low consumption", "eco"), ("max", "maximal"), ("normal", "balanced"), ("rich", "memory-rich")):
        _check(normalize_resource_mode(value) == expected, "documented alias changed")
    for memory, expected in ((0,"balanced"),(6143,"eco"),(6144,"balanced"),(16383,"balanced"),(16384,"maximal"),(49151,"maximal"),(49152,"memory-rich")):
        p = _profile_for_memory("auto", memory)
        _check(p["mode"] == expected and p["detectedMemoryMb"] == memory and p["verificationReserveTurns"] < p["maximumTurns"], "resource boundary lost")
    roles = ["planner", "executor", "verifier"]
    model = text.strip() or "owned-model"
    routes = build_specialist_routes(model, raw_overrides={r: {"model": model, "allowMutations": True} for r in roles}, behavior_plan={"capsule": {"specialistRoles": roles}}, resource_profile={"specialistLimit":3})
    _check(list(routes) == roles and all(route.model == model and route.allow_mutations == (r == "executor") for r,route in routes.items()), "specialist route order/model/authority changed")
    for usage, expected in (({},(0,0,0)), ({"input_tokens":9},(9,0,9)), ({"input_tokens":9,"input_tokens_details":{"cached_tokens":4}},(9,4,5))):
        result = usage_payload(usage)
        _check((result["inputTokens"],result["cachedInputTokens"],result["uncachedInputTokens"]) == expected, "usage observation invented cache/input")
    return {"memoryBoundaries": 7, "specialistRoles": roles, "cacheUsageCases":3}, MAP["resources"]


def _interrupted(root, family):
    signal = root/"child.ready"
    if family == "events":
        code = "from grant_agent.native_event_stream import NativeEventStream;from pathlib import Path;import sys,time;s=NativeEventStream(Path(sys.argv[1]),'owned');s.emit('before-kill',{'text':'durable'});Path(sys.argv[2]).write_text('ready');time.sleep(60)"
    elif family == "goals":
        # Pause only after the real feature writes its transition inside SQLite.
        code = "from grant_agent.native_goals import NativeGoalStore;from pathlib import Path;import sys,time\nclass Paused(NativeGoalStore):\n def _append_event(self,c,g,t,p):\n  super()._append_event(c,g,t,p);Path(sys.argv[2]).write_text('ready');time.sleep(60)\nPaused(Path(sys.argv[1])).create('uncommitted',goal_id='killed')"
    elif family == "checkpoints":
        from .native_checkpoints import NativeCheckpointStore
        first,second=root/"a.txt",root/"b.txt"
        first.write_bytes(b"capture-a");second.write_bytes(b"capture-b")
        capture=NativeCheckpointStore(root).create([first.name,second.name])
        first.write_bytes(b"before-a");second.write_bytes(b"before-b")
        code="from grant_agent.native_checkpoints import NativeCheckpointStore;from pathlib import Path;import sys,time\nclass Paused(NativeCheckpointStore):\n def _apply_entries(self,entries):\n  result=super()._apply_entries(entries[:1]);Path(sys.argv[2]).write_text('ready');time.sleep(60);return result\nPaused(Path(sys.argv[1])).restore("+repr(capture["checkpointId"])+",approved=True)"
    else:
        raise ValueError(family)
    child = subprocess.Popen([sys.executable,"-c",code,str(root),str(signal)], stdout=subprocess.PIPE,stderr=subprocess.PIPE, **hidden_windows_subprocess_kwargs())
    try:
        deadline=time.monotonic()+20
        while not signal.exists() and child.poll() is None and time.monotonic()<deadline: time.sleep(.03)
        _check(signal.exists(), "real child did not reach feature interruption boundary")
        child.kill(); child.communicate(timeout=10)
        _check(child.returncode != 0, "interrupted child returned success")
        if family == "events":
            from .native_event_stream import NativeEventStream
            stream = NativeEventStream(root,"owned")
            next_event=stream.emit("after-kill", {"text":"recovered"})
            _check(next_event["sequence"]==2 and stream.verify()["valid"], "killed event writer did not retain recoverable exact chain")
            bindings=MAP["events"]
        elif family == "goals":
            from .native_goals import NativeGoalStore
            store=NativeGoalStore(root)
            _check(store.list()==[], "killed feature transaction left half-goal")
            store.create("after-kill",goal_id="resumed")
            _check([g["goalId"] for g in store.list()]==["resumed"], "goal transaction lock did not recover")
            bindings={"native.goals.durable"}
        else:
            from .native_checkpoints import NativeCheckpointStore
            _check(first.read_bytes()==b"capture-a" and second.read_bytes()==b"before-b","child did not stop after actual partial restore")
            recovered=NativeCheckpointStore(root)
            _check(first.read_bytes()==b"before-a" and second.read_bytes()==b"before-b" and not recovered.recovery_error,"partial restore before-images were not recovered on reopen")
            transaction_files=list(recovered.transaction_root.glob("*.json"))
            journals=[json.loads(p.read_text(encoding="utf-8")) for p in transaction_files]
            _check(journals and all(j["status"]=="rolled_back" for j in journals),"recovered restore journal not terminal")
            bindings={"native.checkpoints.recovery"}
        boundaries={"events":"actual durable append","goals":"actual uncommitted goal/event transaction","checkpoints":"actual first-file restoration inside durable applying journal"}
        return {"childExit":child.returncode,"interruptionBoundary":boundaries[family]}, bindings
    finally:
        if child.poll() is None: child.kill();child.communicate(timeout=10)


def _runtime_pure(root, category, text):
    from .runtime_handback import build_handback, handback_messages
    from .openai_adapter import CodeExecutionConfig, tools_from_skills, build_responses_request
    from .skills import Skill
    from .runtime_updates import compare_version_tokens
    messages=[] if category=="empty" else [{"role":"operator","content":text},{"role":"assistant","content":text}]
    if category=="huge": messages += [{"role":"assistant","text":str(i)} for i in range(2000)]
    invocation={"invocationId":"owned-invocation","runtime":"codex","parentSessionId":"owned-parent","returns":{"messages":messages,"artifacts":[],"changes":[],"receipts":[]}}
    result=build_handback(invocation)
    _check(result["carriedCount"]==len(messages) and result["counts"]["messages"]==len(messages) and result["runtime"]=="codex", "handback changed observed counts/runtime")
    for source,row in zip(messages,result["carried"]["messages"]):
        expected=hashlib.sha256(json.dumps(["owned-invocation","messages",source],sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()[:16]
        _check(row["item"]==source and row["digest"]==expected and row["origin"]=={"runtime":"codex","invocationId":"owned-invocation","kind":"messages"},"handback changed content/origin/hash")
    transcript=handback_messages(result)
    _check(len(transcript)==len(messages),"transcript dropped meaningful message")
    if messages:
        _check(transcript[0]["author"]=="You" and transcript[1]["author"]=="codex" and transcript[0]["content"]==text,"transcript lost authors/content")
    repeated=build_handback(invocation,already_carried=set(result["digests"]))
    _check(repeated["carriedCount"]==0 and repeated["skippedCount"]==len(messages),"repeat handback duplicated output")
    resumed={**invocation,"returns":{"messages":messages+[{"role":"assistant","content":"new owned output"}]}}
    _check(build_handback(resumed,already_carried=set(result["digests"]))["carriedCount"]==1,"resumed output lost")
    skill=Skill("owned",text,{"type":"object","properties":{"text":{"type":"string"}}},[],[],[],[],False,True)
    for config in (CodeExecutionConfig(enabled=True,file_ids=[text]),CodeExecutionConfig(enabled=True,container_id="owned-container")):
        tools=tools_from_skills([skill],code_execution=config)
        _check(tools[0]=={"type":"function","name":"owned","description":text,"parameters":skill.schema,"strict":True},"skill tool projection changed")
        _check(tools[1]==config.tool_payload(),"container tool projection changed")
        plan=build_responses_request(text,"owned-model",tools,previous_response_id=text,conversation=text,instructions=text,tool_choice=text)
        wire=plan.as_dict()
        _check(wire=={"model":"owned-model","input":[{"role":"user","content":text}],"tools":tools,"previous_response_id":text,"conversation":text,"instructions":text,"tool_choice":text,"store":False},"request wire changed supplied values")
        omitted=build_responses_request(text,"owned-model",tools).as_dict()
        _check(not {"previous_response_id","conversation","instructions","tool_choice"}&omitted.keys(),"unset fields serialized")
    versions=[("", "",0),("v1.2.3","1.2.3",0),("2026.2.15","2026.10.1",-1),("v2.0","1.99",1),(text,text,0)]
    for left,right,expected in versions:
        _check(compare_version_tokens(left,right)==expected,"numeric/date/v version ordering changed")
    return {"observedMessages":len(messages),"repeatCarried":0,"resumedCarried":1,"requestContainerVariants":2,"versionComparisons":len(versions)},MAP["runtime-pure"]


def _runtime_files(root, category, text):
    from dataclasses import asdict
    from datetime import datetime,timezone
    from . import runtime_wrapper as rw
    from .replay import build_lineage_timeline
    stdout,stderr,events=root/"stdout.txt",root/"stderr.txt",root/"events.jsonl"
    raw=text.encode()
    stdout.write_bytes(raw);stderr.write_bytes(raw)
    spec=rw.build_runtime_wrapper_spec(runtime_id="codex",command=[sys.executable,"-c",text or "pass"],cwd=root,environment={"OWNED_KEY":"not-public"},timeout_seconds=17,stdout_tail_path=str(stdout),stderr_tail_path=str(stderr),event_stream_path=str(events))
    public=rw.runtime_wrapper_payload(spec)
    _check(public["command"]==[sys.executable,"-c",text or "pass"] and public["environment_keys"]==["OWNED_KEY"] and "not-public" not in json.dumps(public),"wrapper spec changed argv or leaked environment")
    _reject(lambda:rw.build_runtime_wrapper_spec(runtime_id="unknown",command=["x"],cwd=root))
    _reject(lambda:rw.build_runtime_wrapper_spec(runtime_id="codex",command=[],cwd=root))
    state=rw.build_runtime_wrapper_state(spec,env_status={"OWNED_KEY":"present_masked"},process_tree=[{"pid":os.getpid()}],heartbeat_at=datetime.now(timezone.utc).isoformat(),tail_bytes=97)
    _check(state.stdout_tail==raw[-97:].decode("utf-8",errors="replace") and state.stderr_tail==state.stdout_tail and state.ttl_seconds==17 and state.heartbeat_age_seconds>=0,"actual wrapper tail/TTL/heartbeat differs")
    event=rw.build_runtime_wrapper_phase_event(spec,phase="owned",status="completed",message=text,mission_id="mission",mission_run_id="run")
    _check(event["message"]==text and event["runtimeId"]=="codex" and event["eventStreamPath"]==str(events),"wrapper phase association changed")
    receipt=rw.build_runtime_wrapper_execution_receipt(spec,state,receipt_id="receipt",mission_id="mission",host="owned",workspace=str(root),status="completed",summary=text,mission_run_id="run",changed_files=[stdout.name])
    _check(receipt.commands_run[0]["command"]==" ".join(spec.command) and receipt.changed_files==[stdout.name] and receipt.outputs["envStatus"]=={"OWNED_KEY":"present_masked"},"wrapper receipt lost observed command/files/environment")
    receipt_path=root/"receipt.json"; receipt_path.write_text(json.dumps(asdict(receipt)),encoding="utf-8")
    rows=[{**event,"status":"running"},event]
    events.write_text(json.dumps(rows[0])+"\n{malformed}\n[]\n"+json.dumps(rows[1])+"\n",encoding="utf-8")
    replay=rw.replay_runtime_wrapper(event_stream_path=events,receipt_paths=[receipt_path,root/"missing.json"],limit=10)
    _check(replay["events"]==rows and replay["receiptCount"]==1 and replay["latestStatus"]=="completed","wrapper replay invented/lost real rows")
    limited=rw.replay_runtime_wrapper(event_stream_path=events,limit=1)
    _check(limited["events"]==[rows[-1]],"wrapper replay ignored bound")
    for name in ("first","second"):
        directory=root/name;directory.mkdir(exist_ok=True)
        (directory/"timeline.jsonl").write_text(json.dumps({"text":text})+"\n{invalid}\n[]\n",encoding="utf-8")
    lineage=build_lineage_timeline(root,["first","missing","second"])
    _check([r["session_id"] for r in lineage]==["first","second"] and all(r["text"]==text for r in lineage),"lineage observer changed content/order or invented rows")
    return {"actualTailBytes":min(97,len(raw)),"events":2,"boundedEvents":1,"lineageSources":["first","second"]},MAP["runtime-files"]


def run(root, contracts, categories):
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    rows=[]
    builders={"events":_events,"goals":_goals,"pairing":_pairing,"hooks":_hooks,"learning":_learning,"checkpoints":_checkpoints,"resources":_resources,"runtime-pure":_runtime_pure,"runtime-files":_runtime_files}
    for family,builder in builders.items():
        for category in categories:
            applicable=(category in TEXT or category=="offline" and family not in {"resources","runtime-pure"} or category=="stale" and family in {"events","goals","pairing","learning","checkpoints"} or category=="concurrency" and family in {"events","goals","pairing","learning"} or category=="permissions" and family in {"events","checkpoints"} or category=="interrupted" and family in {"events","goals","checkpoints","hooks"})
            if not applicable: continue
            path=root/family/category;path.mkdir(parents=True,exist_ok=True)
            row={"id":f"native-fixture:{family}:{category}","category":category,"contracts":sorted(MAP[family]&contracts.keys()),"status":"failed","boundary":"production Native feature calls, independently read files/SQLite/OS effects"}
            try:
                if category=="interrupted" and family!="hooks": detail,bindings=_interrupted(path,family)
                elif category=="offline":
                    with _offline() as attempts: detail,bindings=builder(path,category,"offline owned input")
                    _check(not attempts,"local feature attempted network")
                    detail["networkConnectAttempts"]=len(attempts)
                else: detail,bindings=builder(path,category,TEXT.get(category,"owned"))
                row.update(status="passed",detail=detail,contracts=sorted(bindings&contracts.keys()))
            except Exception as exc:
                row["detail"]={"error":str(exc),"type":type(exc).__name__}
            rows.append(row)
    return rows


def blocker(contract, category):
    identity=contract.get("id","")
    if identity in MAP["runtime-pure"] and category in {"concurrency","stale","permissions","interrupted","offline"}:
        return {"kind":"not_applicable","reason":f"Audited {identity} transforms supplied invocation/tool/request/version data only; no worker, durable revision, grant or network request occurs in this invariant's owner for {category}."}
    if identity in MAP["resources"] and category in {"concurrency","stale","permissions","interrupted","offline"}:
        # offline has a real data fixture; this resolver is used only if unbound.
        return {"kind":"not_applicable","reason":f"Audited {identity} owner is an in-memory transform of supplied mode/memory/routes/usage. It has no durable revision, permission grant, process or endpoint for {category}."}
    if identity=="native.pairing.scope-input" and category in {"permissions","interrupted"}:
        return {"kind":"not_applicable","reason":"Invalid target/scope admission is validated before entering any database transaction; disk permissions and worker interruption belong to the separately bound pairing storage/authority invariants."}
    return None
