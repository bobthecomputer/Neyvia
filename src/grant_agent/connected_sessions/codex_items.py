"""Map Codex app-server records to connected-session shapes.

Everything here is a pure function of app-server JSON (plus a bounded tail of a
rollout file for the "running elsewhere" signal), so it is tested without a
process. Item ids are the Codex item ids; ``seq`` is the turn's ordinal (its
index from the start of the thread) plus the item's position inside the turn.
Threads only grow at the end, so a seq never changes, whether the item was read
in a page or seen live. (Older threads have neither UUIDv7 turn ids nor turn
start times, so ordinals are the only ordering every thread has.)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .model import Capabilities, ContextUsage, Item, SessionSummary
from .plan import replace_steps, plan_op
from .transparency import PAYLOAD_LIMIT, bounded_text, normalize_item, reasoning_data
from .. import proofs_a_sessions as _proofs

TEXT_LIMIT = 48_000  # bytes; an event stays under 64 KB with room for its envelope
OUTPUT_LIMIT = PAYLOAD_LIMIT
INPUT_LIMIT = PAYLOAD_LIMIT
PATCH_LIMIT = PAYLOAD_LIMIT

SEQ_SLOTS = 8192  # per turn: 2048 thread items x 4 sub-slots (main item, diff, ...)
SEQ_MAX_INDEX = 2047

# A turn that has written nothing for this long is treated as abandoned, not running.
ROLLOUT_STALE_SECONDS = 30 * 60
# With no readable turn marker, activity this recent still counts as a running turn.
ROLLOUT_ACTIVE_SECONDS = 120
ROLLOUT_TAIL_STEPS = (256 * 1024, 1024 * 1024, 4 * 1024 * 1024)

_TURN_START_EVENTS = {"task_started", "turn_started"}
_TURN_END_EVENTS = {"task_complete", "turn_complete", "turn_aborted", "task_aborted"}

_HARNESS_MARKERS = ("\\.agent_control\\", "\\proof\\", "evidence", "harness", ".sandbox-scratch")
_TEMP_MARKERS = ("\\temp\\", "\\tmp\\", "\\appdata\\local\\temp\\")
_CONTEXT_WRAPPERS = ("in-app-browser-context", "environment_context", "user_instructions",
                     "system-reminder", "turn_aborted")
_UUID7 = re.compile(r"^([0-9a-f]{8})-([0-9a-f]{4})-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")
_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif"}


# -- small helpers ---------------------------------------------------------

def strip_extended_prefix(path: Any) -> str:
    text = str(path or "")
    if os.name == "nt" and text.startswith("\\\\?\\"):
        return text[4:]
    return text


def iso_from_seconds(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def iso_from_ms(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_clip(args[0], args[1], result))
def clip(text: str, limit: int = TEXT_LIMIT) -> str:
    """Bound ``text`` to ``limit`` bytes of UTF-8 (a character limit would not bound non-Latin text)."""
    if len(text) <= limit and text.isascii():
        return text
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    kept = raw[:limit].decode("utf-8", errors="ignore")
    return kept + f"\n[... {len(text) - len(kept)} more characters omitted]"


def clip_tail(text: str, limit: int = OUTPUT_LIMIT) -> str:
    """Keep the end of long output; that is where a command's result is."""
    if len(text) <= limit:
        return text
    # Include the marker in the shared payload budget: normalization must not
    # clip this tail a second time and discard the command's final result.
    tail_size = max(0, limit - 80)
    marker = f"[... {len(text) - tail_size} earlier characters omitted]\n"
    return (marker + text[-tail_size:]) if tail_size else marker[:limit]


def one_line(text: str, limit: int = INPUT_LIMIT) -> str:
    collapsed = " ⏎ ".join(part.strip() for part in text.replace("\r", "").split("\n") if part.strip())
    return collapsed if len(collapsed) <= limit else collapsed[:limit] + "…"


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_uuid_clock(args[0], result))
def uuid7_ms(value: Any) -> int | None:
    match = _UUID7.match(str(value or "").lower())
    if not match:
        return None
    ms = int(match.group(1) + match.group(2), 16)
    return ms if 1_600_000_000_000 < ms < 4_100_000_000_000 else None


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_seq(args[0], args[1], args[2], result))
def make_seq(ordinal: int, index: int, sub: int = 0) -> int:
    return max(0, ordinal) * SEQ_SLOTS + min(max(index, 0), SEQ_MAX_INDEX) * 4 + sub


@_proofs.checked_result(lambda args, kwargs, result: _proofs.require(result == args[0] // SEQ_SLOTS, "sessions.codex.sequence", "sequence ordinal differs"))
def ordinal_from_seq(seq: int) -> int:
    return seq // SEQ_SLOTS


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_media_token(args[0], result))
def media_token(ref: str) -> str:
    """Same token as ``connected_chat_media.descriptors``."""
    return hashlib.sha256(ref.encode()).hexdigest()


def session_id_for(thread_id: str, device_id: str) -> str:
    return f"external:codex:{device_id}:{quote(str(thread_id), safe='-_.~')}"


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_origin(args[0], result))
def classify_origin(cwd: Any) -> str:
    """"neyvia-harness" for Neyvia's own automation folders, else "user"."""
    path = str(cwd or "").replace("/", "\\").lower().rstrip("\\") + "\\"
    if path == "\\":
        return "user"
    if any(marker in path for marker in _HARNESS_MARKERS):
        return "neyvia-harness"
    # Sessions in temp folders come from test and proof runs, not real projects.
    if any(marker in path for marker in _TEMP_MARKERS):
        return "neyvia-harness"
    return "user"


