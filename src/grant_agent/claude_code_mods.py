"""Neyvia's tools as a Claude Code plugin (``plugins/neyvia``): the setting, the launch environment, the mod's reports.

The plugin is plain Claude Code extension material: skills made from the manuals, an MCP server that calls this
backend's ``neyvia.*`` tools, and a mod that reports run status, the checklist and edited files back here. With the
setting on (the default), plan-limits runs start Claude Code with ``CLAUDE_CODE_PLUGIN_DIRS`` naming the plugin, so
the work is visibly Claude Code with mods. Nothing here approves tool calls or rewrites prompts.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

from .ui_command_bus import bus_for, now
from .proofs_a_cli import checked, check_mod_report

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "plugins" / "neyvia"
SETTING = "claudeCodeMods"
RUNS = "claudeCodeRuns"
MAX_RUNS = 40
MAX_ITEMS = 100
MAX_FILES = 100
_SESSION = re.compile(r"[A-Za-z0-9_-]{1,100}")
_TURN_STATES = {"working", "idle", "aborted", "error", "refusal"}
_ITEM_STATES = {"pending", "in_progress", "completed"}
_lock = threading.Lock()

TEXT = {"type": "string"}
DEFINITIONS = [
    ("claude.mods", "Read or switch whether Claude Code runs on plan limits start with the Neyvia plugin "
                    "(Neyvia tools, manuals as skills, live checklist). Leave enabled out to read.",
     {"enabled": {"type": "boolean"}}, []),
    ("claude.runs", "Read what Claude Code sessions running the Neyvia plugin reported: state, checklist, edited files.",
     {"session": TEXT, "limit": {"type": "integer", "minimum": 1, "maximum": 40}}, []),
    ("activity", "Every session, run, mission and agent working right now across providers: what each does, its state, its "
                 "last step and the files it claimed. Short. Read-only.", {"limit": {"type": "integer", "minimum": 1, "maximum": 30}}, []),
    ("message", "Send a short message to another running agent: a Claude Code session started from Neyvia (reaches it "
                "mid-turn, else at its next turn), a Claude Code session of the person's own (its inbox), or a Neyvia agent.",
     {"to": TEXT, "text": {"type": "string", "maxLength": 2000}, "from": TEXT}, ["to", "text"]),
    ("claude.open_cli", "Open a Claude Code session for the person: shows a running turn live in a Neyvia terminal pane, "
                        "or opens an idle session in a terminal window. Only on the person's click.",
     {"session": TEXT, "mode": {"type": "string", "enum": ["view", "terminal"]}}, ["session"]),
]


def plugin_ready() -> tuple[bool, str | None]:
    if not (PLUGIN_DIR / ".claude-plugin" / "plugin.json").is_file():
        return False, "The Neyvia plugin folder is missing from this install."
    return True, None


def settings(bus) -> dict[str, Any]:
    saved = bus.get(SETTING, {}) or {}
    ready, reason = plugin_ready()
    return {"enabled": saved.get("enabled", True) is not False, "available": ready, "reason": reason,
            "pluginDir": str(PLUGIN_DIR)}


@checked('a-cli.mods.launch')
def launch_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Extra environment for one plan-limits ``claude`` process; empty when the setting is off or no backend runs."""
    environ = os.environ if environ is None else environ
    root = environ.get("NEYVIA_UI_STATE_ROOT")
    if not root or not environ.get("NEYVIA_UI_BACKEND_URL"):
        return {}  # the plugin only talks to a running Neyvia service
    try:
        current = settings(bus_for(Path(root)))
    except Exception:  # an unreadable setting must never stop the run; it then starts without the plugin
        return {}
    if not (current["enabled"] and current["available"]):
        return {}
    own = os.path.normcase(str(PLUGIN_DIR))
    others = [part for part in str(environ.get("CLAUDE_CODE_PLUGIN_DIRS") or "").split(os.pathsep)
              if part.strip() and os.path.normcase(part.strip()) != own]
    from .connected_sessions.claude_terminal import hook_python
    env = {"CLAUDE_CODE_PLUGIN_DIRS": os.pathsep.join([str(PLUGIN_DIR), *others]), "NEYVIA_PYTHON": hook_python(),
           "NEYVIA_BACKEND": str(environ.get("NEYVIA_UI_BACKEND_URL"))}
    return env


def run_env(run_id: str, environ: dict[str, str] | None = None) -> dict[str, str]:
    """``launch_env`` for one Neyvia-run turn: the run id and a scoped token that lasts as long as the run."""
    env = launch_env(environ)
    if env:
        from . import claude_code_host as host
        root = (environ if environ is not None else os.environ).get("NEYVIA_UI_STATE_ROOT")
        env["NEYVIA_RUN_ID"] = run_id
        if root:
            env[host.TOKEN_ENV] = host.mint(Path(root), run_id)
    return env


