from __future__ import annotations

import json
import os
import time
import threading
import weakref
from contextlib import contextmanager
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any, Iterator

from .models import (
    EXECUTION_RECEIPT_SCHEMA_VERSION,
    FINAL_PROOF_RECEIPT_SCHEMA_VERSION,
    NIGHT_READINESS_RECEIPT_SCHEMA_VERSION,
    PLAN_RECEIPT_SCHEMA_VERSION,
    REPAIR_RECEIPT_SCHEMA_VERSION,
    STUCK_MISSION_RECEIPT_DECISIONS,
    STUCK_MISSION_RECEIPT_SCHEMA_VERSION,
    VERIFICATION_RECEIPT_DECISIONS,
    VERIFICATION_RECEIPT_SCHEMA_VERSION,
    ExecutionReceipt,
    FinalProofReceipt,
    NightReadinessReceipt,
    PlanReceipt,
    RepairReceipt,
    StuckMissionReceipt,
    VerificationReceipt,
)

MISSION_RECEIPTS_FILENAME = "mission_receipts.jsonl"
MAX_MISSION_RECEIPTS_TO_KEEP = 500
MISSION_RECEIPT_LOCK_TIMEOUT_SECONDS = 10.0
MISSION_RECEIPT_STALE_LOCK_SECONDS = 60.0
_LOCAL_WRITERS = weakref.WeakValueDictionary()
_LOCAL_WRITERS_LOCK = threading.Lock()


def _local_writer(path):
    # Same-process bursts queue before the cross-process lease clock starts.
    # A waiter retains its lock; inactive paths do not accumulate in the map.
    key = os.path.normcase(str(path.resolve()))
    with _LOCAL_WRITERS_LOCK:
        lock = _LOCAL_WRITERS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCAL_WRITERS[key] = lock
        return lock


def _reset_local_writers():
    global _LOCAL_WRITERS, _LOCAL_WRITERS_LOCK
    _LOCAL_WRITERS = weakref.WeakValueDictionary()
    _LOCAL_WRITERS_LOCK = threading.Lock()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset_local_writers)

_SCHEMA_TYPES = {
    NIGHT_READINESS_RECEIPT_SCHEMA_VERSION: NightReadinessReceipt,
    PLAN_RECEIPT_SCHEMA_VERSION: PlanReceipt,
    EXECUTION_RECEIPT_SCHEMA_VERSION: ExecutionReceipt,
    VERIFICATION_RECEIPT_SCHEMA_VERSION: VerificationReceipt,
    REPAIR_RECEIPT_SCHEMA_VERSION: RepairReceipt,
    FINAL_PROOF_RECEIPT_SCHEMA_VERSION: FinalProofReceipt,
    STUCK_MISSION_RECEIPT_SCHEMA_VERSION: StuckMissionReceipt,
}

_COMMON_REQUIRED_FIELDS = (
    "schema",
    "receipt_id",
    "mission_id",
    "generated_at",
    "phase",
    "host",
    "runtime",
    "workspace",
    "status",
    "summary",
    "inputs",
    "outputs",
    "proof_paths",
    "next_action",
)


class ReceiptValidationError(ValueError):
    pass