def relative_path(path: Any, cwd: str | None) -> str:
    text = strip_extended_prefix(path)
    if not text or not cwd:
        return text
    base = strip_extended_prefix(cwd).replace("\\", "/").rstrip("/")
    normal = text.replace("\\", "/")
    if base and normal.lower().startswith(base.lower() + "/"):
        return normal[len(base) + 1:]
    return text


def strip_context_wrappers(text: str) -> str:
    """Drop context blocks the Codex app injects in front of a user's own words."""
    result = text
    while True:
        match = re.match(r"\s*<(" + "|".join(re.escape(tag) for tag in _CONTEXT_WRAPPERS) + r")\b[^>]*>.*?</\1>\s*", result, re.S)
        if not match:
            return result.strip()
        result = result[match.end():]


# -- attachments -----------------------------------------------------------

def attachment(ref: str, kind: str = "image", label: str | None = None) -> dict[str, Any]:
    token = media_token(ref)
    suffix = Path(ref.replace("\\", "/")).suffix.lower()
    data_match = re.match(r"^data:([\w/+.-]+);base64,", ref)
    mime = data_match.group(1) if data_match else _IMAGE_TYPES.get(suffix)
    if label is None:
        label = "Attached image" if data_match else (Path(ref.replace("\\", "/")).name or "Attachment")
    remote = ref if ref.startswith(("http://", "https://")) else None
    return {"id": token, "kind": kind, "label": label, "url": remote, "mime": mime, "mediaRef": token}


def user_content(parts: Any) -> tuple[str, list[dict[str, Any]], list[str]]:
    texts: list[str] = []
    attachments: list[dict[str, Any]] = []
    mentions: list[str] = []
    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "text":
            texts.append(str(part.get("text") or ""))
        elif kind == "image" and isinstance(part.get("url"), str):
            attachments.append(attachment(part["url"]))
        elif kind == "localImage" and isinstance(part.get("path"), str):
            attachments.append(attachment(part["path"]))
        elif kind in ("audio", "localAudio"):
            ref = str(part.get("url") or part.get("path") or "")
            if ref:
                attachments.append(attachment(ref, "file", "Audio"))
        elif kind in ("skill", "mention") and part.get("name"):
            mentions.append(str(part["name"]))
    return strip_context_wrappers("\n".join(texts)), attachments, mentions


def media_refs_of_item(item: dict[str, Any]) -> list[str]:
    """Raw references (data URLs, local paths) in a thread item, for read_media."""
    kind = item.get("type")
    refs: list[str] = []
    if kind == "userMessage":
        for part in item.get("content") or []:
            if isinstance(part, dict):
                value = part.get("url") if part.get("type") == "image" else part.get("path") if part.get("type") == "localImage" else None
                if isinstance(value, str):
                    refs.append(value)
    elif kind == "imageView" and isinstance(item.get("path"), str):
        refs.append(item["path"])
    elif (kind == "imageGeneration" or kind == "extension" and item.get("kind") == "image_gen.generation") and isinstance(item.get("savedPath"), str):
        refs.append(item["savedPath"])
    return refs


# -- diffs -----------------------------------------------------------------

def _count_lines(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _hunk_counts(diff: str) -> tuple[int, int]:
    additions = deletions = 0
    in_hunk = "@@" not in diff
    for line in diff.split("\n"):
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("+") and not line.startswith("+++ "):
            additions += 1
        elif line.startswith("-") and not line.startswith("--- "):
            deletions += 1
    return additions, deletions


def _prefixed(text: str, prefix: str, limit: int) -> str:
    body = text if len(text) <= limit else text[:limit]
    lines = body.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(prefix + line for line in lines)


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_codex_diff(args[0], args[1], args[2], result))
def diff_from_changes(changes: Any, cwd: str | None = None, limit: int = PATCH_LIMIT) -> dict[str, Any]:
    """{"files": [...], "patch": str | None, "truncated": bool} for a fileChange item."""
    files: list[dict[str, Any]] = []
    parts: list[str] = []
    size = 0
    truncated = False
    for change in changes if isinstance(changes, list) else []:
        if not isinstance(change, dict):
            continue
        kind_info = change.get("kind") if isinstance(change.get("kind"), dict) else {}
        kind = str(kind_info.get("type") or "update")
        path = relative_path(change.get("path"), cwd)
        diff = str(change.get("diff") or "")
        if kind == "add":
            additions, deletions = _count_lines(diff), 0
            old, new = "/dev/null", f"b/{path}"
            hunk = f"@@ -0,0 +1,{additions} @@\n" + _prefixed(diff, "+", limit)
        elif kind == "delete":
            additions, deletions = 0, _count_lines(diff)
            old, new = f"a/{path}", "/dev/null"
            hunk = f"@@ -1,{deletions} +0,0 @@\n" + _prefixed(diff, "-", limit)
        else:
            additions, deletions = _hunk_counts(diff)
            old, new = f"a/{path}", f"b/{path}"
            hunk = diff if len(diff) <= limit else diff[:limit]
        entry: dict[str, Any] = {"path": path, "additions": additions, "deletions": deletions, "kind": kind}
        if kind_info.get("move_path"):
            entry["movedTo"] = relative_path(kind_info["move_path"], cwd)
        files.append(entry)
        block = f"diff --git a/{path} b/{path}\n--- {old}\n+++ {new}\n{hunk}\n"
        if size + len(block) > limit:
            truncated = True
            block = block[: max(0, limit - size)]
        if block:
            parts.append(block)
            size += len(block)
        if truncated:
            break
    return {"files": files, "patch": "".join(parts) or None, "truncated": truncated}


