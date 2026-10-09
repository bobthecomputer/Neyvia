"""Concrete artifact and planned-scope completion gates.

The public control-room facade owns collaborators. Resolve it at call time so
existing monkeypatch and late-binding seams survive the responsibility split.
"""
from __future__ import annotations
from .proofs_c_control import checked as _control_checked
from .proofs_c_missions import checked_local_mission as _mission_local_checked

from pathlib import Path
from .models import (
    Mission,
    DelegatedRuntimeSession,
)


def _control_room_facade():
    from . import mission_control
    return mission_control

def _runtime_transcript_artifact_evidence_items(
    *,
    runtime_transcript: dict | None = None,
    agent_messages: list[dict] | None = None,
    mission_events: list[dict] | None = None,
) -> list[dict[str, str]]:
    _facade = _control_room_facade()
    items: list[dict[str, str]] = []

    def mission_artifact_path(value: object) -> str:
        path = str(value or "").strip()
        normalized = path.replace("\\", "/")
        if "/.agent_control/mission_artifacts/" not in normalized:
            return ""
        return path

    def add_from_row(row: dict, *, default_source: str) -> None:
        source = str(row.get("label") or default_source or "runtime_transcript")
        for field in ("artifactPath", "path", "targetPath", "target_path", "servedUrl", "previewUrl"):
            path = mission_artifact_path(row.get(field))
            if path:
                items.append({"source": source, "detail": path[:240]})
        detail = _facade._gate_text(row.get("detail") or row.get("message") or "")
        match = _facade.re.search(
            r"(?:target|artifact(?:\s+path)?|path):\s*([^\s]+/.agent_control/mission_artifacts/[^\s]+)",
            detail,
            flags=_facade.re.IGNORECASE,
        )
        if match:
            items.append({"source": source, "detail": match.group(1)[:240]})
        technical = row.get("technicalDetail") or row.get("technical_detail") or {}
        if isinstance(technical, str) and technical.strip().startswith("{"):
            try:
                technical = _facade.json.loads(technical)
            except _facade.json.JSONDecodeError:
                technical = {}
        if isinstance(technical, dict):
            for field in ("target_path", "artifactPath", "path", "servedUrl", "previewUrl"):
                path = mission_artifact_path(technical.get(field))
                if path:
                    items.append({"source": source, "detail": path[:240]})

    rows: list[dict] = []
    if isinstance(runtime_transcript, dict) and isinstance(runtime_transcript.get("messages"), list):
        rows.extend(row for row in runtime_transcript.get("messages", []) if isinstance(row, dict))
    rows.extend(row for row in list(agent_messages or []) if isinstance(row, dict))
    for row in rows:
        add_from_row(row, default_source="runtime_transcript.messages")
    for event in list(mission_events or []):
        if not isinstance(event, dict):
            continue
        event_data = event.get("data") if isinstance(event.get("data"), dict) else {}
        event_row = {
            **event_data,
            "label": event.get("kind") or "mission_event",
            "detail": event.get("message") or "",
        }
        add_from_row(event_row, default_source="mission_events")

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item["source"], item["detail"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _mission_artifact_evidence_items(
    mission: Mission,
    *,
    runtime_transcript: dict | None = None,
    agent_messages: list[dict] | None = None,
    mission_events: list[dict] | None = None,
) -> list[dict[str, str]]:
    _facade = _control_room_facade()
    items: list[dict[str, str]] = []

    def add(source: str, value: object) -> None:
        if value is None:
            return
        if isinstance(value, str):
            if _facade._gate_has_meaningful_text(value):
                items.append({"source": source, "detail": value[:240]})
            return
        if isinstance(value, dict):
            label = (
                value.get("servedUrl")
                or value.get("previewUrl")
                or value.get("artifactPath")
                or value.get("path")
                or value.get("summary")
                or value.get("label")
                or value.get("artifact_id")
                or value.get("artifactId")
            )
            if label:
                items.append({"source": source, "detail": str(label)[:240]})
            return
        if _facade._gate_has_meaningful_text(value):
            items.append({"source": source, "detail": str(value)[:240]})

    for artifact in list(getattr(mission.proof, "artifacts", []) or []):
        add("proof.artifacts", artifact)
    for artifact in list(getattr(mission.code_execution, "artifacts", []) or []):
        add("code_execution.artifacts", artifact)
    state_code_execution = (
        mission.state.code_execution if isinstance(mission.state.code_execution, dict) else {}
    )
    for artifact in list(state_code_execution.get("artifacts", []) or []):
        add("state.code_execution.artifacts", artifact)
    for action in list(mission.action_history or [])[-12:]:
        action_row = _facade._gate_mapping(action)
        proposal = _facade._gate_mapping(
            action_row.get("proposal") if isinstance(action_row, dict) else getattr(action, "proposal", {})
        )
        result = _facade._gate_mapping(
            action_row.get("result") if isinstance(action_row, dict) else getattr(action, "result", {})
        )
        if str(proposal.get("kind") or "").strip() in {"file_write", "file_patch"}:
            add("action_history.proposal", proposal.get("target_path") or proposal.get("targetPath"))
        stdout = str(result.get("stdout") or "")
        match = _facade.re.search(r"([^\s]+/.agent_control/mission_artifacts/[^\s]+)", stdout)
        if match:
            add("action_history.result", match.group(1))
    items.extend(
        _facade._runtime_transcript_artifact_evidence_items(
            runtime_transcript=runtime_transcript,
            agent_messages=agent_messages,
            mission_events=mission_events,
        )
    )
    return items


def _mission_artifact_root_candidates(
    mission: Mission,
    *,
    root: Path | None = None,
) -> list[Path]:
    _facade = _control_room_facade()
    raw_candidates: list[object] = [root, _facade.Path.cwd()]
    execution_scope = getattr(mission, "execution_scope", None)
    for field_name in ("execution_root", "workspace_root", "worktree_path"):
        raw_candidates.append(getattr(execution_scope, field_name, "") if execution_scope else "")
    state_scope = mission.state.execution_scope if isinstance(mission.state.execution_scope, dict) else {}
    for field_name in ("execution_root", "workspace_root", "worktree_path"):
        raw_candidates.append(state_scope.get(field_name, ""))

    candidates: list[_facade.Path] = []
    seen: set[str] = set()
    for raw_candidate in raw_candidates:
        if raw_candidate is None:
            continue
        try:
            candidate = raw_candidate if isinstance(raw_candidate, _facade.Path) else _facade.Path(str(raw_candidate))
        except (TypeError, ValueError):
            continue
        if not str(candidate).strip():
            continue
        try:
            candidate = candidate.expanduser().resolve()
        except OSError:
            candidate = candidate.expanduser()
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _read_gate_json(path: Path) -> dict:
    _facade = _control_room_facade()
    try:
        value = _facade.json.loads(path.read_text(encoding="utf-8"))
    except (OSError, _facade.json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_gate_text(path: Path, *, max_chars: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def _delegated_session_value(session: object, key: str, default: object = "") -> object:
    if isinstance(session, dict):
        return session.get(key, default)
    return getattr(session, key, default)


def _runtime_event_metadata(row: dict) -> dict:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    if metadata:
        return metadata
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    return data


def _delegated_runtime_event_rows(
    session: DelegatedRuntimeSession | dict,
    *,
    limit: int = 40,
) -> list[dict]:
    _facade = _control_room_facade()
    rows: list[dict] = []
    seen: set[str] = set()
    normalized_limit = max(1, int(limit or 1))

    def append(row: object) -> None:
        if not isinstance(row, dict):
            return
        key = str(row.get("event_id") or row.get("id") or "").strip()
        if not key:
            key = _facade.hashlib.sha1(
                _facade.json.dumps(row, sort_keys=True, default=str).encode("utf-8", errors="ignore")
            ).hexdigest()
        if key in seen:
            return
        seen.add(key)
        rows.append(row)

    events_path_value = str(_facade._delegated_session_value(session, "events_path", "") or "").strip()
    if events_path_value:
        events_path = _facade.Path(events_path_value)
        for row in _facade._read_jsonl_tail(events_path, limit=normalized_limit):
            append(row)
    for row in list(_facade._delegated_session_value(session, "latest_events", []) or [])[-normalized_limit:]:
        append(row)
    return rows[-normalized_limit:]


def _low_signal_delegated_runtime_event(kind: str, message: str) -> bool:
    normalized = " ".join(str(message or "").strip().lower().split())
    if not normalized:
        return True
    if normalized in {"running", "launching", "queued", "completed"}:
        return True
    if normalized.startswith("delegated runtime heartbeat"):
        return True
    kind_normalized = str(kind or "").strip().lower()
    return kind_normalized in {"session.heartbeat", "session.queued", "session.launching"}


def _delegated_runtime_event_transcript_messages(
    mission: Mission,
    *,
    limit: int = 10,
) -> tuple[list[dict], list[str], list[str]]:
    _facade = _control_room_facade()
    messages: list[dict] = []
    session_ids: list[str] = []
    sources: list[str] = []
    seen_messages: set[str] = set()
    event_limit = max(limit * 5, 30)

    for session in list(mission.delegated_runtime_sessions or [])[-8:]:
        session_id = str(
            _facade._delegated_session_value(session, "delegated_id", "")
            or _facade._delegated_session_value(session, "runtime_id", "")
            or ""
        ).strip()
        if session_id and session_id not in session_ids:
            session_ids.append(session_id)
        runtime_id = str(_facade._delegated_session_value(session, "runtime_id", "") or mission.runtime_id or "")
        runtime_name = _facade.runtime_label(runtime_id)
        provider = str(_facade._delegated_session_value(session, "target_provider", "") or "")
        model = str(_facade._delegated_session_value(session, "target_model", "") or "")
        events_path = str(_facade._delegated_session_value(session, "events_path", "") or "").strip()
        if events_path and events_path not in sources:
            sources.append(events_path)

        for event_index, row in enumerate(_facade._delegated_runtime_event_rows(session, limit=event_limit)):
            kind = str(row.get("kind") or row.get("event") or "runtime.event").strip()
            kind_normalized = kind.lower()
            message = str(row.get("message") or row.get("detail") or "").strip()
            metadata = _facade._runtime_event_metadata(row)
            source_kind = str(metadata.get("sourceKind") or metadata.get("source_kind") or "").strip().lower()
            is_transcript_event = (
                kind_normalized in _facade.DELEGATED_TRANSCRIPT_RUNTIME_KINDS
                or kind_normalized.endswith(".output")
                or source_kind == "real-runtime-output"
            )
            if not is_transcript_event or _facade._low_signal_delegated_runtime_event(kind_normalized, message):
                continue
            message_key = _facade.hashlib.sha1(
                f"{runtime_id}:{session_id}:{kind_normalized}:{message[:500]}".encode("utf-8", errors="ignore")
            ).hexdigest()
            if message_key in seen_messages:
                continue
            seen_messages.add(message_key)

            detail = _facade._runtime_transcript_detail(row)
            runtime_output = (
                _facade.is_process_runtime_kind(kind_normalized)
                or _facade._runtime_transcript_has_concrete_output(row, detail)
                or source_kind == "real-runtime-output"
            )
            if runtime_output and "runtime output:" not in detail.lower():
                detail = f"Runtime output:\n{message}"
            elif not detail:
                detail = message
            created_at = str(
                row.get("created_at")
                or row.get("timestamp")
                or _facade._delegated_session_value(session, "updated_at", "")
                or ""
            )
            event_id = str(row.get("event_id") or row.get("id") or f"event_{event_index}")
            is_dialogue = kind_normalized in _facade.MODEL_RUNTIME_KINDS or source_kind == "real-runtime-output"
            label = (
                f"{runtime_name} reply"
                if is_dialogue
                else f"{runtime_name} runtime output"
                if runtime_output
                else f"{runtime_name} live event"
            )
            turn_receipt = {
                "schema": "fluxio.agent_dialogue_runtime_provenance.v1",
                "sourceKind": source_kind or kind_normalized,
                "captureMode": "delegated-runtime-event-log",
                "captureLabel": "live delegated runtime event",
                "sessionId": session_id,
                "sourcePath": events_path,
                "externalRuntimeSessionId": str(
                    metadata.get("externalRuntimeSessionId")
                    or metadata.get("external_runtime_session_id")
                    or metadata.get("sessionId")
                    or metadata.get("session_id")
                    or ""
                ),
            }
            messages.append(
                {
                    "id": f"delegated-runtime-event:{session_id}:{event_id}",
                    "sessionId": session_id,
                    "kind": kind,
                    "label": label,
                    "title": message[:320],
                    "detail": detail[:4800],
                    "technicalDetail": _facade.json.dumps(
                        {
                            "eventId": event_id,
                            "eventsPath": events_path,
                            "kind": kind,
                            "status": row.get("status", ""),
                            "provider": provider,
                            "model": model,
                            "metadata": metadata,
                        },
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )[:3000],
                    "createdAt": created_at,
                    "role": "assistant" if is_dialogue else "runtime",
                    "runtimeId": runtime_id,
                    "tone": "bad" if any(token in kind_normalized for token in ("fail", "error", "block")) else "neutral",
                    "runtimeOutput": runtime_output,
                    "traceOnly": False,
                    "messageKind": "dialogue" if is_dialogue else "activity",
                    "conversationTurn": is_dialogue,
                    "source": "backend-runtime-reply" if is_dialogue else "delegated-runtime-event",
                    "turnReceipt": turn_receipt,
                }
            )
    return messages[-limit:], session_ids, sources


@_mission_local_checked('dialogue')
def mission_runtime_dialogue_turns(mission: Mission, *, root: Path | None=None, limit: int=6) -> list[dict]:
    """Extract real assistant dialogue turns from delegated runtime output.

    Only emits text an executor actually produced: meaningful lane events and
    the recorded runtime_output proof. No synthetic or fallback content.
    """
    _facade = _control_room_facade()
    turns: list[dict] = []
    seen: set[str] = set()

    def add(text: object, *, created_at: str, session_id: str, runtime_id: str='', provider: str='', model: str='', source_kind: str='', capture_mode: str='', source_path: str='', report_path: str='', external_runtime_session_id: str='') -> None:
        body = str(text or '').strip()
        if len(body) < 40:
            return
        key = _facade.hashlib.sha1(body[:400].encode('utf-8')).hexdigest()
        if key in seen:
            return
        seen.add(key)
        turns.append({'text': body, 'createdAt': created_at, 'sessionId': session_id, 'runtimeId': runtime_id, 'provider': provider, 'model': model, 'sourceKind': source_kind, 'captureMode': capture_mode, 'sourcePath': source_path, 'reportPath': report_path, 'externalRuntimeSessionId': external_runtime_session_id})
    for session in list(mission.delegated_runtime_sessions or []):
        status = str(getattr(session, 'status', '') or '').lower()
        if status not in {'completed', 'running'}:
            continue
        provider = str(getattr(session, 'target_provider', '') or '')
        model = str(getattr(session, 'target_model', '') or '')
        session_id = str(getattr(session, 'delegated_id', '') or '')
        runtime_id = str(getattr(session, 'runtime_id', '') or mission.runtime_id or '')
        events = _facade._delegated_runtime_event_rows(session, limit=max(limit * 6, 30))
        for event in reversed(events):
            text = str(event.get('message') or event.get('detail') or '').strip()
            kind = str(event.get('kind') or '').lower()
            metadata = _facade._runtime_event_metadata(event)
            source_kind = str(metadata.get('sourceKind') or metadata.get('source_kind') or '').lower()
            source_path = str(metadata.get('sourcePath') or metadata.get('source_path') or metadata.get('recoveredFrom') or '')
            capture_mode = str(metadata.get('captureMode') or metadata.get('capture_mode') or '').lower()
            if not capture_mode and source_path:
                capture_mode = 'recovered-persisted-session'
            if not capture_mode and source_kind == 'real-runtime-output':
                capture_mode = 'fresh-runtime-command'
            real_output_kind = kind in _facade.DELEGATED_TRANSCRIPT_RUNTIME_KINDS or kind.endswith('.output') or source_kind == 'real-runtime-output'
            if len(text) >= 80 and real_output_kind:
                add(text, created_at=str(event.get('timestamp') or event.get('created_at') or getattr(session, 'updated_at', '')), session_id=session_id, runtime_id=runtime_id, provider=provider, model=model, source_kind=source_kind or kind, capture_mode=capture_mode or 'runtime-session-event', source_path=source_path, report_path=str(metadata.get('reportPath') or metadata.get('report_path') or ''), external_runtime_session_id=str(metadata.get('externalRuntimeSessionId') or metadata.get('external_runtime_session_id') or metadata.get('sessionId') or metadata.get('session_id') or ''))
                break
    for candidate in _facade._mission_artifact_root_candidates(mission, root=root):
        output_path = candidate / '.agent_control' / 'mission_artifacts' / str(mission.mission_id) / 'proof' / 'runtime_output.txt'
        if output_path.is_file():
            add(_facade._read_gate_text(output_path, max_chars=1600), created_at=str(mission.updated_at or ''), session_id='runtime_output_proof', runtime_id=mission.runtime_id, source_kind='mission-runtime-output-file', capture_mode='mission-runtime-output-file', source_path=str(output_path))
            break
    return turns[-limit:]


@_control_checked('preview')
def mission_artifact_manifest_preview_url(mission: Mission, *, root: Path | None=None) -> str:
    """Return the served preview URL for the mission's own artifact output.

    Reads .agent_control/mission_artifacts/<mission_id>/artifact_manifest.json
    (falling back to a bare index.html) so a mission's finished artifact binds
    into the Agent preview window without waiting for Builder live-review
    evidence.
    """
    _facade = _control_room_facade()
    for candidate in _facade._mission_artifact_root_candidates(mission, root=root):
        artifact_dir = candidate / '.agent_control' / 'mission_artifacts' / str(mission.mission_id)
        manifest_path = artifact_dir / 'artifact_manifest.json'
        if manifest_path.is_file():
            manifest = _facade._read_gate_json(manifest_path)
            preview_url = str(manifest.get('previewUrl') or '').strip()
            if preview_url:
                return preview_url
            entrypoint = str(manifest.get('entrypoint') or '').strip()
            if entrypoint:
                return f"/api/artifact?path={_facade.quote(entrypoint, safe='')}"
        index_path = artifact_dir / 'index.html'
        if index_path.is_file():
            return f"/api/artifact?path={_facade.quote(str(index_path), safe='')}"
    return ''


def _mission_manifest_folder_evidence_items(
    mission: Mission,
    *,
    root: Path | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    _facade = _control_room_facade()
    artifact_items: list[dict[str, str]] = []
    runtime_items: list[dict[str, str]] = []

    def add_artifact(source: str, value: object) -> None:
        text = _facade._gate_text(value)
        if text:
            artifact_items.append({"source": source, "detail": text[:240]})

    def add_runtime(source: str, value: object) -> None:
        text = _facade._gate_text(value)
        if _facade._gate_has_meaningful_text(text):
            runtime_items.append({"source": source, "detail": text[:240]})

    def add_manifest_paths(source: str, value: object) -> None:
        if isinstance(value, dict):
            for field in (
                "servedUrl",
                "previewUrl",
                "artifactPath",
                "path",
                "localPath",
                "manifestPath",
            ):
                if value.get(field):
                    add_artifact(source, value.get(field))
            for field in ("summary", "description", "runtimeOutput", "runtimeOutputBody"):
                add_runtime(source, value.get(field))
            for nested_field in ("artifact", "proof", "metadata"):
                nested = value.get(nested_field)
                if isinstance(nested, dict):
                    add_manifest_paths(f"{source}.{nested_field}", nested)
            for list_field in ("artifacts", "files", "outputs", "items"):
                nested_list = value.get(list_field)
                if isinstance(nested_list, list):
                    for index, nested in enumerate(nested_list[:12]):
                        add_manifest_paths(f"{source}.{list_field}.{index}", nested)
            return
        if isinstance(value, str):
            add_artifact(source, value)

    for candidate in _facade._mission_artifact_root_candidates(mission, root=root):
        artifact_dir = (
            candidate
            / ".agent_control"
            / "mission_artifacts"
            / str(mission.mission_id)
        )
        if not artifact_dir.exists() or not artifact_dir.is_dir():
            continue

        manifest_path = artifact_dir / "artifact_manifest.json"
        proof_digest_path = artifact_dir / "proof" / "proof_digest.json"
        runtime_output_path = artifact_dir / "proof" / "runtime_output.txt"
        index_path = artifact_dir / "index.html"

        add_artifact("mission_artifact_folder", str(artifact_dir))
        if manifest_path.exists():
            add_artifact("mission_artifact_manifest", str(manifest_path))
            add_manifest_paths("mission_artifact_manifest", _facade._read_gate_json(manifest_path))
        if proof_digest_path.exists():
            add_artifact("mission_proof_digest", str(proof_digest_path))
            proof_digest = _facade._read_gate_json(proof_digest_path)
            add_manifest_paths("mission_proof_digest", proof_digest)
            for field in ("summary", "runtimeOutputBody", "operatorValue", "verificationSummary"):
                add_runtime("mission_proof_digest", proof_digest.get(field))
        if runtime_output_path.exists():
            add_artifact("mission_runtime_output_file", str(runtime_output_path))
            add_runtime("mission_runtime_output_file", _facade._read_gate_text(runtime_output_path))
        if index_path.exists():
            add_artifact("mission_artifact_index", str(index_path))

    deduped_artifacts: list[dict[str, str]] = []
    deduped_runtime: list[dict[str, str]] = []
    seen_artifacts: set[tuple[str, str]] = set()
    seen_runtime: set[tuple[str, str]] = set()
    for item in artifact_items:
        key = (item["source"], item["detail"])
        if key in seen_artifacts:
            continue
        seen_artifacts.add(key)
        deduped_artifacts.append(item)
    for item in runtime_items:
        key = (item["source"], item["detail"])
        if key in seen_runtime:
            continue
        seen_runtime.add(key)
        deduped_runtime.append(item)
    return deduped_artifacts, deduped_runtime


def _runtime_transcript_output_evidence_items(
    *,
    runtime_transcript: dict | None = None,
    agent_messages: list[dict] | None = None,
    mission_events: list[dict] | None = None,
) -> list[dict[str, str]]:
    _facade = _control_room_facade()
    items: list[dict[str, str]] = []

    def runtime_output_text(row: dict, *, default_source: str) -> tuple[str, str]:
        source = str(row.get("label") or default_source or "runtime_transcript")
        detail = _facade._gate_text(row.get("detail") or row.get("message") or "")
        title = _facade._gate_text(row.get("title") or "")
        if bool(row.get("runtimeOutput")):
            return source, detail or title
        match = _facade.re.search(
            r"runtime output:\s*(.+?)(?:\s+[·]\s+(?:action|target|command|gate|result|error):|\s*$)",
            detail,
            flags=_facade.re.IGNORECASE,
        )
        if match:
            return source, match.group(1)
        return source, ""

    for row in (
        runtime_transcript.get("messages", [])
        if isinstance(runtime_transcript, dict) and isinstance(runtime_transcript.get("messages"), list)
        else []
    ):
        if not isinstance(row, dict):
            continue
        source, text = runtime_output_text(row, default_source="runtime_transcript.messages")
        if _facade._gate_has_meaningful_text(text):
            items.append({"source": source, "detail": _facade._gate_text(text)[:240]})

    for row in list(agent_messages or []):
        if not isinstance(row, dict):
            continue
        source, text = runtime_output_text(row, default_source="agent_messages")
        if _facade._gate_has_meaningful_text(text):
            items.append({"source": source, "detail": _facade._gate_text(text)[:240]})

    for event in list(mission_events or []):
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "").strip()
        event_data = event.get("data") if isinstance(event.get("data"), dict) else {}
        has_runtime_output_pointer = bool(event_data.get("runtimeOutput"))
        if kind == "proof.artifact.updated" or has_runtime_output_pointer or _facade.is_process_runtime_kind(kind):
            text = event.get("message") or event_data.get("summary") or event_data.get("runtimeOutput")
            if _facade._gate_has_meaningful_text(text):
                items.append({"source": kind or "mission_event", "detail": _facade._gate_text(text)[:240]})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item["source"], item["detail"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _mission_runtime_output_evidence_items(
    mission: Mission,
    *,
    runtime_transcript: dict | None = None,
    agent_messages: list[dict] | None = None,
    mission_events: list[dict] | None = None,
) -> list[dict[str, str]]:
    _facade = _control_room_facade()
    items: list[dict[str, str]] = []

    def add(source: str, value: object) -> None:
        text = _facade._gate_text(value)
        if _facade._gate_has_meaningful_text(text):
            items.append({"source": source, "detail": text[:240]})

    state_code_execution = (
        mission.state.code_execution if isinstance(mission.state.code_execution, dict) else {}
    )
    for source, value in (
        ("code_execution.last_result", getattr(mission.code_execution, "last_result", "")),
        ("state.code_execution.last_result", state_code_execution.get("last_result", "")),
    ):
        add(source, value)
    for session in list(mission.delegated_runtime_sessions or []):
        session_runtime = str(getattr(session, "runtime_id", "") or mission.runtime_id)
        session_id = str(getattr(session, "delegated_id", "") or session_runtime)
        for event in list(getattr(session, "latest_events", []) or []):
            if not isinstance(event, dict) or not _facade.is_process_runtime_kind(event.get("kind")):
                continue
            add(
                f"delegated_runtime.{session_runtime}.{session_id}",
                event.get("message") or event.get("detail") or event.get("trace"),
            )
    for action in list(mission.action_history or [])[-12:]:
        action_row = _facade._gate_mapping(action)
        result = _facade._gate_mapping(
            action_row.get("result") if isinstance(action_row, dict) else getattr(action, "result", {})
        )
        add("action_history.result", result.get("result_summary") or result.get("stdout"))
    items.extend(
        _facade._runtime_transcript_output_evidence_items(
            runtime_transcript=runtime_transcript,
            agent_messages=agent_messages,
            mission_events=mission_events,
        )
    )
    return items


@_mission_local_checked('gate')
def mission_hard_artifact_gate(mission: Mission, *, root: Path | None=None, runtime_transcript: dict | None=None, agent_messages: list[dict] | None=None, mission_events: list[dict] | None=None) -> dict[str, object]:
    _facade = _control_room_facade()
    artifact_items = _facade._mission_artifact_evidence_items(mission, runtime_transcript=runtime_transcript, agent_messages=agent_messages, mission_events=mission_events)
    manifest_artifacts, manifest_runtime = _facade._mission_manifest_folder_evidence_items(mission, root=root)
    artifact_items.extend(manifest_artifacts)
    runtime_items = _facade._mission_runtime_output_evidence_items(mission, runtime_transcript=runtime_transcript, agent_messages=agent_messages, mission_events=mission_events)
    runtime_items.extend(manifest_runtime)
    passed = bool(artifact_items and runtime_items)
    return {'schema': 'fluxio.mission.hard_artifact_gate.v1', 'checkId': _facade.HARD_ARTIFACT_GATE_CHECK_ID, 'required': _facade._mission_requires_hard_artifact_gate(mission), 'passed': passed, 'status': 'passed' if passed else 'missing_required_output', 'requiredEvidence': ['concrete runtime-output body', 'served artifact, artifact path, or preview URL'], 'runtimeOutputCount': len(runtime_items), 'artifactCount': len(artifact_items), 'runtimeOutputEvidence': runtime_items[:5], 'artifactEvidence': artifact_items[:5], 'failure': '' if passed else _facade.HARD_ARTIFACT_GATE_FAILURE, 'nextAction': 'Review the runtime output and served artifact.' if passed else 'Resume the mission with a hard artifact gate until both runtime output and artifact evidence are present.'}


def _mission_requires_hard_artifact_gate(mission: Mission) -> bool:
    _facade = _control_room_facade()
    if (
        _facade.HARD_ARTIFACT_GATE_CHECK_ID in mission.state.verification_failures
        or _facade.HARD_ARTIFACT_GATE_FAILURE in mission.state.verification_failures
        or _facade.HARD_ARTIFACT_GATE_FAILURE in mission.proof.failed_checks
        or mission.state.stop_reason == "artifact_gate_failed"
    ):
        return True
    verification_policy = getattr(mission, "verification_policy", None)
    verification_commands = (
        getattr(verification_policy, "commands", [])
        if verification_policy is not None
        else []
    )
    text = " ".join(
        str(item or "")
        for item in [
            mission.title,
            mission.objective,
            *list(mission.success_checks or []),
            *list(verification_commands or []),
        ]
    ).lower()
    explicit_markers = (
        "hard artifact gate",
        "mission_artifacts",
        "previewable",
        "served artifact",
        "artifact path",
        "runtime-output",
        "runtime output",
    )
    if any(marker in text for marker in explicit_markers):
        return True
    build_markers = ("build", "prototype", "report", "dashboard", "workbench", "preview", "artifact")
    return any(marker in text for marker in build_markers)


def _apply_hard_artifact_gate_if_completed(mission: Mission) -> dict[str, object]:
    _facade = _control_room_facade()
    gate = _facade.mission_hard_artifact_gate(mission)
    if (
        mission.state.status != "completed"
        or bool(gate.get("passed"))
        or not bool(gate.get("required", True))
    ):
        return gate
    mission.state.status = "verification_failed"
    mission.state.last_runtime_event = "artifact_gate_failed"
    mission.state.last_error = _facade.HARD_ARTIFACT_GATE_FAILURE
    mission.state.stop_reason = "artifact_gate_failed"
    mission.state.planner_loop_status = "paused"
    mission.state.last_verification_result = "failed"
    mission.state.last_verification_summary = _facade.HARD_ARTIFACT_GATE_FAILURE
    mission.state.last_replan_reason = "missing_artifact_or_runtime_output"
    mission.state.last_replan_trigger = _facade.HARD_ARTIFACT_GATE_CHECK_ID
    if _facade.HARD_ARTIFACT_GATE_CHECK_ID not in mission.state.verification_failures:
        mission.state.verification_failures.append(_facade.HARD_ARTIFACT_GATE_CHECK_ID)
    if _facade.HARD_ARTIFACT_GATE_FAILURE not in mission.proof.failed_checks:
        mission.proof.failed_checks.append(_facade.HARD_ARTIFACT_GATE_FAILURE)
    if _facade.HARD_ARTIFACT_GATE_FAILURE not in mission.proof.blocked_by:
        mission.proof.blocked_by.append(_facade.HARD_ARTIFACT_GATE_FAILURE)
    mission.proof.summary = (
        "Mission needs artifact repair before it can be counted as completed."
    )
    mission.proof.pending_approvals = []
    return gate


def _planned_scope_artifacts_blocking(planned_scope_artifacts: dict | None) -> bool:
    status = str((planned_scope_artifacts or {}).get("status") or "").strip().lower()
    return status in {"missing", "partial"}


def _apply_planned_scope_artifact_gate_if_completed(
    mission: Mission,
    planned_scope_artifacts: dict | None,
) -> bool:
    _facade = _control_room_facade()
    if mission.state.status != "completed" or not _facade._planned_scope_artifacts_blocking(
        planned_scope_artifacts
    ):
        return False
    next_action = str((planned_scope_artifacts or {}).get("nextAction") or "").strip()
    mission.state.status = "verification_failed"
    mission.state.last_runtime_event = "planned_scope_artifacts_failed"
    mission.state.last_error = _facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE
    mission.state.stop_reason = "planned_scope_artifacts_failed"
    mission.state.planner_loop_status = "paused"
    mission.planner_loop_status = mission.state.planner_loop_status
    mission.state.last_verification_result = "failed"
    mission.state.last_verification_summary = _facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE
    mission.state.last_replan_reason = "missing_planned_scope_artifacts"
    mission.state.last_replan_trigger = _facade.PLANNED_SCOPE_ARTIFACT_GATE_CHECK_ID
    if _facade.PLANNED_SCOPE_ARTIFACT_GATE_CHECK_ID not in mission.state.verification_failures:
        mission.state.verification_failures.append(_facade.PLANNED_SCOPE_ARTIFACT_GATE_CHECK_ID)
    if _facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE not in mission.proof.failed_checks:
        mission.proof.failed_checks.append(_facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE)
    if _facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE not in mission.proof.blocked_by:
        mission.proof.blocked_by.append(_facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE)
    mission.proof.summary = (
        "Mission needs planned artifact repair before it can be counted as completed."
    )
    if next_action and next_action not in mission.proof.blocked_by:
        mission.proof.blocked_by.append(next_action)
    mission.proof.pending_approvals = []
    return True


def _clear_repaired_planned_scope_artifact_gate_failure(mission: Mission) -> None:
    _facade = _control_room_facade()
    repaired_markers = {
        _facade.PLANNED_SCOPE_ARTIFACT_GATE_CHECK_ID,
        _facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE,
    }
    mission.state.verification_failures = [
        item for item in mission.state.verification_failures if item not in repaired_markers
    ]
    mission.proof.failed_checks = [
        item for item in mission.proof.failed_checks if item not in repaired_markers
    ]
    mission.proof.blocked_by = [
        item for item in mission.proof.blocked_by if item not in repaired_markers
    ]
    if mission.state.last_error == _facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE:
        mission.state.last_error = None
    if mission.state.stop_reason == "planned_scope_artifacts_failed":
        mission.state.stop_reason = None
    if mission.state.last_runtime_event == "planned_scope_artifacts_failed":
        mission.state.last_runtime_event = "completed"
    if mission.state.last_replan_trigger == _facade.PLANNED_SCOPE_ARTIFACT_GATE_CHECK_ID:
        mission.state.last_replan_trigger = ""
    if mission.state.last_replan_reason == "missing_planned_scope_artifacts":
        mission.state.last_replan_reason = ""
    if mission.state.last_verification_summary == _facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE:
        mission.state.last_verification_summary = "Planned scope artifacts repaired."


def _mission_has_planned_scope_artifact_gate_failure(mission: Mission) -> bool:
    _facade = _control_room_facade()
    return mission.state.status == "verification_failed" and (
        _facade.PLANNED_SCOPE_ARTIFACT_GATE_CHECK_ID in mission.state.verification_failures
        or _facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE in mission.state.verification_failures
        or _facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE in mission.proof.failed_checks
        or mission.state.stop_reason == "planned_scope_artifacts_failed"
        or mission.state.last_runtime_event == "planned_scope_artifacts_failed"
    )


@_mission_local_checked('repair')
def _complete_repaired_planned_scope_artifact_gate_from_detail(mission: Mission, artifact_gate: dict[str, object], planned_scope_artifacts: dict | None) -> bool:
    _facade = _control_room_facade()
    if _facade._planned_scope_artifacts_blocking(planned_scope_artifacts) or not _facade._mission_has_planned_scope_artifact_gate_failure(mission):
        return False
    if bool(artifact_gate.get('required', True)) and (not bool(artifact_gate.get('passed'))):
        return False
    repaired_markers = {_facade.PLANNED_SCOPE_ARTIFACT_GATE_CHECK_ID, _facade.PLANNED_SCOPE_ARTIFACT_GATE_FAILURE}
    remaining_state_failures = [item for item in mission.state.verification_failures if item not in repaired_markers]
    remaining_proof_failures = [item for item in mission.proof.failed_checks if item not in repaired_markers]
    if remaining_state_failures or remaining_proof_failures:
        return False
    _facade._clear_repaired_planned_scope_artifact_gate_failure(mission)
    mission.state.status = 'completed'
    mission.state.last_runtime_event = 'completed'
    mission.state.last_verification_result = 'passed'
    mission.state.last_verification_summary = 'Planned scope artifacts repaired.'
    mission.state.planner_loop_status = 'completed'
    mission.planner_loop_status = mission.state.planner_loop_status
    mission.state.current_cycle_phase = 'complete'
    mission.state.continuity_state = 'complete'
    mission.state.continuity_detail = 'Planned scope artifacts passed from mission detail evidence.'
    mission.proof.summary = 'Mission completed with planned proof artifacts.'
    return True


def _clear_repaired_hard_artifact_gate_failure(mission: Mission) -> None:
    _facade = _control_room_facade()
    repaired_markers = {_facade.HARD_ARTIFACT_GATE_CHECK_ID, _facade.HARD_ARTIFACT_GATE_FAILURE}
    mission.state.verification_failures = [
        item for item in mission.state.verification_failures if item not in repaired_markers
    ]
    mission.proof.failed_checks = [
        item for item in mission.proof.failed_checks if item not in repaired_markers
    ]
    mission.proof.blocked_by = [
        item for item in mission.proof.blocked_by if item not in repaired_markers
    ]
    if mission.state.last_error == _facade.HARD_ARTIFACT_GATE_FAILURE:
        mission.state.last_error = None
    if mission.state.stop_reason == "artifact_gate_failed":
        mission.state.stop_reason = None
    if mission.state.last_runtime_event == "artifact_gate_failed":
        mission.state.last_runtime_event = "completed"
    if mission.state.last_replan_trigger == _facade.HARD_ARTIFACT_GATE_CHECK_ID:
        mission.state.last_replan_trigger = ""
    if mission.state.last_replan_reason == "missing_artifact_or_runtime_output":
        mission.state.last_replan_reason = ""
    if mission.state.last_verification_summary == _facade.HARD_ARTIFACT_GATE_FAILURE:
        mission.state.last_verification_summary = "Hard artifact gate repaired with runtime output."


@_mission_local_checked('repair')
def _complete_repaired_hard_artifact_gate_from_detail(mission: Mission, artifact_gate: dict[str, object], planned_scope_artifacts: dict | None=None) -> bool:
    """Complete a hard-gate failed mission once detail evidence proves the repair."""
    _facade = _control_room_facade()
    if not bool(artifact_gate.get('passed')) or not _facade._mission_has_hard_artifact_gate_failure(mission):
        return False
    if _facade._planned_scope_artifacts_blocking(planned_scope_artifacts):
        return False
    repaired_markers = {_facade.HARD_ARTIFACT_GATE_CHECK_ID, _facade.HARD_ARTIFACT_GATE_FAILURE}
    remaining_state_failures = [item for item in mission.state.verification_failures if item not in repaired_markers]
    remaining_proof_failures = [item for item in mission.proof.failed_checks if item not in repaired_markers]
    if remaining_state_failures or remaining_proof_failures:
        return False
    _facade._clear_repaired_hard_artifact_gate_failure(mission)
    _facade._clear_repaired_planned_scope_artifact_gate_failure(mission)
    mission.state.status = 'completed'
    mission.state.last_runtime_event = 'completed'
    mission.state.last_verification_result = 'passed'
    mission.state.last_verification_summary = 'Hard artifact gate repaired with runtime output.'
    mission.state.planner_loop_status = 'completed'
    mission.state.current_cycle_phase = 'complete'
    mission.state.continuity_state = 'complete'
    mission.state.continuity_detail = 'Hard artifact gate passed from mission detail evidence.'
    mission.proof.summary = 'Mission completed with proof artifacts.'
    return True
