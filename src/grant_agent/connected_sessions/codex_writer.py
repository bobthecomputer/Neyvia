"""Read-only probes of Codex's cross-process writer lock (never touch rollouts)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from ..proofs_a_providers import checked


@checked("providers.codex.lock")
def active_writer(thread_id: str, rollout_path: Any) -> bool | None:
    """True while locked, False when released, None for legacy/unreadable stores.

    Probe an existing file only; neither create/remove locks nor rely on their age.
    The OS releases the probe immediately and releases crashed writers' locks too.
    """
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    if rollout_path:
        for parent in Path(str(rollout_path)).parents:
            if parent.name in ("sessions", "archived_sessions"):
                home = parent.parent
                break
    from ..proofs_e_host import check_writer_home, writer_result
    check_writer_home(home, rollout_path)
    directory = home / "thread-writer-locks"
    if not directory.is_dir():
        return writer_result(None, "legacy")
    if not isinstance(thread_id, str) or not thread_id or any(c in thread_id for c in "/\\\x00") or thread_id in (".", ".."):
        return writer_result(None, "invalid-id")
    # Include the .lock suffix in the portable component bound. Windows may
    # report an overlong name as FileNotFoundError; that is not a missing writer.
    try:
        identity_bytes = thread_id.encode("utf-8")
    except UnicodeEncodeError:
        return writer_result(None, "invalid-id")
    if len(identity_bytes) > 250:
        return writer_result(None, "invalid-id")
    try:
        with (directory / f"{thread_id}.lock").open("rb") as file:
            if os.name == "nt":
                return _windows_locked(file)
            import fcntl
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return writer_result(True, "locked")
            fcntl.flock(file, fcntl.LOCK_UN)
            return writer_result(False, "released")
    except FileNotFoundError:
        return writer_result(False, "missing")
    except OSError as exc:
        error = getattr(exc, "winerror", None)
        return writer_result(True if error in (32, 33) else None, "os-error", error)


def _windows_locked(file: Any) -> bool | None:
    import ctypes
    import msvcrt
    from ctypes import wintypes
    from ..proofs_e_host import writer_result

    class Overlapped(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                    ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
    kernel.LockFileEx.restype = wintypes.BOOL
    kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD, ctypes.POINTER(Overlapped)]
    kernel.UnlockFileEx.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(file.fileno())
    overlapped = Overlapped()
    if not kernel.LockFileEx(handle, 3, 0, 1, 0, ctypes.byref(overlapped)):
        error = ctypes.get_last_error()
        return writer_result(True if error in (32, 33) else None, "os-error", error)
    kernel.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped))
    return writer_result(False, "released")
