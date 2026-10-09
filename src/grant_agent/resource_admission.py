"""Crash-safe managed-process admission; shared slots plus an operator reserve.

This limits cooperating processes in one workspace. It is not a GPU quota,
cross-workspace scheduler, or OS-level CPU reservation.
"""
import os
from pathlib import Path
from .harness_jobs import _try_advisory_job_lock, _release_advisory_job_lock


class ProcessAdmission:
    def __init__(self, root):
        self.base = Path(root) / ".agent_control" / "process_admission"
        self.base.mkdir(parents=True, exist_ok=True)
        self.descriptor = None
        self.slot = None

    def acquire(self, actor):
        if self.descriptor is not None:
            return True
        slots = ["operator-reserve", "shared-0", "shared-1"] if actor == "operator" else ["shared-0", "shared-1"]
        for slot in slots:
            fd = os.open(self.base / (slot + ".guard"), os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
            try:
                acquired = _try_advisory_job_lock(fd)
            except BaseException:
                os.close(fd)
                raise
            if acquired:
                self.descriptor, self.slot = fd, slot
                return True
            os.close(fd)
        return False

    def release(self):
        if self.descriptor is not None:
            try:
                _release_advisory_job_lock(self.descriptor)
            finally:
                os.close(self.descriptor)
                self.descriptor = None

