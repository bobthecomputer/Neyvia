from __future__ import annotations

import errno
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .subprocess_utils import hidden_windows_subprocess_kwargs


HARNESS_JOB_SCHEMA = "neyvia.harness_job.v1"
HARNESS_ADMISSION_POLICY_SCHEMA = "neyvia.harness_admission_policy.v1"
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
WORKER_STOPPED_JOB_STATUSES = TERMINAL_JOB_STATUSES | {"blocked"}
MAX_HARNESS_JOBS = 100
MAX_OPEN_HARNESS_JOBS = 32
SECURITY_ONLY_HARNESSES = {"rook", "wallbreaker"}
HARNESS_JOB_LOCK_TIMEOUT_SECONDS = 10.0
HARNESS_JOB_LOCK_POLL_SECONDS = 0.05
HARNESS_JOB_LOCK_LEGACY_STALE_SECONDS = 60.0
HARNESS_JOB_LOCK_HEARTBEAT_SECONDS = 15.0
HARNESS_JOB_LOCK_GUARD_SHARDS = 64


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _duration_ms(start: object, finish: object) -> int | None:
    started = _timestamp(start)
    finished = _timestamp(finish)
    if started is None or finished is None:
        return None
    return max(0, round((finished - started).total_seconds() * 1000))


def _with_job_observability(payload: dict[str, Any]) -> dict[str, Any]:
    """Derive truthful metrics without mutating legacy durable receipts."""

    observed = dict(payload)
    status = str(observed.get("status") or "queued").strip().lower() or "queued"
    created_at = observed.get("createdAt")
    started_at = observed.get("startedAt")
    finished_at = observed.get("finishedAt")
    reference_at = finished_at or observed.get("updatedAt") or created_at
    timeline: list[dict[str, Any]] = []

    def add_phase(phase: str, label: str, at: object) -> None:
        if not at:
            return
        timeline.append(
            {
                "phase": phase,
                "label": label,
                "at": str(at),
                "elapsedMs": _duration_ms(created_at, at) or 0,
            }
        )

    add_phase("queued", "Saved", created_at)
    add_phase("running", "Worker started", started_at)
    cancel_requested_at = observed.get("cancelRequestedAt")
    if cancel_requested_at:
        add_phase("cancelling", "Cancellation requested", cancel_requested_at)
    if finished_at:
        add_phase(status, status.replace("-", " ").title(), finished_at)

    terminal = status in TERMINAL_JOB_STATUSES
    receipt_present = bool(
        isinstance(observed.get("result"), dict)
        and observed.get("result")
    )
    observed["metrics"] = {
        "queueLatencyMs": _duration_ms(created_at, started_at),
        "executionDurationMs": _duration_ms(started_at, finished_at or reference_at),
        "totalDurationMs": _duration_ms(created_at, finished_at or reference_at),
        "receiptPresent": receipt_present,
        "terminal": terminal,
        "timelinePhaseCount": len(timeline),
    }
    observed["timeline"] = timeline
    from .proofs_b_harness import check_observation
    check_observation(payload, observed)
    return observed


def _safe_id(value: object, fallback: str = "harness-job") -> str:
    text = "".join(
        character
        for character in str(value or "").strip()
        if character.isalnum() or character in {"-", "_"}
    )
    return (text[:100] or fallback).lower()