# -- thread items -> Items -------------------------------------------------

def _command_title(item: dict[str, Any]) -> str:
    actions = [a for a in item.get("commandActions") or [] if isinstance(a, dict)]
    if actions and all(a.get("type") in ("read", "listFiles", "search") for a in actions):
        first = actions[0]
        if first["type"] == "read":
            return f"Read {first.get('name') or Path(str(first.get('path') or '')).name or 'file'}"
        if first["type"] == "search":
            return f"Searched for {first.get('query')}" if first.get("query") else "Searched files"
        return "Listed files"
    return "Ran command"


def _text_of_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    texts: list[str] = []
    for part in content if isinstance(content, list) else []:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
        elif isinstance(part, str):
            texts.append(part)
    return "\n".join(texts)


def _tool_status(raw: Any, phase: str, *, ok: tuple[str, ...] = ("completed",)) -> str:
    if raw in (None, ""):
        return "running" if phase == "started" else "ok"
    if raw == "inProgress":
        return "running"
    return "ok" if raw in ok else "error"


def _json_line(value: Any, limit: int = INPUT_LIMIT) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_codex_item(kwargs, result))
def map_thread_item(item: dict[str, Any], *, seq: int, at: str | None, cwd: str | None = None,
                    phase: str = "completed") -> list[Item]:
    """One Codex ThreadItem to zero, one or two Items (a file change adds a diff).

    ``phase`` is "started" for a live item that has no result yet, otherwise
    "completed"; it only matters for kinds that carry no status of their own.
    """
    kind = str(item.get("type") or "")
    item_id = str(item.get("id") or "")
    if not item_id:
        return []
    try:
        mapped = _map_thread_item(kind, item, item_id, seq, at, cwd, phase)
        for entry in mapped:
            normalize_item("codex", entry.kind, entry.data)
        return mapped
    except (TypeError, ValueError, KeyError, AttributeError):
        return [Item(item_id, seq, "notice", at, {"text": f"Codex sent an item Neyvia could not read ({kind}).", "level": "info"})]


