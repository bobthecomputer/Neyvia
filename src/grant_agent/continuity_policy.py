"""Durable, risk-aware mission continuity for Neyvia.

This is the narrow contract shared by the mission shell, runtime invocation,
Thunder Compute, and marketplace consumers.  It records enough truth to resume
after restart or context compaction without turning the UI into an event dump.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .durability import append_jsonl_durable, atomic_write_json
from .proofs_a_cli import checked

CONTINUITY_SCHEMA = "neyvia.mission_continuity.v1"
CONTINUITY_EVENT_SCHEMA = "neyvia.mission_continuity.event.v1"
RISK_LEVELS = ("lightweight", "standard", "costly", "consequential")
MISSION_STATUSES = (
    "planned",
    "running",
    "approval_waiting",
    "recovering",
    "blocked",
    "failed",
    "completed",
    "stopped",
)
_BASE_RELATIVE = Path(".agent_control") / "neyvia" / "continuity"

DEFAULT_RETRY_LIMITS = {
    "lightweight": 3,
    "standard": 2,
    "costly": 1,
    "consequential": 0,
}
DEFAULT_GPU_POLICY = {
    "maxConcurrentInstances": 1,
    "maxEstimatedHourlyCost": None,
    "maxEstimatedSessionCost": None,
    "maxDurationMinutes": 240,
    "idleReleaseMinutes": 15,
    "minObservationIntervalSeconds": 15,
    "maxConsecutiveUnchangedObservations": 3,
    "requireApprovalForPaidStart": True,
    "requireApprovalForDestructiveAction": True,
    "preferExistingCheckpoint": True,
}
_CONTINUITY_PROCESS_LOCKS_GUARD = threading.Lock()
_CONTINUITY_PROCESS_LOCKS: dict[str, threading.RLock] = {}
DEFAULT_UPDATE_POLICY = {
    "frequency": "meaningful",
    "importance": "normal",
    "verificationDepth": "proportional",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_id(value: object) -> str:
    text = "".join(char if char.isalnum() or char in "._-" else "-" for char in str(value or ""))
    return text.strip(".-")[:160] or f"mission-{uuid.uuid4().hex[:12]}"


def _process_lock_for(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _CONTINUITY_PROCESS_LOCKS_GUARD:
        return _CONTINUITY_PROCESS_LOCKS.setdefault(key, threading.RLock())


def classify_action(action: dict[str, Any]) -> str:
    explicit = str(action.get("risk") or action.get("riskLevel") or "").strip().lower()
    if explicit in RISK_LEVELS:
        return explicit
    kind = str(action.get("kind") or action.get("action") or "").strip().lower()
    if any(token in kind for token in ("delete", "publish", "send", "credential", "expose_port")):
        return "consequential"
    if any(token in kind for token in ("gpu", "paid", "large_download", "training", "instance_start")):
        return "costly"
    if any(token in kind for token in ("edit", "browser", "research", "transfer", "install")):
        return "standard"
    return "lightweight"


@checked('a-cli.continuity.verification')
def proportional_verification(action: dict[str, Any]) -> dict[str, Any]:
    risk = classify_action(action)
    kind = str(action.get("kind") or action.get("action") or "").lower()
    if "transfer" in kind or "copy" in kind:
        checks = ["target_exists", "size_or_hash_matches"]
    elif "gpu" in kind or "training" in kind or "instance" in kind:
        checks = ["instance_and_job_identity", "state_or_logs", "checkpoint_or_artifact", "cost_state"]
    elif "ui" in kind:
        checks = ["focused_build", "one_user_interaction"]
    elif "code" in kind or "edit" in kind:
        checks = ["targeted_changed_behavior", "changed_file_syntax_or_type_check"]
    elif risk == "consequential":
        checks = ["explicit_approval", "strong_result_confirmation"]
    else:
        checks = ["result_exists"]
    return {
        "schema": "neyvia.proportional_verification.v1",
        "risk": risk,
        "checks": checks,
        "avoid": ["unrelated_full_suite", "repetitive_polling"],
    }


@checked('a-cli.continuity.gpu-label')
def classify_gpu_control_action(control_label: object) -> str:
    """Map a provider control label to one continuity-policy action.

    Release verbs are intentionally distinct from inspection.  This keeps a
    user request such as "close the GPUs" from being recorded as a harmless
    read and prevents resume from being confused with allocating a new GPU.
    """

    normalized = " ".join(str(control_label or "").strip().lower().split())
    if any(token in normalized for token in ("delete", "destroy", "remove", "wipe")):
        return "delete_instance"
    if any(
        token in normalized
        for token in ("stop", "close", "terminate", "shut down", "shutdown", "release")
    ):
        return "stop_instance"
    if any(token in normalized for token in ("resume", "continue")):
        return "resume_instance"
    if any(token in normalized for token in ("start", "launch", "create", "allocate")):
        return "start_instance"
    return "inspect_gpu"


class MissionContinuityStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.base = self.root / _BASE_RELATIVE
        self.base.mkdir(parents=True, exist_ok=True)

    def _record_path(self, mission_id: str) -> Path:
        return self.base / f"{_safe_id(mission_id)}.json"

    def _event_path(self, mission_id: str) -> Path:
        return self.base / f"{_safe_id(mission_id)}.events.jsonl"

    def _previous_path(self, mission_id: str) -> Path:
        return self.base / f"{_safe_id(mission_id)}.previous.json"

    @contextmanager
    def _mission_lock(self, mission_id: str) -> Iterator[None]:
        """Serialize one mission's read-modify-write cycle across processes."""
        from .harness_jobs import _exclusive_job_lock
        record_path = self._record_path(mission_id)
        lock_path = record_path.with_suffix(f"{record_path.suffix}.lock")
        process_lock = _process_lock_for(lock_path)
        with process_lock:
            # Use the existing OS-backed lock. Age alone cannot establish that
            # a writer is dead; deleting an old live lock loses checkpoints.
            with _exclusive_job_lock(record_path):
                yield

    def load(self, mission_id: str) -> dict[str, Any] | None:
        current = self._read_record(self._record_path(mission_id))
        if current is not None:
            return current
        previous = self._read_record(self._previous_path(mission_id))
        if previous is None:
            return None
        restored = copy.deepcopy(previous)
        restored["recovery"] = {
            "status": "restored_from_previous_snapshot",
            "at": _now(),
            "reason": "The current continuity snapshot was unreadable.",
        }
        from .proofs_c_missions import check_continuity_recovery
        check_continuity_recovery(restored, previous)
        return restored

    @staticmethod
    def _read_record(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("schema") != CONTINUITY_SCHEMA:
            return None
        return payload

    def create_or_update(
        self,
        mission_id: str,
        *,
        goal: str | None = None,
        patch: dict[str, Any] | None = None,
        event_kind: str = "checkpoint",
    ) -> dict[str, Any]:
        with self._mission_lock(mission_id):
            return self._create_or_update_unlocked(
                mission_id,
                goal=goal,
                patch=patch,
                event_kind=event_kind,
            )

    def _create_or_update_unlocked(
        self,
        mission_id: str,
        *,
        goal: str | None = None,
        patch: dict[str, Any] | None = None,
        event_kind: str = "checkpoint",
    ) -> dict[str, Any]:
        current = self.load(mission_id) or {
            "schema": CONTINUITY_SCHEMA,
            "missionId": _safe_id(mission_id),
            "revision": 0,
            "createdAt": _now(),
            "updatedAt": _now(),
            "goal": str(goal or "").strip(),
            "plan": [],
            "currentStep": "",
            "lastCompletedStep": "",
            "confirmedFacts": [],
            "artifacts": [],
            "toolAttempts": [],
            "latestSafeCheckpoint": None,
            "pendingApproval": None,
            "requiredUserInput": None,
            "nextAction": "",
            "knownFailure": None,
            "recovery": None,
            "status": "planned",
            "retryLimits": copy.deepcopy(DEFAULT_RETRY_LIMITS),
            "gpuPolicy": copy.deepcopy(DEFAULT_GPU_POLICY),
            "updatePolicy": copy.deepcopy(DEFAULT_UPDATE_POLICY),
            "completedIdempotencyKeys": [],
        }
        if goal:
            current["goal"] = str(goal).strip()
        for key, value in (patch or {}).items():
            if key in {
                "schema",
                "missionId",
                "createdAt",
                "revision",
            }:
                continue
            current[key] = copy.deepcopy(value)
        status = str(current.get("status") or "planned")
        if status not in MISSION_STATUSES:
            raise ValueError(f"Unsupported mission continuity status: {status}")
        previous_revision = int(current.get("revision") or 0)
        current["revision"] = previous_revision + 1
        current["updatedAt"] = _now()
        record_path = self._record_path(mission_id)
        previous = self._read_record(record_path)
        if previous is not None:
            atomic_write_json(self._previous_path(mission_id), previous)
        atomic_write_json(record_path, current)
        if previous is None and not self._previous_path(mission_id).exists():
            atomic_write_json(self._previous_path(mission_id), current)
        append_jsonl_durable(
            self._event_path(mission_id),
            {
                "schema": CONTINUITY_EVENT_SCHEMA,
                "missionId": current["missionId"],
                "revision": current["revision"],
                "at": current["updatedAt"],
                "kind": event_kind,
                "status": current["status"],
                "currentStep": current.get("currentStep"),
                "nextAction": current.get("nextAction"),
            },
        )
        from .proofs_c_missions import check_continuity_write
        check_continuity_write(record_path, current, previous, previous_revision)
        return current

    @checked('a-cli.continuity.attempt')
    def record_tool_attempt(
        self,
        mission_id: str,
        *,
        tool: str,
        idempotency_key: str,
        action: dict[str, Any],
        outcome: str,
        evidence: dict[str, Any] | None = None,
        error: str = "",
        alternative: str = "",
    ) -> dict[str, Any]:
        with self._mission_lock(mission_id):
            record = self.load(mission_id) or self._create_or_update_unlocked(mission_id)
            key = str(idempotency_key).strip()
            completed_keys = set(record.get("completedIdempotencyKeys") or [])
            if key and key in completed_keys:
                return {
                    "duplicateSuppressed": True,
                    "detail": "This completed action already has a durable receipt.",
                    "record": record,
                }
            attempts = list(record.get("toolAttempts") or [])
            risk = classify_action(action)
            attempt = {
                "attemptId": f"attempt-{uuid.uuid4().hex[:12]}",
                "at": _now(),
                "tool": str(tool),
                "idempotencyKey": key,
                "action": copy.deepcopy(action),
                "risk": risk,
                "outcome": str(outcome),
                "evidence": copy.deepcopy(evidence or {}),
                "error": str(error),
                "alternative": str(alternative),
                "verification": proportional_verification(action),
            }
            attempts.append(attempt)
            patch: dict[str, Any] = {"toolAttempts": attempts[-100:]}
            if outcome in {"completed", "succeeded", "verified"} and key:
                patch["completedIdempotencyKeys"] = sorted(completed_keys | {key})[-500:]
                patch["knownFailure"] = None
                patch["latestSafeCheckpoint"] = {
                    "at": attempt["at"],
                    "tool": attempt["tool"],
                    "idempotencyKey": key,
                    "evidence": attempt["evidence"],
                }
            elif outcome in {"failed", "error"}:
                patch["knownFailure"] = {
                    "at": attempt["at"],
                    "tool": attempt["tool"],
                    "error": attempt["error"],
                    "evidence": attempt["evidence"],
                }
            updated = self._create_or_update_unlocked(
                mission_id,
                patch=patch,
                event_kind="tool_attempt",
            )
            return {"duplicateSuppressed": False, "attempt": attempt, "record": updated}

    def retry_decision(
        self,
        mission_id: str,
        *,
        tool: str,
        action: dict[str, Any],
        transient: bool,
        alternative_available: bool,
    ) -> dict[str, Any]:
        record = self.load(mission_id) or self.create_or_update(mission_id)
        risk = classify_action(action)
        matching = [
            item
            for item in record.get("toolAttempts") or []
            if item.get("tool") == tool
            and item.get("risk") == risk
            and item.get("outcome") in {"failed", "error"}
        ]
        limit = int((record.get("retryLimits") or DEFAULT_RETRY_LIMITS).get(risk, 0))
        if risk == "consequential":
            decision = "ask_for_authority"
        elif transient and len(matching) < limit:
            decision = "retry"
        elif alternative_available:
            decision = "use_alternative"
        else:
            decision = "blocked"
        return {
            "schema": "neyvia.retry_decision.v1",
            "decision": decision,
            "risk": risk,
            "failedAttempts": len(matching),
            "retryLimit": limit,
            "requiresUser": decision == "ask_for_authority",
        }

    @checked('a-cli.continuity.recovery')
    def recover(self, mission_id: str) -> dict[str, Any]:
        record = self.load(mission_id)
        if record is None:
            return {
                "schema": "neyvia.mission_recovery.v1",
                "missionId": _safe_id(mission_id),
                "status": "missing",
                "nextAction": "Create a continuity record before starting work.",
            }
        attempts = record.get("toolAttempts") or []
        latest = attempts[-1] if attempts else None
        needs_reconcile = bool(
            latest
            and latest.get("risk") in {"costly", "consequential"}
            and latest.get("outcome") not in {"completed", "succeeded", "verified"}
        )
        return {
            "schema": "neyvia.mission_recovery.v1",
            "missionId": record["missionId"],
            "status": "reconcile_required" if needs_reconcile else "resume",
            "goal": record.get("goal"),
            "currentStep": record.get("currentStep"),
            "lastCompletedStep": record.get("lastCompletedStep"),
            "latestSafeCheckpoint": record.get("latestSafeCheckpoint"),
            "pendingApproval": record.get("pendingApproval"),
            "knownFailure": record.get("knownFailure"),
            "nextAction": (
                "Re-observe external state before repeating the last costly action."
                if needs_reconcile
                else record.get("nextAction")
            ),
            "duplicateProtection": record.get("completedIdempotencyKeys") or [],
        }

    @checked('a-cli.continuity.gpu')
    def evaluate_gpu_action(
        self,
        mission_id: str,
        proposal: dict[str, Any],
        observed: dict[str, Any],
    ) -> dict[str, Any]:
        record = self.load(mission_id) or self.create_or_update(mission_id)
        policy = {**DEFAULT_GPU_POLICY, **(record.get("gpuPolicy") or {})}
        action = str(proposal.get("action") or proposal.get("kind") or "").lower()
        current_instances = int(observed.get("runningInstances") or 0)
        estimated_cost = proposal.get("estimatedHourlyCost")
        estimated_duration = float(
            proposal.get("estimatedDurationMinutes")
            or policy.get("maxDurationMinutes")
            or 0
        )
        estimated_session_cost = (
            float(estimated_cost) * estimated_duration / 60
            if estimated_cost is not None and estimated_duration > 0
            else None
        )
        running_duration = float(observed.get("runningDurationMinutes") or 0)
        idle_minutes = float(observed.get("idleMinutes") or 0)
        blockers: list[str] = []
        if action in {"start", "start_instance", "allocate_gpu"}:
            if current_instances >= int(policy["maxConcurrentInstances"]):
                blockers.append("GPU concurrency limit reached.")
            ceiling = policy.get("maxEstimatedHourlyCost")
            if ceiling is not None and estimated_cost is not None and float(estimated_cost) > float(ceiling):
                blockers.append("Estimated hourly cost exceeds the configured limit.")
            session_ceiling = policy.get("maxEstimatedSessionCost")
            if (
                session_ceiling is not None
                and estimated_session_cost is not None
                and estimated_session_cost > float(session_ceiling)
            ):
                blockers.append("Estimated session cost exceeds the configured limit.")
        duration_limit_reached = bool(
            current_instances
            and running_duration >= float(policy["maxDurationMinutes"])
        )
        idle_release_required = bool(
            current_instances
            and idle_minutes >= float(policy["idleReleaseMinutes"])
        )
        if action in {
            "continue",
            "continue_training",
            "resume",
            "resume_instance",
            "resume_training",
        }:
            if duration_limit_reached:
                blockers.append("GPU duration limit reached; checkpoint and release the instance.")
            if idle_release_required:
                blockers.append("GPU idle-release limit reached; release the instance before continuing.")
        observation_action = action in {
            "inspect",
            "inspect_gpu",
            "observe",
            "observe_gpu",
            "poll",
            "poll_gpu",
            "status",
        }
        observation_override = bool(
            proposal.get("urgent")
            or proposal.get("stateChangeExpected")
            or observed.get("stateChangeExpected")
        )
        seconds_since_observation = observed.get("secondsSinceLastObservation")
        unchanged_observations = int(observed.get("consecutiveUnchangedObservations") or 0)
        poll_backoff_required = False
        if observation_action and not observation_override:
            minimum_interval = float(policy["minObservationIntervalSeconds"])
            if (
                seconds_since_observation is not None
                and float(seconds_since_observation) < minimum_interval
            ):
                blockers.append(
                    "GPU state was observed too recently; wait for the bounded poll interval."
                )
                poll_backoff_required = True
            if unchanged_observations >= int(policy["maxConsecutiveUnchangedObservations"]):
                blockers.append(
                    "GPU state is unchanged after the configured observation limit; wait for a provider event or back off."
                )
                poll_backoff_required = True
        existing_checkpoint = bool(observed.get("validCheckpoint"))
        prefer_resume = bool(policy["preferExistingCheckpoint"] and existing_checkpoint)
        destructive = any(token in action for token in ("delete", "destroy", "wipe"))
        paid_start = action in {
            "start",
            "start_instance",
            "allocate_gpu",
            "resume",
            "resume_instance",
            "resume_training",
            "continue_training",
        } and bool(
            proposal.get("paid", True)
        )
        approval_required = bool(
            (paid_start and policy["requireApprovalForPaidStart"])
            or (destructive and policy["requireApprovalForDestructiveAction"])
        )
        result = {
            "schema": "neyvia.gpu_action_decision.v1",
            "allowed": not blockers,
            "approvalRequired": approval_required,
            "preferResume": prefer_resume,
            "releaseRequired": duration_limit_reached or idle_release_required,
            "pollBackoffRequired": poll_backoff_required,
            "releaseReasons": [
                reason
                for condition, reason in (
                    (duration_limit_reached, "duration_limit"),
                    (idle_release_required, "idle_limit"),
                )
                if condition
            ],
            "blockers": blockers,
            "estimatedSessionCost": estimated_session_cost,
            "policy": policy,
            "observed": copy.deepcopy(observed),
            "nextAction": (
                "Checkpoint current work and release the GPU instance."
                if duration_limit_reached or idle_release_required
                else "Wait for a provider event or the next bounded observation interval."
                if poll_backoff_required
                else
                "Resume the existing valid checkpoint."
                if prefer_resume
                else "Request approval before paid or destructive GPU work."
                if approval_required
                else "Proceed within the configured limits."
            ),
        }
        from .proofs_c_missions import check_gpu
        check_gpu(result, proposal, observed)
        return result

    def operator_update(self, mission_id: str) -> dict[str, Any]:
        record = self.load(mission_id) or self.create_or_update(mission_id)
        attempts = record.get("toolAttempts") or []
        latest = attempts[-1] if attempts else {}
        return {
            "schema": "neyvia.mission_update.v1",
            "missionId": record["missionId"],
            "status": record["status"],
            "currentAction": record.get("currentStep") or latest.get("tool") or "Waiting to start",
            "recentProgress": record.get("lastCompletedStep") or "",
            "approval": record.get("pendingApproval"),
            "blocker": record.get("knownFailure"),
            "latestProof": (
                (record.get("latestSafeCheckpoint") or {}).get("evidence")
                or latest.get("evidence")
                or {}
            ),
            "recovery": record.get("recovery"),
            "nextAction": record.get("nextAction") or "",
            "policy": record.get("updatePolicy") or DEFAULT_UPDATE_POLICY,
        }
