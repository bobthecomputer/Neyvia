"""Durable operator questions for agent runs."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .harness_jobs import _exclusive_job_lock

_RELATIVE_PATH = ".agent_control/agent_questions.json"
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(path: Path) -> threading.RLock:
    # The cross-process guard lives next to the store, including on the first
    # read in a fresh workspace where no question has ever been written.
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, label: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        if required or value is not None:
            raise ValueError(f"{label} must be text")
        return ""
    value = value.strip()
    if required and not value:
        raise ValueError(f"{label} is required")
    if len(value) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    return value


def _read(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid question store: {exc}") from exc
    if not isinstance(value, list):
        raise ValueError("invalid question store: expected an array")
    return [item for item in value if isinstance(item, dict)]


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="agent-questions-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def request_question(
    root: Path,
    session_id: str,
    question: str,
    options: list[str] | None = None,
    context: str = "",
    *, conversation_id: str = "",
) -> dict[str, Any]:
    session = _text(session_id, "session_id", 200)
    prompt = _text(question, "question", 1000)
    detail = _text(context, "context", 2000, required=False)
    conversation = _text(conversation_id, "conversation_id", 200, required=False)
    normalized_options: list[str] = []
    if options is not None:
        if not isinstance(options, list) or len(options) > 3:
            raise ValueError("options must contain at most 3 items")
        for option in options:
            item = _text(option, "option", 200)
            if item in normalized_options:
                raise ValueError("options must be unique")
            normalized_options.append(item)
    path = Path(root) / _RELATIVE_PATH
    with _lock(path), _exclusive_job_lock(path):
        rows = _read(path)
        pending = next((row for row in rows if row.get("sessionId") == session and row.get("status") == "pending"), None)
        if pending:
            if pending.get("question") == prompt and pending.get("options", []) == normalized_options and pending.get("context", "") == detail and pending.get("conversationId", "") == conversation:
                return dict(pending)
            raise ValueError("session already has a pending question")
        row = {
            "questionId": f"q-{uuid.uuid4().hex}",
            "sessionId": session,
            "conversationId": conversation,
            "question": prompt,
            "options": normalized_options,
            "context": detail,
            "status": "pending",
            "createdAt": _now(),
        }
        before = [dict(item) for item in rows]
        rows.append(row)
        _write(path, rows)
        from .proofs_a_control import check_questions
        check_questions(path, before, rows, row, "request")
        return dict(row)


def list_questions(root: Path, session_id: str | None = None, pending_only: bool = True) -> list[dict[str, Any]]:
    path = Path(root) / _RELATIVE_PATH
    session = _text(session_id, "session_id", 200, required=False) if session_id is not None else None
    with _lock(path), _exclusive_job_lock(path):
        rows = _read(path)
        result = [dict(row) for row in rows if (session is None or row.get("sessionId") == session) and (not pending_only or row.get("status") == "pending")]
        from .proofs_a_control import check_question_list
        check_question_list(rows, session, pending_only, result)
        return result


def answer_question(root: Path, question_id: str, answer: str, *, conversation_id=None, allowed_sessions=None) -> dict[str, Any]:
    identifier = _text(question_id, "question_id", 200)
    response = _text(answer, "answer", 12000)
    path = Path(root) / _RELATIVE_PATH
    with _lock(path), _exclusive_job_lock(path):
        rows = _read(path)
        for row in rows:
            if row.get("questionId") != identifier:
                continue
            if conversation_id is not None and not (row.get("conversationId") == conversation_id or (not row.get("conversationId") and row.get("sessionId") in (allowed_sessions or []))):
                raise ValueError("Question does not belong to this conversation")
            if row.get("status") == "answered":
                if row.get("answer") == response:
                    return dict(row)
                raise ValueError("question is already answered")
            before = [dict(item) for item in rows]
            row["status"] = "answered"
            row["answer"] = response
            row["answeredAt"] = _now()
            _write(path, rows)
            from .proofs_a_control import check_questions
            check_questions(path, before, rows, row, "answer")
            return dict(row)
    raise ValueError("question not found")


def answer_pending_question(root: Path, session_id: str, answer: str) -> dict[str, Any] | None:
    session = _text(session_id, "session_id", 200)
    pending = list_questions(root, session, pending_only=True)
    if not pending:
        return None
    latest = pending[-1]
    return answer_question(root, latest["questionId"], answer)


def question_context(root, session_id, *, conversation_id="", max_characters=4000):
    """Keep exact scoped answers or an explicit retrieval requirement; never summarize consent."""
    if type(max_characters) is not int or not 600 <= max_characters <= 16000:
        raise ValueError("Question context budget must be between 600 and 16000 characters")
    rows = [row for row in list_questions(root, pending_only=False)
            if (conversation_id and row.get("conversationId") == conversation_id)
            or (row.get("sessionId") == session_id and not row.get("conversationId"))]
    result = {"scope": conversation_id or session_id, "entries": [], "omittedCount": 0,
              "requiresRetrieval": False, "authorityGranted": False,
              "retrievalPath": str(Path(root) / _RELATIVE_PATH)}
    for row in reversed(rows):
        result["entries"].append(row)
        if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > max_characters - 80:
            result["entries"].pop()
    result["entries"].reverse()
    result["omittedCount"] = len(rows)-len(result["entries"])
    result["requiresRetrieval"] = result["omittedCount"] > 0
    return result
