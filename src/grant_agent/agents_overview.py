"""One cached, read-only agent graph for the pane, CL and native clients.

No scheduler or provider poller is started here. Source owners retain control;
their persisted records and the connected broker's cached inventory are read.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .ui_command_bus import now

STATES = {"working", "waiting", "asking", "done", "failed", "stopped", "ended", "unknown"}


def state(value):
    return {"running": "working", "queued": "working", "starting": "working", "active": "working",
            "merging": "working", "checking": "working", "waiting_approval": "waiting", "waiting_input": "waiting",
            "blocked": "waiting", "needs_review": "waiting", "conflict": "waiting", "paused": "waiting", "completed": "done",
            "finished": "done", "merged": "done", "settled": "done", "ready": "done", "ok": "done",
            "error": "failed", "checks_failed": "failed", "interrupted": "stopped", "cancelled": "stopped",
            "idle": "done"}.get(value, value if value in STATES else "unknown")


def new_tokens(usage):
    if not isinstance(usage, dict):
        return None
    total, cached = usage.get("totalTokens"), usage.get("cachedInputTokens")
    if type(total) is int and type(cached) is int and 0 <= cached <= total:
        return total - cached
    return None


def stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def node(identity, source, title, raw, *, parent=None, app="neyvia", session=None, run=None):
    started = raw.get("startedAt") or raw.get("since") or raw.get("createdAt")
    ended = raw.get("finishedAt") or raw.get("updatedAt")
    status = state(raw.get("state") or raw.get("status"))
    start = stamp(started)
    end = stamp(ended) if status in {"done", "failed", "stopped", "ended"} else time.time()
    activity = raw.get("activity") or raw.get("lastActivity") or raw.get("reason")
    if activity == "Writing a reply" and status in {"done", "failed", "stopped", "ended"}:
        # The tail's live phrase outlives the turn; a finished card must not claim it is still writing.
        activity = "Reply written"
    return {"id": identity, "parentId": parent, "source": source, "app": app or "neyvia", "title": title or identity,
            "state": status, "activity": activity,
            "project": raw.get("project") or raw.get("folder") or raw.get("cwd") or raw.get("repo"),
            "worktree": raw.get("worktree") or raw.get("cwd"), "branch": raw.get("branch") or raw.get("git_branch"), "model": raw.get("model"),
            "startedAt": started, "elapsedSeconds": max(0, end - start) if start and end else None,
            "newTokens": new_tokens(raw.get("usage")), "sessionId": session, "runId": run,
            "actions": {"chat": bool(session), "watch": bool(session or run), "message": False, "stop": None}}


def check_graph(result):
    """Executable agents.live-overview contract, checked on every real read."""
    nodes, edges = result["nodes"], result["edges"]
    by_id = {row["id"]: row for row in nodes}
    assert len(by_id) == len(nodes), "Overview repeated an agent identity"
    for row in nodes:
        assert row["state"] in STATES
        assert row["newTokens"] is None or type(row["newTokens"]) is int and row["newTokens"] >= 0
        path, parent = {row["id"]}, row.get("parentId")
        while parent:
            assert parent in by_id and parent not in path, "Overview parent is missing or cyclic"
            path.add(parent)
            parent = by_id[parent].get("parentId")
    assert all(edge["from"] in by_id and edge["to"] in by_id for edge in edges)
    agents = [row for row in nodes if row.get("isAgent", True)]
    assert result["totals"]["working"] == sum(row["state"] == "working" for row in agents)
    assert result["totals"]["waiting"] == sum(row["state"] in {"waiting", "asking"} for row in agents)


class Overview:
    def __init__(self, service):
        self.service = service
        self.lock = threading.Lock()
        self.value = None
        self.built = 0
        self.refreshing = False
        self.last_event = 0
        service.broker().add_event_listener(self.changed)

    def changed(self, event):
        if event.get("type") not in {"session.updated", "run.state", "run.updated", "usage.updated", "item.upsert", "item.delta", "item.updated", "item.completed"}:
            return
        # A burst of tool/token events costs at most one invalidation per second.
        with self.lock:
            if time.monotonic() - self.last_event < 1:
                return
            self.last_event = time.monotonic()
            self.built = 0
        self.service.bus.emit("agents.overview.changed", {"at": now()})

    def read(self):
        with self.lock:
            if self.value is None:
                self.value = {"at": None, "nodes": [], "edges": [], "totals": {"working": 0, "waiting": 0,
                              "newTokensLastHour": None}, "limits": [], "sources": [], "loading": True}
            if not self.refreshing and time.monotonic() - self.built >= 3:
                self.refreshing = True
                threading.Thread(target=self.refresh, name="agents-overview", daemon=True).start()
            return {**self.value, "refreshing": self.refreshing}

    def refresh(self):
        try:
            value = aggregate(self.service)
        except Exception as exc:  # preserve last observations with an explicit failed refresh
            with self.lock:
                self.value = {**self.value, "error": str(exc), "loading": False}
        else:
            signature = {k: value[k] for k in ("nodes", "edges", "totals")}
            signature["nodes"] = [{k: v for k, v in row.items() if k != "elapsedSeconds"} for row in value["nodes"]]
            digest = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
            with self.lock:
                changed = digest != self.value.get("revision")
                self.value = {**value, "revision": digest, "loading": False}
            if changed:
                self.service.bus.emit("agents.overview.changed", {"revision": digest, "at": value["at"]})
        finally:
            with self.lock:
                self.built, self.refreshing = time.monotonic(), False


_services = {}
_lock = threading.Lock()
_tail_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="agents-tail")


def overview(service):
    key = str(service.bus.root.resolve())
    with _lock:
        reader = _services.get(key)
        if reader is None:
            reader = _services[key] = Overview(service)
    return reader.read()


def aggregate(service):
    from .connected_sessions.dashboard import doing_now, running_inventory, subagents
    from .connected_sessions.live_limits import service_for
    from .connected_sessions.runs import public_run
    broker = service.broker()
    rows, edges, sources = {}, [], []
    from .claude_code_host import _swr, _swr_cache, _swr_lock

    def source(name, read):
        key = ("agents-source", str(broker.root), name)
        with _swr_lock:
            _swr_cache.setdefault(key, [None, 0.0, False])
        def compute():
            try:
                return {"value": read(), "at": now(), "error": None}
            except Exception as exc:
                return {"value": [], "at": now(), "error": str(exc)[:300]}
        cached = _swr(key, 10, compute)
        sources.append({"id": name, "available": bool(cached and not cached["error"]),
                        "at": cached["at"] if cached else None,
                        **({"error": cached["error"] if cached else "First observation pending"}
                           if not cached or cached["error"] else {})})
        return cached["value"] if cached else []

    inventory = source("sessions", lambda: running_inventory(broker)[0])
    # Recent owned runs keep completed/failed/stopped results inspectable. Active
    # inventory is never truncated by recency or by this history query.
    with broker.store.connect() as db:
        recent = [json.loads(row[0]) for row in db.execute("SELECT data FROM connected_session_runs ORDER BY started DESC LIMIT 200")]
    latest = {}
    for run in recent:
        latest.setdefault(run.get("sessionId"), run)
    seen = {row["id"] for row in inventory}
    for session, run in latest.items():
        if not isinstance(session, str):
            continue  # a queued new chat has not received its provider identity yet
        if session not in seen and (stamp(run.get("updatedAt")) or 0) > time.time() - 3600:
            # New owned turns must appear immediately, even while a provider's
            # inventory is refreshing. The run store is their actual authority.
            summary = broker.find_summary(session, refresh=False)
            inventory.append(summary.public() if summary else {
                "id": session, "app": run.get("app"), "title": (run.get("taskText") or "Agent run").splitlines()[0][:140],
                "cwd": run.get("workspaceRoot"), "model": run.get("model")})
            seen.add(session)
    latest.update(broker.store.latest_many([row["id"] for row in inventory]))
    inventory.sort(key=lambda row: (latest.get(row["id"], {}).get("state") not in
                                   {"queued", "running", "waiting_approval", "waiting_input"},
                                   row.get("status") != "working"))
    def read(session):
        # Share each tail across overview refreshes; a slow provider read cannot
        # spawn duplicate reads for the same session during an event burst.
        key = ("agents-tail", str(broker.root), session["id"])
        with _swr_lock:
            _swr_cache.setdefault(key, [{}, 0.0, False])
        def compute():
            try:
                return _tail_pool.submit(broker.read, session["id"], limit=120).result()
            except Exception as exc:
                return {"items": [], "error": str(exc)[:160]}
        return _swr(key, 10, compute)
    pages = {session["id"]: read(session) for session in inventory}
    for session in inventory:
        identity = "session:" + session["id"]
        # The persisted latest turn is already in this one query. Do not recover
        # old turns or refresh every provider summary during an aggregate read.
        run = public_run(latest[session["id"]]) if session["id"] in latest else {}
        page = pages[session["id"]]
        error = page.get("error")
        activity = "Activity unavailable: " + error[:160] if error else (doing_now(page.get("items") or [], page.get("plan")) or {}).get("text")
        raw = {**session, **run, "state": run.get("state") or session.get("status"),
               "startedAt": run.get("startedAt") or session.get("status_since") or session.get("created_at"), "activity": activity}
        row = rows[identity] = node(identity, "sessions", session.get("title"), raw, app=session.get("app"),
                                    session=session["id"], run=run.get("runId"))
        row["actions"]["message"] = bool(run.get("canSteer") or session.get("app") in {"claude-code", "neyvia"})
        if run.get("canStop"):
            row["actions"]["stop"] = {"kind": "session", "id": run["runId"]}
        from .agents_overview_sources import session_subagents
        for child in session_subagents((page or {}).get("items") or [], raw):
            child_id = identity + ":" + str(child["id"])
            child_row = node(child_id, "sessions", child["title"], {**child, "activity": child.get("now")},
                             parent=identity, app=row["app"], session=session["id"], run=row["runId"])
            # Subagent input/output alone cannot distinguish cache reads.
            child_row["newTokens"] = None
            child_row["project"] = row["project"]
            child_row["worktree"], child_row["branch"] = row["worktree"], row["branch"]
            if child.get("durationMs") is not None:
                child_row["elapsedSeconds"] = max(0, child["durationMs"] / 1000)
            child_row["actions"] = {**row["actions"], "message": False, "stop": None}
            rows[child_id] = child_row

    from .agents_overview_sources import orchestration
    orchestration(service, rows, edges, source)
    for row in rows.values():
        if row.get("parentId"):
            edges.append({"from": row["parentId"], "to": row["id"], "kind": "parent"})
    # Message metadata is emitted by the real shared message boundary. No inbox
    # text is copied into this overview, and failed deliveries create no edge.
    with service.bus.connect() as db:
        messages = db.execute("SELECT payload FROM events WHERE action='agents.message.sent' ORDER BY id DESC LIMIT 100").fetchall()
    for (payload,) in messages:
        message = json.loads(payload)
        a, b = "session:" + str(message.get("from")), "session:" + str(message.get("to"))
        if a in rows and b in rows:
            edges.append({"from": a, "to": b, "kind": "messaged", "at": message.get("at")})
    from .usage_report import overview_usage
    usage = overview_usage(service.bus.root)
    session_tokens = usage.pop("sessionNewTokens", {})
    for row in rows.values():
        if row.get("sessionId") and row["newTokens"] is None and not row.get("parentId"):
            raw_id = row["sessionId"].rsplit(":", 1)[-1]
            key = next((key for key in session_tokens if key == raw_id or key.endswith(raw_id)), None)
            if key:
                row["newTokens"] = session_tokens[key]
    agents = [row for row in rows.values() if row.get("isAgent", True)]
    result = {"at": now(), "nodes": list(rows.values()), "edges": [e for e in edges if e["from"] in rows and e["to"] in rows],
              "totals": {"working": sum(row["state"] == "working" for row in agents),
                         "waiting": sum(row["state"] in {"waiting", "asking"} for row in agents),
                         "partial": any(not source["available"] for source in sources), **usage},
              "limits": service_for(broker.root).snapshot()["limits"], "sources": sources}
    check_graph(result)
    return result
