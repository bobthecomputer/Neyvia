"""Mission contracts enforced by production boundaries and replayed in scratch.

The startup journey exercises receipt persistence, context handoffs, phase
control and a real local Python output producer. It does not execute a model,
external runtime, network call or supervisor.
"""
from __future__ import annotations

import json
import tempfile
import time
import inspect
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, fields, MISSING
from datetime import datetime
from pathlib import Path

CONTRACTS = (
    "proofs-c.missions.receipt-schema", "proofs-c.missions.receipt-durable",
    "proofs-c.missions.receipt-filter", "proofs-c.missions.default-isolation",
    "proofs-c.missions.artifact-layout", "proofs-c.missions.executor-boundary",
    "proofs-c.missions.verifier-boundary", "proofs-c.missions.skill-relevance",
    "proofs-c.missions.run-envelope", "proofs-c.missions.phase-transition",
    "proofs-c.missions.acceptance-receipt", "proofs-c.missions.continuity-durable",
    "proofs-c.missions.gpu-policy", "proofs-c.missions.security-scope",
    "proofs-c.missions.security-coverage", "proofs-c.missions.turn-mode",
    "proofs-c.missions.control-durable", "proofs-c.missions.orchestration-durable",
    "proofs-c.missions.security-route",
    "proofs-c.missions.local-dialogue", "proofs-c.missions.local-transcript",
    "proofs-c.missions.local-messages", "proofs-c.missions.local-read-model",
    "proofs-c.missions.local-flight", "proofs-c.missions.local-artifact-gate",
    "proofs-c.missions.local-artifact-repair", "proofs-c.missions.local-public-launch",
    "proofs-c.missions.local-storage",
    "proofs-c.missions.local-platform",
)


def require(condition, identity, message):
    if not condition:
        raise ValueError(f"Contract {identity}: {message}")


def check_default_factories(model):
    """Mutable factory results must be independent; no process-global instances."""
    for field in fields(model):
        if field.default_factory is MISSING:
            require(not isinstance(field.default, (list, dict, set)), CONTRACTS[3], "mutable class default")
            continue
        first, second = field.default_factory(), field.default_factory()
        if isinstance(first, (list, dict, set)):
            require(first is not second and first == second, CONTRACTS[3], "factory shares mutable state")


def check_receipt(payload, receipt_type):
    from .models import VERIFICATION_RECEIPT_DECISIONS
    defaults = {field.name: field.default for field in fields(receipt_type)}
    require(payload["schema"] == defaults["schema"] and payload["phase"] == defaults["phase"],
            CONTRACTS[0], "receipt schema and producer phase disagree")
    datetime.fromisoformat(payload["generated_at"])
    require(VERIFICATION_RECEIPT_DECISIONS == ("accepted", "repair_needed", "blocked", "operator_needed"),
            CONTRACTS[0], "verification decision vocabulary changed")
    check_default_factories(receipt_type)


def check_receipt_write(path, expected_lines, payload, maximum):
    expected = [line for line in expected_lines if line.strip()][-max(1, int(maximum or 1)):]
    actual = path.read_text(encoding="utf-8").splitlines()
    require(actual == expected and json.loads(actual[-1]) == payload,
            CONTRACTS[1], "durable receipt stream differs from serialized append/retention")


def check_receipt_read(rows, mission_id, limit):
    require(len(rows) <= max(1, int(limit or 1)) and
            (not mission_id or all(row["mission_id"] == mission_id for row in rows)),
            CONTRACTS[2], "mission filtering or tail bound violated")


def check_layout(layout, workspace, create):
    from .mission_artifacts import MISSION_RUN_ARTIFACT_DIRS, MISSION_RUN_ARTIFACT_LAYOUT_SCHEMA
    expected = Path(workspace).expanduser().resolve() / ".agent_control/mission_runs" / layout.mission_id
    require(layout.schema == MISSION_RUN_ARTIFACT_LAYOUT_SCHEMA and Path(layout.root) == expected,
            CONTRACTS[4], "artifact tree escaped its canonical mission root")
    expected_fields = {f"{name}_dir": expected / name for name in MISSION_RUN_ARTIFACT_DIRS}
    expected_fields.update(receipts_jsonl=expected / "receipts/mission_receipts.jsonl",
                           event_stream_jsonl=expected / "events/events.jsonl",
                           final_report_json=expected / "reports/final_report.json")
    require(all(Path(getattr(layout, field)) == path for field, path in expected_fields.items()),
            CONTRACTS[4], "artifact payload path differs from layout")
    if create:
        require(all((expected / name).is_dir() for name in MISSION_RUN_ARTIFACT_DIRS),
                CONTRACTS[4], "requested artifact directories are missing")


def check_capsule(capsule):
    from .mission_phase_inputs import EXECUTOR_PHASE_INPUT_SCHEMA, VERIFIER_PHASE_INPUT_SCHEMA
    plan = capsule.plan_receipt
    identity = CONTRACTS[5] if capsule.schema == EXECUTOR_PHASE_INPUT_SCHEMA else CONTRACTS[6]
    require(capsule.schema in {EXECUTOR_PHASE_INPUT_SCHEMA, VERIFIER_PHASE_INPUT_SCHEMA}, identity, "unknown capsule")
    require(len(capsule.original_goal) <= 1000 and plan["schema"] == "fluxio.plan_receipt.v1", identity, "wrong plan or goal limit")
    excluded = {"inputs", "outputs", "metadata", "skill_brief", "fullMissionHistory", "rawDocs"}
    require(not excluded.intersection(plan), identity, "planner-only context leaked")
    bounds = {"file_scope": (80, 240), "selected_skills": (24, 120), "forbidden_paths": (40, 240),
              "assumptions": (4, 180), "expected_artifacts": (40, 240), "verification_ladder": (12, 180)}
    for key, (count, length) in bounds.items():
        require(len(plan[key]) <= count and all(isinstance(item, str) and len(item) <= length for item in plan[key]), identity, f"{key} cap violated")
    require(len(plan["tasks"]) <= 40 and all(len(item["title"]) <= 160 for item in plan["tasks"]), identity, "task cap violated")
    if capsule.schema == EXECUTOR_PHASE_INPUT_SCHEMA:
        require(capsule.file_scope == plan["file_scope"] and capsule.selected_skills == plan["selected_skills"], identity, "selected IDs or scope differ from compact plan")
    else:
        execution = capsule.execution_receipt
        require(execution["schema"] == "fluxio.execution_receipt.v1" and not excluded.intersection(execution), identity, "wrong execution or runtime transcript leaked")
        require(len(capsule.changed_files) <= 80 and len(capsule.proof_artifacts) <= 40 and
                len(set(capsule.changed_files)) == len(capsule.changed_files) and
                len(set(capsule.proof_artifacts)) == len(capsule.proof_artifacts), identity, "artifact/scope deduplication or cap violated")


def check_relevance(result):
    checks = result["checks"]
    count = sum(not item["relevant"] for item in checks)
    status = "blocked" if not checks else "review" if count else "passed"
    require(result["selectedSkillCount"] == len(checks) and result["irrelevantSkillCount"] == count and result["status"] == status,
            CONTRACTS[7], "selected skill status/counts conceal empty or irrelevant selection")


def check_run(run):
    from .models import MISSION_RUN_PHASES, MISSION_RUN_STATUSES, MISSION_RUN_TERMINAL_STATUSES
    require(MISSION_RUN_PHASES == ("preflight", "planner", "executor", "verifier", "repair", "final_report") and
            MISSION_RUN_TERMINAL_STATUSES == ("blocked", "failed", "completed", "cancelled") and
            {"queued", "repair_needed"} <= set(MISSION_RUN_STATUSES), CONTRACTS[8], "lifecycle vocabulary changed")
    require(run.schema_version == "fluxio.mission_run.v1" and run.current_phase in MISSION_RUN_PHASES and run.status in MISSION_RUN_STATUSES,
            CONTRACTS[8], "run envelope has unknown schema/phase/status")
    datetime.fromisoformat(run.created_at)
    datetime.fromisoformat(run.updated_at)
    check_default_factories(type(run))


def check_transition(run, previous, outcome, transition):
    check_run(run)
    identity = CONTRACTS[9]
    phase, previous_count = previous
    expected = {"preflight": "planner", "planner": "executor", "executor": "verifier",
                "verifier": "final_report", "repair": "verifier", "final_report": "final_report"}
    if outcome in {"failed", "blocked", "operator_needed"}:
        wanted_phase, wanted_status = phase, "failed" if outcome == "failed" else "blocked"
    elif phase == "verifier" and outcome == "repair_needed":
        exhausted = run.metadata.get("repair_loop_limit_exhausted") is True
        wanted_phase, wanted_status = (phase, "blocked") if exhausted else ("repair", "repair_needed")
        require(int(run.metadata["repair_loop_count"]) == previous_count + int(not exhausted), identity, "repair counter changed unexpectedly")
    else:
        wanted_phase, wanted_status = expected[phase], "completed" if phase == "final_report" else "running"
    require(run.current_phase == wanted_phase and run.status == wanted_status and
            transition.from_phase == phase and transition.to_phase == wanted_phase and transition.run_status == wanted_status,
            identity, "phase successor/status differs from accepted outcome")
    require(transition.terminal == (wanted_status in {"blocked", "failed", "completed", "cancelled"}) and
            (not transition.terminal or bool(run.completed_at)), identity, "terminal receipt lacks completion timestamp")
    require(len({state.phase for state in run.phases}) == len(run.phases), identity, "duplicate phase states")


