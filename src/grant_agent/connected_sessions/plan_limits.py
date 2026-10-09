"""Plan-limit windows (5-hour, weekly) as the apps themselves last reported them. Nothing is estimated.

Claude Code reports its windows in ``rate_limit_event`` messages while a turn streams through Neyvia
(``claude_stream`` records them here); Codex writes ``rate_limits`` next to every token count in its
rollout files, so the newest rollout tail says where the account stands even when Neyvia ran nothing.
A window nobody reported is simply absent. ``live_limits`` actively refreshes through the CLIs;
these stream/rollout observations remain compatible with existing passive callers.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CLAUDE_LABELS = {"five_hour": "5-hour", "seven_day": "Weekly", "seven_day_opus": "Weekly · Opus",
                  "seven_day_sonnet": "Weekly · Sonnet", "overage": "Extra usage"}
_lock = threading.Lock()
_claude: dict[str, dict[str, Any]] = {}
_claude_roots: dict[Path, dict[str, dict[str, Any]]] = {}
_claude_stamps: dict[Path, tuple[int, int] | None] = {}
_codex_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])
CODEX_TTL_SECONDS = 20.0
log = logging.getLogger(__name__)


@contextmanager
def _claude_write(root: Path | None):
    """Conserve windows across service processes through checked replacement."""
    with _lock:
        if root is None:
            yield
            return
        selected_root = Path(root).resolve()
        folder = selected_root / ".neyvia"
        folder.mkdir(parents=True, exist_ok=True)
        from ..harness_jobs import _exclusive_job_lock
        with _exclusive_job_lock(folder / "plan-limits.json", timeout_seconds=30):
            # Re-read under the process lease, even if a cached filesystem stamp
            # happens to match a replacement from another service process.
            _claude_roots.pop(selected_root, None)
            _claude_stamps.pop(selected_root, None)
            yield


def _claude_for(root: Path | None) -> dict[str, dict[str, Any]]:
    """Load when the service supplies its root, never guess from cwd or a global config folder."""
    if root is None:
        return _claude  # Direct callers without service context keep only in-memory observations.
    root = Path(root).resolve()
    saved_path = root / ".neyvia" / "plan-limits.json"
    try:
        stat = saved_path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    if root not in _claude_roots or _claude_stamps.get(root) != stamp:
        rows: dict[str, dict[str, Any]] = {}
        try:
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                rows = {key: row for key, row in saved.items() if isinstance(row, dict)
                        and row.get("app") == "claude-code" and row.get("window") == key and isinstance(row.get("at"), str)}
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning("Could not read saved Claude plan limits: %s", exc)
        _claude_roots[root] = rows
        _claude_stamps[root] = stamp
    return _claude_roots[root]


def _save_claude(root: Path, rows: dict[str, dict[str, Any]]) -> None:
    folder = Path(root).resolve() / ".neyvia"
    pending: Path | None = None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, prefix="plan-limits-", suffix=".tmp", delete=False) as handle:
            pending = Path(handle.name)
            json.dump(rows, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        pending.replace(folder / "plan-limits.json")
        from ..proofs_a_control import require
        require(json.loads((folder / "plan-limits.json").read_text(encoding="utf-8")) == rows,
                "control.plan-limits", "durable reported windows changed during atomic write")
    except OSError as exc:
        log.warning("Could not persist Claude plan limits: %s", exc)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def _iso(seconds: Any) -> str | None:
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0:
        return None
    if seconds > 10_000_000_000:  # milliseconds
        seconds = seconds / 1000
    try:
        return datetime.fromtimestamp(float(seconds), timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _percent(value: Any, *, fraction: bool) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value) * 100 if fraction else float(value)
    if not math.isfinite(number):
        return None
    return round(max(0.0, min(100.0, number)), 1)


def record_claude(info: Any, root: Path | None = None) -> None:
    """Keep one ``rate_limit_info`` from Claude Code's stream (its utilization is a 0–1 fraction)."""
    if not isinstance(info, dict):
        return
    kind = str(info.get("rateLimitType") or "")
    if not kind:
        return
    util = info.get("utilization")
    row = {
        "app": "claude-code", "window": kind, "label": _CLAUDE_LABELS.get(kind, kind.replace("_", " ").capitalize()),
        "usedPercent": _percent(util, fraction=isinstance(util, (int, float)) and not isinstance(util, bool) and util <= 1.0),
        "status": str(info.get("status") or "") or None, "resetsAt": _iso(info.get("resetsAt")),
        "at": _now(), "source": "claude-stream",
    }
    with _claude_write(root):
        rows = _claude_for(root)
        rows[kind] = row
        if root is not None:
            _save_claude(root, rows)


def claude_limits(root: Path | None = None) -> list[dict[str, Any]]:
    with _lock:
        return [dict(row) for row in _claude_for(root).values()]


def record_claude_statusline(payload: Any, root: Path) -> list[dict[str, Any]]:
    """Read only the documented rate_limits fields; never persist the rest of stdin."""
    limits = payload.get("rate_limits") if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        return claude_limits(root)  # Missing data cannot erase a last-known reading.
    with _claude_write(root):
        rows = _claude_for(root)
        previous = {kind: dict(row) for kind, row in rows.items()}
        for kind in ("five_hour", "seven_day"):
            window = limits.get(kind)
            if not isinstance(window, dict):
                continue
            percent = _percent(window.get("used_percentage"), fraction=False)
            if percent is None:
                continue
            rows[kind] = {"app": "claude-code", "window": kind, "label": _CLAUDE_LABELS[kind],
                          "usedPercent": percent, "resetsAt": _iso(window.get("resets_at")),
                          "status": None, "at": _now(), "source": "claude-statusline"}
        _save_claude(root, rows)
        output = [dict(row) for row in rows.values()]
        from ..proofs_e_host import check_limits
        check_limits(output, payload, previous, root)
        return output


