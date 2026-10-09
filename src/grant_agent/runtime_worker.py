from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

try:
    from .cluster import ClusterRegistry
    from .subprocess_utils import background_creationflags, hidden_windows_subprocess_kwargs, split_process_command, install_hidden_subprocess_default
    from .runtimes.base import runtime_subprocess_env
    from .durability import file_transaction
except ImportError:  # pragma: no cover - direct script fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from grant_agent.cluster import ClusterRegistry
    from grant_agent.subprocess_utils import background_creationflags, hidden_windows_subprocess_kwargs, split_process_command, install_hidden_subprocess_default
    from grant_agent.runtimes.base import runtime_subprocess_env
    from grant_agent.durability import file_transaction

STRUCTURED_EVENT_PREFIX = "FLUXIO_EVENT:"
HEARTBEAT_INTERVAL_SECONDS = max(
    float(os.environ.get("FLUXIO_HEARTBEAT_INTERVAL_SECONDS", "10")),
    0.05,
)
RUNTIME_NO_OUTPUT_TIMEOUT_SECONDS = max(
    float(os.environ.get("FLUXIO_RUNTIME_NO_OUTPUT_TIMEOUT_SECONDS", "0")),
    0.0,
)
SNAPSHOT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".agent_control",
    ".agent_runs",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "target",
}
SNAPSHOT_MAX_FILES = max(int(os.environ.get("FLUXIO_DELEGATED_SNAPSHOT_MAX_FILES", "8000")), 100)
CHANGED_FILE_LIMIT = max(int(os.environ.get("FLUXIO_DELEGATED_CHANGED_FILE_LIMIT", "240")), 20)
_STATE_LOCK = threading.RLock()


def _load_state(path: Path) -> dict:
    if not path.parent.exists():
        return {}
    with file_transaction(path):
        if not path.exists():
            return {}
        return _read_json_with_retries(path)


def _write_state(path: Path, updates: dict) -> dict:
    with _STATE_LOCK, file_transaction(path):
        payload = _load_state(path)
        payload.update(updates)
        _atomic_write_json(path, payload)
        return payload


def _append_event(session_path: Path, *, kind: str, message: str, status: str = "", data: dict | None = None) -> dict:
    with _STATE_LOCK:
        return _append_event_locked(
            session_path,
            kind=kind,
            message=message,
            status=status,
            data=data,
        )


def _append_event_locked(session_path: Path, *, kind: str, message: str, status: str = "", data: dict | None = None) -> dict:
    payload = _load_state(session_path)
    events_path = Path(payload.get("events_path", session_path.with_suffix(".events.jsonl"))).resolve()
    events_path.parent.mkdir(parents=True, exist_ok=True)
    event_timestamp = _utc_now()
    event = {
        "event_id": f"evt_{uuid.uuid4().hex[:10]}",
        "delegated_id": payload.get("delegated_id", ""),
        "runtime_id": payload.get("runtime_id", ""),
        "kind": kind,
        "message": message,
        "status": status or payload.get("status", ""),
        "created_at": event_timestamp,
        "data": data or {},
    }
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True) + "\n")
    latest_events, event_count = _read_events(events_path, max_events=5)
    updates = {
        "updated_at": event_timestamp,
        "last_event": message,
        "last_event_kind": kind,
        "latest_events": latest_events,
        "event_cursor": event_count,
    }
    current_status = str(event["status"] or "")
    if current_status in {"launching", "running", "waiting_for_approval"}:
        updates["heartbeat_at"] = event_timestamp
        updates["heartbeat_status"] = "healthy"
        updates["heartbeat_interval_seconds"] = max(
            int(round(HEARTBEAT_INTERVAL_SECONDS)),
            1,
        )
    elif current_status in {"completed", "failed", "stopped"}:
        updates["heartbeat_status"] = "inactive"
    _write_state(
        session_path,
        updates,
    )
    return event


def _read_events(path: Path, max_events: int = 0) -> tuple[list[dict], int]:
    if not path.exists():
        return [], 0
    event_count = 0
    if max_events > 0:
        rows: deque[dict] = deque(maxlen=max_events)
    else:
        rows = deque()
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_count += 1
            rows.append(event)
    return list(rows), event_count


def _read_json_with_retries(path: Path, retries: int = 8, delay: float = 0.02) -> dict:
    with file_transaction(path):
        return _read_json_locked(path, retries, delay)


