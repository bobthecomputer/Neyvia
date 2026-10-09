"""Durable, idempotent dispatch for same-session connected app messages."""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .external_chat_inventory import resolve_external_chat

_WORKER_LOCK = threading.RLock()
_LIVE_WORKERS: set[str] = set()
_STALE_AFTER_SECONDS = 6 * 60 * 60


class ConnectedAppChats:
    def __init__(self, root: Path):
        self.path = Path(root) / ".agent_control" / "connected_chats.sqlite3"
        self._request_lock = threading.RLock()
        self._request_waiters: dict[str, dict] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, chat TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL, pid INTEGER, updated REAL, data TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def capabilities(self, identity: str) -> dict:
        app = resolve_external_chat(identity)["app"]
        if app == "codex":
            from .connected_codex_chats import connected_codex_capabilities
            available = bool(connected_codex_capabilities().get("available"))
        elif app == "claude-code":
            from .connected_claude_chats import capabilities
            available = bool(capabilities().get("available"))
        else:
            available = False
        return {"canSend": available, "reason": "" if available else "This app has no available same-session send adapter on this host.",
                "authentication": "existing-host-sign-in", "app": app}

    @staticmethod
    def _thread_name(run_id: str) -> str:
        return f"connected-app-chat-{run_id}"

    def _worker_is_live(self, run_id: str) -> bool:
        with _WORKER_LOCK:
            if run_id in _LIVE_WORKERS:
                return True
        name = self._thread_name(run_id)
        return any(thread.name == name and thread.is_alive() for thread in threading.enumerate())

    def _owner_process_is_live(self, row: sqlite3.Row, data: dict) -> bool:
        try:
            import psutil
        except ImportError:
            return False
        try:
            process = psutil.Process(int(row["pid"] or 0))
            expected_start = data.get("_ownerProcessStartedAt")
            if expected_start is not None and abs(process.create_time() - float(expected_start)) > 1.0:
                return False
            return True
        except (OSError, ValueError, psutil.Error):
            return False

    def _mark_interrupted(self, db, row: sqlite3.Row, data: dict, reason: str):
        data.update(state="interrupted", error=reason)
        db.execute("UPDATE runs SET state=?,updated=?,data=? WHERE id=?", ("interrupted", time.time(), json.dumps(data), row["id"]))
        return data

    def _recover_stale(self, db, *, chat: str | None = None, run_id: str | None = None):
        sql = "SELECT * FROM runs WHERE state IN ('queued','running')"
        args = []
        if chat is not None:
            sql += " AND chat=?"
            args.append(chat)
        if run_id is not None:
            sql += " AND id=?"
            args.append(run_id)
        for row in db.execute(sql, args).fetchall():
            data = json.loads(row["data"])
            if int(row["pid"] or 0) == os.getpid():
                if self._worker_is_live(row["id"]):
                    continue
            elif self._owner_process_is_live(row, data):
                if time.time() - float(row["updated"] or 0) < _STALE_AFTER_SECONDS:
                    continue
            reason = "The previous send stopped before Neyvia recorded completion. Inspect the same app chat before retrying; it was not resent."
            self._mark_interrupted(db, row, data, reason)

    def get(self, run_id: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover_stale(db, run_id=run_id)
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise ValueError("Connected chat run not found")
            data = json.loads(row["data"])
            return {key: value for key, value in data.items() if not key.startswith("_")}

    def latest(self, chat_id: str) -> dict | None:
        """Return the most recently updated run for this exact discovered chat."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover_stale(db, chat=chat_id)
            row = db.execute(
                "SELECT * FROM runs WHERE chat=? ORDER BY updated DESC, rowid DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
            if not row:
                return None
            data = json.loads(row["data"])
            return {key: value for key, value in data.items() if not key.startswith("_")}

    def answer(self, run_id: str, pending_id: str, response: dict) -> dict:
        """Resolve only the currently displayed request on its live owner thread."""
        if not isinstance(response, dict):
            raise ValueError("A response object is required")
        decision = str(response.get("decision") or "")
        if decision not in {"approve", "deny"}:
            raise ValueError("Choose approve or deny for this request")
        answers = response.get("answers") if isinstance(response.get("answers"), dict) else {}
        with self._request_lock:
            waiter = self._request_waiters.get(run_id)
            if not waiter or waiter.get("pendingId") != pending_id:
                raise ValueError("This request is no longer waiting. Refresh the chat and review its current state.")
            if waiter["event"].is_set():
                raise ValueError("This request already has a response. Refresh the chat to see its current state.")
            if waiter.get("kind") == "user_input" and waiter.get("method") != "mcpServer/elicitation/request" and decision != "approve":
                raise ValueError("Submit the answers or use Stop to end this turn")
            choices = waiter.get("choices") or []
            if waiter.get("kind") == "approval" and decision not in choices:
                raise ValueError("That action is not available for this request")
            waiter["response"] = {"decision": decision, "answers": {str(key): str(value)[:20_000] for key, value in answers.items()}}
            waiter["event"].set()
        return self.get(run_id)

    def cancel(self, run_id: str) -> dict:
        """Stop a connected Codex turn, or answer an open prompt with cancel."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover_stale(db, run_id=run_id)
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise ValueError("Connected chat run not found")
            run_data = json.loads(row["data"])
            if run_data.get("app") != "codex":
                raise ValueError("Stopping a connected turn is currently supported for Codex only")
            if row["state"] not in {"queued", "running"}:
                return {key: value for key, value in run_data.items() if not key.startswith("_")}
        with self._request_lock:
            event = self._cancel_events.get(run_id)
            if event:
                event.set()
            waiter = self._request_waiters.get(run_id)
            if waiter:
                waiter["response"] = {"decision": "cancel", "answers": {}}
                waiter["event"].set()
        return self.get(run_id)

    @staticmethod
    def _public_request(method: str, params: dict) -> dict:
        if method == "item/commandExecution/requestApproval":
            kind, title = "approval", "Codex requests permission to run a command"
            detail = str(params.get("reason") or "Review the command before allowing it.")[:4000]
        elif method == "item/fileChange/requestApproval":
            kind, title = "approval", "Codex requests permission to apply file changes"
            detail = str(params.get("reason") or "Review the requested file changes before allowing them.")[:4000]
        elif method == "item/permissions/requestApproval":
            kind, title = "approval", "Codex requests additional permissions"
            detail = str(params.get("reason") or "The request will be granted for this turn only.")[:4000]
        elif method == "item/tool/requestUserInput":
            kind, title = "user_input", "Codex needs your input"
            detail = "Answer the questions below to continue this same turn."
        else:
            kind, title = "user_input", "A connected MCP tool needs your input"
            detail = str(params.get("message") or "Review the request and provide a response.")[:4000]
        request = {"id": uuid.uuid4().hex, "kind": kind, "method": method, "title": title, "detail": detail,
                   "reason": str(params.get("reason") or "")[:4000], "expiresAt": time.time() + 24 * 60 * 60}
        if isinstance(params.get("command"), str):
            request["command"] = params["command"][:20_000]
        if isinstance(params.get("cwd"), str):
            request["cwd"] = params["cwd"][:2000]
        if method == "item/tool/requestUserInput":
            questions = []
            for question in params.get("questions", []) if isinstance(params.get("questions"), list) else []:
                if not isinstance(question, dict):
                    continue
                row = {key: str(question.get(key) or "")[:4000] for key in ("id", "header", "question")}
                row["isSecret"] = bool(question.get("isSecret"))
                row["options"] = [
                    {"label": str(option.get("label") or "")[:300], "description": str(option.get("description") or "")[:1000]}
                    for option in question.get("options", []) if isinstance(option, dict)
                ] if isinstance(question.get("options"), list) else []
                questions.append(row)
            request["questions"] = questions[:20]
        elif method == "mcpServer/elicitation/request":
            request["mode"] = str(params.get("mode") or "")[:100]
            request["requestedSchema"] = params.get("requestedSchema") if isinstance(params.get("requestedSchema"), dict) else {}
        elif method == "item/permissions/requestApproval":
            request["permissions"] = params.get("permissions") if isinstance(params.get("permissions"), dict) else {}
            request["choices"] = ["approve", "deny"]
        elif method == "item/commandExecution/requestApproval":
            available = params.get("availableDecisions")
            allowed = set()
            for decision in available if isinstance(available, list) else []:
                if isinstance(decision, str):
                    allowed.add(decision)
                elif isinstance(decision, dict):
                    allowed.update(str(key) for key in decision)
            request["choices"] = [choice for choice, names in (("approve", {"accept"}), ("deny", {"decline"})) if (available is None and choice in {"approve", "deny"}) or allowed.intersection(names)]
            if not request["choices"]:
                request["choices"] = ["deny"]
        else:
            request["choices"] = ["approve", "deny"]
        return request

    def _await_request(self, run_id: str, data: dict, event: dict, *, timeout: float = 24 * 60 * 60) -> dict:
        from .connected_codex_chats import CodexRunCancelled
        method = str(event.get("method") or "")
        params = event.get("params") if isinstance(event.get("params"), dict) else {}
        pending = self._public_request(method, params)
        waiter = {"pendingId": pending["id"], "kind": pending["kind"], "method": method, "choices": pending.get("choices", []), "event": threading.Event(), "response": None}
        with self._request_lock:
            self._request_waiters[run_id] = waiter
        data["pendingRequest"] = pending
        data["events"] = [{"message": pending["title"]}]
        self._save(data)
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if waiter["event"].wait(timeout=0.2):
                    break
                with self._request_lock:
                    cancel_event = self._cancel_events.get(run_id)
                    if cancel_event and cancel_event.is_set():
                        raise CodexRunCancelled()
            else:
                raise TimeoutError("The connected app request expired before it was answered.")
            with self._request_lock:
                if waiter.get("response") is None:
                    raise CodexRunCancelled()
                response = dict(waiter["response"])
            if response.get("decision") == "cancel":
                return response
            data["pendingRequest"] = None
            data["events"] = [{"message": "Resuming the same app turn…"}]
            self._save(data)
            return response
        finally:
            data["pendingRequest"] = None
            try:
                self._save(data)
            except sqlite3.Error:
                pass
            with self._request_lock:
                if self._request_waiters.get(run_id) is waiter:
                    self._request_waiters.pop(run_id, None)

    def _save(self, data: dict):
        with self.connect() as db:
            db.execute("UPDATE runs SET state=?,updated=?,data=? WHERE id=?", (data["state"], time.time(), json.dumps(data), data["runId"]))

    def send(self, identity: str, message: str, request_id: str) -> dict:
        if not isinstance(message, str) or not message.strip() or len(message) > 100_000:
            raise ValueError("Send a message between 1 and 100,000 characters")
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 160:
            raise ValueError("A stable request ID is required")
        fingerprint = hashlib.sha256((identity + "\0" + message).encode()).hexdigest()
        data = {"runId": request_id, "chatId": identity, "app": "", "state": "queued", "reply": "", "events": [], "error": ""}
        data["pendingRequest"] = None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover_stale(db, chat=identity)
            old = db.execute("SELECT fingerprint,data FROM runs WHERE id=?", (request_id,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("Request ID was already used for a different message")
                old_data = json.loads(old["data"])
                return {key: value for key, value in old_data.items() if not key.startswith("_")}
            active = db.execute("SELECT id FROM runs WHERE chat=? AND state IN ('queued','running')", (identity,)).fetchone()
            if active:
                raise ValueError("This connected chat already has a Neyvia send in progress")
            row = resolve_external_chat(identity)
            data["app"] = row["app"]
            data["canCancel"] = row["app"] == "codex"
            if not self.capabilities(identity)["canSend"]:
                raise ValueError("This chat cannot be continued from this host")
            try:
                import psutil
                data["_ownerProcessStartedAt"] = psutil.Process(os.getpid()).create_time()
            except (ImportError, OSError, ValueError):
                data["_ownerProcessStartedAt"] = None
            thread_name = self._thread_name(request_id)
            with self._request_lock:
                self._cancel_events[request_id] = threading.Event()
            thread = threading.Thread(target=self._run, args=(row["app"], identity, message, data), name=thread_name, daemon=True)
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (request_id, identity, fingerprint, "queued", os.getpid(), time.time(), json.dumps(data)))
            with _WORKER_LOCK:
                _LIVE_WORKERS.add(request_id)
        try:
            thread.start()
        except RuntimeError:
            with _WORKER_LOCK:
                _LIVE_WORKERS.discard(request_id)
            with self._request_lock:
                self._cancel_events.pop(request_id, None)
            data.update(state="interrupted", error="Neyvia could not start this send. Inspect the same app chat before retrying.")
            self._save(data)
        return {**{key: value for key, value in data.items() if not key.startswith("_")}, "events": []}

    def _run(self, app: str, identity: str, message: str, data: dict):
        data["state"] = "running"
        with self._request_lock:
            cancellation = self._cancel_events.setdefault(data["runId"], threading.Event())
        def event(value):
            # Never export reasoning or raw tool arguments to a UI progress log.
            kind = value.get("type") or value.get("method") or ""
            text = ""
            if kind == "assistant_delta":
                text = str(value.get("text") or "")
            elif kind == "item/agentMessage/delta":
                text = str((value.get("params") or {}).get("delta") or "")
            elif kind == "assistant_message":
                parts = (value.get("message") or {}).get("content") or []
                data["reply"] = "\n".join(str(p.get("text") or "") for p in parts if isinstance(p, dict) and p.get("type") == "text")[-200_000:]
            if text:
                data["reply"] = (data["reply"] + text)[-200_000:]
            data["events"] = [{"message": "Receiving the app response…" if text else "Working in the connected app session…"}]
            try:
                self._save(data)
            except sqlite3.Error:
                # Final state is saved after the adapter returns. A transient
                # polling/UI write failure must not interrupt the native turn.
                pass
        try:
            if app == "codex" and cancellation.is_set():
                from .connected_codex_chats import CodexRunCancelled
                raise CodexRunCancelled()
            self._save(data)
            if app == "codex":
                from .connected_codex_chats import (
                    CodexApprovalRequired, CodexAppServerError, CodexInputRequired,
                    CodexThreadBusy, send_codex_chat_message,
                )
                result = send_codex_chat_message(identity, message, request_id=data["runId"], on_event=event,
                    on_request=lambda request: self._await_request(data["runId"], data, request, timeout=24 * 60 * 60),
                    is_cancelled=cancellation.is_set, timeout=24 * 60 * 60)
                if not result.get("ok"):
                    code = result.get("errorCode")
                    if result.get("status") == "interrupted":
                        raise CodexRunCancelled()
                    if code == "approval_required":
                        raise CodexApprovalRequired()
                    if code == "input_required":
                        raise CodexInputRequired()
                    if code == "chat_busy":
                        raise CodexThreadBusy()
                    raise CodexAppServerError(str(code or "turn_failed"), str(result.get("error") or "Codex did not confirm completion. Inspect the same chat before retrying."))
                data["reply"] = str((result.get("message") or {}).get("text") or data["reply"])
            else:
                from .connected_claude_chats import send_message
                result = send_message(identity, message, request_id=data["runId"], on_event=event)
                data["reply"] = result["text"]
            data["state"] = "completed"
        except Exception as exc:
            safe_types = {"ConnectedClaudeChatError", "CodexThreadBusy", "CodexApprovalRequired", "CodexInputRequired", "CodexAppServerError", "CodexRunCancelled"}
            if type(exc).__name__ == "CodexRunCancelled":
                data.update(state="interrupted", error=str(exc))
            else:
                data.update(state="failed", error=str(exc) if type(exc).__name__ in safe_types else "The app did not confirm this send. Inspect its existing chat before retrying; Neyvia has not resent it.")
        finally:
            try:
                self._save(data)
            finally:
                with _WORKER_LOCK:
                    _LIVE_WORKERS.discard(data["runId"])
                with self._request_lock:
                    self._cancel_events.pop(data["runId"], None)
