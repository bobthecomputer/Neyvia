"""Neyvia chat turns and chat-stream events as connected-session items.

Tool calls and reasoning follow ``web/src/neyvia/neyviaChatStream.js``, which the classic UI uses to
render the same records: only recorded tool events and provider-authored reasoning summaries become
items, and nothing is inferred. ``turn_items`` maps a stored turn; ``LiveTurn`` maps the events of a
running turn, and gives its items the ids and sequence numbers ``turn_items`` gives them once saved.

Sequence numbers are ``(turn ordinal + 1) * 100 + slot``: a turn's activity uses slots 0-98 in
order and its own text slot 99, so items sort the way the transcript reads and a page can be
requested by turn.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from .model import ContextUsage, Item
from .neyvia_options import model_label, normalize_runtime
from .plan import plan_op
from .. import proofs_a_sessions as _proofs

TEXT_LIMIT = 8 * 1024  # tool output, tool input and reasoning text per item
SEQ_STRIDE = 100
TEXT_SLOT = SEQ_STRIDE - 1

_SUMMARY_KINDS = frozenset({"reasoning_summary", "runtime_reasoning_summary", "runtime_reasoning_summary_delta", "summary"})
_TOOL_KINDS = frozenset({"tool", "runtime_tool", "tool_call", "tool_result", "runtime_tool_call", "runtime_tool_result"})
_THINKING_KINDS = frozenset({"thinking_text", "runtime_thinking", "runtime_thinking_delta"})
_PROVIDER_REASONING = "provider.reasoning_content"
_OK = frozenset({"completed", "ok", "success", "succeeded", "done"})
_FAILED = frozenset({"failed", "error"})
_CATEGORY_RULES = (
    (re.compile(r"^mcp|[._]mcp[._]"), "mcp"),
    (re.compile(r"terminal|shell|command|powershell|bash|(^|[._])exec($|[._])"), "command"),
    (re.compile(r"write|edit|patch|apply|delete|rename|move"), "edit"),
    (re.compile(r"web|browser|situation|fetch|url|preview"), "web"),
    (re.compile(r"search|find|grep|glob|list|describe|retrieve|memory"), "search"),
    (re.compile(r"read|open|inspect|view|screenshot"), "read"),
    (re.compile(r"agent|delegate|spawn|goal|ask_user|question"), "agent"),
)
_PLAIN_SOURCES = frozenset({"operator-submitted", "backend-runtime-reply", "backend-model-message"})
_PATH_KEYS = ("path", "file", "file_path", "filePath")
_QUERY_KEYS = ("query", "url", "pattern", "q")


def seq_for(ordinal: int, slot: int) -> int:
    return (ordinal + 1) * SEQ_STRIDE + slot


def ordinal_of(seq: int) -> int:
    return seq // SEQ_STRIDE - 1


def _iso(value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value) if value else None


def _clip(text: str, limit: int = TEXT_LIMIT) -> tuple[str, bool]:
    return (text[:limit], True) if len(text) > limit else (text, False)


def _json_value(text: str) -> Any:
    if not isinstance(text, str) or not re.match(r"\s*[\[{]", text):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _json_object(text: str) -> dict[str, Any]:
    value = _json_value(text)
    return value if isinstance(value, dict) else {}


def _display(value: Any) -> str:
    """A tool input or output as text; JSON is pretty-printed like the classic UI does."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        parsed = _json_value(value)
        return json.dumps(parsed, ensure_ascii=False, indent=2) if parsed is not None else value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


# -- tools -------------------------------------------------------------------------------------


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_native_tool_category(args[0], result))
def tool_category(name: str) -> str:
    lowered = str(name or "").lower()
    return next((category for pattern, category in _CATEGORY_RULES if pattern.search(lowered)), "other")


def _first(args: dict[str, Any], keys: tuple[str, ...]) -> str:
    return next((str(args[key]) for key in keys if isinstance(args.get(key), (str, int)) and str(args[key]).strip()), "")


def tool_title(name: str, category: str, args: dict[str, Any]) -> str:
    detail = ""
    if category == "command":
        detail = (_first(args, ("command", "cmd")).strip().splitlines() or [""])[0]
    elif category in ("read", "edit"):
        detail = _first(args, _PATH_KEYS)
    elif category in ("search", "web"):
        detail = _first(args, _QUERY_KEYS)
    return (detail[:160] if detail else name) or "tool"


