"""Incremental, tail-first reader for Claude Code session transcripts (``~/.claude/projects``).

Files range from a few KB to tens of MB and are appended to while a session runs, so
nothing here re-parses a whole file on every call:

* ``SummaryIndex`` keeps a byte offset per file and only parses appended bytes. Its first
  look at a big file reads the head (first prompt, creation time), the tail (latest cwd,
  branch, model, usage) and, only when no title is in the tail, a backward search.
* ``ItemStore`` maps records to chronological items. The first read parses the newest
  window of bytes; older windows load on demand (``before_seq``); appended bytes are mapped
  as they arrive. Item ``seq`` is derived from the byte offset of the source record, so it
  is stable whichever window is parsed first.
"""
from __future__ import annotations

import base64
import binascii
import copy
import json
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterator

from ..connected_chat_media import MAX_MEDIA_BYTES, TYPES
from ..external_chat_inventory import _home
from .claude_items import (
    QUESTION_TOOL, answers_by_id, apply_tool_result, attachment_dict, bound_output, bound_text, classify_user_text,
    collapse, context_used, flatten_result_content, helper_reports, image_token, int_or_none, parse_time, question_data, ref_token,
    task_notification, text_media_refs, tool_category, tool_data, tool_title, valid_session_id,
)
from .plan import latest_plan
from .claude_plan_history import apply_plan_result, read_plan_history
from .model import Item
from .transparency import normalize_item, reasoning_data
from ..proofs_a_providers import checked

NEWLINE = b"\n"
SEQ_SHIFT = 6  # seq = (byte offset of the source line << 6) | block index
INITIAL_WINDOW = 1024 * 1024
EARLIER_WINDOW = 1024 * 1024
MAX_ITEMS_IN_MEMORY = 4000
MAX_STORES = 8
SPLIT_SEQ_BLOCKS = 63


# --------------------------------------------------------------------------- paths


def config_dir() -> Path:
    """Claude's config dir: ``CLAUDE_CONFIG_DIR`` when set (as ``external_chat_inventory`` does), else ``~/.claude``."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override).expanduser() if override else _home() / ".claude"


def iter_session_files(projects: Path) -> Iterator[Path]:
    """Top-level ``<project>/<sessionId>.jsonl`` files; sub-agent transcripts live deeper and are not sessions."""
    try:
        projects_iter = list(os.scandir(projects))
    except OSError:
        return
    for project in projects_iter:
        if not project.is_dir(follow_symlinks=False):
            continue
        try:
            entries = list(os.scandir(project.path))
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if name.endswith(".jsonl") and not name.startswith(("agent-", "agent_")) and entry.is_file():
                yield Path(entry.path)


def find_session_file(projects: Path, session_id: str) -> Path | None:
    session_id = valid_session_id(session_id)
    try:
        for project in os.scandir(projects):
            candidate = Path(project.path) / f"{session_id}.jsonl"
            if project.is_dir(follow_symlinks=False) and candidate.is_file():
                return candidate
    except OSError:
        return None
    return None


# --------------------------------------------------------------------------- line reading


def _loads(segment: bytes) -> dict | None:
    if not segment.strip():
        return None
    try:
        value = json.loads(segment)
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def split_records(buf: bytes, base: int) -> tuple[list[tuple[int, dict]], int]:
    """(offset, record) for every complete line of ``buf`` plus the offset consumed.

    A last line without a newline counts only if it already parses as a full record;
    otherwise it is left for the next read (the writer is mid-line).
    """
    records: list[tuple[int, dict]] = []
    pos, size = 0, len(buf)
    while pos < size:
        newline = buf.find(b"\n", pos)
        if newline == -1:
            record = _loads(buf[pos:])
            if record is not None:
                records.append((base + pos, record))
                pos = size
            break
        record = _loads(buf[pos:newline])
        if record is not None:
            records.append((base + pos, record))
        pos = newline + 1
    return records, base + pos


@checked("providers.claude.read_bytes")
def read_bytes(path: Path, start: int, end: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start)
        return handle.read(max(0, end - start))


def read_line_at(path: Path, offset: int, limit: int = 32 * 1024 * 1024) -> bytes:
    """The record line starting at ``offset`` (without its newline)."""
    chunks: list[bytes] = []
    total = 0
    with path.open("rb") as handle:
        handle.seek(offset)
        while total < limit:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            newline = chunk.find(b"\n")
            if newline != -1:
                chunks.append(chunk[:newline])
                break
            chunks.append(chunk)
            total += len(chunk)
    return b"".join(chunks)


def aligned_records(path: Path, start: int, end: int) -> tuple[list[tuple[int, dict]], int]:
    """Records whose lines begin inside [start, end); ``start`` may fall mid-line."""
    if start <= 0:
        return split_records(read_bytes(path, 0, end), 0)
    buf = read_bytes(path, start - 1, end)  # one byte of look-behind tells whether start is a line boundary
    if buf[:1] == NEWLINE:
        return split_records(buf[1:], start)
    newline = buf.find(NEWLINE)
    if newline == -1:
        return [], start
    return split_records(buf[newline + 1:], start + newline)


class LineFollower:
    """Yields records appended to a file since the last poll (offset kept in memory)."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self._head = b""
        self.reset_count = 0

    def poll(self) -> list[tuple[int, dict]]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.offset or (self.offset and not self._head_matches()):
            self.offset, self._head = 0, b""
            self.reset_count += 1
        if size == self.offset:
            return []
        buf = read_bytes(self.path, self.offset, size)
        records, end = split_records(buf, self.offset)
        if self.offset == 0 and not self._head:
            self._head = read_bytes(self.path, 0, min(256, size))
        self.offset = end
        return records

    def _head_matches(self) -> bool:
        try:
            return read_bytes(self.path, 0, len(self._head)) == self._head
        except OSError:
            return False


# --------------------------------------------------------------------------- summary index

_TITLE_KINDS = re.compile(rb'"type"\s*:\s*"(custom-title|summary|ai-title)"')
_MESSAGE_TYPES = {"user", "assistant", "system", "attachment"}


def _clean_title(value: Any) -> str | None:
    text = collapse(value, 160) if isinstance(value, str) else ""
    return text or None