def _map_thread_item(kind: str, item: dict[str, Any], item_id: str, seq: int, at: str | None,
                     cwd: str | None, phase: str) -> list[Item]:
    if kind == "extension" and item.get("kind") == "image_gen.generation":
        status = _tool_status(item.get("status"), phase)
        receipt = Item(item_id, seq, "tool", at, {
            "name": "image_gen.imagegen", "category": "other", "title": "Image generation",
            "status": status, "input": str(item.get("revisedPrompt") or "")[:500],
            "output": str(item.get("failure") or "")[:500], "files": [], "exitCode": None,
            "durationMs": None, "generationEvent": True})
        saved = str(item.get("savedPath") or "")
        if status == "ok" and saved:
            return [receipt, Item(item_id + ':image', seq + 1, 'assistant', at, {
                'text': 'Generated an image', 'generatedImage': True,
                'attachments': [attachment(saved)]})]
        return [receipt]
    if kind == "userMessage":
        text, attachments, mentions = user_content(item.get("content"))
        if not text and not attachments:
            return []
        data: dict[str, Any] = {"text": clip(text), "attachments": attachments}
        if len(data["text"]) < len(text):
            data["truncated"] = True
        if mentions:
            data["mentions"] = mentions
        if item.get("clientId"):
            data["clientId"] = item["clientId"]
        return [Item(item_id, seq, "user", at, data)]
    if kind == "agentMessage":
        full = str(item.get("text") or "")
        data = {"text": clip(full), "attachments": []}
        if len(data["text"]) < len(full):
            data["truncated"] = True
        if item.get("phase"):
            data["phase"] = item["phase"]
        return [Item(item_id, seq, "assistant", at, data)]
    if kind == "reasoning":
        summary = "\n\n".join(str(part).strip() for part in item.get("summary") or [] if str(part).strip())
        content = "\n\n".join(str(part).strip() for part in item.get("content") or [] if str(part).strip())
        text = "\n\n".join(part for part in (summary, content) if part)
        data = reasoning_data("codex", text, source="app-server", exposure="thinking" if content else "summary", pending=phase == "started")
        if summary and content:
            data.update(reasoningSummary=summary, content=content)
        return [Item(item_id, seq, "reasoning", at, data)]
    if kind == "commandExecution":
        raw_status = item.get("status")
        exit_code = item.get("exitCode") if isinstance(item.get("exitCode"), int) else None
        status = "running" if raw_status == "inProgress" else ("ok" if raw_status == "completed" and exit_code in (None, 0) else "error")
        output = str(item.get("aggregatedOutput") or "")
        actions = [a for a in item.get("commandActions") or [] if isinstance(a, dict)]
        data = {"name": "shell", "category": "command", "title": _command_title(item),
                "input": bounded_text(str(item.get("command") or ""))[0], "command": bounded_text(str(item.get("command") or ""))[0],
                "inputTruncated": len(str(item.get("command") or "")) > INPUT_LIMIT, "status": status,
                "output": clip_tail(output), "outputTruncated": len(output) > OUTPUT_LIMIT,
                "exitCode": exit_code, "cwd": strip_extended_prefix(item.get("cwd")) or None,
                "files": [relative_path(a.get("path"), cwd) for a in actions if a.get("type") == "read" and a.get("path")],
                "durationMs": item.get("durationMs") if isinstance(item.get("durationMs"), int) else None}
        if raw_status == "declined":
            data["declined"] = True
        if item.get("source") == "userShell":
            data["userInitiated"] = True
        return [Item(item_id, seq, "tool", at, data)]
    if kind == "fileChange":
        raw_status = item.get("status")
        diff = diff_from_changes(item.get("changes"), cwd)
        files = diff["files"]
        paths = [entry["path"] for entry in files]
        title = "Editing files" if raw_status == "inProgress" else (f"Edited {paths[0]}" if len(paths) == 1 else f"Edited {len(paths)} files")
        tool = Item(item_id, seq, "tool", at, {
            "name": "apply_patch", "category": "edit", "title": title, "input": one_line(", ".join(paths)),
            "status": _tool_status(raw_status, phase), "output": "", "exitCode": None, "files": paths,
            "durationMs": None, "additions": sum(f["additions"] for f in files), "deletions": sum(f["deletions"] for f in files),
            **({"declined": True} if raw_status == "declined" else {})})
        items = [tool]
        if files and raw_status not in ("declined", "failed"):
            items.append(Item(f"{item_id}:diff", seq + 1, "diff", at, diff))
        return items
    if kind == "mcpToolCall":
        arguments = item.get("arguments")
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        error = item.get("error") if isinstance(item.get("error"), dict) else {}
        output = _text_of_content(result.get("content")) or str(error.get("message") or "")
        title = str(arguments.get("title")) if isinstance(arguments, dict) and isinstance(arguments.get("title"), str) else str(item.get("tool") or "MCP tool")
        mapped = Item(item_id, seq, "tool", at, {
            "name": f"{item.get('server')}.{item.get('tool')}", "category": "mcp", "title": one_line(title, 200),
            "input": bounded_text(arguments)[0], "args": bounded_text(arguments)[0], "inputTruncated": bounded_text(arguments)[1],
            "status": _tool_status(item.get("status"), phase), "output": clip_tail(output), "outputTruncated": len(output) > OUTPUT_LIMIT,
            "result": bounded_text(result or error)[0], "resultTruncated": bounded_text(result or error)[1],
            "exitCode": None, "files": [], "server": item.get("server"), "tool": item.get("tool"),
            "durationMs": item.get("durationMs") if isinstance(item.get("durationMs"), int) else None})
        plan = plan_op(mapped.data["name"], arguments)
        if plan is not None and mapped.data["status"] != "error" and not result.get("isError") and not error:
            mapped.data["plan"] = plan
        return [mapped]
    if kind == "dynamicToolCall":
        success = item.get("success")
        status = "running" if item.get("status") == "inProgress" else ("error" if success is False or item.get("status") == "failed" else "ok")
        return [Item(item_id, seq, "tool", at, {
            "name": str(item.get("tool") or "tool"), "category": "other", "title": str(item.get("tool") or "Tool call"),
            "input": bounded_text(item.get("arguments"))[0], "args": bounded_text(item.get("arguments"))[0],
            "inputTruncated": bounded_text(item.get("arguments"))[1], "status": status,
            "output": clip_tail(_text_of_content(item.get("contentItems"))), "outputTruncated": len(_text_of_content(item.get("contentItems"))) > OUTPUT_LIMIT,
            "result": bounded_text(item.get("contentItems") or [])[0], "resultTruncated": bounded_text(item.get("contentItems") or [])[1], "exitCode": None, "files": [],
            "durationMs": item.get("durationMs") if isinstance(item.get("durationMs"), int) else None})]
    if kind == "webSearch":
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        query = str(item.get("query") or action.get("query") or action.get("url") or "")
        title = f"Opened {action['url']}" if action.get("type") == "openPage" and action.get("url") else f"Searched the web for {query}" if query else "Searched the web"
        return [Item(item_id, seq, "tool", at, {
            "name": "web_search", "category": "web", "title": one_line(title, 200), "input": one_line(query),
            "status": "running" if phase == "started" else "ok", "output": "", "exitCode": None, "files": [], "durationMs": None})]
    if kind == "imageView":
        path = str(item.get("path") or "")
        return [Item(item_id, seq, "tool", at, {
            "name": "view_image", "category": "read", "title": "Viewed image", "input": Path(path.replace("\\", "/")).name,
            "status": "ok", "output": "", "exitCode": None, "files": [strip_extended_prefix(path)], "durationMs": None,
            "attachments": [attachment(path)] if path else []})]
    if kind == "imageGeneration":
        saved = str(item.get("savedPath") or "")
        text = str(item.get("revisedPrompt") or "") or "Generated an image"
        return [Item(item_id, seq, "assistant", at, {
            "text": clip(text), "attachments": [attachment(saved)] if saved else [], "generatedImage": True})]
    if kind == "sleep":
        seconds = round((item.get("durationMs") or 0) / 1000)
        return [Item(item_id, seq, "tool", at, {
            "name": "sleep", "category": "other", "title": f"Waited {seconds}s", "input": "",
            "status": "running" if phase == "started" else "ok", "output": "", "exitCode": None, "files": [],
            "durationMs": item.get("durationMs") if isinstance(item.get("durationMs"), int) else None})]
    if kind == "collabAgentToolCall":
        status = "running" if item.get("status") == "inProgress" else ("error" if item.get("status") == "failed" else "ok")
        tool = str(item.get("tool") or "agent")
        return [Item(item_id, seq, "tool", at, {
            "name": tool, "category": "agent", "title": f"Sub-agent: {tool}", "input": one_line(str(item.get("prompt") or "")),
            "status": status, "output": "", "exitCode": None, "files": [], "durationMs": None,
            "model": item.get("model"), "agentThreadIds": item.get("receiverThreadIds") or []})]
    if kind == "subAgentActivity":
        activity = str(item.get("kind") or "")
        status = {"started": "running", "completed": "ok", "failed": "error",
                  "errored": "error", "interrupted": "interrupted"}.get(activity, "unknown")
        return [Item(item_id, seq, "tool", at, {
            "name": "sub_agent", "category": "agent", "title": f"Sub-agent {item.get('kind') or 'activity'}",
            "input": str(item.get("agentPath") or ""), "status": status, "agentActivity": activity, "output": "", "exitCode": None, "files": [],
            "durationMs": None, "agentThreadIds": [item["agentThreadId"]] if item.get("agentThreadId") else []})]
    if kind == "functionCallOutput":
        return [Item(item_id, seq, "tool", at, {
            "name": str(item.get("name") or "tool"), "category": "other", "title": str(item.get("name") or "Tool output"),
            "input": "", "status": "ok", "output": clip_tail(_text_of_content(item.get("output"))), "outputTruncated": len(_text_of_content(item.get("output"))) > OUTPUT_LIMIT, "exitCode": None,
            "files": [], "durationMs": None})]
    if kind == "plan":
        return [Item(item_id, seq, "notice", at, {"text": clip(str(item.get("text") or "")), "level": "info",
                                                   "subtype": "plan", "title": "Plan"})]
    if kind == "contextCompaction":
        return [Item(item_id, seq, "compaction", at, {"state": "started" if phase == "started" else "completed",
                                                      "beforeTokens": None, "afterTokens": None})]
    if kind in ("enteredReviewMode", "exitedReviewMode"):
        verb = "Entered" if kind == "enteredReviewMode" else "Finished"
        return [Item(item_id, seq, "notice", at, {"text": f"{verb} review mode. {item.get('review') or ''}".strip(), "level": "info"})]
    if kind == "hookPrompt":
        fragments = item.get("fragments") or []
        text, truncated = bounded_text("\n\n".join(str(fragment.get("text") or "") for fragment in fragments if isinstance(fragment, dict)))
        return [Item(item_id, seq, "tool", at, {"name": "hook_context", "category": "other", "title": "Hook context supplied",
            "input": text, "inputTruncated": truncated, "args": bounded_text(fragments)[0], "argsTruncated": bounded_text(fragments)[1],
            "status": "ok", "output": "", "exitCode": None, "durationMs": None, "files": [], "source": "app-server"})]
    return [Item(item_id, seq, "notice", at, {"text": f"Codex sent an item Neyvia does not show yet ({kind or 'unknown'}).", "level": "info"})]