def _normalize_open_job_limit(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Harness open-job limit must be an integer.")
    try:
        limit = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("Harness open-job limit must be an integer.") from exc
    if limit < 1:
        raise ValueError("Harness open-job limit must be at least 1.")
    if limit > MAX_HARNESS_JOBS:
        raise ValueError(
            f"Harness open-job limit cannot exceed the visible retention bound of {MAX_HARNESS_JOBS}."
        )
    return limit


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    from .proofs_b_harness import check_write
    check_write(path, payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    )
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    # Windows readers (dashboard polling included) can briefly hold a handle
    # without FILE_SHARE_DELETE. Retry the atomic replace, never a partial write.
    for attempt in range(20):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if os.name != "nt" or attempt == 19:
                raise
            time.sleep(0.05)


def _release_active_budget_on_cancellation(
    payload: dict[str, Any],
    now: str,
) -> bool:
    """Settle an active run budget only once cancellation is terminal.

    Runtime-budget expiry marks the budget ``exhausted`` before it calls the
    shared cancellation path.  This helper therefore releases only ``active``
    budgets and deliberately leaves exhausted evidence untouched.  Keeping the
    mutation inside the same durable job lock prevents a terminal cancelled job
    from being persisted with a misleading still-active budget.
    """

    budget_value = payload.get("budget")
    if not isinstance(budget_value, dict):
        return False
    budget = dict(budget_value)
    if str(budget.get("status") or "").strip().lower() != "active":
        return False
    budget.update(
        {
            "status": "released",
            "finishedAt": budget.get("finishedAt") or now,
            "releasedAt": budget.get("releasedAt") or now,
        }
    )
    payload["budget"] = budget
    payload["budgetOutcome"] = "cancelled-before-budget"
    return True


def _cancellation_error(payload: dict[str, Any], default: str) -> str:
    """Return a terminal cancellation message consistent with its attribution."""

    reason = str(
        payload.get("cancelReason") or payload.get("stopReason") or ""
    ).strip().lower()
    if reason == "runtime_budget":
        budget = payload.get("budget")
        max_runtime_seconds = (
            int(budget.get("maxRuntimeSeconds") or 0)
            if isinstance(budget, dict)
            else 0
        )
        if max_runtime_seconds > 0:
            return (
                f"Hard runtime budget of {max_runtime_seconds} seconds was exhausted; "
                "Neyvia stopped the Harness run."
            )
        return "Hard runtime budget was exhausted; Neyvia stopped the Harness run."
    return default


def _try_advisory_job_lock(descriptor: int) -> bool:
    """Acquire the crash-released OS guard without blocking the interpreter."""

    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            contention_errno = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
            if exc.errno in contention_errno or getattr(exc, "winerror", None) in {
                32,
                33,
                36,
            }:
                return False
            raise
        return True

    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            return False
        raise
    return True


def _release_advisory_job_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _legacy_lock_owner(lock_path: Path) -> tuple[int | None, str]:
    """Read both the historical one-line PID lock and the new tokenized form."""

    try:
        lines = lock_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except (FileNotFoundError, OSError):
        return None, ""
    if not lines:
        return None, ""
    try:
        owner_pid = int(lines[0].strip())
    except ValueError:
        return None, ""
    owner_token = lines[1].strip() if len(lines) > 1 else ""
    return owner_pid, owner_token


def _job_guard_path(path: Path) -> Path:
    """Map a job to one of a bounded set of persistent advisory guard files."""

    shard = zlib.crc32(path.name.encode("utf-8")) % HARNESS_JOB_LOCK_GUARD_SHARDS
    return path.parent / f".harness-job-mutation-{shard:02x}.guard"


def _heartbeat_job_lock(
    lock_path: Path,
    owner_token: str,
    stop_event: threading.Event,
) -> None:
    """Keep old Neyvia builds from age-stealing a lock held by this build."""

    while not stop_event.wait(HARNESS_JOB_LOCK_HEARTBEAT_SECONDS):
        _owner_pid, current_token = _legacy_lock_owner(lock_path)
        if current_token != owner_token:
            return
        try:
            os.utime(lock_path, None)
        except OSError:
            return


@contextmanager
def _exclusive_job_lock(path: Path, *, timeout_seconds: float | None = None) -> Iterator[None]:
    """Serialize durable job mutations and recover safely from process crashes.

    The historical lock used file age alone and could delete a lock still owned by
    a live process after 60 seconds. The new protocol adds a sharded OS advisory
    guard, which is released automatically when a process exits, while retaining
    the old ``.lock`` file as a compatibility fence for already-running older
    Neyvia processes. A tokenized compatibility lock left behind after a crash is
    safe to reclaim once this process owns the advisory guard; a one-line legacy
    lock is reclaimed only when its recorded PID is no longer live.

    A caller may supply a shorter bounded wait for an interactive/local action;
    this never changes ownership or recovery policy. The default stays unchanged.
    """

    lock_path = path.with_suffix(path.suffix + ".lock")
    guard_path = _job_guard_path(path)
    wait_seconds = HARNESS_JOB_LOCK_TIMEOUT_SECONDS if timeout_seconds is None else float(timeout_seconds)
    if not math.isfinite(wait_seconds) or wait_seconds < 0:
        raise ValueError("Harness lock timeout must be finite and non-negative.")
    deadline = time.monotonic() + wait_seconds
    guard_flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
    guard_descriptor = os.open(guard_path, guard_flags, 0o600)
    guard_held = False
    legacy_descriptor = -1
    owner_token = ""
    heartbeat_stop = threading.Event()
    heartbeat_thread: threading.Thread | None = None

    try:
        while not guard_held:
            try:
                guard_held = _try_advisory_job_lock(guard_descriptor)
            except OSError as exc:
                raise RuntimeError(
                    "The workspace filesystem cannot provide crash-safe Harness "
                    f"job locking for {path.name}: {type(exc).__name__}: {exc}"
                ) from exc
            if guard_held:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Timed out waiting for crash-safe Harness job guard: {path.name}. "
                    "Another Neyvia process is still mutating this run."
                )
            time.sleep(HARNESS_JOB_LOCK_POLL_SECONDS)

        while legacy_descriptor < 0:
            if lock_path.exists():
                owner_pid, existing_token = _legacy_lock_owner(lock_path)
                if existing_token:
                    # New-protocol holders always own the same shard guard at the
                    # same time. Because we hold it now, a tokenized compatibility
                    # file can only be residue from a process that exited.
                    lock_path.unlink(missing_ok=True)
                    continue
                if owner_pid is not None:
                    if _process_alive(owner_pid):
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                f"Timed out waiting for Harness job lock: {path.name}. "
                                f"Legacy owner PID {owner_pid} is still live; Neyvia "
                                "refused to steal its mutation lease."
                            )
                        time.sleep(HARNESS_JOB_LOCK_POLL_SECONDS)
                        continue
                    lock_path.unlink(missing_ok=True)
                    continue

                try:
                    lock_age = max(0.0, time.time() - lock_path.stat().st_mtime)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise RuntimeError(
                        f"Harness job lock metadata is unreadable: {path.name}: {exc}"
                    ) from exc
                if lock_age < HARNESS_JOB_LOCK_LEGACY_STALE_SECONDS:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            f"Timed out waiting for Harness job lock: {path.name}. "
                            "The compatibility lock is unreadable and too recent to "
                            "reclaim safely."
                        )
                    time.sleep(HARNESS_JOB_LOCK_POLL_SECONDS)
                    continue
                lock_path.unlink(missing_ok=True)
                continue

            try:
                legacy_descriptor = os.open(
                    lock_path,
                    os.O_CREAT
                    | os.O_EXCL
                    | os.O_WRONLY
                    | getattr(os, "O_BINARY", 0),
                    0o600,
                )
            except FileExistsError:
                # An older process may have raced the compatibility fence while
                # this build held the advisory guard. Respect it and re-evaluate.
                continue

        owner_token = uuid.uuid4().hex
        os.write(
            legacy_descriptor,
            f"{os.getpid()}\n{owner_token}\n".encode("ascii"),
        )
        try:
            os.fsync(legacy_descriptor)
        except OSError:
            pass

        heartbeat_thread = threading.Thread(
            target=_heartbeat_job_lock,
            args=(lock_path, owner_token, heartbeat_stop),
            name=f"neyvia-job-lock-heartbeat-{path.stem[-12:]}",
            daemon=True,
        )
        heartbeat_thread.start()
        yield
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)
        if legacy_descriptor >= 0:
            try:
                os.close(legacy_descriptor)
            except OSError:
                pass
            _owner_pid, current_token = _legacy_lock_owner(lock_path)
            if current_token == owner_token:
                lock_path.unlink(missing_ok=True)
        if guard_held:
            try:
                _release_advisory_job_lock(guard_descriptor)
            except OSError:
                # Closing the descriptor also releases OS advisory locks. Do not
                # hide the original job exception because cleanup reporting failed.
                pass
        try:
            os.close(guard_descriptor)
        except OSError:
            pass


