"""Connected chat adapter for local Claude Code sessions.

Claude Desktop/web conversations are cloud-backed and have no supported local
resume API. This adapter intentionally targets only sessions indexed by
``external_chat_inventory`` (``app == 'claude-code'``), and delegates resume
to the official Claude Code CLI so the user's existing CLI login is used.

The adapter never reads/writes Claude's transcript files itself. Sends are
serialized by session across Neyvia processes, and are refused if another
Claude Code CLI process advertises that same session as active. The Desktop
application is a different product/store and is not treated as an owner of a
Claude Code transcript.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import queue
import time
from pathlib import Path
from typing import Any, Callable

from .external_chat_inventory import _discover, _host, _paths


class ConnectedClaudeChatError(RuntimeError):
    """A safe, user-presentable connected chat failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def capabilities() -> dict[str, Any]:
    """Report the exact supported Claude surface and its boundary."""
    cli = _cli_path()
    return {
        "provider": "claude-code",
        "available": bool(cli),
        "cliPath": str(cli) if cli else "",
        "capabilities": {"list": True, "read": True, "continue": bool(cli), "images": "inherited-session-context-only"},
        "unsupported": {
            "claudeDesktopChats": "Claude Desktop conversations are not Claude Code local sessions and have no supported local resume API.",
            "claudeWebChats": "Claude.ai chats are cloud-backed; this adapter does not access account APIs or browser state.",
            "newImageUploads": "The CLI stream bridge accepts text prompts only; existing image context remains with the resumed native session where Claude Code retains it.",
        },
    }


