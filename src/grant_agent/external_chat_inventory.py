"""Read-only inventory of local Codex, Claude Code, and OpenCode chats.

This module never imports chats into Neyvia and never writes to the source
applications' stores. IDs are namespaced by app and machine so they cannot be
confused with Neyvia conversation IDs or chats from another device.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

MAX_FILE_BYTES = 32 * 1024 * 1024
PREVIEW_FILE_BYTES = 256 * 1024
_INVENTORY_CACHE: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}
_CACHE_LOCK = threading.RLock()
MAX_PREVIEW_CHARS = 600


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home())).expanduser()


def _host() -> dict[str, str]:
    name = socket.gethostname().strip() or "This device"
    identity = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:12]
    return {"deviceId": identity, "deviceName": name, "kind": "local"}


def _paths(root: str | Path | None) -> dict[str, Path]:
    home = Path(root).expanduser() if root else _home()
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex").expanduser()
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude").expanduser()
    opencode_home = Path(os.environ.get("OPENCODE_DATA_DIR") or home / ".local" / "share" / "opencode").expanduser()
    # OpenCode follows platformdirs on Windows. Honor the normal APPDATA data
    # location as well as the XDG location used by Linux/WSL installations.
    if root is None and not os.environ.get("OPENCODE_DATA_DIR") and os.name == "nt":
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "opencode"
        if (roaming / "opencode.db").is_file():
            opencode_home = roaming
    return {"codex": codex_home / "sessions", "claude-code": claude_home / "projects", "opencode": opencode_home / "opencode.db"}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (_text(item) for item in value)))
    if isinstance(value, dict):
        if value.get("type") in {"tool_use", "tool_result", "thinking", "redacted_thinking"}:
            return ""
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("content"), (str, list)):
            return _text(value["content"])
        return ""
    return ""


def _stamp(value: Any) -> str:
    if isinstance(value, (int, float)):
        try:
            if value > 10_000_000_000:
                value /= 1000
            return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return ""
    if isinstance(value, str):
        if value.isdigit():
            return _stamp(int(value))
        return value
    if isinstance(value, dict):
        return _stamp(value.get("timestamp") or value.get("created_at") or value.get("createdAt"))
    return ""


def _read_jsonl(path: Path, *, tail: bool = False, max_bytes: int = MAX_FILE_BYTES) -> list[dict[str, Any]]:
    try:
        if path.stat().st_size > max_bytes:
            with path.open("rb") as stream:
                stream.seek(-max_bytes, os.SEEK_END)
                raw = stream.read()
            if tail:
                raw = raw.split(b"\n", 1)[-1]
            else:
                raw = raw[:MAX_FILE_BYTES].rsplit(b"\n", 1)[0]
        else:
            raw = path.read_bytes()
        rows = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except json.JSONDecodeError:
                continue
        return rows
    except (OSError, PermissionError):
        return []


def _codex_messages(path: Path, *, preview: bool = False) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for row in _read_jsonl(path, tail=True, max_bytes=PREVIEW_FILE_BYTES if preview else MAX_FILE_BYTES):
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
        msg = payload.get("message") if isinstance(payload.get("message"), dict) else payload
        role = str(msg.get("role") or payload.get("role") or "").lower()
        if role not in {"user", "assistant"}:
            continue
        channel = str(payload.get("channel") or msg.get("channel") or "").lower()
        if role == "assistant" and channel and channel not in {"final", "commentary", "complete"}:
            continue
        content = msg.get("content") or msg.get("text") or payload.get("text")
        text = _text(content).strip()
        from .connected_chat_media import media_refs
        refs = media_refs(content, text) if not preview else []
        if text or refs:
            messages.append({"role": role, "text": text, "_mediaRefs": refs, "timestamp": _stamp(row.get("timestamp") or payload.get("timestamp"))})
    return messages


def _codex_db_rows(base: Path, host: dict[str, str]) -> list[dict[str, Any]]:
    """Use Codex's local state DB as its session index, without opening write mode."""
    codex_home = base.parent
    candidates = sorted(codex_home.glob("state*.sqlite"), key=lambda item: item.stat().st_mtime, reverse=True)
    for db in candidates:
        try:
            conn = sqlite3.connect(f"file:{quote(str(db.resolve()))}?mode=ro", uri=True, timeout=0.3)
            cols = {row[1] for row in conn.execute('PRAGMA table_info("threads")')}
            if not {"id", "rollout_path"} <= cols:
                conn.close()
                continue
            selected = [name for name in ("id", "rollout_path", "name", "title", "first_user_message", "updated_at", "updated_at_ms", "cwd", "has_user_event") if name in cols]
            statement = ",".join('"' + name + '"' for name in selected)
            sort = '"updated_at_ms" DESC' if "updated_at_ms" in cols else '"updated_at" DESC' if "updated_at" in cols else '"id" DESC'
            rows = conn.execute(f'SELECT {statement} FROM "threads" ORDER BY {sort} LIMIT 5000').fetchall()
            conn.close()
            result = []
            index_names = _codex_index_names(codex_home / "session_index.jsonl")
            mapping = {name: idx for idx, name in enumerate(selected)}
            for values in rows:
                record = dict(zip(selected, values))
                path_text = str(record.get("rollout_path") or "")
                if os.name == "nt" and path_text.startswith("\\\\?\\"):
                    path_text = path_text[4:]
                rollout = Path(path_text)
                if not rollout.is_absolute():
                    rollout = codex_home / rollout
                try:
                    resolved = rollout.resolve()
                    resolved.relative_to(base.resolve())
                    if not resolved.is_file():
                        continue
                except (OSError, ValueError):
                    continue
                # Recent Codex desktop builds leave has_user_event=0 even for
                # populated chats. Use actual named/user metadata instead.
                if not any(record.get(key) for key in ("name", "title", "first_user_message")):
                    continue
                sid = str(record.get("id") or "")
                if not sid:
                    sid = _codex_rollout_id(resolved.name)
                if not sid:
                    continue
                title = str(record.get("name") or index_names.get(sid) or record.get("title") or record.get("first_user_message") or "Codex conversation")
                cwd = str(record.get("cwd") or "")
                project = Path(cwd).name if cwd else ""
                row = _row("codex", sid, title, resolved, host, record.get("updated_at_ms") or record.get("updated_at"), project)
                result.append(row)
            return result
        except (sqlite3.Error, OSError, PermissionError):
            continue
    return []


