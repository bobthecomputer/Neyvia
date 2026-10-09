from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .harness_jobs import (
    HARNESS_JOB_SCHEMA,
    MAX_HARNESS_JOBS,
    _atomic_write_json,
    _exclusive_job_lock,
    _release_advisory_job_lock,
    _try_advisory_job_lock,
)


HARNESS_EXECUTION_POLICY_SCHEMA = "neyvia.harness_execution_policy.v1"
HARNESS_EXECUTION_SLOT_SCHEMA = "neyvia.harness_execution_slot.v1"
DEFAULT_MAX_RUNNING_HARNESS_JOBS = 4


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _normalize_running_limit(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Harness running-job limit must be an integer.")
    try:
        limit = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("Harness running-job limit must be an integer.") from exc
    if limit < 1:
        raise ValueError("Harness running-job limit must be at least 1.")
    if limit > MAX_HARNESS_JOBS:
        raise ValueError(
            f"Harness running-job limit cannot exceed {MAX_HARNESS_JOBS}."
        )
    return limit


def _safe_receipt(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != HARNESS_JOB_SCHEMA:
        return None
    return raw


@dataclass
class HarnessExecutionLease:
    """One crash-released execution slot held by a detached Harness worker."""

    descriptor: int
    path: Path
    slot: int
    job_id: str
    max_running_jobs: int
    acquired_at: str
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        released_at = _utc_now()
        try:
            os.lseek(self.descriptor, 0, os.SEEK_SET)
            os.ftruncate(self.descriptor, 0)
            os.write(
                self.descriptor,
                (
                    json.dumps(
                        {
                            "schema": HARNESS_EXECUTION_SLOT_SCHEMA,
                            "slot": self.slot,
                            "state": "available",
                            "releasedAt": released_at,
                            "previousJobId": self.job_id,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8"),
            )
            try:
                os.fsync(self.descriptor)
            except OSError:
                pass
        finally:
            try:
                _release_advisory_job_lock(self.descriptor)
            finally:
                os.close(self.descriptor)

    def __enter__(self) -> "HarnessExecutionLease":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()


class HarnessExecutionCapacity:
    """Crash-safe, fail-closed admission for expensive Harness execution.

    Open-run admission and execution concurrency are deliberately separate. A
    workspace may retain many queued/blocked runs while allowing only a small
    number to enter provider/model/runtime execution at once. The hard running
    limit is persisted with monotonic tightening so differently configured
    same-version workers cannot silently expand capacity.

    The implementation uses bounded OS advisory slot locks rather than a daemon
    semaphore. A worker crash therefore releases its execution slot at the OS
    boundary. Durable receipt metadata remains evidence, but stale metadata is
    never treated as ownership of a slot.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_running_jobs: int | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve(strict=True)
        self.jobs_root = self.root / ".agent_control" / "harness_jobs"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        configured: object = max_running_jobs
        if configured is None:
            configured = os.environ.get(
                "NEYVIA_MAX_RUNNING_HARNESS_JOBS",
                DEFAULT_MAX_RUNNING_HARNESS_JOBS,
            )
        self.requested_max_running_jobs = _normalize_running_limit(configured)
        self.max_running_jobs = self.requested_max_running_jobs
        self.slots_root = self.jobs_root / ".execution-slots"
        self.slots_root.mkdir(parents=True, exist_ok=True)

    def _dispatch_lock_path(self) -> Path:
        return self.jobs_root / ".harness-execution-dispatch"

    def _policy_path(self) -> Path:
        return self.jobs_root / ".harness-execution-policy.json"

    def _sync_policy_locked(self) -> int:
        path = self._policy_path()
        requested = self.requested_max_running_jobs
        now = _utc_now()
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Harness execution policy is unreadable. Neyvia refused to guess "
                "how many expensive Harness runs may execute concurrently."
            ) from exc

        if raw is None:
            policy = {
                "schema": HARNESS_EXECUTION_POLICY_SCHEMA,
                "maxRunningJobs": requested,
                "createdAt": now,
                "updatedAt": now,
                "mode": "monotonic-tighten",
            }
            _atomic_write_json(path, policy)
            self.max_running_jobs = requested
            return requested

        if not isinstance(raw, dict) or raw.get("schema") != HARNESS_EXECUTION_POLICY_SCHEMA:
            raise RuntimeError(
                "Harness execution policy has an unsupported schema. Neyvia refused "
                "to guess a hard running limit."
            )
        try:
            persisted = _normalize_running_limit(raw.get("maxRunningJobs"))
        except ValueError as exc:
            raise RuntimeError(
                "Harness execution policy contains an invalid hard running limit."
            ) from exc

        effective = min(persisted, requested)
        if effective < persisted:
            updated = dict(raw)
            updated.update(
                {
                    "maxRunningJobs": effective,
                    "previousMaxRunningJobs": persisted,
                    "tightenedAt": now,
                    "updatedAt": now,
                    "mode": "monotonic-tighten",
                }
            )
            _atomic_write_json(path, updated)
        self.max_running_jobs = effective
        return effective

    def effective_limit(self) -> int:
        with _exclusive_job_lock(self._dispatch_lock_path()):
            return self._sync_policy_locked()

    def _queue_rows_locked(self) -> tuple[list[tuple[str, str]], int, int]:
        waiters: list[tuple[str, str]] = []
        legacy_or_unknown_active = 0
        unreadable = 0
        for path in self.jobs_root.glob("harness-job-*.json"):
            payload = _safe_receipt(path)
            if payload is None:
                # Execution admission is intentionally fail-closed. An unreadable
                # durable run may be consuming provider/CPU/GPU resources, so it
                # occupies one running slot until repaired or safely reconciled.
                unreadable += 1
                legacy_or_unknown_active += 1
                continue
            status = str(payload.get("status") or "unknown").strip().lower() or "unknown"
            if (
                status in {"queued", "running"}
                and str(payload.get("waitingReason") or "").strip().lower()
                == "execution-capacity"
            ):
                # Current workers stay lifecycle-running while their detached
                # process waits for an expensive-execution slot. Accept the older
                # queued form too so an interrupted rollout cannot strand a waiter.
                queue = payload.get("executionQueue")
                queue = queue if isinstance(queue, dict) else {}
                enqueued_at = str(
                    queue.get("enqueuedAt") or payload.get("createdAt") or ""
                )
                waiters.append((enqueued_at, str(payload.get("id") or path.stem)))
                continue
            if status not in {"running", "cancelling"}:
                continue
            capacity = payload.get("executionCapacity")
            capacity = capacity if isinstance(capacity, dict) else {}
            if str(capacity.get("state") or "").strip().lower() == "active":
                # New-version workers are accounted for by the OS slot lock, not
                # by possibly stale receipt metadata. A crash releases the lock.
                continue
            # A live/unknown older-version run has no slot lock. Reserve capacity
            # for it so deploying the scheduler cannot oversubscribe an already
            # active workspace during a rolling/mixed-version transition.
            legacy_or_unknown_active += 1
        waiters.sort(key=lambda row: (row[0], row[1]))
        return waiters, legacy_or_unknown_active, unreadable

    def _slot_path(self, slot: int) -> Path:
        return self.slots_root / f"slot-{slot:03d}.guard"

    def try_acquire(self, job_id: str) -> tuple[HarnessExecutionLease | None, dict[str, Any]]:
        """Try once to dispatch the oldest waiting run into a free execution slot."""

        with _exclusive_job_lock(self._dispatch_lock_path()):
            max_running = self._sync_policy_locked()
            waiters, legacy_active, unreadable = self._queue_rows_locked()
            waiter_ids = [row[1] for row in waiters]
            try:
                queue_position = waiter_ids.index(job_id)
            except ValueError:
                queue_position = -1

            active_new_slots = 0
            slot_flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
            for slot in range(1, max_running + 1):
                descriptor = os.open(self._slot_path(slot), slot_flags, 0o600)
                try:
                    acquired = _try_advisory_job_lock(descriptor)
                    if acquired:
                        _release_advisory_job_lock(descriptor)
                    else:
                        active_new_slots += 1
                finally:
                    os.close(descriptor)

            available_new_slots = max(
                0,
                max_running - legacy_active - active_new_slots,
            )
            snapshot: dict[str, Any] = {
                "policy": "fifo-bounded",
                "maxRunningJobs": max_running,
                "legacyOrUnknownActive": legacy_active,
                "activeNewSlots": active_new_slots,
                "unreadableJobs": unreadable,
                "queueDepth": len(waiters),
                "queuePosition": queue_position,
                "availableNewSlots": available_new_slots,
                "state": "waiting",
            }
            from .proofs_b_harness import check_execution_snapshot
            check_execution_snapshot(snapshot, waiter_ids, job_id)
            if queue_position < 0:
                snapshot["reason"] = "job-not-in-execution-queue"
                return None, snapshot
            if queue_position > 0:
                snapshot["reason"] = "fifo-predecessor"
                return None, snapshot
            if available_new_slots <= 0:
                snapshot["reason"] = (
                    "all-new-version-slots-busy"
                    if active_new_slots > 0
                    else "running-capacity-exhausted"
                )
                return None, snapshot

            # Slot ids are intentionally one-based. Besides being clearer in
            # receipts/support evidence, this avoids a valid first slot being
            # confused with a falsey/missing sentinel by older observability code.
            for slot in range(1, max_running + 1):
                path = self._slot_path(slot)
                flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
                descriptor = os.open(path, flags, 0o600)
                try:
                    acquired = _try_advisory_job_lock(descriptor)
                except BaseException:
                    os.close(descriptor)
                    raise
                if not acquired:
                    os.close(descriptor)
                    continue
                acquired_at = _utc_now()
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.ftruncate(descriptor, 0)
                os.write(
                    descriptor,
                    (
                        json.dumps(
                            {
                                "schema": HARNESS_EXECUTION_SLOT_SCHEMA,
                                "slot": slot,
                                "state": "active",
                                "jobId": job_id,
                                "pid": os.getpid(),
                                "maxRunningJobs": max_running,
                                "acquiredAt": acquired_at,
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    ).encode("utf-8"),
                )
                try:
                    os.fsync(descriptor)
                except OSError:
                    pass
                snapshot.update(
                    {
                        "state": "dispatched",
                        "reason": "slot-acquired",
                        "slot": slot,
                    }
                )
                return (
                    HarnessExecutionLease(
                        descriptor=descriptor,
                        path=path,
                        slot=slot,
                        job_id=job_id,
                        max_running_jobs=max_running,
                        acquired_at=acquired_at,
                    ),
                    snapshot,
                )

            snapshot["reason"] = "all-new-version-slots-busy"
            return None, snapshot

    def wait_delay_seconds(self, attempt: int) -> float:
        """Bound polling load while keeping capacity release responsive."""

        return min(1.0, 0.1 * (1.35 ** min(max(0, attempt), 12)))