def _read_json_locked(path: Path, retries: int, delay: float) -> dict:
    last_error: json.JSONDecodeError | None = None
    for attempt in range(retries):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            last_error = exc
            if attempt == retries - 1:
                break
            time.sleep(delay)
    raise RuntimeError(f"Unable to read delegated runtime state from {path}") from last_error


def _atomic_write_json(path: Path, payload: dict) -> None:
    with file_transaction(path):
        _atomic_write_json_locked(path, payload)


def _atomic_write_json_locked(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for attempt in range(10):
        try:
            temp_path.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                break
            time.sleep(0.02)
    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        pass
    raise PermissionError(f"Unable to atomically update delegated runtime state at {path}")


def _creationflags() -> int:
    return background_creationflags()


def _runtime_env(session_path: Path, cwd: Path) -> dict[str, str]:
    payload = _load_state(session_path)
    env = runtime_subprocess_env(cwd)
    env["FLUXIO_SESSION_FILE"] = str(session_path.resolve())
    env["FLUXIO_EVENTS_FILE"] = str(Path(payload.get("events_path", session_path.with_suffix(".events.jsonl"))).resolve())
    env["FLUXIO_LOG_FILE"] = str(Path(payload.get("log_path", session_path.with_suffix(".log"))).resolve())
    env["FLUXIO_APPROVAL_FILE"] = str(Path(payload.get("decision_path", session_path.with_suffix(".approval.json"))).resolve())
    env["FLUXIO_EXECUTION_ROOT"] = str(cwd.resolve())
    env["FLUXIO_CLUSTER_JOB_ID"] = str(
        payload.get("cluster_job_id") or env.get("FLUXIO_CLUSTER_JOB_ID", "")
    )
    env["FLUXIO_CLUSTER_LEASE_ID"] = str(
        payload.get("host_lease_id") or env.get("FLUXIO_CLUSTER_LEASE_ID", "")
    )
    env["FLUXIO_CLUSTER_HOST_ID"] = str(
        payload.get("assigned_host") or env.get("FLUXIO_CLUSTER_HOST_ID", "")
    )
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _cluster_registry_for_session(payload: dict) -> ClusterRegistry | None:
    job_id = str(payload.get("cluster_job_id") or os.environ.get("FLUXIO_CLUSTER_JOB_ID") or "")
    lease_id = str(payload.get("host_lease_id") or os.environ.get("FLUXIO_CLUSTER_LEASE_ID") or "")
    if not job_id or not lease_id:
        return None
    root = str(os.environ.get("FLUXIO_CLUSTER_ROOT") or "").strip()
    if not root:
        session_path = str(payload.get("session_path") or "").strip()
        root = str(Path(session_path).resolve().parents[2]) if session_path else "."
    try:
        return ClusterRegistry(Path(root))
    except Exception:
        return None


def _heartbeat_cluster_lease(session_path: Path, *, process_id: int = 0) -> None:
    try:
        payload = _load_state(session_path)
        registry = _cluster_registry_for_session(payload)
        if registry is None:
            return
        lease_id = str(payload.get("host_lease_id") or os.environ.get("FLUXIO_CLUSTER_LEASE_ID") or "")
        host_id = str(payload.get("assigned_host") or os.environ.get("FLUXIO_CLUSTER_HOST_ID") or "")
        if lease_id and host_id:
            registry.heartbeat_lease(
                lease_id=lease_id,
                host_id=host_id,
                process_id=process_id,
            )
    except Exception:
        return


def _complete_cluster_job(
    session_path: Path,
    *,
    status: str,
    detail: str,
    return_code: int,
    changed_files: list[str],
) -> None:
    try:
        payload = _load_state(session_path)
        registry = _cluster_registry_for_session(payload)
        if registry is None:
            return
        job_id = str(payload.get("cluster_job_id") or os.environ.get("FLUXIO_CLUSTER_JOB_ID") or "")
        lease_id = str(payload.get("host_lease_id") or os.environ.get("FLUXIO_CLUSTER_LEASE_ID") or "")
        host_id = str(payload.get("assigned_host") or os.environ.get("FLUXIO_CLUSTER_HOST_ID") or "")
        if not job_id or not lease_id or not host_id:
            return
        registry.complete_job(
            job_id=job_id,
            lease_id=lease_id,
            host_id=host_id,
            status=status,
            detail=detail,
            changed_files=changed_files,
            result={"returnCode": return_code},
        )
    except Exception:
        return


def _runtime_path_entries(cwd: Path) -> list[str]:
    candidates = [
        cwd / ".venv" / "bin",
        cwd / "venv" / "bin",
        cwd / ".agent_control" / "runtime" / "bin",
        cwd.parent / "runtime" / "bin",
        cwd.parent / "syntelos" / "runtime" / "bin",
    ]
    entries: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.exists():
            continue
        value = str(candidate.resolve())
        if value in seen:
            continue
        entries.append(value)
        seen.add(value)
    return entries


def _parse_structured_event(line: str) -> dict | None:
    candidate = line.strip()
    if candidate.startswith(STRUCTURED_EVENT_PREFIX):
        candidate = candidate[len(STRUCTURED_EVENT_PREFIX) :].strip()
    else:
        return None
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _wait_for_approval(session_path: Path, child: subprocess.Popen, request: dict) -> str:
    payload = _load_state(session_path)
    decision_path = Path(payload.get("decision_path", session_path.with_suffix(".approval.json"))).resolve()
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        if decision_path.exists():
            try:
                decision = json.loads(decision_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                decision = {}
            status = str(decision.get("status", "approved"))
            resolved_at = str(decision.get("resolved_at", _utc_now()))
            request["status"] = status
            request["resolved_at"] = resolved_at
            request["resolved_by"] = str(decision.get("actor", "operator"))
            history = list(payload.get("approval_history", []))
            history.append(request)
            if status == "approved":
                _write_state(
                    session_path,
                    {
                        "status": "running",
                        "detail": "Delegated runtime resumed after approval.",
                        "pending_approval": {},
                        "approval_history": history,
                    },
                )
                _append_event(
                    session_path,
                    kind="approval.resolved",
                    message="Delegated approval approved by operator.",
                    status="running",
                    data={"request_id": request.get("request_id"), "decision": "approved"},
                )
                return "approved"
            _terminate_child(child)
            _write_state(
                session_path,
                {
                    "status": "failed",
                    "detail": "Delegated runtime was rejected by operator.",
                    "pending_approval": request,
                    "approval_history": history,
                },
            )
            _append_event(
                session_path,
                kind="approval.rejected",
                message="Delegated approval rejected by operator.",
                status="failed",
                data={"request_id": request.get("request_id"), "decision": "rejected"},
            )
            return "rejected"

        if child.poll() is not None:
            return "child_exited"
        time.sleep(0.1)


def _heartbeat_message(status: str) -> str:
    normalized = (status or "running").strip().lower()
    if normalized == "waiting_for_approval":
        return "Delegated runtime heartbeat: waiting for approval."
    if normalized == "launching":
        return "Delegated runtime heartbeat: launch still in progress."
    return "Delegated runtime heartbeat: session is healthy."


def _heartbeat_loop(
    session_path: Path,
    child: subprocess.Popen,
    stop_event: threading.Event,
) -> None:
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        if child.poll() is not None:
            return
        payload = _load_state(session_path)
        status = str(payload.get("status", "running"))
        if status in {"completed", "failed", "stopped"}:
            return
        _append_event(
            session_path,
            kind="session.heartbeat",
            message=_heartbeat_message(status),
            status=status,
            data={"phase": status},
        )
        _heartbeat_cluster_lease(session_path, process_id=child.pid)


def _no_output_watchdog_loop(
    session_path: Path,
    child: subprocess.Popen,
    stop_event: threading.Event,
    last_output_at: list[float],
) -> None:
    timeout = RUNTIME_NO_OUTPUT_TIMEOUT_SECONDS
    if timeout <= 0:
        return
    poll_interval = min(max(timeout / 4, 0.05), 1.0)
    while not stop_event.wait(poll_interval):
        if child.poll() is not None:
            return
        if time.monotonic() - last_output_at[0] <= timeout:
            continue
        detail = (
            f"Delegated runtime produced no stdout for {timeout:.1f} seconds "
            "after launch."
        )
        _write_state(
            session_path,
            {
                "status": "failed",
                "exit_code": -1,
                "updated_at": _utc_now(),
                "detail": detail,
                "heartbeat_status": "inactive",
            },
        )
        _append_event(
            session_path,
            kind="session.failed",
            message=detail,
            status="failed",
            data={"reason": "no_output_timeout", "pid": child.pid},
        )
        _terminate_child(child)
        return


def run(session_path: Path, cwd: Path, command: str) -> int:
    session_path = session_path.resolve()
    cwd = cwd.resolve()
    payload = _load_state(session_path)
    log_path = Path(payload.get("log_path", session_path.with_suffix(".log"))).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    events_path = Path(payload.get("events_path", session_path.with_suffix(".events.jsonl"))).resolve()
    decision_path = Path(payload.get("decision_path", session_path.with_suffix(".approval.json"))).resolve()
    before_snapshot = _workspace_snapshot(cwd)

    _write_state(
        session_path,
        {
            "status": "launching",
            "supervisor_pid": os.getpid(),
            "updated_at": _utc_now(),
            "detail": "Launching delegated runtime process.",
            "events_path": str(events_path),
            "decision_path": str(decision_path),
            "heartbeat_at": _utc_now(),
            "heartbeat_status": "healthy",
            "heartbeat_interval_seconds": max(
                int(round(HEARTBEAT_INTERVAL_SECONDS)),
                1,
            ),
        },
    )
    _append_event(
        session_path,
        kind="session.launching",
        message="Launching delegated runtime process.",
        status="launching",
    )
    _heartbeat_cluster_lease(session_path, process_id=os.getpid())

    with log_path.open("a", encoding="utf-8") as handle:
        popen_command = _popen_command(command)
        child = subprocess.Popen(  # noqa: S603
            popen_command,
            shell=False,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_creationflags(),
            env=_runtime_env(session_path, cwd),
        )

        _write_state(
            session_path,
            {
                "status": "running",
                "pid": child.pid,
                "updated_at": _utc_now(),
                "detail": "Delegated runtime process is running.",
            },
        )
        _append_event(
            session_path,
            kind="session.running",
            message="Delegated runtime process is running.",
            status="running",
        )
        _heartbeat_cluster_lease(session_path, process_id=child.pid)
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(session_path, child, heartbeat_stop),
            daemon=True,
        )
        heartbeat_thread.start()
        watchdog_stop = threading.Event()
        last_output_at = [time.monotonic()]
        watchdog_thread = threading.Thread(
            target=_no_output_watchdog_loop,
            args=(session_path, child, watchdog_stop, last_output_at),
            daemon=True,
        )
        watchdog_thread.start()

        if child.stdout is not None:
            for raw_line in iter(child.stdout.readline, ""):
                if not raw_line:
                    if child.poll() is not None:
                        break
                    continue
                last_output_at[0] = time.monotonic()
                handle.write(raw_line)
                handle.flush()
                line = raw_line.strip()
                if not line:
                    continue
                structured = _parse_structured_event(line)
                if structured is None:
                    _append_event(
                        session_path,
                        kind="runtime.output",
                        message=line,
                        status="running",
                    )
                    continue

                kind = str(structured.get("kind", "runtime.event"))
                message = str(structured.get("message", line))
                runtime_status = str(structured.get("status", "running"))
                event_data = dict(structured.get("data", {}))
                if kind == "approval.request":
                    request = {
                        "request_id": str(structured.get("request_id", f"approval_{uuid.uuid4().hex[:8]}")),
                        "delegated_id": payload.get("delegated_id", ""),
                        "runtime_id": payload.get("runtime_id", ""),
                        "prompt": message,
                        "risk_level": str(structured.get("risk_level", event_data.get("risk_level", "medium"))),
                        "status": "pending",
                        "created_at": _utc_now(),
                        "resolved_at": None,
                        "resolved_by": "",
                        "metadata": event_data,
                    }
                    _write_state(
                        session_path,
                        {
                            "status": "waiting_for_approval",
                            "detail": "Delegated runtime is waiting for approval.",
                            "pending_approval": request,
                        },
                    )
                    _append_event(
                        session_path,
                        kind="approval.request",
                        message=message,
                        status="waiting_for_approval",
                        data=event_data,
                    )
                    decision = _wait_for_approval(session_path, child, request)
                    if decision == "rejected":
                        break
                    continue

                _write_state(
                    session_path,
                    {
                        "status": runtime_status or "running",
                        "detail": message,
                    },
                )
                _append_event(
                    session_path,
                    kind=kind,
                    message=message,
                    status=runtime_status or "running",
                    data=event_data,
                )

    heartbeat_stop.set()
    watchdog_stop.set()
    heartbeat_thread.join(timeout=1)
    watchdog_thread.join(timeout=1)
    return_code = child.wait()
    summary = _tail_summary(log_path)
    existing = _load_state(session_path)
    changed_files = _changed_files_since(before_snapshot, _workspace_snapshot(cwd))
    try:
        decision_path.unlink(missing_ok=True)
    except OSError:
        pass
    if existing.get("status") == "failed" and existing.get("pending_approval", {}).get("status") == "rejected":
        final_status = "failed"
    elif existing.get("status") == "stopped":
        final_status = "stopped"
    else:
        final_status = "completed" if return_code == 0 else "failed"
    final_detail = summary or (
        "Delegated runtime completed."
        if final_status == "completed"
        else str(existing.get("detail") or "Delegated runtime failed.")
    )
    _complete_cluster_job(
        session_path,
        status=final_status,
        detail=final_detail,
        return_code=return_code,
        changed_files=changed_files,
    )
    _write_state(
        session_path,
        {
            "status": final_status,
            "exit_code": return_code,
            "updated_at": _utc_now(),
            "detail": (
                "Delegated runtime process completed."
                if final_status == "completed"
                else str(existing.get("detail") or "Delegated runtime process failed.")
            ),
            "last_event": summary or "runtime_finished",
            "changed_files": changed_files,
            "heartbeat_status": "inactive",
        },
    )
    _append_event(
        session_path,
        kind="session.completed" if final_status == "completed" else "session.failed",
        message=summary or ("Delegated runtime completed." if final_status == "completed" else "Delegated runtime failed."),
        status=final_status,
        data={"exit_code": return_code, "changed_files": changed_files},
    )
    return return_code


def _popen_command(command: str) -> list[str]:
    try:
        args = split_process_command(str(command or "")) if str(command or "").strip() else []
    except ValueError:
        args = []
    if not args:
        raise ValueError("Delegated runtime command is empty or malformed.")
    return args


def _workspace_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return snapshot
    scanned = 0
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            dirname for dirname in dirnames if dirname not in SNAPSHOT_EXCLUDED_DIRS
        ]
        current = Path(current_root)
        for filename in filenames:
            if scanned >= SNAPSHOT_MAX_FILES:
                return snapshot
            path = current / filename
            try:
                relative_parts = path.relative_to(root).parts
                stat = path.stat()
            except OSError:
                continue
            snapshot["/".join(relative_parts)] = (stat.st_size, stat.st_mtime_ns)
            scanned += 1
    return snapshot