def check_acceptance(payload, path):
    journeys = payload["journeys"]
    require(payload["simulated"] is True and all(payload[key] is False for key in
            ("networkUsed", "paidComputeUsed", "externalAccountsUsed")), CONTRACTS[10], "local harness asserted external execution")
    passed = sum(bool(row["ok"]) for row in journeys)
    require(len(journeys) == 5 and payload["ok"] == (passed == len(journeys)) and
            payload["summary"] == {"passed": passed, "total": len(journeys), "failed": [row["id"] for row in journeys if not row["ok"]]} and
            json.loads(Path(path).read_text(encoding="utf-8")) == payload,
            CONTRACTS[10], "acceptance summary or durable receipt differs from inspected journeys")


def check_continuity_write(path, record, previous, revision):
    require(record["revision"] == revision + 1 and json.loads(Path(path).read_text(encoding="utf-8")) == record,
            CONTRACTS[11], "continuity revision/state was lost under lock")
    if previous is not None:
        previous_path = Path(path).with_name(Path(path).stem + ".previous.json")
        require(json.loads(previous_path.read_text(encoding="utf-8")) == previous, CONTRACTS[11], "previous safe snapshot lost")


def check_continuity_recovery(restored, previous):
    require({key: value for key, value in restored.items() if key != "recovery"} ==
            {key: value for key, value in previous.items() if key != "recovery"} and
            restored["recovery"]["status"] == "restored_from_previous_snapshot", CONTRACTS[11], "recovery lost previous valid facts")


def check_gpu(result, proposal, observed):
    policy = result["policy"]
    release = []
    if observed.get("runningInstances") and float(observed.get("runningDurationMinutes") or 0) >= float(policy["maxDurationMinutes"]):
        release.append("duration_limit")
    if observed.get("runningInstances") and float(observed.get("idleMinutes") or 0) >= float(policy["idleReleaseMinutes"]):
        release.append("idle_limit")
    require(result["releaseReasons"] == release and result["releaseRequired"] == bool(release) and result["allowed"] == (not result["blockers"]), CONTRACTS[12], "GPU release/cost blockers concealed")
    cost = proposal.get("estimatedHourlyCost")
    duration = float(proposal.get("estimatedDurationMinutes") or policy.get("maxDurationMinutes") or 0)
    require(result["estimatedSessionCost"] == (float(cost) * duration / 60 if cost is not None and duration > 0 else None), CONTRACTS[12], "GPU session cost differs from bounded proposal")


def check_security(result):
    scope = result["scope"]
    active = result["active"]
    require(result["allowed"] == (result["scopeAllowed"] and result["approvalSatisfied"]) and
            result["scopeAllowed"] == (not result["blockers"]) and 1 <= result["maxProbeAttempts"] <= 50,
            CONTRACTS[13], "security authorization/approval/budget decision disagrees")
    if result["allowed"] and active:
        require(scope["mode"] == "active" and scope["authorizedBy"] and scope["authorizationConfirmed"] and
                result["actionClass"] in scope["allowedActionClasses"] and result["target"] in scope["allowedTargets"] and
                result["target"] not in scope["excludedTargets"], CONTRACTS[13], "active action escaped explicit authorization")


def check_security_plan(result):
    require([row["owner"] for row in result["phases"]] == ["auditor", "red", "blue", "defender", "auditor"] and
            result["ready"] == result["scope"]["valid"], CONTRACTS[13], "purple team phase separation or authorization lost")


def check_security_coverage(result):
    missing = [row["phase"] for row in result["phases"] if not row["matchedTools"]]
    require(result["missingPhases"] == missing and result["ready"] == (not missing) and
            all(row["ready"] == bool(row["matchedTools"]) for row in result["phases"]), CONTRACTS[14], "coverage concealed unavailable security phases")
    unavailable = {row["id"] for row in result["unavailableCandidates"]}
    require(not any(unavailable.intersection(row["matchedTools"]) for row in result["phases"]), CONTRACTS[14], "unavailable candidate counted as executable")


def check_turn_mode(result, objective, checks, overrides, mode):
    from .mission_control import PLAN_TURN_MODE_DIRECTIVE, PLAN_TURN_MODE_SUCCESS_CHECK
    resolved = result["turnMode"]
    require(resolved in {"standard", "plan", "fast", "max-context"}, CONTRACTS[15], "unknown turn mode")
    if resolved == "plan":
        require(PLAN_TURN_MODE_DIRECTIVE in result["objective"] and objective in result["objective"] and
                PLAN_TURN_MODE_SUCCESS_CHECK in result["successChecks"] and all(str(row) in result["successChecks"] for row in checks or []), CONTRACTS[15], "plan launch lost original goal/checks or plan gate")
    elif resolved in {"fast", "max-context"}:
        effort = "low" if resolved == "fast" else "high"
        require(all(row["effort"] == effort for row in result["routeOverrides"]) and
                (result["budgetHours"] is None or (result["budgetHours"] <= 1 if resolved == "fast" else result["budgetHours"] >= 8)) and
                (resolved != "max-context" or result["mode"] == "Deep Run"), CONTRACTS[15], "turn mode effort/budget not applied")
    else:
        require(result["objective"] == str(objective or "") and result["successChecks"] == [str(row) for row in checks or []] and
                result["routeOverrides"] == [dict(row) for row in overrides or [] if isinstance(row, dict)] and result["mode"] == str(mode or "Autopilot"), CONTRACTS[15], "standard mode changed launch semantics")


def check_control_write(path, payload):
    require(json.loads(Path(path).read_text(encoding="utf-8")) == json.loads(json.dumps(payload)), CONTRACTS[16], "control-room write differs from durable payload")


def check_orchestration(store, mission, receipt):
    saved = store.get_mission(mission.mission_id)
    keys = {"parallelAgents": "parallel_agents", "observationCount": "observation_count", "mergePolicy": "merge_policy", "crossMissionAwareness": "cross_mission_awareness"}
    require(saved is not None and all(receipt[key] == getattr(saved.state, field) == saved.state.runtime_autonomy[key] for key, field in keys.items()), CONTRACTS[17], "orchestration receipt differs from stored mission policy")


def check_security_route(profile):
    expected = {"security_red_team": "adversarial_verification_execution", "security_blue_team": "defensive_detection_execution"}
    task = profile["taskType"]
    if task in expected:
        require(profile["routeIntent"] == expected[task] and profile["matchCount"] >= 1 and
                bool(profile["matchedKeywords"]), CONTRACTS[18], "security task routed to wrong mission intent")


