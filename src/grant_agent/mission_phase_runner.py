from __future__ import annotations

from dataclasses import dataclass

from .models import (
    MISSION_RUN_PHASES,
    MISSION_RUN_TERMINAL_STATUSES,
    MissionRun,
    MissionRunPhaseState,
    MissionRunReceiptRef,
    utc_now_iso,
)

MISSION_PHASE_RUNNER_SCHEMA = "fluxio.mission_phase_runner.v1"


class MissionPhaseTransitionError(ValueError):
    pass


@dataclass
class MissionPhaseTransition:
    schema: str
    mission_run_id: str
    from_phase: str
    outcome: str
    to_phase: str
    run_status: str
    terminal: bool
    summary: str = ""


def start_current_phase(
    run: MissionRun,
    *,
    host_id: str = "",
    runtime_id: str = "",
    lease_id: str = "",
) -> MissionRunPhaseState:
    from .proofs_c_missions import check_run
    check_run(run)
    if run.status in MISSION_RUN_TERMINAL_STATUSES:
        raise MissionPhaseTransitionError("Cannot start a phase for a terminal mission run")
    phase = _validate_phase(run.current_phase)
    phase_state = _phase_state_for(run, phase)
    if phase_state.status == "running":
        return phase_state
    if phase_state.status == "completed":
        raise MissionPhaseTransitionError(f"Phase already completed: {phase}")
    phase_state.status = "running"
    phase_state.attempt += 1
    phase_state.host_id = host_id or phase_state.host_id or run.assigned_host or run.host_id
    phase_state.runtime_id = runtime_id or phase_state.runtime_id or run.runtime_id
    phase_state.lease_id = lease_id or phase_state.lease_id or run.lease_id
    phase_state.started_at = utc_now_iso()
    phase_state.completed_at = ""
    phase_state.error = ""
    run.status = "running"
    run.updated_at = utc_now_iso()
    return phase_state


def complete_current_phase(
    run: MissionRun,
    *,
    outcome: str = "completed",
    receipt_ref: MissionRunReceiptRef | None = None,
    summary: str = "",
    proof_paths: list[str] | None = None,
    error: str = "",
) -> MissionPhaseTransition:
    from .proofs_c_missions import check_run, check_transition
    check_run(run)
    previous = (run.current_phase, int(run.metadata.get("repair_loop_count") or 0))
    phase = _validate_phase(run.current_phase)
    normalized_outcome = _normalize_outcome(outcome)
    phase_state = _phase_state_for(run, phase)
    if phase_state.status not in {"running", "pending"}:
        raise MissionPhaseTransitionError(f"Phase is not active: {phase}")
    if receipt_ref is not None:
        phase_state.receipt_id = receipt_ref.receipt_id
        phase_state.receipt_path = receipt_ref.path
        phase_state.proof_paths = list(receipt_ref.artifact_paths or proof_paths or [])
        phase_state.summary = summary or receipt_ref.summary
        if not any(item.receipt_id == receipt_ref.receipt_id for item in run.receipts):
            run.receipts.append(receipt_ref)
    else:
        phase_state.proof_paths = list(proof_paths or [])
        phase_state.summary = summary
    next_phase, run_status = _next_phase_and_status(run, phase, normalized_outcome)
    phase_state.error = (
        error
        or (
            "Verifier requested repair, but the configured repair loop limit is exhausted."
            if phase == "verifier" and normalized_outcome == "repair_needed" and run_status == "blocked"
            else ""
        )
    )
    phase_state.completed_at = utc_now_iso()
    phase_state.status = _phase_status_for_outcome(normalized_outcome, run_status=run_status)
    if next_phase:
        run.current_phase = next_phase
        next_state = _phase_state_for(run, next_phase)
        if phase == "repair" and next_phase == "verifier":
            next_state.status = "pending"
            next_state.completed_at = ""
            next_state.error = ""
    run.status = run_status
    if run.status in MISSION_RUN_TERMINAL_STATUSES and not run.completed_at:
        run.completed_at = utc_now_iso()
    run.updated_at = utc_now_iso()
    transition = MissionPhaseTransition(
        schema=MISSION_PHASE_RUNNER_SCHEMA,
        mission_run_id=run.mission_run_id,
        from_phase=phase,
        outcome=normalized_outcome,
        to_phase=run.current_phase,
        run_status=run.status,
        terminal=run.status in MISSION_RUN_TERMINAL_STATUSES,
        summary=summary or phase_state.summary,
    )
    check_transition(run, previous, normalized_outcome, transition)
    return transition


def _next_phase_and_status(run: MissionRun, phase: str, outcome: str) -> tuple[str, str]:
    if outcome == "failed":
        return "", "failed"
    if outcome in {"blocked", "operator_needed"}:
        return "", "blocked"
    if phase == "verifier" and outcome == "repair_needed":
        repair_count = int(run.metadata.get("repair_loop_count") or 0)
        repair_limit = int(run.metadata.get("maximum_repair_loops") or 1)
        if repair_count >= max(0, repair_limit):
            run.metadata["repair_loop_count"] = repair_count
            run.metadata["repair_loop_limit_exhausted"] = True
            return "", "blocked"
        run.metadata["repair_loop_count"] = repair_count + 1
        run.metadata["maximum_repair_loops"] = repair_limit
        run.metadata["repair_loop_limit_exhausted"] = False
        return "repair", "repair_needed"
    if phase == "verifier" and outcome in {"completed", "accepted"}:
        return "final_report", "running"
    if phase == "repair" and outcome == "completed":
        return "verifier", "running"
    if phase == "final_report" and outcome in {"completed", "accepted"}:
        return "", "completed"
    if outcome not in {"completed", "accepted"}:
        raise MissionPhaseTransitionError(f"Unsupported outcome for {phase}: {outcome}")
    current_index = MISSION_RUN_PHASES.index(phase)
    if current_index + 1 >= len(MISSION_RUN_PHASES):
        return "", "completed"
    return MISSION_RUN_PHASES[current_index + 1], "running"


def _phase_state_for(run: MissionRun, phase: str) -> MissionRunPhaseState:
    for state in run.phases:
        if state.phase == phase:
            return state
    state = MissionRunPhaseState(phase=phase)
    run.phases.append(state)
    return state


def _phase_status_for_outcome(outcome: str, *, run_status: str = "") -> str:
    if run_status == "blocked":
        return "blocked"
    if outcome in {"completed", "accepted"}:
        return "completed"
    if outcome == "repair_needed":
        return "completed"
    if outcome in {"blocked", "operator_needed"}:
        return "blocked"
    if outcome == "failed":
        return "failed"
    raise MissionPhaseTransitionError(f"Unsupported phase outcome: {outcome}")


def _validate_phase(phase: str) -> str:
    value = str(phase or "").strip()
    if value not in MISSION_RUN_PHASES:
        raise MissionPhaseTransitionError(f"Unsupported mission run phase: {value or '<missing>'}")
    return value


def _normalize_outcome(outcome: str) -> str:
    value = str(outcome or "").strip().lower()
    if not value:
        return "completed"
    return value