def _read_job_payload(path: Path, job_id: object) -> dict[str, Any]:
    try:
        # A Windows atomic replacement can briefly deny a simultaneous reader.
        # Retry only OS access/sharing failures; corrupt JSON stays fail-closed.
        for attempt in range(20):
            try:
                text = path.read_text(encoding="utf-8")
                break
            except PermissionError as exc:
                if (os.name != "nt" or exc.errno != errno.EACCES
                        or exc.winerror not in {None, 5, 32, 33} or attempt == 19):
                    raise
                time.sleep(0.05)
        payload = json.loads(text)
    except FileNotFoundError as exc:
        raise KeyError(f"Harness job not found: {job_id}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Harness job record is unreadable: {path.name}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != HARNESS_JOB_SCHEMA:
        raise RuntimeError(f"Harness job record has an unsupported schema: {path.name}")
    return payload


class HarnessJobStore:
    def __init__(self, root: Path, *, max_open_jobs: int | None = None) -> None:
        self.root = Path(root).expanduser().resolve(strict=True)
        self.jobs_root = self.root / ".agent_control" / "harness_jobs"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        configured_limit: object = max_open_jobs
        if configured_limit is None:
            configured_limit = os.environ.get(
                "NEYVIA_MAX_OPEN_HARNESS_JOBS",
                MAX_OPEN_HARNESS_JOBS,
            )
        self.requested_max_open_jobs = _normalize_open_job_limit(configured_limit)
        # Keep this public attribute for compatibility, but refresh it from the
        # durable workspace policy before every capacity/admission decision.
        self.max_open_jobs = self.requested_max_open_jobs

    def job_path(self, job_id: object) -> Path:
        safe_id = _safe_id(job_id)
        if not safe_id.startswith("harness-job-"):
            raise ValueError("Invalid Harness job id.")
        return self.jobs_root / f"{safe_id}.json"

    def _admission_lock_path(self) -> Path:
        return self.jobs_root / ".harness-job-admission"

    def _admission_policy_path(self) -> Path:
        return self.jobs_root / ".harness-job-admission-policy.json"

    def _sync_admission_policy_locked(self) -> int:
        """Return the authoritative workspace limit while the admission lease is held.

        The environment/constructor value is a requested ceiling, not isolated
        process-local authority. The first same-version process persists the
        workspace policy. A later process may tighten that policy, but a process
        requesting a larger value cannot silently raise it again. This monotonic
        rule keeps a stricter rollout authoritative even while older processes are
        still alive. Raising the hard limit therefore requires an explicit future
        policy migration rather than an ambient environment mismatch.
        """

        path = self._admission_policy_path()
        requested = self.requested_max_open_jobs
        now = _utc_now()
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Harness admission policy is unreadable. Neyvia refused to make a "
                "capacity decision until the durable workspace policy is repaired."
            ) from exc

        if raw is None:
            policy = {
                "schema": HARNESS_ADMISSION_POLICY_SCHEMA,
                "maxOpenJobs": requested,
                "createdAt": now,
                "updatedAt": now,
                "mode": "monotonic-tighten",
            }
            _atomic_write_json(path, policy)
            self.max_open_jobs = requested
            return requested

        if not isinstance(raw, dict) or raw.get("schema") != HARNESS_ADMISSION_POLICY_SCHEMA:
            raise RuntimeError(
                "Harness admission policy has an unsupported schema. Neyvia refused "
                "to guess a hard capacity limit."
            )
        try:
            persisted = _normalize_open_job_limit(raw.get("maxOpenJobs"))
        except ValueError as exc:
            raise RuntimeError(
                "Harness admission policy contains an invalid hard limit. Neyvia "
                "refused to guess a replacement value."
            ) from exc

        effective = min(persisted, requested)
        if effective < persisted:
            policy = dict(raw)
            policy.update(
                {
                    "maxOpenJobs": effective,
                    "previousMaxOpenJobs": persisted,
                    "tightenedAt": now,
                    "updatedAt": now,
                    "mode": "monotonic-tighten",
                }
            )
            _atomic_write_json(path, policy)
        self.max_open_jobs = effective
        return effective

    def _capacity_snapshot(self, max_open_jobs: int) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        open_jobs = 0
        unreadable_jobs = 0
        paths = list(self.jobs_root.glob("harness-job-*.json"))
        for path in paths:
            try:
                payload = _read_job_payload(path, path.stem)
                status = str(payload.get("status") or "unknown").strip().lower() or "unknown"
            except (KeyError, OSError, RuntimeError, ValueError):
                status = "unreadable"
                unreadable_jobs += 1
            status_counts[status] = status_counts.get(status, 0) + 1
            if status not in TERMINAL_JOB_STATUSES:
                open_jobs += 1
        available_slots = max(0, max_open_jobs - open_jobs)
        snapshot = {
            "policy": "reject-new",
            "maxOpenJobs": max_open_jobs,
            "openJobs": open_jobs,
            "availableSlots": available_slots,
            "blockedJobs": status_counts.get("blocked", 0),
            "unreadableJobs": unreadable_jobs,
            "statusCounts": status_counts,
            "admissionState": "available" if available_slots > 0 else "blocked",
        }
        from .proofs_b_harness import check_admission
        check_admission(snapshot)
        return snapshot

    def capacity(self) -> dict[str, Any]:
        """Return a fail-closed snapshot of durable Harness admission pressure.

        Any unreadable or unknown-state receipt occupies capacity. Losing track of
        a run is not permission to launch another one. Terminal receipts do not
        consume admission capacity; `blocked` deliberately does because it remains
        an unresolved operator obligation. The hard limit itself is read from the
        durable store-wide policy under the same crash-released admission lease.
        """

        with _exclusive_job_lock(self._admission_lock_path()):
            max_open_jobs = self._sync_admission_policy_locked()
            return self._capacity_snapshot(max_open_jobs)

    def load(self, job_id: object, *, reconcile: bool = True) -> dict[str, Any]:
        path = self.job_path(job_id)
        payload = _read_job_payload(path, job_id)
        if reconcile and payload.get("status") in {"queued", "running", "cancelling"}:
            pid = int(payload.get("pid") or 0)
            if pid and not _process_alive(pid):
                payload = self._mark_interrupted_if_stale(payload["id"], pid)
            elif pid:
                command_line = _process_command_line(pid)
                # Identity lookup failure is not evidence that a live process is
                # stale. Only a positively observed, non-matching command may free
                # admission capacity; an empty/unavailable lookup stays fail-closed.
                if command_line and not _is_harness_worker_command(
                    command_line,
                    str(payload["id"]),
                ):
                    payload = self._mark_interrupted_if_stale(payload["id"], pid)
        return _with_job_observability(payload)

    def _mark_interrupted_if_stale(self, job_id: object, expected_pid: int) -> dict[str, Any]:
        """Reconcile a dead worker without overwriting a newer terminal update."""

        path = self.job_path(job_id)
        with _exclusive_job_lock(path):
            payload = _read_job_payload(path, job_id)
            if (
                payload.get("status") not in {"queued", "running", "cancelling"}
                or int(payload.get("pid") or 0) != int(expected_pid)
            ):
                return payload
            now = _utc_now()
            if payload.get("status") == "cancelling":
                payload.update(
                    {
                        "status": "cancelled",
                        "pid": None,
                        "finishedAt": payload.get("finishedAt") or now,
                        "updatedAt": now,
                        "cancelledAt": payload.get("cancelledAt") or now,
                        "cancelOutcome": "worker-no-longer-live",
                        "error": (
                            "Cancellation was already requested and the Harness worker "
                            "is no longer live. Neyvia finalized the job as cancelled."
                        ),
                    }
                )
                _release_active_budget_on_cancellation(payload, now)
                payload["error"] = _cancellation_error(
                    payload,
                    str(payload.get("error") or "Cancelled."),
                )
            else:
                payload.update(
                    {
                        "status": "interrupted",
                        "pid": None,
                        "finishedAt": now,
                        "updatedAt": now,
                        "error": (
                            "The Harness worker stopped before writing a terminal result. "
                            "The job can be launched again from the saved request."
                        ),
                    }
                )
            _atomic_write_json(path, payload)
            return payload

    def _reconcile_admission_receipts(self) -> None:
        """Reconcile every durable receipt that admission will subsequently count.

        The normal list is intentionally bounded to 100 visible records. Admission
        cannot use that visibility bound as a lifecycle bound because legacy
        workspaces may contain older unresolved receipts. Unsupported/corrupt
        records are intentionally left untouched so the capacity snapshot can count
        them fail-closed rather than deleting evidence.
        """

        for path in list(self.jobs_root.glob("harness-job-*.json")):
            try:
                self.load(path.stem)
            except (KeyError, OSError, RuntimeError, ValueError):
                continue

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        paths = sorted(
            self.jobs_root.glob("harness-job-*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for path in paths[: max(1, min(int(limit), MAX_HARNESS_JOBS))]:
            try:
                rows.append(self.load(path.stem))
            except (KeyError, OSError, RuntimeError, ValueError):
                continue
        return rows

    def create(self, request: dict[str, Any], *, job_id: str | None = None) -> dict[str, Any]:
        now = _utc_now()
        job_id = job_id or f"harness-job-{uuid.uuid4().hex}"
        self.job_path(job_id)  # Validate before using an internal reservation id.
        message = str(request.get("message") or request.get("objective") or "").strip()
        mode = (
            "orchestration"
            if str(request.get("mode") or "").strip().lower() == "orchestration"
            else "direct"
        )
        harness_id = str(
            request.get("harnessId")
            or request.get("runtime")
            or request.get("runtimeId")
            or "codex"
        ).strip().lower()
        if harness_id in SECURITY_ONLY_HARNESSES:
            label = "Rook" if harness_id == "rook" else "Wallbreaker"
            if mode != "orchestration":
                raise ValueError(
                    f"{label} is security-only and cannot be launched from Direct chat."
                )
            if request.get("authorizedSecurity") is not True:
                raise ValueError(
                    f"{label} requires explicit acknowledgement of an authorized, controlled target."
                )

        # Reconcile every durable receipt admission will count. This remains outside
        # the store-wide admission lease so individual job mutation locks can never
        # create a store-lock -> job-lock cycle. A concurrent change after this pass
        # is still counted fail-closed by the serialized capacity snapshot below.
        self._reconcile_admission_receipts()

        payload = {
            "schema": HARNESS_JOB_SCHEMA,
            "id": job_id,
            "status": "queued",
            "mode": mode,
            "harnessId": harness_id,
            "harnessLabel": str(request.get("harnessLabel") or ""),
            "runtime": str(request.get("runtime") or request.get("runtimeId") or "codex"),
            "workspacePath": str(request.get("workspacePath") or self.root),
            "prompt": message,
            "promptPreview": " ".join(message.split())[:240],
            "request": request,
            "pid": None,
            "createdAt": now,
            "startedAt": None,
            "updatedAt": now,
            "finishedAt": None,
            "result": None,
            "error": "",
            "logPath": str(self.jobs_root / f"{job_id}.log"),
        }
        with _exclusive_job_lock(self._admission_lock_path()):
            if self.job_path(job_id).exists():
                existing = _read_job_payload(self.job_path(job_id), job_id)
                if existing.get("request") != request:
                    raise ValueError("Harness job identity conflicts with its saved request.")
                return _with_job_observability(existing)
            max_open_jobs = self._sync_admission_policy_locked()
            capacity = self._capacity_snapshot(max_open_jobs)
            if int(capacity["availableSlots"]) <= 0:
                raise RuntimeError(
                    "Harness admission capacity is exhausted: "
                    f"{capacity['openJobs']} unresolved/open runs already occupy the "
                    f"operator limit of {capacity['maxOpenJobs']}. Resolve, cancel, or "
                    "finish an existing run before starting another. Neyvia did not "
                    "create a new Harness job."
                )
            payload["admission"] = {
                "policy": "reject-new",
                "maxOpenJobs": capacity["maxOpenJobs"],
                "openJobsBefore": capacity["openJobs"],
                "availableSlotsBefore": capacity["availableSlots"],
                "admittedAt": now,
            }
            _atomic_write_json(self.job_path(job_id), payload)
            self._prune()
        return _with_job_observability(payload)

    def start(self, job_id: object) -> dict[str, Any]:
        """Atomically claim a queued job before spawning exactly one worker."""

        path = self.job_path(job_id)
        process: Any = None
        with _exclusive_job_lock(path):
            job = _read_job_payload(path, job_id)
            if job.get("status") != "queued":
                raise RuntimeError(f"Harness job is not queued: {job.get('status')}")

            log_path = Path(str(job["logPath"]))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("a", encoding="utf-8")
            worker_path = Path(__file__).resolve().with_name("harness_job_worker.py")
            command = [
                sys.executable,
                str(worker_path),
                "--root",
                str(self.root),
                "--job-id",
                str(job["id"]),
            ]
            child_env = os.environ.copy()
            if sys.dont_write_bytecode:
                child_env["PYTHONDONTWRITEBYTECODE"] = "1"
            package_source_root = Path(__file__).resolve().parents[1]
            existing_pythonpath = str(child_env.get("PYTHONPATH") or "").strip()
            pythonpath_parts = [str(package_source_root)]
            if existing_pythonpath:
                pythonpath_parts.append(existing_pythonpath)
            child_env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
            launch_kwargs: dict[str, Any] = {
                "cwd": str(self.root),
                "stdin": subprocess.DEVNULL,
                "stdout": log_handle,
                "stderr": subprocess.STDOUT,
                "env": child_env,
                **hidden_windows_subprocess_kwargs(),
            }
            if os.name == "nt":
                launch_kwargs["creationflags"] = int(
                    launch_kwargs.get("creationflags", 0)
                ) | int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            else:
                launch_kwargs["start_new_session"] = True

            try:
                process = subprocess.Popen(command, **launch_kwargs)  # noqa: S603
            except (OSError, subprocess.SubprocessError) as exc:
                now = _utc_now()
                job.update(
                    {
                        "status": "failed",
                        "pid": None,
                        "finishedAt": now,
                        "updatedAt": now,
                        "error": (
                            f"Harness worker could not start: {type(exc).__name__}: {exc}"
                        )[:4000],
                    }
                )
                _atomic_write_json(path, job)
                raise RuntimeError("Harness worker could not start.") from exc
            finally:
                log_handle.close()

            now = _utc_now()
            job.update(
                {
                    "status": "running",
                    "pid": int(process.pid),
                    "startedAt": job.get("startedAt") or now,
                    "updatedAt": now,
                    "workerCommand": command,
                }
            )
            _atomic_write_json(path, job)
            started = _with_job_observability(job)

        assert process is not None
        threading.Thread(
            target=process.wait,
            name=f"neyvia-harness-reaper-{process.pid}",
            daemon=True,
        ).start()
        return started

    def mark_started(
        self,
        job_id: object,
        *,
        pid: int,
        worker_command: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record the worker PID without reviving stopping or worker-stopped jobs."""

        path = self.job_path(job_id)
        with _exclusive_job_lock(path):
            payload = _read_job_payload(path, job_id)
            if payload.get("status") in WORKER_STOPPED_JOB_STATUSES | {"cancelling"}:
                return _with_job_observability(payload)
            current_pid = int(payload.get("pid") or 0)
            if (
                worker_command
                and payload.get("status") == "running"
                and current_pid > 0
                and current_pid != int(pid)
                and not payload.get("workerCommand")
            ):
                # On Windows, a venv launcher may spawn the real interpreter
                # and exit before the parent records the launcher PID. The
                # worker self-registers its real PID first; keep that
                # authoritative PID and attach only the verified command.
                payload["workerCommand"] = worker_command
                payload["updatedAt"] = _utc_now()
                _atomic_write_json(path, payload)
                return _with_job_observability(payload)
            payload.update(
                {
                    "status": "running",
                    "pid": int(pid),
                    "startedAt": payload.get("startedAt") or _utc_now(),
                    "updatedAt": _utc_now(),
                }
            )
            if worker_command:
                payload["workerCommand"] = worker_command
            _atomic_write_json(path, payload)
            return _with_job_observability(payload)

    def update(self, job_id: object, **changes: Any) -> dict[str, Any]:
        path = self.job_path(job_id)
        with _exclusive_job_lock(path):
            payload = _read_job_payload(path, job_id)
            payload.update(changes)
            payload["updatedAt"] = _utc_now()
            _atomic_write_json(path, payload)
            return _with_job_observability(payload)

    def finish(
        self,
        job_id: object,
        *,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        """Commit a worker result without racing cancellation or stale workers.

        Backend outcomes that explicitly report ``blocked`` or ``interrupted``
        retain that lifecycle meaning instead of being flattened into ``failed``
        merely because they also carry an explanatory error/detail string. A
        blocked job has no live worker but remains operator-resolvable, so only an
        explicit cancel/retry/resume path may move it afterward.
        """

        path = self.job_path(job_id)
        with _exclusive_job_lock(path):
            payload = _read_job_payload(path, job_id)
            status = str(payload.get("status") or "")
            if status in WORKER_STOPPED_JOB_STATUSES:
                return _with_job_observability(payload)

            now = _utc_now()
            if status == "cancelling":
                payload.update(
                    {
                        "status": "cancelled",
                        "pid": None,
                        "finishedAt": payload.get("finishedAt") or now,
                        "cancelledAt": payload.get("cancelledAt") or now,
                        "cancelOutcome": payload.get("cancelOutcome") or "worker-acknowledged",
                    }
                )
                _release_active_budget_on_cancellation(payload, now)
                if not payload.get("error"):
                    payload["error"] = _cancellation_error(
                        payload,
                        "Cancelled by the operator.",
                    )
            else:
                result_status = (
                    str(result.get("status") or "").strip().lower()
                    if isinstance(result, dict)
                    else ""
                )
                terminal_status = (
                    result_status
                    if result_status in {"blocked", "interrupted"}
                    else "failed" if error else "completed"
                )
                payload.update(
                    {
                        "status": terminal_status,
                        "result": result,
                        "error": str(error or "")[:4000],
                        "finishedAt": now,
                        "pid": None,
                    }
                )
                if terminal_status == "blocked":
                    payload["blockedAt"] = payload.get("blockedAt") or now
                elif terminal_status == "interrupted":
                    payload["interruptedAt"] = payload.get("interruptedAt") or now
            payload["updatedAt"] = now
            _atomic_write_json(path, payload)
            return _with_job_observability(payload)

    def cancel(self, job_id: object) -> dict[str, Any]:
        """Claim cancellation atomically, then stop the verified worker process tree."""

        path = self.job_path(job_id)
        pid = 0
        with _exclusive_job_lock(path):
            job = _read_job_payload(path, job_id)
            if job.get("status") in TERMINAL_JOB_STATUSES:
                return _with_job_observability(job)

            now = _utc_now()
            prior_status = str(job.get("status") or "").strip().lower()
            pid = int(job.get("pid") or 0)
            if pid <= 0:
                blocked_cleanup = prior_status == "blocked"
                job.update(
                    {
                        "status": "cancelled",
                        "pid": None,
                        "finishedAt": now,
                        "updatedAt": now,
                        "cancelRequestedAt": job.get("cancelRequestedAt") or now,
                        "cancelledAt": now,
                        "cancelReason": job.get("cancelReason") or "operator",
                        "cancelOutcome": (
                            "blocked-cleanup" if blocked_cleanup else "before-start"
                        ),
                    }
                )
                job["error"] = _cancellation_error(
                    job,
                    (
                        "Cancelled while blocked; no Harness worker was live."
                        if blocked_cleanup
                        else "Cancelled before the Harness worker started."
                    ),
                )
                _release_active_budget_on_cancellation(job, now)
                _atomic_write_json(path, job)
                return _with_job_observability(job)

            command_line = _process_command_line(pid)
            expected = str(job["id"])
            if not _is_harness_worker_command(command_line, expected):
                if not _process_alive(pid):
                    job.update(
                        {
                            "status": "cancelled",
                            "pid": None,
                            "finishedAt": now,
                            "updatedAt": now,
                            "cancelRequestedAt": job.get("cancelRequestedAt") or now,
                            "cancelledAt": now,
                            "cancelReason": job.get("cancelReason") or "operator",
                            "cancelOutcome": "worker-no-longer-live",
                        }
                    )
                    job["error"] = _cancellation_error(
                        job,
                        (
                            "Cancellation was requested after the Harness worker "
                            "had already stopped."
                        ),
                    )
                    _release_active_budget_on_cancellation(job, now)
                    _atomic_write_json(path, job)
                    return _with_job_observability(job)
                raise RuntimeError(
                    "Refusing to stop a PID that cannot be verified as this Harness worker."
                )

            job.update(
                {
                    "status": "cancelling",
                    "cancelRequestedAt": job.get("cancelRequestedAt") or now,
                    "cancelReason": job.get("cancelReason") or "operator",
                    "updatedAt": now,
                }
            )
            _atomic_write_json(path, job)

        try:
            _terminate_process_tree(pid)
        except BaseException as exc:
            with _exclusive_job_lock(path):
                current = _read_job_payload(path, job_id)
                if current.get("status") == "cancelling":
                    current["updatedAt"] = _utc_now()
                    current["cancelError"] = (
                        f"Process tree stop was not confirmed: {type(exc).__name__}: {exc}"
                    )[:4000]
                    _atomic_write_json(path, current)
            raise

        with _exclusive_job_lock(path):
            current = _read_job_payload(path, job_id)
            if current.get("status") in TERMINAL_JOB_STATUSES:
                return _with_job_observability(current)
            now = _utc_now()
            current.update(
                {
                    "status": "cancelled",
                    "pid": None,
                    "finishedAt": current.get("finishedAt") or now,
                    "updatedAt": now,
                    "cancelledAt": current.get("cancelledAt") or now,
                    "cancelReason": current.get("cancelReason") or "operator",
                    "cancelOutcome": current.get("cancelOutcome") or "process-tree-stopped",
                }
            )
            current["error"] = _cancellation_error(
                current,
                "Cancelled by the operator.",
            )
            _release_active_budget_on_cancellation(current, now)
            _atomic_write_json(path, current)
            return _with_job_observability(current)

    def _prune(self) -> None:
        paths = sorted(
            self.jobs_root.glob("harness-job-*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for path in paths[MAX_HARNESS_JOBS:]:
            try:
                payload = _read_job_payload(path, path.stem)
            except (KeyError, OSError, RuntimeError, ValueError):
                # Unknown/corrupt lifecycle evidence is intentionally retained. A
                # future/unsupported schema saying "completed" is not terminal
                # evidence this build is entitled to delete.
                continue
            if payload.get("status") in TERMINAL_JOB_STATUSES and not payload.get("request", {}).get("batchId"):
                path.unlink(missing_ok=True)
                path.with_suffix(".log").unlink(missing_ok=True)


def _windows_process_alive(pid: int) -> bool:
    """Probe a Windows PID without using ``os.kill(pid, 0)``.

    CPython maps non-console-control signals on Windows to TerminateProcess, so
    the POSIX zero-signal liveness idiom is unsafe there. Admission and stale
    ownership recovery are safety boundaries: only positive evidence of process
    exit may release capacity. Access-denied or other indeterminate Win32 errors
    therefore fail closed as live.
    """

    import ctypes

    synchronize = 0x00100000
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    error_invalid_parameter = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.WaitForSingleObject.restype = ctypes.c_ulong
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    # WaitForSingleObject requires SYNCHRONIZE and nothing more. Requesting only
    # that right reduces privilege-dependent false negatives while keeping this
    # probe observational and non-destructive.
    handle = kernel32.OpenProcess(synchronize, False, int(pid))
    if not handle:
        # ERROR_INVALID_PARAMETER is the only failure we accept as positive death
        # evidence. Access denied and every other failure are indeterminate and
        # therefore retain ownership/capacity fail-closed.
        error = ctypes.get_last_error()
        outcome = error != error_invalid_parameter
        from .proofs_b_harness import check_liveness_outcome
        check_liveness_outcome(outcome, error=error)
        return outcome
    try:
        wait_result = int(kernel32.WaitForSingleObject(handle, 0))
        outcome = wait_result != wait_object_0
        from .proofs_b_harness import check_liveness_outcome
        check_liveness_outcome(outcome, wait_result=wait_result)
        return outcome
    finally:
        kernel32.CloseHandle(handle)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_alive(pid)
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.is_file():
        try:
            # Linux keeps an exited child visible until its parent reaps it.
            # State Z is not an executing Harness worker and must reconcile.
            remainder = proc_stat.read_text(encoding="utf-8").rsplit(")", 1)[1]
            if remainder.strip().split(maxsplit=1)[0] == "Z":
                return False
        except (IndexError, OSError):
            pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # EPERM/AccessDenied is positive evidence that the PID exists but this
        # process cannot inspect/signal it. Treat it as live so admission and
        # stale-lock recovery remain fail-closed across service-account changes.
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        # Any other liveness-probe failure is indeterminate, not proof of death.
        # Conservatively retain ownership/capacity until positive evidence exists.
        return True
    return True


def _is_harness_worker_command(command_line: str, job_id: str) -> bool:
    worker_markers = (
        "grant_agent.harness_job_worker",
        "grant_agent/harness_job_worker.py",
        "grant_agent\\harness_job_worker.py",
    )
    return bool(job_id) and job_id in command_line and any(
        marker in command_line for marker in worker_markers
    )


def _process_command_line(pid: int) -> str:
    proc_path = Path(f"/proc/{pid}/cmdline")
    if proc_path.is_file():
        try:
            return proc_path.read_bytes().replace(b"\0", b" ").decode(
                "utf-8",
                errors="replace",
            )
        except OSError:
            return ""
    if os.name == "nt":
        command = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "(Get-CimInstance Win32_Process -Filter "
                f"'ProcessId = {int(pid)}').CommandLine"
            ),
        ]
    else:
        command = ["ps", "-p", str(pid), "-o", "command="]
    # A cold PowerShell/CIM query can take well over five seconds on a loaded PC. A timeout
    # is not an answer about the process, so retry before the caller refuses to act on it.
    for _ in range(3):
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
                **(hidden_windows_subprocess_kwargs() if os.name == "nt" else {}),
            )
        except subprocess.TimeoutExpired:
            continue
        except (OSError, subprocess.SubprocessError):
            return ""
        if completed.returncode == 0 and completed.stdout.strip():
            return completed.stdout.strip()
        if not _process_alive(pid):
            return ""
    return ""


def _terminate_process_tree(pid: int) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        if completed.returncode not in {0, 128} and _process_alive(pid):
            raise RuntimeError(f"Could not stop Harness worker PID {pid}.")
        return
    try:
        process_group = os.getpgid(pid)
    except OSError:
        process_group = pid
    try:
        os.killpg(process_group, signal.SIGTERM)
    except OSError:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 8
    while _process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if _process_alive(pid):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except OSError:
            os.kill(pid, signal.SIGKILL)
