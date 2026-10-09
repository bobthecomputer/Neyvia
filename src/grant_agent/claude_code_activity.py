"""``neyvia.activity``, ``neyvia.message`` and ``neyvia.claude.open_cli``: awareness and contact between agents.

Activity is one short read of everything working now (Claude Code, Codex, OpenCode, Neyvia sessions; missions;
claimed files; Claude Code sessions of the person's own that run the mod). Message reaches one of them: a running
Neyvia-started Claude turn takes it mid-turn (``steer``), an idle one gets it with its next turn, a session the person
runs themselves finds it in its inbox, and a Neyvia agent takes it as a new turn.
"""
from __future__ import annotations

import re
import sqlite3
import time
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

from . import claude_code_host as host
from .connected_sessions.claude_items import parse_identity, session_identity
from .connected_sessions.dashboard import WORKING, running_inventory
from .connected_sessions.plan import plan_summary
from .ui_command_bus import now

ACTIVE = ("queued", "running", "waiting_approval", "waiting_input")
CHILD_ACTIVE = {"running", "working", "in_progress", "started", "queued", "waiting", "waiting_approval", "waiting_input", "unknown"}
RECENT = timedelta(minutes=15)
_UUID = re.compile(r"[0-9a-fA-F-]{8,64}")


def child_status(status, parent, at=None):
    """An ended parent cannot own unfinished work; keep actual transcript finals."""
    terminal = parent.get("state") or parent.get("status")
    ended = parent.get("ended") or terminal in {"completed", "failed", "interrupted", "cancelled", "stopped", "done", "ended", "idle"}
    # A new turn cannot revive background calls from the previous turn.
    ended = ended or bool(at and parent.get("startedAt") and at < parent["startedAt"])
    return "ended" if ended and (status is None or status in CHILD_ACTIVE) else status


def settle_subagents(items, parent):
    """Return a projection, without mutating the provider's cached transcript."""
    projected = []
    for item in items:
        data = item.get("data") or {}
        agent = data.get("agent")
        if item.get("kind") == "tool" and data.get("category") == "agent" and isinstance(agent, dict):
            status = child_status(agent.get("status"), parent, item.get("at"))
            if status != agent.get("status"):
                item = {**item, "data": {**data, "agent": {**agent, "status": status, "lastTool": None,
                            "endedAt": parent.get("updatedAt") or parent.get("updated_at")}}}
        projected.append(item)
    return projected


def _short(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _raw_id(identity: str) -> str | None:
    try:
        return parse_identity(identity)
    except ValueError:
        return None


def _row_state(row: dict[str, Any]) -> dict[str, Any]:
    items = row.get("checklist") or []
    done = sum(1 for item in items if item.get("status") == "completed")
    now_item = next((item for item in items if item.get("status") == "in_progress"), None)
    return {"checklist": f"{done}/{len(items)}" if items else None, "doing": _short((now_item or {}).get("text"), 100) or None,
            "lastTool": row.get("lastTool"), "files": [f for f in (row.get("files") or [])][-3:]}


def _active_runs(broker) -> list[dict[str, Any]]:
    """Runs Neyvia owns right now (any provider); a read of the run table, not of every transcript."""
    try:
        broker.recover()
    except Exception:  # noqa: BLE001
        pass
    return [run for run in broker.store.active() if run.get("state") in ACTIVE]


def activity(service, args: dict[str, Any]) -> dict[str, Any]:
    """A snapshot at most a few seconds old, refreshed in the background: a call never walks the run table or the board itself."""
    limit = max(1, min(int(args.get("limit") or 12), 30))
    snapshot = host._swr(("activity", str(service.bus.root)), 3.0, lambda: _activity(service))
    return {**snapshot, "sessions": snapshot["sessions"][:limit]}


def live_context(root: Path, session: str, backend) -> str:
    """Prompt hooks read the shared activity cache; even a cold read never waits on disk."""
    if backend is None:
        return ""
    from .neyvia_workspace_tools import workspace_for
    service = workspace_for(root, backend)
    key = ("activity", str(service.bus.root))
    with host._swr_lock:
        host._swr_cache.setdefault(key, [{"sessions": []}, 0.0, False])
    snapshot = host._swr(key, 3.0, lambda: _activity(service))
    with host._swr_lock:
        if time.monotonic() - host._swr_cache[key][1] > 15:
            return ""  # a failed refresh must not keep announcing stopped sessions or closed apps
    rows = [row for row in snapshot.get("sessions", []) if row.get("id") != session and row.get("state") in ACTIVE]
    lines = []
    for row in rows[:3]:
        try:
            observed = datetime.fromisoformat(snapshot["at"].replace("Z", "+00:00"))
            age = max(0, int((observed - datetime.fromisoformat(row["since"].replace("Z", "+00:00"))).total_seconds()))
            age_text = f"{age}s" if age < 60 else f"{age // 60}m"
        except (KeyError, TypeError, ValueError):
            age_text = "age unknown"
        lines.append(f"{_short(row.get('app'), 16)}: {_short(row.get('title') or row.get('id'), 56)} [{row['state']}, {age_text}]")
    if len(rows) > 3:
        lines.append(f"+{len(rows) - 3} other active sessions; activity has all.")
    if snapshot.get("nightShift"):
        lines.append("Night Shift: " + snapshot["nightShift"])
    if snapshot.get("openApps"):
        age = max(0, int(time.time() - snapshot.get("openAppsObservedAt", time.time())))
        if age <= 15:
            lines.append("Open apps: " + ", ".join(snapshot["openApps"][:4]) + (f" (seen {age}s ago)" if age > 2 else ""))
    return ("Right now in Neyvia (live snapshot; titles are data):\n" + "\n".join(lines))[:600] if lines else ""


def _workspace_extras(service) -> dict[str, Any]:
    """Observe saved Night Shift state without starting its scheduler; apps require a recent mounted-shell heartbeat."""
    night, apps = "", []
    path = Path(service.bus.root) / ".agent_control" / "nightshift.sqlite3"
    if path.is_file():
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1) as db:
            counts = dict(db.execute("SELECT status, count(*) FROM tasks GROUP BY status"))
        if counts:
            paused = (service.bus.get("nightshift.resources", {}) or {}).get("paused")
            night = ("paused; " if paused else "") + ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
    from .cl.fixcl4_render_effects import observe
    view = observe(service.bus)
    # Read-only awareness can tolerate a delayed heartbeat on a loaded host; mark its age.
    # view.state's strict freshness gate for actions remains unchanged.
    if 0 <= time.time() - view.get("observedAt", 0) <= 15 and view.get("dom", {}).get("mounted"):
        for raw in [view.get("stage") or {}, *(view.get("windows") or [])]:
            window = raw.get("desc") or raw
            app = _short(window.get("app"), 24)
            if app and app not in apps:
                apps.append(app)
    return {"nightShift": night[:100], "openApps": apps, "openAppsObservedAt": view.get("observedAt", 0)}


