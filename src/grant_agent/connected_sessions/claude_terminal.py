"""One Claude Code turn in its normal interactive mode, in a hidden terminal (the "plan limits" route).

Opt-in alternative to print mode (``claude_stream``). The official, unmodified ``claude`` starts in a
hidden pseudo-console with the person's message as its first prompt, exactly as if they had typed
``claude [--resume <id>] -- "<message>"`` themselves. Terminal input is limited to Escape to stop,
the person's explicit answer to the recognized startup folder-trust menu, and, only after the person presses
"Take over" in the live view (claude_code_cli), what the person types there themselves; the view is read-only otherwise. Bypass permissions carries
the confirmation already given in Neyvia through this run's settings. Neyvia follows the transcript and learns about
prompts through Claude Code's documented hooks, passed with ``--settings`` for this one process (the
person's own settings files are never changed):

- ``PermissionRequest``: a tool needs approval; the person's decision is the hook's answer.
- ``PreToolUse`` (AskUserQuestion only): the question is shown in Neyvia and the answers become the tool input.
- ``Stop`` / ``StopFailure``: the turn ended, so the process is closed.
- ``SessionStart``, ``UserPromptSubmit``, ``Notification``: progress, and prompts Neyvia cannot show.

Usage counts against the plan's interactive limits instead of the Agent SDK credit. Anthropic's consumer
terms restrict automated access to its services, so the route is opt-in and labeled as carrying some
risk to the account. Neyvia never signs in, reads credentials or answers anything on the person's behalf.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from ..subprocess_utils import hidden_windows_subprocess_kwargs
from ..proofs_a_providers import checked, check_event
from .claude_items import QUESTION_TOOL, collapse, now_iso, parse_time, question_data
from .claude_stream import (
    _ERROR_TEXT, _MODEL_RE, _TOKEN_RE, IDLE_TIMEOUT_SECONDS, PENDING_TIMEOUT_SECONDS, ClaudeRun, ClaudeSessionError,
    Pending, approval_data, child_env, cli_prefix,
)
from .claude_transcript import find_session_file
from .claude_trust import TRUST_TOOL, trust_menu
from .model import ContextUsage, Emit, Item, TurnOptions

STARTUP_SECONDS = 45.0
INTERRUPT_GRACE_SECONDS = 3.0
STOP_SETTLE_SECONDS = 0.6
POLL_SECONDS = 0.4
# Windows limits a whole command line to 32,767 characters; the message travels as one argument.
MAX_TERMINAL_MESSAGE_CHARS = 24_000
HOOK_SCRIPT = Path(__file__).with_name("claude_hook.py")
_HOOKS = (
    ("SessionStart", None, "start"),
    ("UserPromptSubmit", None, "prompt"),
    ("PreToolUse", QUESTION_TOOL, "question"),
    ("PermissionRequest", None, "permission"),
    ("Stop", None, "stop"),
    ("StopFailure", None, "failure"),
    ("Notification", None, "notify"),
)
_WAITING_HOOK_SECONDS = 24 * 60 * 60
_CSI_RIGHT = re.compile(r"\x1b\[(\d*)C")
_ANSI = re.compile(r"\x1b\[[0-9;?><]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>]")


def _is_local_command(message: Any) -> bool:
    words = str(message or "").strip().lower().split(None, 1)
    return bool(words) and words[0] == "/compact"


def _since(stamp: Any, moment: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")) >= moment - timedelta(seconds=2)
    except ValueError:
        return False


def hook_python() -> str:
    """A console Python for the hook: ``pythonw`` has no usable stdout to answer Claude Code with."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        return str(exe.with_name("python.exe"))
    return str(exe)


def spawn_terminal(argv: list[str], cwd: str, env: dict[str, str]) -> Any:
    """Start a real ConPTY from an explicitly private process desktop."""
    from ..local_network_policy import child_start
    with child_start():
        from ..private_conpty import PrivateConPTY
        return PrivateConPTY.spawn(argv, cwd=cwd, env=env, dimensions=(50, 200))


