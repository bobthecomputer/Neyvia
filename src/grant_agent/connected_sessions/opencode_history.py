"""Project OpenCode's saved native parts without losing tools or edit receipts."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from .model import Item
from .transparency import bounded_text, normalize_item, reasoning_data


def latest_model(database: Path, native_id: str) -> str | None:
    """Model identity from this session's own saved assistant metadata."""
    try:
        with closing(sqlite3.connect(f"file:{quote(str(database.resolve()))}?mode=ro", uri=True, timeout=0.5)) as conn:
            for (raw,) in conn.execute('SELECT data FROM message WHERE session_id=? ORDER BY time_created DESC', (native_id,)):
                info = json.loads(raw)
                if info.get("role") == "assistant" and info.get("modelID") and info.get("providerID"):
                    return str(info["providerID"]) + "/" + str(info["modelID"])
    except (sqlite3.Error, OSError, ValueError, TypeError):
        pass
    return None


def tool_output(database: Path, native_id: str, item_id: str) -> str | None:
    """Exact saved native output for either a part id or a streamed ACP call id."""
    suffix = item_id.rsplit("#", 1)[-1] if "#" in item_id else item_id.split(":", 1)[-1]
    try:
        with closing(sqlite3.connect(f"file:{quote(str(database.resolve()))}?mode=ro", uri=True, timeout=0.5)) as conn:
            rows = conn.execute('SELECT p.id,p.data FROM part p JOIN message m ON m.id=p.message_id WHERE m.session_id=? AND (p.id=? OR json_extract(p.data,\'$.callID\')=?)',
                                (native_id, suffix, suffix))
            for _, raw in rows:
                part = json.loads(raw)
                if part.get("type") == "tool":
                    state = part.get("state") or {}
                    return str(state.get("error") or state.get("output") or "")
    except (sqlite3.Error, OSError, ValueError):
        return None
    return None


def read_items(database: Path, native_id: str, session_id: str) -> list[Item] | None:
    """None means an older schema: the caller keeps its legacy message reader."""
    from ..external_chat_inventory import _stamp

    if not database.is_file():
        return None
    items: list[Item] = []

    def add(identity, kind, data, created):
        normalize_item("opencode", kind, data)
        items.append(Item(id=f"{session_id}#{identity}", seq=len(items) + 1,
                          kind=kind, at=_stamp(created) or None, data=data))

    try:
        with closing(sqlite3.connect(f"file:{quote(str(database.resolve()))}?mode=ro", uri=True, timeout=0.5)) as conn:
            for table, required in (("message", {"id", "session_id", "data", "time_created"}),
                                    ("part", {"id", "message_id", "data", "time_created"})):
                if not required <= {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}:
                    return None
            no_reasoning = {row[0] for row in conn.execute('''SELECT m.id FROM message m WHERE m.session_id=?
                AND json_extract(m.data,'$.role')='assistant' AND NOT EXISTS
                (SELECT 1 FROM part p WHERE p.message_id=m.id AND json_extract(p.data,'$.type')='reasoning')''', (native_id,))}
            noticed = set()
            rows = conn.execute('''SELECT p.id, p.data, p.time_created, m.data, m.id FROM part p
                JOIN message m ON m.id=p.message_id WHERE m.session_id=?
                ORDER BY m.time_created, m.id, p.time_created, p.id''', (native_id,))
            for identity, raw, created, message, message_id in rows:
                try:
                    part, metadata = json.loads(raw), json.loads(message)
                except (ValueError, TypeError):
                    continue
                if not isinstance(part, dict) or not isinstance(metadata, dict):
                    continue
                kind, role = part.get("type"), metadata.get("role")
                if message_id in no_reasoning and message_id not in noticed:
                    noticed.add(message_id)
                    add(message_id + ":reasoning-availability", "reasoning", reasoning_data("opencode", None, source="native-parts"), created)
                if kind == "text" and role in {"user", "assistant"}:
                    if str(part.get("text") or "").strip():
                        add(identity, role, {"text": str(part["text"]), "attachments": []}, created)
                elif kind == "reasoning":
                    add(identity, "reasoning", reasoning_data("opencode", str(part.get("text") or ""), source="native-parts"), created)
                elif kind == "tool":
                    state = part.get("state") or {}
                    native_status = state.get("status")
                    name = str(part.get("tool") or "tool")
                    category = {"edit": "edit", "write": "edit", "apply_patch": "edit", "bash": "command",
                                "read": "read", "grep": "search", "glob": "search", "webfetch": "web"}.get(name, "other")
                    inputs = state.get("input") or {}
                    tool_meta = state.get("metadata") or {}
                    path = inputs.get("filePath") if isinstance(inputs, dict) else None
                    args, input_truncated = bounded_text(inputs)
                    output, output_truncated = bounded_text(str(state.get("error") or state.get("output") or ""))
                    command = inputs.get("command") if isinstance(inputs, dict) else None
                    timing = state.get("time") or {}
                    start, end = timing.get("start"), timing.get("end")
                    duration = end - start if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start else None
                    add(identity, "tool", {"name": name, "category": category, "title": state.get("title") or name,
                        "input": bounded_text(command)[0] if isinstance(command, str) else args, "args": args,
                        "command": bounded_text(command)[0] if isinstance(command, str) else None, "inputTruncated": input_truncated,
                        "output": output, "outputTruncated": output_truncated,
                        "exitCode": tool_meta.get("exit", tool_meta.get("exitCode")), "durationMs": duration, "durationSource": "native-parts",
                        "status": {"completed": "ok", "error": "error"}.get(native_status, "running"),
                        "files": [path] if path else []}, created)
                    # A cancelled/failed edit must never become a successful diff.
                    if native_status == "completed":
                        native_diff = tool_meta.get("filediff") or {}
                        patch = native_diff.get("patch") or tool_meta.get("diff")
                        if isinstance(patch, str) and patch:
                            file = {"path": native_diff.get("file") or path}
                            for metric in ("additions", "deletions"):
                                if isinstance(native_diff.get(metric), int):
                                    file[metric] = native_diff[metric]
                            bounded, truncated = bounded_text(patch)
                            add(identity + ":diff", "diff", {"files": [file], "patch": bounded, "truncated": truncated, "source": "native-parts"}, created)
        return items
    except (sqlite3.Error, OSError):
        return None
