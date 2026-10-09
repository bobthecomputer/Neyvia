"""Read quotas through the installed CLIs. No credential files or raw terminal receipts.

Claude's /usage runs in an owned hidden ConPTY; Codex uses its stdio API.
OpenCode's session statistics are explicitly not subscription quotas.
"""
from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .plan_limits import _now, _percent, codex_windows

APPS = ("claude-code", "codex", "opencode")
REFRESH_SECONDS = 180
STALE_SECONDS = 360


class LimitsUnavailable(RuntimeError):
    pass


def _reset(text, now):
    """Claude renders civil time with an explicit IANA timezone, not a UTC guess."""
    match = re.search(r"Resets\s+(?:(\w{3})\s+(\d{1,2}),?\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*\(([^)]+)\)", text, re.I)
    if not match:
        return None
    month, day, hour, minute, meridian, zone = match.groups()
    try:
        local = now.astimezone(ZoneInfo(zone))
        hour = int(hour) % 12 + (12 if meridian.lower() == "pm" else 0)
        when = local.replace(hour=hour, minute=int(minute or 0), second=0, microsecond=0)
        if month:
            number = datetime.strptime(month, "%b").month
            when = when.replace(month=number, day=int(day))
            if when < local - timedelta(days=1):
                when = when.replace(year=when.year + 1)
        elif when <= local:
            when += timedelta(days=1)
        return when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, ZoneInfoNotFoundError):
        return None


def parse_claude_usage(text, now=None):
    now = now or datetime.now(timezone.utc)
    # Match the aggregate weekly bucket specifically; never use Fable/Opus/Sonnet.
    headers = (("five_hour", "5-hour", r"Current\s+session"),
               ("seven_day", "Weekly", r"Current\s+week\s*\(all\s*models\)"))
    rows = []
    for key, label, header in headers:
        matches = list(re.finditer(header + r"(.*?)(?=Current\s+(?:session|week)|What's\s+contributing|Usage\s+credits|Esc\s+to\s+cancel|$)", text, re.I | re.S))
        for match in reversed(matches):
            section = match.group(1)
            percent = re.search(r"(\d+(?:\.\d+)?)\s*%\s*used", section)
            if not percent:
                continue
            reset = _reset(section, now)
            if reset is None:
                continue  # Partial repaint is not a complete reading.
            rows.append({"app": "claude-code", "window": key, "label": label,
                         "usedPercent": _percent(float(percent.group(1)), fraction=False),
                         "resetsAt": reset, "at": _now(), "source": "claude-usage", "status": None})
            break
    return rows


