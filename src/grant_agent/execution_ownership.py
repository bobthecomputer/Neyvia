"""Single-host execution ownership, independent of a browser connection.

The OS lock is authoritative. Heartbeat timestamps are observational and never
permit stealing ownership from a live process. All devices use the same server.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path

from .durability import atomic_write_json
from .harness_jobs import _exclusive_job_lock


class ExecutionOwnership:
    def __init__(self, root: str | Path, task_id: str):
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 256:
            raise ValueError("A bounded task identity is required")
        self.task_id = task_id
        self.path = (
            Path(root).resolve()
            / ".agent_control"
            / "execution_ownership"
            / (hashlib.sha256(task_id.encode()).hexdigest() + ".json")
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._guard = None
        self._stop = threading.Event()
        self._thread = None

    def snapshot(self):
        if not self.path.exists():
            return {"taskId": self.task_id, "status": "not_started"}
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            state.get("schema") != "neyvia.execution-ownership.v1"
            or state.get("taskId") != self.task_id
        ):
            raise ValueError("Invalid execution ownership record")
        observed = dict(state)
        if state.get('status') == 'running' and time.time() - state.get('heartbeatAt', 0) > 15:
            observed['status'] = 'heartbeat_stale_execution_unknown'
        return {**observed, "authority": "server_os_lock", "heartbeatIsAuthority": False}

    def enter(self):
        if self._guard is not None:
            raise RuntimeError("Ownership already acquired")
        guard = _exclusive_job_lock(self.path)
        guard.__enter__()
        try:
            self._state = {
                "schema": "neyvia.execution-ownership.v1",
                "taskId": self.task_id,
                "ownerId": uuid.uuid4().hex,
                "host": socket.gethostname(),
                "pid": os.getpid(),
                "status": "running",
                "startedAt": time.time(),
                "heartbeatAt": time.time(),
            }
            atomic_write_json(self.path, self._state)
            self._guard = guard
            self._stop.clear()
            self._thread = threading.Thread(target=self._heartbeat, daemon=True)
            self._thread.start()
            return self.snapshot()
        except BaseException:
            guard.__exit__(None, None, None)
            raise

    def _heartbeat(self):
        while not self._stop.wait(5):
            self._state["heartbeatAt"] = time.time()
            try:
                atomic_write_json(self.path, self._state)
            except OSError:
                # The OS lock remains held. A missing heartbeat cannot start a second executor.
                self._stop.set()

    def exit(self, status="completed"):
        if self._guard is None:
            return
        self._stop.set()
        if self._thread:
            self._thread.join()
        try:
            self._state.update(status=status, finishedAt=time.time())
            atomic_write_json(self.path, self._state)
        finally:
            guard, self._guard = self._guard, None
            guard.__exit__(None, None, None)


async def run_owned(root, task_id, execute):
    """Keep ownership until execution terminates, even if its viewer disconnects."""
    ownership = ExecutionOwnership(root, task_id)
    acquire = asyncio.create_task(asyncio.to_thread(ownership.enter))
    try:
        await asyncio.shield(acquire)
    except asyncio.CancelledError:
        # A queued acquire may finish after cancellation; never leak that lock.
        await acquire
        await asyncio.to_thread(ownership.exit, "cancelled_before_start")
        raise
    running = asyncio.create_task(execute())
    status = "failed"
    try:
        result = await asyncio.shield(running)
        status = result.get("status", "completed") if isinstance(result, dict) else "completed"
        return result
    except asyncio.CancelledError:
        # Provider subprocesses can outlive their awaiting coroutine. Releasing
        # early would admit overlapping execution after a phone disconnect.
        try:
            await asyncio.shield(running)
        finally:
            status = "viewer_detached_execution_finished"
        raise
    finally:
        await asyncio.to_thread(ownership.exit, status)