def _tool_input(category: str, args: dict[str, Any], text: str) -> str:
    if category == "command" and _first(args, ("command", "cmd")):
        return " ".join(_first(args, ("command", "cmd")).split())[:2000]
    if args:
        return json.dumps(args, ensure_ascii=False, separators=(",", ":"), default=str)[:2000]
    return " ".join(text.split())[:2000]


def _bodies(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """A tool result's own object and the nested one it reports the outcome in (``toolResult`` or ``result``)."""
    return [parsed] + [parsed[key] for key in ("toolResult", "result") if isinstance(parsed.get(key), dict)]


def _find_number(parsed: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for source in _bodies(parsed):
        for key in keys:
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
    return None


def _readable_output(category: str, parsed: dict[str, Any], text: str) -> str:
    """What a person wants to see of a result: a command's output or a file's content, else the recorded text."""
    for body in _bodies(parsed)[1:]:
        if category == "command" and isinstance(body.get("stdout"), str):
            errors = body.get("stderr") if isinstance(body.get("stderr"), str) else ""
            return body["stdout"] + ("\n" + errors if errors else "")
        if category == "read" and isinstance(body.get("content"), str):
            return body["content"]
    return text


def normalize_tool_call(raw: dict[str, Any], index: int) -> dict[str, Any]:
    """One tool row as neyviaChatStream.js normalizeNeyviaChatStreamToolCalls reads it."""
    data = raw["data"] if isinstance(raw.get("data"), dict) else raw
    output = data.get("output") if data.get("output") is not None else data.get("result")
    parsed = _json_value(output) if isinstance(output, str) else output
    parsed = parsed if isinstance(parsed, dict) else {}
    failed = parsed.get("ok") is False or parsed.get("isError") is True or parsed.get("is_error") is True
    failure = parsed.get("failure") if isinstance(parsed.get("failure"), dict) else {}
    error = data.get("error") or (failure.get("message") or parsed.get("error") or parsed.get("message") or output if failed else "")
    status = "failed" if error else str(data.get("toolStatus") or data.get("status") or "started")[:32]
    ident = str(data.get("callId") or data.get("itemId") or data.get("id") or f"tool-call-{index + 1}")[:240]
    first = data.get("input") if data.get("input") is not None else data.get("command", data.get("code"))
    return {"id": ident, "tool": str(data.get("tool") or "tool")[:240], "status": status, "input": _display(first),
            "output": _display(output), "error": _display(error), "at": raw.get("at") or data.get("at")}


def _kind_of(raw: dict[str, Any]) -> str:
    return re.sub(r"[.-]", "_", str(raw.get("kind") or raw.get("type") or "").lower())


def _text_of(raw: dict[str, Any], *keys: str) -> str:
    return next((str(raw[key]).strip() for key in keys if raw.get(key)), "")


def merge_calls(existing: dict[str, Any], call: dict[str, Any]) -> dict[str, Any]:
    """A later row of one call updates it; an earlier input or output stays when the later row has none."""
    merged = {**existing, **{key: value for key, value in call.items() if value not in ("", None)}}
    merged["status"] = "failed" if merged.get("error") else call["status"]
    return merged


def segments_from(rows: Any) -> list[dict[str, Any]]:
    """Reasoning and tool segments from a receipt's ``activitySegments`` or ``toolTimeline``."""
    segments: list[dict[str, Any]] = []
    tool_at: dict[str, int] = {}
    for index, raw in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(raw, dict):
            continue
        data = raw["data"] if isinstance(raw.get("data"), dict) else raw
        kind = _kind_of(raw)
        if kind in _SUMMARY_KINDS:
            text = _text_of(data, "text", "message", "output", "summary")
            if text:
                segments.append({"kind": "reasoning_summary", "id": str(raw.get("id") or data.get("id") or f"reasoning-{index + 1}"), "text": text})
        elif kind in _THINKING_KINDS and data.get("source") == _PROVIDER_REASONING:
            text = str(data.get("text") or data.get("message") or data.get("output") or "")
            if text:
                segments.append({"kind": "thinking_text", "id": str(raw.get("id") or data.get("id") or f"thinking-{index + 1}"), "text": text})
        elif kind in _TOOL_KINDS or raw.get("tool") or data.get("tool"):
            call = normalize_tool_call(raw, index)
            if call["id"] in tool_at:  # the start and the result of one call are two rows
                position = tool_at[call["id"]]
                segments[position] = {"kind": "tool", **merge_calls(segments[position], call)}
            else:
                tool_at[call["id"]] = len(segments)
                segments.append({"kind": "tool", **call})
    return segments


def receipt_of(metadata: Any) -> dict[str, Any] | None:
    """The turn receipt, wherever the runtime stored it (the store's own lookup order)."""
    if not isinstance(metadata, dict):
        return None
    if isinstance(metadata.get("turnReceipt"), dict):
        return metadata["turnReceipt"]
    result = metadata.get("runtimeResult")
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("turnReceipt"), dict):
        return result["turnReceipt"]
    compartment = result.get("compartment")
    nested = compartment.get("turnReceipt") if isinstance(compartment, dict) else None
    return nested if isinstance(nested, dict) else None


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_native_segments(args[0], result))
def activity_segments(receipt: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The turn's ordered reasoning and tool segments, as neyviaChatTraceFields resolves them."""
    if not receipt:
        return []
    timeline = receipt.get("toolTimeline") if isinstance(receipt.get("toolTimeline"), list) else []
    recorded = segments_from(receipt.get("activitySegments")) or segments_from(timeline)
    summary = str(receipt.get("reasoningSummary") or "")
    legacy = [{"kind": "reasoning_summary", "id": "reasoning-legacy", "text": summary}] if summary.strip() else []
    if recorded:
        return recorded if any(seg["kind"] == "reasoning_summary" for seg in recorded) else legacy + recorded
    return legacy


def compaction_rows(receipt: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Compaction recorded in the receipt's timeline: one row per compaction, completed once it says so."""
    rows: list[dict[str, Any]] = []
    for row in (receipt or {}).get("toolTimeline") or []:
        text = str(row.get("summary") or "") if isinstance(row, dict) and _kind_of(row) == "runtime_progress" else ""
        if not re.search(r"compact", text, re.I):
            continue
        done = bool(re.search(r"compacted|finished|done", text, re.I))
        if done and rows and rows[-1]["state"] == "started":
            rows[-1] = {**rows[-1], "state": "completed", "text": text[:300]}
        else:
            rows.append({"state": "completed" if done else "started", "text": text[:300], "at": row.get("at")})
    return rows


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_native_tool(kwargs, result))
def tool_item(call: dict[str, Any], item_id: str, seq: int, at: str | None, *, finished: bool,
              duration_ms: int | None = None) -> Item:
    name = call["tool"]
    category = tool_category(name)
    args = _json_object(call["input"])
    status = call["status"].lower()
    if call.get("error") or status in _FAILED:
        state = "error"
    elif status in _OK:
        state = "ok"
    else:
        state = "error" if finished else "running"  # a finished turn never leaves a call running
    parsed = _json_object(call["output"])
    text = call["error"] or call["output"] if state == "error" else _readable_output(category, parsed, call["output"])
    output, cut = _clip(text or "")
    files = [_first(args, _PATH_KEYS)] if category in ("read", "edit") and _first(args, _PATH_KEYS) else []
    data: dict[str, Any] = {
        "name": name, "category": category, "title": tool_title(name, category, args),
        "input": _tool_input(category, args, call["input"]), "status": state, "output": output,
        "exitCode": _find_number(parsed, ("exit_code", "exitCode", "exitcode")), "files": files,
        "durationMs": _find_number(parsed, ("duration_ms", "durationMs")) or duration_ms,  # the tool's own figure first
    }
    if cut:
        data["outputTruncated"] = True
    plan = plan_op(name, args) if state != "error" else None
    if plan is not None:
        data["plan"] = plan  # a run's own checklist (update_plan, TodoWrite) from the call's input
    if finished and state == "error" and status not in _FAILED and not call.get("error"):
        data["note"] = "No result was recorded for this call."
    return Item(id=item_id, seq=seq, kind="tool", at=at, data=data)


# -- stored turns ------------------------------------------------------------------------------


def route_of(turn: dict[str, Any]) -> tuple[str, str, str] | None:
    """(runtime, provider, model) a turn ran on, when it recorded one."""
    metadata = turn.get("metadata") if isinstance(turn.get("metadata"), dict) else {}
    result = metadata.get("runtimeResult") if isinstance(metadata.get("runtimeResult"), dict) else {}
    runtime = normalize_runtime(result.get("runtime") or metadata.get("runtime"))
    if not runtime:
        return None
    route = result.get("route") if isinstance(result.get("route"), dict) else {}
    return runtime, str(route.get("provider") or ""), str(route.get("model") or route.get("model_id") or "")


def _route_notice(previous: tuple[str, str, str] | None, current: tuple[str, str, str] | None) -> str | None:
    if not previous or not current or previous == current:
        return None
    if previous[0] != current[0]:
        label = current[0].replace("-", " ").title() if current[0] != "neyvia-agent" else "Neyvia Native"
        return f"Now running on {label}" + (f" with {model_label(current[2])}." if current[2] else ".")
    # A hand-back turn names its runtime but no model; only two named models can differ.
    return f"Model changed to {model_label(current[2])}." if previous[2] and current[2] and previous[2] != current[2] else None


def _attachments(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for entry in metadata.get("attachments") or []:
        if isinstance(entry, dict) and entry.get("name"):
            mime = str(entry.get("mime") or "")
            # Neyvia keeps only a receipt of an attachment (name, type, size, hash), never a servable copy.
            rows.append({"id": "", "kind": "image" if mime.startswith("image/") else "file", "label": str(entry["name"])[:200],
                         "url": None, "mime": mime or None})
    return rows


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_native_turn(kwargs, result))
def turn_items(turn: dict[str, Any], ordinal: int,
               previous: tuple[str, str, str] | None = None) -> tuple[list[Item], tuple[str, str, str] | None]:
    """The items of one stored turn, and the route to compare the next assistant turn with."""
    turn_id, at = str(turn["turnId"]), turn.get("createdAt")
    metadata = turn.get("metadata") if isinstance(turn.get("metadata"), dict) else {}
    content = str(turn.get("content") or "")
    source = str(turn.get("source") or "")
    extra = {key: value for key, value in (("source", source if source not in _PLAIN_SOURCES else ""),
                                           ("author", metadata.get("author"))) if value}
    if turn.get("role") == "user":
        data = {"text": content, "attachments": _attachments(metadata), **extra}
        return [Item(id=turn_id, seq=seq_for(ordinal, TEXT_SLOT), kind="user", at=at, data=data)], previous
    route = route_of(turn)
    result = metadata.get("runtimeResult") if isinstance(metadata.get("runtimeResult"), dict) else {}
    receipt = receipt_of(metadata)
    slot = 0
    activity: list[Item] = []

    def add(kind: str, data: dict[str, Any], key: str, when: Any = None) -> None:
        nonlocal slot
        if slot < TEXT_SLOT:
            activity.append(Item(id=f"{turn_id}#{key}", seq=seq_for(ordinal, slot), kind=kind, at=when or at, data=data))
            slot += 1

    notice = _route_notice(previous, route)
    if notice:
        add("notice", {"text": notice, "level": "info"}, "route")
    for number, row in enumerate(compaction_rows(receipt), 1):
        add("compaction", {"state": row["state"], "beforeTokens": None, "afterTokens": None, "text": row["text"]},
            f"compaction-{number}", row["at"])
    segments = activity_segments(receipt)
    room = TEXT_SLOT - slot
    shown = segments[:room - 1] if len(segments) > room else segments  # keep one slot for the "more" notice
    reasoning = 0
    for segment in shown:
        if segment["kind"] == "tool":
            item = tool_item(segment, f"{turn_id}#tool-{segment['id']}", seq_for(ordinal, slot), at, finished=True)
            add("tool", item.data, f"tool-{segment['id']}", segment.get("at"))
        else:
            reasoning += 1
            text, cut = _clip(segment["text"])
            add("reasoning", {"summary": text, "hidden": False, **({"truncated": True} if cut else {})}, f"reasoning-{reasoning}")
    if len(segments) > len(shown):
        add("notice", {"text": f"{len(segments) - len(shown)} more activity rows are not shown.", "level": "info"}, "more")
    status = str(result.get("status") or "").lower()
    main_slot = seq_for(ordinal, TEXT_SLOT)
    if status in ("failed", "error", "timeout") or source.endswith("error"):
        main = Item(id=f"{turn_id}#outcome", seq=main_slot, kind="notice", at=at, data={"text": content, "level": "error"})
    elif status in ("cancelled", "stop_unconfirmed", "interrupted") or source == "chat-interrupted":
        level = "info" if status == "cancelled" else "warning"
        main = Item(id=f"{turn_id}#outcome", seq=main_slot, kind="notice", at=at, data={"text": content, "level": level})
    else:
        data = {"text": content, "attachments": [], **extra}
        if route:
            data.update(runtime=route[0], model=route[2] or None)
        main = Item(id=turn_id, seq=main_slot, kind="assistant", at=at, data=data)
    return [*activity, main], route or previous


# -- a running turn ----------------------------------------------------------------------------


from .. import proofs_a_native_sessions as _native_proofs


class LiveTurn:
    """The events of one running turn as item events; ``apply`` is applyNeyviaChatStreamEvents.

    Items carry the ids and slots ``turn_items`` gives the saved turn, so a client that reads the
    session after the turn ends replaces its live rows instead of duplicating them.
    """

    def __init__(self, session_id: str, turn_id: str, ordinal: int):
        self.session_id, self.turn_id, self.ordinal = session_id, turn_id, ordinal
        self.items: dict[str, Item] = {}
        self.context: ContextUsage | None = None
        self._slot = 0
        self._identity = ""
        self._answer = False
        self._last_reasoning: dict[str, Any] | None = None
        self._calls: dict[str, dict[str, Any]] = {}
        self._call_count = 0
        self._started: dict[str, float] = {}
        self._compaction: Item | None = None
        self._notices = 0

    def _event(self, kind: str, item: Item) -> dict[str, Any]:
        return {"type": kind, "sessionId": self.session_id, "item": item.public()}

    def _delta(self, item_id: str, text: str) -> dict[str, Any]:
        return {"type": "item.delta", "sessionId": self.session_id, "itemId": item_id, "textDelta": text}

    def _next_slot(self) -> int | None:
        if self._slot >= TEXT_SLOT:
            return None
        self._slot += 1
        return self._slot - 1

    def _add(self, out: list[dict[str, Any]], key: str, kind: str, data: dict[str, Any], at: Any) -> Item | None:
        slot = self._next_slot()
        if slot is None:
            return None
        item = Item(id=f"{self.turn_id}#{key}", seq=seq_for(self.ordinal, slot), kind=kind, at=_iso(at), data=data)
        self.items[item.id] = item
        out.append(self._event("item.added", item))
        return item

    @_native_proofs.live_contract
    def apply(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, dict):
                continue
            kind, message = str(event.get("kind") or ""), str(event.get("message") or "")
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            if kind == "runtime.answer_start":
                identity = json.dumps([data.get("responseId"), data.get("itemId"), data.get("outputIndex")])
                if identity != self._identity:
                    self._identity = identity
                    answer = self.items.get(self.turn_id)
                    if answer is not None and answer.data["text"]:
                        answer.data["text"] = ""
                        out.append(self._event("item.updated", answer))
            elif kind == "runtime.answer_delta" and message:
                answer = self.items.get(self.turn_id)
                if answer is None:
                    answer = Item(id=self.turn_id, seq=seq_for(self.ordinal, TEXT_SLOT), kind="assistant", at=_iso(event.get("at")),
                                  data={"text": message, "attachments": []})
                    self.items[self.turn_id] = answer
                    out.append(self._event("item.added", answer))
                else:
                    answer.data["text"] += message
                    out.append(self._delta(self.turn_id, message))
            elif kind == "runtime.reasoning_summary_delta" and message:
                self._reasoning(out, message, "reasoning_summary", "", event.get("at"))
            elif kind == "runtime.thinking_delta" and data.get("source") == _PROVIDER_REASONING and message:
                identity = json.dumps([data.get("responseId"), data.get("itemId"), data.get("outputIndex")])
                self._reasoning(out, message, "thinking_text", identity, event.get("at"))
            elif kind == "runtime.tool":
                self._tool(out, event, data, message)
            elif kind == "runtime.stream_error":
                self._notices += 1
                text = message or "The provider stream ended before the reply completed."
                self._add(out, f"notice-{self._notices}", "notice", {"text": text[:1000], "level": "error"}, event.get("at"))
            elif kind == "runtime.progress":
                self._progress(out, event, data, message)
        return out

    def _reasoning(self, out: list[dict[str, Any]], text: str, kind: str, identity: str, at: Any) -> None:
        last = self._last_reasoning
        if last is not None and last["kind"] == kind and (kind == "reasoning_summary" or last["identity"] == identity):
            item = self.items[last["id"]]
            piece = text[:max(0, TEXT_LIMIT - len(item.data["summary"]))]
            if piece:
                item.data["summary"] += piece
                out.append(self._delta(item.id, piece))
            return
        number = sum(1 for item in self.items.values() if item.kind == "reasoning") + 1
        item = self._add(out, f"reasoning-{number}", "reasoning", {"summary": text[:TEXT_LIMIT], "hidden": False}, at)
        self._last_reasoning = {"id": item.id, "kind": kind, "identity": identity} if item else None

    def _tool(self, out: list[dict[str, Any]], event: dict[str, Any], data: dict[str, Any], message: str) -> None:
        event_type = str(data.get("eventType") or "")
        status = str(data.get("toolStatus") or data.get("status") or ("completed" if re.search("output", event_type, re.I) else "started")).lower()
        supplied = str(data.get("callId") or data.get("itemId") or event.get("itemId") or "")
        row = normalize_tool_call({**event, "data": {**data, "tool": str(data.get("tool") or message or "tool"), "status": status}}, 0)
        if supplied:
            row["id"] = supplied
        else:
            self._call_count += 1
            row["id"] = f"tool-call-{self._call_count}"
        self._last_reasoning = None
        previous = self._calls.get(row["id"])
        call = {**previous, **{key: value for key, value in row.items() if value not in ("", None)}} if previous else row
        call["status"] = "failed" if call.get("error") else (row["status"] if row["status"] in _OK | _FAILED | {"running"} else "started")
        self._calls[row["id"]] = call
        at = event.get("at")
        started = self._started.setdefault(row["id"], at if isinstance(at, (int, float)) else 0.0)
        finished_now = call["status"] in _OK | _FAILED
        duration = int((at - started) * 1000) if finished_now and isinstance(at, (int, float)) and started else None
        item_id = f"{self.turn_id}#tool-{row['id']}"
        existing = self.items.get(item_id)
        if existing is None:
            slot = self._next_slot()
            if slot is None:
                return
            item = tool_item(call, item_id, seq_for(self.ordinal, slot), _iso(at), finished=False)
            self.items[item_id] = item
            out.append(self._event("item.added", item))
        else:
            item = tool_item(call, item_id, existing.seq, existing.at, finished=False, duration_ms=duration)
            self.items[item_id] = item
            out.append(self._event("item.updated", item))

    def _progress(self, out: list[dict[str, Any]], event: dict[str, Any], data: dict[str, Any], message: str) -> None:
        event_type = str(data.get("eventType") or "")
        if event_type == "model.usage" and isinstance(data.get("usage"), dict):
            out.append({"type": "usage.updated", "sessionId": self.session_id, "usage": data["usage"]})
            return
        if event_type == "context.compaction.started" and self._compaction is None:
            self._compaction = self._add(out, f"compaction-{len(self.items) + 1}", "compaction",
                                         {"state": "started", "beforeTokens": None, "afterTokens": None, "text": message[:300]}, event.get("at"))
            policy = data.get("policy") if isinstance(data.get("policy"), dict) else {}
            window, trigger = policy.get("contextTokens"), policy.get("triggerTokens")
            if isinstance(window, int) and not isinstance(window, bool) and window > 0:
                # The compaction policy is the only place a Native run records its context window.
                self.context = ContextUsage(window_tokens=window, auto_compact_tokens=trigger if isinstance(trigger, int) else None,
                                            source="neyvia-compaction-policy", updated_at=_iso(event.get("at")))
                out.append({"type": "context.updated", "sessionId": self.session_id, "context": asdict(self.context)})
        elif event_type == "context.usage" and isinstance(data.get("inputTokens"), int):
            window, trigger = data.get("contextTokens"), data.get("triggerTokens")
            self.context = ContextUsage(
                used_tokens=data["inputTokens"],
                window_tokens=window if isinstance(window, int) and not isinstance(window, bool) and window > 0 else None,
                auto_compact_tokens=trigger if isinstance(trigger, int) and not isinstance(trigger, bool) and trigger > 0 else None,
                source="provider-usage", updated_at=_iso(event.get("at")))
            out.append({"type": "context.updated", "sessionId": self.session_id, "context": asdict(self.context)})
        elif event_type == "context.compaction.completed" and self._compaction is not None:
            self._compaction.data.update(state="completed", text=message[:300] or self._compaction.data["text"])
            out.append(self._event("item.updated", self._compaction))
            self._compaction = None
