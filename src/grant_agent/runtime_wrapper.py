from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ExecutionReceipt

RUNTIME_WRAPPER_SCHEMA = "fluxio.runtime_wrapper.v1"
RUNTIME_WRAPPER_STATE_SCHEMA = "fluxio.runtime_wrapper_state.v1"
RUNTIME_WRAPPER_PHASE_EVENT_SCHEMA = "fluxio.runtime_wrapper_phase_event.v1"
RUNTIME_WRAPPER_REPLAY_SCHEMA = "fluxio.runtime_wrapper_replay.v1"
SUPPORTED_RUNTIME_WRAPPERS = ("hermes", "openclaw", "opencode", "codex")


@dataclass
class RuntimeWrapperSpec:
    schema: str
    runtime_id: str
    command: list[str]
    cwd: str
    environment_keys: list[str] = field(default_factory=list)
    timeout_seconds: int = 3600
    stdout_tail_path: str = ""
    stderr_tail_path: str = ""
    event_stream_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeWrapperState:
    schema: str
    runtime_id: str
    cwd: str
    env_status: dict[str, str]
    process_tree: list[dict[str, Any]]
    ttl_seconds: int
    heartbeat_at: str
    heartbeat_age_seconds: int | None
    stdout_tail_path: str
    stderr_tail_path: str
    stdout_tail: str
    stderr_tail: str


def build_runtime_wrapper_spec(
    *,
    runtime_id: str,
    command: list[str],
    cwd: str | Path,
    environment: dict[str, str] | None = None,
    timeout_seconds: int = 3600,
    stdout_tail_path: str = "",
    stderr_tail_path: str = "",
    event_stream_path: str = "",
    metadata: dict[str, Any] | None = None,
) -> RuntimeWrapperSpec:
    normalized_runtime = str(runtime_id or "").strip().lower()
    if normalized_runtime not in SUPPORTED_RUNTIME_WRAPPERS:
        raise ValueError(f"Unsupported runtime wrapper: {runtime_id}")
    clean_command = [str(item) for item in command if str(item or "").strip()]
    if not clean_command:
        raise ValueError("Runtime wrapper command is required")
    return RuntimeWrapperSpec(
        schema=RUNTIME_WRAPPER_SCHEMA,
        runtime_id=normalized_runtime,
        command=clean_command,
        cwd=str(Path(cwd)),
        environment_keys=sorted(str(key) for key in (environment or {}).keys()),
        timeout_seconds=max(1, int(timeout_seconds or 1)),
        stdout_tail_path=stdout_tail_path,
        stderr_tail_path=stderr_tail_path,
        event_stream_path=event_stream_path,
        metadata=dict(metadata or {}),
    )


def runtime_wrapper_payload(spec: RuntimeWrapperSpec) -> dict[str, Any]:
    return asdict(spec)


def build_runtime_wrapper_state(
    spec: RuntimeWrapperSpec,
    *,
    env_status: dict[str, str] | None = None,
    process_tree: list[dict[str, Any]] | None = None,
    ttl_seconds: int | None = None,
    heartbeat_at: str = "",
    tail_bytes: int = 4096,
) -> RuntimeWrapperState:
    return RuntimeWrapperState(
        schema=RUNTIME_WRAPPER_STATE_SCHEMA,
        runtime_id=spec.runtime_id,
        cwd=spec.cwd,
        env_status=dict(env_status or {}),
        process_tree=list(process_tree or []),
        ttl_seconds=max(1, int(ttl_seconds if ttl_seconds is not None else spec.timeout_seconds)),
        heartbeat_at=heartbeat_at,
        heartbeat_age_seconds=_heartbeat_age_seconds(heartbeat_at),
        stdout_tail_path=spec.stdout_tail_path,
        stderr_tail_path=spec.stderr_tail_path,
        stdout_tail=_read_tail(spec.stdout_tail_path, tail_bytes=tail_bytes),
        stderr_tail=_read_tail(spec.stderr_tail_path, tail_bytes=tail_bytes),
    )


