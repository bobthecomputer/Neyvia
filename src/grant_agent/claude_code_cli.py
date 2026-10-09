"""Open Claude Code's real CLI for the person: ``neyvia.claude.open_cli`` and its UI button.

Two ways, both only on the person's click:

* **View** (a Neyvia-started turn is running): the turn's hidden ConPTY is shown in Neyvia's terminal pane through a
  ``LiveView`` registered next to the pane's own terminals. It is read-only. "Take over" lets the person's own
  keystrokes through (their input, nothing Neyvia types). Attaching resizes the ConPTY to the pane, which makes Claude
  Code redraw cleanly.
* **Terminal** (the session is idle or finished): a generated ``.cmd`` that sets the environment and runs
  ``claude --plugin-dir <mod> --resume <session>`` in a new Windows Terminal window. Neyvia holds the session (it starts
  no turn in it) until the mod reports the session ended.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from . import claude_code_host as host

BUFFER_CHARS = 512 * 1024
HOLD_SECONDS = 6 * 3600
UNSAFE = '"%^&|<>\r\n'


class LiveView:
    """A running Claude Code turn's ConPTY as a pane terminal. Duck-types ``neyvia_panes.Terminal``."""

    def __init__(self, run_id: str, cwd: str, term: Any, title: str = "Claude Code"):
        self.id = "claude:" + run_id
        self.run_id = run_id
        self.cwd = str(cwd)
        self.shell = "claude"
        self.title = title
        self.term = term
        self.created = self.last_output = time.time()
        self.chunks: list[str] = []
        self.start = 0
        self.total = 0
        self.alive = True
        self.exit_code = None
        self.cond = threading.Condition()
        self.target = ""
        self.typed = ""
        self.readonly = True
        self.takeover = False
        self.size: tuple[int, int] | None = None

    # fed by the run's reader thread
    def feed(self, data: str) -> None:
        with self.cond:
            self.chunks.append(data)
            self.total += len(data)
            self.last_output = time.time()
            size = self.total - self.start
            while size > BUFFER_CHARS and len(self.chunks) > 1:
                dropped = self.chunks.pop(0)
                self.start += len(dropped)
                size -= len(dropped)
            self.cond.notify_all()

    def finish(self, code: int | None = None) -> None:
        with self.cond:
            self.alive = False
            self.exit_code = code
            self.cond.notify_all()

    def since(self, cursor: int) -> tuple[str, int, bool]:
        with self.cond:
            reset = cursor < self.start
            text = "".join(self.chunks)
            return text[max(0, cursor - self.start):], self.total, reset

    def write(self, data: str) -> None:
        if not self.alive:
            raise ValueError("This Claude Code turn has ended")
        if not self.takeover:
            raise ValueError("Read-only view. Press Take over to type into Claude Code yourself.")
        self.term.write(data)  # the person's own keystrokes

    def resize(self, cols: int, rows: int) -> None:
        if self.alive and (cols, rows) != self.size:
            self.size = (cols, rows)
            self.term.setwinsize(rows, cols)

    def close(self) -> None:
        unregister(self.id)  # closing the tab never ends the turn

    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "cwd": self.cwd, "target": self.target, "typed": "", "shell": "claude", "alive": self.alive,
                "exitCode": self.exit_code, "created": self.created, "lastOutput": self.last_output, "cursor": self.total,
                "readonly": self.readonly, "takeover": self.takeover, "claude": True, "title": self.title}


def register(view: LiveView) -> None:
    from . import neyvia_panes
    with neyvia_panes._terminal_lock:
        neyvia_panes._terminals[view.id] = view


def unregister(identity: str) -> None:
    from . import neyvia_panes
    with neyvia_panes._terminal_lock:
        neyvia_panes._terminals.pop(identity, None)


def retire(view: LiveView, delay: float = 90.0) -> None:
    """The ended view stays readable for a minute and a half, then leaves the pane's list."""
    view.finish(getattr(getattr(view.term, "proc", None), "exitstatus", None))
    timer = threading.Timer(delay, unregister, args=(view.id,))
    timer.daemon = True
    timer.start()