def checked_local_mission(kind):
    """Observe the existing result at its common helper boundary, without collectors."""
    def decorate(action):
        signature = inspect.signature(action)
        @wraps(action)
        def invoke(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            values = bound.arguments
            mission = values.get("mission")
            before = asdict(mission) if mission is not None and kind == "repair" else None
            root = values.get("root")
            durable = Path(root) / ".agent_control/missions.json" if root is not None else None
            original = durable.read_bytes() if durable is not None and durable.is_file() else None
            result = action(*args, **kwargs)
            check_local_projection(kind, values, result, before)
            if kind in {"read-model", "transcript", "dialogue", "messages"} and original is not None:
                require(durable.read_bytes() == original, CONTRACTS[22], "observation mutated persisted mission state")
            return result
        return invoke
    return decorate


def check_local_projection(kind, values, result, before=None):
    from . import mission_control as mc
    mission = values.get("mission")
    if kind == "dialogue":
        identity = CONTRACTS[19]
        evidence = set()
        for session in mission.delegated_runtime_sessions or []:
            if str(getattr(session, "status", "")).lower() not in {"running", "completed"}:
                continue
            for event in mc._delegated_runtime_event_rows(session, limit=max(values["limit"] * 6, 30)):
                meta = mc._runtime_event_metadata(event)
                event_kind = str(event.get("kind") or "").lower()
                source = str(meta.get("sourceKind") or meta.get("source_kind") or "").lower()
                text = str(event.get("message") or event.get("detail") or "").strip()
                if len(text) >= 80 and (event_kind in mc.DELEGATED_TRANSCRIPT_RUNTIME_KINDS or event_kind.endswith(".output") or source == "real-runtime-output"):
                    evidence.add(text)
        for turn in result:
            if turn["sourceKind"] == "mission-runtime-output-file":
                evidence.add(mc._read_gate_text(Path(turn["sourcePath"]), max_chars=1600).strip())
            require(turn["text"] in evidence and turn["captureMode"] and turn["runtimeId"], identity, "dialogue invented text or lost capture provenance")
        require(len(result) <= max(values["limit"], 0) and len({turn["text"][:400] for turn in result}) == len(result), identity, "dialogue duplicate/limit violation")
    elif kind == "transcript":
        identity = CONTRACTS[20]
        messages = result["messages"]
        require(result["messageCount"] == len(messages) and len(messages) <= values["limit"], identity, "transcript count/limit mismatch")
        if result["status"] == "attached":
            require(messages and (any(row.get("runtimeOutput") for row in messages) or
                    mc._runtime_transcript_artifact_evidence_items(runtime_transcript=result)), identity, "bookkeeping rows promoted to runtime output")
            require(not set(result.get("nonConcreteSessionIds", [])).intersection(row["sessionId"] for row in messages), identity, "rejected session reattached")
            latest = mission.state.latest_session_id
            if latest and result["sessionId"] != latest:
                require(latest in result.get("missingSessionIds", []) or latest in result.get("nonConcreteSessionIds", []) or
                        latest not in result["candidateSessionIds"], identity, "latest concrete session was bypassed")
        else:
            require(not messages and result["sessionId"] == "", identity, "missing transcript falsely attached messages")
    elif kind == "messages":
        identity = CONTRACTS[21]
        require(len(result) <= values["limit"], identity, "message projection exceeded limit")
        for message in result:
            if message.get("conversationTurn"):
                require(message["role"] in {"assistant", "operator"} and message["messageKind"] == "dialogue" and
                        (message["role"] == "operator" or message.get("turnReceipt")), identity, "dialogue lost provenance/role")
            if message.get("label") in {"Control-room action result", "Control-room planner", "Runtime heartbeat", "Runtime transcript integrity", "Control-room mission state"}:
                require(message["traceOnly"] and not message["chatPreferred"], identity, "bookkeeping promoted to chat")
    elif kind == "read-model":
        identity = CONTRACTS[22]
        require(result["missionId"] == mission.mission_id and result["workspaceId"] == mission.workspace_id and result["objective"] == mission.objective and
                result["migrationRequired"] is False, identity, "read model changed original mission identity")
        require(result["receiptCount"] == len(result["receipts"]) and all(row["mission_id"] == mission.mission_id for row in result["receipts"]) and
                result["latestReceipt"] == (result["receipts"][-1] if result["receipts"] else {}), identity, "read model receipt filter/order mismatch")
        if not result["snapshotPresent"]:
            require(result["source"] == "legacy_missions_json" and result["missionRunId"] == f"legacy_{mission.mission_id}" and
                    result["status"] == (mission.state.status or "draft") and result["currentPhase"] == (mission.state.current_cycle_phase or "preflight"), identity, "legacy lifecycle was invented")
    elif kind == "flight":
        identity = CONTRACTS[23]
        source = values["snapshot"]
        valid = isinstance(source, dict) and source.get("schema") == "fluxio.mission_flight_recorder_snapshot.v1"
        require(result["present"] == valid, identity, "invalid flight snapshot reported present")
        if valid:
            require(result["events"] == (source.get("events") or [])[-20:] and result["processIds"] == list(source.get("processIds") or [])[:20] and
                    result["currentPhase"] == str(source.get("currentPhase") or "") and result["eventCount"] == int(source.get("eventCount") or len(source.get("events") or [])), identity, "flight projection lost actual process/phase/events")
        else:
            require(result["eventCount"] == 0 and result["events"] == [], identity, "missing flight snapshot invented events")
    elif kind == "gate":
        identity = CONTRACTS[24]
        passed = bool(result["runtimeOutputCount"] and result["artifactCount"])
        require(result["passed"] == passed and result["status"] == ("passed" if passed else "missing_required_output") and
                result["failure"] == ("" if passed else mc.HARD_ARTIFACT_GATE_FAILURE), identity, "artifact-only or runtime-only evidence claimed goal completion")
    elif kind == "repair":
        identity = CONTRACTS[25]
        if result is True:
            require(mission.state.status == "completed" and mission.state.planner_loop_status == "completed" and
                    mission.state.last_verification_result == "passed" and not mission.state.verification_failures and not mission.proof.failed_checks,
                    identity, "artifact repair erased unrelated failures or failed to finish")
        elif result is False:
            require(asdict(mission) == before, identity, "rejected repair mutated mission state")
    elif kind == "public":
        identity = CONTRACTS[26]
        latest = mc._load_json_file(Path(values["root"]) / ".agent_control/public_launch_readiness/latest.json")
        latest = latest if isinstance(latest, dict) else {}
        source = values["source"]
        chosen = source if isinstance(source, dict) else latest
        if isinstance(source, dict) and latest.get("schema") == "fluxio.public_launch_readiness.v1":
            source_at = mc._parse_iso_datetime(str(source.get("checkedAt") or ""))
            latest_at = mc._parse_iso_datetime(str(latest.get("checkedAt") or ""))
            if latest_at and (not source_at or latest_at >= source_at):
                chosen = latest
        if chosen.get("schema") != "fluxio.public_launch_readiness.v1":
            require(result["status"] == "missing" and not result["ok"], identity, "missing publication receipt reported launch ready")
        else:
            require(result["status"] == str(chosen.get("status") or "unknown") and result["ok"] == bool(chosen.get("ok")) and
                    result["internalPacketReady"] == bool(chosen.get("internalPacketReady")), identity, "public launch status used stale evidence")
            for key in ("repairPacket", "publicWeb", "publicationProof", "stagingProof", "releaseCandidate"):
                require(result[key] == (chosen.get(key, {}) if isinstance(chosen.get(key, {}), dict) else {}), identity, "operator receipt fields were dropped")
    elif kind == "storage":
        identity = CONTRACTS[27]
        if result:
            require(result["code"] == "nas_storage_pressure_block" and result["storage"]["measuredUsageAvailable"], identity, "storage blocked without measured capacity")


def check_platform_path(raw, posix, result):
    import os
    import re
    value = str(raw or "").strip().strip('"').strip("'")
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", value)
    if match and (os.name != "nt" if posix is None else posix):
        drive, tail = match.groups()
        expected = "/mnt/" + drive.lower() + "/" + tail.replace("\\", "/").lstrip("/")
        require(result.as_posix() == Path(expected).as_posix(), CONTRACTS[28], "Windows drive conversion changed drive/tail")
    else:
        require(result == Path(value), CONTRACTS[28], "native/relative path changed during conversion")


def self_check(root):
    from . import models as m
    from .mission_artifacts import build_mission_run_artifact_layout, mission_run_artifact_root, mission_run_artifact_layout_payload
    from .mission_receipts import append_mission_receipt, load_mission_receipts, mission_receipts_path, validate_mission_receipt, ReceiptValidationError
    from .mission_phase_inputs import build_executor_phase_input, build_verifier_phase_input, check_selected_skill_relevance
    from .mission_phase_runner import start_current_phase, complete_current_phase, MissionPhaseTransitionError
    from .planner import build_docs_first_plan_receipt
    started = time.perf_counter()
    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="missions-", dir=base))
    cases = []

    def run(identity, contract, action):
        from .contract_gate import wants
        if not wants(contract):
            return
        try:
            action()
            cases.append({"id": identity, "contracts": contract, "ok": True})
        except Exception as error:
            cases.append({"id": identity, "contracts": contract, "ok": False, "error": str(error)})

    def rejects(action, error=ValueError):
        try:
            action()
        except error:
            return
        raise ValueError("Invalid action was accepted")

    def receipt(index, mission="proof", model=m.ExecutionReceipt, **extra):
        return model(receipt_id=f"receipt-{index}", mission_id=mission, host="scratch", runtime="manual-self-check",
                     workspace=str(scratch), status="completed", summary=f"Scratch receipt {index}", **extra)

    layout = build_mission_run_artifact_layout(scratch, "proof")
    def artifact_layout():
        check_layout(layout, scratch, True)
    def readonly_layout():
        parent = scratch / "readonly"
        payload = mission_run_artifact_layout_payload(parent, "proof", create=False)
        require(not parent.exists() and payload["schema"] == "fluxio.mission_run_artifact_layout.v1", CONTRACTS[4], "read-only layout created state")
    def confined_layout():
        for identity in ("../escape", "nested/id", "", "..", "C:/escape", "\\escape"):
            rejects(lambda identity=identity: mission_run_artifact_root(scratch, identity))
    def artifact_receipt():
        final = receipt("final", model=m.FinalProofReceipt, final_mission_status="completed")
        append_mission_receipt(Path(layout.receipts_jsonl), final)
        require(load_mission_receipts(Path(layout.receipts_jsonl), mission_id="proof") == [asdict(final)], CONTRACTS[1], "layout receipt did not roundtrip")
    run("test_build_layout_creates_one_mission_run_artifact_tree", [CONTRACTS[4]], artifact_layout)
    run("test_layout_payload_can_be_built_without_creating_directories", [CONTRACTS[4]], readonly_layout)
    run("test_layout_rejects_path_traversal_mission_ids", [CONTRACTS[4]], confined_layout)
    run("test_receipt_store_can_write_to_layout_receipt_path", [CONTRACTS[1], CONTRACTS[4]], artifact_receipt)

    def concurrent_receipts():
        target = scratch / "concurrent"
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda index: append_mission_receipt(target, receipt(index), max_receipts=50), range(24)))
        rows = load_mission_receipts(target, limit=50)
        require({row["receipt_id"] for row in rows} == {f"receipt-{index}" for index in range(24)} and len(rows) == 24, CONTRACTS[1], "concurrent append lost receipts")
    def retention():
        target = scratch / "retention"
        for index in range(4):
            append_mission_receipt(target, receipt(index, changed_files=[f"file-{index}.py"]), max_receipts=3)
        rows = load_mission_receipts(target, limit=10)
        require([row["receipt_id"] for row in rows] == ["receipt-1", "receipt-2", "receipt-3"] and rows[-1]["changed_files"] == ["file-3.py"], CONTRACTS[1], "oldest receipt retained or fields lost")
    def filtered():
        target = scratch / "filtered"
        path = mission_receipts_path(target)
        path.write_text("{broken}\n[]\n", encoding="utf-8")
        for index in range(5):
            append_mission_receipt(target, receipt(index, "target", m.PlanReceipt, goal_restatement="Goal"))
            append_mission_receipt(target, receipt(f"other-{index}", "other", m.PlanReceipt, goal_restatement="Other"))
        rows = load_mission_receipts(target, limit=3, mission_id="target")
        require([row["receipt_id"] for row in rows] == ["receipt-2", "receipt-3", "receipt-4"], CONTRACTS[2], "filtered limit excludes current target receipts")
    def invalid_schema():
        valid = validate_mission_receipt(receipt("verify", model=m.VerificationReceipt, decision="accepted"))
        rejects(lambda: validate_mission_receipt({**valid, "schema": "unknown"}), ReceiptValidationError)
        rejects(lambda: validate_mission_receipt({**valid, "decision": "maybe"}), ReceiptValidationError)
    def invalid_preserves():
        target = scratch / "invalid"
        rejects(lambda: append_mission_receipt(target, {"schema": "fluxio.execution_receipt.v1", "receipt_id": "bad"}), ReceiptValidationError)
        require(not mission_receipts_path(target).exists(), CONTRACTS[1], "invalid receipt wrote a fake stream")
    run("test_concurrent_appends_preserve_every_receipt", [CONTRACTS[1]], concurrent_receipts)
    run("test_append_and_load_valid_receipts_with_bounded_retention", [CONTRACTS[1]], retention)
    run("test_load_filters_by_mission_before_limit_and_skips_bad_rows", [CONTRACTS[0], CONTRACTS[2]], filtered)
    run("test_validate_rejects_unknown_schema_and_bad_verification_decision", [CONTRACTS[0]], invalid_schema)
    run("test_append_rejects_incomplete_payload_without_writing_fake_receipt", [CONTRACTS[0], CONTRACTS[1]], invalid_preserves)

    def schemas():
        types = [(m.NightReadinessReceipt, {}, "preflight"), (m.PlanReceipt, {"goal_restatement": "Goal"}, "planner"),
                 (m.ExecutionReceipt, {}, "executor"), (m.VerificationReceipt, {"decision": "accepted"}, "verifier"),
                 (m.RepairReceipt, {}, "repair"), (m.FinalProofReceipt, {"final_mission_status": "completed",
                  "receipts_produced": [m.MissionRunReceiptRef("verification", "verification", "accepted")]}, "final_report")]
        for model, extra, phase in types:
            value = receipt(phase, model=model, **extra)
            payload = append_mission_receipt(scratch / "schemas", value)
            require(payload == asdict(value) and payload["phase"] == phase, CONTRACTS[0], "phase receipt serialization lost fields")
    def default_isolation():
        first, second = receipt("first"), receipt("second")
        first.tasks_attempted.append("task")
        first.changed_files.append("file.py")
        first.commands_run.append({"command": "manual verify", "exit_code": 0})
        first.inputs["plan"] = "first"
        first.proof_paths.append("proof.json")
        require(not any((second.tasks_attempted, second.changed_files, second.commands_run, second.inputs, second.proof_paths)), CONTRACTS[3], "execution receipts share defaults")
        validate_mission_receipt(first)
        validate_mission_receipt(second)
    def decisions():
        require(m.VERIFICATION_RECEIPT_DECISIONS == ("accepted", "repair_needed", "blocked", "operator_needed"), CONTRACTS[0], "decision vocabulary differs")
        for decision in m.VERIFICATION_RECEIPT_DECISIONS:
            validate_mission_receipt(receipt(decision, model=m.VerificationReceipt, decision=decision))
    run("test_mission_receipt_schemas_cover_required_phase_contracts", [CONTRACTS[0]], schemas)
    run("test_receipt_mutable_defaults_are_independent_per_instance", [CONTRACTS[3]], default_isolation)
    run("test_verification_receipt_names_all_allowed_decisions", [CONTRACTS[0]], decisions)

    def plan(**extra):
        return build_docs_first_plan_receipt(objective="Run backend verification", docs=["planner-only raw body" * 100],
            mission_id="proof", mission_run_id="run-proof", host="scratch", runtime="manual-self-check", workspace=str(scratch), **extra)
    selected = plan(selected_skills=["run_verification_suite"], file_scope=["module.py"])
    selected.inputs["rawDocs"] = "planner-secret"
    selected.metadata["fullMissionHistory"] = "planner-secret"
    def executor_boundary():
        capsule = build_executor_phase_input(original_goal="Run backend verification", plan_receipt=selected)
        check_capsule(capsule)
        require(capsule.original_goal == "Run backend verification" and capsule.selected_skills == ["run_verification_suite"] and
                capsule.file_scope == ["module.py"] and capsule.plan_receipt["mission_run_id"] == "run-proof" and
                "planner-secret" not in str(asdict(capsule)), CONTRACTS[5], "executor lost identifiers or received raw history")
    def caps():
        value = plan(selected_skills=[f"skill-{index}" for index in range(50)], file_scope=[f"file-{index}.py" for index in range(120)], forbidden_paths=[f"forbidden-{index}" for index in range(60)])
        value.tasks = [{"id": f"task-{index}", "title": "x" * 300} for index in range(60)]
        capsule = build_executor_phase_input(original_goal="x" * 1200, plan_receipt=value)
        require((len(capsule.original_goal), len(capsule.file_scope), len(capsule.selected_skills), len(capsule.plan_receipt["tasks"]), len(capsule.plan_receipt["forbidden_paths"])) == (1000, 80, 24, 40, 40), CONTRACTS[5], "executor did not cap oversize input")
    def brief_ids():
        value = plan(skill_brief={"schema": "fluxio.skill_brief.v1", "brief_id": "private-brief", "selected_skills": [
            {"skillId": "run_verification_suite", "description": "private-description"}, {"skillId": "workspace_search"}],
            "repo_specific_skills": [{"skillId": "private-skill"}], "known_failures": [{"reason": "private-failure"}]})
        capsule = build_executor_phase_input(original_goal="Run verification", plan_receipt=value)
        require(capsule.selected_skills == ["run_verification_suite", "workspace_search"] and not any(text in str(asdict(capsule)) for text in ("private-brief", "private-description", "private-skill", "private-failure")), CONTRACTS[5], "skill brief leaked instead of selected IDs")
    execution = receipt("execution", changed_files=["module.py"], commands_run=[{"command": "manual verify", "exit_code": 0}],
                        stdout_summaries=["ok" * 300], proof_paths=["proof.json"])
    execution.metadata["fullRuntimeTranscript"] = "runtime-private"
    def verifier_boundary():
        capsule = build_verifier_phase_input(original_goal="Verify", plan_receipt=selected, execution_receipt=execution,
                                            changed_files=["module.py", "consumer.py"], proof_artifacts=["proof.json"])
        require(capsule.changed_files == ["module.py", "consumer.py"] and capsule.proof_artifacts == ["proof.json"] and
                capsule.execution_receipt["commands_run"][0]["exit_code"] == 0 and
                "runtime-private" not in str(asdict(capsule)) and "planner-secret" not in str(asdict(capsule)), CONTRACTS[6], "verifier context lost changed files or leaked transcript")
    def wrong_verifier():
        rejects(lambda: build_verifier_phase_input(original_goal="Verify", plan_receipt=asdict(execution), execution_receipt=execution))
        rejects(lambda: build_verifier_phase_input(original_goal="Verify", plan_receipt=selected, execution_receipt=asdict(selected)))
    def relevance(skill, goal, description, status):
        value = plan(selected_skills=[skill] if skill else [])
        result = check_selected_skill_relevance(original_goal=goal, plan_receipt=value, skill_brief={"selected_skills": [{"skillId": skill, "description": description}]})
        require(result["status"] == status and result["selectedSkillCount"] == int(bool(skill)) and
                result["irrelevantSkillCount"] == int(status == "review"), CONTRACTS[7], "relevance decision concealed selection mismatch")
    run("test_executor_phase_input_contains_only_goal_plan_skills_and_file_scope", [CONTRACTS[5]], executor_boundary)
    run("test_executor_phase_input_caps_plan_lists_for_executor_context", [CONTRACTS[5]], caps)
    run("test_executor_phase_input_receives_only_selected_skill_ids_from_skill_brief_plan", [CONTRACTS[5]], brief_ids)
    run("test_executor_phase_input_rejects_non_plan_receipts", [CONTRACTS[5]], lambda: rejects(lambda: build_executor_phase_input(original_goal="Goal", plan_receipt=asdict(execution))))
    run("test_verifier_phase_input_contains_goal_plan_execution_changed_files_and_artifacts", [CONTRACTS[6]], verifier_boundary)
    run("test_verifier_phase_input_rejects_wrong_receipt_schemas", [CONTRACTS[6]], wrong_verifier)
    run("test_skill_relevance_check_accepts_selected_skill_with_brief_context", [CONTRACTS[7]], lambda: relevance("run_verification_suite", "Run verification for changed Python files", "Run lint typecheck tests and build commands after code changes", "passed"))
    run("test_skill_relevance_check_flags_irrelevant_selected_skill", [CONTRACTS[7]], lambda: relevance("frontend_image_direction", "Run backend verification", "Choose visual image direction for hero media and landing page art", "review"))
    run("test_skill_relevance_check_blocks_empty_selected_skills", [CONTRACTS[7]], lambda: relevance("", "Run backend verification", "", "blocked"))

    def new_run():
        return m.MissionRun("run-proof", "proof", "scratch", "Complete scratch lifecycle", runtime_id="manual-self-check",
                            assigned_host="scratch", preferred_host="scratch", lease_id="scratch-lease", lease_status="active",
                            file_scope=["module.py"], selected_skills=["run_verification_suite"])
    def envelope():
        value = new_run()
        value.phases.append(m.MissionRunPhaseState("planner", status="completed", host_id="scratch", receipt_id="plan"))
        value.process_tree.append(m.MissionRunProcessRef("process", "command", "manual verify", str(scratch), "scratch", pid=4242, ttl_seconds=3600))
        value.receipts.append(m.MissionRunReceiptRef("plan", "plan", "accepted", producer_phase="planner"))
        check_run(value)
        payload = json.loads(json.dumps(asdict(value)))
        require(payload["status"] == "draft" and payload["current_phase"] == "preflight" and payload["lease_status"] == "active" and
                payload["file_scope"] == ["module.py"] and payload["selected_skills"] == ["run_verification_suite"] and
                payload["phases"][0]["receipt_id"] == "plan" and payload["process_tree"][0]["pid"] == 4242 and
                payload["process_tree"][0]["ttl_seconds"] == 3600 and payload["receipts"][0]["kind"] == "plan", CONTRACTS[8], "run serialization lost lifecycle truth")
    def run_defaults():
        first, second = new_run(), m.MissionRun("second", "second", "scratch", "Other")
        first.file_scope.append("only-first.py")
        first.selected_skills.append("only-first")
        first.phases.append(m.MissionRunPhaseState("preflight"))
        first.receipts.append(m.MissionRunReceiptRef("first", "readiness", "passed"))
        first.process_tree.append(m.MissionRunProcessRef("first", "command", "manual verify", str(scratch), "scratch"))
        first.metadata["owner"] = "first"
        check_run(first)
        check_run(second)
        require(not any((second.file_scope, second.selected_skills, second.phases, second.receipts, second.process_tree, second.metadata)), CONTRACTS[3], "run instances share defaults")
    def lifecycle():
        value = new_run()
        for phase, kind in (("preflight", "readiness"), ("planner", "plan"), ("executor", "execution"), ("verifier", "verification"), ("final_report", "final")):
            state = start_current_phase(value)
            require(state.phase == phase and state.status == "running", CONTRACTS[9], "phase start differs from current phase")
            complete_current_phase(value, outcome="accepted" if phase == "verifier" else "completed",
                receipt_ref=m.MissionRunReceiptRef(kind, kind, "accepted", path=str(Path(layout.receipts_jsonl))))
        require(value.status == "completed" and value.completed_at and [state.phase for state in value.phases] == ["preflight", "planner", "executor", "verifier", "final_report"] and
                [row.kind for row in value.receipts] == ["readiness", "plan", "execution", "verification", "final"], CONTRACTS[9], "normal lifecycle did not preserve phase receipts")
        (scratch / "run-envelope.json").write_text(json.dumps(asdict(value), indent=2), encoding="utf-8")
    def repair(second=False):
        value = new_run()
        for _ in range(3):
            start_current_phase(value)
            complete_current_phase(value)
        start_current_phase(value)
        transition = complete_current_phase(value, outcome="repair_needed")
        require(transition.to_phase == "repair" and value.status == "repair_needed" and value.metadata["repair_loop_count"] == 1 and value.metadata["maximum_repair_loops"] == 1, CONTRACTS[9], "first repair not bounded")
        start_current_phase(value)
        complete_current_phase(value)
        require(value.current_phase == "verifier" and value.status == "running" and [state.phase for state in value.phases].count("verifier") == 1 and [state.phase for state in value.phases].count("repair") == 1, CONTRACTS[9], "repair did not return to existing verifier")
        if second:
            start_current_phase(value)
            transition = complete_current_phase(value, outcome="repair_needed")
            state = next(state for state in value.phases if state.phase == "verifier")
            require(transition.terminal and value.status == "blocked" and value.current_phase == "verifier" and value.metadata["repair_loop_count"] == 1 and value.metadata["repair_loop_limit_exhausted"] and state.status == "blocked" and "repair loop limit is exhausted" in state.error, CONTRACTS[9], "exhausted repair loop escaped terminal gate")
    def blocked():
        value = new_run()
        start_current_phase(value)
        transition = complete_current_phase(value, outcome="blocked", error="scratch runtime unavailable")
        require(transition.terminal and value.status == "blocked" and value.current_phase == "preflight" and value.phases[0].status == "blocked" and value.completed_at, CONTRACTS[9], "blocked phase claimed progress")
    def no_restart():
        value = new_run()
        start_current_phase(value)
        complete_current_phase(value)
        value.current_phase = "preflight"
        rejects(lambda: start_current_phase(value), MissionPhaseTransitionError)
        terminal = new_run()
        terminal.status = "completed"
        rejects(lambda: start_current_phase(terminal), MissionPhaseTransitionError)
    run("test_mission_run_envelope_serializes_core_lifecycle_truth", [CONTRACTS[8]], envelope)
    run("test_mission_run_defaults_are_independent_per_instance", [CONTRACTS[3], CONTRACTS[8]], run_defaults)
    run("test_mission_run_contract_names_expected_phases_and_statuses", [CONTRACTS[8]], lambda: check_run(new_run()))
    run("test_phase_runner_advances_normal_flow_without_executing_fake_work", [CONTRACTS[9]], lifecycle)
    run("test_verifier_repair_needed_routes_to_single_repair_phase_then_back_to_verifier", [CONTRACTS[9]], repair)
    run("test_second_repair_needed_blocks_instead_of_looping_forever", [CONTRACTS[9]], lambda: repair(True))
    run("test_blocked_phase_stops_without_advancing_or_claiming_completion", [CONTRACTS[9]], blocked)
    run("test_runner_rejects_restarting_completed_or_terminal_runs", [CONTRACTS[9]], no_restart)
    _extended_self_check(scratch, run, require)
    _local_projection_self_check(scratch, run)
    return {"ok": all(row["ok"] for row in cases), "contracts": list(CONTRACTS), "cases": cases,
            "failures": [row for row in cases if not row["ok"]], "scratchRoot": str(scratch),
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "frontier": "Unmapped control-room/runtime cases remain retained. Supervisor coordination and real installed security delegation are outside this local scratch proof."}


