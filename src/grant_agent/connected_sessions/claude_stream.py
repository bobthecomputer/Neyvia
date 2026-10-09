"""One Claude Code turn: a persistent stream-json CLI process, its control protocol and the live events.

The official, unmodified ``claude`` CLI is started once per run with stdin kept open. It writes
stream-json to stdout and, whenever a tool needs a decision, a ``control_request`` (``can_use_tool``)
that Neyvia answers with a ``control_response`` once the person chose. Stop is the ``interrupt``
control request, backed by a hard process-tree kill after a grace period.

Verified against Claude Code 2.1.282 (see docs/NEYVIA_CONNECTED_SESSIONS_CONTRACT.md notes in the
adapter report): ``--permission-prompt-tool stdio`` is what makes the CLI ask the host, and it is also
what exposes the AskUserQuestion tool in print mode.
"""
from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..subprocess_utils import hidden_windows_subprocess_kwargs
from ..proofs_a_providers import checked, check_event, check_process
from .claude_items import (
    COMMAND_LIMIT, QUESTION_TOOL, answers_by_id, apply_tool_result, attachment_dict, bound_text, classify_user_text,
    collapse, context_used, flatten_result_content, image_token, int_or_none, now_iso, question_data, tool_category,
    tool_data, tool_files, tool_title,
)
from .claude_transcript import AgentAggregate, apply_agent_result, new_agent_hints
from .model import ContextUsage, Emit, Item, TurnOptions
from .transparency import normalize_item, reasoning_data
from .plan_limits import record_claude as record_claude_limit

IDLE_TIMEOUT_SECONDS = 30 * 60
PENDING_TIMEOUT_SECONDS = 24 * 60 * 60
INTERRUPT_GRACE_SECONDS = 10.0
SHUTDOWN_GRACE_SECONDS = 10.0
CONTEXT_PROBE_SECONDS = 3.0
# Session-identifying variables an outer Claude Code (desktop app, terminal session) exports. A child that
# inherited them could believe it belongs to that session, so a Neyvia-owned turn starts without them.
_HOST_SESSION_ENV = (
    "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_DESKTOP_APP_VERSION",
    "CLAUDE_AGENT_SDK_VERSION", "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH",
)
_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,127}")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
# Slash commands that would leave the session (a new id) instead of continuing it.
_SESSION_LEAVING_COMMANDS = ("/clear", "/reset", "/new", "/branch", "/fork", "/resume")

_ERROR_TEXT = {
    "authentication_failed": ("auth_failed", "Claude Code is not signed in, or its sign-in was rejected, on this PC. Sign in with Claude Code there, then try again."),
    "oauth_org_not_allowed": ("auth_failed", "This Claude sign-in is not allowed for Claude Code."),
    "account_on_hold": ("account_on_hold", "This Claude account is on hold. Check the account in Claude."),
    "billing_error": ("billing", "Claude Code reported a billing problem. Check the Agent SDK credits for this account."),
    "rate_limit": ("rate_limited", "Claude is rate limited right now. Try again in a few minutes."),
    "overloaded": ("overloaded", "Claude is overloaded right now. Try again in a few minutes."),
    "invalid_request": ("invalid_request", "Claude rejected the request."),
    "model_not_found": ("model_not_found", "The chosen model is not available for this account."),
    "server_error": ("server_error", "Claude had a server error. Try again."),
    "max_output_tokens": ("max_output_tokens", "The reply hit the output limit."),
    "cloud_credential_error": ("auth_failed", "The cloud credentials for this model were rejected."),
}
_HTTP_ERRORS = {401: "authentication_failed", 403: "authentication_failed", 402: "billing_error", 429: "rate_limit", 529: "overloaded", 503: "overloaded", 500: "server_error"}


def declined_message(reason: str) -> str:
    """What Claude is told when the person refuses a tool call: the CLI's own phrasing, so the model reacts as it does natively
    and transcripts of the refusal are recognizable (``claude_items.apply_tool_result`` flags it ``declined``)."""
    base = "The user doesn't want to proceed with this tool use. The tool use was rejected."
    return f"{base} To tell you how to proceed, the user said:\n{reason}" if reason else base


class ClaudeSessionError(RuntimeError):
    """A safe, user-presentable failure (the broker turns ``code`` into its error responses)."""

    def __init__(self, code: str, message: str, *, owner: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.owner = owner

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.owner:
            out["owner"] = self.owner
        return out


# --------------------------------------------------------------------------- process


@checked("providers.claude.environment")
def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The parent environment minus host-session identity; credentials are never added, read or logged."""
    env = {key: value for key, value in os.environ.items() if key not in _HOST_SESSION_ENV}
    env.update(extra or {})
    # Maximum exposed thinking is a per-child choice; never rewrite the user's settings.
    env.pop("CLAUDE_CODE_DISABLE_THINKING", None)
    if env.get("MAX_THINKING_TOKENS") == "0":
        env.pop("MAX_THINKING_TOKENS")
    return env


def cli_prefix(cli: str | Path | list[str] | tuple[str, ...]) -> list[str]:
    """The command that starts the CLI: one executable, or a list such as ``[python, fake_cli.py]`` in tests."""
    return [str(part) for part in cli] if isinstance(cli, (list, tuple)) else [str(cli)]


@checked("providers.claude.argv")
def build_argv(cli: str | Path | list[str], session_id: str | None, options: TurnOptions, extra_args: list[str] | None = None) -> list[str]:
    """``claude -p --resume <id> --input-format stream-json ...``; ``--resume`` is omitted for a new session."""
    argv = [*cli_prefix(cli), "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--permission-prompt-tool", "stdio", "--replay-user-messages",
            "--thinking-display", "summarized",
            "--settings", '{"alwaysThinkingEnabled":true}']
    if session_id:
        argv += ["--resume", session_id]
    elif options.fork_from:
        argv += ["--resume", options.fork_from, "--fork-session"]
    if options.model:
        if not _MODEL_RE.fullmatch(options.model):
            raise ClaudeSessionError("invalid_option", "That model name is not valid.")
        argv += ["--model", options.model]
    if options.effort:
        if not _TOKEN_RE.fullmatch(options.effort):
            raise ClaudeSessionError("invalid_option", "That effort level is not valid.")
        argv += ["--effort", options.effort]
    if options.permission_mode:
        mode = "manual" if options.permission_mode == "default" else options.permission_mode
        if not _TOKEN_RE.fullmatch(mode):
            raise ClaudeSessionError("invalid_option", "That permission mode is not valid.")
        argv += ["--permission-mode", mode]
        if mode == "bypassPermissions":
            argv += ["--allow-dangerously-skip-permissions"]
    return argv + list(extra_args or [])


def kill_process_tree(process: subprocess.Popen) -> None:
    """Stop the process and everything it started (shell commands, MCP servers)."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10,
                           check=False, **hidden_windows_subprocess_kwargs())
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def start_process(argv: list[str], cwd: str, env: dict[str, str]) -> subprocess.Popen:
    options = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
               "shell": False, "start_new_session": os.name != "nt", **hidden_windows_subprocess_kwargs(new_process_group=True)}
    check_process(options)
    return subprocess.Popen(argv, cwd=cwd, env=env, **options)