def terminal_available() -> tuple[bool, str | None]:
    if os.name != "nt":
        return False, "Plan-limits mode is only built for Windows hosts so far."
    return True, None


IMAGE_DIR = Path.home() / ".neyvia" / "claude-images"
_IMAGE_SUFFIX = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}


@checked("providers.terminal.images")
def attach_images_as_files(text: str, images: list[dict[str, Any]]) -> str:
    """Interactive Claude Code takes no image blocks on its command line: save each image on this
    PC and name its path in the message, so Claude opens it with its Read tool."""
    import base64
    import binascii

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for image in images:
        suffix = _IMAGE_SUFFIX.get(str(image.get("mime") or "").lower())
        if suffix is None:
            raise ClaudeSessionError("invalid_image", "Plan-limits mode takes PNG, JPEG, GIF or WebP images.")
        try:
            data = base64.b64decode(str(image.get("data") or ""), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ClaudeSessionError("invalid_image", "An attached image couldn't be read.") from exc
        path = IMAGE_DIR / f"{uuid.uuid4().hex}{suffix}"
        path.write_bytes(data)
        paths.append(str(path))
    lines = "\n".join(f"Attached image: {path}" for path in paths)
    return f"{text.rstrip()}\n\n{lines}" if text.strip() else f"Look at the attached image{'s' if len(paths) > 1 else ''}.\n\n{lines}"


@checked("providers.terminal.argv")
def terminal_argv(cli: Any, session_id: str, resume: bool, options: TurnOptions, settings: Path, message: str,
                  extra_args: list[str] | None = None) -> list[str]:
    # Native Claude Code 2.1.295 accepts this display flag for new and resumed turns.
    # Explicit display also avoids print-mode omission; user settings stay untouched.
    argv = [*cli_prefix(cli), "--settings", str(settings), "--thinking-display", "summarized"]
    if resume:
        argv += ["--resume", session_id]
    elif options.fork_from:
        # A branch: the CLI copies the history into a new session with the id we follow.
        argv += ["--resume", options.fork_from, "--fork-session", "--session-id", session_id]
    else:
        argv += ["--session-id", session_id]
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
    return argv + list(extra_args or []) + ["--", message]


@checked("providers.terminal.screen")
def screen_text(raw: str) -> str:
    """Readable text of a stretch of terminal output (cursor moves become spaces, other escapes go)."""
    text = _CSI_RIGHT.sub(lambda match: " " * max(1, int(match.group(1) or 1)), raw)
    text = _ANSI.sub(" ", text).replace("\r", "\n")
    return " ".join(text.split())


def _kill_tree(pid: int | None) -> None:
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10, check=False,
                           **hidden_windows_subprocess_kwargs())
        else:
            os.kill(pid, 9)
    except (OSError, subprocess.TimeoutExpired):
        pass


