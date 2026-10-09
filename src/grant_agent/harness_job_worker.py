from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# The durable launcher executes this file by absolute path.  Bootstrap the
# sealed release's ``src`` directory so a worker never depends on a service
# manager preserving PYTHONPATH across a detach boundary.
if __package__ in {None, ""}:
    _SOURCE_ROOT = Path(__file__).resolve().parents[1]
    _SOURCE_ROOT_TEXT = str(_SOURCE_ROOT)
    while _SOURCE_ROOT_TEXT in sys.path:
        sys.path.remove(_SOURCE_ROOT_TEXT)
    sys.path.insert(0, _SOURCE_ROOT_TEXT)

from grant_agent.harness_execution_capacity import (
    HarnessExecutionCapacity,
    HarnessExecutionLease,
)
from grant_agent.harness_jobs import (
    HarnessJobStore,
    _atomic_write_json,
    _exclusive_job_lock,
    _read_job_payload,
)
from grant_agent.subprocess_utils import install_hidden_subprocess_default


_TERMINAL_JOB_STATES = {
    "cancelled",
    "completed",
    "failed",
    "interrupted",
    "blocked",
}
_TERMINAL_OR_STOPPING_STATUSES = _TERMINAL_JOB_STATES | {"cancelling"}
_BUDGET_ENFORCEMENT_RETRY_INITIAL_SECONDS = 0.25
_BUDGET_ENFORCEMENT_RETRY_MAX_SECONDS = 5.0
_EXECUTION_QUEUE_RECONCILE_INTERVAL_SECONDS = 2.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _remaining_runtime_budget_seconds(
    started_at: object,
    max_runtime_seconds: int,
    *,
    now: datetime | None = None,
) -> float:
    """Return remaining wall-clock budget measured from persisted launch time.

    `HarnessJobStore.start()` persists `startedAt` immediately after `Popen`.
    Measuring from that durable timestamp prevents scheduler/import/lock delay in
    the detached child from granting a fresh full budget.  A malformed persisted
    timestamp fails closed to immediate expiry rather than silently extending a
    hard operator limit.
    """

    if max_runtime_seconds <= 0:
        return 0.0
    started = _parse_utc_timestamp(started_at)
    if started is None:
        return 0.0
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    elapsed = max(0.0, (current - started).total_seconds())
    return max(0.0, float(max_runtime_seconds) - elapsed)