def user_prose(record: dict) -> str:
    """The text a person typed in a user record (internal markers, tool results and meta records excluded)."""
    if record.get("isMeta") or record.get("isSidechain") or record.get("isCompactSummary"):
        return ""
    origin = record.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return ""
    content = (record.get("message") or {}).get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
    parts = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            kind, text, _ = classify_user_text(str(block.get("text") or ""))
            if kind == "prose":
                parts.append(text)
    return "\n".join(parts)


class SummaryIndex:
    """Cheap per-session facts for the sidebar, kept up to date from appended bytes only."""

    FULL_SCAN = 3 * 1024 * 1024
    HEAD = 256 * 1024
    HEAD_MAX = 8 * 1024 * 1024
    TAIL = 512 * 1024
    TAIL_MAX = 4 * 1024 * 1024

    def __init__(self, path: Path, session_id: str):
        self.path = path
        self.session_id = session_id
        self.lock = threading.RLock()
        self.sig: tuple[int, int] | None = None
        self.parsed_end = 0
        self._head = b""
        self._reset()

    def _reset(self) -> None:
        self.custom_title = self.summary_title = self.ai_title = None
        self.first_prompt: str | None = None
        self.created: str | None = None
        self.updated: str | None = None
        self.cwd = self.git_branch = self.model = self.effort = self.permission_mode = self.entrypoint = None
        self.used: int | None = None
        self.used_at: str | None = None
        self.has_content = False
        self.parsed_end = 0
        self.mtime_iso: str | None = None
        self._head_titles: dict[str, str | None] = {}

    # ---- update

    def refresh(self) -> None:
        with self.lock:
            try:
                stat = self.path.stat()
            except OSError:
                return
            sig = (stat.st_size, stat.st_mtime_ns)
            if sig == self.sig:
                return
            size = stat.st_size
            if self.sig is None or size < self.parsed_end or not self._head_matches():
                self._reset()
                self._initial_scan(size)
            else:
                records, end = split_records(read_bytes(self.path, self.parsed_end, size), self.parsed_end)
                for _, record in records:
                    self._take(record)
                self.parsed_end = end
            self.sig = sig
            self.mtime_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime))

    def _head_matches(self) -> bool:
        if not self._head:
            return True
        try:
            return read_bytes(self.path, 0, len(self._head)) == self._head
        except OSError:
            return False

    def _initial_scan(self, size: int) -> None:
        self._head = read_bytes(self.path, 0, min(256, size))
        if size <= self.FULL_SCAN:
            records, end = split_records(read_bytes(self.path, 0, size), 0)
            for _, record in records:
                self._take(record)
            self.parsed_end = end
            return
        head_end = self._scan_head(size)
        tail_start = self._scan_tail(size, head_end)
        self._search_middle_titles(head_end, tail_start)
        for kind, value in self._head_titles.items():
            attr = {"custom-title": "custom_title", "summary": "summary_title", "ai-title": "ai_title"}[kind]
            if getattr(self, attr) is None and value:
                setattr(self, attr, value)
        self.parsed_end = size

    def _scan_head(self, size: int) -> int:
        span = self.HEAD
        while True:
            records, end = split_records(read_bytes(self.path, 0, min(span, size)), 0)
            for _, record in records:
                self._take(record, head=True)
            if self.first_prompt or span >= min(self.HEAD_MAX, size):
                return end
            span *= 4
            self.created = self.first_prompt = None
            self.has_content = False

    def _scan_tail(self, size: int, head_end: int) -> int:
        span = self.TAIL
        while True:
            start = max(head_end, size - span)
            records, _ = aligned_records(self.path, start, size)
            self._reset_latest()
            for _, record in records:
                self._take(record)
            if self.used is not None or self.used_at or start <= head_end or span >= self.TAIL_MAX:
                return start
            span *= 4

    def _reset_latest(self) -> None:
        self.custom_title = self.summary_title = self.ai_title = None
        self.model = self.effort = self.permission_mode = None
        self.used = self.used_at = None

    def _search_middle_titles(self, start: int, end: int) -> None:
        """Backward search for the latest custom title (else summary, else AI title) in [start, end)."""
        wanted = {"custom-title": self.custom_title, "summary": self.summary_title, "ai-title": self.ai_title}
        if self.custom_title is not None or start >= end:
            return
        found: dict[str, str | None] = {}
        chunk = 4 * 1024 * 1024
        pos = end
        while pos > start and "custom-title" not in found:
            lo = max(start, pos - chunk)
            buf = read_bytes(self.path, lo, pos)
            for match in reversed(list(_TITLE_KINDS.finditer(buf))):
                kind = match.group(1).decode()
                if kind in found or wanted[kind] is not None:
                    continue
                line_start = buf.rfind(b"\n", 0, match.start()) + 1
                line_end = buf.find(b"\n", match.end())
                record = _loads(buf[line_start: line_end if line_end != -1 else len(buf)])
                if record is not None:
                    found[kind] = _clean_title(record.get("customTitle" if kind == "custom-title" else "summary" if kind == "summary" else "aiTitle"))
            pos = lo
        if "custom-title" in found:
            self.custom_title = found["custom-title"]
        if self.summary_title is None and "summary" in found:
            self.summary_title = found["summary"]
        if self.ai_title is None and "ai-title" in found:
            self.ai_title = found["ai-title"]

    def _take(self, record: dict, head: bool = False) -> None:
        kind = record.get("type")
        if kind == "custom-title":
            value = _clean_title(record.get("customTitle"))
            if head:
                self._head_titles["custom-title"] = value
            else:
                self.custom_title = value
        elif kind == "summary":
            value = _clean_title(record.get("summary"))
            if head:
                self._head_titles["summary"] = value
            else:
                self.summary_title = value
        elif kind == "ai-title":
            value = _clean_title(record.get("aiTitle"))
            if head:
                self._head_titles["ai-title"] = value
            else:
                self.ai_title = value
        elif kind == "permission-mode":
            self.permission_mode = record.get("permissionMode") or self.permission_mode
        elif kind in _MESSAGE_TYPES:
            self._take_message(record, kind)

    def _take_message(self, record: dict, kind: str) -> None:
        timestamp = record.get("timestamp")
        if isinstance(timestamp, str) and timestamp:
            if not self.created:
                self.created = timestamp
            self.updated = timestamp
        if record.get("isSidechain"):
            return
        for attr, key in (("cwd", "cwd"), ("git_branch", "gitBranch"), ("entrypoint", "entrypoint")):
            if record.get(key):
                setattr(self, attr, record[key])
        if kind == "user":
            self.has_content = True
            if record.get("permissionMode"):
                self.permission_mode = record["permissionMode"]
            if self.first_prompt is None:
                prose = user_prose(record)
                if prose:
                    self.first_prompt = collapse(prose, 120)
        elif kind == "assistant":
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            model = message.get("model")
            if model == "<synthetic>" or record.get("isApiErrorMessage"):
                return
            self.has_content = True
            if model:
                self.model = model
            if record.get("effort"):
                self.effort = record["effort"]
            used = context_used(message.get("usage"))
            if used is not None:
                self.used, self.used_at = used, timestamp
        elif kind == "system" and record.get("subtype") == "compact_boundary":
            self.used, self.used_at = None, timestamp or self.used_at or "compacted"

    # ---- read

    @property
    @checked("providers.claude.title_priority")
    def title(self) -> str:
        return self.custom_title or self.summary_title or self.ai_title or self.first_prompt or "Untitled session"

    def updated_iso(self) -> str | None:
        return self.updated or self.mtime_iso


