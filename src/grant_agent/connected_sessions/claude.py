"""Claude Code adapter for connected sessions.

Reads the sessions Claude Code keeps under ``~/.claude/projects`` (made in the terminal CLI or the
Claude desktop app's Code tab) and continues the SAME session by driving the official, unmodified
``claude`` CLI over stream-json (see ``claude_stream``). Nothing here reads or relays credentials:
the CLI signs in with the user's own login, and Neyvia never sets an API key or token.
"""
from __future__ import annotations

import dataclasses

import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..external_chat_inventory import _host
from ..subprocess_utils import hidden_windows_subprocess_kwargs
from ..proofs_a_providers import checked
from .claude_items import (
    collapse, folder_name, int_or_none, parse_identity, session_identity, session_origin, valid_session_id,
)
from .claude_stream import (
    ClaudeRun, ClaudeSessionError, IDLE_TIMEOUT_SECONDS, INTERRUPT_GRACE_SECONDS, PENDING_TIMEOUT_SECONDS, child_env,
    cli_prefix, kill_process_tree, start_process,
)
from .claude_login import CliLogin
from .claude_terminal import ClaudeTerminalRun, terminal_available
from .claude_transcript import StoreCache, SummaryIndex, config_dir, find_session_file, iter_session_files
from .model import Capabilities, ContextUsage, Emit, ItemsPage, LiveOwner, SessionStatus, SessionSummary, TurnOptions

__all__ = ["ClaudeAdapter", "ClaudeSessionError"]

AGENTS_TTL_SECONDS = 2.0
# Claude Code rewrites ``<config>/sessions/<pid>.json`` whenever a session's status
# changes and removes it on exit. While that folder is unchanged the last
# ``claude agents --json`` (~0.5 s of process start per call) still holds; it is
# re-run at least this often anyway, for a process that died without cleaning up.
AGENTS_MAX_AGE_SECONDS = 30.0
AGENTS_TIMEOUT_SECONDS = 8.0
MODELS_TTL_SECONDS = 600.0
AUTH_TTL_SECONDS = 300.0
LISTING_TTL_SECONDS = 60.0
MAX_MESSAGE_CHARS = 100_000
_SESSION_LEAVING = ("/clear", "/reset", "/new", "/branch", "/fork", "/resume")
_FALLBACK_ALIASES = ("opus", "sonnet", "haiku")

_MODE_LABELS = {
    "manual": ("Ask before acting", "Ask before file edits and shell commands."),
    "acceptEdits": ("Accept edits", "Apply file edits without asking; still ask before shell commands."),
    "plan": ("Plan", "Explore and plan without changing files."),
    "auto": ("Auto", "A classifier approves or denies each prompt."),
    "dontAsk": ("Don't ask", "Deny anything that would need a prompt."),
    "bypassPermissions": ("Bypass permissions", "Run everything without asking. Only for a sandbox."),
}
_STATUS_OF_RUN = {"running": "working", "queued": "working", "waiting_approval": "waiting_approval", "waiting_input": "waiting_input"}


# Claude Code sessions started from a terminal or a script (not the desktop app) are grouped as CLI chats.
CLI_ENTRYPOINTS = frozenset({"cli", "sdk-cli", "sdk-py", "sdk-ts"})

