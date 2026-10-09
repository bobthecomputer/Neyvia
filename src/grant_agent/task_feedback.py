"""Terminal task feedback, shared by connected UI and workspace tools.

Rows and retry identities commit together. The host root scopes the database;
HTTP admission additionally restricts this private task evidence to the PC owner.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from .connected_sessions.registry import ConnectedError
from .connected_sessions.runs import TERMINAL_STATES
from .ui_command_bus import now

COMMANDS = frozenset({"task_feedback_submit_command", "task_feedback_get_command",
                      "lesson_list_command", "lesson_revert_command"})
TOOLS = {"feedback.submit": "task_feedback_submit_command", "feedback.get": "task_feedback_get_command",
         "lessons.list": "lesson_list_command", "lessons.revert": "lesson_revert_command"}
TEXT = {"type": "string", "minLength": 1}
DEFINITIONS = [
    ("feedback.submit", "Save the owner's feedback on a finished run; retry with the same requestId.",
     {"runId": TEXT, "sessionId": TEXT, "verdict": {"type": "string", "enum": ["good", "not_quite", "wrong"]},
      "reason": {"type": "string", "maxLength": 4000}, "reasonSource": {"type": "string", "enum": ["typed", "dictated"]},
      "requestId": TEXT}, ["runId", "sessionId", "verdict", "requestId"]),
    ("feedback.get", "Read saved feedback for a run on this host.", {"runId": TEXT}, ["runId"]),
    ("lessons.list", "List durable feedback lessons and their evidence.",
     {"state": {"type": "string", "enum": ["quarantined", "testing", "promoted", "rejected", "reverted", "decayed"]},
      "manual": TEXT, "runId": TEXT, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, []),
    ("lessons.revert", "Revert a promoted lesson and restore its parent manual version.",
     {"lessonId": TEXT, "requestId": TEXT}, ["lessonId", "requestId"]),
]


def _text(body, key, limit=500, required=True):
    value = body.get(key, "")
    if not isinstance(value, str) or len(value) > limit or required and not value.strip():
        raise ConnectedError("invalid_request", f"{key} must be text of at most {limit} characters.")
    return value


def capture_outputs(workspace, paths):
    """Freeze text evidence from known task edits; never scan a user's tree."""
    outputs, snapshots, warnings = [], {}, []
    if not workspace:
        return outputs, snapshots, warnings
    root = Path(workspace).resolve()
    protected = [Path(r"C:\Users\user\Projects\Neyvia").resolve(),
                 Path(r"C:\Users\user\Projects\Neyvia-next").resolve()]
    budget = 100_000
    for value in sorted(set(paths))[:200]:
        try:
            path = Path(value)
            path = (root / path).resolve() if not path.is_absolute() else path.resolve()
            relative = path.relative_to(root)
            if any(path == p or p in path.parents for p in protected) or any(
                    part.casefold() in {".agent_control", ".neyvia", ".git", "node_modules", ".ssh", ".codex", ".claude"}
                    or part.casefold().startswith(".env")
                    or "credential" in part.casefold() or "nas_access_runbook" in part.casefold()
                    for part in relative.parts):
                warnings.append({"path": str(relative), "reason": "protected"})
                continue
            if path.suffix.casefold() in {".pem", ".key", ".pfx", ".p12"}:
                warnings.append({"path": str(relative), "reason": "protected"})
                continue
            if not path.is_file() or path.stat().st_size > 1024 * 1024:
                warnings.append({"path": str(relative), "reason": "missing_or_over_1mb"})
                continue
            before = path.stat()
            data = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                warnings.append({"path": str(relative), "reason": "changed_during_read"})
                continue
            name = relative.as_posix()
            outputs.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
            try:
                text = data.decode("utf-8")
            except UnicodeError:
                continue
            if "\x00" not in text and len(text) <= budget:
                snapshots[name] = text
                budget -= len(text)
        except (OSError, ValueError):
            warnings.append({"path": str(value)[:300], "reason": "unavailable_or_outside_workspace"})
    return outputs, snapshots, warnings