# --------------------------------------------------------------------------- sub-agent aggregation


class AgentAggregate:
    """Totals for one sub-agent, from its sidechain records (either its own file or in-file sidechains)."""

    def __init__(self) -> None:
        self.first_ts: str | None = None
        self.last_ts: str | None = None
        self.model: str | None = None
        self.tool_ids: set[str] = set()
        self.out_by_msg: dict[str, int] = {}
        self.last_context: int | None = None
        self.records = 0
        self.last_tool: str | None = None

    def feed(self, record: dict) -> None:
        timestamp = record.get("timestamp")
        if isinstance(timestamp, str) and timestamp:
            self.first_ts = self.first_ts or timestamp
            self.last_ts = timestamp
        self.records += 1
        if record.get("type") != "assistant":
            return
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        if message.get("model") and message["model"] != "<synthetic>":
            self.model = message["model"]
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id"):
                self.tool_ids.add(str(block["id"]))
                self.last_tool = tool_title(str(block.get("name") or "tool"), block.get("input"))
        usage = message.get("usage")
        if isinstance(usage, dict):
            out = int_or_none(usage.get("output_tokens"))
            key = str(message.get("id") or record.get("uuid") or self.records)
            if out is not None:
                self.out_by_msg[key] = max(out, self.out_by_msg.get(key, 0))
            context = context_used(usage)
            if context is not None:
                self.last_context = context

    @checked("providers.claude.aggregate")
    def summarize(self, hints: dict[str, Any], now: float | None = None) -> dict[str, Any]:
        """The ``data.agent`` dict; a field stays None when neither the sidechain nor the parent transcript carries it.

        ``inputTokens`` is the context size at the agent's latest model call (input + cache reads + cache
        creation), the same figure Claude Code reports for a finished agent; ``outputTokens`` is the sum
        of everything it generated.
        """
        now = time.time() if now is None else now
        totals = hints.get("totals") or {}
        note = hints.get("note")  # latest task notification: (status, timestamp)
        last, note_time = parse_time(self.last_ts), parse_time(note[1]) if note else None
        resumed = last is not None and note_time is not None and last > note_time + 2  # worked again after that notice
        if hints.get("syncResult") is not None:
            status = "error" if hints["syncResult"] else "ok"
        elif note and not resumed:
            status = "ok" if str(note[0]).lower() in {"completed", "complete", "done", "success"} else "error"
        elif hints.get("resultTs") is None and not hints.get("async"):
            status = "running"  # a synchronous agent whose tool call has no result yet
        elif last is not None:
            status = "running" if now - last < 600 else None
        else:
            launched = parse_time(hints.get("toolTs"))
            status = "running" if launched is not None and now - launched < 120 else None
        finished = status in ("ok", "error")
        started = self.first_ts or hints.get("toolTs")
        ended = (self.last_ts or (note[1] if note else None) or hints.get("resultTs")) if finished else None
        duration = totals.get("durationMs") if finished else None
        if finished and duration is None and parse_time(started) is not None and parse_time(ended) is not None:
            duration = int((parse_time(ended) - parse_time(started)) * 1000)
        seen = {"toolCount": len(self.tool_ids) if self.records else None, "inputTokens": self.last_context,
                "outputTokens": sum(self.out_by_msg.values()) if self.out_by_msg else None}
        # A finished synchronous call carries the CLI's own totals (they include blocks a live stream does not forward).
        authoritative = hints.get("syncResult") is not None

        def figure(name: str) -> int | None:
            own, reported = seen[name], totals.get(name)
            return reported if authoritative and reported is not None else own if own is not None else reported

        return {
            "description": hints.get("description"),
            "subagentType": hints.get("subagentType") or hints.get("metaType"),
            "model": self.model or totals.get("model") or hints.get("inputModel"),
            "status": status,
            "startedAt": started,
            "endedAt": ended,
            "durationMs": duration,
            "toolCount": figure("toolCount"),
            "inputTokens": figure("inputTokens"),
            "outputTokens": figure("outputTokens"),
            "lastTool": self.last_tool if status == "running" else None,
        }


def new_agent_hints(tool_input: dict, shell: dict, stamp: str | None) -> dict[str, Any]:
    """What the Agent/Task call itself says, before any sidechain record is known (see ``AgentAggregate.summarize``)."""
    return {
        "description": shell["description"], "subagentType": shell["subagentType"], "inputModel": shell["model"],
        "toolTs": stamp, "async": bool(tool_input.get("run_in_background")) or None,
        "resultTs": None, "syncResult": None, "note": None, "totals": {}, "agentId": None,
        "promptHead": str(tool_input.get("prompt") or "").strip()[:200],
    }


