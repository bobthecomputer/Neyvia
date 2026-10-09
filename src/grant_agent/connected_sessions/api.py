"""HTTP and command surface of the connected-sessions broker.

``handle_connected_command`` is what ``FluxioWebBackend.dispatch`` delegates to. The HTTP
helpers write the JSON responses, the live event stream (SSE) and the media route for
``web_backend``'s request handler, so ``web_backend`` only carries small hooks. Imports of the
broker and ``web_backend`` are lazy: ``desktop_bridge`` imports this module for the command
names alone.
"""
from __future__ import annotations

import json
import logging
import select
import socket
import ssl
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from .. import proofs_a_sessions as _proofs

log = logging.getLogger("neyvia.connected_sessions")

from ..neyvia_conductor import COMMANDS as CONDUCTOR_COMMANDS, MUTATIONS as CONDUCTOR_MUTATIONS
from ..task_feedback import COMMANDS as FEEDBACK_COMMANDS
from ..prompt_amplifier import COMMANDS as PROMPT_COMMANDS

CONNECTED_COMMANDS = CONDUCTOR_COMMANDS | FEEDBACK_COMMANDS | PROMPT_COMMANDS | frozenset({
    "connected_sessions_list_command",
    "connected_session_read_command",
    "connected_session_tool_output_command",
    "connected_session_send_command",
    "connected_session_new_command",
    "connected_session_stop_command",
    "connected_session_steer_command",
    "connected_session_answer_command",
    "connected_session_compact_command",
    "connected_session_goal_command",
    "connected_provider_options_command",
    "connected_session_workspace_command",
    "connected_session_file_diff_command",
    "connected_session_git_action_command",
    "connected_session_mark_seen_command",
    "connected_events_poll_command",
    "connected_folders_command",
    "connected_github_repos_command",
    "connected_folder_clone_command",
    "connected_folder_worktree_command",
    "connected_app_auth_command",
    "connected_app_sign_in_command",
    "connected_session_media_command",
    "connected_app_sign_in_code_command",
    "connected_agents_dashboard_command",
    "connected_limits_command",
})

# The desktop app has no session cookie for the media route, so it reads an image through
# this command instead; larger files stay a "not available here" chip.
MAX_MEDIA_COMMAND_BYTES = 12 * 1024 * 1024

# Commands that act with the PC's own sign-ins (Claude, Codex, GitHub) or change
# files. Only the PC owner's account may run them: another Neyvia user must never
# drive this PC's Claude or Codex subscription.
OWNER_COMMANDS = CONDUCTOR_MUTATIONS | FEEDBACK_COMMANDS | PROMPT_COMMANDS | frozenset({
    "connected_limits_command",
    "connected_session_send_command",
    "connected_session_new_command",
    "connected_session_stop_command",
    "connected_session_steer_command",
    "connected_session_answer_command",
    "connected_session_compact_command",
    "connected_session_goal_command",
    "connected_session_git_action_command",
    "connected_folder_clone_command",
    "connected_folder_worktree_command",
    "connected_app_sign_in_command",
    "connected_app_sign_in_code_command",
})

HEARTBEAT_SECONDS = 15.0
MAX_POLL_SECONDS = 20.0


def _int(payload: dict[str, Any], key: str, default: int | None = None) -> int | None:
    from .broker import ConnectedError

    value = payload.get(key)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConnectedError("invalid_request", f"{key} must be a number.") from exc


def _check_state_root(backend: Any, payload: dict[str, Any]) -> None:
    from .broker import ConnectedError

    expected = payload.get("_expectedStateRoot")
    if not expected:
        return
    try:
        same = Path(str(expected)).samefile(backend.root)
    except OSError:
        same = False
    if not same:
        raise ConnectedError("wrong_state_root", "The host service is using a different Neyvia state folder.", 409)