# --------------------------------------------------------------------------- run


def approval_data(request_id: str, tool: str, tool_input: dict[str, Any], request: dict[str, Any], tool_use_id: str | None,
                  cwd: str | None) -> dict[str, Any]:
    """The approval card for one tool call (print mode's ``can_use_tool`` and the terminal route's hook)."""
    category = tool_category(tool)
    title = tool_title(tool, tool_input)
    verb = {"command": "Run", "edit": "Edit", "read": "Read", "web": "Fetch", "mcp": "Use", "agent": "Start agent"}.get(category, "Use")
    detail = collapse(request.get("description") or "", 1000)
    if request.get("blocked_path"):
        detail = (detail + " " if detail else "") + f"Path: {request['blocked_path']}"
    if not detail:
        detail = collapse(json.dumps(tool_input, ensure_ascii=False, default=str), 1000)
    data: dict[str, Any] = {
        "requestId": request_id, "title": f"{verb} {title}?" if category != "other" else f"Allow {request.get('display_name') or tool}?",
        "detail": detail, "command": None, "cwd": cwd, "choices": ["approve", "deny"], "decision": None,
        "tool": tool, "category": category, "toolUseId": tool_use_id, "files": tool_files(tool, tool_input),
    }
    if category == "command":
        data["command"], _ = bound_text(str(tool_input.get("command") or ""), COMMAND_LIMIT)
    if request.get("blocked_path"):
        data["blockedPath"] = str(request["blocked_path"])
    return data


@dataclass
class Pending:
    request_id: str
    kind: str  # "approval" | "question"
    tool_name: str
    tool_use_id: str | None
    tool_input: dict[str, Any]
    item_id: str
    created: float = field(default_factory=time.monotonic)