def plan_item(turn_id: str, seq: int, at: str | None, steps: list[dict[str, Any]], explanation: str | None) -> Item:
    marks = {"completed": "[x]", "inProgress": "[~]", "in_progress": "[~]"}
    lines = [f"- {marks.get(str(step.get('status')), '[ ]')} {step.get('step')}" for step in steps]
    text = "\n".join(([explanation] if explanation else []) + lines)
    return Item(f"plan:{turn_id}", seq, "notice", at, {
        "text": clip(text), "level": "info", "subtype": "plan", "title": "Plan",
        "steps": [{"step": str(step.get("step") or ""), "status": str(step.get("status") or "pending")} for step in steps],
        "plan": replace_steps(steps, explanation, source="codex")})


def turn_end_items(turn: dict[str, Any], *, seq: int, at: str | None) -> list[Item]:
    """A marker for a turn that did not complete normally."""
    status = str(turn.get("status") or "")
    turn_id = str(turn.get("id") or "")
    if status == "failed":
        error = turn.get("error") if isinstance(turn.get("error"), dict) else {}
        message = " ".join(str(error.get("message") or "The turn failed.").split())[:600]
        return [Item(f"turn-error:{turn_id}", seq, "notice", at, {"text": message, "level": "error"})]
    if status == "interrupted":
        return [Item(f"turn-interrupted:{turn_id}", seq, "notice", at, {"text": "Turn stopped.", "level": "info"})]
    return []


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_codex_turns(args[0], args[1], result))
def map_turns(turns: list[dict[str, Any]], ordinals: dict[str, int], *, cwd: str | None = None) -> list[Item]:
    """Turns (oldest first) to items; ``ordinals`` maps a turn id to its index from the thread start."""
    result: list[Item] = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        key = ordinals.get(str(turn.get("id")), 0)
        finished = iso_from_seconds(turn.get("completedAt"))
        started = iso_from_seconds(turn.get("startedAt")) or iso_from_ms(uuid7_ms(turn.get("id"))) or finished
        finished = finished or started
        items = [i for i in turn.get("items") or [] if isinstance(i, dict)]
        last_message = max((n for n, i in enumerate(items) if i.get("type") == "agentMessage"), default=-1)
        for index, thread_item in enumerate(items):
            at = finished if index == last_message else started
            result.extend(map_thread_item(thread_item, seq=make_seq(key, index), at=at, cwd=cwd))
        if str(turn.get("status")) == "completed" and not any(i.get("type") == "reasoning" for i in items):
            result.append(Item(f"reasoning-unreported:{turn.get('id')}", make_seq(key, len(items)), "reasoning", finished,
                reasoning_data("codex", None, source="app-server")))
        result.extend(turn_end_items(turn, seq=make_seq(key, len(items) + 1), at=finished))
    return result


# -- sessions --------------------------------------------------------------

def capabilities_for(available: bool, reason: str | None = None, *, archived: bool = False) -> Capabilities:
    if not available:
        return Capabilities(reason=reason or "Codex is not available on this host.")
    if archived:
        return Capabilities(reason="This chat is archived in Codex. Unarchive it there to continue it.")
    return Capabilities(continue_session=True, new_session=True, stop=True, approvals=True, questions=True,
                        images=True, goal=True, compact=True, steer=True, model_choice=True,
                        effort_choice=True, permission_choice=True)