def handle_connected_command(backend: Any, command: str, payload: Any) -> Any:
    """Run one connected-sessions command; raises ``ConnectedError`` for a refusal."""
    from .broker import ConnectedError, broker_for
    from .workspace import WorkspaceError, file_diff, git_action, workspace_state

    _proofs.check_connected_allowlist()
    body = payload if isinstance(payload, dict) else {}
    _check_state_root(backend, body)
    if command in FEEDBACK_COMMANDS:
        from ..task_feedback import handle_command
        return handle_command(backend, command, body)
    if command in PROMPT_COMMANDS:
        from ..prompt_amplifier import handle_command
        return handle_command(backend, command, body)
    if command == "connected_limits_command":
        from .live_limits import service_for
        for key in ("refresh", "wait"):
            if key in body and type(body[key]) is not bool:
                raise ConnectedError("invalid_request", f"{key} must be boolean")
        live = service_for(backend.root)
        return live.refresh(wait=body.get("wait", False)) if body.get("refresh") else live.snapshot()
    if command in CONDUCTOR_COMMANDS:
        from ..neyvia_conductor import handle_command
        return handle_command(backend, command, body)
    if command in {"connected_session_answer_command", "connected_session_stop_command"}:
        from ..neyvia_conductor import control_turn
        try:
            forwarded = control_turn(backend.root, command, body)
        except ValueError as exc:
            raise ConnectedError("invalid_request", str(exc), 400) from exc
        if forwarded is not None:
            return forwarded
    broker = broker_for(backend.root, backend)
    text = lambda key: str(body.get(key) or "")  # noqa: E731
    try:
        if command == "connected_sessions_list_command":
            return broker.list_sessions(
                query=text("query"), app=text("app"), category=text("category"), include_archived=bool(body.get("includeArchived")),
                include_harness=bool(body.get("includeHarness")), limit=_int(body, "limit", 100), offset=_int(body, "offset", 0))
        if command == "connected_session_read_command":
            return broker.read(text("id"), cursor=body.get("cursor"), before_seq=body.get("beforeSeq"),
                               limit=_int(body, "limit", 200))
        if command == "connected_session_tool_output_command":
            return broker.tool_output(text("id"), body.get("itemId"))
        if command == "connected_session_media_command":
            import base64

            data, mime, name = broker.media(text("id"), text("mediaRef"))
            if len(data) > MAX_MEDIA_COMMAND_BYTES:
                raise ConnectedError("media_too_large", "That image is too large to show here.", 413)
            return {"mime": mime, "name": name, "data": base64.b64encode(data).decode("ascii")}
        if command == "connected_session_send_command":
            return broker.send(text("id"), body.get("message"), body.get("requestId"), body.get("options"), memory_owner=body.get('_memoryUser'))
        if command == "connected_session_new_command":
            return broker.new(body.get("app"), body.get("cwd"), body.get("message"), body.get("requestId"), body.get("options"), memory_owner=body.get('_memoryUser'))
        if command == "connected_session_stop_command":
            return broker.stop(text("runId"))
        if command == "connected_session_steer_command":
            return broker.steer(text("runId"), body.get("message"), body.get("options"))
        if command == "connected_session_answer_command":
            return broker.answer(text("runId"), text("requestId"), body.get("response"))
        if command == "connected_session_compact_command":
            return broker.compact(text("id"), body.get("options"), body.get("instructions"))
        if command == "connected_session_goal_command":
            return broker.goal(text("id"), body.get("action") or "get", body.get("text"))
        if command == "connected_provider_options_command":
            return broker.provider_options(body.get("app"), body.get("id"))
        if command == "connected_app_auth_command":
            return broker.app_auth(body.get("app"))
        if command == "connected_app_sign_in_command":
            return broker.app_auth(body.get("app"), sign_in=True)
        if command == "connected_app_sign_in_code_command":
            return broker.app_sign_in_code(body.get("app"), body.get("code"))
        if command == "connected_agents_dashboard_command":
            from ..neyvia_workspace_tools import workspace_for
            from .dashboard import build
            return build(broker, service=workspace_for(backend.root, backend), limit=_int(body, "limit", 16), offset=_int(body, "offset", 0))
        if command == "connected_session_mark_seen_command":
            return broker.mark_seen(text("id"), body.get("seq"))
        if command == "connected_events_poll_command":
            try:
                wait = min(MAX_POLL_SECONDS, max(0.0, float(body.get("waitSeconds") or 0)))
            except (TypeError, ValueError) as exc:
                raise ConnectedError("invalid_request", "waitSeconds must be a number.") from exc
            cursor = _int(body, "cursor")
            with broker.subscription():
                events, head, resync = broker.wait_events(cursor, wait)
            result = {"events": events, "cursor": head, **({"resync": True} if resync else {})}
            _proofs.check_poll(body, wait, result, (events, head, resync))
            return result
        if command == "connected_session_workspace_command":
            return workspace_state(broker.session_cwd(text("id")))
        if command == "connected_session_file_diff_command":
            return file_diff(broker.session_cwd(text("id")), text("path"))
        if command == "connected_session_git_action_command":
            return git_action(broker.session_cwd(text("id")), text("action"), message=body.get("message"),
                              title=body.get("title"), body=body.get("body"), confirm=body.get("confirm"))
        if command in {"connected_folders_command", "connected_github_repos_command",
                       "connected_folder_clone_command", "connected_folder_worktree_command"}:
            return _folder_command(command, body, state_root=backend.root)
    except WorkspaceError as exc:
        raise ConnectedError(exc.code, exc.message, exc.status) from exc
    raise ConnectedError("unknown_command", f"Unknown connected sessions command: {command}", 404)


