"""Bounded analytics over durable run receipts; no extra model calls or prompts."""
from __future__ import annotations

import json
from datetime import datetime

from .model_usage import FIELDS


def publish_indicator(bus, event):
    if event.get("type") != "usage.updated" or not isinstance(event.get("usage"), dict):
        return
    usage = event["usage"]
    tokens = usage.get("totalTokens")
    known = isinstance(tokens, int) and not isinstance(tokens, bool)
    cached = usage.get("cachedInputTokens")
    cached = cached if isinstance(cached, int) and not isinstance(cached, bool) and 0 <= cached <= (tokens or 0) else None
    # Cache reads re-send context the provider already holds; they dwarf the real work (often 95%+ of the
    # raw total) and are billed at a fraction of new input. Headline the new tokens, name the cache apart.
    fresh = tokens - cached if known and cached is not None else None
    if not known:
        label = "Latest run · usage unknown"
    elif fresh is not None:
        label = f"Latest run · {fresh:,} new tokens" + (f" · {cached:,} cached" if cached else "")
    else:
        label = f"Latest run · {tokens:,} tokens"
    reading = {"key": "usage", "runId": event.get("runId"), "unit": "tokens",
               "used": fresh if fresh is not None else tokens if known else None, "limit": None,
               "total": tokens if known else None, "cached": cached,
               "label": label + (" (partial)" if usage.get("coverage") == "partial" else "")}
    from .proofs_d_ui_planning import check_usage
    check_usage(usage, reading)
    bus.update("indicators", {"usage": reading})
    bus.emit("indicator.updated", reading)


def report(broker):
    with broker.store.connect() as db:
        rows = db.execute("SELECT data FROM connected_session_runs ORDER BY started DESC LIMIT 2000").fetchall()
        count = db.execute("SELECT count(*) FROM connected_session_runs").fetchone()[0]
    runs = [json.loads(row[0]) for row in rows]
    metrics = {}
    for key in FIELDS:
        values = [(run.get("usage") or {}).get(key) for run in runs]
        known = [index for index, value in enumerate(values) if isinstance(value, int) and not isinstance(value, bool)]
        full = [index for index in known if (runs[index].get("usage") or {}).get("reportedByTransport")]
        measured = sum(values[index] for index in known)
        metrics[key] = {"measured": measured, "reportedRuns": len(full), "partialRuns": len(known) - len(full),
                        "unknownRuns": len(runs) - len(known),
                        "total": measured if len(full) == len(runs) and count == len(runs) else None}
    groups = {}
    for run in runs:
        key = (run.get("app"), run.get("model"))
        group = groups.setdefault(key, {"harness": key[0], "requestedModel": key[1], "runs": 0,
                                       "completed": 0, "failed": 0, "active": 0})
        group["runs"] += 1
        group["completed"] += run["state"] == "completed"
        group["failed"] += run["state"] in {"failed", "cancelled", "interrupted"}
        group["active"] += run["state"] in {"queued", "running", "waiting_approval", "waiting_input"}
    recent = []
    for run in runs[:50]:
        elapsed = None
        if run.get("startedAt") and run.get("updatedAt"):
            elapsed = max(0, (datetime.fromisoformat(run["updatedAt"].replace("Z", "+00:00")) -
                              datetime.fromisoformat(run["startedAt"].replace("Z", "+00:00"))).total_seconds())
        recent.append({key: run.get(key) for key in ("runId", "sessionId", "app", "model", "effort", "permissionMode",
                                                    "state", "usage", "promptCharacters")} | {"elapsedSeconds": elapsed})
    return {"scope": "this backend's retained connected runs", "retentionDays": 30, "runs": len(runs),
            "truncated": count > len(runs), "metrics": metrics, "groups": list(groups.values()), "recent": recent,
            "cashCost": None, "cacheConvention": "cachedInputTokens is a subset of inputTokens",
            "notes": ["Unknown usage is not zero. No subscription cash cost is inferred.",
                      "Resumed thread totals are shown separately when no current baseline is available.",
                      "Standalone native receipts and runs outside this backend are excluded."]}