def thread_title(thread: dict[str, Any]) -> str:
    name = " ".join(str(thread.get("name") or "").split())
    if name:
        return name[:160]
    preview = strip_context_wrappers(str(thread.get("preview") or ""))
    first = next((line.strip() for line in preview.split("\n") if line.strip()), "")
    return first[:100] or "Codex conversation"


def project_name(thread: dict[str, Any], projects: list[dict[str, Any]]) -> str | None:
    """Codex project by id, else the project whose folder contains the chat's cwd, else the cwd folder."""
    project_id = thread.get("projectId")
    for project in projects:
        if project_id and project.get("id") == project_id:
            return str(project.get("name") or "") or None
    cwd = strip_extended_prefix(thread.get("cwd")).replace("\\", "/").rstrip("/").lower()
    best: tuple[int, str] | None = None
    for project in projects:
        for root in project.get("roots") or []:
            base = strip_extended_prefix(root.get("path") if isinstance(root, dict) else root).replace("\\", "/").rstrip("/").lower()
            if base and (cwd == base or cwd.startswith(base + "/")) and (best is None or len(base) > best[0]):
                best = (len(base), str(project.get("name") or ""))
    if best and best[1]:
        return best[1]
    return Path(strip_extended_prefix(thread.get("cwd"))).name or None


def status_from_thread(status: Any) -> str:
    kind = str(status.get("type") if isinstance(status, dict) else status or "")
    if kind == "active":
        flags = status.get("activeFlags") if isinstance(status, dict) else []
        if "waitingOnApproval" in (flags or []):
            return "waiting_approval"
        if "waitingOnUserInput" in (flags or []):
            return "waiting_input"
        return "working"
    if kind == "systemError":
        return "failed"
    if kind in ("idle", "notLoaded"):
        return "idle"
    return "unknown"


def summarize_thread(thread: dict[str, Any], *, device: dict[str, str], projects: list[dict[str, Any]],
                     available: bool = True, reason: str | None = None, archived: bool = False,
                     status: str | None = None, live_owner: str | None = None,
                     status_since: str | None = None) -> SessionSummary:
    cwd = strip_extended_prefix(thread.get("cwd")) or None
    git = thread.get("gitInfo") if isinstance(thread.get("gitInfo"), dict) else {}
    return SessionSummary(
        id=session_id_for(str(thread.get("id") or ""), device["deviceId"]), app="codex",
        title=thread_title(thread), updated_at=iso_from_seconds(thread.get("updatedAt")),
        created_at=iso_from_seconds(thread.get("createdAt")), cwd=cwd, project=project_name(thread, projects),
        git_branch=git.get("branch") or None, model=thread.get("model") or None,
        status=status or status_from_thread(thread.get("status")),  # type: ignore[arg-type]
        status_since=status_since, live_owner=live_owner,  # type: ignore[arg-type]
        origin=classify_origin(cwd),  # type: ignore[arg-type]
        background=thread.get("source") == "exec",
        host_device_id=device["deviceId"], host_device_name=device["deviceName"], archived=archived,
        capabilities=capabilities_for(available, reason, archived=archived))


def context_from_usage(usage: dict[str, Any], *, updated_at: str | None,
                       auto_compact_tokens: int | None = None) -> ContextUsage:
    last = usage.get("last") if isinstance(usage.get("last"), dict) else {}
    window = usage.get("modelContextWindow")
    used = last.get("totalTokens")
    return ContextUsage(
        used_tokens=used if isinstance(used, int) and not isinstance(used, bool) and used >= 0 else None,
        window_tokens=window if isinstance(window, int) and not isinstance(window, bool) and window > 0 else None,
        auto_compact_tokens=auto_compact_tokens, source="codex-app-server", updated_at=updated_at)


# -- rollout tail (bounded) ------------------------------------------------

def read_tail_rows(path: Path, max_bytes: int) -> list[dict[str, Any]]:
    """Parsed JSONL rows from the last ``max_bytes`` of a file; never reads more."""
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            stream.seek(max(0, size - max_bytes))
            raw = stream.read(max_bytes)
    except OSError:
        return []
    lines = raw.split(b"\n")
    if size > max_bytes:
        lines = lines[1:]  # the first line is cut mid-way
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    _proofs.check_tail_read(max_bytes, raw, rows, size > max_bytes)
    return rows


def rollout_activity(path: Any, *, now: float | None = None) -> dict[str, Any]:
    """Is a turn open in this rollout right now, judged from persisted state only?

    {"inProgress": bool, "ageSeconds": float | None, "turnId": str | None, "since": iso | None}
    A turn counts as open when its last marker is a start and the file was written
    within ROLLOUT_STALE_SECONDS; a file with no readable marker counts only while
    it is being written (ROLLOUT_ACTIVE_SECONDS).
    """
    result: dict[str, Any] = {"inProgress": False, "ageSeconds": None, "turnId": None, "since": None}
    text = strip_extended_prefix(path)
    if not text:
        _proofs.check_rollout_activity(result, None)
        return result
    file = Path(text)
    try:
        stat = file.stat()
    except OSError:
        _proofs.check_rollout_activity(result, None)
        return result
    age = max(0.0, (now if now is not None else time.time()) - stat.st_mtime)
    result["ageSeconds"] = age
    if age > ROLLOUT_STALE_SECONDS:
        _proofs.check_rollout_activity(result, age)
        return result
    for step in ROLLOUT_TAIL_STEPS:
        rows = read_tail_rows(file, step)
        for row in reversed(rows):
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            marker = payload.get("type")
            if row.get("type") == "event_msg" and marker in _TURN_START_EVENTS | _TURN_END_EVENTS:
                result["inProgress"] = marker in _TURN_START_EVENTS
                if result["inProgress"]:
                    result["turnId"] = payload.get("turn_id")
                    result["since"] = iso_from_seconds(payload.get("started_at")) or row.get("timestamp")
                _proofs.check_rollout_activity(result, age, marker=marker, payload=payload, timestamp=row.get("timestamp"))
                return result
        if stat.st_size <= step:
            break
    result["inProgress"] = age <= ROLLOUT_ACTIVE_SECONDS
    _proofs.check_rollout_activity(result, age)
    return result