def read_claude(root, *, timeout=35):
    from .claude_terminal import screen_text, spawn_terminal, _kill_tree
    from .claude_trust import trust_menu
    cli = next((value for value in (shutil.which(name) for name in ("claude.exe", "claude.cmd", "claude")) if value), None)
    if not cli:
        raise LimitsUnavailable("Claude Code CLI is not installed")
    folder = Path(root) / ".agent_control" / "limits-terminal"
    folder.mkdir(parents=True, exist_ok=True)
    # Host SDK routing/session markers can send /usage to a host proxy rather
    # than the CLI account. Strip by name only; never inspect their values.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("CLAUDE_", "CLAUDECODE", "ANTHROPIC_"))}
    env.update({"DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    term = spawn_terminal([cli, "/usage", "--safe-mode", "--tools", "", "--setting-sources", "",
                           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}'], str(folder), env)
    chunks, lock = [], threading.Lock()
    stopped = threading.Event()
    def read():
        try:
            while not stopped.is_set() and term.isalive():
                chunk = term.read(16384)
                with lock:
                    chunks.append(chunk)
                    while sum(map(len, chunks)) > 128 * 1024:
                        chunks.pop(0)
        except (OSError, EOFError):
            pass
    reader = threading.Thread(target=read, name="claude-limits-terminal", daemon=True)
    reader.start()
    retried = False
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            time.sleep(.2)
            with lock:
                text = screen_text("".join(chunks))
            menu = trust_menu(text)
            if menu:
                # CLI trust is stored in its global configuration. This reader
                # never changes it; a new state root needs the owner's own CLI UI.
                raise LimitsUnavailable("Claude Code needs folder trust; open Claude in this state's .agent_control/limits-terminal once")
            rows = parse_claude_usage(text)
            if len(rows) == 2:
                return rows
            if "Failed to load usage data" in text and not retried:
                term.write("r")
                retried = True
        raise LimitsUnavailable("Claude /usage did not report both windows; retry or check Claude Code sign-in")
    finally:
        stopped.set()
        _kill_tree(getattr(term, "pid", None))
        try:
            term.terminate(force=True)
        except (OSError, EOFError):
            pass
        reader.join(1)


def read_codex(root):
    from .codex_rpc import AppServerConnection, resolve_command
    # Reuse the production RPC transport and its bounded owned-process cleanup.
    conn = AppServerConnection(resolve_command, on_notification=lambda *_: None,
                               on_server_request=lambda *_: None, initialize_timeout=15)
    try:
        result = conn.request("account/rateLimits/read", {}, timeout=15)
        rows = codex_windows(result.get("rateLimits"), _now())
        rows = [row for row in rows if row["usedPercent"] is not None and row["resetsAt"]]
        for row in rows:
            row["source"] = "codex-cli"
            if (result.get("rateLimits") or {}).get("ordinaryUsageAllowed") is False:
                row["status"] = "rejected"
        if not rows:
            raise LimitsUnavailable("Codex CLI did not report subscription windows")
        return rows
    finally:
        conn.close()


def read_claude_preferring_mod(root, *, timeout=35):
    """Both Claude windows from the Neyvia mod when it reported them lately (free, exact); else ask /usage in a hidden terminal."""
    from .plan_limits import fresh_mod_rows
    rows = fresh_mod_rows(root, REFRESH_SECONDS + 60)
    if {row["window"] for row in rows} >= {"five_hour", "seven_day"}:
        return rows
    return read_claude(root, timeout=timeout)


def read_opencode(root):
    if not any(shutil.which(name) for name in ("opencode.exe", "opencode.cmd", "opencode")):
        raise LimitsUnavailable("OpenCode CLI is not installed")
    raise LimitsUnavailable("Installed OpenCode CLI exposes session stats, not subscription quota windows")


def _clean_row(row):
    """Only the public limit contract can be saved or relayed."""
    return {key: row.get(key) for key in ("app", "window", "label", "usedPercent", "resetsAt", "at", "source", "status")}


class LiveLimits:
    def __init__(self, root, *, interval=REFRESH_SECONDS, readers=None):
        self.root = Path(root).resolve()
        self.path = self.root / ".neyvia" / "live-limits.json"
        self.interval = interval
        self.readers = readers or {"claude-code": read_claude_preferring_mod, "codex": read_codex, "opencode": read_opencode}
        self.lock = threading.RLock()
        self.gate = threading.Lock()
        self.closed, self.requested, self.completed = threading.Event(), threading.Event(), threading.Event()
        self.rows, self.providers, self.listeners = {}, {}, []
        self.refreshing = False
        self.persistence_error = None
        self.thread = None
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            for row in saved.get("limits", []):
                if isinstance(row, dict) and row.get("app") in APPS and row.get("window") and row.get("at"):
                    self.rows[(row["app"], row["window"])] = _clean_row(row)
            for provider in saved.get("providers", []):
                if isinstance(provider, dict) and provider.get("app") in APPS:
                    self.providers[provider["app"]] = {key: provider.get(key) for key in ("app", "status", "checkedAt", "error")}
        except (OSError, ValueError, AttributeError, TypeError):
            pass

    def start(self):
        with self.lock:
            if self.thread is None and not self.closed.is_set():
                self.thread = threading.Thread(target=self._loop, name="live-plan-limits", daemon=True)
                self.requested.set()
                self.thread.start()
        return self

    def _loop(self):
        while not self.closed.is_set():
            self.requested.wait(self.interval)
            if self.closed.is_set():
                break
            self.requested.clear()
            self.collect()

    def refresh(self, *, wait=False):
        with self.lock:
            if not self.refreshing and not self.requested.is_set():
                self.completed.clear()
                self.requested.set()
        self.start()
        if wait:
            self.completed.wait(55)
        return self.snapshot()

    def collect(self):
        if not self.gate.acquire(blocking=False):
            return
        try:
            with self.lock:
                self.refreshing = True
                self.completed.clear()
            def read_one(app):
                rows, error, status = [], None, "ready"
                try:
                    rows = self.readers[app](self.root)
                    if not rows:
                        raise LimitsUnavailable("CLI reported no quota windows")
                except LimitsUnavailable as exc:
                    error, status = str(exc), "unavailable"
                except Exception:
                    # Never relay a raw exception (may contain CLI/account data).
                    error, status = "CLI limit refresh failed; retry in the CLI", "error"
                with self.lock:
                    if rows:
                        self.rows = {key: value for key, value in self.rows.items() if key[0] != app}
                        self.rows.update({(app, row["window"]): _clean_row(row) for row in rows})
                    self.providers[app] = {"app": app, "status": status, "checkedAt": _now(), "error": error}
            workers = [threading.Thread(target=read_one, args=(app,), daemon=True) for app in APPS]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()  # Production readers have their own strict deadlines.
            with self.lock:
                try:
                    self._save()
                    self.persistence_error = None
                except OSError:
                    self.persistence_error = "Last-known limits could not be saved"
                self.refreshing = False
                listeners = list(self.listeners)
            for listener in listeners:
                try:
                    listener()
                except Exception:
                    pass
        finally:
            self.refreshing = False
            self.completed.set()
            self.gate.release()

    def adopt(self, rows):
        """Windows the Neyvia mod just read from Claude Code: shown at once, no hidden /usage terminal needed."""
        with self.lock:
            for row in rows:
                if row.get("app") == "claude-code" and row.get("window"):
                    self.rows[("claude-code", row["window"])] = _clean_row(row)
            self.providers["claude-code"] = {"app": "claude-code", "status": "ready", "checkedAt": _now(), "error": None}
            try:
                self._save()
            except OSError:
                pass
            listeners = list(self.listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                pass

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        pending = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                pending = Path(handle.name)
                json.dump({"limits": list(self.rows.values()), "providers": list(self.providers.values())}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            pending.replace(self.path)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)

    def snapshot(self):
        with self.lock:
            current = datetime.now(timezone.utc)
            rows = []
            for row in self.rows.values():
                provider = self.providers.get(row["app"], {})
                try:
                    at = datetime.fromisoformat(row["at"].replace("Z", "+00:00"))
                    reset = datetime.fromisoformat(row["resetsAt"].replace("Z", "+00:00"))
                    stale = (current - at).total_seconds() > STALE_SECONDS or reset <= current
                except (ValueError, TypeError, AttributeError):
                    stale = True
                stale = stale or provider.get("status") != "ready"
                rows.append({**row, "stale": stale, "availability": provider.get("status", "unavailable"), "error": provider.get("error")})
            busy = self.refreshing or self.requested.is_set()
            providers = [{"app": app, "status": "unavailable", "checkedAt": None, "error": None,
                          **self.providers.get(app, {}), "refreshing": busy} for app in APPS]
            return {"limits": rows, "providers": providers, "refreshing": busy, "refreshSeconds": self.interval,
                    "persistenceError": self.persistence_error}

    def close(self):
        self.closed.set()
        self.requested.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(2)


_services, _lock = {}, threading.Lock()


def service_for(root):
    key = str(Path(root).resolve())
    with _lock:
        if key not in _services or _services[key].closed.is_set():
            _services[key] = LiveLimits(root).start()
            atexit.register(_services[key].close)
        return _services[key]


def existing_service(root):
    with _lock:
        return _services.get(str(Path(root).resolve())) if root is not None else None