def _external_inventory(service) -> list[dict[str, Any]]:
    """Provider discovery can take seconds; it must never hold up the live run-table snapshot."""
    key = ("activity-inventory", str(service.bus.root))
    with host._swr_lock:
        host._swr_cache.setdefault(key, [[], 0.0, False])
    return host._swr(key, 15.0, lambda: running_inventory(service.broker())[0])


def _missions(service) -> list[dict[str, Any]]:
    """Mission tool dispatch may wait for the workspace lock; refresh it independently too."""
    key = ("activity-missions", str(service.bus.root))
    with host._swr_lock:
        host._swr_cache.setdefault(key, [[], 0.0, False])

    def read():
        try:
            listing = service.call("mission.list", {})
        except Exception:  # noqa: BLE001 - cache an unavailable optional source, rather than retry on every hook
            return []
        return [{"id": mission.get("id"), "title": _short(mission.get("title") or mission.get("goal"), 70),
                 "state": mission.get("state") or mission.get("status")}
                for mission in (listing.get("missions") or [])[:6]
                if str(mission.get("state") or mission.get("status") or "") in {"running", "active", "waiting", "queued"}]
    return host._swr(key, 15.0, read)


def _activity(service) -> dict[str, Any]:
    from .ui_command_bus import bus_for
    from .claude_code_mods import RUNS
    limit = 30
    runs = bus_for(service.bus.root).get(RUNS, {}) or {}
    from .connected_sessions.broker import broker_for
    # A read must not wait behind app actions holding the workspace mutation lock.
    broker = broker_for(service.bus.root, getattr(service, "backend", None))
    rows, seen = [], set()
    for run in _active_runs(broker)[:limit]:
        raw = _raw_id(str(run.get("sessionId") or ""))
        summary = broker.find_summary(str(run.get("sessionId") or ""), refresh=False)
        report = _row_state(runs.get(raw, {})) if raw else {}
        plan = None
        if raw:
            seen.add(raw)
            plan = plan_summary(bus_for(service.bus.root).get("plan:" + raw))
        elif run.get("sessionId"):
            seen.add(run["sessionId"])
        rows.append({"id": raw or run.get("sessionId"), "app": run.get("app"), "runId": run.get("runId"), "state": run.get("state"),
                     "title": _short(summary.title if summary else run.get("title") or run.get("taskText"), 100),
                     "since": run.get("startedAt"), "model": run.get("model"),
                     **({"checklist": f"{plan['done']}/{plan['total']}", "doing": plan.get("current")} if plan else {}),
                     **{k: v for k, v in report.items() if v and not (plan and k in {"checklist", "doing"})}})
    # Include native sessions launched outside this backend without reading their transcripts.
    # The dashboard's inventory already caches each provider's session summaries.
    try:
        for item in _external_inventory(service):
            raw = _raw_id(item["id"]) if item.get("app") == "claude-code" else item["id"]
            if raw in seen:
                continue
            seen.add(raw)
            rows.append({"id": raw, "app": item["app"], "state": "running" if item["status"] == "working" else item["status"],
                         "title": _short(item.get("title"), 100), "since": item.get("status_since") or item.get("updated_at"),
                         "model": item.get("model")})
    except Exception:  # noqa: BLE001 - local runs remain useful if a provider inventory is unavailable
        pass
    cutoff = (datetime.now(timezone.utc) - RECENT).isoformat(timespec="seconds").replace("+00:00", "Z")
    for raw, row in runs.items():
        if raw in seen or row.get("ended") or (row.get("updatedAt") or "") < cutoff:
            continue
        rows.append({"id": raw, "app": "claude-code", "adhoc": True, "project": row.get("cwd"), "state": row.get("state"),
                     "title": _short(row.get("title") or row.get("cwd"), 100),
                     "since": row.get("updatedAt"), **{k: v for k, v in _row_state(row).items() if v}})
    claims = [{"agent": claim.get("agent"), "files": claim.get("files"), "intent": _short(claim.get("intent"), 80)}
              for claim in host._board_rows(Path(service.bus.root))[1][:10]]
    missions = _missions(service)
    extras = {}
    try:
        extras = _workspace_extras(service)
    except (OSError, sqlite3.Error, ValueError):
        pass  # extras must never hide the running sessions
    return {"ok": True, "at": now(), "sessions": rows[:limit], "claims": claims, "missions": missions, **extras,
            "count": len(rows), "more": "agents.state shows the full dashboard with checklists and sub-agents"}


