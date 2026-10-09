"""Read and continue existing Codex chats through the supported app-server API.

This adapter never edits Codex session or index files. Chat IDs are the same
namespaced IDs returned by ``external_chat_inventory``; continuation is sent
to that existing Codex thread through ``thread/resume`` and ``turn/start``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from .subprocess_utils import hidden_windows_subprocess_kwargs

EventCallback = Callable[[dict[str, Any]], None]
ArtifactResolver = Callable[[Path], str | None]


class CodexAppServerError(RuntimeError):
    """A supported app-server operation failed or returned an invalid result."""

    def __init__(self, code: str = "app_server_error", message: str = "Codex could not complete this action. Inspect the same chat in Codex before retrying."):
        super().__init__(message)
        self.code = code


class CodexThreadBusy(CodexAppServerError):
    """The target thread already has a running turn or its state is unclear."""

    def __init__(self, message: str = "This Codex chat already has a turn in progress. Let it finish in Codex, then refresh before sending."):
        super().__init__("chat_busy", message)


class CodexApprovalRequired(CodexAppServerError):
    """A turn is blocked on an approval that Neyvia cannot answer yet."""

    def __init__(self):
        super().__init__("approval_required", "Codex is waiting for an approval. Resolve it in the same Codex chat, then refresh its status before sending again.")


class CodexInputRequired(CodexAppServerError):
    """A turn is waiting for user input that Neyvia cannot answer yet."""

    def __init__(self):
        super().__init__("input_required", "Codex is waiting for your input. Reply in the same Codex chat, then refresh its status before sending again.")


class CodexRunCancelled(CodexAppServerError):
    def __init__(self):
        super().__init__("turn_interrupted", "This connected Codex turn was stopped.")


def _command() -> list[str]:
    configured = str(os.environ.get("NEYVIA_CODEX_APP_SERVER_COMMAND") or "").strip()
    if configured:
        return [configured, "app-server", "--stdio"]
    candidates = [shutil.which(name) for name in ("codex.exe", "codex.cmd", "codex")]
    executable = next((item for item in candidates if item), None)
    if not executable:
        raise CodexAppServerError("Codex CLI is unavailable on the server host")
    return [executable, "app-server", "--stdio"]


class _Connection:
    """Small JSON-RPC client for one bounded app-server stdio connection."""

    def __init__(self, *, timeout: float = 30, on_event: EventCallback | None = None):
        self.timeout = timeout
        self.on_event = on_event
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._responses: dict[int | str, dict[str, Any]] = {}
        self._notifications: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stderr: list[str] = []

    def __enter__(self) -> "_Connection":
        options: dict[str, Any] = {
            "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8",
            "errors": "replace", "bufsize": 1,
            "start_new_session": os.name != "nt",
        }
        options.update(hidden_windows_subprocess_kwargs(new_process_group=True))
        try:
            self.process = subprocess.Popen(_command(), env=dict(os.environ), **options)
        except OSError as exc:
            raise CodexAppServerError("app_server_start_failed", "Codex app-server could not start. Check the host CLI installation and sign-in.") from exc
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        init = self.request("initialize", {"clientInfo": {"name": "neyvia-connected-chats", "version": "1.0"}, "capabilities": {"experimentalApi": True}})
        del init
        self.notify("initialized", {})
        return self

    def __exit__(self, *_: object) -> None:
        process = self.process
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

    def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        for raw in self.process.stdout:
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            request_id = item.get("id")
            if isinstance(request_id, (int, str)) and not item.get("method"):
                with self._lock:
                    self._responses[request_id] = item
            elif item.get("method"):
                params = item.get("params") if isinstance(item.get("params"), dict) else {}
                notification = {"method": str(item["method"]), "params": params}
                if isinstance(request_id, (int, str)):
                    notification["serverRequestId"] = request_id
                with self._lock:
                    self._notifications.append(notification)
                if self.on_event:
                    self.on_event(notification)

    def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        for raw in self.process.stderr:
            if raw.strip():
                self._stderr.append(raw.strip()[-300:])
                self._stderr[:] = self._stderr[-8:]

    def notify(self, method: str, params: dict[str, Any]) -> None:
        assert self.process and self.process.stdin
        with self._write_lock:
            self.process.stdin.write(json.dumps({"method": method, "params": params}) + "\n")
            self.process.stdin.flush()

    def respond_server_request(self, request_id: int | str, result: dict[str, Any]) -> None:
        assert self.process and self.process.stdin
        with self._write_lock:
            self.process.stdin.write(json.dumps({"id": request_id, "result": result}) + "\n")
            self.process.stdin.flush()

    def reject_server_request(self, request_id: int | str, message: str = "The request was cancelled by the user.") -> None:
        assert self.process and self.process.stdin
        with self._write_lock:
            self.process.stdin.write(json.dumps({"id": request_id, "error": {"code": -32800, "message": message}}) + "\n")
            self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self.process and self.process.stdin
        self._next_id += 1
        # Keep client request IDs in a disjoint namespace from server initiated
        # requests, whose numeric IDs may otherwise collide with our RPCs.
        request_id = f"neyvia-{self._next_id}"
        with self._write_lock:
            self.process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
            self.process.stdin.flush()
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            with self._lock:
                response = self._responses.pop(request_id, None)
            if response is not None:
                if "error" in response:
                    error = response["error"]
                    if method == "turn/start" and _has_key(error, "activeTurnNotSteerable"):
                        raise CodexThreadBusy()
                    raise CodexAppServerError("rpc_failed")
                result = response.get("result")
                if not isinstance(result, dict):
                    raise CodexAppServerError(f"{method}: app-server returned no result object")
                return result
            if self.process.poll() is not None:
                break
            time.sleep(0.01)
        detail = "; ".join(self._stderr)
        suffix = f" ({detail})" if detail else ""
        raise CodexAppServerError("rpc_timeout", f"Codex did not answer the {method} request. Inspect the same chat before retrying.")

    def wait_for_turn(self, thread_id: str, *, timeout: float, turn_id: str = "", on_request: Callable[[dict[str, Any]], dict[str, Any]] | None = None, is_cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        observed: set[str] = set()
        interrupt_sent = False
        while time.monotonic() < deadline:
            with self._lock:
                events = list(self._notifications)
            for event in events:
                marker = str(event.get("serverRequestId", "")) or json.dumps(event, sort_keys=True, default=str)
                if marker in observed:
                    continue
                observed.add(marker)
                method = event["method"]
                params = event["params"]
                event_thread = str(params.get("threadId") or "")
                if event_thread and event_thread != thread_id:
                    continue
                if method in {"turn/completed", "turn/failed"}:
                    turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
                    status = str(turn.get("status") or ("failed" if method == "turn/failed" else "completed"))
                    return {"status": status, "turnId": str(turn.get("id") or ""), "turn": turn}
                request_id = event.get("serverRequestId")
                if request_id is not None and method in {
                    "item/commandExecution/requestApproval", "item/fileChange/requestApproval",
                    "item/permissions/requestApproval", "item/tool/requestUserInput",
                    "mcpServer/elicitation/request",
                }:
                    if not on_request:
                        self.reject_server_request(request_id)
                        continue
                    request_started = time.monotonic()
                    try:
                        response = on_request(event)
                    except CodexRunCancelled:
                        response = {"decision": "cancel"}
                    finally:
                        # A user may leave the browser open while reviewing a
                        # request; that wait must not consume the model turn's
                        # execution timeout budget.
                        deadline += time.monotonic() - request_started
                    if isinstance(response, dict):
                        cancelled = response.get("decision") == "cancel"
                        wire_result = _server_request_result(method, params, response)
                        self.respond_server_request(request_id, wire_result)
                        if cancelled and turn_id and not interrupt_sent:
                            try:
                                self.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
                            except CodexAppServerError:
                                pass
                            interrupt_sent = True
            if is_cancelled and is_cancelled() and not interrupt_sent:
                if turn_id:
                    try:
                        self.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
                    except CodexAppServerError:
                        pass
                interrupt_sent = True
            if self.process and self.process.poll() is not None:
                raise CodexAppServerError("turn_interrupted", "Codex app-server stopped before confirming completion. Inspect the same chat before retrying.")
            time.sleep(0.05)
        raise CodexAppServerError("turn_timeout", "Codex has not confirmed that this turn finished. Inspect the same chat before retrying.")


def _has_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_has_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_has_key(child, key) for child in value)
    return False


def _server_request_result(method: str, params: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Translate the small browser response contract to Codex's exact schema."""
    decision = str(response.get("decision") or "deny")
    if method == "item/commandExecution/requestApproval":
        # Keep grants scoped to this single action; never create a session rule.
        return {"decision": {"approve": "accept", "deny": "decline", "cancel": "cancel"}.get(decision, "decline")}
    if method == "item/fileChange/requestApproval":
        return {"decision": {"approve": "accept", "deny": "decline", "cancel": "cancel"}.get(decision, "decline")}
    if method == "item/permissions/requestApproval":
        permissions = params.get("permissions") if decision == "approve" and isinstance(params.get("permissions"), dict) else {"fileSystem": None, "network": None}
        return {"permissions": permissions, "scope": "turn", "strictAutoReview": None}
    if method == "item/tool/requestUserInput":
        answers = response.get("answers") if isinstance(response.get("answers"), dict) else {}
        mapped: dict[str, dict[str, list[str]]] = {}
        for question in params.get("questions", []) if isinstance(params.get("questions"), list) else []:
            if not isinstance(question, dict) or not question.get("id"):
                continue
            question_id = str(question["id"])
            value = str(answers.get(question_id, ""))[:20_000]
            mapped[question_id] = {"answers": [value] if value else []}
        return {"answers": mapped}
    if method == "mcpServer/elicitation/request":
        if decision != "approve":
            return {"action": "cancel" if decision == "cancel" else "decline"}
        values = response.get("answers") if isinstance(response.get("answers"), dict) else {}
        return {"action": "accept", "content": values}
    return {}