def mod_active(environ: dict[str, str] | None = None) -> bool:
    """True when a turn started now gets the mod (the setting is on and a backend runs): its text then comes from the mod."""
    return bool(launch_env(environ))


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def record_report(bus, body: dict[str, Any]) -> dict[str, Any]:
    """Keep one report from the mod: ``session``, ``turn``, ``checklist`` or ``edit``."""
    session = str(body.get("session") or "")
    if not _SESSION.fullmatch(session):
        raise ValueError("session is the Claude Code session id")
    kind = body.get("kind")
    patch: dict[str, Any] = {}
    if kind == "session":
        patch = {"cwd": _text(body.get("cwd"), 500) or None, "version": _text(body.get("version"), 40) or None,
                 "runId": _text(body.get("runId"), 100) or None, "ended": False}
    elif kind == "turn":
        state = body.get("state")
        if state not in _TURN_STATES:
            raise ValueError("state is one of " + ", ".join(sorted(_TURN_STATES)))
        patch = {"state": state, "ended": False}
        if body.get("lastTool"):
            patch["lastTool"] = _text(body.get("lastTool"), 80)
        usage = body.get("usage")
        if isinstance(usage, dict):
            patch["usage"] = {key: int(value) for key, value in usage.items()
                              if isinstance(key, str) and len(key) <= 40 and isinstance(value, (int, float)) and value >= 0}
    elif kind == "checklist":
        items = body.get("items")
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise ValueError(f"items is a list of up to {MAX_ITEMS} checklist rows")
        patch = {"checklist": [{"text": _text(item.get("text"), 300), "status": item.get("status")}
                               for item in items if isinstance(item, dict) and item.get("status") in _ITEM_STATES
                               and _text(item.get("text"), 300)]}
    elif kind == "edit":
        path = _text(body.get("path"), 500)
        if not path:
            raise ValueError("path is the edited file")
        patch = {"file": path}
    elif kind == "limits":
        windows = []
        for item in (body.get("rateLimits") if isinstance(body.get("rateLimits"), list) else [])[:6]:
            if isinstance(item, dict) and isinstance(item.get("percentUsed"), (int, float)) and not isinstance(item.get("percentUsed"), bool):
                windows.append({"window": _text(item.get("kind"), 30), "usedPercent": max(0.0, min(float(item["percentUsed"]), 1000.0)),
                                "resetsAt": _text(item.get("resetsAt"), 40) or None})
        context = body.get("context") if isinstance(body.get("context"), dict) else {}
        patch = {"limits": {"windows": windows, "at": now()},
                 **({"contextPercent": float(context["percent"])} if isinstance(context.get("percent"), (int, float)) else {})}
        if not windows and not patch.get("contextPercent"):
            patch = {}
    elif kind == "end":
        patch = {"state": "idle", "ended": True, "endedAt": now(), "endReason": _text(body.get("reason"), 40) or None}
    else:
        raise ValueError("kind is session, turn, checklist, edit, limits or end")
    if kind == "limits" and patch.get("limits", {}).get("windows"):
        from .connected_sessions.plan_limits import record_claude_mod
        saved = record_claude_mod(patch["limits"]["windows"], Path(bus.root))
        from .connected_sessions.live_limits import existing_service
        live = existing_service(Path(bus.root))
        if live is not None:
            live.adopt([row for row in saved if row.get("source") == "claude-mod"])
    with _lock:
        runs = bus.get(RUNS, {}) or {}
        row = dict(runs.get(session) or {"session": session, "files": [], "checklist": [], "state": "idle"})
        previous = dict(row)
        added = patch.pop("file", None)
        row.update({key: value for key, value in patch.items() if value is not None})
        if added and added not in row["files"]:
            row["files"] = [*row["files"], added][-MAX_FILES:]
        row["updatedAt"] = now()
        runs[session] = row
        if len(runs) > MAX_RUNS:
            for stale in sorted(runs, key=lambda key: runs[key].get("updatedAt") or "")[:len(runs) - MAX_RUNS]:
                runs.pop(stale, None)
        check_mod_report(body, runs, session, previous)
        bus.put(RUNS, runs)
    return {"ok": True, "session": session}


def call(workspace, name: str, args: dict[str, Any]) -> dict[str, Any]:
    bus = workspace.bus
    if name == "claude.mods":
        if "enabled" in args:
            if not isinstance(args["enabled"], bool):
                raise ValueError("enabled is true or false")
            bus.put(SETTING, {"enabled": args["enabled"], "updatedAt": now()})
        return {"ok": True, **settings(bus)}
    if name == "claude.runs":
        runs = sorted((bus.get(RUNS, {}) or {}).values(), key=lambda row: row.get("updatedAt") or "", reverse=True)
        wanted = str(args.get("session") or "").strip()
        if wanted:
            runs = [row for row in runs if row.get("session") == wanted]
        limit = max(1, min(int(args.get("limit") or 10), MAX_RUNS))
        return {"ok": True, "runs": runs[:limit], "total": len(runs)}
    if name in {"activity", "message", "claude.open_cli"}:
        from . import claude_code_activity as activity
        return getattr(activity, name.replace("claude.", ""))(workspace, args)
    raise ValueError("Unknown Claude Code plugin action")
