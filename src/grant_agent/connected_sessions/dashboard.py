"""Everything working right now, in one read: the agents dashboard (UI) and ``neyvia.agents.state`` (bot).

For each chat that is working or waiting (Claude Code, Codex, OpenCode, Neyvia), wherever it runs:
what it is doing now (its checklist item, else its latest tool), its checklist progress, context
tokens, and the sub-agents working under it. Plus the plan-limit windows the apps last reported
(``plan_limits``) and, when the work board exists (``neyvia.work.list``), who claimed what.
Every figure comes from the app's own records; a missing one stays ``None``.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from .plan import latest_plan, plan_summary

WORKING = ("working", "waiting_approval", "waiting_input")
_ACTIVE_RUN = ("queued", "running", "waiting_approval", "waiting_input")
MAX_ROWS = 16
MAX_PAGE_ROWS = 100
INVENTORY_PAGE = 500
READ_LIMIT = 120
READ_SECONDS = 12.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _tokens(agent: dict[str, Any]) -> int | None:
    parts = [agent.get("inputTokens"), agent.get("outputTokens")]
    known = [part for part in parts if isinstance(part, int) and not isinstance(part, bool)]
    return sum(known) if known else None


def subagents(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sub-agents recorded in a page (Claude Agent/Task calls, Codex collab agents); running ones first."""
    rows = []
    for item in items:
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if item.get("kind") != "tool" or data.get("category") != "agent":
            continue
        if data.get("name") == "sub_agent":
            continue  # Codex activity notices repeat the actual collabAgentToolCall.
        agent = data.get("agent") if isinstance(data.get("agent"), dict) else {}
        status = agent.get("status") or ("running" if data.get("status") == "running" else "error" if data.get("status") == "error" else "ok")
        rows.append({
            "id": item.get("id"), "title": agent.get("description") or data.get("title") or "Sub-agent",
            "type": agent.get("subagentType"), "model": agent.get("model") or data.get("model"),
            "status": status, "startedAt": agent.get("startedAt") or item.get("at"), "durationMs": agent.get("durationMs"),
            "tokens": _tokens(agent), "toolCount": agent.get("toolCount"), "now": agent.get("lastTool"),
        })
    running = [row for row in rows if row["status"] == "running"]
    result = running + [row for row in rows if row["status"] != "running"][-3:]
    from ..proofs_a_control import require
    require(all(any(item.get("id") == row["id"] and item.get("kind") == "tool"
                    and (item.get("data") or {}).get("category") == "agent"
                    and (item.get("data") or {}).get("name") != "sub_agent" for item in items) for row in result),
            "control.plan-dashboard", "dashboard counted activity notices as actual subagent calls")
    return result