def apply_agent_result(hints: dict[str, Any], structured: Any, is_error: bool, timestamp: str | None) -> None:
    """Fold an Agent tool result (async launch or completed run) into the hints."""
    result = structured if isinstance(structured, dict) else {}
    hints["resultTs"] = timestamp
    if result.get("agentId"):
        hints["agentId"] = str(result["agentId"])
    if result.get("status") == "async_launched":
        hints["async"] = True
        hints["totals"]["model"] = result.get("resolvedModel")
    elif result.get("status") == "completed" or is_error:
        hints["syncResult"] = bool(is_error)
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        output, total = int_or_none(usage.get("output_tokens")), int_or_none(result.get("totalTokens"))
        hints["totals"].update({
            "toolCount": int_or_none(result.get("totalToolUseCount")), "durationMs": int_or_none(result.get("totalDurationMs")),
            "model": result.get("resolvedModel"), "outputTokens": output,
            # totalTokens is the figure Claude Code reports for a finished agent (its context plus what it generated)
            "inputTokens": total - output if total is not None and output is not None and total >= output else context_used(usage),
        })
    if not hints.get("subagentType") and result.get("agentType"):
        hints["subagentType"] = result["agentType"]


class _AgentFile:
    def __init__(self, path: Path):
        self.follower = LineFollower(path)
        self.aggregate = AgentAggregate()

    def poll(self) -> AgentAggregate:
        records = self.follower.poll()
        if self.follower.reset_count:
            self.aggregate, self.follower.reset_count = AgentAggregate(), 0
        for _, record in records:
            self.aggregate.feed(record)
        return self.aggregate