def _hard_runtime_budget_seconds(request: dict[str, Any]) -> int:
    """Return an explicit hard per-run wall-clock limit, or ``0`` for unlimited.

    This deliberately does not reuse provider/runtime request timeouts.  A model
    call timeout and an operator hard run budget have different semantics: the
    latter must stop the whole durable Harness worker tree, not merely one API
    request.  The budget can be supplied either as ``maxRuntimeSeconds`` or
    inside a structured ``budget`` object.
    """

    nested_budget = request.get("budget")
    nested_value = (
        nested_budget.get("maxRuntimeSeconds")
        if isinstance(nested_budget, dict)
        else None
    )
    raw_value = nested_value
    if raw_value is None:
        raw_value = request.get("maxRuntimeSeconds")
    if raw_value is None:
        raw_value = request.get("max_runtime_seconds")
    if raw_value is None or raw_value == "":
        return 0
    if isinstance(raw_value, bool):
        raise ValueError("maxRuntimeSeconds must be a non-negative integer.")
    try:
        seconds = int(str(raw_value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("maxRuntimeSeconds must be a non-negative integer.") from exc
    if seconds < 0:
        raise ValueError("maxRuntimeSeconds must be a non-negative integer.")
    if seconds > threading.TIMEOUT_MAX:
        raise ValueError(
            "maxRuntimeSeconds exceeds the platform-supported watchdog timeout "
            f"of {int(threading.TIMEOUT_MAX)} seconds."
        )
    from grant_agent.proofs_b_harness import check_budget_input
    check_budget_input(request, seconds)
    return seconds


def _arm_runtime_budget(
    store: HarnessJobStore,
    job_id: str,
    request: dict[str, Any],
    *,
    max_runtime_seconds: int,
) -> float | None:
    """Atomically arm a hard budget and return its launch-adjusted remainder."""

    path = store.job_path(job_id)
    with _exclusive_job_lock(path):
        current = _read_job_payload(path, job_id)
        if str(current.get("status") or "").strip().lower() != "running":
            return None
        started_at = str(current.get("startedAt") or "").strip()
        remaining_seconds = _remaining_runtime_budget_seconds(
            started_at,
            max_runtime_seconds,
        )
        budget = (
            dict(request.get("budget"))
            if isinstance(request.get("budget"), dict)
            else {}
        )
        budget.update(
            {
                "maxRuntimeSeconds": max_runtime_seconds,
                "hard": True,
                "status": "active",
                "startedAt": started_at,
                "remainingRuntimeSecondsAtArm": round(remaining_seconds, 3),
            }
        )
        current.update(
            {
                "budget": budget,
                "budgetExhaustedAt": None,
                "budgetOutcome": "armed",
                "updatedAt": _utc_now(),
            }
        )
        _atomic_write_json(path, current)
        return remaining_seconds


def _settle_runtime_budget(
    store: HarnessJobStore,
    job_id: str,
    *,
    status: str,
    outcome: str,
) -> None:
    """Atomically settle a still-active wall-clock budget, best effort.

    Budget metadata is observability, not a second execution gate.  Never turn a
    successful/failed Harness result into a different outcome merely because the
    receipt write becomes unavailable.  The same durable mutation lock used by
    finish/cancel prevents settlement from racing a concurrent stop, and other
    nested budget dimensions are preserved rather than replaced.
    """

    try:
        path = store.job_path(job_id)
        with _exclusive_job_lock(path):
            current = _read_job_payload(path, job_id)
            current_status = str(current.get("status") or "").strip().lower()
            if current_status in _TERMINAL_OR_STOPPING_STATUSES:
                return
            budget = (
                dict(current.get("budget"))
                if isinstance(current.get("budget"), dict)
                else {}
            )
            if str(budget.get("status") or "").strip().lower() != "active":
                return
            max_runtime_seconds = int(budget.get("maxRuntimeSeconds") or 0)
            remaining_seconds = _remaining_runtime_budget_seconds(
                budget.get("startedAt"),
                max_runtime_seconds,
            )
            finished_at = _utc_now()
            budget.update(
                {
                    "status": status,
                    "finishedAt": finished_at,
                    "remainingRuntimeSecondsAtFinish": round(remaining_seconds, 3),
                }
            )
            current.update(
                {
                    "budget": budget,
                    "budgetOutcome": outcome,
                    "updatedAt": finished_at,
                }
            )
            _atomic_write_json(path, current)
    except BaseException:  # noqa: BLE001 - budget receipt must not corrupt outcome
        traceback.print_exc()


def _claim_runtime_budget_exhaustion(
    store: HarnessJobStore,
    job_id: str,
    *,
    max_runtime_seconds: int,
    exhausted_at: str,
) -> bool:
    """Atomically claim expiry before any terminal result can win the race.

    The status check, budget receipt and transition to ``cancelling`` share the
    exact durable mutation lock used by ``finish()`` and ``cancel()``.  If normal
    completion already committed, this returns ``False`` and does not stamp the
    terminal job as exhausted.  A pending cancellation is not terminal: if its
    process-tree stop failed and the hard deadline later arrives, the still-active
    budget must become exhausted and retry enforcement rather than disappearing.
    If expiry wins, a concurrent/late ``finish()`` sees ``cancelling`` and cannot
    fabricate successful completion.
    """

    path = store.job_path(job_id)
    with _exclusive_job_lock(path):
        current = _read_job_payload(path, job_id)
        status = str(current.get("status") or "").strip().lower()
        if status in _TERMINAL_JOB_STATES:
            return False
        budget = (
            dict(current.get("budget"))
            if isinstance(current.get("budget"), dict)
            else {}
        )
        if str(budget.get("status") or "").strip().lower() != "active":
            return False
        budget.update(
            {
                "maxRuntimeSeconds": max_runtime_seconds,
                "hard": True,
                "status": "exhausted",
                "exhaustedAt": exhausted_at,
                "remainingRuntimeSecondsAtFinish": 0.0,
            }
        )
        current.update(
            {
                "status": "cancelling",
                "budget": budget,
                "stopReason": "runtime_budget",
                "cancelReason": "runtime_budget",
                "budgetExhaustedAt": exhausted_at,
                "budgetOutcome": "termination-requested",
                "cancelRequestedAt": current.get("cancelRequestedAt") or exhausted_at,
                "updatedAt": exhausted_at,
            }
        )
        _atomic_write_json(path, current)
        return True


def _record_runtime_budget_enforcement_failure(
    store: HarnessJobStore,
    job_id: str,
    *,
    attempt: int,
    error: BaseException,
) -> bool:
    """Persist retry evidence while a hard budget still needs enforcement."""

    path = store.job_path(job_id)
    with _exclusive_job_lock(path):
        current = _read_job_payload(path, job_id)
        status = str(current.get("status") or "").strip().lower()
        if status in _TERMINAL_JOB_STATES:
            return False
        budget = (
            dict(current.get("budget"))
            if isinstance(current.get("budget"), dict)
            else {}
        )
        budget_status = str(budget.get("status") or "").strip().lower()
        if budget_status not in {"active", "exhausted"}:
            return False
        now = _utc_now()
        current.update(
            {
                "budgetOutcome": (
                    "enforcement-retrying"
                    if budget_status == "exhausted"
                    else "expiry-claim-retrying"
                ),
                "budgetEnforcementAttempts": attempt,
                "budgetEnforcementError": (
                    f"{type(error).__name__}: {error}"
                )[:4000],
                "budgetLastEnforcementAttemptAt": now,
                "updatedAt": now,
            }
        )
        _atomic_write_json(path, current)
        return True


def _record_runtime_budget_enforced(
    store: HarnessJobStore,
    job_id: str,
) -> None:
    """Mark a returned cancellation as enforced without erasing retry evidence."""

    try:
        path = store.job_path(job_id)
        with _exclusive_job_lock(path):
            current = _read_job_payload(path, job_id)
            status = str(current.get("status") or "").strip().lower()
            budget = (
                dict(current.get("budget"))
                if isinstance(current.get("budget"), dict)
                else {}
            )
            if status not in _TERMINAL_JOB_STATES:
                return
            if str(budget.get("status") or "").strip().lower() != "exhausted":
                return
            now = _utc_now()
            current.update(
                {
                    "budgetOutcome": "enforced",
                    "budgetEnforcedAt": now,
                    "updatedAt": now,
                }
            )
            _atomic_write_json(path, current)
    except BaseException:  # noqa: BLE001 - terminal receipt already exists
        traceback.print_exc()


def _budget_enforcement_retry_delay(attempt: int) -> float:
    return min(
        _BUDGET_ENFORCEMENT_RETRY_MAX_SECONDS,
        _BUDGET_ENFORCEMENT_RETRY_INITIAL_SECONDS
        * (2 ** min(max(0, attempt - 1), 5)),
    )


def _start_runtime_budget_watchdog(
    store: HarnessJobStore,
    job_id: str,
    max_runtime_seconds: int,
    stop_event: threading.Event,
    *,
    wait_seconds: float | None = None,
) -> threading.Thread | None:
    """Stop the durable worker tree after an operator-declared hard run budget.

    The watchdog lives inside the detached worker rather than the Neyvia client
    or web backend, so closing the UI does not silently disable enforcement.  It
    atomically claims exhaustion before requesting process-tree cancellation;
    transient enforcement failures are durably attributed and retried with
    bounded backoff until the job is terminal.
    """

    if max_runtime_seconds <= 0:
        return None
    delay_seconds = (
        float(max_runtime_seconds)
        if wait_seconds is None
        else max(0.0, float(wait_seconds))
    )

    def _watch() -> None:
        if delay_seconds > 0 and stop_event.wait(delay_seconds):
            return
        exhausted_at = _utc_now()

        claim_attempt = 1
        while True:
            try:
                claimed = _claim_runtime_budget_exhaustion(
                    store,
                    job_id,
                    max_runtime_seconds=max_runtime_seconds,
                    exhausted_at=exhausted_at,
                )
            except BaseException as exc:  # noqa: BLE001 - retryable durable boundary
                try:
                    should_retry = _record_runtime_budget_enforcement_failure(
                        store,
                        job_id,
                        attempt=claim_attempt,
                        error=exc,
                    )
                except BaseException:  # noqa: BLE001 - do not lose the retry loop
                    traceback.print_exc()
                    should_retry = True
                if not should_retry:
                    return
                time.sleep(_budget_enforcement_retry_delay(claim_attempt))
                claim_attempt += 1
                continue
            if not claimed:
                return
            break

        cancel_attempt = 1
        while True:
            try:
                result = store.cancel(job_id)
                status = str(result.get("status") or "").strip().lower()
                if status in _TERMINAL_JOB_STATES:
                    _record_runtime_budget_enforced(store, job_id)
                    return
                raise RuntimeError(
                    f"Budget cancellation returned non-terminal status {status or 'unknown'}."
                )
            except BaseException as exc:  # noqa: BLE001 - hard-limit enforcement loop
                try:
                    should_retry = _record_runtime_budget_enforcement_failure(
                        store,
                        job_id,
                        attempt=cancel_attempt,
                        error=exc,
                    )
                except BaseException:  # noqa: BLE001 - do not lose the retry loop
                    traceback.print_exc()
                    should_retry = True
                if not should_retry:
                    return
                time.sleep(_budget_enforcement_retry_delay(cancel_attempt))
                cancel_attempt += 1

    thread = threading.Thread(
        target=_watch,
        name=f"neyvia-hard-runtime-budget-{job_id[-12:]}",
        daemon=True,
    )
    thread.start()
    return thread


def _execution_result_status(result: dict[str, Any]) -> str:
    """Read lifecycle status from both orchestration and Direct wrapper shapes."""

    direct = str(result.get("status") or "").strip().lower()
    if direct:
        return direct
    nested = result.get("result")
    if isinstance(nested, dict):
        nested_status = str(nested.get("status") or "").strip().lower()
        if nested_status:
            return nested_status
    invocation = result.get("invocation")
    if isinstance(invocation, dict):
        invocation_state = str(invocation.get("state") or "").strip().lower()
        if invocation_state in {
            "blocked",
            "interrupted",
            "failed",
            "error",
            "completed",
            "closed",
        }:
            return invocation_state
    return ""


def _execution_result_detail(result: dict[str, Any], status: str) -> str:
    nested = result.get("result")
    nested = nested if isinstance(nested, dict) else {}
    return str(
        result.get("error")
        or result.get("detail")
        or result.get("message")
        or nested.get("error")
        or nested.get("detail")
        or nested.get("message")
        or f"Harness execution ended with status {status}."
    )


def _mark_waiting_for_execution_capacity(
    store: HarnessJobStore,
    job_id: str,
    *,
    max_running_jobs: int,
) -> bool:
    """Persist a worker-owned execution wait without reopening launch admission."""

    path = store.job_path(job_id)
    with _exclusive_job_lock(path):
        current = _read_job_payload(path, job_id)
        status = str(current.get("status") or "").strip().lower()
        if status in _TERMINAL_OR_STOPPING_STATUSES:
            return False
        queue = (
            dict(current.get("executionQueue"))
            if isinstance(current.get("executionQueue"), dict)
            else {}
        )
        now = _utc_now()
        queue.update(
            {
                "schema": "neyvia.harness_execution_queue.v1",
                "state": "waiting",
                "policy": "fifo-bounded",
                "enqueuedAt": queue.get("enqueuedAt") or now,
                "maxRunningJobs": max_running_jobs,
            }
        )
        current.update(
            {
                "status": "running",
                "pid": os.getpid(),
                "waitingReason": "execution-capacity",
                "executionQueue": queue,
                "updatedAt": now,
            }
        )
        _atomic_write_json(path, current)
        return True


def _refresh_execution_queue_snapshot(
    store: HarnessJobStore,
    job_id: str,
    snapshot: dict[str, Any],
) -> bool:
    path = store.job_path(job_id)
    with _exclusive_job_lock(path):
        current = _read_job_payload(path, job_id)
        status = str(current.get("status") or "").strip().lower()
        if status in _TERMINAL_OR_STOPPING_STATUSES:
            return False
        queue = (
            dict(current.get("executionQueue"))
            if isinstance(current.get("executionQueue"), dict)
            else {}
        )
        raw_position = int(snapshot.get("queuePosition") or 0)
        queue.update(
            {
                "schema": "neyvia.harness_execution_queue.v1",
                "state": "waiting",
                "policy": str(snapshot.get("policy") or "fifo-bounded"),
                "enqueuedAt": queue.get("enqueuedAt") or _utc_now(),
                "position": raw_position + 1 if raw_position >= 0 else None,
                "depth": int(snapshot.get("queueDepth") or 0),
                "maxRunningJobs": int(snapshot.get("maxRunningJobs") or 0),
                "legacyOrUnknownActive": int(
                    snapshot.get("legacyOrUnknownActive") or 0
                ),
                "reason": str(snapshot.get("reason") or "waiting"),
                "observedAt": _utc_now(),
            }
        )
        current.update(
            {
                "status": "running",
                "pid": os.getpid(),
                "waitingReason": "execution-capacity",
                "executionQueue": queue,
                "updatedAt": _utc_now(),
            }
        )
        _atomic_write_json(path, current)
        return True


def _claim_execution_capacity(
    store: HarnessJobStore,
    job_id: str,
    lease: HarnessExecutionLease,
) -> bool:
    """Bind a held OS slot to the durable run without reviving cancellation."""

    started = store.mark_started(job_id, pid=os.getpid())
    status = str(started.get("status") or "").strip().lower()
    if status in _TERMINAL_OR_STOPPING_STATUSES:
        return False
    path = store.job_path(job_id)
    with _exclusive_job_lock(path):
        current = _read_job_payload(path, job_id)
        status = str(current.get("status") or "").strip().lower()
        if status != "running" or int(current.get("pid") or 0) != os.getpid():
            return False
        now = _utc_now()
        queue = (
            dict(current.get("executionQueue"))
            if isinstance(current.get("executionQueue"), dict)
            else {}
        )
        queue.update(
            {
                "state": "dispatched",
                "dispatchedAt": now,
                "position": 0,
            }
        )
        current.update(
            {
                "waitingReason": "",
                "executionStartedAt": current.get("executionStartedAt") or now,
                "executionQueue": queue,
                "executionCapacity": {
                    "schema": "neyvia.harness_execution_capacity.v1",
                    "state": "active",
                    "policy": "fifo-bounded",
                    "slot": lease.slot,
                    "maxRunningJobs": lease.max_running_jobs,
                    "ownerPid": os.getpid(),
                    "acquiredAt": lease.acquired_at,
                },
                "updatedAt": now,
            }
        )
        _atomic_write_json(path, current)
        return True


def _record_execution_capacity_release(
    store: HarnessJobStore,
    job_id: str,
    lease: HarnessExecutionLease,
) -> None:
    """Record release best-effort; the OS lock remains the authority."""

    try:
        path = store.job_path(job_id)
        with _exclusive_job_lock(path):
            current = _read_job_payload(path, job_id)
            capacity = (
                dict(current.get("executionCapacity"))
                if isinstance(current.get("executionCapacity"), dict)
                else {}
            )
            if (
                str(capacity.get("state") or "").strip().lower() != "active"
                or int(capacity.get("slot") or -1) != lease.slot
            ):
                return
            now = _utc_now()
            capacity.update(
                {
                    "state": "released",
                    "releasedAt": now,
                    "ownerPid": None,
                }
            )
            current["executionCapacity"] = capacity
            current["executionFinishedAt"] = (
                current.get("executionFinishedAt") or now
            )
            current["updatedAt"] = now
            _atomic_write_json(path, current)
    except BaseException:  # noqa: BLE001 - releasing the OS lease is more important
        traceback.print_exc()


def _wait_for_execution_capacity(
    store: HarnessJobStore,
    root: Path,
    job_id: str,
) -> HarnessExecutionLease | None:
    """Queue this worker until the workspace can safely run expensive work."""

    controller = HarnessExecutionCapacity(root)
    max_running_jobs = controller.effective_limit()
    if not _mark_waiting_for_execution_capacity(
        store,
        job_id,
        max_running_jobs=max_running_jobs,
    ):
        return None

    attempt = 0
    last_reconcile = 0.0
    while True:
        current = store.load(job_id, reconcile=False)
        status = str(current.get("status") or "").strip().lower()
        if status in _TERMINAL_OR_STOPPING_STATUSES:
            return None

        lease, snapshot = controller.try_acquire(job_id)
        if lease is not None:
            if _claim_execution_capacity(store, job_id, lease):
                return lease
            lease.release()
            return None

        now_monotonic = time.monotonic()
        if now_monotonic - last_reconcile >= _EXECUTION_QUEUE_RECONCILE_INTERVAL_SECONDS:
            # Reuse the existing fail-closed liveness/identity reconciliation only
            # after a dispatch attempt is actually blocked. An immediately
            # dispatchable worker must not depend on command-line reconciliation,
            # and stale predecessors are still cleared before the next attempt.
            store._reconcile_admission_receipts()
            last_reconcile = now_monotonic
        if not _refresh_execution_queue_snapshot(store, job_id, snapshot):
            return None
        time.sleep(controller.wait_delay_seconds(attempt))
        attempt += 1


def run_harness_job(root: Path, job_id: str) -> int:
    store = HarnessJobStore(root)
    job = store.load(job_id, reconcile=False)
    job = store.mark_started(
        job_id,
        pid=os.getpid(),
    )
    if job.get("status") in {
        "cancelling",
        "cancelled",
        "completed",
        "failed",
        "interrupted",
        "blocked",
    }:
        return 0
    request = job.get("request")
    if not isinstance(request, dict):
        store.finish(job_id, error="Harness job request is missing or invalid.")
        return 2

    try:
        hard_runtime_seconds = _hard_runtime_budget_seconds(request)
    except ValueError as exc:
        store.finish(job_id, error=f"Invalid hard runtime budget: {exc}")
        return 2

    budget_stop = threading.Event()
    budget_thread: threading.Thread | None = None
    if hard_runtime_seconds > 0:
        remaining_runtime_seconds = _arm_runtime_budget(
            store,
            job_id,
            request,
            max_runtime_seconds=hard_runtime_seconds,
        )
        if remaining_runtime_seconds is None:
            current = store.load(job_id, reconcile=False)
            current_status = str(current.get("status") or "").strip().lower()
            if current_status in _TERMINAL_OR_STOPPING_STATUSES:
                return 0
            store.finish(
                job_id,
                error="Hard runtime budget could not be armed safely for this Harness run.",
            )
            return 2
        budget_thread = _start_runtime_budget_watchdog(
            store,
            job_id,
            hard_runtime_seconds,
            budget_stop,
            wait_seconds=remaining_runtime_seconds,
        )

    def disarm_budget_watchdog() -> None:
        budget_stop.set()
        if budget_thread is not None and budget_thread is not threading.current_thread():
            # Do not allow a timer that has already crossed its deadline to race
            # terminal result persistence.  Before the deadline this returns
            # immediately because stop_event wakes the watchdog.  After the
            # deadline the watchdog owns cancellation and this join prevents a
            # late successful receipt from bypassing hard-limit enforcement.
            budget_thread.join()

    execution_lease: HarnessExecutionLease | None = None
    try:
        try:
            execution_lease = _wait_for_execution_capacity(store, root, job_id)
        except BaseException as exc:  # noqa: BLE001 - hard capacity boundary
            current = store.load(job_id, reconcile=False)
            current_status = str(current.get("status") or "").strip().lower()
            if current_status in _TERMINAL_OR_STOPPING_STATUSES:
                return 0
            disarm_budget_watchdog()
            _settle_runtime_budget(
                store,
                job_id,
                status="released",
                outcome="execution-capacity-failed-before-budget",
            )
            store.finish(
                job_id,
                error=(
                    "Harness execution capacity could not be established safely: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
            return 2

        if execution_lease is None:
            return 0

        # Import here so the worker process starts with its durable job record
        # already visible, even if importing the broader backend fails.
        from grant_agent.web_backend import FluxioWebBackend

        backend = FluxioWebBackend(
            root=root,
            static_root=root / "web" / "dist",
        )
        if request.get("conductor") is True:
            from grant_agent.neyvia_conductor import execute
            result = execute(backend, store, job_id)
        elif str(job.get("mode") or "").strip().lower() == "orchestration":
            result: dict[str, Any] = backend._run_runtime_lane_cycle(request)
        else:
            result = backend._run_agent_chat(request, allow_mutation=False)
        result_status = _execution_result_status(result)
        if result_status and not str(result.get("status") or "").strip():
            # Direct chat wraps its compact provider result under `result` while
            # orchestration returns status at the top level. Normalize only the
            # lifecycle field so the durable receipt and budget settlement see
            # the same outcome without discarding the original wrapper evidence.
            result = {**result, "status": result_status}
        disarm_budget_watchdog()
        if result_status in {"failed", "error", "blocked", "interrupted"}:
            _settle_runtime_budget(
                store,
                job_id,
                status="released",
                outcome="execution-ended-before-budget",
            )
            detail = _execution_result_detail(result, result_status)
            store.finish(job_id, result=result, error=detail)
            return 1
        _settle_runtime_budget(
            store,
            job_id,
            status="satisfied",
            outcome="completed-within-budget",
        )
        store.finish(job_id, result=result)
        return 0
    except BaseException as exc:  # noqa: BLE001 - durable worker boundary
        disarm_budget_watchdog()
        _settle_runtime_budget(
            store,
            job_id,
            status="released",
            outcome="execution-ended-before-budget",
        )
        detail = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        store.finish(job_id, error=detail)
        return 1
    finally:
        disarm_budget_watchdog()
        if execution_lease is not None:
            _record_execution_capacity_release(store, job_id, execution_lease)
            execution_lease.release()


def main(argv: list[str] | None = None) -> int:
    install_hidden_subprocess_default()
    parser = argparse.ArgumentParser(description="Run one durable NEYVIA Harness job.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    return run_harness_job(Path(args.root), args.job_id)


if __name__ == "__main__":
    raise SystemExit(main())