class ClaudeRun:
    """Owns one CLI process for one turn; every method except ``run`` is safe to call from another thread."""

    def __init__(self, *, cli: str | Path | list[str], run_id: str, session_id: str | None, message: str, options: TurnOptions,
                 cwd: str, emit: Emit, start_offset: int = 0, extra_args: list[str] | None = None,
                 extra_env: dict[str, str] | None = None, idle_timeout: float = IDLE_TIMEOUT_SECONDS,
                 pending_timeout: float = PENDING_TIMEOUT_SECONDS, interrupt_grace: float = INTERRUPT_GRACE_SECONDS,
                 shutdown_grace: float = SHUTDOWN_GRACE_SECONDS, context_probe: bool = True,
                 windows: dict[str, int] | None = None, on_models: Callable[[list], None] | None = None,
                 on_session: Callable[[str, bool], None] | None = None,
                 keep_media: Callable[[str, bytes, str], None] | None = None, state_root: Path | None = None):
        self.cli, self.run_id, self.cwd, self.emit = cli, run_id, cwd, emit
        self.state_root = state_root
        self.requested_id = session_id
        self.session_id: str | None = session_id
        self.message, self.options = message, options
        self.extra_args, self.extra_env = extra_args or [], extra_env or {}
        self.idle_timeout, self.pending_timeout = idle_timeout, pending_timeout
        self.interrupt_grace, self.shutdown_grace = interrupt_grace, shutdown_grace
        self.context_probe = context_probe
        self.windows = windows if windows is not None else {}
        self._on_models, self._on_session, self._keep_media = on_models, on_session, keep_media
        self.state = "queued"
        self.pid: int | None = None
        self.process: subprocess.Popen | None = None
        self.stderr_bytes = 0
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._inbox: queue.Queue = queue.Queue()
        self._pending: dict[str, Pending] = {}
        self._items: dict[str, Item] = {}
        self._seq_base = start_offset << 6
        self._seq = 0
        self._notice_n = 0
        # streaming state
        self._msg_id: str | None = None
        self._model: str | None = None
        self._blocks: dict[int, dict[str, Any]] = {}
        self._streamed: set[str] = set()
        self._tool_ready: set[str] = set()
        self._announced = False
        self._user_item_id = ""
        self._user_item_data: dict[str, Any] = {}
        self._nonstream_index: dict[str, int] = {}
        self._compaction_item: Item | None = None
        self._retry_item: Item | None = None
        self._agents: dict[str, dict[str, Any]] = {}
        self._agent_emit_at: dict[str, float] = {}
        self._tool_started: dict[str, str] = {}
        # bookkeeping
        self._last_output = time.monotonic()
        self._interrupt_requested = False
        self._interrupt_deadline: float | None = None
        self._interrupt_reason: str | None = None
        self._eof = False
        self._done = False
        self._final: tuple[str, str | None, str | None] | None = None
        self._result: dict[str, Any] | None = None
        self._last_usage_used: int | None = None
        self._error_category: str | None = None
        self._ctx_request: str | None = None
        self._ctx_response: dict | None = None
        self.context = ContextUsage()
        # Steering: messages sent while the turn runs, and how many the CLI has taken in (its replays).
        self._steers_sent = 0
        self._replays_seen = 0

    # ---- public (any thread)

    def interrupt(self, reason: str | None = None) -> None:
        """Ask the CLI to stop the turn; a hard kill follows after ``interrupt_grace`` seconds."""
        with self._lock:
            if self._done or self._interrupt_requested:
                return
            self._interrupt_requested = True
            self._interrupt_reason = reason
            self._interrupt_deadline = time.monotonic() + self.interrupt_grace
            pending = list(self._pending.values())
            self._pending.clear()
        for request in pending:  # a turn blocked on a prompt ends when the prompt is refused with interrupt
            self._respond(request.request_id, {"behavior": "deny", "message": "The turn was stopped.", "interrupt": True})
            self._inbox.put(("resolved", request.request_id, "cancel", {}))
        self._send({"type": "control_request", "request_id": "neyvia_int_" + uuid.uuid4().hex[:8], "request": {"subtype": "interrupt"}})

    def steer(self, message: str, images: list[dict[str, Any]] | None = None) -> None:
        """Add a message to the running turn. Claude Code takes it in at its next step (after the
        current tool call) and carries on with it; if the turn was already finishing, it runs it next."""
        text = message if isinstance(message, str) else ""
        if not text.strip() and not images:
            raise ClaudeSessionError("empty_message", "Enter a message to send.")
        with self._lock:
            if self._done or self._interrupt_requested or self.process is None or self.process.poll() is not None:
                raise ClaudeSessionError("run_not_active", "This turn has finished. Send your message as a new one.")
            self._steers_sent += 1
            self._last_output = time.monotonic()
        user_id, content, data = self._user_payload(text, images or [])
        self._add_item(user_id, "user", {**data, "steer": True})
        if not self._send({"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None, "uuid": user_id}):
            with self._lock:
                self._steers_sent -= 1
            raise ClaudeSessionError("run_not_active", "Claude Code isn't taking messages for this turn any more.")

    def answer(self, request_id: str, response: dict[str, Any]) -> None:
        """Resolve one pending permission request or question exactly once."""
        decision = str((response or {}).get("decision") or "")
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                raise ClaudeSessionError("request_not_pending", "This request is no longer waiting. Refresh the session and review its current state.")
            reply, answers = self._build_reply(pending, decision, response or {})
            self._pending.pop(request_id)
            self._last_output = time.monotonic()  # the person's answer is activity: the idle clock restarts
        self._respond(request_id, reply)
        self._inbox.put(("resolved", request_id, decision, answers))

    # ---- reply construction

    @staticmethod
    @checked("providers.claude.reply")
    def _build_reply(pending: Pending, decision: str, response: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        reason = collapse(response.get("message") or response.get("reason") or "", 500)
        if decision == "cancel":
            return {"behavior": "deny", "message": declined_message(reason or "The turn was cancelled."), "interrupt": True}, {}
        if decision == "deny":
            return {"behavior": "deny", "message": declined_message(reason)}, {}
        if decision != "approve":
            raise ClaudeSessionError("invalid_decision", "Choose approve, deny or cancel.")
        if pending.kind == "approval":
            updated = response.get("updatedInput") if isinstance(response.get("updatedInput"), dict) else pending.tool_input
            return {"behavior": "allow", "updatedInput": updated}, {}
        questions = pending.tool_input.get("questions") if isinstance(pending.tool_input.get("questions"), list) else []
        given = response.get("answers") if isinstance(response.get("answers"), dict) else {}
        answers: dict[str, str] = {}
        by_question: dict[str, str] = {}
        for index, question in enumerate(questions):
            value = given.get(f"q{index}")
            if isinstance(value, list):
                value = ", ".join(str(part) for part in value)
            if not isinstance(value, str) or not value.strip():
                raise ClaudeSessionError("answer_required", "Answer every question before continuing.")
            answers[f"q{index}"] = value.strip()[:20_000]
            by_question[str(question.get("question") or "")] = answers[f"q{index}"]
        updated = {"questions": questions, "answers": by_question}
        if isinstance(response.get("text"), str) and response["text"].strip():
            updated["response"] = response["text"].strip()[:20_000]
        return {"behavior": "allow", "updatedInput": updated}, answers

    # ---- stdin

    def _send(self, payload: dict[str, Any]) -> bool:
        process = self.process
        if process is None or process.stdin is None:
            return False
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            try:
                process.stdin.write(line)
                process.stdin.flush()
                return True
            except (OSError, ValueError):
                return False

    def _respond(self, request_id: str, response: dict[str, Any]) -> None:
        self._send({"type": "control_response", "response": {"subtype": "success", "request_id": request_id, "response": response}})

    def _respond_error(self, request_id: str, message: str) -> None:
        self._send({"type": "control_response", "response": {"subtype": "error", "request_id": request_id, "error": message}})

    # ---- events

    def _emit(self, event: dict[str, Any]) -> None:
        if "runId" in event and event["runId"] != self.run_id:
            raise ValueError("Provider event belongs to a different run")
        event.setdefault("runId", self.run_id)
        check_event("claude", event)
        try:
            self.emit(event)
        except Exception:  # a broken listener must not strand the CLI process
            pass

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq_base + self._seq

    def _add_item(self, item_id: str, kind: str, data: dict[str, Any], at: str | None = None) -> Item:
        normalize_item("claude-code", kind, data)
        item = Item(item_id, self._next_seq(), kind, at or now_iso(), data)
        self._items[item_id] = item
        self._emit({"type": "item.added", "sessionId": self.session_id, "item": item.public()})
        return item

    def _update_item(self, item: Item) -> None:
        normalize_item("claude-code", item.kind, item.data)
        self._emit({"type": "item.updated", "sessionId": self.session_id, "item": item.public()})

    def _delta(self, item_id: str, text: str) -> None:
        if text:
            self._emit({"type": "item.delta", "sessionId": self.session_id, "itemId": item_id, "textDelta": text})

    def _notice(self, text: str, level: str = "info", item_id: str | None = None) -> Item:
        self._notice_n += 1
        return self._add_item(item_id or f"notice:{self.run_id}:{self._notice_n}", "notice", {"text": text, "level": level})

    def _set_state(self, state: str, *, pending: dict | None = None, error: str | None = None, code: str | None = None) -> None:
        self.state = state
        event = {"type": "run.state", "sessionId": self.session_id, "runId": self.run_id, "state": state,
                 "pendingRequest": pending, "error": error}
        if code:
            event["errorCode"] = code
        self._emit(event)

    def _context_event(self, used: int | None, *, window: int | None = None, threshold: int | None = None, source: str = "claude-cli") -> None:
        window = window or self.windows.get(self._model or "") or self.context.window_tokens
        threshold = threshold if threshold is not None else self.context.auto_compact_tokens
        context = ContextUsage(used_tokens=used, window_tokens=window, auto_compact_tokens=threshold, source=source, updated_at=now_iso())
        if asdict(context) == {**asdict(self.context), "updated_at": context.updated_at}:
            return
        self.context = context
        self._emit({"type": "context.updated", "sessionId": self.session_id, "context": asdict(context)})

    # ---- lifecycle

    def run(self) -> str:
        """Run the turn to completion on this thread; returns the session id (known from ``system/init``)."""
        argv = build_argv(self.cli, self.requested_id, self.options, self.extra_args)
        from ..cua_launch import claude_args
        argv += claude_args(self.session_id or self.run_id)
        try:
            from ..claude_code_mods import launch_env  # the Neyvia mod, on both launch paths (same env as the terminal path)
            from ..claude_code_mods import run_env
            plugin = run_env(self.run_id)
            self.process = start_process(argv, self.cwd, child_env({**plugin, **self.extra_env}))
        except OSError as exc:
            self._final = ("failed", "Claude Code could not be started. Check that it is installed and signed in on this PC.", "cli_start_failed")
            self._finish()
            raise ClaudeSessionError("cli_start_failed", self._final[1]) from exc
        self.pid = self.process.pid
        # Child admission can wait on the network-policy launch gate. The
        # provider's idle budget starts only once its process exists.
        with self._lock:
            self._last_output = time.monotonic()
        threading.Thread(target=self._pump_stdout, name=f"claude-out-{self.run_id[:8]}", daemon=True).start()
        threading.Thread(target=self._drain_stderr, name=f"claude-err-{self.run_id[:8]}", daemon=True).start()
        try:
            self._send({"type": "control_request", "request_id": "neyvia_init", "request": {"subtype": "initialize"}})
            self._send_user_message()
            if self.session_id:  # resuming: the session is known before the CLI says anything
                self._announce()
            self._loop()
        finally:
            self._shutdown()
        if self._final is None:
            self._final = ("failed", "Claude Code stopped unexpectedly.", "cli_exited")
        self._finish()
        if not self.session_id:
            raise ClaudeSessionError(self._final[2] or "cli_failed", self._final[1] or "Claude Code did not start a session.")
        return self.session_id

    def _send_user_message(self) -> str:
        user_id, content, data = self._user_payload(self.message, self.options.images or [])
        self._user_item_id, self._user_item_data = user_id, data
        self._send({"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None, "uuid": user_id})
        return user_id

    def _user_payload(self, text: str, images: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        """(uuid, stream-json content, the user item's data) for a message and its images."""
        user_id = str(uuid.uuid4())
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        attachments = []
        for image in images:
            mime, data = str(image.get("mime") or ""), str(image.get("data") or "")
            if not mime.startswith("image/") or not data:
                continue
            content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
            token = image_token(mime, data)
            attachments.append(attachment_dict(token, kind="image", label=str(image.get("name") or "Attached image"), mime=mime))
            if self._keep_media:
                try:
                    import base64
                    self._keep_media(token, base64.b64decode(data), mime)
                except (ValueError, TypeError):
                    pass
        return user_id, content, {"text": text, "attachments": attachments}

    def _announce(self) -> None:
        """Show the person's message and mark the run running, once the session id is known."""
        if self._announced:
            return
        self._announced = True
        self._add_item(self._user_item_id, "user", self._user_item_data)
        self._set_state("running")
        if self._on_session and self.session_id:
            try:
                self._on_session(self.session_id, True)
            except Exception:
                pass

    def _pump_stdout(self) -> None:
        stream = self.process.stdout  # type: ignore[union-attr]
        try:
            for raw in iter(stream.readline, b""):
                try:
                    message = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if isinstance(message, dict):
                    # Output is activity when received, even if a session
                    # callback is still working on an earlier event.
                    with self._lock:
                        self._last_output = time.monotonic()
                    self._inbox.put(("msg", message))
        except (OSError, ValueError):
            pass
        self._inbox.put(("eof",))

    def _drain_stderr(self) -> None:
        stream = self.process.stderr  # type: ignore[union-attr]
        try:
            for raw in iter(stream.readline, b""):
                self.stderr_bytes += len(raw)  # counted, never relayed: it can carry prompts and paths
        except (OSError, ValueError):
            pass

    def _loop(self) -> None:
        while not self._done:
            self._check_deadlines()
            if self._done:
                break
            try:
                entry = self._inbox.get(timeout=0.25)
            except queue.Empty:
                self._tick()
                continue
            kind = entry[0]
            if kind == "msg":
                self._handle(entry[1])
            elif kind == "resolved":
                self._resolved(entry[1], entry[2], entry[3])
            elif kind == "eof":
                self._eof = True
                if self._final is None:
                    self._final = self._exit_outcome()
                self._done = True
        self._tick()

    def _tick(self) -> None:
        self._refresh_agents()
        if not self._eof and self.process is not None and self.process.poll() is not None and self._inbox.empty():
            self._eof = True
            if self._final is None:
                self._final = self._exit_outcome()
            self._done = True

    def _exit_outcome(self) -> tuple[str, str | None, str | None]:
        if self._interrupt_requested:
            return ("interrupted", self._interrupt_reason or "Stopped.", None)
        code = self.process.poll() if self.process else None
        return ("failed", "Claude Code stopped before finishing this turn." + (f" (exit code {code})" if code not in (None, 0) else ""), "cli_exited")

    def _check_deadlines(self) -> None:
        now = time.monotonic()
        if self._interrupt_deadline is not None and now >= self._interrupt_deadline and not self._done:
            if self.process is not None:
                kill_process_tree(self.process)
            self._final = ("interrupted", self._interrupt_reason or "Stopped.", None)
            self._done = True
            return
        with self._lock:
            waiting = bool(self._pending)
        limit = self.pending_timeout if waiting else self.idle_timeout
        # The reader can receive output while the consumer is delivering an
        # event. Drain that activity before deciding the CLI has gone silent.
        # The explicit interruption deadline above still bounds cancellation.
        if not self._interrupt_requested and self._inbox.empty() and now - self._last_output > limit:
            minutes = int(limit // 60)
            what = "answer" if waiting else "output"
            self.interrupt(f"No {what} for {minutes} minutes; the turn was stopped.")

    def _shutdown(self) -> None:
        process = self.process
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        deadline = time.monotonic() + self.shutdown_grace
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if process.poll() is None:  # did not exit after stdin closed: stop it and everything it started
            kill_process_tree(process)

    def _finish(self) -> None:
        state, error, code = self._final or ("failed", "Claude Code stopped unexpectedly.", "cli_exited")
        if state == "completed" and not any(item.kind == "reasoning" for item in self._items.values()):
            self._add_item(f"reasoning-unreported:{self.run_id}", "reasoning",
                           reasoning_data("claude-code", None, source="stream-json"))
        self._set_state(state, error=error, code=code)
        if self.session_id and self._on_session:
            try:
                self._on_session(self.session_id, False)
            except Exception:
                pass

    # ---- message dispatch

    def _handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        session = message.get("session_id")
        if session and self.session_id and session != self.session_id and kind != "control_response":
            self._fork_detected(str(session))
            return
        if kind == "stream_event":
            self._stream_event(message)
        elif kind == "assistant":
            self._assistant(message)
        elif kind == "user":
            self._user(message)
        elif kind == "system":
            self._system(message)
        elif kind == "result":
            self._on_result(message)
        elif kind == "control_request":
            self._control_request(message)
        elif kind == "control_cancel_request":
            self._control_cancel(str(message.get("request_id") or ""))
        elif kind == "control_response":
            self._control_response(message)
        elif kind == "rate_limit_event":
            info = message.get("rate_limit_info") if isinstance(message.get("rate_limit_info"), dict) else {}
            record_claude_limit(info, self.state_root)  # durable windows belong to the service root, not the chat's cwd
            if info.get("status") not in (None, "allowed"):
                self._notice("Claude usage is close to its limit." if info.get("status") == "allowed_warning" else "Claude usage limit reached.", "warning")

    def _fork_detected(self, other: str) -> None:
        """The CLI is working in a different session than the one asked for: stop, never continue in a copy."""
        self._final = ("failed", f"Claude Code started a copy of this session ({other}) instead of continuing it. Neyvia stopped it and did not continue in the copy.", "session_forked")
        self._done = True
        if self.process:
            kill_process_tree(self.process)

    # ---- system

    def _system(self, message: dict[str, Any]) -> None:
        subtype = message.get("subtype")
        if subtype == "init":
            self._on_init(message)
        elif subtype == "api_retry":
            attempt, maximum = message.get("attempt"), message.get("max_retries")
            text = f"Claude did not answer; retrying (attempt {attempt} of {maximum})."
            if self._retry_item is None:
                self._retry_item = self._notice(text, "warning", f"retry:{self.run_id}")
            else:
                self._retry_item.data["text"] = text
                self._update_item(self._retry_item)
        elif subtype == "status":
            if message.get("status") == "compacting":
                self._compaction_item = self._add_item(f"compaction:{self.run_id}", "compaction",
                                                       {"state": "started", "beforeTokens": self.context.used_tokens, "afterTokens": None})
            elif message.get("compact_result") == "failed" and self._compaction_item is not None:
                self._compaction_item.data["state"] = "failed"
                self._update_item(self._compaction_item)
        elif subtype == "compact_boundary":
            meta = message.get("compact_metadata") if isinstance(message.get("compact_metadata"), dict) else {}
            data = {"state": "completed", "beforeTokens": int_or_none(meta.get("pre_tokens")), "afterTokens": int_or_none(meta.get("post_tokens"))}
            if meta.get("trigger"):
                data["trigger"] = meta["trigger"]
            if self._compaction_item is not None:
                self._compaction_item.data.update(data)
                self._update_item(self._compaction_item)
            else:
                self._compaction_item = self._add_item(str(message.get("uuid") or f"compaction:{self.run_id}"), "compaction", data)
            self._context_event(int_or_none(meta.get("post_tokens")))
        elif subtype == "task_notification":
            text = collapse(message.get("summary") or "Background task update", 300)
            self._notice(text, "error" if str(message.get("status")) in {"failed", "killed", "error"} else "info")

    def _on_init(self, message: dict[str, Any]) -> None:
        session = str(message.get("session_id") or "")
        if self.requested_id and session != self.requested_id:
            self._fork_detected(session)
            return
        self.session_id = session
        self._model = message.get("model") or self._model
        self._announce()

    # ---- streaming

    def _stream_event(self, message: dict[str, Any]) -> None:
        if message.get("parent_tool_use_id"):
            return  # sub-agent traffic is counted on its Agent item, never streamed as chat
        event = message.get("event") if isinstance(message.get("event"), dict) else {}
        kind = event.get("type")
        if kind == "message_start":
            info = event.get("message") if isinstance(event.get("message"), dict) else {}
            self._msg_id, self._model = str(info.get("id") or uuid.uuid4().hex), info.get("model") or self._model
            self._blocks.clear()
            self._streamed.add(self._msg_id)
            used = context_used(info.get("usage"))
            if used is not None:
                self._last_usage_used = used
                self._context_event(used)
        elif kind == "content_block_start":
            self._block_start(int(event.get("index") or 0), event.get("content_block") or {})
        elif kind == "content_block_delta":
            self._block_delta(int(event.get("index") or 0), event.get("delta") or {})
        elif kind == "content_block_stop":
            self._block_stop(int(event.get("index") or 0))

    def _block_id(self, index: int) -> str:
        return f"{self._msg_id}:{index}"

    def _block_start(self, index: int, block: dict[str, Any]) -> None:
        kind = block.get("type")
        if kind == "text":
            item = self._add_item(self._block_id(index), "assistant", {"text": "", "attachments": []})
            self._blocks[index] = {"kind": "text", "item": item}
        elif kind in ("thinking", "redacted_thinking"):
            item = self._add_item(self._block_id(index), "reasoning",
                reasoning_data("claude-code", (str(block.get("thinking") or "") or None) if kind == "thinking" else None,
                               source="stream-json", exposure="summary", pending=kind == "thinking", withheld=kind == "redacted_thinking"))
            self._blocks[index] = {"kind": "thinking", "item": item, "text": str(block.get("thinking") or "") if kind == "thinking" else "",
                                   "withheld": kind == "redacted_thinking"}
        elif kind == "tool_use":
            name, tool_id = str(block.get("name") or "tool"), str(block.get("id") or "")
            state: dict[str, Any] = {"kind": "tool", "id": tool_id, "name": name, "json": "", "item": None}
            self._tool_started[tool_id] = now_iso()
            if name != QUESTION_TOOL:
                state["item"] = self._new_tool_item(tool_id, name, {})
            self._blocks[index] = state

    def _new_tool_item(self, tool_id: str, name: str, tool_input: dict[str, Any]) -> Item:
        item = self._add_item(tool_id, "tool", tool_data(name, tool_input))
        if item.data["category"] == "agent":
            self._agents[tool_id] = {"hints": new_agent_hints(tool_input, item.data["agent"], item.at), "aggregate": AgentAggregate()}
        return item

    def _block_delta(self, index: int, delta: dict[str, Any]) -> None:
        state = self._blocks.get(index)
        if state is None:
            return
        kind = delta.get("type")
        if kind == "text_delta" and state["kind"] == "text":
            text = str(delta.get("text") or "")
            state["item"].data["text"] += text
            self._delta(state["item"].id, text)
        elif kind == "thinking_delta" and state["kind"] == "thinking" and not state["withheld"]:
            text = str(delta.get("thinking") or "")
            if text:  # empty thinking means the provider withheld it: stay hidden, never invent
                state["text"] += text
                state["item"].data["summary"] = state["text"]
                state["item"].data.update(hidden=False, exposure="summary", notice=None)
                self._delta(state["item"].id, text)
        elif kind == "input_json_delta" and state["kind"] == "tool":
            state["json"] += str(delta.get("partial_json") or "")

    def _block_stop(self, index: int) -> None:
        state = self._blocks.pop(index, None)
        if state is None:
            return
        if state["kind"] == "thinking":
            state["item"].data.update(reasoning_data(
                "claude-code", state["text"], source="stream-json", exposure="summary", withheld=state["withheld"]))
            self._update_item(state["item"])
        elif state["kind"] == "tool":
            self._tool_input_ready(state["id"], state["name"], state["json"], state["item"])

    def _tool_input_ready(self, tool_id: str, name: str, raw_json: str, item: Item | None) -> None:
        if tool_id in self._tool_ready:
            return  # the complete assistant message and the block stop both report the same input
        self._tool_ready.add(tool_id)
        try:
            tool_input = json.loads(raw_json) if raw_json.strip() else {}
        except ValueError:
            tool_input = {}
        if not isinstance(tool_input, dict):
            tool_input = {}
        if name == QUESTION_TOOL:
            if tool_id not in self._items:
                self._add_item(tool_id, "question", question_data(tool_input, None))
            return
        if item is None:
            item = self._items.get(tool_id) or self._new_tool_item(tool_id, name, tool_input)
        fresh = tool_data(name, tool_input)
        for key in ("title", "input", "files", "command", "description", "args", "server", "tool", "plan", "diff", "inputTruncated", "argsTruncated"):
            if key in fresh:
                item.data[key] = fresh[key]
        if item.data["category"] == "agent" and tool_id in self._agents:
            hints = self._agents[tool_id]["hints"]
            hints.update(description=fresh["agent"]["description"], subagentType=fresh["agent"]["subagentType"],
                         inputModel=fresh["agent"]["model"], promptHead=str(tool_input.get("prompt") or "").strip()[:200],
                         **{"async": bool(tool_input.get("run_in_background")) or None})
            item.data["agent"] = self._agent_summary(tool_id)
        self._update_item(item)

    # ---- complete messages

    def _assistant(self, message: dict[str, Any]) -> None:
        body = message.get("message") if isinstance(message.get("message"), dict) else {}
        parent = message.get("parent_tool_use_id")
        if parent:
            self._subagent_message(str(parent), message)
            return
        if message.get("error"):
            self._error_category = str(message["error"])
        used = context_used(body.get("usage"))
        if used is not None and body.get("model") != "<synthetic>":
            self._last_usage_used = used
        message_id = str(body.get("id") or "")
        if message_id in self._streamed:
            for block in body.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    self._tool_input_from_message(block)
            return
        # No partial-message stream for this message: build its items from the complete blocks.
        for block in body.get("content") or []:
            if not isinstance(block, dict):
                continue
            index = self._nonstream_index.get(message_id, 0)
            self._nonstream_index[message_id] = index + 1
            self._msg_id = message_id or self._msg_id or uuid.uuid4().hex
            kind = block.get("type")
            if kind == "text" and str(block.get("text") or "").strip():
                clipped, _ = bound_text(str(block["text"]), 48_000)
                self._add_item(f"{self._msg_id}:{index}", "assistant", {"text": clipped, "attachments": []})
            elif kind in ("thinking", "redacted_thinking"):
                text = str(block.get("thinking") or "").strip() if kind == "thinking" else ""
                self._add_item(f"{self._msg_id}:{index}", "reasoning",
                    reasoning_data("claude-code", text, source="stream-json", exposure="summary", withheld=kind == "redacted_thinking"))
            elif kind == "tool_use":
                self._tool_input_from_message(block)
        if used is not None:
            self._context_event(used)

    def _tool_input_from_message(self, block: dict[str, Any]) -> None:
        tool_id, name = str(block.get("id") or ""), str(block.get("name") or "tool")
        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        self._tool_started.setdefault(tool_id, now_iso())
        item = self._items.get(tool_id)
        if name == QUESTION_TOOL:
            if item is None:
                self._add_item(tool_id, "question", question_data(tool_input, None))
            return
        self._tool_input_ready(tool_id, name, json.dumps(tool_input), item)

    def _user(self, message: dict[str, Any]) -> None:
        body = message.get("message") if isinstance(message.get("message"), dict) else {}
        if message.get("isReplay"):
            if not message.get("parent_tool_use_id"):
                with self._lock:
                    self._replays_seen += 1  # the first is the turn's own message, the rest are steers
            return
        if message.get("parent_tool_use_id"):
            return
        content = body.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else [b for b in content or [] if isinstance(b, dict)]
        for block in blocks:
            if block.get("type") == "tool_result":
                self._tool_result(block, message)
            elif block.get("type") == "text":
                kind, text, level = classify_user_text(str(block.get("text") or ""))
                if kind == "notice":
                    self._notice(text, level)

    def _tool_result(self, block: dict[str, Any], message: dict[str, Any]) -> None:
        tool_id = str(block.get("tool_use_id") or "")
        item = self._items.get(tool_id)
        if item is None:
            return
        text, _ = flatten_result_content(block.get("content"))
        structured = message.get("tool_use_result")
        is_error = bool(block.get("is_error"))
        if item.kind == "question":
            answers = structured.get("answers") if isinstance(structured, dict) else None
            item.data["answers"] = answers_by_id(item.data.get("questions", []), answers)
            item.data["answered"] = bool(item.data["answers"]) and not is_error
            if is_error:
                item.data["declined"] = True
        else:
            apply_tool_result(item.data, text=text, is_error=is_error, timestamp=message.get("timestamp") or now_iso(),
                              started_at=self._tool_started.get(tool_id), structured=structured)
            agent = self._agents.get(tool_id)
            if agent is not None:
                apply_agent_result(agent["hints"], structured, is_error, message.get("timestamp") or now_iso())
                item.data["agent"] = self._agent_summary(tool_id)
        self._update_item(item)
        if item.kind == "tool" and item.data.get("diff") and not is_error:
            self._add_item(f"{tool_id}:diff", "diff", item.data["diff"])

    # ---- sub-agents

    def _subagent_message(self, parent: str, message: dict[str, Any]) -> None:
        agent = self._agents.get(parent)
        if agent is None:
            return
        agent["aggregate"].feed({"type": "assistant", "timestamp": message.get("timestamp") or now_iso(), "message": message.get("message")})
        self._emit_agent(parent, force=False)

    def _agent_summary(self, tool_id: str) -> dict[str, Any]:
        agent = self._agents[tool_id]
        return agent["aggregate"].summarize(agent["hints"])

    def _emit_agent(self, tool_id: str, force: bool) -> None:
        item = self._items.get(tool_id)
        if item is None or tool_id not in self._agents:
            return
        now = time.monotonic()
        if not force and now - self._agent_emit_at.get(tool_id, 0) < 0.3:
            return
        summary = self._agent_summary(tool_id)
        if summary != item.data.get("agent"):
            item.data["agent"] = summary
            self._agent_emit_at[tool_id] = now
            self._update_item(item)

    def _refresh_agents(self) -> None:
        for tool_id in list(self._agents):
            self._emit_agent(tool_id, force=False)

    # ---- permission requests and questions

    def _control_request(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("request_id") or "")
        request = message.get("request") if isinstance(message.get("request"), dict) else {}
        if request.get("subtype") != "can_use_tool":
            self._respond_error(request_id, "Neyvia cannot answer this kind of request.")
            return
        if self._interrupt_requested:
            self._respond(request_id, {"behavior": "deny", "message": "The turn was stopped.", "interrupt": True})
            return
        tool, tool_input = str(request.get("tool_name") or ""), request.get("input") if isinstance(request.get("input"), dict) else {}
        tool_use_id = str(request.get("tool_use_id") or "") or None
        if tool == QUESTION_TOOL:
            item = self._items.get(tool_use_id or "")
            data = question_data(tool_input, request_id)
            if item is None:
                item = self._add_item(tool_use_id or f"question:{request_id}", "question", data)
            else:
                item.data.update(data)
                self._update_item(item)
            pending = Pending(request_id, "question", tool, tool_use_id, tool_input, item.id)
            with self._lock:
                self._pending[request_id] = pending
            self._set_state("waiting_input", pending={"requestId": request_id, "kind": "question", **item.data})
            return
        data = self._approval_data(request_id, tool, tool_input, request, tool_use_id)
        item = self._add_item(f"approval:{request_id}", "approval", data)
        with self._lock:
            self._pending[request_id] = Pending(request_id, "approval", tool, tool_use_id, tool_input, item.id)
        self._set_state("waiting_approval", pending={"requestId": request_id, "kind": "approval", **item.data})

    def _approval_data(self, request_id: str, tool: str, tool_input: dict[str, Any], request: dict[str, Any], tool_use_id: str | None) -> dict[str, Any]:
        return approval_data(request_id, tool, tool_input, request, tool_use_id, self.cwd)

    def _resolved(self, request_id: str, decision: str, answers: dict[str, str]) -> None:
        """The person answered (or the request was withdrawn): update the item and resume the run state."""
        item = next((entry for entry in self._items.values() if entry.kind in ("approval", "question")
                     and entry.data.get("requestId") == request_id), None)
        if item is not None:
            if item.kind == "approval":
                item.data["decision"] = {"approve": "approved", "deny": "denied", "cancel": "cancelled"}.get(decision, decision)
            else:
                item.data["answers"] = answers
                item.data["answered"] = decision == "approve"
            self._update_item(item)
        with self._lock:
            still_waiting = bool(self._pending)
        if not still_waiting and not self._done and self.state in ("waiting_approval", "waiting_input"):
            self._set_state("running")

    def _control_cancel(self, request_id: str) -> None:
        with self._lock:
            existed = self._pending.pop(request_id, None)
        if existed is not None:
            self._resolved(request_id, "cancel", {})

    def _control_response(self, message: dict[str, Any]) -> None:
        response = message.get("response") if isinstance(message.get("response"), dict) else {}
        request_id = response.get("request_id")
        body = response.get("response") if isinstance(response.get("response"), dict) else {}
        if request_id == "neyvia_init":
            models = body.get("models")
            if isinstance(models, list) and self._on_models:
                self._on_models(models)
        elif request_id == self._ctx_request:
            self._ctx_response = body

    # ---- result

    def _on_result(self, message: dict[str, Any]) -> None:
        self._result = message
        from ..model_usage import claude_receipt
        usage = claude_receipt(message.get("usage"))
        if usage:
            self._emit({"type": "usage.updated", "sessionId": self.session_id, "usage": usage})
        usage_by_model = message.get("modelUsage") if isinstance(message.get("modelUsage"), dict) else {}
        for model, usage in usage_by_model.items():
            window = int_or_none(usage.get("contextWindow")) if isinstance(usage, dict) else None
            if window:
                self.windows[str(model)] = window
        window = self.windows.get(self._model or "")
        if window is None and len(usage_by_model) == 1:
            window = int_or_none(next(iter(usage_by_model.values())).get("contextWindow"))
        if self._last_usage_used is not None or window:
            self._context_event(self._last_usage_used, window=window)
        if self.context_probe and not self._interrupt_requested:
            self._probe_context()
        for tool_id in list(self._agents):
            self._emit_agent(tool_id, force=True)
        with self._lock:
            queued = self._steers_sent - max(0, self._replays_seen - 1)
        # Only a CLI that replays messages says when it took one in; without replays nothing is held.
        if queued > 0 and self._replays_seen >= 1 and not self._interrupt_requested and not message.get("is_error"):
            return  # a steer arrived as the turn finished: Claude Code runs it next, so keep listening
        self._final = self._outcome(message)
        self._done = True

    def _probe_context(self) -> None:
        """Ask the CLI for its own window and auto-compact threshold (``get_context_usage``); best effort, short."""
        self._ctx_request = "neyvia_ctx_" + uuid.uuid4().hex[:6]
        if not self._send({"type": "control_request", "request_id": self._ctx_request, "request": {"subtype": "get_context_usage", "detail": "summary"}}):
            return
        deadline = time.monotonic() + CONTEXT_PROBE_SECONDS
        while self._ctx_response is None and time.monotonic() < deadline:
            try:
                entry = self._inbox.get(timeout=0.1)
            except queue.Empty:
                continue
            if entry[0] == "msg":
                self._handle(entry[1])
            elif entry[0] == "eof":
                self._eof = True
                return
        body = self._ctx_response
        if isinstance(body, dict):
            window = int_or_none(body.get("maxTokens"))
            threshold = int_or_none(body.get("autoCompactThreshold")) if body.get("isAutoCompactEnabled") else None
            if window:
                self.windows[str(body.get("model") or self._model or "")] = window
            self._context_event(self._last_usage_used, window=window, threshold=threshold)

    def _outcome(self, message: dict[str, Any]) -> tuple[str, str | None, str | None]:
        terminal = str(message.get("terminal_reason") or "")
        if self._interrupt_requested or terminal in ("aborted_streaming", "aborted_tools", "interrupted"):
            return ("interrupted", self._interrupt_reason or "Stopped.", None)
        if message.get("subtype") == "success" and not message.get("is_error"):
            return ("completed", None, None)
        category = self._error_category or _HTTP_ERRORS.get(message.get("api_error_status") if isinstance(message.get("api_error_status"), int) else -1)
        if category in _ERROR_TEXT:
            code, text = _ERROR_TEXT[category]
            return ("failed", text, code)
        subtype = str(message.get("subtype") or "")
        if subtype == "error_max_turns":
            return ("failed", "Claude Code stopped: the turn limit was reached.", "max_turns")
        if subtype == "error_max_budget_usd":
            return ("failed", "Claude Code stopped: the spending limit for this turn was reached.", "max_budget")
        return ("failed", "Claude Code could not finish this turn. Check the session in Claude Code on this PC.", "turn_failed")
