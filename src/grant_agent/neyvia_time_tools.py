"""Precise clocks and durable elapsed timers; timers never cancel agent work."""
from __future__ import annotations

import json
import math
import time
import uuid
from datetime import datetime, timedelta, timezone

EPOCH = uuid.uuid4().hex
S = {"type": "string"}
PHASE = {"type": "string", "enum": ["planning", "execution", "verification", "review", "other"]}
PAGE = {"offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}
DEFINITIONS = [
    ("time.now", "Read precise UTC and local time without a model inference.", {}, []),
    ("time.budget", "Inspect deadline risk and verification reserve; advisory only, never stops required work.",
     {"deadlineAt": S, "estimatedNextSeconds": {"type": "number", "minimum": 0}, "verificationReserveSeconds": {"type": "number", "minimum": 0}, "optional": {"type": "boolean"}}, []),
    ("timer.start", "Start a persistent elapsed timer. Same ID replays identical intent; targetSeconds is advisory.",
     {"id": S, "label": S, "phase": PHASE, "targetSeconds": {"type": "number", "exclusiveMinimum": 0}}, ["id", "label"]),
    ("timer.read", "Read elapsed time and paged laps; monotonic while live, explicitly wall-clock estimated across restarts.", {"id": S, **PAGE}, ["id"]),
    ("timer.lap", "Record a named timing checkpoint exactly once per lapId; no model or CPU-time claim.", {"id": S, "lapId": S, "label": S, "phase": PHASE}, ["id", "lapId", "label"]),
    ("timer.stop", "Stop the elapsed timer; repeated stops return the saved measurement.", {"id": S}, ["id"]),
    ("timer.list", "Read a paged timer inventory without scanning provider transcripts.", {"status": {"type": "string", "enum": ["running", "stopped", "all"]}, **PAGE}, []),
    ("schedule.after", "Schedule one follow-up in seconds, using the existing durable scheduler and exact requestId retries.",
     {"seconds": {"type": "number", "exclusiveMinimum": 0}, "prompt": S, "scope": {"type": "object", "x-empty-text-is-empty-object": True, "description": "Empty object means notification only. An empty text transport wrapper uses this same safe scope."}, "requestId": S}, ["seconds", "prompt", "scope", "requestId"]),
]


def stamp():
    return datetime.now(timezone.utc)


def positive(value):
    if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
        raise ValueError("Seconds must be finite and positive")
    return value


def identity(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError("Use a stable nonempty ID of at most 160 characters")
    return value


def label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("Use a timing label of 1–200 characters")
    return value


def measure(row, *, wall=None, monotonic=None):
    delta, recovered = 0, row.get("recovered", False)
    if row["status"] == "running":
        if row["epoch"] == EPOCH:
            delta = max(0, (time.monotonic() if monotonic is None else monotonic) - row["anchorMonotonic"])
        else:
            delta = ((wall or stamp()) - datetime.fromisoformat(row["anchorUtc"])).total_seconds()
            recovered = True
    elapsed = row["elapsedBase"] + max(0, delta)
    return {"elapsedSeconds": round(elapsed, 6), "clockBasis": "wall_clock_recovered_estimate" if recovered else "monotonic",
            "clockAnomaly": delta < 0 or row.get("clockAnomaly", False), "targetSeconds": row.get("targetSeconds"),
            "remainingSeconds": max(0, row["targetSeconds"] - elapsed) if row.get("targetSeconds") else None,
            "targetExceeded": elapsed > row["targetSeconds"] if row.get("targetSeconds") else False}


def view(row, args):
    offset, limit = args.get("offset", 0), args.get("limit", 20)
    laps = row["laps"]
    return {**{key: row.get(key) for key in ("id", "label", "phase", "status", "startedAt", "stoppedAt")}, **measure(row),
            "laps": laps[offset:offset + limit], "lapCount": len(laps), "nextOffset": offset + limit if len(laps) > offset + limit else None,
            "scope": "elapsed time, not CPU time or provider cost; target is advisory"}


def call(service, name, args):
    if name == "time.now":
        current = stamp()
        return {"ok": True, "utc": current.isoformat().replace("+00:00", "Z"), "unixSeconds": current.timestamp(),
                "timezone": "UTC", "local": current.astimezone().isoformat()}
    if name == "time.budget":
        if args.get("deadlineAt") and datetime.fromisoformat(args["deadlineAt"].replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("deadlineAt requires an explicit timezone")
        from .crashproof import CrashProofStore
        return {"ok": True, **CrashProofStore(service.bus.root).time_snapshot(deadline_at=args.get("deadlineAt"),
                estimated_next_seconds=args.get("estimatedNextSeconds", 0), verification_reserve_seconds=args.get("verificationReserveSeconds", 0), optional=args.get("optional", False)),
                "advisory": True}
    if name == "schedule.after":
        seconds = positive(args["seconds"])
        old = service.bus.get("schedules", {}).get(identity(args["requestId"]))
        if old:
            if old.get("relativeSeconds") != seconds or any(old.get(key) != args[key] for key in ("scope", "prompt")):
                raise ValueError("requestId already represents a different follow-up")
            return {"ok": True, "schedule": old, "replayed": True}
        return service.schedule("schedule.create", {key: value for key, value in args.items() if key != "seconds"} |
                                {"when": (stamp() + timedelta(seconds=seconds)).isoformat(), "relativeSeconds": seconds})
    if name == "timer.list":
        status = args.get("status", "all")
        with service.bus.connect() as db:
            rows = db.execute("SELECT value FROM state WHERE key LIKE 'timer:%' AND (?='all' OR json_extract(value,'$.status')=?) ORDER BY rowid LIMIT ? OFFSET ?",
                              (status, status, args.get("limit", 20) + 1, args.get("offset", 0))).fetchall()
        limit, offset = args.get("limit", 20), args.get("offset", 0)
        return {"ok": True, "timers": [view(json.loads(row[0]), {"limit": 1}) for row in rows[:limit]],
                "nextOffset": offset + limit if len(rows) > limit else None}
    key = "timer:" + identity(args["id"])
    row = service.bus.get(key)
    if name == "timer.start":
        intended = {"label": label(args["label"]), "phase": args.get("phase", "execution"), "targetSeconds": positive(args["targetSeconds"]) if args.get("targetSeconds") is not None else None}
        if row:
            if any(row.get(field) != value for field, value in intended.items()):
                raise ValueError("Timer ID already represents a different intent; use a new ID")
            return {"ok": True, "timer": view(row, {}), "replayed": True}
        current = stamp().isoformat()
        row = {"id": args["id"], **intended, "status": "running", "startedAt": current, "anchorUtc": current,
               "anchorMonotonic": time.monotonic(), "epoch": EPOCH, "elapsedBase": 0, "laps": []}
    else:
        if not row:
            raise ValueError("Unknown timer")
        if name == "timer.read":
            return {"ok": True, "timer": view(row, args)}
        current, anchor = stamp(), time.monotonic()
        measured = measure(row, wall=current, monotonic=anchor)
        if name == "timer.lap":
            lap_id = identity(args["lapId"])
            previous = next((lap for lap in row["laps"] if lap["id"] == lap_id), None)
            intended = {"label": label(args["label"]), "phase": args.get("phase", row["phase"])}
            if previous:
                if any(previous[field] != value for field, value in intended.items()):
                    raise ValueError("lapId already represents a different checkpoint")
                return {"ok": True, "lap": previous, "replayed": True}
            if row["status"] != "running" or len(row["laps"]) >= 1000:
                raise ValueError("Laps require a running timer with fewer than 1,000 checkpoints; use a new timer for longer histories")
            last = row["laps"][-1]["elapsedSeconds"] if row["laps"] else 0
            lap = {"id": lap_id, **intended, **measured, "intervalSeconds": round(measured["elapsedSeconds"] - last, 6), "at": current.isoformat()}
            row["laps"].append(lap)
        elif name == "timer.stop":
            if row["status"] == "stopped":
                return {"ok": True, "timer": view(row, args), "replayed": True}
            row.update(status="stopped", stoppedAt=current.isoformat())
        else:
            raise ValueError("Unknown time tool")
        row.update(elapsedBase=measured["elapsedSeconds"], recovered=measured["clockBasis"] != "monotonic", clockAnomaly=measured["clockAnomaly"], anchorUtc=current.isoformat(), anchorMonotonic=anchor, epoch=EPOCH)
    service.bus.put(key, row)
    timer = view(row, args)
    event = service.bus.emit("timer.changed", {"timer": timer})
    return {"ok": True, "timer": timer, "event": event, **({"lap": lap} if name == "timer.lap" else {})}
