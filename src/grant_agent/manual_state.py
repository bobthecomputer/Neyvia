"""Durable observation handles, bounded projections and JSON Patch deltas."""
from __future__ import annotations
import hashlib
import json
import re
import uuid
from .durability import atomic_write_json


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pointer(value, path):
    if not path:
        return value
    if not path.startswith("/"):
        raise ValueError("Projection path must be a JSON Pointer")
    for part in path[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def changes(before, after, path=""):
    if type(before) is not type(after):
        return [{"op": "replace", "path": path, "value": after}]
    if isinstance(before, dict):
        rows = [{"op": "remove", "path": path + "/" + escape(key)} for key in sorted(before.keys() - after.keys())]
        for key in sorted(after):
            child = path + "/" + escape(key)
            rows += changes(before[key], after[key], child) if key in before else [{"op": "add", "path": child, "value": after[key]}]
        return rows
    if isinstance(before, list) and len(before) == len(after):
        return [row for index, (old, new) in enumerate(zip(before, after)) for row in changes(old, new, path + "/" + str(index))]
    return [] if before == after else [{"op": "replace", "path": path, "value": after}]


def escape(key):
    return key.replace("~", "~0").replace("/", "~1")


def read(root, handle):
    if not re.fullmatch(r"[a-f0-9]{32}", handle):
        raise ValueError("Invalid state handle")
    row = json.loads((root / "manual-state" / (handle + ".json")).read_text(encoding="utf-8"))
    if hashlib.sha256(encoded(row["value"]).encode()).hexdigest() != row["valueSha256"]:
        raise ValueError("State handle integrity check failed")
    return row


def project(root, args):
    row = read(root, args["handle"])
    value = pointer(row["value"], args.get("path", ""))
    offset, limit = args.get("offset", 0), args.get("limit", 20)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("offset >= 0 and limit 1..100 required")
    size = len(value) if isinstance(value, (str, list, dict)) else 1
    if isinstance(value, dict):
        keys = list(value)[offset:offset + limit]
        projected = {key: value[key] for key in keys}
    elif isinstance(value, (str, list)):
        projected = value[offset:offset + limit]
    else:
        projected = value if offset == 0 else None
    if len(encoded(projected)) > 8000:
        return {"ok": True, "handle": args["handle"], "path": args.get("path", ""), "total": size,
                "tooLarge": True, "hint": "Choose a deeper path or smaller limit; no value was pasted."}
    end = min(size, offset + limit)
    return {"ok": True, "handle": args["handle"], "path": args.get("path", ""), "value": projected,
            "offset": offset, "total": size, "nextOffset": end if end < size else None, "valueSha256": row["valueSha256"]}


def observe(root, metadata, value, args):
    """A stream's first result is a small snapshot or handle; later results are deltas."""
    root.mkdir(parents=True, exist_ok=True)
    stream = {**metadata, "inputs": args.get("inputs") or {}, "scopeTools": args.get("scopeTools"), "stream": args.get("stream", "default")}
    key = hashlib.sha256(encoded(stream).encode()).hexdigest()
    latest = root / "manual-state-streams" / (key + ".json")
    previous = args.get("previousHandle")
    if not previous and latest.exists() and not args.get("reset"):
        previous = json.loads(latest.read_text(encoding="utf-8"))["handle"]
    baseline = read(root, previous) if previous else None
    if baseline and baseline["streamKey"] != key:
        raise ValueError("Previous handle belongs to another observer, input, scope or stream")
    handle = uuid.uuid4().hex
    row = {**metadata, "streamKey": key, "value": value, "valueSha256": hashlib.sha256(encoded(value).encode()).hexdigest()}
    atomic_write_json(root / "manual-state" / (handle + ".json"), row)
    response = {"ok": True, **metadata, "handle": handle, "valueSha256": row["valueSha256"], "characters": len(encoded(value))}
    if baseline:
        delta = changes(baseline["value"], value)
        response.update(mode="diff", previousHandle=previous)
        if len(encoded(delta)) <= 8000:
            response["diff"] = delta
        else:
            diff_handle = uuid.uuid4().hex
            atomic_write_json(root / "manual-state" / (diff_handle + ".json"), {**metadata, "streamKey": key, "value": delta,
                              "valueSha256": hashlib.sha256(encoded(delta).encode()).hexdigest()})
            response.update(diffHandle=diff_handle, changes=len(delta))
    elif len(encoded(value)) <= 4000:
        response.update(mode="snapshot", observed=value)
    else:
        response.update(mode="handle", hint="Use manual.project(handle,path,offset,limit) for selected state.")
    atomic_write_json(latest, {"handle": handle})
    return response