def _decode_identity(identity: str) -> tuple[str, str]:
    parts = str(identity or "").split(":", 3)
    if len(parts) != 4 or parts[0] != "external" or parts[1] != "codex":
        raise ValueError("Expected a namespaced local Codex chat ID")
    from .external_chat_inventory import _host
    if parts[2] != _host()["deviceId"]:
        raise ValueError("This Codex chat belongs to another device")
    thread_id = unquote(parts[3])
    if not thread_id or len(thread_id) > 200 or any(ch in thread_id for ch in "\\/\x00"):
        raise ValueError("Invalid Codex thread ID")
    return identity, thread_id


def _resolve_inventory_chat(identity: str) -> dict[str, Any]:
    """Use the inventory's path-checked resolver when available (read-only)."""
    from . import external_chat_inventory as inventory
    resolver = getattr(inventory, "resolve_external_chat", None)
    if callable(resolver):
        row = resolver(identity)
        if not row:
            raise FileNotFoundError("Codex chat is unavailable on this device")
        return row
    from .external_chat_inventory import _discover, _host, _paths
    host, paths = _host(), _paths(None)
    row = next((item for item in _discover("codex", paths, host) if item.get("id") == identity), None)
    if row is None:
        raise FileNotFoundError("Codex chat is unavailable on this device")
    return row