def doing_now(items: list[dict[str, Any]], plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """The checklist item in progress, else the latest tool call or waiting state, else reply activity."""
    summary = plan_summary(plan)
    if summary and summary.get("current"):
        return {"kind": "plan", "text": summary["current"]}
    for item in reversed(items):
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if item.get("kind") == "tool" and data.get("title"):
            return {"kind": "tool", "text": str(data["title"]), "status": data.get("status"), "category": data.get("category"),
                    "at": item.get("at")}
        if item.get("kind") in ("approval", "question"):
            return {"kind": "waiting", "text": str(data.get("title") or "Waiting for your answer")}
    if any(item.get("kind") in ("assistant", "reasoning") for item in items):
        return {"kind": "text", "text": "Writing a reply"}
    return None


def _row(session: dict[str, Any], page: dict[str, Any] | None, run: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    items = (page or {}).get("items") or []
    plan = (page or {}).get("plan")
    if plan is None and page is not None:
        plan = latest_plan(items)
    context = (page or {}).get("context") or {}
    since = ((run or {}).get("startedAt") if (run or {}).get("state") in _ACTIVE_RUN else None) or session.get("status_since")
    if since is None and session.get("app") == "claude-code" and session.get("status") == "working":
        since = next((item.get("at") for item in reversed(items) if item.get("kind") == "user" and item.get("at")), None)
    result = {
        "id": session["id"], "app": session.get("app"), "category": session.get("category"), "runtime": session.get("runtime"),
        "title": session.get("title") or "Untitled chat", "project": session.get("project"), "status": session.get("status"),
        "since": since, "liveOwner": session.get("live_owner"),
        "model": session.get("model"), "now": doing_now(items, plan), "plan": plan_summary(plan),
        "tokens": context.get("used_tokens"), "windowTokens": context.get("window_tokens"),
        "subagents": subagents(items), "error": error,
    }
    from ..proofs_a_control import require
    require(result["id"] == session["id"] and result["since"] == since,
            "control.plan-dashboard", "dashboard lost session/start identity")
    if not (plan_summary(plan) or {}).get("current") and not any(
        item.get("kind") in {"approval", "question"} or item.get("kind") == "tool" and (item.get("data") or {}).get("title") for item in items
    ):
        require(result["now"] == ({"kind": "text", "text": "Writing a reply"} if any(item.get("kind") in {"assistant", "reasoning"} for item in items) else None),
                "control.plan-dashboard", "reply activity exposed private reasoning or invented work")
    return result


def work_board(service: Any) -> dict[str, Any] | None:
    """Claims from the work board (plan 12 §2) when that tool exists here; None when it doesn't."""
    try:
        from ..neyvia_workspace_tools import DEFINITIONS
    except Exception:  # noqa: BLE001
        return None
    if service is None or not any(name == "work.list" for name, *_ in DEFINITIONS):
        return None
    try:
        result = service.call("work.list", {})
    except Exception as exc:  # noqa: BLE001
        return {"available": True, "error": str(exc)[:300], "claims": []}
    claims = result.get("claims") if isinstance(result, dict) else result
    return {"available": True, "claims": claims if isinstance(claims, list) else []}


def running_inventory(broker: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Walk every inventory page before filtering, including harness and archived owners.

    History order is unrelated to activity: an old chat may still own a writer.
    Transcript reads stay limited to the requested dashboard page.
    """
    working: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    offset = 0
    while True:
        listing = broker.list_sessions(limit=INVENTORY_PAGE, offset=offset,
                                       include_harness=True, include_archived=True, observe=False,
                                       include_running=True)
        sources = listing.get("sources") or sources
        for session in listing.get("sessions") or []:
            if session.get("status") in WORKING:
                working[session["id"]] = session
        next_offset = listing.get("nextOffset")
        if next_offset is None:
            break
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise ValueError("Session inventory paging did not advance.")
        offset = next_offset
    return list(working.values()), sources


def _attach_mod(broker: Any, rows: list[dict[str, Any]]) -> None:
    """What the Neyvia mod knows about each Claude Code row: loaded or not, stop-gate blocks, hold, queued messages."""
    try:
        from .. import claude_code_host as host
        from ..claude_code_mods import RUNS
        from ..ui_command_bus import bus_for
        from .claude_items import parse_identity
        runs = bus_for(broker.root).get(RUNS, {}) or {}
        for row in rows:
            if row.get("app") != "claude-code":
                continue
            try:
                raw = parse_identity(row["id"])
            except ValueError:
                continue
            report = runs.get(raw) or {}
            row["mod"] = {"loaded": host.mod_loaded(broker.root, raw), "blocks": host._blocks.get(raw, 0), "held": host.held(raw),
                          "queued": sum(1 for e in host._mailbox.get(raw, []) if not e.get("seen")),
                          "lastTool": report.get("lastTool"), "gate": report.get("gate")}
    except Exception:  # noqa: BLE001 - the mod's extras never break the dashboard
        pass


def build(broker: Any, *, service: Any = None, limit: int = MAX_ROWS, offset: int = 0) -> dict[str, Any]:
    started = time.monotonic()
    from .live_limits import service_for
    limit_state = service_for(broker.root).snapshot()
    inventory, sources = running_inventory(broker)
    bounded = max(1, min(int(limit), MAX_PAGE_ROWS))
    start = max(0, int(offset))
    working = inventory[start:start + bounded]

    def read(session: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        try:
            return broker.read(session["id"], limit=READ_LIMIT), None
        except Exception as exc:  # noqa: BLE001
            return None, str(getattr(exc, "message", None) or exc)[:300]

    pages: list[tuple[dict[str, Any] | None, str | None]] = []
    if working:
        pool = ThreadPoolExecutor(max_workers=min(6, len(working)), thread_name_prefix="dashboard")
        try:
            futures = [pool.submit(read, session) for session in working]
            for future in futures:
                try:
                    pages.append(future.result(timeout=max(1.0, READ_SECONDS - (time.monotonic() - started))))
                except Exception:  # noqa: BLE001
                    pages.append((None, "This chat took too long to read."))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)  # a slow read never holds the dashboard
    rows = [_row(session, page, (page or {}).get("run") if page else broker.latest_run(session["id"]), error)
            for session, (page, error) in zip(working, pages)]
    next_offset = start + len(working) if start + len(working) < len(inventory) else None
    _attach_mod(broker, rows)
    from ..neyvia_cua import _SERVICES
    driver = _SERVICES.get(str(broker.root.resolve()))
    if driver:
        for row in rows:
            session = next((s for s in driver.sessions.values() if s["status"] == "active" and (s.get("owner") or {}).get("chatId") == row.get("id")), None)
            row["driver"] = {"sessionId": session["id"], "app": (session["windows"][0]["app_name"] if session["windows"] else None), "control": session["control"]} if session else None
    return {"at": _now(), "sessions": rows, "limits": limit_state["limits"],
            "limitProviders": limit_state["providers"], "limitsRefreshing": limit_state["refreshing"], "board": work_board(service),
            "sources": sources, "total": len(inventory), "offset": start, "limit": bounded,
            "nextOffset": next_offset, "hasMore": next_offset is not None}
