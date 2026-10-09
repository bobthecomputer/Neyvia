"""Persisted night periods and every harness attempt, including failed retries."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .ui_command_bus import now

HARNESSES = ("codex", "claude-code", "neyvia", "opencode")


def timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def initialize(service):
    with service.lock:
        if getattr(service, "_night_ledger_ready", False):
            return
        with service.connect() as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(attempts)")}
            for key, kind in {"night_id": "TEXT", "harness": "TEXT", "started": "TEXT",
                              "finished": "TEXT", "elapsed": "REAL", "effective_limits": "TEXT"}.items():
                if key not in columns:
                    db.execute(f"ALTER TABLE attempts ADD COLUMN {key} {kind}")
            db.execute("CREATE TABLE IF NOT EXISTS night_periods (night_id TEXT PRIMARY KEY, started TEXT NOT NULL, active INTEGER NOT NULL)")
            period = db.execute("SELECT * FROM night_periods WHERE active=1").fetchone()
            if not period:
                identity, started = uuid.uuid4().hex, now()
                db.execute("INSERT INTO night_periods VALUES(?,?,1)", (identity, started))
            else:
                identity, started = period["night_id"], period["started"]
            # Older saved attempts remain accounted for; missing usage stays explicitly unknown.
            tasks = {task["id"]: task for task in service.tasks()}
            for row in db.execute("SELECT * FROM attempts WHERE night_id IS NULL").fetchall():
                task = tasks.get(row["task"], {})
                terminal = task.get("status") != "running" or task.get("runId") != row["run_id"]
                db.execute("UPDATE attempts SET night_id=?,harness=?,started=?,finished=?,elapsed=? WHERE run_id=?",
                           (identity, task.get("harness"), task.get("updatedAt") or started,
                            started if terminal else None, 0 if terminal else None, row["run_id"]))
        service._night_ledger_ready = True


def period(service):
    initialize(service)
    with service.connect() as db:
        row = db.execute("SELECT * FROM night_periods WHERE active=1").fetchone()
    return {"nightId": row["night_id"], "startedAt": row["started"]}


def begin(service):
    initialize(service)
    with service.lock:
        if any(task["status"] == "running" for task in service.tasks()):
            raise ValueError("Stop or finish running tasks before starting a new night")
        identity, started = uuid.uuid4().hex, now()
        with service.connect() as db:
            db.execute("UPDATE night_periods SET active=0 WHERE active=1")
            db.execute("INSERT INTO night_periods VALUES(?,?,1)", (identity, started))
        result = {"nightId": identity, "startedAt": started}
        service.bus.emit("nightshift.night.started", result)
        resources = getattr(service, "resources", None)
        if resources:
            resources.refresh_timers()
        return result


def record(service, task, effective_limits=None):
    current = period(service)
    with service.lock, service.connect() as db:
        db.execute("INSERT OR IGNORE INTO attempts(run_id,task) VALUES(?,?)", (task["runId"], task["id"]))
        db.execute("UPDATE attempts SET night_id=COALESCE(night_id,?),harness=COALESCE(harness,?),"
                   "started=COALESCE(started,?),effective_limits=COALESCE(effective_limits,?) WHERE run_id=?",
                   (current["nightId"], task["harness"], now(), json.dumps(effective_limits or {}), task["runId"]))


def rename_run(service, old_id, new_id):
    if old_id != new_id:
        with service.connect() as db:
            db.execute("UPDATE attempts SET run_id=? WHERE run_id=?", (new_id, old_id))


def attempt(service, run_id):
    initialize(service)
    with service.connect() as db:
        row = db.execute("SELECT * FROM attempts WHERE run_id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def finish(service, task):
    """Capture transport usage before another task can consume the remaining budget."""
    initialize(service)
    with service.lock:
        row = attempt(service, task.get("runId"))
        if not row or row["finished"]:
            return
        try:
            run = service.broker.get_run(task["runId"])
        except Exception as exc:
            if getattr(exc, "code", None) != "run_not_found":
                raise
            run = {}
        if run.get("state") not in {None, "completed", "failed", "cancelled", "interrupted"}:
            raise ValueError("Cannot finish accounting for an active harness run")
        finished = now()
        elapsed = max(0.0, (timestamp(finished) - timestamp(row["started"])).total_seconds())
        # Prefer final transport usage; an absent final report may still have prior live usage.
        usage = run.get("usage") if run.get("usage") is not None else (json.loads(row["usage"]) if row["usage"] else None)
        with service.connect() as db:
            db.execute("UPDATE attempts SET finished=?,elapsed=?,usage=? WHERE run_id=? AND finished IS NULL",
                       (finished, elapsed, json.dumps(usage) if usage is not None else None, task["runId"]))


def recover_claude_usage(service, row, usage):
    """Repair older terminal attempts from their exact saved session and turn window."""
    usage = usage if isinstance(usage, dict) else {}
    if row["harness"] != "claude-code" or not row["finished"]:
        return usage
    if usage.get("reportedByTransport") and all(isinstance(usage.get(key), int) for key in
                                                ("inputTokens", "outputTokens", "cachedInputTokens", "totalTokens")):
        return usage
    run = service.broker.store.load(row["run_id"])
    if not run or not all(run.get(key) for key in ("sessionId", "startedAt", "updatedAt")) or run.get("state") not in {"completed", "failed", "cancelled", "interrupted"}:
        return usage
    try:
        from .connected_sessions.claude_usage import ClaudeTranscriptUsage
        _, path = service.broker._adapter("claude-code")._locate(run["sessionId"])
        recovered = ClaudeTranscriptUsage(timestamp(run["startedAt"]), timestamp(run["updatedAt"])).poll(path)
    except (OSError, ValueError, RuntimeError):
        return usage  # The saved transcript may have been removed; never manufacture zero usage.
    if recovered is not None:
        with service.connect() as db:
            db.execute("UPDATE attempts SET usage=? WHERE run_id=? AND finished IS NOT NULL",
                       (json.dumps(recovered), row["run_id"]))
        return recovered
    return usage


def summary(service):
    current = period(service)
    current_time = datetime.now(timezone.utc)
    policy = service.resources.policy()
    rows_by_harness = {harness: {"reportedTokens": 0, "elapsedSeconds": 0.0,
                                "inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0, "tokenBreakdownUnknownRuns": 0,
                                "knownRuns": 0, "unknownRuns": 0, "unknownCompletedRuns": 0, "running": 0,
                                "maxTokens": (policy.get("perHarnessBudgets", {}).get(harness) or {}).get("maxTokens"),
                                "maxSeconds": (policy.get("perHarnessBudgets", {}).get(harness) or {}).get("maxSeconds")}
                       for harness in HARNESSES}
    with service.connect() as db:
        attempts = db.execute("SELECT * FROM attempts WHERE night_id=?", (current["nightId"],)).fetchall()
    known_attempts, unknown_attempts = [], []
    for row in attempts:
        harness = row["harness"]
        if harness not in rows_by_harness:
            continue
        target = rows_by_harness[harness]
        usage = recover_claude_usage(service, row, json.loads(row["usage"]) if row["usage"] else {})
        tokens = (usage or {}).get("totalTokens")
        known = isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0 and bool((usage or {}).get("reportedByTransport"))
        (known_attempts if known else unknown_attempts).append(row["run_id"])
        if known:
            target["reportedTokens"] += tokens
        # Input already includes cache writes and reads (model_usage receipts).
        # Keep budget totals unchanged; expose the Usage screen's separate counters.
        split = [(usage or {}).get(key) for key in ("inputTokens", "outputTokens", "cachedInputTokens")]
        if known and all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in split) and split[2] <= split[0]:
            for key, value in zip(("inputTokens", "outputTokens", "cachedInputTokens"), split):
                target[key] += value
        else:
            target["tokenBreakdownUnknownRuns"] += 1
        target["knownRuns" if known else "unknownRuns"] += 1
        if row["finished"]:
            if not known:
                target["unknownCompletedRuns"] += 1
            target["elapsedSeconds"] += row["elapsed"] or 0
        else:
            target["running"] += 1
            target["elapsedSeconds"] += max(0.0, (current_time - timestamp(row["started"])).total_seconds())
    for target in rows_by_harness.values():
        target["elapsedSeconds"] = round(target["elapsedSeconds"], 3)
    elapsed = round(sum(row["elapsedSeconds"] for row in rows_by_harness.values()), 3)
    return {"night": {**current, "elapsedSeconds": max(0.0, (current_time - timestamp(current["startedAt"])).total_seconds())},
            "perHarness": rows_by_harness, "elapsedSeconds": elapsed,
            "usage": {"reportedTokens": sum(row["reportedTokens"] for row in rows_by_harness.values()),
                      **{key: sum(row[key] for row in rows_by_harness.values())
                         for key in ("inputTokens", "outputTokens", "cachedInputTokens", "tokenBreakdownUnknownRuns")},
                      "knownRuns": sum(row["knownRuns"] for row in rows_by_harness.values()),
                      "unknownRuns": sum(row["unknownRuns"] for row in rows_by_harness.values()),
                      "attempts": len(attempts), "knownTasks": known_attempts,
                      "unknownTasks": unknown_attempts, "complete": not unknown_attempts, "cashCost": None}}
