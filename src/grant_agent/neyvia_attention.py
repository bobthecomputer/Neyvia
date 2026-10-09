"""A bounded actionable inbox from saved owner approvals, tasks and run states."""
from __future__ import annotations

import json
import sqlite3
import math
from contextlib import closing
from datetime import datetime, timedelta, timezone

from .ui_command_bus import now

DEFINITIONS = [("attention.list", "Read actual pending owner reviews, waiting/failed runs and blocked tasks. Local receipts only; no model polling or automatic action.",
    {"limit": {"type": "integer", "minimum": 1, "maximum": 100}, "offset": {"type": "integer", "minimum": 0},
     "recentHours": {"type": "number", "minimum": 0.01, "maximum": 720}}, [])]


def call(service, args):
    limit, offset, hours = args.get("limit", 20), args.get("offset", 0), args.get("recentHours", 24)
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0 or type(hours) not in {int, float} or not math.isfinite(hours) or not .01 <= hours <= 720:
        raise ValueError("Use limit 1–100, offset >=0 and recentHours .01–720")
    items = []
    with service.bus.connect() as db:
        approvals = db.execute("SELECT a.key,a.value FROM state a WHERE a.key LIKE 'approval:%' AND NOT EXISTS (SELECT 1 FROM state s WHERE s.key IN ('grant:'||json_extract(a.value,'$.key'),'denied:'||json_extract(a.value,'$.key')) AND s.value='true') ORDER BY a.rowid DESC LIMIT 1000").fetchall()
    for row in approvals:
        approval = json.loads(row["value"])
        items.append({"id": row["key"], "kind": "approval", "priority": 0, "title": approval["description"], "approvalId": row["key"][9:], "details": approval.get("details")})
    path = service.bus.root / ".agent_control/nightshift.sqlite3"
    task_truncated = False
    if path.exists():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute("SELECT id,body,reason,updated FROM tasks WHERE status='blocked' ORDER BY updated DESC LIMIT 1001").fetchall()
        task_truncated = len(rows) > 1000
        for identity, body, reason, updated in rows[:1000]:
            task = json.loads(body)
            items.append({"id": "task:" + identity, "kind": "blocked_task", "priority": 1, "title": task.get("title") or identity, "reason": reason, "updatedAt": updated, "taskId": identity})
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with service.broker().store.connect() as db:
        runs = db.execute("SELECT data FROM connected_session_runs WHERE json_extract(data,'$.state') IN ('waiting_approval','waiting_input','failed','interrupted') AND (json_extract(data,'$.state') IN ('waiting_approval','waiting_input') OR json_extract(data,'$.updatedAt')>=?) ORDER BY started DESC LIMIT 1001", (since,)).fetchall()
    for raw in runs[:1000]:
        run = json.loads(raw[0])
        waiting = run["state"] in {"waiting_approval", "waiting_input"}
        items.append({"id": "run:" + run["runId"], "kind": "waiting_run" if waiting else "failed_run", "priority": 0 if waiting else 2,
                      **{key: run.get(key) for key in ("runId", "sessionId", "app", "state", "error", "updatedAt")},
                      "title": (run.get("pendingRequest") or {}).get("title") or run["state"]})
    items.sort(key=lambda row: row["priority"])
    return {"ok": True, "items": items[offset:offset + limit], "nextOffset": offset + limit if len(items) > offset + limit else None,
            "inspectedItems": len(items), "truncated": len(approvals) == 1000 or task_truncated or len(runs) > 1000,
            "observedAt": now(), "scope": "saved local approvals/blocked tasks and recent failed runs; no independent outcome judgement", "providerCalls": 0}