class SubagentIndex:
    """``<session>/subagents/agent-<id>.jsonl`` files and the ``.meta.json`` that names their parent tool call."""

    def __init__(self, session_dir: Path):
        self.dir = session_dir / "subagents"
        self.by_tool: dict[str, str] = {}
        self.meta: dict[str, dict] = {}
        self.files: dict[str, _AgentFile] = {}
        self._scanned_at = 0.0
        self._seen_meta: set[str] = set()

    def _scan(self) -> None:
        if time.monotonic() - self._scanned_at < 1.0:
            return
        self._scanned_at = time.monotonic()
        try:
            names = [entry.name for entry in os.scandir(self.dir) if entry.name.endswith(".meta.json")]
        except OSError:
            return
        for name in names:
            if name in self._seen_meta:
                continue
            try:
                meta = json.loads((self.dir / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            self._seen_meta.add(name)
            agent_id = name[len("agent-"): -len(".meta.json")] if name.startswith("agent-") else name[: -len(".meta.json")]
            self.meta[agent_id] = meta
            if meta.get("toolUseId"):
                self.by_tool[str(meta["toolUseId"])] = agent_id

    def aggregate(self, tool_use_id: str, agent_id_hint: str | None) -> tuple[AgentAggregate | None, dict]:
        agent_id = self.by_tool.get(tool_use_id)
        if agent_id is None:
            self._scan()
            agent_id = self.by_tool.get(tool_use_id) or agent_id_hint
        if not agent_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", agent_id):
            return None, {}
        path = self.dir / f"agent-{agent_id}.jsonl"
        if not path.is_file():
            return None, self.meta.get(agent_id, {})
        entry = self.files.get(agent_id)
        if entry is None:
            entry = self.files[agent_id] = _AgentFile(path)
        return entry.poll(), self.meta.get(agent_id, {})


# --------------------------------------------------------------------------- item mapping


class _Live:
    """Per-window mapper state that does not survive across windows."""

    def __init__(self) -> None:
        self.block_counts: dict[str, int] = {}
        self.reasoning_messages: set[str] = set()
        self.last_item: Item | None = None
        self.last_text: Item | None = None
        self.last_text_mid: str | None = None


class ItemStore:
    """Chronological items of one session file, mapped tail-first and extended as the file grows."""

    def __init__(self, path: Path, session_id: str, cwd: str | None = None):
        self.path = path
        self.session_id = session_id
        self.cwd = cwd
        self.lock = threading.RLock()
        self.subagents = SubagentIndex(path.parent / session_id)
        self._reset()

    def _reset(self) -> None:
        # Cursor versions belong to one transcript generation. Replacing or
        # truncating the file must invalidate old cursors before versions reset.
        self.generation = uuid.uuid4().hex[:8]
        self.items: list[Item] = []
        self.by_id: dict[str, Item] = {}
        self.version = 0
        self.touched: dict[str, int] = {}
        self.orphan_results: OrderedDict[str, dict] = OrderedDict()
        self.result_offsets: dict[str, int] = {}
        self.media: dict[str, dict] = {}
        self.starts: dict[str, str | None] = {}
        self.agent_hints: dict[str, dict] = {}
        self.agent_notes: dict[str, tuple] = {}
        self.inline_agents: dict[str, AgentAggregate] = {}
        self.sidechain_owner: dict[str, str] = {}
        self.tail_start = 0
        self.parsed_end = 0
        self.initialized = False
        self._plan_history: tuple[int, list[Item]] = (-1, [])
        self._head = b""
        self._live = _Live()

    # ---- bookkeeping

    def _touch(self, item: Item, *, older: bool = False) -> None:
        normalize_item("claude-code", item.kind, item.data)
        if older:
            self.touched.setdefault(item.id, 0)
            return
        self.version += 1
        self.touched[item.id] = self.version

    def _add(self, item: Item, live: _Live, older: bool) -> Item:
        existing = self.by_id.get(item.id)
        if existing is not None:  # a duplicated record: keep the first item, refresh its data
            existing.data.update(item.data)
            self._touch(existing, older=older)
            return existing
        self.by_id[item.id] = item
        self.items.append(item)
        live.last_item = item
        self._touch(item, older=older)
        return item

    # ---- loading

    def refresh(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if self.initialized and (size < self.parsed_end or not self._head_matches()):
            self._reset()
        if not self.initialized:
            self._initial_load(size)
        elif size > self.parsed_end:
            records, end = split_records(read_bytes(self.path, self.parsed_end, size), self.parsed_end)
            for offset, record in records:
                self._feed(offset, record, self._live, older=False)
            self.parsed_end = end
        self._refresh_agents()
        self._trim()

    def _head_matches(self) -> bool:
        try:
            return not self._head or read_bytes(self.path, 0, len(self._head)) == self._head
        except OSError:
            return False

    def _initial_load(self, size: int) -> None:
        self._head = read_bytes(self.path, 0, min(256, size))
        span = INITIAL_WINDOW
        while True:
            start = max(0, size - span)
            records, end = aligned_records(self.path, start, size)
            records = self._drop_leading_assistant(records, start)
            if records or start == 0:
                break
            span *= 2
        self.tail_start = records[0][0] if records else (0 if start == 0 else start)
        self.parsed_end = end
        self.initialized = True
        for offset, record in records:
            self._feed(offset, record, self._live, older=False)

    @staticmethod
    def _drop_leading_assistant(records: list[tuple[int, dict]], start: int) -> list[tuple[int, dict]]:
        """A window must not start inside an assistant message (its blocks are merged): start at the next non-assistant record."""
        if start == 0:
            return records
        for index, (_, record) in enumerate(records):
            if record.get("type") != "assistant":
                return records[index:]
        return []

    def load_earlier(self) -> bool:
        """Parse the window just before ``tail_start``; False when the file start was already reached."""
        if self.tail_start <= 0:
            return False
        span = EARLIER_WINDOW
        while True:
            start = max(0, self.tail_start - span)
            records, _ = aligned_records(self.path, start, self.tail_start)
            records = self._drop_leading_assistant(records, start)
            if records or start == 0:
                break
            span *= 2
        live = _Live()
        before = len(self.items)
        for offset, record in records:
            self._feed(offset, record, live, older=True)
        added = self.items[before:]
        self.items[before:] = []
        self.items = added + self.items
        self.tail_start = 0 if start == 0 else (records[0][0] if records else start)
        self._refresh_agents()
        return True

    def _trim(self) -> None:
        """Bound memory: drop the oldest items; they re-parse from disk when paged to."""
        if len(self.items) <= MAX_ITEMS_IN_MEMORY:
            return
        drop = self.items[: len(self.items) - MAX_ITEMS_IN_MEMORY + 1000]
        self.items = self.items[len(drop):]
        for item in drop:
            self.by_id.pop(item.id, None)
            self.touched.pop(item.id, None)
        self.tail_start = self.items[0].seq >> SEQ_SHIFT

    # ---- pages

    @checked("providers.claude.store_page")
    def page(self, *, cursor: str | None, before_seq: int | None, limit: int) -> tuple[list[Item], bool, str]:
        limit = max(1, min(int(limit or 200), 200))
        with self.lock:
            self.refresh()
            since = self._cursor_version(cursor)
            if since is not None:
                changed = [item for item in self.items if self.touched.get(item.id, 0) > since]
                chosen = changed[-limit:]
                return self._copy(chosen), len(changed) > limit, self._cursor()
            if before_seq is not None:
                while sum(1 for item in self.items if item.seq < before_seq) <= limit and self.load_earlier():
                    pass
                older = [item for item in self.items if item.seq < before_seq]
                return self._copy(older[-limit:]), len(older) > limit, self._cursor()
            while len(self.items) <= limit and self.load_earlier():
                pass
            return self._copy(self.items[-limit:]), len(self.items) > limit, self._cursor()

    def plan(self) -> dict | None:
        """The latest checklist, including calls before the initial tail and their matching results."""
        with self.lock:
            if self._plan_history[0] != self.tail_start:
                history = read_plan_history(self.path, self.tail_start, SEQ_SHIFT) if self.tail_start else []
                self._plan_history = (self.tail_start, history)
            historical = []
            for item in self._plan_history[1]:
                if item.id in self.by_id:
                    continue  # Paging older items must not apply the same operation twice.
                if item.data.get("status") == "running" and item.id in self.result_offsets:
                    item = Item(item.id, item.seq, item.kind, item.at, copy.deepcopy(item.data))
                    record = _loads(read_line_at(self.path, self.result_offsets[item.id]))
                    if record is not None:
                        apply_plan_result(item, record)
                historical.append(item)
            result = latest_plan(historical + self.items)
            from ..proofs_a_control import check_itemstore_plan
            check_itemstore_plan(self, historical, result)
            return result

    def _cursor(self) -> str:
        return f"{self.generation}:{self.version}"

    def _cursor_version(self, cursor: str | None) -> int | None:
        if not cursor or ":" not in str(cursor):
            return None
        generation, _, version = str(cursor).partition(":")
        if generation != self.generation or not version.isdigit():
            return None
        return int(version)

    @staticmethod
    def _copy(items: list[Item]) -> list[Item]:
        return [Item(item.id, item.seq, item.kind, item.at, dict(item.data)) for item in items]

    # ---- mapping

    def _feed(self, offset: int, record: dict, live: _Live, older: bool) -> None:
        kind = record.get("type")
        if record.get("isSidechain"):
            self._sidechain(offset, record)
        elif kind == "assistant":
            self._assistant(offset, record, live, older)
        elif kind == "user":
            self._user(offset, record, live, older)
        elif kind == "system":
            self._system(offset, record, live, older)
        elif kind == "attachment":
            self._attachment(offset, record, live, older)

    @staticmethod
    @checked("providers.claude.sequence")
    def _seq(offset: int, sub: int = 0) -> int:
        return (offset << SEQ_SHIFT) | min(sub, SPLIT_SEQ_BLOCKS)

    def _assistant(self, offset: int, record: dict, live: _Live, older: bool) -> None:
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else [b for b in content or [] if isinstance(b, dict)]
        stamp = record.get("timestamp")
        message_id = str(message.get("id") or record.get("uuid") or offset)
        if message.get("model") == "<synthetic>" or record.get("isApiErrorMessage"):
            text = "\n".join(str(b.get("text") or "") for b in blocks if b.get("type") == "text").strip()
            if text:
                level = "error" if record.get("isApiErrorMessage") else "info"
                text = collapse(text, 400)
                self._add(Item(f"{record.get('uuid') or offset}:n", self._seq(offset), "notice", stamp,
                               {"text": text, "level": level}), live, older)
            return
        base = record.get("apiBlockIndex")
        for position, block in enumerate(blocks):
            if isinstance(base, int):
                index = base + position
                live.block_counts[message_id] = max(live.block_counts.get(message_id, 0), index + 1)
            else:
                index = live.block_counts.get(message_id, 0)
                live.block_counts[message_id] = index + 1
            item_id = f"{message_id}:{index}"
            block_type = block.get("type")
            if block_type == "text":
                self._assistant_text(offset, position, item_id, message_id, str(block.get("text") or ""), stamp, live, older)
            elif block_type in ("thinking", "redacted_thinking"):
                live.reasoning_messages.add(message_id)
                text = str(block.get("thinking") or "").strip() if block_type == "thinking" else ""
                self._add(Item(item_id, self._seq(offset, position), "reasoning", stamp,
                               reasoning_data("claude-code", text, source="transcript", exposure="summary", withheld=block_type == "redacted_thinking")), live, older)
                live.last_text = None
            elif block_type == "tool_use":
                self._tool_use(offset, position, block, stamp, live, older)
                live.last_text = None
        if message.get("stop_reason") == "end_turn" and message_id not in live.reasoning_messages:
            self._add(Item(f"reasoning-unreported:{message_id}", self._seq(offset, len(blocks)), "reasoning", stamp,
                           reasoning_data("claude-code", None, source="transcript")), live, older)

    def _assistant_text(self, offset: int, position: int, item_id: str, message_id: str, text: str,
                        stamp: str | None, live: _Live, older: bool) -> None:
        if not text.strip():
            return
        if live.last_text is not None and live.last_text_mid == message_id and live.last_item is live.last_text:
            merged = live.last_text
            merged.data["text"], _ = bound_text(merged.data["text"] + "\n\n" + text)
            self._touch(merged, older=older)
            return
        attachments = []
        for ref, attachment in text_media_refs(text):
            self.media[attachment["id"]] = {"kind": "path", "ref": ref, "mime": attachment["mime"]}
            attachments.append(attachment)
        clipped, truncated = bound_text(text)
        data: dict[str, Any] = {"text": clipped, "attachments": attachments}
        if truncated:
            data["truncated"] = True
        item = self._add(Item(item_id, self._seq(offset, position), "assistant", stamp, data), live, older)
        live.last_text, live.last_text_mid = item, message_id

    def _tool_use(self, offset: int, position: int, block: dict, stamp: str | None, live: _Live, older: bool) -> None:
        tool_id, name = str(block.get("id") or ""), str(block.get("name") or "tool")
        if not tool_id:
            return
        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        self.starts[tool_id] = stamp
        if name == QUESTION_TOOL:
            item = Item(tool_id, self._seq(offset, position), "question", stamp, question_data(tool_input, tool_id))
        else:
            item = Item(tool_id, self._seq(offset, position), "tool", stamp, tool_data(name, tool_input))
            if item.data["category"] == "agent":
                self.agent_hints[tool_id] = new_agent_hints(tool_input, item.data["agent"], stamp)
        item = self._add(item, live, older)
        pending = self.orphan_results.pop(tool_id, None)
        if pending is not None:
            self._apply_result(item, pending, older)

    def _user(self, offset: int, record: dict, live: _Live, older: bool) -> None:
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else [b for b in content or [] if isinstance(b, dict)]
        stamp, uid = record.get("timestamp"), str(record.get("uuid") or offset)
        if record.get("isMeta") or record.get("isCompactSummary") or record.get("isVisibleInTranscriptOnly"):
            for index, block in enumerate(blocks):
                if block.get("type") == "text":
                    self._helper_notices(offset, index, uid, str(block.get("text") or ""), stamp, live, older)
            return
        origin = record.get("origin")
        machine = isinstance(origin, dict) and origin.get("kind") not in (None, "human")
        prose: list[str] = []
        attachments: list[dict] = []
        for index, block in enumerate(blocks):
            block_type = block.get("type")
            if block_type == "tool_result":
                self._record_result(offset, record, block, older)
            elif block_type == "text":
                if self._helper_notices(offset, index, uid, str(block.get("text") or ""), stamp, live, older):
                    continue
                kind, text, level = classify_user_text(str(block.get("text") or ""))
                if kind == "prose" and machine:
                    kind, text = "notice", collapse(text, 400)
                if kind == "prose":
                    prose.append(text)
                    for ref, attachment in text_media_refs(text):
                        self.media[attachment["id"]] = {"kind": "path", "ref": ref, "mime": attachment["mime"]}
                        attachments.append(attachment)
                elif kind == "notice":
                    self._notice(offset, index, uid + f":n{index}", text, level, stamp, live, older)
                    note = task_notification(str(block.get("text") or ""))
                    if note:
                        self._note_agent(note, stamp)
            elif block_type == "image":
                attachment = self._image_attachment(offset, index, block)
                if attachment:
                    attachments.append(attachment)
        if prose or attachments:
            text, truncated = bound_text("\n\n".join(prose))
            data: dict[str, Any] = {"text": text, "attachments": attachments}
            if truncated:
                data["truncated"] = True
            if record.get("permissionMode"):
                data["permissionMode"] = record["permissionMode"]
            self._add(Item(uid, self._seq(offset), "user", stamp, data), live, older)
            live.last_text = None

    def _notice(self, offset: int, sub: int, item_id: str, text: str, level: str, stamp: str | None, live: _Live, older: bool) -> None:
        self._add(Item(item_id, self._seq(offset, sub + 1), "notice", stamp, {"text": text, "level": level}), live, older)
        live.last_text = None

    def _helper_notices(self, offset: int, sub: int, uid: str, text: str, stamp: str | None, live: _Live, older: bool) -> bool:
        reports = helper_reports(text)
        for index, report in enumerate(reports):
            helper = report["helper"]
            hints = next((h for h in self.agent_hints.values() if h.get("agentId") == helper), {})
            report["helper"] = hints.get("description") or helper
            body, truncated = bound_text(report["report"])
            data = {**report, "report": body, "text": "Helper reported · " + report["helper"], "truncated": truncated}
            self._add(Item(uid + f":helper:{sub}:{index}", self._seq(offset, sub + index + 1), "notice", stamp, data), live, older)
        if reports:
            note = task_notification(text)
            if note:
                self._note_agent(note, stamp)
            live.last_text = None
        return bool(reports)

    def _image_attachment(self, offset: int, index: int, block: dict) -> dict | None:
        source = block.get("source") if isinstance(block.get("source"), dict) else {}
        mime = source.get("media_type")
        if source.get("type") == "base64" and mime in set(TYPES.values()) and isinstance(source.get("data"), str):
            token = image_token(mime, source["data"])
            self.media[token] = {"kind": "data", "offset": offset, "mime": mime}
            return attachment_dict(token, kind="image", label="Attached image", mime=mime)
        return None

    def _record_result(self, offset: int, record: dict, block: dict, older: bool) -> None:
        tool_id = str(block.get("tool_use_id") or "")
        if not tool_id:
            return
        text, images = flatten_result_content(block.get("content"))
        info = {"text": text, "isError": bool(block.get("is_error")), "timestamp": record.get("timestamp"), "offset": offset,
                "structured": record.get("toolUseResult", record.get("tool_use_result")), "images": [self._image_attachment(offset, i, image) for i, image in enumerate(images)]}
        self.result_offsets[tool_id] = offset
        item = self.by_id.get(tool_id)
        if item is None:
            self.orphan_results[tool_id] = info
            while len(self.orphan_results) > 2000:
                self.orphan_results.popitem(last=False)
            return
        self._apply_result(item, info, older)

    def _apply_result(self, item: Item, info: dict, older: bool) -> None:
        if item.kind == "question":
            answers = info["structured"].get("answers") if isinstance(info["structured"], dict) else None
            item.data["answers"] = answers_by_id(item.data.get("questions", []), answers)
            item.data["answered"] = bool(item.data["answers"]) and not info["isError"]
            if info["isError"]:
                item.data["declined"] = True
        else:
            apply_tool_result(item.data, text=info["text"], is_error=info["isError"], timestamp=info["timestamp"],
                              started_at=self.starts.get(item.id), structured=info["structured"])
            images = [image for image in info["images"] if image]
            if images:
                item.data["attachments"] = images
            if item.id in self.agent_hints:
                self._agent_result(item.id, info)
        self._touch(item, older=older)
        if item.kind == "tool" and item.data.get("diff") and not info["isError"]:
            diff_id = f"{item.id}:diff"
            existing = self.by_id.get(diff_id)
            if existing is not None:
                existing.data = dict(item.data["diff"])
                self._touch(existing, older=older)
            else:
                self._add(Item(diff_id, self._seq(info.get("offset", 0), 62), "diff", info["timestamp"],
                               dict(item.data["diff"])), self._live, older)

    def _agent_result(self, tool_id: str, info: dict) -> None:
        apply_agent_result(self.agent_hints[tool_id], info["structured"], info["isError"], info["timestamp"])

    def _note_agent(self, note: dict[str, str], stamp: str | None) -> None:
        """Remember a task notification by tool-use id; ``_refresh_agents`` folds it into the agent's status."""
        if note.get("toolUseId") and note.get("status"):
            totals = {name: int(note[key]) for key, name in (("toolUses", "toolCount"), ("durationMs", "durationMs")) if note.get(key)}
            self.agent_notes[note["toolUseId"]] = (note["status"], stamp, totals)

    def _system(self, offset: int, record: dict, live: _Live, older: bool) -> None:
        subtype, stamp = record.get("subtype"), record.get("timestamp")
        uid = str(record.get("uuid") or offset)
        if subtype == "compact_boundary":
            meta = record.get("compactMetadata") if isinstance(record.get("compactMetadata"), dict) else {}
            data = {"state": "completed", "beforeTokens": int_or_none(meta.get("preTokens")),
                    "afterTokens": int_or_none(meta.get("postTokens"))}
            if meta.get("trigger"):
                data["trigger"] = meta["trigger"]
            self._add(Item(uid, self._seq(offset), "compaction", stamp, data), live, older)
            live.last_text = None
        elif subtype == "informational" and record.get("content"):
            level = {"warning": "warning", "error": "error"}.get(str(record.get("level")), "info")
            self._notice(offset, 0, uid, collapse(record["content"], 400), level, stamp, live, older)
        elif subtype == "api_error":
            retry, maximum = record.get("retryAttempt"), record.get("maxRetries")
            if maximum is not None and retry is not None and retry < maximum:
                return  # only the failure that exhausted the retries is worth showing
            error = record.get("error") if isinstance(record.get("error"), dict) else {}
            self._notice(offset, 0, uid, collapse(error.get("formatted") or error.get("message") or "API error", 300), "error", stamp, live, older)

    def _attachment(self, offset: int, record: dict, live: _Live, older: bool) -> None:
        attachment = record.get("attachment") if isinstance(record.get("attachment"), dict) else {}
        kind, stamp, uid = attachment.get("type"), record.get("timestamp"), str(record.get("uuid") or offset)
        if kind == "queued_command":
            raw = attachment.get("prompt")
            if isinstance(raw, list):
                # Sent while Claude was working, with an image: a list of content blocks, not text.
                self._queued_blocks(offset, uid, stamp, [b for b in raw if isinstance(b, dict)], live, older)
                return
            prompt = str(raw or "")
            if self._helper_notices(offset, 0, uid, prompt, stamp, live, older):
                return
            if attachment.get("commandMode") == "task-notification" or prompt.lstrip().startswith("<task-notification>"):
                note = task_notification(prompt)
                if note:
                    self._note_agent(note, stamp)
                _, text, level = classify_user_text(prompt)
                if text:
                    self._notice(offset, 0, uid, text, level, stamp, live, older)
            else:
                kind2, text, level = classify_user_text(prompt)
                if kind2 == "prose":
                    clipped, _ = bound_text(text)
                    self._add(Item(uid, self._seq(offset), "user", stamp, {"text": clipped, "attachments": [], "queued": True}), live, older)
                    live.last_text = None
                elif kind2 == "notice":
                    self._notice(offset, 0, uid, text, level, stamp, live, older)
        elif kind == "max_turns_reached":
            self._notice(offset, 0, uid, f"Reached the turn limit ({attachment.get('maxTurns')} turns).", "warning", stamp, live, older)

    def _queued_blocks(self, offset: int, uid: str, stamp: str | None, blocks: list[dict], live: _Live, older: bool) -> None:
        prose: list[str] = []
        attachments: list[dict] = []
        for index, block in enumerate(blocks):
            if block.get("type") == "text":
                if self._helper_notices(offset, index, uid, str(block.get("text") or ""), stamp, live, older):
                    continue
                kind, text, level = classify_user_text(str(block.get("text") or ""))
                if kind == "prose":
                    prose.append(text)
                elif kind == "notice":
                    self._notice(offset, index, uid + f":n{index}", text, level, stamp, live, older)
            elif block.get("type") == "image":
                attachment = self._image_attachment(offset, index, block)
                if attachment:
                    attachments.append(attachment)
        if prose or attachments:
            clipped, _ = bound_text("\n\n".join(prose))
            self._add(Item(uid, self._seq(offset), "user", stamp, {"text": clipped, "attachments": attachments, "queued": True}), live, older)
            live.last_text = None

    def _sidechain(self, offset: int, record: dict) -> None:
        """Sub-agent traffic inside the main file: never a top-level item, counted on its Agent tool item."""
        uid, parent = str(record.get("uuid") or ""), record.get("parentUuid")
        owner = self.sidechain_owner.get(str(parent))
        if owner is None and record.get("type") == "user":
            # The first sidechain record is the sub-agent's prompt: match it to the Agent call that carried it.
            prompt = user_prose_text_of_sidechain(record)
            owner = next((tool_id for tool_id, hints in self.agent_hints.items()
                          if prompt and hints["promptHead"] == prompt and tool_id not in self.inline_agents), None)
        if owner is None:
            return
        self.sidechain_owner[uid] = owner
        self.inline_agents.setdefault(owner, AgentAggregate()).feed(record)

    def _refresh_agents(self) -> None:
        """Recompute ``data.agent`` of every Agent/Task item still running (or not yet computed) and touch changed ones."""
        for tool_id, hints in self.agent_hints.items():
            item = self.by_id.get(tool_id)
            if item is None or (item.data.get("agent", {}).get("status") in ("ok", "error") and tool_id not in self.agent_notes):
                continue
            aggregate = self.inline_agents.get(tool_id)
            meta: dict = {}
            if aggregate is None:
                aggregate, meta = self.subagents.aggregate(tool_id, hints.get("agentId"))
            if not hints.get("subagentType") and meta.get("agentType"):
                hints["metaType"] = meta["agentType"]
            if not hints.get("description") and meta.get("description"):
                hints["description"] = meta["description"]
            note = self.agent_notes.get(tool_id)
            if note:
                hints["note"] = note[:2]
                hints["totals"].update(note[2])
            summary = (aggregate or AgentAggregate()).summarize(hints)
            if summary != item.data.get("agent"):
                item.data["agent"] = summary
                self._touch(item)

    # ---- on-demand content

    def tool_output(self, item_id: str, limit: int = 2 * 1024 * 1024) -> str | None:
        """Full (not 8 KB) output of a tool item, read from its result record."""
        with self.lock:
            self.refresh()
            offset = self.result_offsets.get(item_id)
            if offset is None:
                return None
            record = _loads(read_line_at(self.path, offset))
        for block in ((record or {}).get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id") == item_id:
                text, _ = flatten_result_content(block.get("content"))
                return text[:limit]
        return None

    def read_media(self, token: str) -> tuple[bytes, str, str] | None:
        """(bytes, mime, name) for a ``mediaRef`` token of this session, or None."""
        with self.lock:
            self.refresh()
            entry = self.media.get(token)
        if entry is None:
            entry = self._scan_media(token)
        if entry is None:
            return None
        if entry["kind"] == "data":
            record = _loads(read_line_at(self.path, entry["offset"]))
            for block in _iter_image_blocks(record or {}):
                source = block.get("source") or {}
                if source.get("type") == "base64" and image_token(str(source.get("media_type")), str(source.get("data"))) == token:
                    try:
                        return base64.b64decode(source["data"], validate=True), str(source["media_type"]), "image"
                    except (binascii.Error, ValueError):
                        return None
            return None
        ref = entry["ref"]
        raw = ref[len("file://"):] if ref.startswith("file://") else ref
        if re.match(r"^/[A-Za-z]:/", raw):
            raw = raw[1:]
        path = Path(raw)
        if not path.is_absolute():
            if not self.cwd:
                return None
            path = Path(self.cwd) / path
        mime = TYPES.get(path.suffix.lower())
        try:
            if not mime or not path.is_file() or path.stat().st_size > MAX_MEDIA_BYTES:
                return None
            return path.read_bytes(), mime, path.name
        except OSError:
            return None

    def _scan_media(self, token: str) -> dict | None:
        """Slow path after a restart: find the image block whose token matches by scanning the file once."""
        offset = 0
        with self.path.open("rb") as handle:
            for line in handle:
                if b'"image"' in line:
                    record = _loads(line)
                    for block in _iter_image_blocks(record or {}):
                        source = block.get("source") or {}
                        if source.get("type") == "base64" and image_token(str(source.get("media_type")), str(source.get("data"))) == token:
                            entry = {"kind": "data", "offset": offset, "mime": source.get("media_type")}
                            self.media[token] = entry
                            return entry
                offset += len(line)
        return None


def user_prose_text_of_sidechain(record: dict) -> str:
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content.strip()[:200]
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return str(block.get("text") or "").strip()[:200]
    return ""


def _iter_image_blocks(record: dict) -> Iterator[dict]:
    attachment = record.get("attachment") if isinstance(record.get("attachment"), dict) else {}
    if attachment.get("type") == "queued_command" and isinstance(attachment.get("prompt"), list):
        yield from (block for block in attachment["prompt"] if isinstance(block, dict) and block.get("type") == "image")
    content = (record.get("message") or {}).get("content")
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "image":
            yield block
        elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
            for inner in block["content"]:
                if isinstance(inner, dict) and inner.get("type") == "image":
                    yield inner


class StoreCache:
    """Small LRU of ``ItemStore`` objects (each holds parsed items in memory)."""

    def __init__(self, limit: int = MAX_STORES):
        self.limit = limit
        self._stores: OrderedDict[str, ItemStore] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, path: Path, session_id: str, cwd: str | None) -> ItemStore:
        key = str(path)
        with self._lock:
            store = self._stores.get(key)
            if store is None:
                store = self._stores[key] = ItemStore(path, session_id, cwd)
            else:
                store.cwd = cwd or store.cwd
            self._stores.move_to_end(key)
            while len(self._stores) > self.limit:
                self._stores.popitem(last=False)
            return store
