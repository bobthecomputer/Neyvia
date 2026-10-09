from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


_APPEND_LOCK = threading.Lock()
_FILE_LOCKS: dict[str, threading.RLock] = {}
_FILE_LOCKS_GUARD = threading.Lock()
_FILE_TRANSACTIONS = threading.local()


@contextmanager
def file_transaction(path: Path):
    """Serialize file readers/mutations across threads and crash-safe processes."""
    from .harness_jobs import _exclusive_job_lock
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.resolve())
    if os.name == 'nt':
        key = key.casefold()
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.setdefault(key, threading.RLock())
    with lock:
        held = getattr(_FILE_TRANSACTIONS, 'held', None)
        if held is None:
            held = _FILE_TRANSACTIONS.held = set()
        if key in held:
            yield
            return
        with _exclusive_job_lock(path):
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)


def _replace_complete_file(temporary: Path, target: Path) -> None:
    # Windows readers and scanners can briefly deny deletion of the old name.
    # Preserve the complete sibling bytes while retrying; permanent denial
    # still raises within this bounded half-second publication window.
    for attempt in range(21):
        try:
            os.replace(temporary, target)
            return
        except PermissionError as error:
            if os.name != "nt" or getattr(error, "winerror", None) not in {5, 32, 33} or attempt == 20:
                raise
            time.sleep(.025)


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    """Replace a file only after its complete new contents reach the filesystem."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_complete_file(temporary, target)
        _sync_directory(target.parent)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def atomic_write_json(path: str | Path, payload: Any, *, indent: int = 2) -> Path:
    return atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=indent) + "\n",
    )


def atomic_write_bytes(path: str | Path, payload: bytes) -> Path:
    """Replace a file durably without altering its byte representation."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_complete_file(temporary, target)
        _sync_directory(target.parent)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def append_jsonl_durable(path: str | Path, payload: Any) -> Path:
    """Append one complete JSONL record and flush it before returning."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
    with _APPEND_LOCK:
        with target.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    return target


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