def _folder_command(command: str, body: dict[str, Any], *, state_root: Path | None = None) -> Any:
    from . import folders
    from .broker import ConnectedError

    try:
        if command == "connected_folders_command":
            recent = [
                {"path": str(row.get("path")), "name": str(row.get("name") or ""), "branch": row.get("branch")}
                for row in (body.get("recent") if isinstance(body.get("recent"), list) else [])[:20]
                if isinstance(row, dict) and isinstance(row.get("path"), str)
            ]
            return folders.candidates(recent=recent, query=str(body.get("query") or ""))
        if command == "connected_github_repos_command":
            return folders.github_candidates(query=str(body.get("query") or ""))
        if command == "connected_folder_clone_command":
            return folders.clone(str(body.get("repo") or ""), confirm=body.get("confirm") is True)
        if body.get("jobId"):
            if state_root is None:
                raise ValueError("The worktree service state folder is unavailable.")
            from .folder_jobs import status
            return status(state_root, str(body["jobId"]))
        return folders.create_worktree(str(body.get("path") or ""), str(body.get("branch") or ""),
            confirm=body.get("confirm") is True, state_root=state_root)
    except ValueError as exc:
        raise ConnectedError("invalid_request", str(exc), 400) from exc


# -- HTTP ---------------------------------------------------------------------------------

def _private_memory_event(event: dict[str, Any], bindings: set[str]) -> bool:
    # A new provider turn can emit before its final session ID is assigned.
    return event.get('sessionId') in bindings or 'pending:' + str(event.get('runId') or '') in bindings


def respond_connected_command(handler: Any, backend: Any, command: str, payload: Any) -> None:
    """Answer ``POST /api/backend`` for a connected command; refusals carry ``code``."""
    from ..web_backend import _json_response
    from .broker import ConnectedError
    from ..cue_memory import private_sessions
    account = str((backend.authenticated_session(handler) or {}).get('username') or '')
    try:
        private = private_sessions(backend.root, account)
    except Exception:  # A missing ownership fence must not expose private chats.
        _json_response(handler, 503, {'ok': False, 'code': 'memory_store_unavailable',
            'error': 'Private chat ownership is temporarily unavailable.'})
        return
    target = (payload or {}).get('id') if isinstance(payload, dict) else None
    if isinstance(target, str) and target in private:
        _json_response(handler, 403, {'ok': False, 'code': 'memory_owner_required',
            'error': 'This chat received another account’s private memory.'})
        return

    if command in OWNER_COMMANDS:
        session = backend.authenticated_session(handler) or {}
        owner = str(backend.username or "").casefold()
        account = str(session.get("username") or "").casefold()
        if account != owner or command in FEEDBACK_COMMANDS and (not owner or not account):
            _json_response(handler, 403, {"ok": False, "code": "owner_required",
                                          "error": "Only the PC owner's Neyvia account can run agents or change files on this PC.",
                                          "message": "Only the PC owner's Neyvia account can run agents or change files on this PC."})
            return
    if command in {'connected_session_new_command', 'connected_session_send_command'}:
        payload = {**(payload if isinstance(payload, dict) else {}),
                   '_memoryUser': str((backend.authenticated_session(handler) or {}).get('username') or '')}
    result, caught = None, None
    try:
        result = backend.dispatch(command, payload)
        if command == 'connected_events_poll_command':
            private = private_sessions(backend.root, account)
            result['events'] = [event for event in result['events'] if not _private_memory_event(event, private)]
        elif command in {'connected_sessions_list_command', 'connected_agents_dashboard_command'}:
            private = private_sessions(backend.root, account)
            result['sessions'] = [row for row in result['sessions'] if row.get('id') not in private]
    except ConnectedError as exc:
        caught = exc
        status, body = exc.status, exc.public()
    except Exception as exc:  # noqa: BLE001 - never leak a traceback to a client
        log.exception("connected command %s failed", command)
        status, body = 500, {"ok": False, "code": "internal_error", "error": str(exc)[:300], "message": str(exc)[:300]}
    else:
        status, body = 200, {"ok": True, "data": result}
    _proofs.check_http_response(status, body, result=result, error=caught)
    try:
        _json_response(handler, status, body)
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
        return