MOD_FRESH_SECONDS = 300


def record_claude_mod(windows: Any, root: Path) -> list[dict[str, Any]]:
    """The windows the Neyvia mod read from Claude Code's own responses (``session.measure``): the real numbers."""
    if not isinstance(windows, list):
        return claude_limits(root)
    with _claude_write(root):
        rows = _claude_for(root)
        for window in windows:
            if not isinstance(window, dict) or window.get("window") not in {"five_hour", "seven_day"}:
                continue
            percent = _percent(window.get("usedPercent"), fraction=False)
            if percent is None:
                continue
            kind = window["window"]
            rows[kind] = {"app": "claude-code", "window": kind, "label": _CLAUDE_LABELS[kind], "usedPercent": percent,
                          "resetsAt": window.get("resetsAt") or None, "status": None, "at": _now(), "source": "claude-mod"}
        _save_claude(root, rows)
        return [dict(row) for row in rows.values()]


def fresh_mod_rows(root: Path, seconds: int = MOD_FRESH_SECONDS) -> list[dict[str, Any]]:
    """Mod-reported Claude windows read within ``seconds``; Neyvia then does not start Claude just to ask /usage."""
    current = datetime.now(timezone.utc)
    found = []
    for row in claude_limits(root):
        if row.get("source") != "claude-mod":
            continue
        try:
            if (current - datetime.fromisoformat(row["at"].replace("Z", "+00:00"))).total_seconds() <= seconds:
                found.append(row)
        except (ValueError, TypeError, AttributeError, KeyError):
            continue
    return found


def _window_label(minutes: Any) -> tuple[str, str]:
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or minutes <= 0:
        return "window", "Window"
    if minutes == 300:
        return "five_hour", "5-hour"
    if minutes == 10080:
        return "weekly", "Weekly"
    hours = minutes / 60
    if hours < 48:
        return f"{int(hours)}h", f"{int(hours)}-hour"
    return f"{int(hours // 24)}d", f"{int(hours // 24)}-day"


def codex_windows(limits: Any, at: str | None = None) -> list[dict[str, Any]]:
    """Rows for a Codex ``rate_limits`` object (``primary`` / ``secondary`` windows)."""
    if not isinstance(limits, dict):
        return []
    rows = []
    for slot in ("primary", "secondary"):
        window = limits.get(slot)
        if not isinstance(window, dict):
            continue
        key, label = _window_label(window.get("window_minutes", window.get("windowDurationMins")))
        rows.append({
            "app": "codex", "window": key, "label": label,
            "usedPercent": _percent(window.get("used_percent", window.get("usedPercent")), fraction=False),
            "status": "rejected" if limits.get("rate_limit_reached_type") else None,
            "resetsAt": _iso(window.get("resets_at", window.get("resetsAt"))), "at": at, "source": "codex-rollout",
        })
    from ..proofs_a_control import require
    require(all(row["source"] == "codex-rollout" and row["at"] == at and
                (row["usedPercent"] is None or 0 <= row["usedPercent"] <= 100) for row in rows)
            and len(rows) == sum(isinstance(limits.get(slot), dict) for slot in ("primary", "secondary")),
            "control.plan-limits", "reported Codex windows lost source/timestamp/count or bounded percentage")
    return rows


def _codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured) if configured else Path.home() / ".codex"


def _newest_rollouts(sessions: Path, count: int = 3) -> list[Path]:
    """The newest rollout files, looking only at the latest few day folders (YYYY/MM/DD)."""
    def newest_dirs(folder: Path, keep: int) -> list[Path]:
        try:
            return sorted((child for child in folder.iterdir() if child.is_dir() and child.name.isdigit()), reverse=True)[:keep]
        except OSError:
            return []
    files: list[tuple[float, Path]] = []
    for year in newest_dirs(sessions, 1):
        for month in newest_dirs(year, 2):
            for day in newest_dirs(month, 3):
                try:
                    for entry in os.scandir(day):
                        if entry.name.startswith("rollout-") and entry.name.endswith(".jsonl"):
                            files.append((entry.stat().st_mtime, Path(entry.path)))
                except OSError:
                    continue
    return [path for _, path in sorted(files, reverse=True)[:count]]


def codex_limits(home: Path | None = None, *, force: bool = False) -> list[dict[str, Any]]:
    global _codex_cache
    with _lock:
        stamp, cached = _codex_cache
        if not force and home is None and time.monotonic() - stamp < CODEX_TTL_SECONDS:
            return [dict(row) for row in cached]
    from .codex_items import rate_limits_from_rollout
    rows: list[dict[str, Any]] = []
    for path in _newest_rollouts((home or _codex_home()) / "sessions"):
        found = rate_limits_from_rollout(path)
        if found:
            rows = codex_windows(found, found.get("_at"))
            break
    if home is None:
        with _lock:
            _codex_cache = (time.monotonic(), rows)
    return rows


def all_limits(root: Path | None = None) -> list[dict[str, Any]]:
    from .live_limits import existing_service
    live = existing_service(root)
    if live is not None:
        return live.snapshot()["limits"]
    order = {"five_hour": 0, "5h": 0, "weekly": 1, "seven_day": 1}
    rows = claude_limits(root) + codex_limits()
    return sorted(rows, key=lambda row: (row["app"], order.get(row["window"], 2), row["window"]))