def context_from_rollout(path: Any) -> ContextUsage | None:
    """Latest reported token count in a bounded rollout tail, as the app wrote it."""
    text = strip_extended_prefix(path)
    if not text:
        return None
    from ..connected_chat_context import context_from_events
    rows = read_tail_rows(Path(text), 1024 * 1024)
    context = context_from_events("codex", rows)
    if context.get("usedTokens") is None and context.get("windowTokens") is None:
        return None
    return ContextUsage(used_tokens=context.get("usedTokens"), window_tokens=context.get("windowTokens"),
                        source="codex-rollout", updated_at=context.get("updatedAt"))


def plan_from_rollout(path: Any, max_bytes: int = 1024 * 1024) -> dict[str, Any] | None:
    """The latest ``update_plan`` call in a bounded rollout tail, as a plan (its own arguments, never output text)."""
    text = strip_extended_prefix(path)
    if not text:
        return None
    from .plan import apply_op
    for row in reversed(read_tail_rows(Path(text), max_bytes)):
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if row.get("type") != "response_item" or payload.get("type") != "function_call" or payload.get("name") != "update_plan":
            continue
        try:
            args = json.loads(payload.get("arguments") or "{}")
        except ValueError:
            return None
        steps = args.get("plan") if isinstance(args, dict) else None
        if not isinstance(steps, list):
            return None
        return apply_op(None, replace_steps(steps, args.get("explanation"), source="codex"), at=row.get("timestamp"))
    return None


def rate_limits_from_rollout(path: Any, max_bytes: int = 256 * 1024) -> dict[str, Any] | None:
    """The latest ``rate_limits`` Codex wrote with a token count: its plan windows, as the app reported them."""
    text = strip_extended_prefix(path)
    if not text:
        return None
    for row in reversed(read_tail_rows(Path(text), max_bytes)):
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        limits = payload.get("rate_limits")
        if row.get("type") == "event_msg" and isinstance(limits, dict):
            return {**limits, "_at": row.get("timestamp")}
    return None


# -- permissions -----------------------------------------------------------

PERMISSION_MODES: dict[str, dict[str, Any]] = {
    "ask": {
        "label": "Ask for approval",
        "description": "Codex reads freely and asks before it edits files, runs commands or uses the network.",
        "approvalPolicy": "on-request", "sandbox": "read-only",
        "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
    },
    "auto": {
        "label": "Auto in workspace",
        "description": "Codex edits and runs commands inside the workspace, and asks before going outside it.",
        "approvalPolicy": "on-request", "sandbox": "workspace-write",
        "sandboxPolicy": {"type": "workspaceWrite", "writableRoots": [], "networkAccess": False,
                          "excludeTmpdirEnvVar": False, "excludeSlashTmp": False},
    },
    "full": {
        "label": "Full access",
        "description": "Codex runs without a sandbox and without asking. Use only for work you trust.",
        "approvalPolicy": "never", "sandbox": "danger-full-access",
        "sandboxPolicy": {"type": "dangerFullAccess"},
    },
}


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_permission(kwargs, result, "catalogue"))
def permission_modes() -> list[dict[str, str]]:
    return [{"id": key, "label": mode["label"], "description": mode["description"]} for key, mode in PERMISSION_MODES.items()]


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_permission(kwargs, result, "match"))
def permission_mode_for(approval_policy: Any, sandbox_mode: Any) -> str | None:
    for key, mode in PERMISSION_MODES.items():
        if mode["approvalPolicy"] == approval_policy and mode["sandbox"] == sandbox_mode:
            return key
    return None


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_permission(kwargs, result, "turn"))
def turn_permission_params(mode_id: str | None) -> dict[str, Any]:
    mode = PERMISSION_MODES.get(str(mode_id or ""))
    return {"approvalPolicy": mode["approvalPolicy"], "sandboxPolicy": dict(mode["sandboxPolicy"])} if mode else {}


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_permission(kwargs, result, "thread"))
def thread_permission_params(mode_id: str | None) -> dict[str, Any]:
    mode = PERMISSION_MODES.get(str(mode_id or ""))
    return {"approvalPolicy": mode["approvalPolicy"], "sandbox": mode["sandbox"]} if mode else {}


# -- server requests -------------------------------------------------------

APPROVAL_METHODS = {"item/commandExecution/requestApproval", "item/fileChange/requestApproval",
                    "item/permissions/requestApproval"}
INPUT_METHODS = {"item/tool/requestUserInput", "mcpServer/elicitation/request"}
REQUEST_METHODS = APPROVAL_METHODS | INPUT_METHODS