def _codex_index_names(path: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in _read_jsonl(path, max_bytes=4 * 1024 * 1024):
        sid, name = str(row.get("id") or ""), str(row.get("thread_name") or "").strip()
        if sid and name:
            names[sid] = name[:160]
    return names


def _codex_rollout_id(filename: str) -> str:
    match = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.jsonl$", filename)
    return match.group(1) if match else ""


_CLAUDE_INTERNAL_MARKERS = ("<task-notification", "<system-reminder", "<command-name>", "<local-command", "<antml:")


def _claude_messages(path: Path, *, preview: bool = False, tail: bool = True) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for row in _read_jsonl(path, tail=tail, max_bytes=PREVIEW_FILE_BYTES if preview else MAX_FILE_BYTES):
        if row.get("isSidechain") is True or row.get("isMeta") is True or row.get("isVisibleInTranscript") is False:
            continue
        msg = row.get("message") if isinstance(row.get("message"), dict) else row
        role = str(msg.get("role") or row.get("type") or "").lower()
        if role not in {"user", "assistant"}:
            continue
        text = _text(msg.get("content") or row.get("content") or msg.get("text")).strip()
        from .connected_chat_media import media_refs
        refs = media_refs(msg.get("content"), text) if not preview else []
        if (text or refs) and not text.lstrip().lower().startswith(_CLAUDE_INTERNAL_MARKERS):
            messages.append({"role": role, "text": text, "_mediaRefs": refs, "timestamp": _stamp(row.get("timestamp") or msg.get("timestamp"))})
    return messages


def _claude_index_titles(projects: Path) -> dict[tuple[str, str], str]:
    titles: dict[tuple[str, str], str] = {}
    if not projects.is_dir():
        return titles
    for project in projects.iterdir():
        if not project.is_dir():
            continue
        for name in ("sessions-index.json", "sessions-index.jsonl", "session_index.json"):
            index = project / name
            if not index.is_file():
                continue
            try:
                if index.stat().st_size > 4 * 1024 * 1024:
                    continue
                content = index.read_text(encoding="utf-8", errors="replace")
                try:
                    value = json.loads(content)
                    entries = value.get("entries", []) if isinstance(value, dict) else value
                    if isinstance(entries, dict):
                        entries = list(entries.values())
                except json.JSONDecodeError:
                    entries = []
                    for line in content.splitlines():
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                for entry in entries if isinstance(entries, list) else []:
                    if not isinstance(entry, dict):
                        continue
                    sid = str(entry.get("sessionId") or entry.get("session_id") or entry.get("id") or "")
                    title = str(entry.get("customTitle") or entry.get("summary") or entry.get("firstPrompt") or entry.get("first_prompt") or "").strip()
                    if sid and title:
                        titles[(project.name, sid)] = " ".join(title.split())[:160]
            except OSError:
                continue
            break
    return titles


def _row(app: str, session_id: str, title: str, path: Path, host: dict[str, str], updated: Any = None, project: str = "") -> dict[str, Any]:
    sid = quote(str(session_id), safe="-_.~")
    return {
        "id": f"external:{app}:{host['deviceId']}:{sid}",
        "title": (" ".join(str(title or "").split()) or "Untitled conversation")[:160],
        "app": app,
        "appLabel": {"codex": "Codex", "claude-code": "Claude Code", "opencode": "OpenCode"}[app],
        "deviceId": host["deviceId"], "deviceName": host["deviceName"],
        "updatedAt": _stamp(updated) or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
        "project": str(project or ""),
        "_sourcePath": str(path), "_sessionId": str(session_id),
    }


def _opencode_rows(db: Path, host: dict[str, str]) -> list[dict[str, Any]]:
    if not db.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{quote(str(db.resolve()))}?mode=ro", uri=True, timeout=0.5)
        conn.row_factory = sqlite3.Row
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "session" not in tables:
            conn.close()
            return []
        cols = {row[1] for row in conn.execute('PRAGMA table_info("session")')}
        required = {"id"}
        if not required <= cols:
            conn.close()
            return []
        select = [name for name in ("id", "title", "directory", "time_created", "time_updated") if name in cols]
        quoted = ",".join('"' + c + '"' for c in select)
        output = []
        for row in conn.execute(f'SELECT {quoted} FROM "session" ORDER BY ' + ('"time_updated" DESC' if "time_updated" in cols else '"id" DESC') + " LIMIT 1000"):
            values = dict(row)
            sid = str(values.get("id") or "")
            if not sid:
                continue
            updated = values.get("time_updated") or values.get("time_created")
            output.append(_row("opencode", sid, values.get("title") or "", db, host, updated, values.get("directory") or ""))
        conn.close()
        return output
    except (sqlite3.Error, OSError, PermissionError):
        return []


def _discover(app: str, locations: dict[str, Path], host: dict[str, str]) -> list[dict[str, Any]]:
    base = locations[app]
    cache_key = (str(base.resolve()), app)
    with _CACHE_LOCK:
        cached = _INVENTORY_CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < 10:
            return [dict(row) for row in cached[1]]
    result: list[dict[str, Any]] = []
    if app == "opencode":
        result = _opencode_rows(base, host)
        with _CACHE_LOCK:
            _INVENTORY_CACHE[cache_key] = (time.monotonic(), result)
        return [dict(row) for row in result]
    if not base.is_dir():
        return result
    if app == "codex":
        result = _codex_db_rows(base, host)
        if result:
            with _CACHE_LOCK:
                _INVENTORY_CACHE[cache_key] = (time.monotonic(), result)
            return [dict(row) for row in result]
    try:
        claude_titles = _claude_index_titles(base) if app == "claude-code" else {}
        files = base.rglob("*.jsonl")
        inspected = 0
        for path in files:
            try:
                inspected += 1
                if inspected > 5000:
                    break
                if not path.is_file() or path.stat().st_size == 0:
                    continue
                # Codex stores YYYY/MM/DD/<session-id>.jsonl. Claude Code uses
                # one <session-id>.jsonl per project under ~/.claude/projects.
                if app == "codex":
                    sid = _codex_rollout_id(path.name)
                    if not sid:
                        continue
                    msgs = _codex_messages(path, preview=True)
                    project = ""
                else:
                    sid = path.stem
                    if "subagents" in path.parts or path.stem.startswith(("agent-", "agent_")):
                        continue
                    msgs = _claude_messages(path, preview=True, tail=False)
                    project = path.parent.name
                if not msgs:
                    continue
                title = next((m["text"] for m in msgs if m["role"] == "user"), "")
                if app == "claude-code":
                    title = claude_titles.get((path.parent.name, sid), title)
                # The title may come from the bounded head; recency must still
                # follow the actual transcript, not its first few messages.
                result.append(_row(app, sid, title, path, host, None, project))
            except OSError:
                continue
    except OSError:
        pass
    with _CACHE_LOCK:
        _INVENTORY_CACHE[cache_key] = (time.monotonic(), result)
    return [dict(row) for row in result]


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def list_external_chats(root: str | Path | None = None, query: str = "", app: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """Enumerate local external chat metadata without modifying native stores."""
    host, locations = _host(), _paths(root)
    selected = str(app or "").strip().lower()
    aliases = {"claude": "claude-code", "claude_code": "claude-code", "open-code": "opencode"}
    selected = aliases.get(selected, selected)
    apps = (selected,) if selected in locations else tuple(locations) if not selected else ()
    statuses = []
    rows: list[dict[str, Any]] = []
    for source in apps:
        found = _discover(source, locations, host)
        available = locations[source].exists()
        statuses.append({"app": source, "appLabel": {"codex": "Codex", "claude-code": "Claude Code", "opencode": "OpenCode"}[source], "available": available, "chatCount": len(found), "error": ""})
        rows.extend(found)
    needle = " ".join(str(query or "").casefold().split())
    if needle:
        rows = [row for row in rows if needle in " ".join(str(row.get(key) or "") for key in ("title", "project", "appLabel")).casefold()]
    rows.sort(key=lambda row: row.get("updatedAt", ""), reverse=True)
    bounded = max(1, min(int(limit or 100), 500))
    start = max(0, int(offset or 0))
    end = start + bounded
    return {"chats": [_public(row) for row in rows[start:end]], "sources": statuses, "host": host,
            "total": len(rows), "nextOffset": end if end < len(rows) else None}


def resolve_external_chat(identity: str, root: str | Path | None = None) -> dict[str, Any]:
    """Resolve a discovered source identity, never a caller-supplied file path."""
    parts = str(identity or "").split(":", 3)
    if len(parts) != 4 or parts[0] != "external":
        raise ValueError("Invalid external chat ID")
    _, app, device_id, encoded_session = parts
    if app not in {"codex", "claude-code", "opencode"}:
        raise ValueError("Unsupported external chat source")
    host = _host()
    if device_id != host["deviceId"]:
        raise ValueError("This chat belongs to another device")
    # The path is resolved by discovery, never supplied by the caller.
    from urllib.parse import unquote
    session_id = unquote(encoded_session)
    paths = _paths(root)
    source_row = next((item for item in _discover(app, paths, host) if item["id"] == identity), None)
    if source_row is None:
        raise FileNotFoundError("External chat is unavailable on this device")
    return {**source_row, "_sessionId": session_id}


def read_external_chat(identity: str, root: str | Path | None = None, max_messages: int = 300, max_chars: int = 180_000) -> dict[str, Any]:
    """Read one namespaced source transcript; returns a bounded, read-only view."""
    source_row = resolve_external_chat(identity, root)
    app, session_id, paths = source_row["app"], source_row["_sessionId"], _paths(root)
    row = _public(source_row)
    source_truncated = False
    if app == "opencode":
        messages = _opencode_messages(paths[app], session_id)
    else:
        path = Path(source_row["_sourcePath"])
        source_truncated = path.stat().st_size > MAX_FILE_BYTES
        messages = _codex_messages(path) if app == "codex" else _claude_messages(path)
    count_cap, char_cap = max(1, min(max_messages, 1000)), max(1000, min(max_chars, 500_000))
    truncated = source_truncated or len(messages) > count_cap
    messages = messages[-count_cap:]
    out: list[dict[str, str]] = []
    chars = 0
    for message in reversed(messages):
        text = message["text"]
        if chars + len(text) > char_cap:
            room = max(0, char_cap - chars)
            if room:
                out.append({**message, "text": text[-room:]})
            truncated = True
            break
        out.append(message)
        chars += len(text)
    out.reverse()
    from .connected_chat_media import descriptors
    for message in out:
        message["attachments"] = descriptors(identity, message.pop("_mediaRefs", []))
    from .connected_chat_context import context_from_events
    context = context_from_events(app, _read_jsonl(Path(source_row["_sourcePath"]), tail=True, max_bytes=2 * 1024 * 1024)) if app != "opencode" else context_from_events(app, [])
    return {"chat": row, "messages": out, "truncated": truncated, "context": context}


def _opencode_messages(db: Path, session_id: str) -> list[dict[str, str]]:
    if not db.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{quote(str(db.resolve()))}?mode=ro", uri=True, timeout=0.5)
        conn.row_factory = sqlite3.Row
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        output: list[dict[str, str]] = []
        if "message" in tables:
            cols = {row[1] for row in conn.execute('PRAGMA table_info("message")')}
            if {"session_id", "data"} <= cols:
                msg_id_expr = '"id"' if "id" in cols else "rowid"
                sort_col = '"time_created"' if "time_created" in cols else msg_id_expr
                for row in conn.execute(f'SELECT {msg_id_expr} AS msg_id, "data", {sort_col} AS created FROM "message" WHERE "session_id"=? ORDER BY created', (session_id,)):
                    # OpenCode stores message metadata and text parts in
                    # separate tables. Read both, preserving message order.
                    data = json.loads(row[1]) if isinstance(row[1], str) else {}
                    role = str(data.get("role") or "").lower()
                    text = _text(data.get("content") or data.get("text"))
                    if "part" in tables:
                        part_cols = {item[1] for item in conn.execute('PRAGMA table_info("part")')}
                        if {"message_id", "data"} <= part_cols:
                            p_sort = '"time_created"' if "time_created" in part_cols else '"id"' if "id" in part_cols else "rowid"
                            if not row[0]:
                                continue
                            part_rows = conn.execute(f'SELECT "data" FROM "part" WHERE "message_id"=? ORDER BY {p_sort}', (row[0],))
                            parts = []
                            for part_row in part_rows:
                                try:
                                    part = json.loads(part_row[0]) if isinstance(part_row[0], str) else {}
                                except json.JSONDecodeError:
                                    continue
                                if isinstance(part, dict) and part.get("type") == "text":
                                    parts.append(str(part.get("text") or ""))
                            if parts:
                                text = "\n".join(parts)
                    if role in {"user", "assistant"} and text.strip():
                        output.append({"role": role, "text": text.strip(), "timestamp": _stamp(data.get("time") or data.get("createdAt") or row[2])})
        conn.close()
        return output
    except (sqlite3.Error, OSError, PermissionError):
        return []


if __name__ == "__main__":  # small JSON bridge for isolated fixture checks
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("list", "read"))
    parser.add_argument("--root", default="")
    parser.add_argument("--id", default="")
    parser.add_argument("--app", default="")
    parser.add_argument("--query", default="")
    args = parser.parse_args()
    result = list_external_chats(root=args.root or None, app=args.app, query=args.query) if args.action == "list" else read_external_chat(args.id, root=args.root or None)
    print(json.dumps(result, ensure_ascii=False))