def mission_receipts_path(root: str | Path) -> Path:
    root_path = Path(root)
    path = (
        root_path
        if root_path.name == MISSION_RECEIPTS_FILENAME
        else root_path / ".agent_control" / MISSION_RECEIPTS_FILENAME
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_mission_receipt(
    root: str | Path,
    receipt: Any,
    *,
    max_receipts: int = MAX_MISSION_RECEIPTS_TO_KEEP,
) -> dict[str, Any]:
    payload = validate_mission_receipt(receipt)
    path = mission_receipts_path(root)
    with _receipt_file_lock(path):
        lines = _read_lines(path)
        lines.append(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        _write_capped_lines(path, lines, max_receipts=max_receipts)
        from .proofs_c_missions import check_receipt_write
        check_receipt_write(path, lines, payload, max_receipts)
    return payload


def load_mission_receipts(
    root: str | Path,
    *,
    limit: int = 50,
    mission_id: str = "",
) -> list[dict[str, Any]]:
    path = mission_receipts_path(root)
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    target_mission_id = str(mission_id or "").strip()
    scan_lines = _read_lines(path) if target_mission_id else _tail_text_lines(path, limit)
    for line in scan_lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            if target_mission_id and str(payload.get("mission_id") or "") != target_mission_id:
                continue
            rows.append(validate_mission_receipt(payload))
        except (json.JSONDecodeError, ReceiptValidationError, TypeError):
            continue
    result = rows[-max(1, int(limit or 1)) :]
    from .proofs_c_missions import check_receipt_read
    check_receipt_read(result, target_mission_id, limit)
    return result


def validate_mission_receipt(receipt: Any) -> dict[str, Any]:
    payload = _payload_from_receipt(receipt)
    schema = str(payload.get("schema") or "")
    receipt_type = _SCHEMA_TYPES.get(schema)
    if receipt_type is None:
        raise ReceiptValidationError(f"Unsupported mission receipt schema: {schema or '<missing>'}")

    allowed_fields = {field.name for field in fields(receipt_type)}
    unexpected = sorted(set(payload) - allowed_fields)
    if unexpected:
        raise ReceiptValidationError(f"Unexpected mission receipt fields: {', '.join(unexpected)}")

    missing = [field for field in _COMMON_REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ReceiptValidationError(f"Missing mission receipt fields: {', '.join(missing)}")

    blank = [
        field
        for field in ("receipt_id", "mission_id", "generated_at", "phase", "host", "runtime", "workspace", "status", "summary")
        if not str(payload.get(field) or "").strip()
    ]
    if blank:
        raise ReceiptValidationError(f"Blank mission receipt fields: {', '.join(blank)}")

    for field_name in ("inputs", "outputs"):
        if not isinstance(payload.get(field_name), dict):
            raise ReceiptValidationError(f"{field_name} must be an object")
    if not isinstance(payload.get("proof_paths"), list):
        raise ReceiptValidationError("proof_paths must be a list")
    if schema == VERIFICATION_RECEIPT_SCHEMA_VERSION and payload.get("decision") not in VERIFICATION_RECEIPT_DECISIONS:
        raise ReceiptValidationError("VerificationReceipt decision is not allowed")
    if schema == STUCK_MISSION_RECEIPT_SCHEMA_VERSION and payload.get("decision") not in STUCK_MISSION_RECEIPT_DECISIONS:
        raise ReceiptValidationError("StuckMissionReceipt decision is not allowed")

    # Reconstruct the dataclass once so constructor-required fields stay enforced.
    receipt_type(**{key: value for key, value in payload.items() if key in allowed_fields})
    from .proofs_c_missions import check_receipt
    try:
        check_receipt(payload, receipt_type)
    except ValueError as error:
        raise ReceiptValidationError(str(error)) from error
    return dict(payload)


def _payload_from_receipt(receipt: Any) -> dict[str, Any]:
    if is_dataclass(receipt) and not isinstance(receipt, type):
        payload = asdict(receipt)
    elif isinstance(receipt, dict):
        payload = dict(receipt)
    else:
        raise ReceiptValidationError("Mission receipt must be a dataclass instance or dict")
    return payload


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


@contextmanager
def _receipt_file_lock(path: Path) -> Iterator[None]:
    from .harness_jobs import _exclusive_job_lock
    # The OS guard serializes recovery as well as writes and is released if a
    # process exits. Retain the legacy JSON lock to fence older writers.
    with _local_writer(path):
        with _exclusive_job_lock(path.with_suffix(path.suffix + ".mutation"),
                                 timeout_seconds=MISSION_RECEIPT_LOCK_TIMEOUT_SECONDS):
            with _legacy_receipt_file_lock(path):
                yield


@contextmanager
def _legacy_receipt_file_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(f"{path.suffix}.lock")
    deadline = time.monotonic() + MISSION_RECEIPT_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"pid": os.getpid(), "createdAt": time.time()}))
            break
        except (FileExistsError, PermissionError) as error:
            # Windows can report access denied while another writer's closed
            # lock file is pending deletion. Treat that brief state as bounded
            # contention; never enter the receipt write without owning a lock.
            if isinstance(error, PermissionError) and not (
                os.name == "nt" and (
                    getattr(error, "winerror", None) in {5, 32, 33}
                    or (getattr(error, "winerror", None) is None and error.errno == 13)
                )
            ):
                raise
            try:
                if time.time() - lock_path.stat().st_mtime > MISSION_RECEIPT_STALE_LOCK_SECONDS:
                    from .harness_jobs import _process_alive
                    owner = json.loads(lock_path.read_text(encoding="utf-8"))
                    owner_pid = owner.get("pid") if isinstance(owner, dict) else None
                    if type(owner_pid) is int and owner_pid > 0 and not _process_alive(owner_pid):
                        lock_path.unlink(missing_ok=True)
                        continue
            except (OSError, ValueError):
                pass
            if time.monotonic() >= deadline:
                if isinstance(error, PermissionError):
                    # A permanent ACL/access failure remains the original error,
                    # rather than becoming success or an ambiguous lock timeout.
                    raise
                raise TimeoutError(f"Timed out waiting for mission receipt lock: {lock_path}") from error
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _write_capped_lines(path: Path, lines: list[str], *, max_receipts: int) -> None:
    capped_count = max(1, int(max_receipts or 1))
    capped = [line for line in lines if str(line).strip()][-capped_count:]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    temporary.write_text(("\n".join(capped) + "\n") if capped else "", encoding="utf-8")
    os.replace(temporary, path)


def _tail_text_lines(path: Path, limit: int, *, chunk_size: int = 8192) -> list[str]:
    if limit <= 0:
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            offset = size
            chunks: list[bytes] = []
            line_count = 0
            while offset > 0 and line_count <= limit:
                read_size = min(chunk_size, offset)
                offset -= read_size
                handle.seek(offset)
                chunk = handle.read(read_size)
                chunks.append(chunk)
                line_count += chunk.count(b"\n")
    except OSError:
        return []
    data = b"".join(reversed(chunks))
    return data.decode("utf-8", errors="replace").splitlines()[-limit:]