def _elicitation_questions(params: dict[str, Any]) -> list[dict[str, Any]]:
    schema = params.get("requestedSchema") if isinstance(params.get("requestedSchema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = set(schema.get("required") or [])
    questions = []
    for key, spec in list(properties.items())[:20]:
        spec = spec if isinstance(spec, dict) else {}
        choices = spec.get("enum") if isinstance(spec.get("enum"), list) else [
            entry.get("const") for entry in spec.get("oneOf") or [] if isinstance(entry, dict) and "const" in entry]
        if spec.get("type") == "boolean":
            choices = ["true", "false"]
        questions.append({
            "id": str(key), "header": str(spec.get("title") or key)[:200],
            "question": str(spec.get("description") or params.get("message") or key)[:2000],
            "options": [{"label": str(choice)[:300], "description": ""} for choice in choices or []],
            "isSecret": False, "isOther": not choices, "required": key in required, "type": spec.get("type"),
        })
    return questions


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_public_request(kwargs, result))
def public_request(method: str, params: dict[str, Any], request_id: str) -> dict[str, Any]:
    """RunRecord.pendingRequest for a server request: {requestId, kind, ...Item.data}."""
    from ..connected_app_chats import ConnectedAppChats
    base = ConnectedAppChats._public_request(method, params)
    pending: dict[str, Any] = {"requestId": request_id, "method": method, "title": base["title"], "detail": base["detail"]}
    if method in APPROVAL_METHODS:
        pending["kind"] = "approval"
        pending["command"] = base.get("command")
        pending["cwd"] = base.get("cwd")
        choices = [choice for choice in base.get("choices") or ["approve", "deny"] if choice in ("approve", "deny")]
        pending["choices"] = (choices or ["deny"]) + ["cancel"]
        pending["decision"] = None
        if method == "item/permissions/requestApproval":
            pending["permissions"] = base.get("permissions") or {}
        return pending
    pending["kind"] = "question"
    if method == "item/tool/requestUserInput":
        questions = base.get("questions") or []
        by_id = {str(q.get("id")): q for q in params.get("questions") or [] if isinstance(q, dict)}
        for question in questions:
            question["isOther"] = bool(by_id.get(question.get("id"), {}).get("isOther"))
    else:
        mode = str(params.get("mode") or "")
        if mode == "url":
            pending["kind"] = "approval"
            pending["url"] = str(params.get("url") or "")[:2000]
            pending["command"] = None
            pending["cwd"] = None
            pending["choices"] = ["approve", "cancel"]
            pending["decision"] = None
            pending["detail"] = f"{str(params.get('message') or 'Finish this step in your browser.')[:1000]}"
            return pending
        questions = _elicitation_questions(params)
        pending["server"] = str(params.get("serverName") or "")[:200]
    pending["questions"] = questions
    pending["answers"] = {}
    return _fit_event(pending)


def _fit_event(pending: dict[str, Any], limit: int = 48_000) -> dict[str, Any]:
    """Shrink free text in a pending request so the event that carries it stays under 64 KB."""
    # (detail/command chars, header/question chars, options kept, label chars, description chars, questions kept)
    for detail, text, options, label, description, questions in ((1000, 500, 20, 100, 200, 20), (400, 200, 10, 60, 100, 12),
                                                                  (200, 100, 6, 40, 60, 6)):
        if len(json.dumps(pending, default=str)) <= limit:
            break
        for key in ("detail", "command"):
            if isinstance(pending.get(key), str):
                pending[key] = pending[key][:detail]
        pending["questions"] = pending.get("questions", [])[:questions]
        for question in pending["questions"]:
            for key in ("header", "question"):
                question[key] = str(question.get(key) or "")[:text]
            question["options"] = [{"label": str(o.get("label") or "")[:label], "description": str(o.get("description") or "")[:description]}
                                   for o in (question.get("options") or [])[:options]]
    return pending


def _coerce_answer(value: str, kind: Any) -> Any:
    if kind == "boolean":
        return value.strip().lower() in ("true", "yes", "1", "on")
    if kind in ("number", "integer"):
        try:
            number = float(value)
        except ValueError:
            return value
        return int(number) if kind == "integer" or number.is_integer() else number
    return value


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_request_wire(kwargs, result))
def server_request_result(method: str, params: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """The exact wire result for a server request, from {"decision", "answers"}.

    Approvals are scoped to the single action; no session-wide rule is ever created.
    """
    decision = str(response.get("decision") or "deny")
    answers = response.get("answers") if isinstance(response.get("answers"), dict) else {}
    if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
        return {"decision": {"approve": "accept", "deny": "decline", "cancel": "cancel"}.get(decision, "decline")}
    if method == "item/permissions/requestApproval":
        granted: dict[str, Any] = {}
        if decision == "approve" and isinstance(params.get("permissions"), dict):
            granted = {key: value for key, value in params["permissions"].items() if value is not None}
        return {"permissions": granted, "scope": "turn"}
    if method == "item/tool/requestUserInput":
        mapped: dict[str, dict[str, list[str]]] = {}
        for question in params.get("questions") or []:
            if not isinstance(question, dict) or not question.get("id"):
                continue
            key = str(question["id"])
            value = str(answers.get(key, ""))[:20_000] if decision == "approve" else ""
            mapped[key] = {"answers": [value] if value else []}
        return {"answers": mapped}
    if method == "mcpServer/elicitation/request":
        if decision != "approve":
            return {"action": "cancel" if decision == "cancel" else "decline", "content": None, "_meta": None}
        if str(params.get("mode") or "") == "url":
            return {"action": "accept", "content": None, "_meta": None}
        kinds = {q["id"]: q.get("type") for q in _elicitation_questions(params)}
        content = {str(key): _coerce_answer(str(value), kinds.get(str(key))) for key, value in answers.items()}
        return {"action": "accept", "content": content, "_meta": None}
    return {}
