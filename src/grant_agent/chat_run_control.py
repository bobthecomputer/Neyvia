"""Cancellation and recovery for a single active chat, shared by desktop and web processes.

The stop request names a turn, never a PID or arbitrary command. The process
which owns that turn observes the request and stops its own runtime child.

A turn can also outlive the process that owned it: the desktop app can crash
or be closed while a response is streaming. The registration then still says
``running`` although nobody will ever finish it. Status reads and stop
requests detect that the owner has exited, record the turn as
``interrupted``, stop any runtime child it left behind, and close the turn's
event stream so every window watching it can settle instead of waiting.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any, Iterator
import uuid


_TURN_ID = re.compile(r"[A-Za-z0-9_.-]{1,180}\Z")
_TOKEN = re.compile(r"[a-f0-9]{32}\Z")
_TERMINAL_STATES = frozenset({"finished", "cancelled", "failed", "interrupted"})
# A process created this long after the run registered cannot be its owner:
# the operating system reused the PID after the original owner exited.
_PID_REUSE_TOLERANCE_SECONDS = 5.0
_MAX_RUNTIME_PROCESSES = 8
_MAX_RESULT_BYTES = 4 * 1024 * 1024
_RESULT_KEYS = (
    "ok", "reply", "finalMessage", "message", "runtime", "sessionId", "externalRuntimeSessionId",
    "route", "status", "error", "elapsedMs", "command", "toolTimeline", "filesChanged",
    "changeEvidenceAvailable", "readOnly", "compartment", "pendingQuestions", "promptHash",
    "turnReceipt", "proofArtifacts", "recovery", "processStopped", "cancelledByUser",
    "conversationPersistence", "completedAt",
)
INTERRUPTED_MESSAGE = "Neyvia closed while this response was running, so it could not finish."


class ChatRunCancelled(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Stopped by you.")
        self.recovery = {
            "code": "user_cancelled",
            "sideEffects": "uncertain",
            "retrySafety": "reconcile_before_retry",
        }


class _ActiveRun:
    __slots__ = ("path", "stop_file", "token")

    def __init__(self, path: Path, stop_file: Path, token: str) -> None:
        self.path = path
        self.stop_file = stop_file
        self.token = token


_current_run: ContextVar[_ActiveRun | None] = ContextVar("neyvia_chat_run", default=None)


def _run_path(root: Path, turn_id: object) -> Path:
    value = str(turn_id or "").strip()
    if not _TURN_ID.fullmatch(value) or value in {".", ".."}:
        raise ValueError("Invalid chat turn id.")
    return Path(root) / ".agent_control" / "chat_runs" / f"{value}.json"


def _result_path(root: Path, turn_id: object) -> Path:
    state_path = _run_path(root, turn_id)
    return state_path.parent / "results" / state_path.name


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".chat-run-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=True, separators=(",", ":"))
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


_write_state = _write_json


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _windows_process_started_at(pid: int) -> float | None:
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        # Access denied still proves the PID exists; its start time is unknown.
        return 0.0 if ctypes.get_last_error() == 5 else None
    try:
        exit_code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            return None  # 259 is STILL_ACTIVE
        creation, exited, kernel_time, user_time = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exited),
                                      ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return 0.0
        ticks = (int(creation.high) << 32) | int(creation.low)
        return ticks / 10_000_000 - 11_644_473_600
    finally:
        kernel.CloseHandle(handle)


def _posix_process_started_at(pid: int) -> float | None:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return 0.0
    except OSError:
        return None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        fields = stat[stat.rindex(")") + 2:].split()
        if fields and fields[0] == "Z":
            return None  # A zombie has exited; only its exit status remains.
        start_ticks = int(fields[19])
        boot_time = next(
            int(line.split()[1])
            for line in Path("/proc/stat").read_text(encoding="ascii").splitlines()
            if line.startswith("btime ")
        )
        return boot_time + start_ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return 0.0


def process_started_at(pid: object) -> float | None:
    """Return a live process's start time; 0.0 when alive but unknown, None when gone."""
    try:
        value = int(pid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    try:
        return _windows_process_started_at(value) if os.name == "nt" else _posix_process_started_at(value)
    except OSError:
        return None


def _owner_alive(state: dict) -> bool:
    started = process_started_at(state.get("processId"))
    if started is None:
        return False
    try:
        registered = float(state.get("processStartedAt") or 0)
    except (TypeError, ValueError):
        registered = 0.0
    if started and registered:
        return abs(started - registered) <= 2.0
    try:
        run_started = float(state.get("startedAt") or 0)
    except (TypeError, ValueError):
        run_started = 0.0
    return not (started and run_started and started > run_started + _PID_REUSE_TOLERANCE_SECONDS)


def _stop_process_tree(pid: int) -> bool:
    try:
        if os.name == "nt":
            completed = subprocess.run(  # noqa: S603
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return completed.returncode == 0
        os.killpg(pid, signal.SIGKILL)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _stop_orphaned_runtime_processes(state: dict) -> list[dict]:
    """Stop runtime children an exited owner left behind, only if their identity still matches."""
    outcomes = []
    for entry in state.get("runtimeProcesses") or []:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("processId")
        try:
            recorded = float(entry.get("processStartedAt") or 0)
        except (TypeError, ValueError):
            recorded = 0.0
        started = process_started_at(pid)
        if started is None:
            outcomes.append({"processId": pid, "state": "already_exited"})
        elif not recorded or not started or abs(started - recorded) > 2.0:
            # Without a matching identity the PID may now belong to something else.
            outcomes.append({"processId": pid, "state": "identity_unverified"})
        else:
            outcomes.append({"processId": pid, "state": "stopped" if _stop_process_tree(int(pid)) else "stop_failed"})
    return outcomes


def _close_stream(root: Path, turn_id: str, status: str, message: str) -> None:
    from .chat_stream import append_chat_stream

    try:
        append_chat_stream(root, turn_id, {"kind": "runtime.done", "status": status, "message": message})
    except (OSError, ValueError):
        pass


def _mark_interrupted(root: Path, path: Path, state: dict) -> dict:
    current = _read_json(path)
    if current is None or current.get("token") != state.get("token") or current.get("state") != "running":
        # The owner finished, or a newer invocation replaced it, after our read.
        return current or state
    interrupted = {
        **current,
        "state": "interrupted",
        "finishedAt": time.time(),
        "interruptedReason": "owner_process_exited",
        "runtimeProcessOutcomes": _stop_orphaned_runtime_processes(current),
    }
    _write_state(path, interrupted)
    for stop_file in path.parent.glob(f"{path.stem}.*.stop"):
        stop_file.unlink(missing_ok=True)
    _close_stream(root, path.stem, "interrupted", INTERRUPTED_MESSAGE)
    return interrupted


@contextmanager
def active_chat_run(root: Path, turn_id: object) -> Iterator[None]:
    """Register the active turn without imposing any elapsed-time deadline."""
    if not str(turn_id or "").strip():
        yield
        return
    path = _run_path(root, turn_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    _result_path(root, turn_id).unlink(missing_ok=True)
    nonce = uuid.uuid4().hex
    stop_file = path.with_name(f"{path.stem}.{nonce}.stop")
    state = {
        "turnId": path.stem, "token": nonce, "state": "running",
        "processId": os.getpid(), "processStartedAt": process_started_at(os.getpid()) or 0.0,
        "startedAt": time.time(),
    }
    _write_state(path, state)
    context_token = _current_run.set(_ActiveRun(path, stop_file, nonce))
    terminal = "finished"
    try:
        yield
    except ChatRunCancelled:
        terminal = "cancelled"
        raise
    except BaseException:
        terminal = "failed"
        raise
    finally:
        _current_run.reset(context_token)
        # Never overwrite the metadata for a newer invocation of this turn.
        try:
            current = _read_json(path)
            if current is not None and current.get("token") == nonce:
                _write_state(path, {**current, "state": terminal, "finishedAt": time.time()})
        finally:
            stop_file.unlink(missing_ok=True)


def note_runtime_process(pid: object) -> None:
    """Remember a runtime child so it can be stopped if its owner disappears."""
    run = _current_run.get()
    if run is None:
        return
    started = process_started_at(pid)
    if not started:
        return
    try:
        current = _read_json(run.path)
        if current is None or current.get("token") != run.token:
            return
        processes = [item for item in current.get("runtimeProcesses") or [] if isinstance(item, dict)]
        processes.append({"processId": int(pid), "processStartedAt": started})  # type: ignore[arg-type]
        _write_state(run.path, {**current, "runtimeProcesses": processes[-_MAX_RUNTIME_PROCESSES:]})
    except (OSError, ValueError, TypeError):
        pass


def chat_cancellation_requested() -> bool:
    run = _current_run.get()
    return run is not None and run.stop_file.is_file()


def _compartment_without_session_window(compartment: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Keep this turn's compartment, not its copy of the session's messages and receipts.

    Nothing that reads a recorded result uses the session window, and the
    persisted conversation turn rebuilds it; record where that turn is.
    """
    from .turn_compartment import WINDOW_KEYS, without_window

    if not any(key in compartment for key in WINDOW_KEYS):
        return compartment
    trimmed = without_window(compartment)
    persistence = result.get("conversationPersistence")
    if isinstance(persistence, dict) and persistence.get("turnId"):
        trimmed["windowRef"] = {
            "conversationId": persistence.get("conversationId"),
            "turnId": persistence.get("turnId"),
        }
    from .proofs_a_control import require
    require(trimmed == {**{key: value for key, value in compartment.items() if key not in WINDOW_KEYS},
                        **({"windowRef": {"conversationId": persistence.get("conversationId"), "turnId": persistence["turnId"]}}
                           if isinstance(persistence, dict) and persistence.get("turnId") else {})},
            "control.result-compaction", "removing the session copy changed turn metadata")
    return trimmed


def compact_recorded_results(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Remove the session window from results recorded before it was left out."""
    report = {"files": 0, "compacted": 0, "bytesBefore": 0, "bytesAfter": 0, "dryRun": dry_run}
    directory = Path(root) / ".agent_control" / "chat_runs" / "results"
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        value = _read_json(path)
        if value is None:
            continue
        size = path.stat().st_size
        report["files"] += 1
        report["bytesBefore"] += size
        compartment = value.get("compartment")
        if not isinstance(compartment, dict):
            report["bytesAfter"] += size
            continue
        trimmed = _compartment_without_session_window(compartment, value)
        if trimmed is compartment:
            report["bytesAfter"] += size
            continue
        value["compartment"] = trimmed
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), default=str)
        report["compacted"] += 1
        report["bytesAfter"] += len(encoded.encode("ascii"))
        if not dry_run:
            _write_json(path, value)
    return report


_RESULT_LOCKS = tuple(threading.RLock() for _ in range(64))


def record_chat_run_result(root: Path, turn_id: object, result: dict[str, Any]) -> None:
    """Keep the final result so a window that reconnects later can show it."""
    if not isinstance(result, dict):
        return
    from .harness_jobs import _exclusive_job_lock
    path = _result_path(root, turn_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _RESULT_LOCKS[hash(str(path.resolve()).casefold()) % len(_RESULT_LOCKS)]
    with lock, _exclusive_job_lock(path, timeout_seconds=30):
        _record_chat_run_result_locked(root, turn_id, result)


def _record_chat_run_result_locked(root: Path, turn_id: object, result: dict[str, Any]) -> None:
    compact = {key: result[key] for key in _RESULT_KEYS if key in result}
    compact.setdefault("completedAt", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if isinstance(compact.get("compartment"), dict):
        compact["compartment"] = _compartment_without_session_window(compact["compartment"], result)
    encoded = json.dumps(compact, ensure_ascii=True, separators=(",", ":"), default=str)
    receipt = compact.get("turnReceipt")
    usage = receipt.get("usage") if isinstance(receipt, dict) else None
    # Drop the compartment first if the result is still oversized, and keep
    # the turn's usage even when its receipt has to go.
    for keys in (("compartment",), ("toolTimeline", "turnReceipt")):
        if len(encoded) <= _MAX_RESULT_BYTES:
            break
        for key in keys:
            compact.pop(key, None)
        if isinstance(usage, dict):
            compact["usage"] = usage
        compact["resultTruncated"] = True
        encoded = json.dumps(compact, ensure_ascii=True, separators=(",", ":"), default=str)
    _write_json(_result_path(root, turn_id), json.loads(encoded))
    from .proofs_a_control import check_recorded_result
    check_recorded_result(result, _read_json(_result_path(root, turn_id)))


def chat_run_status(root: Path, turn_id: object) -> dict[str, Any]:
    """Report whether a turn is really running, reconciling one whose owner exited."""
    path = _run_path(root, turn_id)
    state = _read_json(path)
    result = _read_json(_result_path(root, turn_id))
    if state is None:
        return {"ok": True, "turnId": path.stem, "status": "unknown", "result": result}
    status = str(state.get("state") or "unknown")
    if status == "running" and not _owner_alive(state):
        state = _mark_interrupted(Path(root), path, state)
        status = str(state.get("state") or "interrupted")
    stream = Path(root) / ".agent_control" / "chat_streams" / f"{path.stem}.jsonl"
    try:
        last_activity = stream.stat().st_mtime
    except OSError:
        last_activity = None
    return {
        "ok": True,
        "turnId": path.stem,
        "status": status,
        "startedAt": state.get("startedAt"),
        "finishedAt": state.get("finishedAt"),
        "lastActivityAt": last_activity,
        "stopRequested": status == "running" and any(path.parent.glob(f"{path.stem}.*.stop")),
        "interruptedReason": state.get("interruptedReason", ""),
        "message": INTERRUPTED_MESSAGE if status == "interrupted" else "",
        "result": result if status in _TERMINAL_STATES else None,
    }


def request_chat_cancellation(root: Path, turn_id: object) -> dict:
    path = _run_path(root, turn_id)
    state = _read_json(path)
    if state is None:
        return {"ok": False, "status": "not_running", "turnId": path.stem}
    nonce = str(state.get("token") or "")
    if state.get("state") != "running" or not _TOKEN.fullmatch(nonce):
        return {"ok": True, "status": "already_finished", "turnId": path.stem, "state": state.get("state")}
    if not _owner_alive(state):
        _mark_interrupted(Path(root), path, state)
        return {"ok": True, "status": "interrupted", "turnId": path.stem, "message": INTERRUPTED_MESSAGE}
    stop_file = path.with_name(f"{path.stem}.{nonce}.stop")
    stop_file.write_text(nonce, encoding="ascii")
    return {"ok": True, "status": "stop_requested", "turnId": path.stem}