def set_takeover(identity: str, on: bool) -> dict[str, Any]:
    from . import neyvia_panes
    found = neyvia_panes._terminals.get(str(identity))
    if not isinstance(found, LiveView):
        raise ValueError("That is not a Claude Code view")
    found.takeover = bool(on)
    return {"ok": True, "takeover": found.takeover}


# ---------------------------------------------------------------- the idle-session launcher

def _plugin_env() -> dict[str, str]:
    from .claude_code_mods import launch_env
    env = launch_env()
    env.pop("NEYVIA_RUN_ID", None)  # a session of the person's own: the mod reports as adhoc
    return env


def _quote(value: str) -> str:
    if any(ch in value for ch in '"%^&|<>\r\n'):
        raise ValueError("A path contains a character the launcher cannot quote safely")
    return '"' + value + '"'


def launcher_script(state_root: Path, session: str, cwd: str, claude: str) -> Path:
    from .claude_code_mods import PLUGIN_DIR
    env = _plugin_env()
    lines = ["@echo off", "title Claude Code (opened from Neyvia)"]
    for key, value in env.items():
        if any(ch in value for ch in UNSAFE):
            raise ValueError(f"{key} holds a character the launcher cannot quote safely")
        lines.append(f'set "{key}={value}"')
    lines += [f"cd /d {_quote(cwd)}", f"{_quote(claude)} --plugin-dir {_quote(str(PLUGIN_DIR))} --resume {session}", "pause"]
    folder = Path(state_root) / ".neyvia" / "cli"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"open-{session}.cmd"
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return path


def terminal_argv(script: Path, cwd: str) -> list[str]:
    return ["wt", "-w", "new", "-d", cwd, "cmd", "/k", str(script)]


def open_cli(service, args: dict[str, Any]) -> dict[str, Any]:
    """The tool behind the "Open CLI" button. ``fromClick`` must be true: it is the person's action, never an agent's."""
    if args.get("fromClick") is not True:
        raise ValueError("Open CLI is for the person to start: use the Open CLI button in the session")
    from .connected_sessions.claude_items import parse_identity
    from .claude_code_activity import _active_runs
    target = str(args.get("session") or "").strip()
    try:
        raw = parse_identity(target) if target.startswith("external:") else target
    except ValueError as exc:
        raise ValueError("session is a Claude Code session id") from exc
    mode = args.get("mode") or "auto"
    broker = service.broker()
    running = next((run for run in _active_runs(broker) if (run.get("app") == "claude-code") and raw in str(run.get("sessionId") or "")), None)
    if running and mode in {"auto", "view"}:
        from . import neyvia_panes
        view = neyvia_panes._terminals.get("claude:" + running["runId"])
        if view is None:
            return {"ok": False, "error": "This turn does not run in a terminal (it uses Agent SDK credit, not plan limits), so there is no CLI to show. Its event log is in the session."}
        return {"ok": True, "mode": "view", "terminalId": view.id, "target": view.id, "readonly": True}
    if running:
        raise ValueError("A Neyvia turn is running in this session; open the live view instead")
    claude = shutil.which("claude.exe") or shutil.which("claude.cmd") or shutil.which("claude")
    if not claude:
        raise ValueError("Claude Code is not installed on this PC")
    from .connected_sessions.claude_items import session_identity
    cwd = str(args.get("cwd") or "") or (broker.session_cwd(target if target.startswith("external:") else session_identity(raw)) or "")
    if not cwd or not os.path.isdir(cwd):
        raise ValueError("The folder for this session does not exist any more")
    script = launcher_script(service.bus.root, raw, cwd, claude)
    argv = terminal_argv(script, cwd)
    host.hold(raw, "Open in a terminal window")
    launched = False
    if not args.get("dryRun"):
        subprocess.Popen(argv, cwd=cwd, close_fds=True)
        launched = True
    return {"ok": True, "mode": "terminal", "argv": argv, "script": str(script), "launched": launched,
            "held": True, "note": "Neyvia starts no turn in this session until it ends in the terminal."}