def serve_connected_get(backend: Any, handler: Any, parsed: Any) -> None:
    """GET routes under ``/api/connected/``: the event stream and attachment media."""
    from ..web_backend import PRODUCT_NAME, _json_response

    if not backend.is_authenticated(handler):
        _json_response(handler, 401, {"ok": False, "error": f"{PRODUCT_NAME} login is required.", "loginRequired": True})
        return
    if parsed.path == '/api/connected/media':
        from ..cue_memory import private_sessions
        user = str((backend.authenticated_session(handler) or {}).get('username') or '')
        target = (parse_qs(parsed.query).get('session') or [''])[0]
        if target in private_sessions(backend.root, user):
            _json_response(handler, 403, {'ok': False, 'code': 'memory_owner_required', 'error': 'This chat received private memory for another account.'})
            return
    if parsed.path == "/api/connected/events":
        _serve_events(backend, handler, parsed)
    elif parsed.path == "/api/connected/media":
        _serve_media(backend, handler, parsed)
    else:
        _json_response(handler, 404, {"ok": False, "error": "Unknown API route"})


def _client_gone(handler: Any) -> bool:
    """True when the peer has closed its side of a plain socket."""
    try:
        sock = handler.connection
        if isinstance(sock, ssl.SSLSocket):
            return False
        readable, _, _ = select.select([sock], [], [], 0)
        return bool(readable) and sock.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):
        return True


def _serve_events(backend: Any, handler: Any, parsed: Any) -> None:
    from ..web_backend import _apply_security_headers, _json_response, _send_cors_headers
    from .broker import ConnectedError, broker_for

    broker = broker_for(backend.root, backend)
    raw = (handler.headers.get("Last-Event-ID") or "").strip() or (parse_qs(parsed.query).get("cursor") or [""])[0]
    try:
        cursor: int | None = int(raw) if str(raw).strip() else None
    except ValueError:
        cursor = None

    def write(text: str) -> None:
        handler.wfile.write(text.encode("utf-8"))
        handler.wfile.flush()

    def send(event: dict[str, Any]) -> None:
        from ..cue_memory import private_sessions
        user = str((backend.authenticated_session(handler) or {}).get('username') or '')
        if _private_memory_event(event, private_sessions(backend.root, user)):
            return
        frame = f"id: {event['cursor']}\ndata: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
        _proofs.check_sse(event, frame)
        write(frame)

    try:
        with broker.subscription():
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
            handler.send_header("X-Accel-Buffering", "no")
            _apply_security_headers(handler, cache_control="no-cache, no-transform")
            _send_cors_headers(handler)
            handler.end_headers()
            events, head, resync = broker.events_since(cursor)
            write(": connected\nretry: 3000\n\n")
            if resync:
                send({"type": "resync", "cursor": head})
            cursor = head if cursor is None or resync else cursor
            last_write = time.monotonic()
            while not broker.closed:
                events, head, resync = broker.wait_events(cursor, min(1.0, HEARTBEAT_SECONDS))
                if resync:
                    send({"type": "resync", "cursor": head})
                    cursor = head
                for event in events:
                    send(event)
                    cursor = event["cursor"]
                now = time.monotonic()
                if events or resync:
                    last_write = now
                elif now - last_write >= HEARTBEAT_SECONDS:
                    write(": heartbeat\n\n")
                    last_write = now
                if _client_gone(handler):
                    break
    except ConnectedError as exc:
        _json_response(handler, exc.status, exc.public())
    except (OSError, ssl.SSLError):
        return  # the client went away


def _serve_media(backend: Any, handler: Any, parsed: Any) -> None:
    from urllib.parse import quote

    from ..connected_chat_media import TYPES
    from ..web_backend import _json_response, _write_response_body
    from .broker import ConnectedError, broker_for

    query = parse_qs(parsed.query)
    try:
        body, mime, name = broker_for(backend.root, backend).media((query.get("session") or [""])[0], (query.get("media") or [""])[0])
    except ConnectedError as exc:
        _json_response(handler, exc.status, exc.public())
        return
    safe = mime if mime in set(TYPES.values()) else "application/octet-stream"
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", safe)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Cache-Control", "private, no-store")
        handler.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        if not safe.startswith("image/"):
            handler.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(str(name), safe=""))
        handler.end_headers()
        _write_response_body(handler, body)
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
        return