class ClaudeTerminalRun:
    """Owns one hidden interactive ``claude`` process for one turn; every method except ``run`` is thread safe."""

    def __init__(self, *, cli: Any, run_id: str, session_id: str | None, message: str, options: TurnOptions, cwd: str,
                 emit: Emit, projects: Path, store_for: Callable[[Path, str, str | None], Any],
                 context_for: Callable[[Path], ContextUsage] | None = None, extra_args: list[str] | None = None,
                 extra_env: dict[str, str] | None = None, idle_timeout: float = IDLE_TIMEOUT_SECONDS,
                 pending_timeout: float = PENDING_TIMEOUT_SECONDS, interrupt_grace: float = INTERRUPT_GRACE_SECONDS,
                 startup_timeout: float = STARTUP_SECONDS, poll_interval: float = POLL_SECONDS,
                 spawn: Callable[[list[str], str, dict[str, str]], Any] | None = None, python: str | None = None,
                 spool_root: str | Path | None = None, on_session: Callable[[str, bool], None] | None = None):
        self.cli, self.run_id, self.cwd, self.emit = cli, run_id, cwd, emit
        self.resume = bool(session_id)
        self.session_id: str = session_id or str(uuid.uuid4())
        self.message, self.options = message, options
        self.projects, self._store_for, self._context_for = projects, store_for, context_for
        self.extra_args, self.extra_env = extra_args or [], extra_env or {}
        self.idle_timeout, self.pending_timeout = idle_timeout, pending_timeout
        self.interrupt_grace, self.startup_timeout, self.poll_interval = interrupt_grace, startup_timeout, poll_interval
        self._spawn = spawn or spawn_terminal
        self._python = python or hook_python()
        self._spool_root = str(spool_root) if spool_root else None
        self._on_session = on_session
        self.state = "queued"
        self.pid: int | None = None
        self.term: Any = None
        self._lock = threading.RLock()
        self._spool: Path | None = None
        self._seen_events: set[str] = set()
        self._pending: dict[str, Pending] = {}
        self._items: dict[str, Item] = {}
        self._max_seq = 0
        self._path: Path | None = None
        self._cursor: str | None = None
        self._context: dict[str, Any] | None = None
        self._screen: list[str] = []
        self._view = None  # the live view of this turn's terminal in Neyvia's terminal pane (claude_code_cli)
        self._screen_size = 0
        self._started = self._prompted = False
        # A local command such as /compact never fires UserPromptSubmit or Stop; the transcript is how it ends.
        self._local_command = _is_local_command(message)
        self._began_at = datetime.now(timezone.utc)
        from .claude_usage import ClaudeTranscriptUsage
        self._usage = ClaudeTranscriptUsage(self._began_at)
        self._trust_offered = False
        self._spawned_at = 0.0
        self._last_activity = time.monotonic()
        self._stop_at: float | None = None
        self._failure: tuple[str, str] | None = None
        self._unshown: tuple[float, str] | None = None  # (when, text) of a prompt Neyvia may not be able to show
        self._last_request_at = 0.0
        self._interrupt_requested = False
        self._interrupt_deadline: float | None = None
        self._interrupt_reason: str | None = None
        self._done = False
        self._final: tuple[str, str | None, str | None] | None = None

    # ---- public (any thread)

    def interrupt(self, reason: str | None = None) -> None:
        """Stop the turn: refuse pending prompts, press Escape, and close the process after a short grace."""
        with self._lock:
            if self._done or self._interrupt_requested:
                return
            self._interrupt_requested = True
            self._interrupt_reason = reason
            self._interrupt_deadline = time.monotonic() + self.interrupt_grace
            pending = list(self._pending.values())
            self._pending.clear()
        for request in pending:
            self._reply(request, {"behavior": "deny", "message": "The turn was stopped.", "interrupt": True})
            self._resolved(request.request_id, "cancel", {})
        term = self.term
        if term is not None:
            try:
                term.write("\x1b")
            except Exception:  # noqa: BLE001 - the close that follows stops it either way
                pass

    @checked("providers.terminal.answer")
    def answer(self, request_id: str, response: dict[str, Any]) -> None:
        decision = str((response or {}).get("decision") or "")
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                raise ClaudeSessionError("request_not_pending", "This request is no longer waiting. Refresh the session and review its current state.")
            reply, answers = ClaudeRun._build_reply(pending, decision, response or {})
            if pending.tool_name == TRUST_TOOL:
                menu = trust_menu(screen_text("".join(self._screen)))
                if self._prompted or self._interrupt_requested or not self.term or not self.term.isalive() or menu is None or menu.detail != pending.tool_input.get("detail"):
                    raise ClaudeSessionError("request_not_pending", "The folder-trust dialog changed or closed. Stop this turn and retry to review a fresh request.")
                try:
                    self.term.write(menu.keys(decision == "approve"))
                except Exception as exc:
                    raise ClaudeSessionError("terminal_write_failed", "Claude Code could not receive your folder-trust decision. Stop this turn and retry.") from exc
                self._screen.clear()
                self._screen_size = 0
                self._spawned_at = time.monotonic()
                if decision != "approve":
                    self._interrupt_requested = True
                    self._interrupt_reason = "Folder trust was declined."
                    self._interrupt_deadline = time.monotonic() + self.interrupt_grace
            self._reply(pending, reply)
            self._pending.pop(request_id)
            self._last_activity = time.monotonic()
        self._resolved(request_id, decision, answers)

    # ---- hook replies

    def _reply(self, pending: Pending, reply: dict[str, Any]) -> None:
        if pending.tool_name == TRUST_TOOL:
            return  # The native startup menu, not a hook, owns this decision.
        allow = reply.get("behavior") == "allow"
        if pending.kind == "question":
            output = ({"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": reply.get("updatedInput") or {}}
                      if allow else {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                     "permissionDecisionReason": reply.get("message") or "The user declined to answer."})
        else:
            decision: dict[str, Any] = {"behavior": "allow" if allow else "deny"}
            if allow and isinstance(reply.get("updatedInput"), dict) and reply["updatedInput"] != pending.tool_input:
                decision["updatedInput"] = reply["updatedInput"]
            if not allow:
                decision["message"] = reply.get("message") or "Denied."
                if reply.get("interrupt"):
                    decision["interrupt"] = True
            output = {"hookEventName": "PermissionRequest", "decision": decision}
        spool = self._spool
        if spool is None:
            return
        folder = spool / "decisions"
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / f".{pending.request_id}.tmp"
        temp.write_text(json.dumps({"hookSpecificOutput": output}), encoding="utf-8")
        os.replace(temp, folder / f"{pending.request_id}.json")

    # ---- events

    def _emit(self, event: dict[str, Any]) -> None:
        check_event("claude", event)
        try:
            self.emit(event)
        except Exception:  # noqa: BLE001 - a broken listener must not strand the process
            pass

    def _set_state(self, state: str, *, pending: dict | None = None, error: str | None = None, code: str | None = None) -> None:
        self.state = state
        event = {"type": "run.state", "sessionId": self.session_id, "runId": self.run_id, "state": state,
                 "pendingRequest": pending, "error": error}
        if code:
            event["errorCode"] = code
        self._emit(event)

    def _show(self, item: Item) -> None:
        known = item.id in self._items
        self._items[item.id] = item
        self._max_seq = max(self._max_seq, item.seq)
        self._emit({"type": "item.updated" if known else "item.added", "sessionId": self.session_id, "item": item.public()})

    def _notice(self, text: str, level: str = "info") -> None:
        self._show(Item(f"notice:{self.run_id}:{uuid.uuid4().hex[:6]}", self._max_seq + 1, "notice", None, {"text": text, "level": level}))

    def _resolved(self, request_id: str, decision: str, answers: dict[str, str]) -> None:
        item = next((entry for entry in self._items.values() if entry.kind in ("approval", "question")
                     and entry.data.get("requestId") == request_id), None)
        if item is not None:
            if item.kind == "approval":
                item.data["decision"] = {"approve": "approved", "deny": "denied", "cancel": "cancelled"}.get(decision, decision)
            else:
                item.data["answers"] = answers
                item.data["answered"] = decision == "approve"
            self._show(item)
        with self._lock:
            still_waiting = bool(self._pending)
        if not still_waiting and not self._done and self.state in ("waiting_approval", "waiting_input"):
            self._set_state("running")

    def steer(self, message: str, images: list[dict[str, Any]] | None = None) -> None:
        """Type a message into the running interactive Claude Code, as a person would while it works;
        Claude Code queues it and takes it in at its next step."""
        if images:
            raise ClaudeSessionError("images_unsupported", "Send images with your next message instead; they can't be added mid-turn in plan-limits mode.")
        text = " ".join(str(message or "").split())
        if not text:
            raise ClaudeSessionError("empty_message", "Enter a message to send.")
        if len(text) > 4000:
            raise ClaudeSessionError("message_too_long", "Keep a mid-turn message under 4,000 characters.")
        term = getattr(self, "term", None)
        if term is None or self._final is not None:
            raise ClaudeSessionError("run_not_active", "This turn has finished. Send your message as a new one.")
        try:
            term.write(text)
            time.sleep(0.15)
            term.write("\r")
        except (OSError, EOFError) as exc:
            raise ClaudeSessionError("run_not_active", "Claude Code isn't taking messages for this turn any more.") from exc
        self._last_activity = time.monotonic()

    # ---- lifecycle

    def run(self) -> str:
        text = self.message if isinstance(self.message, str) else ""
        if self.options.images:
            text = attach_images_as_files(text, self.options.images)
        if len(text) > MAX_TERMINAL_MESSAGE_CHARS:
            raise ClaudeSessionError("message_too_long", f"Plan-limits mode takes messages up to {MAX_TERMINAL_MESSAGE_CHARS:,} characters. Switch to Agent SDK credit for longer ones.")
        self._spool = Path(tempfile.mkdtemp(prefix=f"neyvia-claude-{self.run_id[:8]}-", dir=self._spool_root))
        try:
            settings = self._write_settings()
            if self.resume:
                self._baseline()
            argv = terminal_argv(self.cli, self.session_id, self.resume, self.options, settings, text, self.extra_args)
            from ..cua_launch import claude_args
            cua = claude_args(self.session_id)
            if cua:
                argv = argv[:-2] + cua + argv[-2:]
            try:
                from ..claude_code_mods import launch_env  # the Neyvia plugin, when the setting is on (default)
                from ..claude_code_mods import run_env
                plugin = run_env(self.run_id)
                self.term = self._spawn(argv, self.cwd, child_env({**plugin, **self.extra_env}))
            except (OSError, ImportError, RuntimeError) as exc:
                self._final = ("failed", "Claude Code could not be started in a hidden terminal on this PC.", "cli_start_failed")
                self._finish()
                raise ClaudeSessionError("cli_start_failed", self._final[1]) from exc
            self.pid = getattr(self.term, "pid", None)
            try:
                from ..claude_code_cli import LiveView, register
                self._view = LiveView(self.run_id, self.cwd, self.term)
                register(self._view)
            except Exception:  # noqa: BLE001 - the view is a courtesy; the turn never depends on it
                self._view = None
            self._spawned_at = self._last_activity = time.monotonic()
            threading.Thread(target=self._drain, name=f"claude-term-{self.run_id[:8]}", daemon=True).start()
            self._set_state("running")
            self._session_changed(True)
            self._loop()
        finally:
            self._close()
            if self._view is not None:
                from ..claude_code_cli import retire
                retire(self._view)
        if self._final is None:
            self._final = ("failed", "Claude Code stopped unexpectedly.", "cli_exited")
        self._finish()
        if not self.resume and self._path is None and self._final[0] == "failed":
            raise ClaudeSessionError(self._final[2] or "cli_failed", self._final[1] or "Claude Code did not start a session.")
        return self.session_id

    def _write_settings(self) -> Path:
        spool = self._spool
        assert spool is not None
        (spool / "events").mkdir(exist_ok=True)
        (spool / "decisions").mkdir(exist_ok=True)
        hooks: dict[str, list] = {}
        for event, matcher, tag in _HOOKS:
            entry: dict[str, Any] = {"hooks": [{"type": "command", "command": self._python,
                                                "args": [str(HOOK_SCRIPT), str(spool), tag],
                                                "timeout": _WAITING_HOOK_SECONDS if tag in ("permission", "question") else 30}]}
            if matcher:
                entry["matcher"] = matcher
            hooks.setdefault(event, []).append(entry)
        settings: dict[str, Any] = {"hooks": hooks, "alwaysThinkingEnabled": True, "showThinkingSummaries": True}
        if self.options.permission_mode == "bypassPermissions":
            # Claude Code reads flagSettings for its one-time warning. Neyvia has already asked
            # the person to confirm this mode; carry that choice only for this process.
            settings["skipDangerousModePermissionPrompt"] = True
        path = spool / "settings.json"
        path.write_text(json.dumps(settings), encoding="utf-8")
        return path

    def _baseline(self) -> None:
        """For a resumed session, start following the transcript where it ends now."""
        path = find_session_file(self.projects, self.session_id)
        if path is None:
            return
        self._path = path
        try:
            _, _, self._cursor = self._store_for(path, self.session_id, self.cwd).page(cursor=None, before_seq=None, limit=1)
        except OSError:
            self._cursor = None

    def _drain(self) -> None:
        term = self.term
        while True:
            try:
                chunk = term.read(4096)
            except Exception:  # noqa: BLE001 - EOFError when the process ends, OSError when it is closed
                return
            if not chunk:
                if not term.isalive():
                    return
                time.sleep(0.05)
                continue
            if self._view is not None:
                self._view.feed(chunk)
            with self._lock:
                self._screen.append(chunk)
                self._screen_size += len(chunk)
                while self._screen_size > 32_000 and len(self._screen) > 1:
                    self._screen_size -= len(self._screen.pop(0))

    def _screen_hint(self) -> str:
        with self._lock:
            raw = "".join(self._screen)
        return screen_text(raw)[-300:]

    def _offer_folder_trust(self) -> bool:
        with self._lock:
            if self._trust_offered or self._prompted or self._interrupt_requested:
                return any(request.tool_name == TRUST_TOOL for request in self._pending.values())
            menu = trust_menu(screen_text("".join(self._screen)))
            if menu is None:
                return False
            self._trust_offered = True
            request_id = str(uuid.uuid4())
            data = {"requestId": request_id, "kind": "approval", "category": "folder_trust",
                    "title": "Trust this folder in Claude Code?", "detail": menu.detail, "cwd": self.cwd,
                    "choices": ["approve", "deny"]}
            item = Item(f"approval:{request_id}", self._max_seq + 1, "approval", None, data)
            self._pending[request_id] = Pending(request_id, "approval", TRUST_TOOL, None,
                                                 {"detail": menu.detail}, item.id)
            self._last_activity = time.monotonic()
        self._show(item)
        self._set_state("waiting_approval", pending=data)
        return True

    def _loop(self) -> None:
        while not self._done:
            self._read_events()
            self._poll_transcript()
            self._check()
            if not self._done:
                time.sleep(self.poll_interval)

    def _close(self) -> None:
        spool = self._spool
        if spool is not None:
            try:
                (spool / "closed").write_text("closed", encoding="utf-8")
            except OSError:
                pass
        term = self.term
        if term is not None:
            alive = False
            try:
                alive = bool(term.isalive())
            except Exception:  # noqa: BLE001
                alive = False
            if alive:
                _kill_tree(self.pid)
                try:
                    term.terminate(force=True)
                except Exception:  # noqa: BLE001
                    pass
        if spool is not None:
            time.sleep(0.3)  # a waiting hook sees ``closed`` and exits before its folder goes
            shutil.rmtree(spool, ignore_errors=True)

    def _finish(self) -> None:
        state, error, code = self._final or ("failed", "Claude Code stopped unexpectedly.", "cli_exited")
        if state == "completed" and not any(item.kind == "reasoning" and (parse_time(item.at) or 0) >= self._began_at.timestamp() for item in self._items.values()):
            from .transparency import reasoning_data
            self._show(Item(f"reasoning-unreported:{self.run_id}", self._max_seq + 1, "reasoning", now_iso(),
                            reasoning_data("claude-code", None, source="terminal-transcript")))
        self._done = True
        self._set_state(state, error=error, code=code)
        self._session_changed(False)

    def _session_changed(self, active: bool) -> None:
        if self._on_session:
            try:
                self._on_session(self.session_id, active)
            except Exception:  # noqa: BLE001
                pass

    # ---- hook events

    def _read_events(self) -> None:
        spool = self._spool
        if spool is None:
            return
        try:
            names = sorted(name for name in os.listdir(spool / "events") if name.endswith(".json") and name not in self._seen_events)
        except OSError:
            return
        for name in names:
            try:
                record = json.loads((spool / "events" / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # still being written; read again next round
            self._seen_events.add(name)
            self._last_activity = time.monotonic()
            if isinstance(record, dict):
                self._on_event(str(record.get("event") or ""), str(record.get("requestId") or ""),
                               record.get("data") if isinstance(record.get("data"), dict) else {})

    def _on_event(self, event: str, request_id: str, data: dict[str, Any]) -> None:
        session = str(data.get("session_id") or "")
        if session and session != self.session_id and event in ("start", "prompt"):
            self._final = ("failed", f"Claude Code opened a different session ({session}) instead of this one. Neyvia stopped it.", "session_forked")
            self._done = True
            return
        if event == "start":
            self._started = True
            if self._local_command:
                self._prompted = True  # no prompt hook will come, and compacting can take minutes
            self._adopt_transcript(data.get("transcript_path"))
        elif event == "prompt":
            self._started = self._prompted = True
        elif event in ("permission", "question"):
            self._last_request_at = time.monotonic()
            self._on_request(event, request_id, data)
        elif event == "stop":
            self._stop_at = time.monotonic()
        elif event == "failure":
            kind = next((str(value) for value in data.values() if isinstance(value, str) and value in _ERROR_TEXT), "unknown")
            code, message = _ERROR_TEXT.get(kind, ("cli_failed", "Claude reported an error and stopped this turn."))
            self._failure = (code, message)
            self._stop_at = time.monotonic()
        elif event == "notify":
            self._on_notification(data)

    def _adopt_transcript(self, value: Any) -> None:
        if not isinstance(value, str) or not value:
            return
        path = Path(value)
        try:
            inside = path.resolve().is_relative_to(self.projects.resolve())
        except (OSError, ValueError):
            inside = False
        if inside and path.stem == self.session_id:
            self._path = path

    def _on_request(self, event: str, request_id: str, data: dict[str, Any]) -> None:
        tool = str(data.get("tool_name") or "")
        tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        tool_use_id = str(data.get("tool_use_id") or "") or None
        if self._interrupt_requested or self._done:
            pending = Pending(request_id, "question" if event == "question" else "approval", tool, tool_use_id, tool_input, "")
            self._reply(pending, {"behavior": "deny", "message": "The turn was stopped.", "interrupt": True})
            return
        if event == "question" or tool == QUESTION_TOOL:
            item = self._items.get(tool_use_id or "")
            fields = question_data(tool_input, request_id)
            if item is None:
                item = Item(tool_use_id or f"question:{request_id}", self._max_seq + 1, "question", None, fields)
            else:
                item.data.update(fields)
            self._show(item)
            with self._lock:
                self._pending[request_id] = Pending(request_id, "question", tool, tool_use_id, tool_input, item.id)
            self._set_state("waiting_input", pending={"requestId": request_id, "kind": "question", **item.data})
            return
        request = {"description": data.get("description") or data.get("message") or ""}
        fields = approval_data(request_id, tool, tool_input, request, tool_use_id, self.cwd)
        item = Item(f"approval:{request_id}", self._max_seq + 1, "approval", None, fields)
        self._show(item)
        with self._lock:
            self._pending[request_id] = Pending(request_id, "approval", tool, tool_use_id, tool_input, item.id)
        self._set_state("waiting_approval", pending={"requestId": request_id, "kind": "approval", **item.data})

    def _on_notification(self, data: dict[str, Any]) -> None:
        kind = str(data.get("notification_type") or "")
        with self._lock:
            waiting = bool(self._pending)
        if kind == "idle_prompt" and self._prompted:
            self._stop_at = self._stop_at or time.monotonic()
        elif kind in ("permission_prompt", "elicitation_dialog", "elicitation_url_dialog", "agent_needs_input") and not waiting:
            # The hook for the same prompt may still be starting: judge a few seconds later (``_check``).
            self._unshown = (time.monotonic(), collapse(str(data.get("message") or ""), 300))

    # ---- transcript

    def _poll_transcript(self) -> None:
        path = self._path or find_session_file(self.projects, self.session_id)
        if path is None:
            return
        first = self._path is None
        self._path = path
        try:
            usage = self._usage.poll(path)
            if usage is not None:
                self._emit({"type": "usage.updated", "sessionId": self.session_id, "usage": usage})
        except (OSError, ValueError):
            pass  # A transcript still being written will be retried at the next poll.
        try:
            store = self._store_for(path, self.session_id, self.cwd)
            items, _, cursor = store.page(cursor=self._cursor, before_seq=None, limit=200)
        except OSError:
            return
        self._cursor = cursor
        for item in items:
            self._note_local_result(item)
            known = self._items.get(item.id)
            if known is not None and known.data.get("requestId") and item.kind in ("question", "approval"):
                item.data = {**item.data, **{k: v for k, v in known.data.items() if k in ("answers", "answered", "decision")}}
            self._show(item)
        if items:
            self._last_activity = time.monotonic()
        if first:
            self._session_changed(True)
        if self._context_for is not None:
            try:
                context = asdict(self._context_for(path))
            except (OSError, ValueError):
                return
            if context.get("used_tokens") is not None and {**context, "updated_at": None} != {**(self._context or {}), "updated_at": None}:
                self._context = context
                self._emit({"type": "context.updated", "sessionId": self.session_id, "context": context})

    @checked("providers.terminal.compact")
    def _note_local_result(self, item: Item) -> None:
        """A /compact turn is over when its boundary (or the command's own output line) shows up in the transcript."""
        if not self._local_command or self._stop_at is not None or not _since(item.at, self._began_at):
            return
        if item.kind == "compaction" and item.data.get("state") == "completed":
            self._prompted, self._stop_at = True, time.monotonic()
        elif item.kind == "notice" and str(item.data.get("text") or "").strip() and not str(item.data.get("text")).startswith("/"):
            self._prompted, self._stop_at = True, time.monotonic()  # e.g. "Not enough messages to compact."

    # ---- deadlines and endings

    def _check(self) -> None:
        if self._done:
            return
        now = time.monotonic()
        trust_waiting = self._offer_folder_trust()
        try:
            alive = bool(self.term.isalive())
        except Exception:  # noqa: BLE001
            alive = False
        if self._stop_at is not None and now - self._stop_at >= STOP_SETTLE_SECONDS:
            self._poll_transcript()
            self._final = ("failed", self._failure[1], self._failure[0]) if self._failure else ("completed", None, None)
            self._done = True
        elif self._interrupt_deadline is not None and now >= self._interrupt_deadline:
            self._poll_transcript()
            self._final = ("interrupted", self._interrupt_reason or "Stopped.", None)
            self._done = True
        elif not alive:
            self._read_events()
            self._poll_transcript()
            if self._stop_at is not None:
                self._final = ("failed", self._failure[1], self._failure[0]) if self._failure else ("completed", None, None)
            elif self._interrupt_requested:
                self._final = ("interrupted", self._interrupt_reason or "Stopped.", None)
            else:
                self._final = ("failed", self._explain("Claude Code closed before finishing this turn."), "cli_exited")
            self._done = True
        elif not self._prompted and not trust_waiting and now - self._spawned_at > self.startup_timeout:
            what = "did not take the message" if self._started else "did not start"
            self._final = ("failed", self._explain(f"Claude Code {what} in plan-limits mode."), "terminal_blocked")
            self._done = True
        else:
            with self._lock:
                waiting = bool(self._pending)
            if self._unshown is not None and now - self._unshown[0] > 3.0:
                seen_at, text = self._unshown
                self._unshown = None
                if not waiting and self._last_request_at < seen_at - 1.0:
                    self._notice(f"Claude Code asked for something Neyvia can't show here{': ' + text if text else ''}. The turn was stopped; "
                                 "continue it in Claude Code, or switch this chat to Agent SDK credit.", "warning")
                    self.interrupt("Claude Code needed an answer Neyvia can't show.")
                    return
            limit = self.pending_timeout if waiting else self.idle_timeout
            if not self._interrupt_requested and now - self._last_activity > limit:
                self.interrupt(f"No {'answer' if waiting else 'progress'} for {int(limit // 60)} minutes; the turn was stopped.")

    def _explain(self, base: str) -> str:
        hint = self._screen_hint()
        lowered = hint.lower()
        if "trust" in lowered and "folder" in lowered:
            return base + " It is asking whether to trust this folder: open the folder once in Claude Code and accept, then try again."
        if "login" in lowered or "sign in" in lowered or "/login" in lowered:
            return base + " It is not signed in on this PC: run `claude` in a terminal and sign in, then try again."
        return base + (f" Last thing it showed: “{hint[-160:]}”" if hint else "")