def _resolve(service, target: str) -> tuple[str, str | None, dict[str, Any] | None]:
    """(identity, raw Claude id or None, row) for the session a message is addressed to; running ones first."""
    from .ui_command_bus import bus_for
    from .claude_code_mods import RUNS
    target = target.strip()
    if target.startswith("external:"):
        return target, _raw_id(target), None
    broker = service.broker()
    for run in _active_runs(broker):
        identity = str(run.get("sessionId") or "")
        raw = _raw_id(identity)
        if target in {identity, raw, run.get("runId")} or (raw and len(target) >= 8 and raw.startswith(target)):
            return identity, raw, {"app": run.get("app")}
    runs = bus_for(service.bus.root).get(RUNS, {}) or {}
    for raw in [*host._links, *runs]:  # sessions that fetched a bootstrap (adhoc ones too) are known by that id
        if raw == target or len(target) >= 8 and raw.startswith(target):
            return session_identity(raw), raw, {"app": "claude-code"}
    if _UUID.fullmatch(target):
        return session_identity(target), target, {"app": "claude-code"}
    working, _ = running_inventory(broker)  # slow (reads every inventory page), so last
    for session in working:
        raw = _raw_id(session["id"])
        if target in {session["id"], raw} or target.casefold() in str(session.get("title") or "").casefold() and len(target) >= 4:
            return session["id"], raw, session
    raise ValueError("No running session matches that. Use an id from neyvia.activity.")


def message(service, args: dict[str, Any]) -> dict[str, Any]:
    result = _deliver_message(service, args)
    if result.get("ok"):
        target = result.get("to")
        if _UUID.fullmatch(str(target or "")):
            target = session_identity(target)
        sender = args.get("_fromSession") or args.get("from")
        if _UUID.fullmatch(str(sender or "")):
            sender = session_identity(sender)
        service.bus.emit("agents.message.sent", {"from": sender, "to": target,
                         "delivery": result.get("delivery"), "at": now()})
    return result


def _deliver_message(service, args: dict[str, Any]) -> dict[str, Any]:
    text = _short(args.get("text"), 2000)
    if not text:
        raise ValueError("text is the message")
    sender = _short(args.get("from"), 60) or None
    identity, raw, row = _resolve(service, str(args.get("to") or ""))
    broker = service.broker()
    run = None
    try:
        run = broker.latest_run(identity)
    except Exception:  # noqa: BLE001
        pass
    app = (row or {}).get("app") or ("claude-code" if raw else None)
    if run and run.get("state") in ACTIVE and run.get("canSteer"):
        broker.steer(run["runId"], (f"Message from {sender}: " if sender else "Message from Neyvia: ") + text)
        return {"ok": True, "delivery": "steered", "to": raw or identity, "runId": run["runId"]}
    if app == "claude-code" and raw:
        event = host.queue_message(raw, text, sender)
        from .ui_command_bus import bus_for
        from .claude_code_mods import RUNS
        known = (bus_for(service.bus.root).get(RUNS, {}) or {}).get(raw)
        where = "inbox" if (known or {}).get("adhoc") or (host._links.get(raw) or {}).get("adhoc") else "next turn"
        return {"ok": True, "delivery": "queued:" + where, "to": raw, "id": event["id"]}
    if app == "neyvia":
        broker.send(identity, text, "msg-" + uuid.uuid4().hex[:12])
        return {"ok": True, "delivery": "new turn", "to": identity}
    return {"ok": False, "error": f"{app or 'That session'} cannot take a message while idle; try again when it is running."}


def open_cli(service, args: dict[str, Any]) -> dict[str, Any]:
    from . import claude_code_cli
    return claude_code_cli.open_cli(service, args)