def _cli_path() -> Path | None:
    command = shutil.which("claude")
    if not command:
        return None
    path = Path(command)
    # npm's Windows PowerShell/CMD shims launch this official executable.
    if path.suffix.casefold() in {".cmd", ".ps1", ".bat"}:
        candidates = [path.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None
    return path


def _resolve_session(identity: str) -> tuple[str, str]:
    if not isinstance(identity, str) or not identity.startswith("external:claude-code:"):
        raise ConnectedClaudeChatError("unsupported_chat", "Only local Claude Code sessions can be continued. Claude Desktop and Claude.ai chats are not supported by this adapter.")
    try:
        locations = _paths(None)
        row = next((item for item in _discover("claude-code", locations, _host()) if item["id"] == identity), None)
    except (OSError, ValueError) as exc:
        raise ConnectedClaudeChatError("inventory_unavailable", "Claude Code session inventory is unavailable on this device.") from exc
    if row is None:
        raise ConnectedClaudeChatError("session_unavailable", "This Claude Code session is not available on this device.")
    return str(row["_sessionId"]), str(row["_sourcePath"])


def _session_is_running(session_id: str) -> bool:
    """Fail closed for a matching Claude Code CLI process, not Claude Desktop."""
    try:
        import psutil
    except ImportError:
        raise ConnectedClaudeChatError("activity_check_unavailable", "Cannot safely check whether this Claude Code session is already active; install the runtime process-inspection dependency or continue it in Claude Code.")
    cli = _cli_path()
    if cli is None:
        return False
    target = os.path.normcase(str(cli.resolve()))
    # Claude Code names project transcript directories from their CWD. If any
    # CLI process is live in that project, it may own a session resumed via the
    # in-app /resume picker (which is not visible in its original argv).
    session_path = next((row["_sourcePath"] for row in _discover("claude-code", _paths(None), _host()) if row["_sessionId"] == session_id), "")
    project_key = Path(session_path).parent.name if session_path else ""
    for process in psutil.process_iter(("exe", "cmdline")):
        try:
            info = process.info
            executable = os.path.normcase(str(info.get("exe") or ""))
            if executable != target:
                continue
            argv = [str(value) for value in (info.get("cmdline") or [])]
            try:
                environment = process.environ()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                environment = {}
            if environment.get("CLAUDE_CODE_SESSION_ID") == session_id:
                return True
            for flag in ("--resume", "-r"):
                for index, value in enumerate(argv[:-1]):
                    if value == flag and argv[index + 1] == session_id:
                        return True
            if project_key:
                try:
                    cwd = process.cwd()
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    cwd = ""
                project_from_cwd = cwd.replace(":", "--").replace("\\", "-").replace("/", "-")
                if os.path.normcase(project_from_cwd) == os.path.normcase(project_key):
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False


class _SessionLock:
    """Cross-process exclusive lease used by Neyvia sends for one session."""
    def __init__(self, session_id: str):
        key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        self.path = Path(tempfile.gettempdir()) / "neyvia-claude-session-locks" / f"{key}.lock"
        self.handle: Any = None

    def __enter__(self) -> "_SessionLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                if self.handle.read(1) == b"":
                    self.handle.write(b"0")
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.handle.close()
            self.handle = None
            raise ConnectedClaudeChatError("session_busy", "A Neyvia request is already continuing this Claude Code session.") from exc
        return self

    def __exit__(self, *_: Any) -> None:
        if self.handle is None:
            return
        if os.name == "nt":
            import msvcrt
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


def _request_line(message: str) -> bytes:
    return (json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": message}]}}, ensure_ascii=False) + "\n").encode("utf-8")


def send_message(
    identity: str,
    message: str,
    *,
    request_id: str,
    on_event: Callable[[dict[str, Any]], None],
    timeout_seconds: float = 600,
) -> dict[str, Any]:
    """Continue an indexed Claude Code session using official CLI stream IO.

    ``on_event`` receives ``message_start``, ``assistant_delta``,
    ``assistant_message``, ``tool_activity`` and ``result`` events. The caller
    owns durable request idempotency and status storage.
    """
    if not isinstance(message, str) or not message.strip():
        raise ConnectedClaudeChatError("empty_message", "Enter a message to continue this chat.")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ConnectedClaudeChatError("request_id_required", "A stable request ID is required for this send.")
    session_id, _ = _resolve_session(identity)
    cli = _cli_path()
    if cli is None:
        raise ConnectedClaudeChatError("cli_unavailable", "Claude Code CLI is not installed or could not be resolved through its official launcher.")
    with _SessionLock(session_id):
        if _session_is_running(session_id):
            raise ConnectedClaudeChatError("session_active", "This Claude Code session is already active in another CLI process. Close or finish that session before continuing it through Neyvia.")
        argv = [str(cli), "--print", "--resume", session_id, "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
        # Recheck immediately before spawning; the session lock prevents other
        # Neyvia callers, while this narrows the race with a native CLI launch.
        if _session_is_running(session_id):
            raise ConnectedClaudeChatError("session_active", "This Claude Code session became active in another CLI process. Close or finish that session before continuing it through Neyvia.")
        on_event({"type": "message_start", "requestId": request_id, "chatId": identity})
        try:
            from .subprocess_utils import hidden_windows_subprocess_kwargs
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, **hidden_windows_subprocess_kwargs())
        except OSError as exc:
            raise ConnectedClaudeChatError("cli_start_failed", "Claude Code could not be started. Check the CLI installation and account sign-in on the host device.") from exc
        events: queue.Queue[str | None] = queue.Queue()

        def pump_stdout() -> None:
            assert process.stdout is not None
            for raw_line in iter(process.stdout.readline, b""):
                events.put(raw_line.decode("utf-8", errors="replace"))
            events.put(None)

        def drain_stderr() -> None:
            assert process.stderr is not None
            for _ in iter(process.stderr.readline, b""):
                pass

        stdout_thread = threading.Thread(target=pump_stdout, name="claude-chat-stdout", daemon=True)
        stderr_thread = threading.Thread(target=drain_stderr, name="claude-chat-stderr", daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        assert process.stdin is not None
        process.stdin.write(_request_line(message))
        process.stdin.close()
        deadline = time.monotonic() + max(1.0, min(float(timeout_seconds), 1800.0))
        result_text = ""
        result_failed = False
        ended = False
        try:
            while not ended:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout_seconds)
                try:
                    line = events.get(timeout=min(remaining, 0.25))
                except queue.Empty:
                    if process.poll() is not None and not stdout_thread.is_alive():
                        break
                    continue
                if line is None:
                    ended = True
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = str(event.get("type") or "")
                if kind == "stream_event":
                    inner = event.get("event") if isinstance(event.get("event"), dict) else {}
                    delta = inner.get("delta") if isinstance(inner.get("delta"), dict) else {}
                    if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                        on_event({"type": "assistant_delta", "requestId": request_id, "text": delta["text"]})
                    elif inner.get("type") in {"content_block_start", "content_block_stop"}:
                        on_event({"type": "tool_activity", "requestId": request_id})
                elif kind == "assistant":
                    on_event({"type": "assistant_message", "requestId": request_id, "message": event.get("message", {})})
                elif kind == "result":
                    result_text = str(event.get("result") or "")
                    result_failed = bool(event.get("is_error"))
                    on_event({"type": "result", "requestId": request_id, "text": result_text, "isError": bool(event.get("is_error"))})
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise ConnectedClaudeChatError("timeout", "Claude Code did not finish before the connected chat timeout; check the native session before retrying.") from exc
        finally:
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
        if process.returncode != 0 or result_failed:
            # Do not relay arbitrary CLI stderr, which may contain prompt data or sensitive paths.
            raise ConnectedClaudeChatError("cli_failed", "Claude Code could not continue this session. Check account sign-in and the session in Claude Code on the host device.")
        if not result_text:
            raise ConnectedClaudeChatError("empty_result", "Claude Code ended without a final response; inspect the native session before retrying.")
        return {"requestId": request_id, "chatId": identity, "sessionId": session_id, "text": result_text, "returnCode": process.returncode}