class FeedbackStore:
    def __init__(self, root):
        self.path = Path(root).resolve() / ".neyvia" / "task-feedback.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS feedback (run_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, intent TEXT NOT NULL, data TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT data FROM feedback WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, body, run):
        run_id, session_id = _text(body, "runId"), _text(body, "sessionId")
        request_id, verdict = _text(body, "requestId", 200), body.get("verdict")
        reason = _text(body, "reason", 4000, False)
        source = body.get("reasonSource", "typed")
        if not isinstance(verdict, str) or verdict not in {"good", "not_quite", "wrong"} or not isinstance(source, str) or source not in {"typed", "dictated"}:
            raise ConnectedError("invalid_request", "Choose a feedback verdict and typed or dictated reason source.")
        if run.get("sessionId") != session_id or run.get("runId") != run_id:
            raise ConnectedError("session_mismatch", "That run belongs to a different session.", 403)
        if run.get("state") not in TERMINAL_STATES:
            raise ConnectedError("run_active", "Wait until the run finishes before giving feedback.", 409)
        intent = json.dumps([run_id, session_id, verdict, reason, source], ensure_ascii=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            retry = db.execute("SELECT intent,data FROM requests WHERE request_id=?", (request_id,)).fetchone()
            if retry:
                if retry[0] != intent:
                    raise ConnectedError("request_id_conflict", "This feedback request ID already describes different feedback.", 409)
                return json.loads(retry[1]), False
            receipts = run.get("skillReceipts") or {}
            feedback = {"schema": "neyvia.task-feedback.v1", "id": uuid.uuid4().hex,
                        "runId": run_id, "sessionId": session_id, "app": run.get("app"),
                        "verdict": verdict, "reason": reason, "reasonSource": source, "at": now(),
                        "taskText": run.get("taskText", ""), "workspaceRoot": run.get("workspaceRoot"),
                        "outputs": run.get("outputs", []), "outputSnapshots": run.get("outputSnapshots", {}),
                        "doneStatus": run.get("doneStatus"),
                        "skillReceipts": {"no-slop": receipts.get("no-slop"), "deliverables": receipts.get("deliverables")},
                        "evidenceWarnings": run.get("evidenceWarnings", [])}
            encoded = json.dumps(feedback, ensure_ascii=False, allow_nan=False)
            db.execute("INSERT OR REPLACE INTO feedback VALUES (?,?)", (run_id, encoded))
            db.execute("INSERT INTO requests VALUES (?,?,?)", (request_id, intent, encoded))
        return feedback, True


def public_feedback(root, run_id):
    path = Path(root) / ".neyvia" / "task-feedback.sqlite3"
    if not path.exists():
        return None
    feedback = FeedbackStore(root).get(run_id)
    if feedback is None:
        return None
    from .lesson_evolver import service_for
    lessons = service_for(root).list_lessons({"runId": run_id, "limit": 200})
    if isinstance(lessons, dict):
        lessons = lessons.get("lessons", [])
    return {"verdict": feedback["verdict"], "at": feedback["at"],
            "lessonCount": sum(row.get("evidence", {}).get("feedbackId") == feedback["id"] for row in lessons)}


def handle_command(backend, command, body):
    from .connected_sessions.broker import broker_for
    from .lesson_evolver import service_for
    broker = broker_for(backend.root, backend)
    store = FeedbackStore(backend.root)
    evolver = service_for(backend.root, backend)
    emit = lambda kind, data: broker._publish({"type": kind, **data})
    if command == "lesson_list_command":
        if "limit" in body and (type(body["limit"]) is not int or not 1 <= body["limit"] <= 200):
            raise ConnectedError("invalid_request", "Use a lesson limit from 1 to 200.")
        if "state" in body and (not isinstance(body["state"], str) or body["state"] not in {"quarantined", "testing", "promoted", "rejected", "reverted", "decayed"}):
            raise ConnectedError("invalid_request", "Choose a lesson state.")
        for key in ("manual", "runId"):
            if key in body:
                _text(body, key)
        lessons = evolver.list_lessons(body)
        return lessons if isinstance(lessons, dict) else {"lessons": lessons}
    if command == "lesson_revert_command":
        lesson_id, request_id = _text(body, "lessonId"), _text(body, "requestId", 200)
        try:
            result = evolver.revert_lesson(lesson_id, request_id, emit=emit)
        except ValueError as exc:
            raise ConnectedError("lesson_revert_refused", str(exc)[:500], 409) from exc
        return result if isinstance(result, dict) and "lesson" in result else {"lesson": result}
    run_id = _text(body, "runId")
    # Authoritative persisted run, never client-supplied task text or output paths.
    broker.get_run(run_id)
    run = broker.store.load(run_id)
    if run is None:
        raise ConnectedError("run_not_found", "That run was not found.", 404)
    broker._host_check(run.get("sessionId") or "")
    if command == "task_feedback_get_command":
        return {"feedback": store.get(run_id)}
    feedback, changed = store.save(body, run)
    if changed:
        emit("feedback.saved", {key: feedback[key] for key in ("runId", "sessionId", "verdict", "at")})
    # Retry repairs an interrupted save-to-queue handoff. A retry of an older,
    # replaced verdict must not re-draft the stale intent.
    if store.get(run_id)["id"] == feedback["id"]:
        evolver.enqueue_feedback(feedback, emit=emit)
    return {"feedback": feedback, "lessons": []}


def call(service, name, args):
    if service.backend is None:
        from .neyvia_ui_client import call_tool
        return call_tool(name, args)
    return handle_command(service.backend, TOOLS[name], args)