class ClaudeAdapter:
    app = "claude-code"

    def __init__(self, *, state_root: str | Path | None = None, config_dir: str | Path | None = None, cli_path: str | Path | None = None,
                 host: dict[str, str] | None = None, extra_args: list[str] | None = None,
                 extra_env: dict[str, str] | None = None, idle_timeout: float = IDLE_TIMEOUT_SECONDS,
                 pending_timeout: float = PENDING_TIMEOUT_SECONDS, interrupt_grace: float = INTERRUPT_GRACE_SECONDS,
                 context_probe: bool = True, agents_ttl: float = AGENTS_TTL_SECONDS):
        self._config_dir = Path(config_dir).expanduser() if config_dir else None
        self.state_root = Path(state_root).resolve() if state_root is not None else None
        if self.state_root is not None:
            from .plan_limits import claude_limits
            claude_limits(self.state_root)  # Registry supplies the state root before any rate event arrives.
        # ``cli_path`` may be one executable or a command list such as [python, fake_cli.py] (tests, proof rigs).
        self._cli_override = cli_prefix(cli_path) if cli_path else None
        self._host = host or _host()
        self.extra_args, self.extra_env = list(extra_args or []), dict(extra_env or {})
        self.idle_timeout, self.pending_timeout, self.interrupt_grace = idle_timeout, pending_timeout, interrupt_grace
        self.context_probe, self.agents_ttl = context_probe, agents_ttl
        self._lock = threading.RLock()
        self._indexes: dict[str, SummaryIndex] = {}
        self._stores = StoreCache()
        self._runs: dict[str, ClaudeRun] = {}
        self._active_sessions: set[str] = set()
        self._windows: dict[str, int] = {}
        self._live_media: dict[str, tuple[bytes, str]] = {}
        self._login = CliLogin()
        self._agents_cache: tuple[float, list[dict] | None] = (0.0, None)
        self._agents_signature: tuple | None = None
        self._agents_lock = threading.Lock()
        self._models_cache: tuple[float, list[dict]] | None = None
        self._help_cache: tuple[float, str] | None = None
        self._listing_cache: dict[str, tuple[float, Any]] = {}
        self._auth_cache: tuple[float, dict[str, Any]] | None = None
        self.terminal_spawn = None  # tests replace the hidden-terminal launcher

    # ------------------------------------------------------------------ paths and the CLI

    def _projects(self) -> Path:
        return (self._config_dir or config_dir()) / "projects"

    def _cli(self) -> list[str] | None:
        """Command that starts the CLI, or None when it is not installed."""
        if self._cli_override is not None:
            return self._cli_override if Path(self._cli_override[-1]).is_file() else None
        from ..connected_claude_chats import _cli_path  # resolves the real claude.exe behind npm's shim

        path = _cli_path()
        return [str(path)] if path else None

    def available(self) -> tuple[bool, str | None]:
        if self._cli() is None:
            return False, "Claude Code is not installed on this PC (the claude command was not found)."
        return True, None

    def _run_cli(self, args: list[str], timeout: float, cwd: str | None = None) -> subprocess.CompletedProcess | None:
        cli = self._cli()
        if cli is None:
            return None
        try:
            return subprocess.run([*cli, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout, cwd=cwd or str(Path.home()), env=child_env(self.extra_env), check=False,
                                  **hidden_windows_subprocess_kwargs())
        except (OSError, subprocess.TimeoutExpired):
            return None

    # ------------------------------------------------------------------ live sessions

    @checked("providers.claude.live")
    def _agents_entries(self, force: bool = False) -> list[dict] | None:
        """Rows of ``claude agents --json`` (sessions live right now), cached ~2 s; None when it cannot be read."""
        with self._agents_lock:
            stamp, cached = self._agents_cache
            age = time.monotonic() - stamp
            if not force and age < self.agents_ttl:
                return cached
            signature = self._sessions_signature()
            if (not force and self.agents_ttl > 0 and cached is not None and signature is not None
                    and signature == self._agents_signature and age < AGENTS_MAX_AGE_SECONDS):
                return cached
            done = self._run_cli(["agents", "--json"], AGENTS_TIMEOUT_SECONDS)
            rows: list[dict] | None = None
            if done is not None and done.returncode == 0:
                try:
                    value = json.loads(done.stdout)
                    rows = [row for row in value if isinstance(row, dict)] if isinstance(value, list) else None
                except ValueError:
                    rows = None
            self._agents_cache = (time.monotonic(), rows)
            self._agents_signature = signature
            return rows

    def _sessions_signature(self) -> tuple | None:
        """Names, sizes and write times of Claude Code's live-session files; None when unreadable."""
        folder = (self._config_dir or config_dir()) / "sessions"
        try:
            with os.scandir(folder) as entries:
                rows = []
                for entry in entries:
                    if entry.name.endswith(".json"):
                        info = entry.stat()
                        rows.append((entry.name, info.st_mtime_ns, info.st_size))
        except OSError:
            return None
        return tuple(sorted(rows))

    def _own_pids(self) -> set[int]:
        with self._lock:
            return {run.pid for run in self._runs.values() if run.pid}

    def live_status(self) -> dict[str, tuple[SessionStatus, LiveOwner | None]]:
        result: dict[str, tuple[SessionStatus, LiveOwner | None]] = {}
        own = self._own_pids()
        for row in self._agents_entries() or []:
            session = str(row.get("sessionId") or "")
            if not session or row.get("pid") in own:
                continue
            try:
                identity = session_identity(valid_session_id(session), self._host)
            except ValueError:
                continue
            status: SessionStatus = "working" if row.get("status") == "busy" else "idle" if row.get("status") == "idle" else "unknown"
            result[identity] = (status, "cli" if row.get("kind") == "background" else "app")
        with self._lock:
            for run in self._runs.values():
                if run.session_id:
                    result[session_identity(run.session_id, self._host)] = (_STATUS_OF_RUN.get(run.state, "working"), "neyvia")  # type: ignore[assignment]
        return result

    def _foreign_owner(self, session_id: str) -> dict[str, Any] | None:
        """Who has this session open right now (per ``claude agents --json``), excluding Neyvia's own processes."""
        rows = self._agents_entries(force=True)
        if rows is None:
            raise ClaudeSessionError("live_check_unavailable", "Neyvia could not check whether this session is open in Claude Code, so it did not send. Try again in a moment.")
        own = self._own_pids()
        for row in rows:
            if row.get("sessionId") == session_id and row.get("pid") not in own:
                return row
        return None

    # ------------------------------------------------------------------ list

    def _index(self, path: Path) -> SummaryIndex:
        key = str(path)
        with self._lock:
            index = self._indexes.get(key)
            if index is None:
                index = self._indexes[key] = SummaryIndex(path, path.stem)
        index.refresh()
        return index

    @checked("providers.claude.capabilities")
    def _capabilities(self, owner: LiveOwner | None, status: SessionStatus | None = None, *, installed: bool | None = None) -> Capabilities:
        if not (self._cli() is not None if installed is None else installed):
            return Capabilities(reason="Claude Code is not installed on this PC.")
        elsewhere = owner in ("app", "cli")
        # Open in the Claude app or a terminal but idle: Neyvia adds to the same chat. Only while
        # Claude is working there would two programs write one chat at once, so only then it waits.
        # A background session ("cli") is a headless agent that can resume by itself: never shared.
        busy = elsewhere and (status != "idle" or owner == "cli")
        where = "the Claude app" if owner == "app" else "a background Claude Code session"
        return Capabilities(
            continue_session=not busy, new_session=True, stop=True, approvals=True, questions=True, images=True,
            compact=not busy, steer=not elsewhere, model_choice=True, effort_choice=True, permission_choice=True,
            billing="agent-sdk-credits", fork=elsewhere,
            reason=(f"Claude is working on this chat in {where} right now. You can send here once it finishes, "
                    "or start a branch from the + menu.") if busy and owner == "app" else
                   (f"This chat belongs to {where}. Continue it there, or start a branch from the + menu.") if busy else None,
        )

    @checked("providers.claude.summary")
    def _summary(self, index: SummaryIndex, live: dict[str, tuple[SessionStatus, LiveOwner | None]] | None,
                 installed: bool | None = None) -> SessionSummary:
        identity = session_identity(index.session_id, self._host)
        status, owner = ("unknown", None) if live is None else live.get(identity, ("idle", None))
        return SessionSummary(
            id=identity, app="claude-code", title=index.title, updated_at=index.updated_iso(), created_at=index.created,
            cwd=index.cwd, project=folder_name(index.cwd), git_branch=index.git_branch, model=index.model, status=status,
            live_owner=owner, origin=session_origin(index.cwd), background=index.entrypoint in CLI_ENTRYPOINTS,
            host_device_id=self._host["deviceId"],  # type: ignore[arg-type]
            host_device_name=self._host["deviceName"], archived=False, capabilities=self._capabilities(owner, status, installed=installed),
        )

    def list_sessions(self, *, include_archived: bool = False) -> list[SessionSummary]:
        rows_live = self._agents_entries() is not None
        live = self.live_status() if rows_live else None
        installed = self._cli() is not None  # one PATH lookup per listing, not one per chat
        summaries = []
        for path in iter_session_files(self._projects()):
            try:
                index = self._index(path)
            except OSError:
                continue
            if index.has_content:
                summaries.append(self._summary(index, live, installed))
        summaries.sort(key=lambda summary: summary.updated_at or "", reverse=True)
        return summaries

    # ------------------------------------------------------------------ read

    def _session_id(self, session_id: str) -> str:
        try:
            return parse_identity(session_id, self._host) if str(session_id).startswith("external:") else valid_session_id(str(session_id))
        except ValueError as exc:
            raise ClaudeSessionError("session_unavailable", "This Claude Code session is not available on this device.") from exc

    def _locate(self, session_id: str) -> tuple[str, Path]:
        sid = self._session_id(session_id)
        path = find_session_file(self._projects(), sid)
        if path is None:
            raise ClaudeSessionError("session_unavailable", "This Claude Code session is not available on this device.")
        return sid, path

    def _settings(self) -> dict[str, Any]:
        """Only the few non-secret keys this adapter uses; the rest of settings.json (env, helpers) is never kept."""
        try:
            raw = json.loads(((self._config_dir or config_dir()) / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        permissions = raw.get("permissions") if isinstance(raw.get("permissions"), dict) else {}
        return {
            "model": raw["model"] if isinstance(raw.get("model"), str) else None,
            "defaultMode": permissions.get("defaultMode") if isinstance(permissions.get("defaultMode"), str) else None,
            "effortLevel": raw["effortLevel"] if isinstance(raw.get("effortLevel"), str) else None,
            "autoCompactWindow": int_or_none(raw.get("autoCompactWindow")),
        }

    @checked("providers.claude.context")
    def _context(self, index: SummaryIndex) -> ContextUsage:
        threshold = self._settings().get("autoCompactWindow")
        return ContextUsage(
            used_tokens=index.used, window_tokens=self._windows.get(index.model or ""), auto_compact_tokens=threshold,
            source="claude-transcript" + ("+settings" if threshold else ""), updated_at=index.used_at,
        )

    @checked("providers.claude.page")
    def read(self, session_id: str, *, cursor: str | None = None, before_seq: int | None = None, limit: int = 200) -> ItemsPage:
        sid, path = self._locate(session_id)
        try:
            index = self._index(path)
            store = self._stores.get(path, sid, index.cwd)
            items, has_earlier, new_cursor = store.page(cursor=cursor, before_seq=before_seq, limit=limit)
            plan = store.plan()
        except OSError as exc:
            raise ClaudeSessionError("session_unavailable", "This Claude Code session could not be read right now.") from exc
        live = self.live_status() if self._agents_entries() is not None else None
        return ItemsPage(session=self._summary(index, live), items=items, context=self._context(index), cursor=new_cursor,
                         has_earlier=has_earlier, plan=plan)

    def tool_output(self, session_id: str, item_id: str) -> str | None:
        """Full output of a tool item (pages carry at most 8 KB)."""
        sid, path = self._locate(session_id)
        return self._stores.get(path, sid, None).tool_output(item_id)

    @checked("providers.claude.media")
    def read_media(self, session_id: str, media_ref: str) -> tuple[bytes, str, str] | None:
        """(bytes, mime, name) for the ``mediaRef`` of an attachment, or None."""
        if not re.fullmatch(r"[0-9a-f]{64}", str(media_ref)):
            return None
        with self._lock:
            live = self._live_media.get(media_ref)
        if live is not None:
            return live[0], live[1], "image"
        sid, path = self._locate(session_id)
        index = self._index(path)
        return self._stores.get(path, sid, index.cwd).read_media(media_ref)

    # ------------------------------------------------------------------ options

    def _help_text(self) -> str:
        with self._lock:
            if self._help_cache and time.monotonic() - self._help_cache[0] < 3600:
                return self._help_cache[1]
        done = self._run_cli(["--help"], 15)
        text = done.stdout if done is not None and done.returncode == 0 else ""
        with self._lock:
            self._help_cache = (time.monotonic(), text)
        return text

    def _help_choices(self, flag: str) -> list[str]:
        """Values ``claude --help`` lists for a flag: ``(choices: "a", "b")`` or a plain ``(a, b, c)``."""
        text = self._help_text()
        start = text.find(f"--{flag} ")
        if start < 0:
            return []
        block = re.split(r"\n\s{0,4}-", text[start + len(flag) + 2:], maxsplit=1)[0]
        flat = " ".join(block.split())
        quoted = re.search(r"choices: ((?:\"[^\"]+\",? ?)+)", flat)
        if quoted:
            return re.findall(r'"([^"]+)"', quoted.group(1))
        plain = re.search(r"\(([A-Za-z0-9_-]+(?:, [A-Za-z0-9_-]+)+)\)", flat)
        return [part.strip() for part in plain.group(1).split(",")] if plain else []

    def _remember_models(self, models: list) -> None:
        cleaned = [m for m in models if isinstance(m, dict) and isinstance(m.get("value"), str)]
        if cleaned:
            with self._lock:
                self._models_cache = (time.monotonic(), cleaned)

    def _probe_models(self, cwd: str | None) -> list[dict]:
        """Model list straight from the CLI (``initialize`` + ``list_models`` control requests; no model call, no credits)."""
        with self._lock:
            if self._models_cache and time.monotonic() - self._models_cache[0] < MODELS_TTL_SECONDS:
                return self._models_cache[1]
        cli = self._cli()
        if cli is None:
            return []
        argv = [*cli, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
        folder = cwd if cwd and os.path.isdir(cwd) else str(Path.home())
        try:
            process = start_process(argv + self.extra_args, folder, child_env(self.extra_env))
        except OSError:
            return []
        models: list[dict] = []
        results: dict[str, Any] = {}

        def read() -> None:
            try:
                for raw in iter(process.stdout.readline, b""):  # type: ignore[union-attr]
                    try:
                        message = json.loads(raw.decode("utf-8", errors="replace"))
                    except ValueError:
                        continue
                    response = message.get("response") if isinstance(message, dict) else None
                    if isinstance(response, dict) and response.get("request_id") in ("neyvia_models",):
                        results["models"] = (response.get("response") or {}).get("models")
                        return
            except (OSError, ValueError):
                return

        reader = threading.Thread(target=read, daemon=True, name="claude-models-probe")
        reader.start()
        threading.Thread(target=lambda: [process.stderr.read()], daemon=True).start()  # type: ignore[union-attr]
        try:
            for request_id, subtype in (("neyvia_init", "initialize"), ("neyvia_models", "list_models")):
                line = json.dumps({"type": "control_request", "request_id": request_id, "request": {"subtype": subtype}}) + "\n"
                process.stdin.write(line.encode())  # type: ignore[union-attr]
                process.stdin.flush()  # type: ignore[union-attr]
            reader.join(20)
        except (OSError, ValueError):
            pass
        finally:
            try:
                process.stdin.close()  # type: ignore[union-attr]
            except OSError:
                pass
            kill_process_tree(process)
        if isinstance(results.get("models"), list):
            models = results["models"]
            self._remember_models(models)
        return models

    def _model_options(self, cwd: str | None, current: str | None, settings: dict[str, Any]) -> list[dict[str, Any]]:
        efforts_all = self._help_choices("effort")
        reported = self._probe_models(cwd)
        options: list[dict[str, Any]] = []
        for entry in reported:
            efforts = list(entry.get("supportedEffortLevels") or []) if entry.get("supportsEffort") else []
            options.append({"id": entry["value"], "label": str(entry.get("displayName") or entry["value"]),
                            "efforts": efforts, "default": False, "resolved": entry.get("resolvedModel"),
                            "description": collapse(entry.get("description") or "", 200) or None})
        have = {option["id"] for option in options}
        for alias in _FALLBACK_ALIASES:
            if alias not in have:
                options.append({"id": alias, "label": alias.capitalize(), "efforts": list(efforts_all), "default": False})
        if current and current not in have and all(current != option.get("resolved") for option in options):
            options.append({"id": current, "label": current, "efforts": [], "default": False})
        chosen = settings.get("model")
        target = next((option for option in options if option["id"] == chosen), None) if chosen else \
            next((option for option in options if option["id"] == "default"), None)
        if target:
            target["default"] = True
        for option in options:
            option.pop("resolved", None)
        return options

    def _skills(self, cwd: str | None) -> list[dict[str, str]]:
        roots = [("user", (self._config_dir or config_dir()) / "skills")]
        if cwd:
            roots.append(("project", Path(cwd) / ".claude" / "skills"))
        found: list[dict[str, str]] = []
        for scope, root in roots:
            try:
                names = sorted(entry.name for entry in os.scandir(root) if entry.is_dir())
            except OSError:
                continue
            for name in names:
                skill = root / name / "SKILL.md"
                if skill.is_file():
                    found.append({"name": name, "scope": scope, "description": self._skill_description(skill)})
        return found

    @staticmethod
    def _skill_description(path: Path) -> str:
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            return ""
        match = re.search(r"^description:\s*(.+)$", head, re.MULTILINE)
        return collapse(match.group(1).strip("\"' "), 200) if match else ""

    def _cached_listing(self, key: str, loader) -> Any:
        with self._lock:
            hit = self._listing_cache.get(key)
            if hit and time.monotonic() - hit[0] < LISTING_TTL_SECONDS:
                return hit[1]
        value = loader()
        with self._lock:
            self._listing_cache[key] = (time.monotonic(), value)
        return value

    def _mcp_servers(self) -> list[dict[str, Any]]:
        def load() -> list[dict[str, Any]]:
            done = self._run_cli(["mcp", "list"], 12)
            if done is None or done.returncode != 0:
                return []
            servers = []
            for line in done.stdout.splitlines():
                match = re.match(r"^(?P<name>[^:\s][^:]*?):\s+(?P<target>.+?)\s+-\s+(?P<status>\S.*)$", line.strip())
                if not match:
                    continue
                status = match["status"].lower()
                state = "connected" if "connected" in status and "not" not in status else "needs_auth" if "auth" in status else "failed"
                entry = {"name": match["name"].strip(), "state": state}
                if state == "failed":
                    entry["error"] = collapse(match["status"], 200)
                servers.append(entry)
            return servers

        return self._cached_listing("mcp", load)

    def _plugins(self) -> list[dict[str, Any]]:
        def load() -> list[dict[str, Any]]:
            done = self._run_cli(["plugin", "list", "--json"], 12)
            if done is None or done.returncode != 0:
                return []
            try:
                value = json.loads(done.stdout)
            except ValueError:
                return []
            plugins = []
            for entry in value if isinstance(value, list) else []:
                if isinstance(entry, dict) and (entry.get("id") or entry.get("name")):
                    name = str(entry.get("id") or entry.get("name"))
                    enabled = entry.get("enabled")
                    plugins.append({"id": name, "label": str(entry.get("name") or name),
                                    "state": entry.get("state") or ("enabled" if enabled is not False else "disabled")})
            return plugins

        return self._cached_listing("plugins", load)

    @checked("providers.claude.options")
    def options(self, session_id: str | None = None) -> dict[str, Any]:
        cwd = current = None
        if session_id:
            try:
                _, path = self._locate(session_id)
                index = self._index(path)
                cwd, current = index.cwd, index.model
            except ClaudeSessionError:
                pass
        settings = self._settings()
        self._help_text()  # once, before the workers below read it
        with ThreadPoolExecutor(max_workers=4) as pool:
            models = pool.submit(self._model_options, cwd, current, settings)
            servers = pool.submit(self._mcp_servers)
            plugins = pool.submit(self._plugins)
            modes = self._help_choices("permission-mode")
            result: dict[str, Any] = {"models": models.result(), "mcpServers": servers.result(), "plugins": plugins.result()}
        default_mode = settings.get("defaultMode") or ("manual" if "manual" in modes else None)
        result["permissionModes"] = [
            {"id": mode, "label": _MODE_LABELS.get(mode, (mode, ""))[0], "description": _MODE_LABELS.get(mode, (mode, ""))[1],
             "default": mode == default_mode}
            for mode in modes
        ]
        result["efforts"] = self._help_choices("effort")
        result["defaultEffort"] = settings.get("effortLevel")
        result["skills"] = self._skills(cwd)
        result["auth"] = self._auth()
        result["transports"] = self._transports(result["auth"])
        return result

    # ------------------------------------------------------------------ how turns run and are billed

    def auth(self, force: bool = False) -> dict[str, Any]:
        return self._auth(force)

    def sign_in(self) -> dict[str, Any]:
        """Start Claude Code's own sign-in (``claude auth login``) on this PC and return its claude.com link.

        The link works from any device: the user signs in on Anthropic's page, which shows a one-time
        code, and pastes it into ``finish_sign_in``; Neyvia hands it to the waiting CLI the way a
        terminal would. Neyvia never sees a password, and keeps neither the code nor any token.
        """
        current = self._auth(True)
        if current.get("kind") == "subscription":
            return {"state": "signed-in", "auth": current}
        cli = self._cli()
        if cli is None:
            raise ClaudeSessionError("cli_unavailable", "Claude Code is not installed on this PC.")
        url = self._login.start(cli, Path.home(), child_env(self.extra_env))
        with self._lock:
            self._auth_cache = None
        return {"state": "paste", "verificationUrl": url, "auth": current,
                "message": "Open the link on any device and sign in with your Claude account, then paste the code it shows."}

    def finish_sign_in(self, code: Any) -> dict[str, Any]:
        """Give the waiting ``claude auth login`` the code from Anthropic's page."""
        detail = self._login.finish(code)
        with self._lock:
            self._auth_cache = None
        auth = self._auth(True)
        if auth.get("kind") == "subscription":
            return {"state": "signed-in", "auth": auth}
        raise ClaudeSessionError("sign_in_failed", "Claude Code didn't accept that code" + (f" ({detail})" if detail else "")
                                 + ". Start the sign-in again and copy the whole code.")

    @checked("providers.claude.auth")
    def _auth(self, force: bool = False) -> dict[str, Any]:
        """How the CLI signs in, from ``claude auth status`` (no secrets: it reports the method, never a token)."""
        with self._lock:
            if not force and self._auth_cache and time.monotonic() - self._auth_cache[0] < AUTH_TTL_SECONDS:
                return self._auth_cache[1]
        done = self._run_cli(["auth", "status"], 15)
        try:
            status = json.loads(done.stdout) if done is not None and done.stdout.strip() else {}
        except ValueError:
            status = {}
        status = status if isinstance(status, dict) else {}
        gateway = self._gateway_host()
        if status.get("apiKeySource") or gateway:
            kind = "gateway" if gateway else "api-key"
            label = f"a custom gateway ({gateway})" if gateway else "an API key"
        elif status.get("loggedIn") and status.get("authMethod") not in (None, "", "none"):
            kind, plan = "subscription", status.get("subscriptionType")
            label = f"your Claude {str(plan).capitalize()} plan" if isinstance(plan, str) and plan else "your Claude account"
        else:
            kind, label = ("signed-out", "no sign-in") if status else ("unknown", "an unknown setup")
        value = {"kind": kind, "label": label}
        with self._lock:
            self._auth_cache = (time.monotonic(), value)
        return value

    def _gateway_host(self) -> str | None:
        """Host of a custom ``ANTHROPIC_BASE_URL`` (Claude Code settings or this process), or None."""
        url = None
        try:
            raw = json.loads(((self._config_dir or config_dir()) / "settings.json").read_text(encoding="utf-8"))
            env = raw.get("env") if isinstance(raw, dict) and isinstance(raw.get("env"), dict) else {}
            url = env.get("ANTHROPIC_BASE_URL")
        except (OSError, ValueError):
            pass
        url = url or self.extra_env.get("ANTHROPIC_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL")
        if not isinstance(url, str) or not url.strip():
            return None
        host = re.sub(r"^[a-z]+://", "", url.strip()).split("/")[0]
        return None if host.endswith("anthropic.com") else host[:80]

    @checked("providers.claude.transports")
    def _transports(self, auth: dict[str, Any]) -> list[dict[str, Any]]:
        usable, why = terminal_available()
        same_bill = auth.get("kind") != "subscription"
        note = (f"Claude Code on this PC is set up with {auth.get('label')}, so both ways are billed there and plan limits don't apply."
                if same_bill and auth.get("kind") not in ("unknown",) else None)
        return [
            {"id": "print", "label": "Agent SDK credit", "default": True, "available": True, "risk": None,
             "description": "Claude Code's print mode (claude -p). Anthropic bills it to your monthly Agent SDK credit, "
                            "separate from your plan's limits. This is the supported way for other apps to run Claude Code.",
             "note": note},
            {"id": "terminal", "label": "Plan limits", "default": False, "available": usable, "reason": why,
             "description": "Claude Code's normal interactive mode, run in a hidden terminal on this PC with your message as its "
                            "prompt. It uses your plan's usual limits instead of the Agent SDK credit.",
             "risk": "Anthropic's terms restrict automated access to Claude, and here a program starts Claude Code for you. "
                     "This could put your Claude account at risk. Use it at your own discretion.",
             "limits": ["Images are saved on the PC and opened by Claude", "Replies arrive step by step, not word by word",
                        "Folder trust is reviewed with Approve or Deny in this chat"],
             "note": note},
        ]

    def _claude_json(self) -> Path:
        if self._config_dir:
            return self._config_dir / ".claude.json"
        custom = os.environ.get("CLAUDE_CONFIG_DIR")
        return Path(custom) / ".claude.json" if custom else Path.home() / ".claude.json"

    def _folder_trusted(self, folder: str) -> bool | None:
        """Whether Claude Code's trust prompt was accepted for this folder or a parent; None when unknown.

        Only the per-folder ``hasTrustDialogAccepted`` flags are read; nothing else in the file is kept.
        """
        try:
            data = json.loads(self._claude_json().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        projects = data.get("projects") if isinstance(data, dict) else None
        if not isinstance(projects, dict):
            return None
        decisions = {os.path.normcase(os.path.normpath(key)): value.get("hasTrustDialogAccepted")
                     for key, value in projects.items() if isinstance(value, dict)
                     and isinstance(value.get("hasTrustDialogAccepted"), bool)}
        current = Path(folder)
        for candidate in (current, *current.parents):
            decision = decisions.get(os.path.normcase(os.path.normpath(str(candidate))))
            if decision is not None:
                return decision
        return None

    # ------------------------------------------------------------------ turns

    def preflight(self, session_id: str | None) -> None:
        """Raise ``ClaudeSessionError`` when a turn on this session must not start (the broker calls it on send)."""
        if self._cli() is None:
            raise ClaudeSessionError("cli_unavailable", "Claude Code is not installed on this PC, so this session cannot be continued from Neyvia.")
        if session_id is None:
            return
        sid = self._session_id(session_id)
        from ..claude_code_host import held
        if held(sid):
            raise ClaudeSessionError("session_held", "You opened this session in a terminal window. Neyvia sends nothing to it until it ends there.")
        with self._lock:
            if sid in self._active_sessions:
                raise ClaudeSessionError("session_busy", "A Neyvia turn is already running in this Claude Code session.")
        owner = self._foreign_owner(sid)
        if owner is not None and (owner.get("status") != "idle" or owner.get("kind") == "background"):
            raise ClaudeSessionError("session_live_elsewhere", self._owner_message(sid, owner), owner=self._owner_dict(owner))

    def _owner_dict(self, row: dict) -> dict[str, Any]:
        return {"kind": row.get("kind"), "owner": "cli" if row.get("kind") == "background" else "app",
                "pid": row.get("pid"), "status": row.get("status"), "name": row.get("name")}

    def _owner_message(self, session_id: str, row: dict) -> str:
        entrypoint = None
        path = find_session_file(self._projects(), session_id)
        if path is not None:
            entrypoint = self._index(path).entrypoint
        where = ("a background Claude Code session" if row.get("kind") == "background"
                 else "the Claude desktop app" if entrypoint == "claude-desktop"
                 else "a Claude Code terminal" if entrypoint == "cli" else "Claude Code")
        if row.get("kind") == "background":
            return f"This chat belongs to {where}. Continue it there, or start a branch from the + menu."
        return f"Claude is working on this chat in {where} right now. Send here once it finishes, or start a branch from the + menu."

    @checked("providers.claude.lifecycle")
    def start_turn(self, session_id: str | None, message: str, options: TurnOptions, *, cwd: str | None, run_id: str, emit: Emit) -> str:
        images = [image for image in (options.images or []) if isinstance(image, dict)]
        text = message if isinstance(message, str) else ""
        if not text.strip() and not images:
            raise ClaudeSessionError("empty_message", "Enter a message to send.")
        if len(text) > MAX_MESSAGE_CHARS:
            raise ClaudeSessionError("message_too_long", f"Messages are limited to {MAX_MESSAGE_CHARS:,} characters.")
        lowered = text.strip().lower()
        for command in _SESSION_LEAVING:
            if lowered == command or lowered.startswith(command + " "):
                raise ClaudeSessionError("unsupported_command", f"{command} would leave this session, so it cannot be sent from here. Use Claude Code for it.")
        sid: str | None = None
        start_offset = 0
        folder = cwd
        if options.fork_from and not session_id:
            source, source_path = self._locate(options.fork_from)
            folder = folder or self._index(source_path).cwd
            options = dataclasses.replace(options, fork_from=source)
        if session_id:
            sid, path = self._locate(session_id)
            index = self._index(path)
            folder = folder or index.cwd
            start_offset = index.parsed_end
        if not folder or not os.path.isdir(folder):
            raise ClaudeSessionError("cwd_missing", "The folder for this session does not exist any more." if sid else "Choose an existing folder to start the session in.")
        if (options.transport or "print") == "terminal" and self._folder_trusted(folder) is False:
            raise ClaudeSessionError("folder_not_trusted", "Accept Claude Code's trust prompt for this folder on the host before continuing it in Neyvia.")
        self.preflight(session_id)
        if (options.transport or "print") == "terminal":
            usable, why = terminal_available()
            if not usable and self.terminal_spawn is None:
                raise ClaudeSessionError("terminal_unavailable", why or "Plan-limits mode isn't available on this PC.")
        with self._lock:
            if run_id in self._runs:
                raise ClaudeSessionError("run_exists", "This run id is already in use.")
            if sid:
                if sid in self._active_sessions:
                    raise ClaudeSessionError("session_busy", "A Neyvia turn is already running in this Claude Code session.")
                self._active_sessions.add(sid)

        def on_session(found: str, started: bool) -> None:
            from ..neyvia_cua import bind_chat
            identity = session_identity(found, self._host)
            bind_chat(run_id, identity)
            bind_chat(found, identity)
            if started:
                with self._lock:
                    self._active_sessions.add(found)
            try:
                path_now = find_session_file(self._projects(), found)
                if path_now is not None:
                    emit({"type": "session.updated", "session": self._summary(self._index(path_now), self.live_status()).public()})
            except (OSError, ValueError):
                pass

        def keep_media(token: str, data: bytes, mime: str) -> None:
            with self._lock:
                self._live_media[token] = (data, mime)
                while len(self._live_media) > 16:
                    self._live_media.pop(next(iter(self._live_media)))

        from ..neyvia_intent_plan import claude_turn_args
        from .. import claude_code_host as mod_host
        from ..claude_code_mods import mod_active
        # With the Neyvia mod loaded, everything that changes per turn (work board, intent note, memory recall) reaches the
        # model as mod context, so the system prompt stays byte-identical across turns and keeps its cache.
        via_mod = bool(self.state_root) and mod_active() and mod_host.mod_loaded(self.state_root, sid)
        if via_mod:
            from ..neyvia_intent_plan import CLAUDE_TASK_TOOLS, needs_checklist, turn_note
            turn_args = [*self.extra_args, "--allowedTools", CLAUDE_TASK_TOOLS]
            if needs_checklist(text):
                mod_host.note_turn(run_id, turn_note(
                    "TaskCreate (one task per ask), then TaskUpdate as each one moves. They may be deferred: load them with "
                    "ToolSearch query \"select:TaskCreate,TaskUpdate\". On older Claude Code use TodoWrite"))
        else:
            # Several asks in one message: tell this turn to publish its intent checklist (TodoWrite) first.
            turn_args = [*self.extra_args, *claude_turn_args(text)]
            from .work_board import turn_note as work_note
            awareness = work_note(self.state_root, folder, session_id)
            if awareness:
                if "--append-system-prompt" in turn_args:
                    index = turn_args.index("--append-system-prompt") + 1
                    turn_args[index] += "\n\n" + awareness
                else:
                    turn_args += ["--append-system-prompt", awareness]
        run: ClaudeRun | ClaudeTerminalRun
        if (options.transport or "print") == "terminal":
            run = ClaudeTerminalRun(
                cli=self._cli(), run_id=run_id, session_id=sid, message=text, options=options, cwd=folder, emit=emit,
                projects=self._projects(), store_for=self._stores.get, context_for=lambda path: self._context(self._index(path)),
                extra_args=turn_args, extra_env=self.extra_env, idle_timeout=self.idle_timeout,
                pending_timeout=self.pending_timeout, spawn=self.terminal_spawn, on_session=on_session,
            )
        else:
            run = ClaudeRun(
                cli=self._cli(), run_id=run_id, session_id=sid, message=text, options=options, cwd=folder, emit=emit,
                start_offset=start_offset, extra_args=turn_args, extra_env=self.extra_env, idle_timeout=self.idle_timeout,
                pending_timeout=self.pending_timeout, interrupt_grace=self.interrupt_grace, context_probe=self.context_probe,
                windows=self._windows, on_models=self._remember_models, on_session=on_session, keep_media=keep_media,
                state_root=self.state_root,
            )
        with self._lock:
            self._runs[run_id] = run
        try:
            return run.run()
        finally:
            mod_host.forget_run(run_id)
            with self._lock:
                self._runs.pop(run_id, None)
                self._active_sessions.discard(run.session_id or "")
                if sid:
                    self._active_sessions.discard(sid)

    def interrupt(self, run_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
        if run is not None:
            run.interrupt()

    def steer(self, run_id: str, message: str, images: list[dict[str, Any]] | None = None) -> None:
        """Add a message to a running Neyvia turn (print or plan-limits mode)."""
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise ClaudeSessionError("run_not_active", "This run is not active any more. Send your message as a new one.")
        run.steer(message, images)

    def answer(self, run_id: str, request_id: str, response: dict[str, Any]) -> None:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise ClaudeSessionError("run_not_active", "This run is not active any more. Refresh the session to see its current state.")
        run.answer(request_id, response)
