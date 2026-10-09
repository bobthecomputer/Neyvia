"""Published outputs share the workspace bus, durable identity and guarded previews.

Publishing registers bytes already on disk; opening verifies those same bytes.
No output is executed and no arbitrary URL is fetched. Events and rows commit
together so an interrupted process cannot publish a notification without its row.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import uuid
from pathlib import Path

from .ui_command_bus import now

KINDS = ["file", "diff", "image", "report", "receipt"]
TEXT = {"type": "string"}
DEFINITIONS = [
    ("artifact.publish", "Register an existing output with hash and provenance in the shared Outputs panel. Reuse requestId for retries; changed bytes produce a new version.",
     {"path": TEXT, "kind": {"type": "string", "enum": KINDS}, "title": TEXT,
      "sessionId": TEXT, "runId": TEXT, "requestId": TEXT, "metadata": {"type": "object"}}, ["path"]),
    ("artifact.list", "Read published outputs, newest first, with optional kind/session/run filters and pagination.",
     {"kind": {"type": "string", "enum": KINDS}, "sessionId": TEXT, "runId": TEXT,
      "limit": {"type": "integer", "minimum": 1, "maximum": 200}, "offset": {"type": "integer", "minimum": 0}}, []),
    ("artifact.get", "Read a publication and check whether its exact bytes are still available.", {"id": TEXT}, ["id"]),
    ("artifact.open", "Verify published bytes, then open the existing guarded artifact/diff/file pane. Refuses changed or missing bytes.", {"id": TEXT}, ["id"]),
]
COMMANDS = {"artifact_" + op + "_command": "artifact." + op for op in ("publish", "list", "get", "open")}
COMMANDS["app_open_command"] = "app.open"


def failure(status, message):
    return {"ok": False, "status": status, "error": message}


def _text(args, key, limit=1000):
    value = args.get(key, "")
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{key} must be text of at most {limit} characters")
    return value.strip()


def _path(service, value):
    from .neyvia_files_tools import guard
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = service.bus.root / path
    # Same real-path guard as Files; resolve before touching any bytes.
    resolved = path.resolve()
    for protected in (Path(r"C:\Users\user\Projects\Neyvia-next"),):
        if resolved == protected or protected in resolved.parents:
            raise ValueError("The shared Neyvia-next tree is protected")
    return guard(service.bus.root, str(resolved))


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        stat = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    current = path.stat()
    if (stat.st_size, stat.st_mtime_ns, stat.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or (
            after.st_size, after.st_mtime_ns, after.st_ino) != (current.st_size, current.st_mtime_ns, current.st_ino):
        raise ValueError("The output changed while reading it; retry after the writer finishes")
    return digest.hexdigest(), stat.st_size


def _tables(db):
    db.execute("CREATE TABLE IF NOT EXISTS published_outputs (id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL, session_id TEXT NOT NULL, run_id TEXT NOT NULL, row_json TEXT NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS published_outputs_path ON published_outputs(path)")
    db.execute("CREATE TABLE IF NOT EXISTS output_requests (id TEXT PRIMARY KEY, intent TEXT NOT NULL, output_id TEXT NOT NULL)")


def publish(service, args):
    path_text = _text(args, "path", 32768)
    if not path_text:
        raise ValueError("Give a path to an existing output")
    path = _path(service, path_text)
    if not path.is_file():
        return failure("missing", "That output file does not exist")
    digest, size = _digest(path)
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    kind = args.get("kind") or ("image" if media.startswith("image/") else "diff" if path.suffix.lower() in {".diff", ".patch"} else "file")
    if kind not in KINDS:
        raise ValueError("Choose file, diff, image, report or receipt")
    title = _text(args, "title", 300) or path.name
    session, run = _text(args, "sessionId"), _text(args, "runId")
    request = _text(args, "requestId", 200)
    metadata = args.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    encoded = json.dumps(metadata, sort_keys=True, allow_nan=False)
    if len(encoded.encode()) > 16384:
        raise ValueError("metadata must fit in 16 KB")
    fingerprint = hashlib.sha256(json.dumps([os.path.normcase(str(path)), digest, kind, session, run]).encode()).hexdigest()
    intent = hashlib.sha256(json.dumps([fingerprint, title, metadata], sort_keys=True, allow_nan=False).encode()).hexdigest()
    with service.bus.connect() as db:
        _tables(db)
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT * FROM output_requests WHERE id=?", (request,)).fetchone() if request else None
        if prior and prior["intent"] != intent:
            return failure("conflict", "requestId already describes different output bytes or metadata")
        existing = db.execute("SELECT row_json FROM published_outputs WHERE fingerprint=?", (fingerprint,)).fetchone()
        if existing:
            row = json.loads(existing[0])
            event = None
        else:
            previous = db.execute("SELECT id FROM published_outputs WHERE path=? AND kind=? AND session_id=? AND run_id=? ORDER BY rowid DESC LIMIT 1", (str(path), kind, session, run)).fetchone()
            row = {"id": uuid.uuid4().hex, "kind": kind, "title": title, "path": str(path), "name": path.name,
                   "mediaType": media, "size": size, "sha256": digest, "createdAt": now(),
                   "sessionId": session, "runId": run, "metadata": metadata, "previousId": previous[0] if previous else None}
            db.execute("INSERT INTO published_outputs VALUES(?,?,?,?,?,?,?)", (row["id"], fingerprint, str(path), kind, session, run, json.dumps(row)))
            payload = {"artifact": row}
            cursor = db.execute("INSERT INTO events(ts,action,payload) VALUES(?,?,?)", (row["createdAt"], "artifact.published", json.dumps(payload)))
            event = {"id": str(cursor.lastrowid), "ts": row["createdAt"], "action": "artifact.published", "payload": payload}
        if request and not prior:
            db.execute("INSERT INTO output_requests VALUES(?,?,?)", (request, intent, row["id"]))
    if event:
        with service.bus.changed:
            service.bus.changed.notify_all()
    return {"ok": True, "artifact": row, "replayed": existing is not None, **({"event": event} if event else {})}


def listing(service, args):
    limit, offset = args.get("limit", 50), args.get("offset", 0)
    if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
        raise ValueError("Use limit 1–200 and a nonnegative offset")
    conditions, values = [], []
    for key, column in (("kind", "kind"), ("sessionId", "session_id"), ("runId", "run_id")):
        if key in args and args[key] != "":
            value = _text(args, key)
            if key == "kind" and value not in KINDS:
                raise ValueError("Unknown output kind")
            conditions.append(column + "=?")
            values.append(value)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with service.bus.connect() as db:
        _tables(db)
        db.execute("BEGIN")
        total = db.execute("SELECT COUNT(*) FROM published_outputs" + where, values).fetchone()[0]
        rows = db.execute("SELECT row_json FROM published_outputs" + where + " ORDER BY rowid DESC LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()
    return {"ok": True, "artifacts": [json.loads(row[0]) for row in rows], "total": total, "limit": limit, "offset": offset}


def get(service, args):
    identity = _text(args, "id", 100)
    with service.bus.connect() as db:
        _tables(db)
        saved = db.execute("SELECT row_json FROM published_outputs WHERE id=?", (identity,)).fetchone()
    if not saved:
        return failure("missing", "That output publication does not exist")
    row = json.loads(saved[0])
    path = _path(service, row["path"])
    if not path.is_file():
        return {"ok": True, "artifact": row, "availability": "missing"}
    digest, _ = _digest(path)
    return {"ok": True, "artifact": row, "availability": "available" if digest == row["sha256"] else "changed", "currentSha256": digest}


def call(service, name, args):
    if not isinstance(args, dict):
        raise ValueError("Output arguments must be an object")
    if name == "app.open":
        from .neyvia_voice import call as navigate
        return navigate(service, name, args)
    if name == "artifact.publish":
        return publish(service, args)
    if name == "artifact.list":
        return listing(service, args)
    if name in {"artifact.get", "artifact.open"}:
        result = get(service, args)
        if name == "artifact.get" or not result["ok"]:
            return result
        if result["availability"] != "available":
            return failure("conflict" if result["availability"] == "changed" else "missing", "The published output has changed" if result["availability"] == "changed" else "The output file is missing")
        from .neyvia_panes import open_artifact
        row = result["artifact"]
        preview = open_artifact(service.bus.root, {"path": row["path"]})
        if not preview.get("ok"):
            return preview
        # A saved .patch is a publication, whereas the existing diff pane reads
        # live git changes from an active chat. Show the published patch bytes.
        kind = "file" if preview["kind"] == "other" else "artifact"
        payload = {"kind": kind, "target": row["path"]}
        from .cl.renderer_effects import show
        return {**show(service, payload), "artifact": row, "preview": preview}
    raise ValueError("Unknown output operation")


def handle_command(backend, command, payload):
    from .neyvia_workspace_tools import workspace_for
    expected = payload.get("_expectedStateRoot")
    if expected and Path(expected).resolve() != backend.root.resolve():
        return failure("conflict", "The output service belongs to a different workspace")
    try:
        return call(workspace_for(backend.root, backend), COMMANDS[command], payload)
    except (ValueError, TypeError, OSError) as exc:
        return failure(getattr(exc, "status", "invalid"), str(exc))
