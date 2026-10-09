"""Cross-process admission and cooperative stopping for durable agent graphs.

The OS releases admission after a crash. Stopping waits for the current bounded
runtime call; it does not claim to kill a remote provider request.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .harness_jobs import _atomic_write_json, _exclusive_job_lock, _release_advisory_job_lock, _try_advisory_job_lock


def _path(root: Path, conversation_id: str) -> Path:
    if not conversation_id:
        raise ValueError("conversationId is required")
    folder = Path(root) / ".agent_control" / "orchestration_runs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (hashlib.sha256(conversation_id.encode()).hexdigest() + ".json")


@contextmanager
def run_lease(root: Path, conversation_id: str, *, start: bool = False) -> Iterator[bool]:
    path = _path(root, conversation_id).with_suffix(".guard")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
    held = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        with _exclusive_job_lock(_path(root, conversation_id)):
            held = _try_advisory_job_lock(descriptor)
            if held and start:
                previous = state(root, conversation_id)
                if previous.get("status") in {"running", "stopping", "interrupted"}:
                    _atomic_write_json(_path(root, conversation_id), {"status": "interrupted", "stopRequested": False})
                    raise ValueError("Previous execution was interrupted. Inspect its receipts before preparing a new workflow; automatic replay could duplicate work.")
                _atomic_write_json(_path(root, conversation_id), {"status": "running", "stopRequested": False})
        yield held
    finally:
        if held:
            _release_advisory_job_lock(descriptor)
        os.close(descriptor)


def running(root: Path, conversation_id: str) -> bool:
    with run_lease(root, conversation_id) as acquired:
        return not acquired


def state(root: Path, conversation_id: str) -> dict:
    try:
        value = json.loads(_path(root, conversation_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Invalid orchestration control record")
    return value


def request_stop(root: Path, conversation_id: str) -> dict:
    if not running(root, conversation_id):
        return {"status": "not_running", "stopRequested": False}
    path = _path(root, conversation_id)
    with _exclusive_job_lock(path):
        if state(root, conversation_id).get("status") not in {"running", "stopping"}:
            return {"status": "not_running", "stopRequested": False}
        value = {"status": "stopping", "stopRequested": True}
        _atomic_write_json(path, value)
        return value


def finish(root: Path, conversation_id: str, status: str) -> None:
    path = _path(root, conversation_id)
    with _exclusive_job_lock(path):
        _atomic_write_json(path, {"status": status, "stopRequested": False})