def _thread_from(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("thread")
    return value if isinstance(value, dict) else {}


def _read_turn_page(conn: _Connection, thread_id: str, *, limit: int = 40, direction: str = "desc") -> dict[str, Any]:
    return conn.request("thread/turns/list", {"threadId": thread_id, "limit": limit, "sortDirection": direction, "itemsView": "full"})


def _read_thread_and_turns(conn: _Connection, thread_id: str, *, limit: int = 40) -> tuple[dict[str, Any], bool]:
    meta = conn.request("thread/read", {"threadId": thread_id, "includeTurns": False})
    thread = _thread_from(meta)
    if str(thread.get("id") or "") != thread_id:
            raise CodexAppServerError("thread_unavailable", "This Codex chat is unavailable through the host app-server.")
    page = _read_turn_page(conn, thread_id, limit=limit, direction="desc")
    turns = page.get("data") if isinstance(page.get("data"), list) else []
    thread["turns"] = list(reversed(turns))
    return thread, bool(page.get("nextCursor"))


def _page_chats(conn: _Connection, *, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
    from .external_chat_inventory import _host
    device = _host()
    cap = max(1, min(int(limit or 100), 500))
    chats: list[dict[str, Any]] = []
    cursor: str | None = None
    while len(chats) < cap:
        params: dict[str, Any] = {"limit": min(cap - len(chats), 100), "sortKey": "updated_at", "sortDirection": "desc"}
        if cursor:
            params["cursor"] = cursor
        if query.strip():
            params["searchTerm"] = query.strip()[:200]
        page = conn.request("thread/list", params)
        for thread in page.get("data", []) if isinstance(page.get("data"), list) else []:
            if not isinstance(thread, dict) or not thread.get("id"):
                continue
            thread_id = str(thread["id"])
            raw_status = thread.get("status")
            status = str(raw_status.get("type") or "") if isinstance(raw_status, dict) else str(raw_status or "")
            chat = {
                "id": f"external:codex:{device['deviceId']}:{thread_id}", "app": "codex",
                "appLabel": "Codex", "title": str(thread.get("name") or thread.get("preview") or "Codex conversation")[:240],
                "project": Path(str(thread.get("cwd") or "")).name,
                "updatedAt": thread.get("updatedAt") or thread.get("updated_at") or "",
                "deviceId": device["deviceId"], "deviceName": device["deviceName"],
                "source": "codex-app-server", "readable": True, "continuable": True,
                "active": thread.get("canAcceptDirectInput") is False or status in {"inProgress", "running"},
            }
            chats.append(chat)
            if len(chats) >= cap:
                break
        cursor = page.get("nextCursor") if isinstance(page.get("nextCursor"), str) else None
        if not cursor or not page.get("data"):
            break
    return chats


def list_codex_chats(*, query: str = "", limit: int = 100) -> dict[str, Any]:
    """List existing local Codex threads using the installed app-server."""
    with _Connection() as conn:
        chats = _page_chats(conn, query=query, limit=limit)
    from .external_chat_inventory import _host
    return {"chats": chats, "sources": [{"app": "codex", "appLabel": "Codex", "available": True, "chatCount": len(chats), "error": ""}], "host": _host(), "capabilities": {"list": True, "read": True, "continue": True, "transport": "codex-app-server"}}


def _messages_from_thread(thread: dict[str, Any], artifact_resolver: ArtifactResolver | None) -> list[dict[str, Any]]:
    from .external_chat_inventory import _host
    messages: list[dict[str, Any]] = []
    for turn in thread.get("turns", []) if isinstance(thread.get("turns"), list) else []:
        if not isinstance(turn, dict):
            continue
        for item in turn.get("items", []) if isinstance(turn.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "")
            role = "assistant" if kind in {"agentMessage", "assistantMessage", "imageGeneration", "imageView"} else "user" if kind == "userMessage" else ""
            if not role:
                continue
            blocks: list[dict[str, Any]] = []
            raw_text = item.get("text")
            if isinstance(raw_text, str) and raw_text.strip():
                blocks.append({"type": "text", "text": raw_text})
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        blocks.append({"type": "text", "text": text})
                    path_value = part.get("path") or part.get("url") or part.get("imageUrl")
                    if isinstance(path_value, str):
                        resolved = _artifact_reference(path_value, artifact_resolver)
                        if resolved:
                            blocks.append(resolved)
            text = "\n".join(block["text"] for block in blocks if block.get("type") == "text").strip()
            artifacts = _item_artifacts(item, artifact_resolver)
            if text or blocks or artifacts:
                row: dict[str, Any] = {"role": role, "text": text, "timestamp": item.get("createdAt") or turn.get("startedAt") or "", "itemId": str(item.get("id") or ""), "blocks": blocks, "artifacts": artifacts}
                if item.get("phase"):
                    row["phase"] = item["phase"]
                messages.append(row)
    return messages


def _artifact_reference(value: str, resolver: ArtifactResolver | None) -> dict[str, Any] | None:
    if value.startswith(("https://", "http://", "data:")):
        return {"type": "image", "url": value} if value.startswith("data:") or any(ext in value.casefold() for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")) else {"type": "link", "url": value}
    raw = value[7:] if value.startswith("file://") else value
    try:
        path = Path(raw).expanduser().resolve(strict=True)
        if not path.is_file() or not resolver:
            return None
        url = resolver(path)
        if not url:
            return None
        return {"type": "image" if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp", ".gif"} else "file", "url": url, "name": path.name}
    except (OSError, RuntimeError, ValueError):
        return None


def _item_artifacts(item: dict[str, Any], resolver: ArtifactResolver | None) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for key in ("path", "savedPath", "filePath", "outputPath", "imagePath", "artifactPath", "url"):
        value = item.get(key)
        if isinstance(value, str):
            resolved = _artifact_reference(value, resolver)
            if resolved and resolved not in found:
                found.append(resolved)
    # Keep Codex's output object metadata while only surfacing locally resolved URLs.
    for key in ("images", "artifacts", "files"):
        values = item.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str):
                    resolved = _artifact_reference(value, resolver)
                elif isinstance(value, dict):
                    candidate = next((value.get(name) for name in ("path", "filePath", "url") if isinstance(value.get(name), str)), None)
                    resolved = _artifact_reference(candidate, resolver) if candidate else None
                else:
                    resolved = None
                if resolved and resolved not in found:
                    found.append(resolved)
    return found


def read_codex_chat(identity: str, *, artifact_resolver: ArtifactResolver | None = None) -> dict[str, Any]:
    """Read the canonical existing Codex thread and its persisted turn items."""
    _, thread_id = _decode_identity(identity)
    row = _resolve_inventory_chat(identity)
    with _Connection() as conn:
        thread, truncated = _read_thread_and_turns(conn, thread_id)
    device = row.get("deviceId") or _decode_identity(identity)[0].split(":", 3)[2]
    chat = {key: row.get(key) for key in ("id", "app", "appLabel", "title", "project", "updatedAt", "deviceId", "deviceName") if row.get(key) is not None}
    chat["id"] = identity
    chat.setdefault("app", "codex")
    chat.setdefault("appLabel", "Codex")
    return {"chat": chat, "messages": _messages_from_thread(thread, artifact_resolver), "truncated": truncated, "source": "codex-app-server", "capabilities": {"read": True, "continue": True}}


def _ensure_idle(conn: _Connection, thread_id: str) -> dict[str, Any]:
    meta = conn.request("thread/read", {"threadId": thread_id, "includeTurns": False})
    thread = _thread_from(meta)
    if str(thread.get("id") or "") != thread_id:
        raise CodexAppServerError("thread_unavailable", "This Codex chat is unavailable through the host app-server.")
    turn_page = _read_turn_page(conn, thread_id, limit=1)
    turns = turn_page.get("data") if isinstance(turn_page.get("data"), list) else []
    last_turn = turns[0] if turns and isinstance(turns[0], dict) else {}
    turn_status = str(last_turn.get("status") or "").casefold()
    status_value = thread.get("status")
    status = str(status_value.get("type") or "").casefold() if isinstance(status_value, dict) else str(status_value or "").casefold()
    if thread.get("canAcceptDirectInput") is False or status in {"inprogress", "running", "waiting", "requiresaction"} or turn_status == "inprogress":
        raise CodexThreadBusy("The existing Codex chat has an active turn; wait for it to finish before continuing")
    if thread.get("canAcceptDirectInput") is not True and turn_status not in {"completed", "failed", "interrupted"}:
        raise CodexThreadBusy("Codex app-server did not provide enough run state to safely continue this chat")
    return thread


def send_codex_chat_message(
    identity: str,
    message: str,
    *,
    request_id: str = "",
    on_event: EventCallback | None = None,
    artifact_resolver: ArtifactResolver | None = None,
    on_request: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    timeout: float = 900,
) -> dict[str, Any]:
    """Continue the same Codex thread; never create or import a new conversation.

    A fresh app-server connection resumes the existing thread and starts one turn.
    Any active/unclear state, RPC failure, or disconnect is surfaced as-is; this
    method never retries a send because completion may be ambiguous.
    """
    text = str(message or "").strip()
    if not text:
        raise ValueError("A non-empty message is required")
    _, thread_id = _decode_identity(identity)
    _resolve_inventory_chat(identity)
    events: list[dict[str, Any]] = []
    def forward(event: dict[str, Any]) -> None:
        events.append(event)
        if on_event:
            on_event(event)
    with _Connection(timeout=min(max(timeout, 1), 60), on_event=forward) as conn:
        _ensure_idle(conn, thread_id)
        resumed = conn.request("thread/resume", {"threadId": thread_id})
        thread = _thread_from(resumed)
        if str(thread.get("id") or "") != thread_id:
            raise CodexAppServerError("resume_failed", "Codex could not resume this chat. Inspect it in Codex before retrying.")
        # Recheck immediately before sending. The app-server's own active-turn
        # guard is the final arbiter if the desktop app starts a turn in the race.
        _ensure_idle(conn, thread_id)
        started = conn.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": text}]})
        turn = started.get("turn") if isinstance(started.get("turn"), dict) else {}
        turn_id = str(turn.get("id") or "")
        try:
            completion = conn.wait_for_turn(thread_id, timeout=timeout, turn_id=turn_id, on_request=on_request, is_cancelled=is_cancelled)
        except CodexAppServerError as exc:
            return {"ok": False, "threadId": thread_id, "turnId": turn_id, "requestId": request_id, "error": str(exc), "errorCode": exc.code, "retrySafety": "reconcile_same_thread_before_retry", "events": events}
        final_thread, _ = _read_thread_and_turns(conn, thread_id)
    messages = _messages_from_thread(final_thread, artifact_resolver)
    assistant = next((item for item in reversed(messages) if item.get("role") == "assistant"), None)
    status = str(completion.get("status") or "")
    return {"ok": status == "completed", "threadId": thread_id, "turnId": completion.get("turnId") or turn_id, "requestId": request_id,
            "status": status, "message": assistant, "events": events, "source": "codex-app-server",
            "retrySafety": "safe_after_confirmed_completion" if status == "completed" else "reconcile_same_thread_before_retry",
            "capabilities": {"sameThread": True, "images": True, "artifacts": bool(artifact_resolver)}}


def connected_codex_capabilities() -> dict[str, Any]:
    """Report readiness and actual supported operations for this host."""
    command = shutil.which("codex.exe") or shutil.which("codex.cmd") or shutil.which("codex")
    return {"available": bool(command), "authenticatedFromHost": "host_codex_app_server_config",
            "transport": "codex-app-server", "capabilities": {"list": bool(command), "read": bool(command), "continue": bool(command), "images": bool(command), "artifacts": "requires_server_artifact_resolver"},
            "limitation": "Active-turn detection is based on app-server state; a separate desktop runtime may race. Codex app-server turn guards remain authoritative." if command else "Codex CLI is not installed on this host."}
