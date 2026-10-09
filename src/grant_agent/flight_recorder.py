from __future__ import annotations

from .proofs_b_engine import checked as _proofs_b_checked

import json
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from .durability import append_jsonl_durable, atomic_write_json
from .models import utc_now_iso

MISSION_FLIGHT_RECORDER_EVENT_SCHEMA = "fluxio.mission_flight_recorder_event.v1"
MISSION_FLIGHT_RECORDER_SNAPSHOT_SCHEMA = "fluxio.mission_flight_recorder_snapshot.v1"


class MissionFlightRecorder:
    def __init__(self, root: str | Path, mission_id: str) -> None:
        self.root = Path(root)
        self.mission_id = _compact_text(mission_id, 120)
        self.recorder_dir = self.root / ".agent_control" / "mission_runs" / self.mission_id / "flight_recorder"
        self.events_path = self.recorder_dir / "events.jsonl"
        self.snapshot_path = self.recorder_dir / "snapshot.json"

    @_proofs_b_checked("proofs-b.engine.recorder")
    def append_event(
        self,
        *,
        kind: str,
        message: str,
        phase: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.recorder_dir.mkdir(parents=True, exist_ok=True)
        event = {
            "schema": MISSION_FLIGHT_RECORDER_EVENT_SCHEMA,
            "eventId": f"flight_evt_{uuid.uuid4().hex[:12]}",
            "missionId": self.mission_id,
            "kind": _compact_text(kind, 120),
            "message": _compact_text(message, 500),
            "phase": _compact_text(phase, 80),
            "payload": _compact_mapping(payload or {}, limit=24, text_limit=240),
            "createdAt": utc_now_iso(),
        }
        append_jsonl_durable(self.events_path, event)
        return event

    @_proofs_b_checked("proofs-b.engine.recorder")
    def snapshot(
        self,
        *,
        current_phase: str,
        runtime_command: str = "",
        cwd: str = "",
        env_status: dict[str, Any] | None = None,
        process_ids: list[int] | None = None,
        lease_id: str = "",
        heartbeat_age_seconds: int | None = None,
        queue_reason: str = "",
        stdout_path: str | Path | None = None,
        stderr_path: str | Path | None = None,
        changed_files: list[str] | None = None,
        verifier_result: dict[str, Any] | None = None,
        next_recovery_action: str = "",
    ) -> dict[str, Any]:
        self.recorder_dir.mkdir(parents=True, exist_ok=True)
        events = read_flight_recorder_events(self.events_path, limit=200)
        snapshot = {
            "schema": MISSION_FLIGHT_RECORDER_SNAPSHOT_SCHEMA,
            "missionId": self.mission_id,
            "generatedAt": utc_now_iso(),
            "eventCount": len(events),
            "events": events,
            "currentPhase": _compact_text(current_phase, 80),
            "runtimeCommand": _compact_text(runtime_command, 500),
            "cwd": _compact_text(cwd, 240),
            "envStatus": _compact_mapping(env_status or {}, limit=30, text_limit=120),
            "processIds": [int(pid) for pid in (process_ids or [])[:20]],
            "leaseId": _compact_text(lease_id, 120),
            "heartbeatAgeSeconds": heartbeat_age_seconds,
            "queueReason": _compact_text(queue_reason, 240),
            "stdoutTail": _read_tail(stdout_path),
            "stderrTail": _read_tail(stderr_path),
            "changedFiles": _bounded_strings(changed_files or [], limit=120, text_limit=240),
            "verifierResult": _compact_mapping(verifier_result or {}, limit=24, text_limit=240),
            "nextRecoveryAction": _compact_text(next_recovery_action, 300),
        }
        atomic_write_json(self.snapshot_path, snapshot)
        return snapshot


@_proofs_b_checked("proofs-b.engine.event-tail")
def read_flight_recorder_events(path: str | Path, *, limit: int = 200) -> list[dict[str, Any]]:
    event_path = Path(path)
    if not event_path.exists():
        return []
    tail: deque[dict[str, Any]] = deque(maxlen=max(1, min(int(limit or 1), 200)))
    with event_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                tail.append(row)
    return list(tail)


def _read_tail(path: str | Path | None, *, limit: int = 2000) -> str:
    if path is None:
        return ""
    tail_path = Path(path)
    if not tail_path.exists():
        return ""
    try:
        text = tail_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def _compact_mapping(payload: dict[str, Any], *, limit: int, text_limit: int) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if len(compact) >= limit:
            break
        compact_key = _compact_text(key, 80)
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[compact_key] = _compact_text(value, text_limit) if isinstance(value, str) else value
        elif isinstance(value, list):
            compact[compact_key] = _bounded_strings(value, limit=12, text_limit=text_limit)
        else:
            compact[compact_key] = _compact_text(value, text_limit)
    return compact


def _bounded_strings(values: list[Any], *, limit: int, text_limit: int) -> list[str]:
    output: list[str] = []
    for value in values:
        text = _compact_text(value, text_limit)
        if text:
            output.append(text)
        if len(output) >= limit:
            break
    return output


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