def _extended_self_check(scratch, run, require):
    import argparse
    import contextlib
    import io
    from .continuity_policy import MissionContinuityStore
    from .mission_acceptance_harness import run_acceptance_harness
    from .security_runtime_policy import evaluate_security_action, build_purple_team_plan, audit_security_tool_coverage
    from .mission_control import ControlRoomStore, apply_agent_turn_mode_to_launch, normalize_agent_turn_mode, PLAN_TURN_MODE_SUCCESS_CHECK
    from .cli import cmd_mission_orchestration
    from .fluxio_harness import infer_task_route_profile

    def acceptance():
        result = run_acceptance_harness(scratch / "acceptance")
        require(result["ok"] and result["summary"] == {"passed": 5, "total": 5, "failed": []} and result["cpuMs"] < 5000, CONTRACTS[10], "local acceptance journeys failed or exceeded budget")
        scheduler = next(row for row in result["journeys"] if row["id"] == "compiled-scheduler")
        require(all(scheduler["checks"][key] for key in ("mutationBlockedWithoutApproval", "approvedPlanCompleted", "attemptReceiptsPreserved")), CONTRACTS[10], "scheduler approval/receipt journey incomplete")
    def repeated_acceptance():
        root = scratch / "repeat-acceptance"
        first, second = run_acceptance_harness(root), run_acceptance_harness(root)
        require(first["ok"] and second["ok"] and first["runId"] != second["runId"] and first["receiptPath"] != second["receiptPath"] and
                all(Path(row["receiptPath"]).exists() for row in (first, second)), CONTRACTS[10], "repeated acceptance overwrote earlier proof")
    run("test_fast_acceptance_harness_completes_all_journeys_without_external_use", [CONTRACTS[10]], acceptance)
    run("test_acceptance_harness_can_repeat_against_the_same_durable_root", [CONTRACTS[10]], repeated_acceptance)

    def continuity_concurrent():
        store = MissionContinuityStore(scratch / "continuity-concurrent")
        store.create_or_update("parallel", goal="Preserve every receipt")
        def record(index):
            return store.record_tool_attempt("parallel", tool="local.observer", idempotency_key=f"receipt-{index}",
                                            action={"kind": "read"}, outcome="verified", evidence={"index": index})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(record, range(24)))
        saved = store.load("parallel")
        require(len(saved["toolAttempts"]) == len(saved["completedIdempotencyKeys"]) == 24 and
                not list(store.base.glob("*.lock")), CONTRACTS[11], "concurrent continuity lost receipts or leaked lock")
    def continuity_recovery():
        store = MissionContinuityStore(scratch / "continuity-recovery")
        first = store.create_or_update("recovery", goal="Retain original goal", patch={"status": "running", "currentStep": "first"})
        store.create_or_update("recovery", patch={"currentStep": "second"})
        (store.base / "recovery.json").write_text("{broken", encoding="utf-8")
        restored = store.load("recovery")
        require(restored["revision"] == first["revision"] and restored["goal"] == first["goal"] and
                restored["recovery"]["status"] == "restored_from_previous_snapshot", CONTRACTS[11], "continuity lost previous safe revision")
        reconciled = store.create_or_update("recovery", patch={"currentStep": "reconciled"}, event_kind="snapshot_reconciled")
        require(reconciled["currentStep"] == store.load("recovery")["currentStep"] == "reconciled", CONTRACTS[11], "recovered continuity could not progress")
    def gpu():
        store = MissionContinuityStore(scratch / "gpu-policy")
        store.create_or_update("gpu", patch={"gpuPolicy": {"maxConcurrentInstances": 1, "maxEstimatedHourlyCost": 5,
            "maxEstimatedSessionCost": 4, "maxDurationMinutes": 60, "idleReleaseMinutes": 10,
            "requireApprovalForPaidStart": True, "requireApprovalForDestructiveAction": True, "preferExistingCheckpoint": True}})
        expensive = store.evaluate_gpu_action("gpu", {"action": "start_instance", "estimatedHourlyCost": 3, "estimatedDurationMinutes": 120}, {"runningInstances": 0, "validCheckpoint": False})
        overtime = store.evaluate_gpu_action("gpu", {"action": "continue_training"}, {"runningInstances": 1, "validCheckpoint": True, "runningDurationMinutes": 60, "idleMinutes": 11})
        require(not expensive["allowed"] and expensive["estimatedSessionCost"] == 6 and any("session cost" in text for text in expensive["blockers"]) and
                not overtime["allowed"] and overtime["releaseRequired"] and overtime["releaseReasons"] == ["duration_limit", "idle_limit"] and
                overtime["nextAction"] == "Checkpoint current work and release the GPU instance.", CONTRACTS[12], "cost/duration/idle policy gate failed")
    run("test_continuity_read_modify_write_is_safe_under_concurrent_tool_receipts", [CONTRACTS[11]], continuity_concurrent)
    run("test_corrupt_continuity_snapshot_recovers_previous_valid_revision", [CONTRACTS[11]], continuity_recovery)
    run("test_gpu_policy_enforces_session_cost_duration_and_idle_release", [CONTRACTS[12]], gpu)

    scope = {"target": "scratch.local", "authorizedBy": "owner", "authorizationConfirmed": True, "environment": "lab", "mode": "active",
             "allowedTargets": ["scratch.local"], "allowedActionClasses": ["probe", "detection", "remediation", "retest"]}
    def security_scope():
        plan = build_purple_team_plan(scope)
        require(plan["ready"] and [row["owner"] for row in plan["phases"]] == ["auditor", "red", "blue", "defender", "auditor"], CONTRACTS[13], "purple team separation failed")
        proposal = {"target": "scratch.local", "actionClass": "probe", "active": True}
        require(evaluate_security_action(scope, proposal)["allowed"], CONTRACTS[13], "authorized lab decision blocked")
        outside = evaluate_security_action(scope, {**proposal, "target": "other.local"})
        unapproved = evaluate_security_action({"target": "scratch.local", "environment": "lab", "mode": "active"}, proposal)
        production = evaluate_security_action({**scope, "environment": "production"}, proposal)
        destructive = evaluate_security_action({**scope, "mode": "passive", "allowedActionClasses": ["destructive"], "allowDestructiveActions": True, "approvalId": "scratch-approval"},
                                              {"target": "scratch.local", "actionClass": "destructive", "active": False})
        credential = evaluate_security_action(scope, {"target": "scratch.local", "actionClass": "credential_access", "active": False})
        require(not outside["allowed"] and not unapproved["allowed"] and production["scopeAllowed"] and production["approvalRequired"] and not production["allowed"] and
                not destructive["scopeAllowed"] and "Active actions require an active security scope." in destructive["blockers"] and
                not credential["allowed"] and credential["active"], CONTRACTS[13], "adverse authorization decision allowed scope escape")
    def bad_budget():
        result = evaluate_security_action({"target": "scratch.local", "environment": "lab", "mode": "passive", "maxProbeAttempts": "many"},
                                          {"target": "scratch.local", "actionClass": "review"})
        require(result["allowed"] and result["maxProbeAttempts"] == 3, CONTRACTS[13], "invalid attempt budget did not safely normalize")
    def missing_defensive():
        result = audit_security_tool_coverage(["security.threat-model", "security.ai-red-team", "security.remediate-and-retest"])
        require(not result["ready"] and result["missingPhases"] == ["blue_detection"] and "blue_detection" in result["nextAction"], CONTRACTS[14], "missing defensive coverage concealed")
    def planned_tool():
        result = audit_security_tool_coverage([{"toolId": "tool.windows-defender", "executionReady": False, "state": "verified", "readinessDetail": "Needs fresh runtime proof"}])
        require("blue_detection" in result["missingPhases"] and result["unavailableCandidates"][0]["id"] == "tool.windows-defender", CONTRACTS[14], "planned tool promoted to executable coverage")
    run("test_security_scope_requires_authorization_and_separates_red_blue_retest", [CONTRACTS[13]], security_scope)
    run("test_security_scope_invalid_attempt_budget_falls_back_without_crashing", [CONTRACTS[13]], bad_budget)
    run("test_security_tool_audit_names_missing_defensive_phase_honestly", [CONTRACTS[14]], missing_defensive)
    run("test_security_tool_audit_does_not_count_a_planned_tool_as_executable", [CONTRACTS[14]], planned_tool)
    def security_routes():
        red = infer_task_route_profile("Run an authorized red-team attack-surface assessment in the lab")
        blue = infer_task_route_profile("Perform blue-team detection engineering and incident response triage")
        require((red["taskType"], red["routeIntent"]) == ("security_red_team", "adversarial_verification_execution") and
                (blue["taskType"], blue["routeIntent"]) == ("security_blue_team", "defensive_detection_execution"), CONTRACTS[18], "red/blue task semantics collapsed")
    run("test_runtime_routes_red_and_blue_team_work_as_distinct_mission_types", [CONTRACTS[18]], security_routes)

    def turn_launch(turn_mode, goal="Scoped edit", checks=None, mode="Autopilot", budget=4, overrides=None):
        return apply_agent_turn_mode_to_launch(turn_mode=turn_mode, objective=goal, success_checks=checks or [],
            route_overrides=overrides or [], mode=mode, budget_hours=budget)
    def turn_aliases():
        expected = {"plan": "plan", "PLANNING": "plan", "fast": "fast", "speed": "fast", "1m": "max-context", "max_context": "max-context", "turbo": "standard", None: "standard"}
        for value, wanted in expected.items():
            require(normalize_agent_turn_mode(value) == turn_launch(value)["turnMode"] == wanted, CONTRACTS[15], "turn mode alias changed launch")
    def plan_launch():
        result = turn_launch("plan", "Build local page", ["Page renders"], overrides=[{"role": "executor", "provider": "local", "model": "manual"}])
        require(result["turnMode"] == "plan" and "Plan first" in result["objective"] and "Build local page" in result["objective"] and
                result["successChecks"][0] == PLAN_TURN_MODE_SUCCESS_CHECK and "Page renders" in result["successChecks"] and result["mode"] == "Autopilot", CONTRACTS[15], "plan requirement lost")
    def fast_launch():
        result = turn_launch("fast", overrides=[{"role": "executor", "effort": "high"}])
        require(result["budgetHours"] == 1.0 and result["routeOverrides"][0]["effort"] == "low", CONTRACTS[15], "fast launch caps failed")
    def max_launch():
        result = turn_launch("1m", overrides=[{"role": "executor", "effort": "medium"}])
        require(result["mode"] == "Deep Run" and result["budgetHours"] == 8.0 and result["routeOverrides"][0]["effort"] == "high", CONTRACTS[15], "deep launch not applied")
    def standard_launch():
        result = turn_launch("standard", "Ship it", ["Done"], mode="Focus", budget=2)
        require(result == {"turnMode": "standard", "objective": "Ship it", "successChecks": ["Done"], "routeOverrides": [], "mode": "Focus", "budgetHours": 2.0}, CONTRACTS[15], "standard launch changed fields")
    run("test_normalize_agent_turn_mode_accepts_aliases_and_rejects_unknown", [CONTRACTS[15]], turn_aliases)
    run("test_apply_agent_turn_mode_plan_requires_written_plan_before_edits", [CONTRACTS[15]], plan_launch)
    run("test_apply_agent_turn_mode_fast_lowers_effort_and_caps_budget", [CONTRACTS[15]], fast_launch)
    run("test_apply_agent_turn_mode_max_context_deepens_run", [CONTRACTS[15]], max_launch)
    run("test_apply_agent_turn_mode_standard_changes_nothing", [CONTRACTS[15]], standard_launch)

    def orchestration():
        target = scratch / "orchestration"
        store = ControlRoomStore(target)
        workspace = store.load_workspaces()[0]
        mission = store.create_mission(workspace_id=workspace.workspace_id, runtime_id="local", objective="Configure local orchestration",
            success_checks=["Policy saved"], mode="Autopilot", verification_commands=[], max_runtime_seconds=3600)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = cmd_mission_orchestration(argparse.Namespace(root=str(target), mission_id=mission.mission_id,
                parallel_agents=4, observation_count=7, merge_policy="consensus", cross_mission_awareness="adapt", reason="Scratch proof"))
        result = json.loads(output.getvalue())
        saved = ControlRoomStore(target).get_mission(mission.mission_id)
        require(exit_code == 0 and result["ok"] and (saved.state.parallel_agents, saved.state.observation_count, saved.state.merge_policy, saved.state.cross_mission_awareness) == (4, 7, "consensus", "adapt"), CONTRACTS[17], "CLI did not persist mission orchestration")
        events = store.recent_events()
        require(any(row["kind"] == "mission.orchestration_updated" and row["metadata"] == result["receipt"] for row in events), CONTRACTS[17], "orchestration event receipt missing")
    run("test_cli_persists_orchestration_and_receipt", [CONTRACTS[16], CONTRACTS[17]], orchestration)