def _changed_files_since(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
) -> list[str]:
    changed = [
        path
        for path, signature in after.items()
        if before.get(path) != signature
    ]
    changed.extend(path for path in before if path not in after)
    return sorted(dict.fromkeys(changed))[:CHANGED_FILE_LIMIT]


def _terminate_child(child: subprocess.Popen) -> None:
    if child.poll() is not None:
        return
    if os.name == "nt":
        completed = subprocess.run(  # noqa: S603
            ["taskkill", "/PID", str(child.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        if completed.returncode != 0 and child.poll() is None:
            try:
                child.terminate()
            except OSError:
                pass
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                child.kill()
                child.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return
    try:
        child.send_signal(signal.SIGTERM)
    except OSError:
        return


def _tail_summary(log_path: Path, max_lines: int = 3) -> str:
    if not log_path.exists():
        return ""
    lines = [line.strip() for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    messages = [event.get("message", "") for line in lines
                if (event := _parse_structured_event(line)) and event.get("kind") == "runtime.model_message"]
    if messages:
        return str(messages[-1])
    return " | ".join(lines[-max_lines:])


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    install_hidden_subprocess_default()
    parser = argparse.ArgumentParser(description="Neyvia delegated runtime worker")
    parser.add_argument("--session", required=True, help="Delegated session JSON path")
    parser.add_argument("--cwd", required=True, help="Working directory")
    parser.add_argument("--command", required=True, help="Shell command to execute")
    args = parser.parse_args(argv)
    return run(Path(args.session), Path(args.cwd), args.command)


if __name__ == "__main__":
    raise SystemExit(main())