def build_runtime_wrapper_phase_event(
    spec: RuntimeWrapperSpec,
    *,
    phase: str,
    status: str,
    message: str,
    mission_id: str = "",
    mission_run_id: str = "",
) -> dict[str, Any]:
    return {
        "schema": RUNTIME_WRAPPER_PHASE_EVENT_SCHEMA,
        "runtimeId": spec.runtime_id,
        "missionId": mission_id,
        "missionRunId": mission_run_id,
        "phase": str(phase or ""),
        "status": str(status or ""),
        "message": str(message or ""),
        "cwd": spec.cwd,
        "eventStreamPath": spec.event_stream_path,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


def build_runtime_wrapper_execution_receipt(
    spec: RuntimeWrapperSpec,
    state: RuntimeWrapperState,
    *,
    receipt_id: str,
    mission_id: str,
    host: str,
    workspace: str,
    status: str,
    summary: str,
    mission_run_id: str = "",
    changed_files: list[str] | None = None,
    errors: list[str] | None = None,
) -> ExecutionReceipt:
    return ExecutionReceipt(
        receipt_id=receipt_id,
        mission_id=mission_id,
        host=host,
        runtime=spec.runtime_id,
        workspace=workspace,
        status=status,
        summary=summary,
        changed_files=list(changed_files or []),
        commands_run=[{"command": " ".join(spec.command), "cwd": spec.cwd, "status": status}],
        stdout_summaries=[state.stdout_tail[-500:]] if state.stdout_tail else [],
        stderr_summaries=[state.stderr_tail[-500:]] if state.stderr_tail else [],
        errors_encountered=list(errors or []),
        proof_paths=[path for path in (spec.event_stream_path, spec.stdout_tail_path, spec.stderr_tail_path) if path],
        next_suggested_verifier_checks=["Inspect runtime wrapper event stream and changed-file proof."],
        mission_run_id=mission_run_id,
        outputs={
            "envStatus": state.env_status,
            "processTree": state.process_tree,
            "heartbeatAgeSeconds": state.heartbeat_age_seconds,
            "ttlSeconds": state.ttl_seconds,
        },
    )


def replay_runtime_wrapper(
    *,
    event_stream_path: str | Path,
    receipt_paths: list[str | Path] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    events = _read_jsonl_events(Path(event_stream_path), limit=limit)
    receipts = []
    for path in receipt_paths or []:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            receipts.append(payload)
    return {
        "schema": RUNTIME_WRAPPER_REPLAY_SCHEMA,
        "eventStreamPath": str(event_stream_path),
        "eventCount": len(events),
        "events": events,
        "receiptCount": len(receipts),
        "receipts": receipts,
        "latestStatus": _latest_status(events, receipts),
    }


def _read_tail(path: str, *, tail_bytes: int) -> str:
    if not path:
        return ""
    candidate = Path(path)
    try:
        with candidate.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max(1, int(tail_bytes or 1))))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _read_jsonl_events(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, int(limit or 1)) :]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _latest_status(events: list[dict[str, Any]], receipts: list[dict[str, Any]]) -> str:
    if receipts:
        status = str(receipts[-1].get("status") or "")
        if status:
            return status
    for event in reversed(events):
        status = str(event.get("status") or "")
        if status:
            return status
    return "unknown"


def _heartbeat_age_seconds(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()))


from .proofs_d_runtime import checked as _checked
build_runtime_wrapper_spec = _checked("d.runtime.wrapper.spec", build_runtime_wrapper_spec)
build_runtime_wrapper_state = _checked("d.runtime.wrapper.state", build_runtime_wrapper_state)
build_runtime_wrapper_phase_event = _checked("d.runtime.wrapper.event", build_runtime_wrapper_phase_event)
build_runtime_wrapper_execution_receipt = _checked("d.runtime.wrapper.receipt", build_runtime_wrapper_execution_receipt)
replay_runtime_wrapper = _checked("d.runtime.wrapper.replay", replay_runtime_wrapper)
