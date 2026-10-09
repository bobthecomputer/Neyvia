"""Generated mission effects and frontend state transitions in owned scratch.

No harness/model is launched. The durable builders use production receipt,
continuity and lifecycle owners; frontend builders import the shipped reducers.
Category bindings are deliberately narrower than family membership.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

PREFIX = "proofs-c.missions."
TEXT_CATEGORIES = {"empty", "huge", "unicode"}


def require(value, message):
    if not value:
        raise AssertionError(message)


def refused(action, exceptions=(ValueError, OSError)):
    try:
        action()
    except exceptions as error:
        return {"type": type(error).__name__, "error": str(error)}
    raise AssertionError("Forbidden/adverse operation succeeded")


def body(category):
    return "" if category == "empty" else "雪 🧭 café e\u0301 שלום" if category == "unicode" else "x" * 196608 if category == "huge" else "owned mission result"


def pool(action, count=8):
    with ThreadPoolExecutor(max_workers=min(8, count)) as executor:
        return list(executor.map(action, range(count)))


@contextmanager
def exclusive(path):
    """An actual Windows sharing refusal, confined to the named owned file."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path.resolve()), 0x80000000, 0, None, 3, 0, None)
    require(handle != ctypes.c_void_p(-1).value, f"Owned exclusive open failed: {ctypes.get_last_error()}")
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def child(root, program, *args):
    return subprocess.run([sys.executable, "-c", program, str(root), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", timeout=30,
                          env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, **hidden_windows_subprocess_kwargs())


def _receipts(root, category):
    from .models import ExecutionReceipt
    from .mission_receipts import append_mission_receipt, load_mission_receipts, mission_receipts_path, validate_mission_receipt, ReceiptValidationError
    text = body(category)
    path = mission_receipts_path(root)
    make = lambda index: ExecutionReceipt(receipt_id=f"r-{index}", mission_id="owned" if index % 2 == 0 else "other",
        host="fixture", runtime="system-python", workspace=str(root), status="completed", summary=text or "empty payload", inputs={"text": text})
    if category == "empty":
        require(load_mission_receipts(root) == [], "Absent receipt stream invented history")
        refused(lambda: append_mission_receipt(root, {}), (ReceiptValidationError,))
        require(not path.exists(), "Invalid empty receipt created stream")
    count = 8 if category in {"huge", "concurrency"} else 4
    if category == "interrupted":
        result = child(root, "import os,sys; from grant_agent.models import ExecutionReceipt; from grant_agent.mission_receipts import append_mission_receipt; append_mission_receipt(sys.argv[1],ExecutionReceipt(receipt_id='r-0',mission_id='owned',host='fixture',runtime='system-python',workspace=sys.argv[1],status='completed',summary='owned mission result',inputs={'text':'owned mission result'})); os._exit(23)")
        require(result.returncode == 23, "Owned receipt writer did not exit after durable append")
        append_mission_receipt(root, make(1), max_receipts=100)
        count = 2
    elif category == "concurrency":
        pool(lambda index: append_mission_receipt(root, make(index), max_receipts=100), count)
    else:
        for index in range(count):
            append_mission_receipt(root, make(index), max_receipts=100)
    before = path.read_bytes()
    raw = [json.loads(line) for line in before.decode().splitlines()]
    require(len(raw) == count and len({row["receipt_id"] for row in raw}) == count, "Durable append lost or duplicated receipt")
    require(all(row["inputs"]["text"] == text for row in raw), "Receipt text did not survive bytes round trip")
    if category == "permissions":
        with exclusive(path):
            error = refused(lambda: append_mission_receipt(root, make(99)), (PermissionError,))
            denied_rows = load_mission_receipts(root, limit=100, mission_id="owned")
            schema_value = validate_mission_receipt(make(100))
        require(path.read_bytes() == before, "Sharing-denied append changed receipt bytes")
        require(denied_rows == [] and schema_value["receipt_id"] == "r-100",
                "Denied receipt read leaked rows or pure schema validation depended on file access")
        return {"contracts": [PREFIX + suffix for suffix in ("receipt-durable", "receipt-filter", "receipt-schema")],
                "detail": {"error": error, "deniedReadRows": len(denied_rows), "schemaValidatedDuringDenial": True,
                           "preservedSha256": hashlib.sha256(before).hexdigest()}}
    if category == "stale":
        with path.open("a", encoding="utf-8") as stream:
            stream.write('{broken\n' + json.dumps({"receipt_id": "stale", "schema": "obsolete"}) + '\n')
    loaded = load_mission_receipts(root, limit=2, mission_id="owned")
    expected = [row for row in raw if row["mission_id"] == "owned"][-2:]
    require(loaded == expected, "Mission filter/tail differs from independently parsed persisted records")
    return {"contracts": [PREFIX + suffix for suffix in ("receipt-schema", "receipt-durable", "receipt-filter")],
            "detail": {"appends": count, "filteredIds": [row["receipt_id"] for row in loaded], "bytes": len(before), "sha256": hashlib.sha256(before).hexdigest(), "childExit": 23 if category == "interrupted" else None}}


def _handoffs(root, category):
    from .models import PlanReceipt, ExecutionReceipt
    from .mission_phase_inputs import build_executor_phase_input, build_verifier_phase_input, check_selected_skill_relevance
    text = body(category)
    common = dict(receipt_id="plan", mission_id="owned", host="fixture", runtime="local", workspace=str(root), status="completed", summary=text or "empty", goal_restatement=text)
    count = 160 if category == "huge" else 0 if category == "empty" else 3
    files = [f"{i}-{text[:300]}.py" for i in range(count)]
    skills = [f"{i}-{text[:180]}" for i in range(count)]
    plan = PlanReceipt(**common, file_scope=files, selected_skills=skills, forbidden_paths=files, tasks=[{"id": str(i), "title": text} for i in range(count)], inputs={"rawDocs": "PRIVATE_CONTEXT"}, metadata={"fullMissionHistory": "PRIVATE_CONTEXT"})
    execution = ExecutionReceipt(**{key: value for key, value in common.items() if key != "goal_restatement"}, changed_files=files, proof_paths=files, metadata={"fullRuntimeTranscript": "PRIVATE_TRANSCRIPT"})
    executor = build_executor_phase_input(original_goal=text, plan_receipt=plan)
    verifier = build_verifier_phase_input(original_goal=text, plan_receipt=plan, execution_receipt=execution, changed_files=files + files, proof_artifacts=files + files)
    expected_goal = text if len(text) <= 1000 else text[:997] + "..."
    require(executor.original_goal == expected_goal and len(executor.file_scope) == min(count, 80) and len(executor.selected_skills) == min(count, 24), "Executor cap or input semantics differs")
    require(len(verifier.changed_files) == min(count, 80) and len(verifier.proof_artifacts) == min(count, 40), "Verifier ordered dedup/caps differs")
    require("PRIVATE_CONTEXT" not in json.dumps(asdict(executor)) and "PRIVATE_TRANSCRIPT" not in json.dumps(asdict(verifier)), "Private raw context leaked into phase capsule")
    if category == "stale":
        refused(lambda: build_executor_phase_input(original_goal=text, plan_receipt={**asdict(plan), "schema": "old-plan"}))
        refused(lambda: build_verifier_phase_input(original_goal=text, plan_receipt=plan, execution_receipt={**asdict(execution), "schema": "old-execution"}))
    relevance_goal = "verify backend " + (text if category == "unicode" else "")
    relevance_ids = [] if category == "empty" else [f"verify_backend-{i}" for i in range(1200)] if category == "huge" else ["verify_backend"]
    result = check_selected_skill_relevance(original_goal=relevance_goal, plan_receipt=PlanReceipt(**{**common, "selected_skills": relevance_ids, "goal_restatement": relevance_goal}), skill_brief={"selected_skills": [{"skillId": name, "description": "verify backend code " + text[:300]} for name in relevance_ids]})
    require(result["status"] == ("blocked" if category == "empty" else "passed"), "Skill-selection decision concealed empty/relevant selection")
    if category == "stale":
        current_plan = PlanReceipt(**{**common, "selected_skills": ["poetry_writer"], "goal_restatement": "verify backend service"})
        stale_brief = {"selected_skills": [{"skillId": "poetry_writer", "description": "write poetry"}]}
        stale = check_selected_skill_relevance(original_goal="verify backend service", plan_receipt=current_plan, skill_brief=stale_brief)
        require(stale["status"] == "review" and stale["irrelevantSkillCount"] == 1
                and stale["checks"][0]["skillId"] == "poetry_writer",
                "Stale skill description remained trusted as relevant")
    require(result["selectedSkillCount"] == min(len(relevance_ids), 24), "Skill relevance selection bound/count differs")
    identities = [PREFIX + "executor-boundary", PREFIX + "verifier-boundary"]
    identities.append(PREFIX + "skill-relevance")
    return {"contracts": identities, "detail": {"inputCharacters": len(text), "fileCount": count, "executorFiles": len(executor.file_scope), "verifierFiles": len(verifier.changed_files), "relevance": result["status"]}}


def _receipt_live_lock(root, category):
    from .mission_receipts import mission_receipts_path, append_mission_receipt, load_mission_receipts
    from .models import ExecutionReceipt
    path = mission_receipts_path(root)
    marker, release = root / "owner-ready", root / "owner-release"
    program = "import sys,time;from pathlib import Path;from grant_agent.mission_receipts import _legacy_receipt_file_lock as _receipt_file_lock,mission_receipts_path;root=Path(sys.argv[1]);\nwith _receipt_file_lock(mission_receipts_path(root)):\n (root/'owner-ready').write_text('ready');deadline=time.monotonic()+20\n while not (root/'owner-release').exists() and time.monotonic()<deadline:time.sleep(.02)\n"
    worker = subprocess.Popen([sys.executable, "-c", program, str(root)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, **hidden_windows_subprocess_kwargs())
    early_write = False
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            deadline = time.monotonic() + 15
            while not marker.exists() and worker.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            require(marker.exists() and worker.poll() is None, "Owned receipt lock holder did not enter boundary")
            lock = path.with_suffix(path.suffix + ".lock")
            os.utime(lock, (time.time() - 100, time.time() - 100))
            receipt = ExecutionReceipt(receipt_id="contender", mission_id="owned", host="fixture", runtime="system-python", workspace=str(root), status="completed", summary="Owned concurrent lock contender")
            future = executor.submit(append_mission_receipt, root, receipt)
            time.sleep(.6)
            early_write = future.done() and path.exists() and worker.poll() is None
        finally:
            release.write_text("release", encoding="utf-8")
            _, errors = worker.communicate(timeout=5)
        result = future.result(timeout=15)
    observed = {"ownedPid": worker.pid, "childExit": worker.returncode, "oldLiveLockRemoved": early_write, "contenderReceipt": result["receipt_id"], "persistedRows": len(load_mission_receipts(root)), "childStderr": errors.decode(errors="replace")[-500:]}
    if early_write:
        error = AssertionError("Receipt append stole an aged lock from an actual living owner and wrote before owner release")
        error.fixture_effects = observed
        raise error
    require(worker.returncode == 0 and observed["persistedRows"] == 1, "Owner release did not unblock exactly one durable append")
    return {"contracts": [PREFIX + "receipt-durable"], "detail": observed}


def _receipt_dead_lock(root, category):
    from .mission_receipts import mission_receipts_path, append_mission_receipt, load_mission_receipts
    from .models import ExecutionReceipt
    path = mission_receipts_path(root)
    program = "import os,sys,time;from pathlib import Path;from grant_agent.mission_receipts import _legacy_receipt_file_lock,mission_receipts_path;p=mission_receipts_path(sys.argv[1]);\nwith _legacy_receipt_file_lock(p):\n lock=p.with_suffix(p.suffix+'.lock');os.utime(lock,(time.time()-100,time.time()-100));os._exit(23)\n"
    result = child(root, program)
    require(result.returncode == 23, "Owned legacy writer did not exit inside lock boundary")
    lock = path.with_suffix(path.suffix + ".lock")
    ownership = json.loads(lock.read_text(encoding="utf-8"))
    require(ownership["pid"] > 0, "Dead writer left no identifiable legacy owner")
    receipt = ExecutionReceipt(receipt_id="recovered", mission_id="owned", host="fixture", runtime="local", workspace=str(root), status="completed", summary="Recovered dead writer fence")
    append_mission_receipt(root, receipt)
    require(not lock.exists() and [row["receipt_id"] for row in load_mission_receipts(root)] == ["recovered"], "Dead legacy fence was not reclaimed into exactly one durable append")
    return {"contracts": [PREFIX + "receipt-durable"], "detail": {"childExit": result.returncode, "deadOwnerPid": ownership["pid"], "legacyFenceReclaimed": True, "persistedReceipts": 1}}


def _control_denied(root, category):
    from .mission_control import ControlRoomStore
    store = ControlRoomStore(root)
    path = store.missions_path
    store._write_json_if_changed(path, [{"text": "original"}])
    before = path.read_bytes()
    with exclusive(path):
        error = refused(lambda: store._write_json_if_changed(path, [{"text": "denied replacement"}]), (OSError,))
    require(path.read_bytes() == before, "Sharing-denied control-room replacement altered original bytes")
    return {"contracts": [PREFIX + "control-durable"], "detail": {"error": error, "preservedSha256": hashlib.sha256(before).hexdigest(), "actualWindowsSharingDenial": True}}


def _continuity(root, category):
    from .continuity_policy import MissionContinuityStore
    store = MissionContinuityStore(root)
    text = body(category)
    first = store.create_or_update("owned", goal=text, patch={"status": "running", "confirmedFacts": [text], "currentStep": "first"})
    count = 8 if category == "huge" else 16 if category == "concurrency" else 2
    action = lambda index: MissionContinuityStore(root).record_tool_attempt("owned", tool="owned.read", idempotency_key=f"result-{index}", action={"kind": "read", "text": text}, outcome="verified", evidence={"index": index, "text": text})
    if category == "interrupted":
        result = child(root, "import os,sys; from grant_agent.continuity_policy import MissionContinuityStore; s=MissionContinuityStore(sys.argv[1]); s.record_tool_attempt('owned',tool='owned.read',idempotency_key='result-0',action={'kind':'read','text':'owned mission result'},outcome='verified',evidence={'index':0,'text':'owned mission result'}); os._exit(23)")
        require(result.returncode == 23, "Owned interrupted continuity writer failed before durable attempt")
        action(1)
    elif category == "concurrency":
        pool(action, count)
    else:
        for index in range(count):
            action(index)
    path = store._record_path("owned")
    raw = json.loads(path.read_text(encoding="utf-8"))
    require(raw["revision"] == first["revision"] + count and len(raw["toolAttempts"]) == count, "Continuity lost concurrent or resumed facts/revisions")
    require({row["evidence"]["index"] for row in raw["toolAttempts"]} == set(range(count)), "Continuity durable evidence differs from emitted indexes")
    before = path.read_bytes()
    duplicate = action(0)
    require(duplicate["duplicateSuppressed"] and path.read_bytes() == before, "Restart replay rewrote completed action")
    if category == "permissions":
        with exclusive(path):
            loaded = store.load("owned")
        require(loaded["recovery"]["status"] == "restored_from_previous_snapshot" and loaded["revision"] == raw["revision"] - 1, "Actual denied current read did not expose previous safe revision")
        require(path.read_bytes() == before, "Denied continuity read mutated current snapshot")
    if category == "stale":
        previous = json.loads(store._previous_path("owned").read_text(encoding="utf-8"))
        path.write_text("{interrupted stale snapshot", encoding="utf-8")
        restored = store.load("owned")
        require(restored["revision"] == previous["revision"] and restored["toolAttempts"] == previous["toolAttempts"], "Corrupt current snapshot invented progress rather than preserving previous facts")
        store.create_or_update("owned", patch={"currentStep": "reconciled"})
    recovered = MissionContinuityStore(root).recover("owned")
    require(recovered["duplicateProtection"], "Recovery forgot durable completed identities")
    identities = [PREFIX + "continuity-durable", "a-cli.continuity.attempt", "a-cli.continuity.recovery"]
    if category == "permissions":
        identities = [PREFIX + "continuity-durable"]
    return {"contracts": identities, "detail": {"attempts": count, "observedRevision": raw["revision"], "replayPreservedBytes": True, "recovery": recovered.get("status"), "childExit": 23 if category == "interrupted" else None}}


def _lifecycle(root, category):
    from .models import MissionRun, MissionRunReceiptRef
    from .mission_phase_runner import start_current_phase, complete_current_phase, MissionPhaseTransitionError
    text = body(category)
    value = MissionRun("owned-run", "owned", "scratch", text)
    other = MissionRun("other-run", "other", "scratch", "other")
    value.file_scope.append(text)
    value.metadata["payload"] = text
    require(not other.file_scope and not other.metadata, "Mission run defaults share mutable state")
    if category == "stale":
        from .proofs_c_missions import check_run
        before = asdict(other)
        value.schema_version = "fluxio.mission_run.obsolete"
        refused(lambda: start_current_phase(value))
        require(asdict(other) == before and other.schema_version == "fluxio.mission_run.v1",
                "Stale envelope mutation crossed into a fresh MissionRun default set")
        value.schema_version = "fluxio.mission_run.v1"
        check_run(value)
    transitions = []
    for phase in ("preflight", "planner", "executor", "verifier", "final_report"):
        require(value.current_phase == phase, "Phase successor unexpected")
        start_current_phase(value)
        transition = complete_current_phase(value, outcome="accepted" if phase == "verifier" else "completed", summary=text,
            receipt_ref=MissionRunReceiptRef(phase, phase, "accepted", summary=text))
        transitions.append(asdict(transition))
    require(value.status == "completed" and value.completed_at and len(value.receipts) == 5, "Terminal lifecycle lost receipts or completion truth")
    before = asdict(value)
    refused(lambda: start_current_phase(value), (MissionPhaseTransitionError,))
    require(asdict(value) == before, "Terminal restart changed lifecycle")
    path = root / "mission-run.json"
    path.write_text(json.dumps(asdict(value), ensure_ascii=False), encoding="utf-8")
    require(json.loads(path.read_text(encoding="utf-8"))["objective"] == text, "Mission envelope durable text differs")
    if category == "stale":
        repair = MissionRun("repair-run", "owned", "scratch", text)
        for _ in range(3):
            start_current_phase(repair)
            complete_current_phase(repair)
        start_current_phase(repair)
        complete_current_phase(repair, outcome="repair_needed")
        start_current_phase(repair)
        complete_current_phase(repair)
        start_current_phase(repair)
        complete_current_phase(repair, outcome="repair_needed")
        require(repair.status == "blocked" and repair.metadata["repair_loop_count"] == 1 and repair.metadata["repair_loop_limit_exhausted"], "Repeated verifier failure escaped repair budget")
    bindings = [PREFIX + "phase-transition"] if category == "stale" else [PREFIX + "run-envelope", PREFIX + "phase-transition", PREFIX + "default-isolation"]
    if category == "stale":
        bindings.extend((PREFIX + "run-envelope", PREFIX + "default-isolation"))
    return {"contracts": bindings, "detail": {"objectiveCharacters": len(text), "transitions": transitions, "terminalRestartRefused": True}}


def _projection(root, category):
    from .models import Mission, VerificationReceipt
    from .mission_control import ControlRoomStore
    from .mission_artifacts import build_mission_run_artifact_layout
    from .mission_receipts import append_mission_receipt
    from .flight_recorder import MissionFlightRecorder
    text = body(category)
    mission = Mission(mission_id="owned", workspace_id="scratch", runtime_id="local", objective=text, success_checks=[])
    store = ControlRoomStore(root)
    store.save_missions([mission])
    before = store.missions_path.read_bytes()
    if category in TEXT_CATEGORIES:
        invalid_identity = "" if category == "empty" else text if category == "unicode" else "x" * 1024
        untouched = set(root.rglob("*"))
        refused(lambda: build_mission_run_artifact_layout(root, invalid_identity, create=True))
        require(set(root.rglob("*")) == untouched, "Rejected artifact identity wrote partial directories")
    layout = build_mission_run_artifact_layout(root, "owned", create=True)
    count = 24 if category == "huge" else 0 if category == "empty" else 3
    for index in range(count):
        append_mission_receipt(Path(layout.receipts_jsonl), VerificationReceipt(receipt_id=f"r-{index}", mission_id="owned", host="fixture", runtime="local", workspace=str(root), status="accepted", summary=text[:8192] or "empty", decision="accepted"))
    recorder = MissionFlightRecorder(root, "owned")
    for index in range(count):
        recorder.append_event(kind="owned.output", message=text, phase="executor", payload={"index": index})
    recorder.snapshot(current_phase="executor", runtime_command="owned local observation", cwd=str(root), env_status={}, process_ids=[os.getpid()], lease_id="owned", heartbeat_age_seconds=0, queue_reason="", changed_files=[], verifier_result={})
    if category == "stale":
        (Path(layout.snapshots_dir) / "mission_run.json").write_text(json.dumps({"schema_version": "fluxio.mission_run.v1", "mission_id": "foreign", "current_phase": "final_report"}))
    value = store._mission_run_read_model_payload(mission, root=root)
    require(value["missionId"] == "owned" and value["objective"] == text and value["receiptCount"] == len(value["receipts"]), "Mission read model lost durable identity or counts")
    require(not value["snapshotPresent"], "Foreign/absent lifecycle snapshot was adopted")
    flight = value["flightRecorder"]
    recorded_snapshot = json.loads(recorder.snapshot_path.read_text(encoding="utf-8"))
    require(flight["present"] and flight["processIds"] == [os.getpid()] and flight["currentPhase"] == "executor" and flight["eventCount"] == recorded_snapshot["eventCount"], "Flight read model lost independently saved phase/process/event evidence")
    require(flight["events"] == recorded_snapshot["events"][-20:], "Flight read model did not preserve bounded event tail")
    require(store.missions_path.read_bytes() == before, "Read model mutated control-room source")
    actual = json.loads(store.missions_path.read_text(encoding="utf-8"))
    require(actual[0]["objective"] == text, "Control-room save differs from actual durable bytes")
    identities = [PREFIX + suffix for suffix in ("control-durable", "local-read-model", "local-flight")]
    if category == "stale":
        identities = [PREFIX + "local-read-model"]
    if category in TEXT_CATEGORIES:
        identities.append(PREFIX + "artifact-layout")
    return {"contracts": identities, "detail": {"receiptCount": value["receiptCount"], "eventCount": flight["eventCount"], "processId": os.getpid(), "sourcePreserved": True}}


def _local_output(root, category):
    from . import mission_control as mc
    from .models import Mission
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    mission = Mission(mission_id="owned", workspace_id="scratch", runtime_id="hermes", objective="Inspect local report artifact", success_checks=[])
    mission.execution_scope.workspace_root = mission.execution_scope.execution_root = str(root)
    store = mc.ControlRoomStore(root)
    store.save_missions([mission])
    require(not mc.mission_runtime_dialogue_turns(mission, root=root) and not mc.mission_hard_artifact_gate(mission, root=root)["passed"], "Missing local output generated dialogue or completed gate")
    directory = root / ".agent_control/mission_artifacts/owned"
    output = directory / "proof/runtime_output.txt"
    output.parent.mkdir(parents=True)
    text = "Local report from the owned Python producer. Arithmetic 17 * 19 = 323. The generated file and captured result are independently available for review. " + body(category)
    # This is the actual producing child, not an inferred model/provider result.
    input_path = root / "producer-input.txt"
    input_path.write_text(text, encoding="utf8")
    program = "from pathlib import Path; import os,sys; value=Path(sys.argv[1]).read_text(encoding='utf8'); Path(sys.argv[2]).write_text(value,encoding='utf8'); print(value,flush=True); " + ("os._exit(23)" if category == "interrupted" else "")
    produced = subprocess.run([sys.executable, "-c", program, str(input_path), str(output)], capture_output=True, text=True, encoding="utf8", timeout=30, env={**os.environ, "PYTHONIOENCODING": "utf8"}, **hidden_windows_subprocess_kwargs())
    require(produced.returncode == (23 if category == "interrupted" else 0) and produced.stdout.rstrip("\r\n") == text and output.read_text(encoding="utf8") == text, "Owned child did not independently conserve captured and durable report")
    (directory / "index.html").write_text("<main>Owned local report</main>", encoding="utf8")
    def observe(_=None):
        transcript = store._mission_runtime_transcript_payload(mission, root=root, events=[])
        messages = store._mission_agent_messages_payload(mission, root=root, events=[], runtime_transcript=transcript)
        dialogue = mc.mission_runtime_dialogue_turns(mission, root=root)
        gate = mc.mission_hard_artifact_gate(mission, root=root, runtime_transcript=transcript, agent_messages=messages)
        require(transcript["status"] == "attached" and transcript["sessionId"] == "runtime_artifact" and gate["passed"] and gate["runtimeOutputCount"] > 0 and gate["artifactCount"] > 0, "Actual report was not attached to transcript/gate")
        require(dialogue and text[:120] in dialogue[0]["text"] and any(text[:120] in str(row.get("detail")) for row in messages), "Local report dialogue/messages lost concrete captured body")
        return {"messageCount": len(messages), "dialogueCount": len(dialogue), "gatePassed": gate["passed"]}
    facts = observe()
    if category == "permissions":
        before = output.read_bytes()
        with exclusive(output):
            require(mc.mission_runtime_dialogue_turns(mission, root=root) == [] and not mc.mission_hard_artifact_gate(mission, root=root)["passed"], "OS-denied report invented accessible dialogue/output evidence")
        require(output.read_bytes() == before, "Denied report reader changed producer bytes")
        observe()
    if category == "concurrency":
        concurrent = pool(observe)
        require(all(row == facts for row in concurrent), "Concurrent readers changed actual report projection")
    if category == "stale":
        mission.state.latest_session_id = "stale-read-only"
        timeline = root / ".agent_runs/stale-read-only/timeline.jsonl"
        timeline.parent.mkdir(parents=True)
        timeline.write_text(json.dumps({"kind": "action.proposed", "message": "Old plan only", "metadata": {"kind": "file_read", "target_path": str(input_path)}}) + "\n", encoding="utf8")
        observe()
    mission.state.status = "verification_failed"
    mission.state.stop_reason = mission.state.last_runtime_event = "artifact_gate_failed"
    mission.state.verification_failures = [mc.HARD_ARTIFACT_GATE_CHECK_ID]
    mission.proof.failed_checks = [mc.HARD_ARTIFACT_GATE_FAILURE, "independent failure"]
    mission.proof.blocked_by = [mc.HARD_ARTIFACT_GATE_FAILURE]
    gate = mc.mission_hard_artifact_gate(mission, root=root)
    require(not mc._complete_repaired_hard_artifact_gate_from_detail(mission, gate), "Local artifact repair erased unrelated verifier failure")
    mission.proof.failed_checks.remove("independent failure")
    require(mc._complete_repaired_hard_artifact_gate_from_detail(mission, gate), "Concrete local output did not complete exact artifact repair")
    store.update_mission(mission)
    saved = mc.ControlRoomStore(root).get_mission("owned")
    require(saved.state.status == "completed" and not saved.proof.failed_checks and not saved.proof.blocked_by, "Repaired local artifact state was not durable")
    return {"contracts": [PREFIX + n for n in ("local-dialogue", "local-transcript", "local-messages", "local-artifact-gate", "local-artifact-repair")], "detail": {**facts, "producerExit": produced.returncode, "producer": "actual owned system Python process", "bytes": len(output.read_bytes()), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "renderedProof": False, "modelProviderInvoked": False}}


def _platform(root, category):
    from .mission_control import _platform_path_for_windows_drive
    tail = "" if category == "empty" else "segment/" * 1000 if category == "huge" else "雪/café/🙂" if category == "unicode" else "owned/evidence"
    values = [f"C:\\{tail.replace('/', chr(92))}", f"D:/{tail}", tail]
    for value in values:
        for posix in (True, False):
            actual = _platform_path_for_windows_drive(value, posix=posix)
            expected = "/mnt/" + value[0].lower() + "/" + value[3:].replace("\\", "/") if posix and len(value) > 2 and value[1:3] in {":/", ":\\"} else value
            require(actual == Path(expected), "Explicit platform path parser changed drive/tail")
    return {"contracts": [PREFIX + "local-platform"], "detail": {"suppliedPaths": len(values), "explicitPlatformBranches": 2, "pathCharacters": len(tail), "filesAccessed": 0}}


def _readiness(root, category):
    from .mission_control import _public_launch_readiness_digest
    path = root / ".agent_control/public_launch_readiness/latest.json"
    path.parent.mkdir(parents=True)
    text = body(category)
    old = {"schema": "fluxio.public_launch_readiness.v1", "checkedAt": "2026-01-01T10:00:00Z", "status": "old_unpublished", "ok": False, "missing": ["publication"]}
    current = {**old, "checkedAt": "2026-01-01T11:00:00Z", "status": "current_unpublished", "missing": [text] if text else [], "publicWeb": {"sourceDirtyPathSample": [text]}, "repairPacket": {"receiptTargets": [text]}, "blockers": [{"checkId": "publication", "details": text}] * (1000 if category == "huge" else 1)}
    path.write_text(json.dumps(current), encoding="utf8")
    before = path.read_bytes()
    def observe(_=None):
        result = _public_launch_readiness_digest(root, old)
        require(result["status"] == current["status"] and result["publicWeb"] == current["publicWeb"] and result["repairPacket"] == current["repairPacket"] and result["missing"] == current["missing"] and result["blockers"] == current["blockers"][:6] and not result["ok"], "Readiness projection lost current exact unpublished evidence or blocker bound")
        return result
    observe()
    if category == "concurrency":
        require(all(row == observe() for row in pool(observe)), "Concurrent readiness readers disagreed")
    if category == "permissions":
        with exclusive(path):
            require(_public_launch_readiness_digest(root, old)["status"] == old["status"] and _public_launch_readiness_digest(root)["status"] == "missing", "OS-denied readiness reader invented publication")
        observe()
    if category == "stale":
        newer = {**old, "checkedAt": "2026-01-01T12:00:00Z", "status": "newer_unpublished"}
        require(_public_launch_readiness_digest(root, newer)["status"] == newer["status"], "Older on-disk readiness displaced newer explicit source")
    require(path.read_bytes() == before, "Readiness projection mutated supplied receipt")
    return {"contracts": [PREFIX + "local-public-launch"], "detail": {"currentTimestampPreferred": True, "bytesPreserved": True, "blockerCount": len(current["blockers"][:6]), "renderedProof": False, "publicationClaimed": False}}


def _policy(root, category):
    from .security_runtime_policy import evaluate_security_action, build_purple_team_plan, audit_security_tool_coverage
    from .mission_control import apply_agent_turn_mode_to_launch
    from .continuity_policy import MissionContinuityStore
    from .fluxio_harness import infer_task_route_profile
    text = body(category)
    target = text if category == "unicode" else "owned.invalid"
    scope = {"target": target, "authorizedBy": text or "owner", "authorizationConfirmed": category != "empty", "environment": "lab", "mode": "active", "allowedTargets": [target], "allowedActionClasses": ["probe"]}
    allowed = evaluate_security_action(scope, {"target": target, "actionClass": "probe", "active": True})
    require(allowed["allowed"] == (category != "empty"), "Owner scope decision did not follow recorded authorization")
    denied = evaluate_security_action(scope, {"target": "foreign.invalid", "actionClass": "probe", "active": True})
    require(not denied["allowed"], "Unscoped target admitted")
    plan = build_purple_team_plan(scope)
    require([row["owner"] for row in plan["phases"]] == ["auditor", "red", "blue", "defender", "auditor"], "Purple-team separation lost role ownership")
    items = [] if category == "empty" else [{"toolId": "tool.windows-defender" + (text if category == "unicode" else ""), "executionReady": category == "unicode", "state": "verified", "readinessDetail": text}] * (1200 if category == "huge" else 1)
    coverage = audit_security_tool_coverage(items)
    require(not coverage["ready"] and "blue_detection" in coverage["missingPhases"], "Unexecutable security tool satisfied phase readiness")
    if category == "stale":
        require(not evaluate_security_action({**scope, "authorizationConfirmed": False}, {"target": target, "actionClass": "probe", "active": True})["allowed"], "Revoked scope authorization remained admitted")
    launch = apply_agent_turn_mode_to_launch(turn_mode="standard", objective=text, success_checks=[text] if text else [], route_overrides=[], mode="Focus", budget_hours=2)
    require(launch["objective"] == text and launch["turnMode"] == "standard" and launch["mode"] == "Focus", "Launch mode corrupted goal")
    deep = apply_agent_turn_mode_to_launch(turn_mode="1m", objective=text, success_checks=[], route_overrides=[{"role": "executor", "effort": "low"}], mode="Focus", budget_hours=2)
    require(deep["mode"] == "Deep Run" and deep["routeOverrides"][0]["effort"] == "high", "Deep launch did not carry runtime effort")
    continuity = MissionContinuityStore(root)
    continuity.create_or_update("gpu", patch={"gpuPolicy": {"maxConcurrentInstances": 1, "maxEstimatedHourlyCost": 5, "maxEstimatedSessionCost": 4, "maxDurationMinutes": 60, "idleReleaseMinutes": 10, "requireApprovalForPaidStart": True}})
    proposal = {"action": "start_instance", "estimatedHourlyCost": 1e9 if category == "huge" else 3, "estimatedDurationMinutes": 120}
    decision = continuity.evaluate_gpu_action("gpu", proposal, {"runningInstances": 0, "validCheckpoint": False})
    require(not decision["allowed"] and decision["estimatedSessionCost"] == proposal["estimatedHourlyCost"] * 2, "GPU cost policy ignored exact expected duration/cost")
    overtime = continuity.evaluate_gpu_action("gpu", {"action": "continue_training"}, {"runningInstances": 1, "runningDurationMinutes": 61, "idleMinutes": 11, "validCheckpoint": True})
    require(overtime["releaseRequired"] and not overtime["allowed"], "GPU expired/idle reservation permitted continued work")
    red = infer_task_route_profile("Run an authorized red-team attack-surface assessment in the lab " + text)
    blue = infer_task_route_profile("Perform blue-team detection engineering and incident response triage " + text)
    require(red["taskType"] == "security_red_team" and blue["taskType"] == "security_blue_team", "Security route intent collapsed distinct runtime role")
    identities = [PREFIX + suffix for suffix in ("security-scope", "security-coverage", "turn-mode", "gpu-policy", "security-route")]
    if category == "permissions":
        identities = [PREFIX + "security-scope", PREFIX + "gpu-policy"]
    elif category == "stale":
        identities = [PREFIX + "security-scope", PREFIX + "gpu-policy"]
    if category in {"empty", "unicode"}:
        identities.remove(PREFIX + "gpu-policy")
    if category == "empty":
        identities.remove(PREFIX + "security-route")
    return {"contracts": identities, "detail": {"scopeAllowed": allowed["allowed"], "foreignTargetRefused": True, "inspectedToolCandidates": len(items), "estimatedSessionCost": decision["estimatedSessionCost"], "releaseRequired": overtime["releaseRequired"], "launchMode": deep["mode"], "externalActions": 0}}


FAMILIES = {
    "local-output": (_local_output, {PREFIX + n for n in ("local-dialogue", "local-transcript", "local-messages", "local-artifact-gate", "local-artifact-repair")}, TEXT_CATEGORIES | {"concurrency", "interrupted", "permissions", "stale", "offline"}),
    "platform": (_platform, {PREFIX + "local-platform"}, TEXT_CATEGORIES),
    "readiness": (_readiness, {PREFIX + "local-public-launch"}, TEXT_CATEGORIES | {"concurrency", "permissions", "stale"}),
    "receipts": (_receipts, {PREFIX + suffix for suffix in ("receipt-schema", "receipt-durable", "receipt-filter")}, TEXT_CATEGORIES | {"concurrency", "interrupted", "stale", "permissions"}),
    "handoffs": (_handoffs, {PREFIX + suffix for suffix in ("executor-boundary", "verifier-boundary", "skill-relevance")}, TEXT_CATEGORIES | {"stale"}),
    "continuity": (_continuity, {PREFIX + "continuity-durable", "a-cli.continuity.attempt", "a-cli.continuity.recovery"}, TEXT_CATEGORIES | {"concurrency", "interrupted", "stale", "permissions"}),
    "lifecycle": (_lifecycle, {PREFIX + suffix for suffix in ("run-envelope", "phase-transition", "default-isolation")}, TEXT_CATEGORIES | {"stale"}),
    "projection": (_projection, {PREFIX + suffix for suffix in ("artifact-layout", "control-durable", "local-read-model", "local-flight")}, TEXT_CATEGORIES | {"stale"}),
    "policy": (_policy, {PREFIX + suffix for suffix in ("security-scope", "security-coverage", "turn-mode", "gpu-policy", "security-route")}, TEXT_CATEGORIES | {"permissions", "stale"}),
    "receipt-live-lock": (_receipt_live_lock, {PREFIX + "receipt-durable"}, {"stale", "concurrency"}),
    "receipt-dead-lock": (_receipt_dead_lock, {PREFIX + "receipt-durable"}, {"interrupted"}),
    "control-denied": (_control_denied, {PREFIX + "control-durable"}, {"permissions"}),
}

NODE_PROGRAM = r'''
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const [repo, category] = process.argv.slice(2);
const load = path => import(pathToFileURL(repo + '/' + path));
const composer = await load('web/src/neyvia/next/nxComposerModel.js');
const autopilot = await load('web/src/neyvia/next/nxAutopilotModel.js');
const attention = await load('web/src/neyvia/neyviaAttentionInbox.js');
const mission = await load('web/src/neyvia/neyviaMissionProjection.js');
const rows = [];
const text = category === 'empty' ? '' : category === 'huge' ? 'x'.repeat(196608) : category === 'unicode' ? '雪 🧭 café e\u0301 שלום' : 'owned';
const count = category === 'huge' ? 1200 : category === 'empty' ? 0 : 6;
async function check(id, supported, action) {
  if (!supported.includes(category)) return;
  try { const detail = await action(); rows.push({id:'missions:frontend:' + id + ':' + category, category, contracts:[id], status:'passed', detail:detail || {observed:true}, boundary:'actual imported production frontend state function with independent output/state assertions'}); }
  catch(error) { rows.push({id:'missions:frontend:' + id + ':' + category, category, contracts:[id], status:'failed', detail:{type:error.name,error:error.message}, boundary:'actual production frontend state function'}); }
}
const textual = ['empty','huge','unicode'];
const image = data => ({name:text || 'owned.png',mime:'image/png',data});
await check('composer.stripDataUrl',textual,()=>{const value=category==='empty'?'':'data:image/png;base64,'+text; assert.equal(composer.stripDataUrl(value),text);});
await check('composer.base64Chars',['empty','huge'],()=>{const n=category==='empty'?0:9007199254740000; assert.equal(composer.base64Chars(n),4*Math.ceil(n/3));});
await check('composer.admitImages',textual,()=>{
  const incoming=category==='empty'?[]:category==='huge'?[image('a'.repeat(composer.MAX_IMAGE_CHARS+1)),image('b')]:[image(text)];
  const result=composer.admitImages([],incoming);
  assert.equal(result.accepted.length,category==='empty'?0:1);
  if(category==='huge'){assert.equal(result.accepted[0].data,'b'); assert(result.refused.length);}
  if(category==='unicode') assert.equal(result.accepted[0].name,text);
});
await check('composer.planImageReads',textual,()=>{
  const files=category==='empty'?[]:category==='huge'?[{name:'huge',type:'image/png',size:1e9},{name:'good',type:'image/png',size:3}]:[{name:text,type:'image/png',size:3}];
  const result=composer.planImageReads([],files); assert.equal(result.read.length,category==='empty'?0:1);
  if(category==='huge') assert.equal(result.read[0].name,'good'); if(category==='unicode') assert.equal(result.read[0].name,text);
});
await check('composer.imageBlocker',['empty','unicode','permissions'],()=>{
  const result=composer.imageBlocker({appName:text,capabilities:category==='empty'?{}:{images:true},model:{label:text,images:false}});
  assert(result.reason); assert.equal(composer.imageBlocker({capabilities:{images:true},model:{images:true}}),null);
  if(category==='unicode') assert(result.reason.includes(text));
});
await check('composer.sendIdentity',[...textual,'stale'],()=>{
  const a={transport:'local',images:[image(text)],config:{b:2,a:1}};
  const first=composer.sendIdentity(text,text,a);
  assert.equal(first,composer.sendIdentity(text,text,{config:{a:1,b:2},images:a.images,transport:'local'}));
  assert.notEqual(first,composer.sendIdentity(text,text,{...a,images:[image(text+'changed')]}));
  assert(!first.includes('"data":'));
});
await check('composer.parseArguments',textual,()=>{
  const input=category==='empty'?'':JSON.stringify({text}); assert.deepEqual(composer.parseArguments(input).value,category==='empty'?{}:{text});
  assert(composer.parseArguments('['+text).error); assert(composer.parseArguments('[]').error);
});
await check('composer.argumentSkeleton',textual,()=>{
  const names=Array.from({length:count},(_,i)=>text.slice(0,180)+'-'+i);
  const schema={type:'object',required:names,properties:Object.fromEntries(names.map(name=>[name,{type:'string',default:text}]))};
  const result=JSON.parse(composer.argumentSkeleton(schema)); assert.deepEqual(Object.keys(result),names); for(const name of names)assert.equal(result[name],text);
});
await check('composer.filterTools',textual,()=>{
  const tools=Array.from({length:count},(_,i)=>({name:'tool-'+String(i).padStart(5,'0'),available:i%2===0,description:text,category:'owned'}));
  const result=composer.filterTools(tools,category==='unicode'?text:''); assert.equal(result.length,tools.length);
  assert(result.slice(0,Math.ceil(count/2)).every(t=>t.available));
});
await check('composer.toolMutates',['empty','unicode','permissions'],()=>{
  assert.equal(composer.toolMutates(category==='empty'?null:{mutability_class:text || 'write'}),category!=='empty');
  assert.equal(composer.toolMutates({mutability_class:'read'}),false); assert.equal(composer.toolMutates({mutability_class:'write'}),true);
});
await check('composer.toolScope',textual,()=>{
  assert.equal(composer.toolScope({tool:'workspace.read',cwd:text}).root,text||null);
  assert.equal(composer.toolScope({tool:'neyvia.notes.read',cwd:text}).root,null);
  assert(composer.toolScope({desktop:true,cwd:text}).label.includes('state folder'));
});
await check('composer.draftUpdate',[...textual,'concurrency'],async()=>{
  const store=composer.createDraftStore(); const original=store.get('other'); const values=category==='empty'?[]:[image(text)];
  store.update('origin',values); assert.equal(store.get('other'),original); assert.equal(store.get('origin').length,values.length);
  if(category==='concurrency') await Promise.all(Array.from({length:8},(_,i)=>Promise.resolve().then(()=>store.update('chat-'+i,[image(String(i))]))));
  if(category==='concurrency') for(let i=0;i<8;i++)assert.equal(store.get('chat-'+i)[0].data,String(i));
});
await check('composer.attachResult',[...textual,'stale','concurrency','interrupted'],async()=>{
  const store=composer.createDraftStore(); const files=category==='empty'?[]:[{name:text||'owned',type:'image/png',size:3}];
  let reads=0; let release; const delayed=new Promise(resolve=>{release=resolve;});
  const pending=composer.attachToDraft(store,'origin',files,async()=>{reads++; if(['stale','concurrency'].includes(category))await delayed; if(category==='interrupted')throw new Error('Owned read cancelled'); return [image(text)];});
  if(category==='stale'){store.update('origin',Array.from({length:6},()=>image('prior'))); store.update('current',[image('unchanged')]); release();}
  else if(category==='concurrency') { await composer.attachToDraft(store,'other',files,async()=>[image('parallel')]); release(); }
  const message=await pending;
  if(category==='empty')assert.equal(reads,0);
  else if(category==='interrupted'){assert(message.includes('cancelled'));assert.equal(store.get('origin').length,0);}
  else if(category==='stale'){assert(message);assert.equal(store.get('origin').length,6);assert.equal(store.get('current')[0].data,'unchanged');}
  else assert.equal(store.get('origin')[0].data,text);
  if(category==='concurrency') assert.equal(store.get('other')[0].data,'parallel');
});
await check('autopilot.scopeTools',['empty','unicode','permissions'],()=>{
  assert(!autopilot.scopeTools(text).includes('workspace.write')); assert(autopilot.scopeTools('edit').includes('workspace.write'));
});
await check('autopilot.scopeOf',['empty','unicode','permissions'],()=>{
  assert.equal(autopilot.scopeOf(category==='empty'?[]:[text]),'look'); assert.equal(autopilot.scopeOf(['workspace.write']),'edit');
});
const run={status:'completed',items:Array.from({length:count},(_,i)=>({status:i%2===0?'completed':'pending',route:'script',modelReasons:[],receipt:{checks:[{passed:true}]}})),models:Array.from({length:count},(_,i)=>({reason:text||'owned',tokens:{input:i+1,output:1}}))};
await check('autopilot.attributeCalls',textual,()=>{
  const out=autopilot.attributeCalls(run); assert.equal(out.calls.length,count); assert.equal(new Set([...out.runLevel,...out.perItem.flat()].map(c=>c.index)).size,count); assert.equal(out.calls.reduce((n,c)=>n+c.total,0),count*(count+1)/2+count);
});
await check('autopilot.shapeRun',[...textual,'stale'],()=>{
  const out=autopilot.shapeRun(run); assert.equal(out.total,count);assert.equal(out.done,Math.ceil(count/2));assert.equal(out.scripts,out.done); assert.equal(out.totalTokens,count*(count+1)/2+count);
  if(category==='stale'){const second=autopilot.shapeRun({...run,status:'blocked'});assert.equal(second.live,false);assert.equal(second.state.tone,'red');}
});
await check('autopilot.checkLine',textual,()=>{
  if(category==='empty'){assert.equal(autopilot.checkLine(null),'');return;}
  const out=autopilot.checkLine({tool:'workspace.read',args:{path:text},expect:{path:'content',op:'contains',value:text}});assert(out.includes(text));assert(out.includes('workspace.read'));assert(out.includes('content contains'));
});
const now=Date.parse('2026-10-04T12:00:00Z');
const conversations=Array.from({length:count},(_,i)=>({conversationId:'chat-'+i,title:text,workspaceId:text||'owned',status:i%2===0?'completed':'running',lastMeaningfulActivityAt:new Date(now-i*1000).toISOString()}));
await check('attention.thread',[...textual,'stale','permissions'],()=>{
  if(category==='empty'){assert.equal(attention.projectAttentionThread({}),null);return;}
  const out=attention.projectAttentionThread({conversation:{conversationId:'owned',title:text,status:'completed',attentionState:category==='stale'?'settled':undefined,snoozedUntil:'2026-10-05T12:00:00Z',hasBlockingApproval:true},now});
  assert.equal(out.attentionState,'needs-action');assert(out.escapedSnooze);assert.equal(out.title,text);
  const review=attention.projectAttentionThread({conversation:{conversationId:'owned',title:text,status:'completed'},now}); assert.equal(review.attentionState,'ready-for-review');
});
await check('attention.inbox',[...textual,'stale'],()=>{
  const out=attention.buildAttentionInbox({conversations,now}); assert.equal(out.threads.length,count); assert.equal(new Set(out.threads.map(t=>t.threadId)).size,count);assert.equal(out.counts['ready-for-review'],Math.ceil(count/2));
  if(category==='stale'){const aged=attention.buildAttentionInbox({missions:[{missionId:'old',status:'completed',updatedAt:'2020-01-01T00:00:00Z'}],now});assert.equal(aged.threads.length,0);}
});
await check('attention.projects',textual,()=>{const threads=attention.buildAttentionInbox({conversations,now}).threads;const groups=attention.groupThreadsByProject(threads);assert.equal(groups.flatMap(g=>g.threads).length,count);if(count)assert.equal(groups[0].id,text||'owned');});
await check('attention.sections',textual,()=>{const threads=attention.buildAttentionInbox({conversations,now}).threads;const groups=attention.projectAttentionSections(threads,{now,timeZone:'Europe/Paris'});assert.equal(groups.flatMap(g=>g.threads).length,count);});
await check('attention.filter',textual,()=>{const inbox=attention.buildAttentionInbox({conversations,now});const groups=attention.filterInboxGroups(inbox,'review');assert(groups.flatMap(g=>g.threads).every(t=>t.attentionState==='ready-for-review'));assert.equal(groups.flatMap(g=>g.threads).length,Math.ceil(count/2));});
await check('attention.description',textual,()=>{const thread=attention.projectAttentionThread({conversation:{conversationId:'owned',title:text,hasBlockingApproval:category!=='empty'},now});assert.equal(typeof attention.attentionThreadDescription(thread),'string');});
await check('attention.activity',['empty','stale'],()=>{assert.equal(attention.attentionActivityTier('',now),'unknown');assert.notEqual(attention.attentionActivityTier('2020-01-01T00:00:00Z',now),attention.attentionActivityTier('2026-10-04T11:59:00Z',now));});
await check('attention.recent',['stale','unicode'],()=>{const a=attention.projectAttentionThread({conversation:{conversationId:'a',title:text,lastMeaningfulActivityAt:'2020-01-01T00:00:00Z'},now});const b=attention.projectAttentionThread({conversation:{conversationId:'b',title:text,lastMeaningfulActivityAt:'2026-10-04T11:59:00Z'},now});assert(attention.compareRecentThreads(a,b)>0);});
let store=mission.mergeMissionSummaries(mission.createMissionProjectionStore(),[{missionId:'owned',title:text,status:'running'}]);
const events=Array.from({length:count},(_,i)=>({eventId:'e-'+i,timestamp:new Date(now+i*1000).toISOString(),message:text,kind:'owned.output'}));
await check('mission.delta',[...textual,'stale'],()=>{
  let next=mission.applyMissionEventDelta(store,'owned',events,'cursor');next=mission.applyMissionEventDelta(next,'owned',events,'cursor');assert.equal(next.missions.owned.events.length,Math.min(count,600));assert.equal(new Set(next.missions.owned.events.map(e=>e.eventId)).size,Math.min(count,600));
  if(category==='stale'){next=mission.applyMissionEventDelta(next,'owned',[{eventId:'rotated',message:text}],'new',{reset:true});assert.deepEqual(next.missions.owned.events.map(e=>e.eventId),['rotated']);}
});
await check('mission.artifacts',textual,()=>{
  const items=Array.from({length:count},(_,i)=>({artifactId:'a-'+i,path:'owned/'+i,label:text,content:'UNEXPECTED_BYTES'}));let next=mission.mergeMissionArtifacts(store,'owned',items);next=mission.mergeMissionArtifacts(next,'owned',items);assert.equal(next.missions.owned.artifacts.length,count);assert(!JSON.stringify(next.missions.owned.artifacts).includes('UNEXPECTED_BYTES'));
});
await check('mission.live',[...textual,'stale'],()=>{
  const view=mission.projectAgentLiveView(store,'owned');assert.equal(view.live,true);assert.equal(view.title,text||'owned');
  const stopped=mission.mergeMissionSummaries(store,[{missionId:'owned',title:text,status:'queued'}]);assert.equal(mission.projectAgentLiveView(stopped,'owned').live,false);
});
console.log(JSON.stringify(rows));
'''


def _frontend(root, contracts, categories):
    script = root / "generated-state-fixtures.mjs"
    script.write_text(NODE_PROGRAM, encoding="utf-8")
    rows = []
    repo = Path(__file__).resolve().parents[2]
    for category in categories:
        result = subprocess.run(["node", str(script), str(repo), category], capture_output=True, text=True, encoding="utf-8", timeout=90, **hidden_windows_subprocess_kwargs())
        if result.returncode:
            rows.append({"id": f"missions:frontend-worker:{category}", "category": category, "contracts": [], "status": "failed", "detail": {"stderr": result.stderr[-2000:]}, "boundary": "owned node worker imports production modules"})
        else:
            rows.extend({**row, "contracts": [identity for identity in row["contracts"] if identity in contracts]} for row in json.loads(result.stdout))
    return rows


def run(root, contracts, categories):
    from .proof_credential_guard import install
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    install(root)
    rows = []
    for family, (builder, identities, supported) in FAMILIES.items():
        if not identities.intersection(contracts):
            continue
        for category in categories:
            if category not in supported:
                continue
            target = root / f"{family}-{category}-{uuid.uuid4().hex[:8]}"
            target.mkdir()
            row = {"id": f"missions:{family}:{category}", "category": category, "boundary": "actual production mission owner with persisted byte/event/process observations", "scratchRoot": str(target)}
            try:
                result = builder(target, category)
                row.update(status="passed", **result)
            except Exception as error:
                row.update(status="failed", contracts=sorted(identities), detail={"type": type(error).__name__, "error": str(error), **getattr(error, "fixture_effects", {})})
            row["contracts"] = [identity for identity in row["contracts"] if identity in contracts]
            rows.append(row)
    rows.extend(_frontend(root, contracts, categories))
    return rows


def blocker(contract, category):
    identity = contract["id"]
    for family, (_, identities, supported) in FAMILIES.items():
        if identity not in identities:
            continue
        if category in supported:
            return None
        if category == "offline":
            return {"kind": "not_applicable", "reason": f"Audited {identity} {family} owner operates on local state or pure phase data; it has no transport/connectivity argument. External runtime launch is governed by separate contracts."}
        if family in {"handoffs", "lifecycle"} and category in {"permissions", "interrupted", "concurrency"}:
            return {"kind": "not_applicable", "reason": f"Audited {identity} computes or mutates one caller-owned in-memory phase capsule; it has no grant, asynchronous worker or shared persistence boundary. State writer interruption is exercised separately."}
        if family == "platform":
            return {"kind": "not_applicable", "reason": "Audited _platform_path_for_windows_drive parses supplied path text and an explicit platform flag without file access, grants, workers, network or mutable revisions. Empty drive tails, 1000 segments and Unicode paths independently exercise both parser branches; no WSL command is run."}
        if family == "readiness" and category == "interrupted":
            return {"kind": "not_applicable", "reason": "Audited _public_launch_readiness_digest synchronously reads a saved receipt and projects current timestamps/blockers; it launches no worker and owns no publication transaction to interrupt. Actual OS-denied receipt reads fall back to supplied evidence or missing; no receipt is rendered proof or publication."}
        return {"kind": "fixture_gap", "reason": f"Actual {category} {family} effect builder for {identity} remains to implement; normal writes or another family do not prove it."}
    node_identities = {
        "composer." + name for name in ("stripDataUrl", "base64Chars", "admitImages", "planImageReads", "imageBlocker", "sendIdentity", "parseArguments", "argumentSkeleton", "filterTools", "toolMutates", "toolScope", "draftUpdate", "attachResult")
    } | {"autopilot." + name for name in ("scopeTools", "scopeOf", "attributeCalls", "shapeRun", "checkLine")} | {"attention." + name for name in ("thread", "inbox", "projects", "sections", "filter", "description", "activity", "recent")} | {"mission." + name for name in ("delta", "artifacts", "live")}
    if identity in node_identities:
        if category == "offline":
            return {"kind": "not_applicable", "reason": f"Audited {identity} is a local frontend computation or draft read admission; it has no backend/provider transport. A disconnected fetch adapter is a different contract."}
        if category in {"permissions", "interrupted", "concurrency"} and identity not in {"composer.attachResult", "composer.draftUpdate", "composer.imageBlocker", "composer.toolMutates", "autopilot.scopeTools", "autopilot.scopeOf", "attention.thread"}:
            return {"kind": "not_applicable", "reason": f"Audited {identity} is a synchronous pure frontend transform without OS authority, asynchronous interruption or shared mutation; those categories cannot change its feature state."}
        return {"kind": "fixture_gap", "reason": f"Exact {identity}/{category} production state transform needs an additional generated perturbation; another model function is not coverage."}
    return None


if __name__ == "__main__":
    from .edge_contracts import inventory
    started = time.monotonic()
    _, contracts = inventory()
    rows = run(Path(sys.argv[1]), contracts, ["empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale"])
    report = {"schema": "neyvia.c7b.mission-fixtures.v1", "ok": all(row["status"] == "passed" for row in rows), "rows": rows,
              "passedPairs": len({(identity, row["category"]) for row in rows if row["status"] == "passed" for identity in row["contracts"]}), "durationMs": round((time.monotonic() - started) * 1000)}
    Path(sys.argv[2]).write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}))
    sys.exit(0 if report["ok"] else 1)
