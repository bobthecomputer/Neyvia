"""One-shot run watches using the existing scheduler and broker state events."""
from __future__ import annotations

import hashlib
import json

from .neyvia_time_tools import identity
from .ui_command_bus import now

STATES = ["completed", "failed", "interrupted", "cancelled", "waiting_approval", "waiting_input"]
S = {"type": "string"}
FOLLOWUP = {"type": "object", "properties": {key: S for key in ("app", "folder", "prompt", "model")}, "required": ["app", "folder", "prompt"], "additionalProperties": False}
DEFINITIONS = [
    ("watch.create", "Arm a one-shot notification for a retained run's terminal/waiting state. Optional read-only model follow-up requires exact-intent owner approval.",
     {"requestId": S, "runId": S, "message": S, "states": {"type": "array", "items": {"type": "string", "enum": STATES}}, "followup": FOLLOWUP}, ["requestId", "runId", "message"]),
    ("watch.list", "Read paged run watches and saved outcomes; uncertain effects never replay automatically.",
     {"offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, []),
    ("watch.cancel", "Cancel an armed run watch; already delivered follow-ups retain their schedule/run identity.", {"id": S}, ["id"]),
]


def rows(service, status=None):
    with service.bus.connect() as db:
        query = "SELECT value FROM state WHERE key LIKE 'watch:%'"
        values = db.execute(query + (" AND json_extract(value,'$.status')=?" if status else "") + " ORDER BY rowid", (status,) if status else ()).fetchall()
    return [json.loads(row[0]) for row in values]


def call(service, name, args):
    if name == "watch.list":
        offset, limit = args.get("offset", 0), args.get("limit", 20)
        with service.bus.connect() as db:
            values = db.execute("SELECT value FROM state WHERE key LIKE 'watch:%' ORDER BY rowid LIMIT ? OFFSET ?", (limit + 1, offset)).fetchall()
        return {"ok": True, "watches": [json.loads(row[0]) for row in values[:limit]], "nextOffset": offset + limit if len(values) > limit else None}
    key = "watch:" + identity(args.get("requestId") if name == "watch.create" else args.get("id"))
    old = service.bus.get(key)
    if name == "watch.cancel":
        if not old:
            raise ValueError("Unknown watch")
        if old["status"] == "cancelled":
            return {"ok": True, "watch": old, "replayed": True}
        if old["status"] != "armed":
            raise ValueError("This watch has already fired; inspect its schedule/run before cancelling that work")
        old.update(status="cancelled", updatedAt=now())
        service.bus.put(key, old)
        service.wake.set()
        return {"ok": True, "watch": old}
    states = args.get("states", STATES[:4])
    if not isinstance(states, list) or not states or any(state not in STATES for state in states):
        raise ValueError("Select one or more supported terminal/waiting states")
    if not isinstance(args["message"], str) or not args["message"].strip() or len(args["message"]) > 2000:
        raise ValueError("Use a notification message of 1–2,000 characters")
    spec = {"id": args["requestId"], "runId": identity(args["runId"]), "message": args["message"], "states": sorted(set(states)), "followup": args.get("followup")}
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    if old:
        if old["fingerprint"] != fingerprint:
            raise ValueError("requestId already represents a different watch")
        return {"ok": True, "watch": old, "replayed": True}
    service.broker().get_run(spec["runId"])
    if len(rows(service, "armed")) >= 64:
        raise ValueError("64 active watches already exist; cancel an obsolete watch before arming another")
    if spec["followup"] is not None:
        from .neyvia_workspace_tools import harness_mode
        followup = spec["followup"]
        if not isinstance(followup, dict) or set(followup) - {"app", "folder", "prompt", "model"}:
            raise ValueError("Follow-up accepts only an explicit app/folder/prompt/model; permissions are read-only")
        folder = service.safe_path(followup["folder"])
        if not folder.is_dir() or not isinstance(followup["prompt"], str) or not followup["prompt"].strip():
            raise ValueError("Follow-up needs an existing safe folder and exact nonempty prompt")
        harness_mode(followup["app"], "read-only")
        refusal = service.require_approval("watch:" + fingerprint, "Approve one read-only follow-up for this run condition", {**spec, "permissionMode": "read-only", "intentSha256": fingerprint})
        if refusal:
            return refusal
    row = {"id": args["requestId"], **spec, "fingerprint": fingerprint, "status": "armed", "createdAt": now()}
    service.bus.put(key, row)
    with service._watch_event_lock:
        service._watch_targets.add(row["runId"])
        service._watching = True
    service.start_timers()
    service.wake.set()
    return {"ok": True, "watch": row}


def evaluate(service):
    """Called only on existing scheduler startup/wake; no polling or model check."""
    with service._watch_event_lock:
        transitions, service._watch_events = service._watch_events, {}
    for row in rows(service, "armed") + rows(service, "firing"):
        key = "watch:" + row["id"]
        if row["status"] == "firing":
            row.update(status="uncertain", reason="Service lost a firing watch; inspect its saved event/schedule, never auto-replay", updatedAt=now())
            service.bus.put(key, row)
        if row["status"] != "armed":
            continue
        try:
            run = service.broker().get_run(row["runId"])
            captured = {state: at for state, at in transitions.get(row["runId"], {}).items() if state in row["states"] and at >= row["createdAt"]}
            trigger = run["state"] if run["state"] in row["states"] else max(captured, key=captured.get) if captured else None
            if not trigger:
                continue
            row.update(status="firing", triggerState=trigger, currentState=run["state"], triggerObservedAt=captured.get(trigger) or now(), updatedAt=now())
            service.bus.put(key, row)
            row["event"] = service.bus.emit("notify", {"message": row["message"], "level": "warning" if trigger in {"failed", "interrupted", "waiting_approval", "waiting_input"} else "info", "watchId": row["id"], "runId": row["runId"], "state": trigger, "currentState": run["state"], "observedAt": row["triggerObservedAt"]})
            if row["followup"]:
                followup = row["followup"]
                row["schedule"] = service.call("schedule.after", {"seconds": 1, "requestId": "watch-followup-" + hashlib.sha256(row["id"].encode()).hexdigest(), "prompt": followup["prompt"],
                    "scope": {key: value for key, value in followup.items() if key != "prompt"} | {"permissionMode": "read-only"}})["schedule"]
            row.update(status="fired", updatedAt=now())
        except Exception as exc:
            row.update(status="uncertain" if row["status"] == "firing" else "blocked", reason=str(exc)[:500], updatedAt=now())
        service.bus.put(key, row)
    active = rows(service, "armed")
    with service._watch_event_lock:
        service._watch_targets = {row["runId"] for row in active}
        service._watching = bool(active)