def _local_projection_self_check(scratch, run):
    """Read disposable, persisted evidence with actual helpers; no collectors.

    Session labels here are projection inputs. The producer is explicitly a local
    Python process; these receipts never assert a genuine model/provider call.
    """
    import subprocess
    import sys
    from datetime import timezone
    from types import SimpleNamespace
    from . import mission_control as mc
    from .flight_recorder import MissionFlightRecorder
    from .models import Mission, DelegatedRuntimeSession, VerificationReceipt
    from .mission_receipts import append_mission_receipt
    from .mission_artifacts import build_mission_run_artifact_layout
    from .mission_watchdog import build_planned_scope_artifacts
    from .cli import _mission_storage_pressure_blocker
    from .subprocess_utils import hidden_windows_subprocess_kwargs

    base = scratch / "local-projections"
    base.mkdir()
    def setup(name):
        root = base / name
        root.mkdir()
        mission = Mission(mission_id=name, workspace_id="scratch", runtime_id="hermes",
                          objective="Review local evidence report", success_checks=[])
        mission.execution_scope.workspace_root = str(root)
        mission.execution_scope.execution_root = str(root)
        store = mc.ControlRoomStore(root)
        store.save_missions([mission])
        return root, mission, store
    def save_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    def timeline(root, session, row):
        path = root / ".agent_runs" / session / "timeline.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        return path
    def transcript(root, mission, events=None):
        value = mc.ControlRoomStore._mission_runtime_transcript_payload(mission, events=events or [], root=root)
        messages = mc.ControlRoomStore._mission_agent_messages_payload(mission, events=events or [], root=root, runtime_transcript=value)
        return value, messages
    def artifact(root, mission, body):
        target = root / ".agent_control/mission_artifacts" / mission.mission_id
        (target / "proof").mkdir(parents=True, exist_ok=True)
        (target / "index.html").write_text("<main>Saved local evidence</main>", encoding="utf-8")
        (target / "proof/runtime_output.txt").write_text(body, encoding="utf-8")
        return target

    def read_model():
        root, mission, store = setup("read-model")
        mission.state.status = "running"
        mission.state.current_cycle_phase = "executor"
        mission.proof.changed_files = ["local-report.md"]
        store.save_missions([mission])
        before = store.missions_path.read_bytes()
        value = mc.ControlRoomStore._mission_run_read_model_payload(mission, root=root)
        require(value["source"] == "legacy_missions_json" and value["missionRunId"] == "legacy_read-model" and
                value["status"] == "running" and value["currentPhase"] == "executor" and value["receiptCount"] == 0 and
                not value["migrationRequired"] and store.missions_path.read_bytes() == before, CONTRACTS[22], "legacy read model mutated or lost lifecycle")
        layout = build_mission_run_artifact_layout(root, mission.mission_id)
        append_mission_receipt(Path(layout.receipts_jsonl), VerificationReceipt(receipt_id="local-verification", mission_id=mission.mission_id,
            host="scratch", runtime="local-python", workspace=str(root), status="accepted", summary="Local action result inspected", decision="accepted"))
        value = mc.ControlRoomStore._mission_run_read_model_payload(mission, root=root)
        require(value["receiptCount"] == 1 and value["latestReceipt"]["receipt_id"] == "local-verification" and
                value["latestReceipt"]["decision"] == "accepted" and value["artifactLayout"]["receipts_jsonl"] == layout.receipts_jsonl,
                CONTRACTS[22], "per-mission receipt not projected")
        save_json(Path(layout.snapshots_dir) / "mission_run.json", {"schema_version": "fluxio.mission_run.v1", "mission_id": "other-mission", "current_phase": "final_report"})
        require(not mc.ControlRoomStore._mission_run_read_model_payload(mission, root=root)["snapshotPresent"], CONTRACTS[22], "foreign mission snapshot adopted")
    run("local-helper:legacy-and-receipt-read-model", [CONTRACTS[22]], read_model)

    def flight():
        root, mission, store = setup("flight")
        recorder = MissionFlightRecorder(root, mission.mission_id)
        recorder.append_event(kind="phase.started", message="Local producer started", phase="executor")
        recorder.snapshot(current_phase="executor", runtime_command="local Python report producer", cwd=str(root), env_status={"producer": "local"},
                          process_ids=[101], lease_id="local-lease", heartbeat_age_seconds=4, queue_reason="scratch", changed_files=["report.md"], verifier_result={"status": "pending"})
        before = store.missions_path.read_bytes()
        value = mc.ControlRoomStore._mission_run_read_model_payload(mission, root=root)["flightRecorder"]
        require(value["present"] and value["schema"] == "fluxio.mission_flight_recorder_read_model.v1" and value["currentPhase"] == "executor" and
                value["processIds"] == [101] and value["eventCount"] == 1 and value["events"][0]["kind"] == "phase.started" and
                before == store.missions_path.read_bytes(), CONTRACTS[23], "flight recorder projection lost written event")
        missing = mc.ControlRoomStore._compact_flight_recorder_payload({}, snapshot_path=root / "missing.json")
        require(not missing["present"] and not missing["events"], CONTRACTS[23], "missing flight recorder invented evidence")
    run("local-helper:flight-recorder-read-model", [CONTRACTS[22], CONTRACTS[23]], flight)

    def dialogue():
        root, mission, store = setup("dialogue")
        require(mc.mission_runtime_dialogue_turns(mission, root=root) == [], CONTRACTS[19], "empty mission generated dialogue")
        source = root / "local_producer.py"
        body = "The local report producer inspected a bounded arithmetic example and wrote a durable report. The captured result is available for independent review."
        source.write_text("print(" + repr(body) + ")\n", encoding="utf-8")
        completed = subprocess.run([sys.executable, "-I", str(source)], cwd=root, capture_output=True, text=True, timeout=10, **hidden_windows_subprocess_kwargs())
        require(completed.returncode == 0 and completed.stdout.strip() == body, CONTRACTS[19], "local producer did not return actual captured output")
        source_path = root / "captured-runtime.jsonl"
        event = {"kind": "runtime.output", "message": completed.stdout.strip(), "timestamp": "2026-10-03T10:00:00Z", "metadata": {
            "sourceKind": "real-runtime-output", "captureMode": "fresh-runtime-command", "sourcePath": str(source_path),
            "reportPath": str(root / "local-report.txt"), "externalRuntimeSessionId": "local-process-capture", "producer": "system-python"}}
        source_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        mission.delegated_runtime_sessions = [DelegatedRuntimeSession(delegated_id="projection-label", runtime_id="hermes", launch_command=str(source),
            status="completed", target_provider="scratch", target_model="local-producer", latest_events=[{"kind": "heartbeat", "message": "x" * 120}, event])]
        output = "Local producer durable report: the inspected arithmetic result agrees with the report and the captured process output."
        directory = artifact(root, mission, output)
        turns = mc.mission_runtime_dialogue_turns(mission, root=root)
        require(len(turns) == 2 and turns[0]["text"] == body and turns[0]["runtimeId"] == "hermes" and turns[0]["model"] == "local-producer" and
                turns[0]["captureMode"] == "fresh-runtime-command" and turns[0]["externalRuntimeSessionId"] == "local-process-capture" and output in turns[1]["text"] and turns[1]["runtimeId"] == "hermes", CONTRACTS[19], "real captured text/provenance not projected")
        messages = mc.ControlRoomStore._mission_agent_messages_payload(mission, events=[], root=root)
        projected = [row for row in messages if row.get("conversationTurn")]
        require(len(projected) >= 2 and projected[0]["role"] == "assistant" and projected[0]["label"] == "Hermes reply" and
                projected[0]["source"] == "backend-runtime-reply" and projected[0]["messageKind"] == "dialogue" and
                body in projected[0]["detail"] and projected[0]["turnReceipt"]["captureMode"] == "fresh-runtime-command" and "local-producer" in projected[0]["chips"] and "real runtime output" in projected[0]["chips"] and
                "fresh runtime command" in projected[0]["chips"] and projected[0]["turnReceipt"]["captureLabel"] == "fresh runtime command" and
                projected[0]["turnReceipt"]["externalRuntimeSessionId"] == "local-process-capture", CONTRACTS[21], "dialogue UI projection lost original capture evidence")
        mission.runtime_id = mission.delegated_runtime_sessions[0].runtime_id = "openclaw"
        switched = [row for row in mc.ControlRoomStore._mission_agent_messages_payload(mission, events=[], root=root) if row.get("conversationTurn")]
        require(switched[0]["label"] == "OpenClaw reply" and switched[0]["source"] == "backend-runtime-reply" and switched[0]["runtimeId"] == "openclaw", CONTRACTS[21], "runtime label change lost conversation projection")
        mission.delegated_runtime_sessions[0].latest_events = [{"kind": "runtime.phase", "message": "Control event " * 20}]
        (directory / "proof/runtime_output.txt").rename(directory / "proof/retained-report.txt")
        require(mc.mission_runtime_dialogue_turns(mission, root=root) == [], CONTRACTS[19], "control events generated fallback dialogue")
    run("test_runtime_dialogue_turns_surface_real_model_output_as_conversation", [CONTRACTS[19], CONTRACTS[21]], dialogue)

    def missing_and_bookkeeping():
        root, mission, store = setup("missing-transcript")
        mission.state.latest_session_id = "missing"
        mission.plan_revisions = [{"revision_id": "rev", "summary": "Review saved plan", "steps": []}]
        mission.action_history = [{"action_id": "saved", "proposal": {"kind": "file_patch", "title": "Patch target file"}, "result": {"result_summary": "File mutation completed."}}]
        events = [{"kind": "mission.runtime_cycle", "message": "Control loop heartbeat"}]
        value, messages = transcript(root, mission, events)
        require(value["status"] == "missing_transcript" and "missing" in value["candidateSessionIds"] and not value["messages"], CONTRACTS[20], "missing transcript attached synthetic rows")
        by_label = {row["label"]: row for row in messages}
        require({"Runtime transcript integrity", "Control-room planner", "Control-room action result"} <= set(by_label) and "Planner review" not in by_label and "mission.runtime_cycle" not in by_label and
                all(by_label[label]["traceOnly"] and not by_label[label]["chatPreferred"] for label in ("Runtime transcript integrity", "Control-room planner", "Control-room action result")), CONTRACTS[21], "bookkeeping masqueraded as chat")
    run("local-helper:missing-transcript-and-bookkeeping", [CONTRACTS[20], CONTRACTS[21]], missing_and_bookkeeping)

    def readonly_and_output():
        root, mission, store = setup("readonly-transcript")
        mission.state.latest_session_id = "read-only"
        timeline(root, "read-only", {"kind": "action.proposed", "message": "Read context for current plan", "metadata": {"kind": "file_read", "target_path": str(root / "notes.md")}})
        value, messages = transcript(root, mission)
        require(value["status"] == "missing_runtime_output" and not value["messages"] and "read-only" in value["nonConcreteSessionIds"] and
                not any(row["label"] == "Hermes session transcript" for row in messages) and
                any(row["label"] == "Runtime transcript integrity" and row["traceOnly"] and "no runtime output body" in row["detail"] for row in messages), CONTRACTS[20], "read-only rows became runtime output")
        body = "Local captured report\n\nWhat changed:\n- Local process wrote a reviewable report body.\n\nConcrete verification:\n- The durable artifact file is readable.\n"
        artifact(root, mission, body)
        value, messages = transcript(root, mission)
        gate = mc.mission_hard_artifact_gate(mission, root=root, runtime_transcript=value, agent_messages=messages)
        require(value["status"] == "attached" and value["sessionId"] == "runtime_artifact" and value["messageCount"] >= 2 and
                "read-only" in value["nonConcreteSessionIds"] and gate["passed"] and gate["runtimeOutputCount"] >= 1 and
                any(row["label"] == "Runtime output artifact" and row["processMessage"] and not row["traceOnly"] and "Local process wrote" in row["detail"] for row in messages), CONTRACTS[24], "actual report artifact was not attached")
    run("local-helper:read-only-rejection-and-artifact-fallback", [CONTRACTS[20], CONTRACTS[21], CONTRACTS[24]], readonly_and_output)

    def concrete_timeline():
        root, mission, store = setup("timeline")
        mission.state.latest_session_id = "current"
        timeline(root, "current", {"kind": "runtime.report", "message": "Local producer emitted an operator report", "metadata": {
            "kind": "file_patch", "target_path": str(root / "report.md"), "args": {"content": "## Local slice report\nA durable report body is present."}, "result": {"result_summary": "File mutation completed."}}})
        save_json(root / ".agent_runs/current/state.json", {"decisions": ["Read-only decision"], "next_actions": ["Planning only"], "notes": ["No executed output"]})
        value, messages = transcript(root, mission)
        selected = next(row for row in messages if row["label"] == "Hermes session transcript")
        require(value["status"] == "attached" and selected["title"] == "Local producer emitted an operator report" and
                selected["detail"].startswith("Runtime output: ## Local slice report") and "Action: file_patch" in selected["detail"] and
                "report.md" in selected["detail"] and "result_summary" in selected["technicalDetail"] and not selected["traceOnly"] and selected["chatPreferred"] and
                not any(row["label"].startswith(("Hermes session decision", "Hermes session note", "Hermes session next action")) for row in messages), CONTRACTS[20], "timeline output lost priority over state bookkeeping")
        events = []
        for index in range(10):
            session = f"stale-{index}"
            timeline(root, session, {"kind": "runtime.report", "message": "Stale runtime report", "metadata": {"kind": "file_write", "args": {"content": "Stale output"}}})
            events.append({"kind": "mission.runtime_cycle", "metadata": {"sessionId": session}})
        require(transcript(root, mission, events)[0]["sessionId"] == "current", CONTRACTS[20], "stale event session displaced latest concrete output")
        mission.state.latest_session_id = "read-only"
        timeline(root, "read-only", {"kind": "action.proposed", "message": "Read plan", "metadata": {"kind": "file_read", "target_path": str(root / "notes.md")}})
        events = [{"kind": "mission.runtime_cycle", "metadata": {"sessionId": "current"}}]
        require(transcript(root, mission, events)[0]["sessionId"] == "current", CONTRACTS[20], "latest read-only session hid older concrete output")
    run("local-helper:concrete-timeline-and-session-priority", [CONTRACTS[20], CONTRACTS[21]], concrete_timeline)

    def repairs():
        root, mission, store = setup("artifact-repair")
        mission.state.status = "verification_failed"
        mission.state.stop_reason = "artifact_gate_failed"
        mission.state.last_runtime_event = "artifact_gate_failed"
        mission.state.verification_failures = [mc.HARD_ARTIFACT_GATE_CHECK_ID]
        mission.proof.failed_checks = [mc.HARD_ARTIFACT_GATE_FAILURE]
        mission.proof.blocked_by = [mc.HARD_ARTIFACT_GATE_FAILURE]
        empty = mc.mission_hard_artifact_gate(mission, root=root)
        require(not empty["passed"] and not mc._complete_repaired_hard_artifact_gate_from_detail(mission, empty), CONTRACTS[25], "missing artifacts completed a repair")
        artifact(root, mission, "Captured local producer report: the file was written and the result can be inspected independently.")
        evidence, messages = transcript(root, mission)
        gate = mc.mission_hard_artifact_gate(mission, root=root, runtime_transcript=evidence, agent_messages=messages)
        mission.proof.failed_checks.append("unrelated verifier failure")
        require(not mc._complete_repaired_hard_artifact_gate_from_detail(mission, gate), CONTRACTS[25], "artifact repair erased unrelated failure")
        mission.proof.failed_checks.remove("unrelated verifier failure")
        require(mc._complete_repaired_hard_artifact_gate_from_detail(mission, gate), CONTRACTS[25], "proven artifact repair did not complete")
        store.update_mission(mission)
        saved = store.get_mission(mission.mission_id)
        require(saved.state.status == "completed" and not saved.proof.failed_checks and not saved.proof.blocked_by and saved.proof.summary == "Mission completed with proof artifacts.", CONTRACTS[25], "artifact repair not durable")
        planned = root / "artifacts/wrappers"
        planned.mkdir(parents=True)
        (planned / "README.md").write_text("# Local wrappers\n", encoding="utf-8")
        (planned / "manifest.json").write_text('{"scope":"local"}', encoding="utf-8")
        mission.planned_file_scope = [str(planned)]
        mission.state.status = "verification_failed"
        mission.state.stop_reason = mission.state.last_runtime_event = "planned_scope_artifacts_failed"
        mission.state.verification_failures = [mc.PLANNED_SCOPE_ARTIFACT_GATE_CHECK_ID]
        mission.proof.failed_checks = [mc.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE]
        ready = build_planned_scope_artifacts(root=root, mission=mission)
        require(ready["status"] == "ready" and mc._complete_repaired_planned_scope_artifact_gate_from_detail(mission, gate, ready), CONTRACTS[25], "ready planned artifact repair not completed")
        store.update_mission(mission)
        require(store.get_mission(mission.mission_id).state.status == "completed", CONTRACTS[25], "planned artifact repair not durable")
    run("local-helper:hard-and-planned-artifact-repair", [CONTRACTS[24], CONTRACTS[25]], repairs)

    def public_launch():
        root, mission, store = setup("public-launch")
        path = root / ".agent_control/public_launch_readiness/latest.json"
        source = {"schema": "fluxio.public_launch_readiness.v1", "checkedAt": "2026-10-03T09:00:00Z", "status": "stale", "ok": False,
                  "missing": ["external_publication_proven"], "publicWeb": {"sourceDirtyPathSample": ["stale.py"]}}
        latest = {"schema": "fluxio.public_launch_readiness.v1", "checkedAt": "2026-10-03T10:00:00Z", "status": "public_packet_ready_missing_current_web_and_publication",
                  "ok": False, "internalPacketReady": True, "missing": ["public_web_current", "external_publication_proven"],
                  "blockers": [{"checkId": "public_web_current", "details": "Current source receipt is required"}],
                  "publicWeb": {"sourceDirtyPathCount": 3, "sourceDirtyPathSample": ["fresh.py"], "dirtySourceTriage": {"releaseBlockingSampleCount": 1}},
                  "publicationProof": {"nextAction": "Attach publication proof"}, "repairPacket": {"orderedLanes": [{"lane": "verifier"}], "commands": [{"command": "npm run verify:public-launch"}],
                    "receiptTargets": [{"path": ".agent_control/public_launch_readiness/latest.json"}]}}
        save_json(path, latest)
        value = mc._public_launch_readiness_digest(root, source)
        require(value["status"] == latest["status"] and value["publicWeb"]["sourceDirtyPathSample"] == ["fresh.py"] and
                value["internalPacketReady"] and value["missing"] == latest["missing"] and value["blockers"][0]["checkId"] == "public_web_current" and
                value["repairPacket"] == latest["repairPacket"] and value["publicationProof"] == latest["publicationProof"], CONTRACTS[26], "fresh publication evidence lost operator fields")
        path.rename(path.with_name("retained.json"))
        require(mc._public_launch_readiness_digest(root, source)["status"] == "stale" and mc._public_launch_readiness_digest(root)["status"] == "missing", CONTRACTS[26], "missing latest evidence discarded explicit source or invented public readiness")
    run("test_public_launch_digest_prefers_fresher_readiness_file", [CONTRACTS[26]], public_launch)

    def storage():
        root, mission, store = setup("storage")
        path = root / ".agent_control/nas_storage_pressure_latest.json"
        workspace = SimpleNamespace(root_path=str(root), nas_project_path=str(root / "local-saved-mount"), local_project_path=str(root))
        now = datetime.now(timezone.utc).isoformat()
        save_json(path, {"schema": "fluxio.nas_storage_pressure.v1", "checkedAt": now, "mount": str(root), "status": "unknown"})
        require(_mission_storage_pressure_blocker(root, workspace) == {}, CONTRACTS[27], "unknown storage state blocked launch")
        save_json(path, {"schema": "fluxio.nas_storage_pressure.v1", "checkedAt": now, "mount": str(root), "status": "full", "measuredUsageAvailable": True, "usedPercent": 100, "availableBytes": 0})
        value = _mission_storage_pressure_blocker(root, workspace)
        require(value.get("code") == "nas_storage_pressure_block" and value["storage"]["measuredUsageAvailable"], CONTRACTS[27], "saved critical capacity receipt failed to block")
        save_json(path, {"schema": "fluxio.nas_storage_pressure.v1", "checkedAt": now, "mount": str(root), "status": "probe_connect_failed", "measuredUsageAvailable": False, "probeConnectFailed": True, "usedPercent": 100, "availableBytes": 0})
        require(_mission_storage_pressure_blocker(root, workspace) == {}, CONTRACTS[27], "failed probe invented measured disk pressure")
    run("test_storage_pressure_preflight_requires_measured_capacity_before_blocking", [CONTRACTS[27]], storage)
    def platform():
        require(mc._platform_path_for_windows_drive(r"C:\volume1\local\evidence.log", posix=True).as_posix() == "/mnt/c/volume1/local/evidence.log", CONTRACTS[28], "WSL parser did not preserve drive/tail")
        require(mc._platform_path_for_windows_drive(r"C:\volume1\local\evidence.log", posix=False) == Path(r"C:\volume1\local\evidence.log"), CONTRACTS[28], "native explicit platform changed path")
    run("test_mission_evidence_windows_path_translates_for_wsl", [CONTRACTS[28]], platform)
