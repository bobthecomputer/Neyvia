"""Turn one thread's live app-server notifications into connected-session events.

A ``ThreadStream`` covers one thread. It assigns each live item the same
``seq`` a later paged read would (turn time plus position in the turn), keeps
the live state of the items so a client that joins mid-turn can be caught up,
and emits the events listed in ``model.py``. It never talks to the process.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable

from .codex_items import (
    OUTPUT_LIMIT, TEXT_LIMIT, clip, clip_tail, context_from_usage, iso_from_ms, iso_from_seconds,
    make_seq, map_thread_item, plan_item, turn_end_items,
)
from .model import ContextUsage, Item
from .transparency import reasoning_data

Emit = Callable[[dict[str, Any]], None]

MAX_EVENT_TEXT = 32_000
MAX_STREAMED_OUTPUT = 256_000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ThreadStream:
    def __init__(self, session_id: str, thread_id: str, emit: Emit, *, cwd: str | None = None,
                 on_context: Callable[[ContextUsage], None] | None = None,
                 auto_compact_tokens: Callable[[], int | None] | None = None,
                 ordinal_of_turn: Callable[[str], int] | None = None) -> None:
        self.session_id = session_id
        self.thread_id = thread_id
        self.emit = emit
        self.cwd = cwd
        self.items: dict[str, Item] = {}
        self._on_context = on_context
        self._auto_compact = auto_compact_tokens
        self._ordinal_of_turn = ordinal_of_turn
        self.turn_id: str | None = None
        self._key = 0
        self._next_index = 0
        self._indexes: dict[str, int] = {}
        self._parts: dict[str, dict[int, str]] = {}
        self._raw_output: dict[str, str] = {}
        self._streamed: dict[str, int] = {}
        self._compaction_seen = False
        self._compaction_before: int | None = None
        self._compaction_open: str | None = None
        self._after_compaction: int | None = None
        self._last_used: int | None = None
        self._notice_count = 0

    # -- turn boundaries ---------------------------------------------------

    def begin_turn(self, turn: dict[str, Any] | None = None, turn_id: str | None = None) -> None:
        turn = turn or {}
        new_id = str(turn.get("id") or turn_id or "")
        if new_id and new_id == self.turn_id:
            return
        self.turn_id = new_id or None
        # The turn's index from the start of the thread, so live seq equals the seq a later page gives it.
        self._key = self._ordinal_of_turn(new_id) if self._ordinal_of_turn else 0
        self._next_index = 0
        self._indexes.clear()
        self._parts.clear()
        self._raw_output.clear()
        self._streamed.clear()
        self._compaction_seen = False
        self._compaction_open = None
        self._after_compaction = None

    def end_turn(self, turn: dict[str, Any]) -> None:
        """Finish items still marked running and mark a turn that did not complete."""
        status = str(turn.get("status") or "completed")
        for item in list(self.items.values()):
            if item.kind == "tool" and item.data.get("status") == "running":
                item.data["status"] = "ok" if status == "completed" else "error"
                self._updated(item)
            elif item.kind == "compaction" and item.data.get("state") == "started":
                item.data["state"] = "completed" if status == "completed" else "failed"
                self._updated(item)
        finished = iso_from_seconds(turn.get("completedAt")) or now_iso()
        current = [self.items[identity] for identity in self._indexes if identity in self.items]
        if status == "completed" and not any(item.kind == "reasoning" for item in current):
            identity = f"reasoning-unreported:{self.turn_id}"
            self._added(Item(identity, self._seq(identity), "reasoning", finished,
                             reasoning_data("codex", None, source="app-server")))
        for marker in turn_end_items(turn, seq=self._seq(f"end:{self.turn_id}"), at=finished):
            self._added(marker)

    # -- item bookkeeping --------------------------------------------------

    def _index(self, item_id: str) -> int:
        if item_id not in self._indexes:
            self._indexes[item_id] = self._next_index
            self._next_index += 1
        return self._indexes[item_id]

    def _seq(self, item_id: str) -> int:
        # Thread-level events outside a turn (a goal being set) sort after the last turn.
        key = self._key if self.turn_id else (self._ordinal_of_turn("") if self._ordinal_of_turn else 0)
        return make_seq(key, self._index(item_id))

    def _added(self, item: Item) -> None:
        self.items[item.id] = item
        self.emit({"type": "item.added", "sessionId": self.session_id, "item": item.public()})

    def _updated(self, item: Item) -> None:
        self.items[item.id] = item
        self.emit({"type": "item.updated", "sessionId": self.session_id, "item": item.public()})

    def _delta(self, item_id: str, text: str) -> None:
        for start in range(0, len(text), MAX_EVENT_TEXT):
            self.emit({"type": "item.delta", "sessionId": self.session_id, "itemId": item_id,
                       "textDelta": text[start:start + MAX_EVENT_TEXT]})

    def _apply(self, mapped: list[Item]) -> None:
        for item in mapped:
            if item.id in self.items:
                item.at = self.items[item.id].at or item.at
                self._updated(item)
            else:
                self._added(item)

    def live_items(self) -> list[Item]:
        return sorted(self.items.values(), key=lambda item: item.seq)

    # -- pending requests --------------------------------------------------

    def add_request_item(self, pending: dict[str, Any]) -> Item:
        request_id = pending["requestId"]
        kind = "approval" if pending.get("kind") == "approval" else "question"
        data = {key: value for key, value in pending.items() if key not in ("kind", "method")}
        item = Item(f"{kind}:{request_id}", self._seq(f"{kind}:{request_id}"), kind, now_iso(), data)  # type: ignore[arg-type]
        self._added(item)
        return item

    def resolve_request_item(self, request_id: str, response: dict[str, Any]) -> None:
        for prefix in ("approval", "question"):
            item = self.items.get(f"{prefix}:{request_id}")
            if item is None:
                continue
            if prefix == "approval":
                item.data["decision"] = str(response.get("decision") or "deny")
            else:
                item.data["answers"] = dict(response.get("answers") or {})
                item.data["decision"] = str(response.get("decision") or "approve")
            self._updated(item)

    # -- notifications -----------------------------------------------------

    def handle(self, method: str, params: dict[str, Any]) -> None:
        handler = _HANDLERS.get(method)
        if handler is not None:
            handler(self, params)

    def _item_started(self, params: dict[str, Any]) -> None:
        raw = params.get("item") if isinstance(params.get("item"), dict) else {}
        if not raw.get("id"):
            return
        if self.turn_id is None:
            self.begin_turn(turn_id=str(params.get("turnId") or ""))
        item_id = str(raw["id"])
        at = iso_from_ms(params.get("startedAtMs")) or now_iso()
        if raw.get("type") == "contextCompaction":
            self._compaction_seen = True
            self._compaction_before = self._last_used
            self._compaction_open = item_id
            self._after_compaction = None
        mapped = map_thread_item(raw, seq=self._seq(item_id), at=at, cwd=self.cwd, phase="started")
        if raw.get("type") == "contextCompaction":
            for item in mapped:
                item.data["beforeTokens"] = self._compaction_before
        self._apply(mapped)

    def _item_completed(self, params: dict[str, Any]) -> None:
        raw = params.get("item") if isinstance(params.get("item"), dict) else {}
        if not raw.get("id"):
            return
        if self.turn_id is None:
            self.begin_turn(turn_id=str(params.get("turnId") or ""))
        item_id = str(raw["id"])
        at = iso_from_ms(params.get("completedAtMs")) or now_iso()
        mapped = map_thread_item(raw, seq=self._seq(item_id), at=at, cwd=self.cwd, phase="completed")
        if raw.get("type") == "contextCompaction":
            self._compaction_seen = True
            for item in mapped:
                item.data["beforeTokens"] = self._compaction_before
                # The new size may already have been reported while it ran, or arrive just after.
                item.data["afterTokens"] = self._after_compaction
            if self._after_compaction is not None:
                self._compaction_open = None
        self._apply(mapped)

    def _agent_delta(self, params: dict[str, Any]) -> None:
        item = self.items.get(str(params.get("itemId") or ""))
        delta = str(params.get("delta") or "")
        if item is None or not delta:
            return
        item.data["text"] = clip(str(item.data.get("text") or "") + delta, TEXT_LIMIT)
        self._delta(item.id, delta)

    def _reasoning_delta(self, params: dict[str, Any]) -> None:
        item = self.items.get(str(params.get("itemId") or ""))
        delta = str(params.get("delta") or "")
        if item is None or not delta:
            return
        index = int(params.get("summaryIndex") or 0)
        parts = self._parts.setdefault(item.id, {})
        prefix = "\n\n" if index > 0 and index not in parts and parts else ""
        parts[index] = parts.get(index, "") + delta
        summary = "\n\n".join(text for _, text in sorted(parts.items()))
        item.data["summary"] = "\n\n".join(text for text in (summary, item.data.get("content")) if text)
        item.data["hidden"] = False
        item.data.update(exposure="thinking" if item.data.get("content") else "summary", notice=None)
        if item.data.get("content"):
            item.data["reasoningSummary"] = summary
            self._updated(item)
        else:
            self._delta(item.id, prefix + delta)

    def _reasoning_text_delta(self, params: dict[str, Any]) -> None:
        item = self.items.get(str(params.get("itemId") or ""))
        delta = str(params.get("delta") or "")
        if item is None or not delta:
            return
        index = int(params.get("contentIndex") or 0)
        parts = self._parts.setdefault(item.id + ":content", {})
        parts[index] = parts.get(index, "") + delta
        item.data["content"] = "\n\n".join(text for _, text in sorted(parts.items()))
        summary = self._parts.get(item.id, {})
        item.data["reasoningSummary"] = "\n\n".join(text for _, text in sorted(summary.items()))
        item.data["summary"] = "\n\n".join(text for text in (item.data["reasoningSummary"], item.data["content"]) if text)
        item.data.update(hidden=False, exposure="thinking", notice=None)
        self._updated(item)

    def _output_delta(self, params: dict[str, Any]) -> None:
        item = self.items.get(str(params.get("itemId") or ""))
        delta = str(params.get("delta") or "")
        if item is None or not delta:
            return
        raw = (self._raw_output.get(item.id, "") + delta)[-4 * OUTPUT_LIMIT:]
        self._raw_output[item.id] = raw
        item.data["output"] = clip_tail(raw)
        streamed = self._streamed.get(item.id, 0)
        if streamed < MAX_STREAMED_OUTPUT:
            self._streamed[item.id] = streamed + len(delta)
            self._delta(item.id, delta)

    def _mcp_progress(self, params: dict[str, Any]) -> None:
        item = self.items.get(str(params.get("itemId") or ""))
        message = str(params.get("message") or "")
        if item is None or not message:
            return
        item.data["output"] = clip_tail(str(item.data.get("output") or "") + message + "\n")
        self._delta(item.id, message + "\n")

    def _patch_updated(self, params: dict[str, Any]) -> None:
        item_id = str(params.get("itemId") or "")
        if not item_id:
            return
        raw = {"type": "fileChange", "id": item_id, "changes": params.get("changes") or [], "status": "inProgress"}
        self._apply(map_thread_item(raw, seq=self._seq(item_id), at=now_iso(), cwd=self.cwd, phase="started"))

    def _plan_delta(self, params: dict[str, Any]) -> None:
        item = self.items.get(str(params.get("itemId") or ""))
        delta = str(params.get("delta") or "")
        if item is None or not delta:
            return
        item.data["text"] = clip(str(item.data.get("text") or "") + delta, TEXT_LIMIT)
        self._delta(item.id, delta)

    def _plan_updated(self, params: dict[str, Any]) -> None:
        turn_id = str(params.get("turnId") or self.turn_id or "")
        steps = [step for step in params.get("plan") or [] if isinstance(step, dict)]
        item = plan_item(turn_id, self._seq(f"plan:{turn_id}"), now_iso(), steps, params.get("explanation"))
        self._apply([item])

    def _token_usage(self, params: dict[str, Any]) -> None:
        usage = params.get("tokenUsage") if isinstance(params.get("tokenUsage"), dict) else {}
        from ..model_usage import counters
        total = counters(usage.get("total"))
        if total is not None:
            previous_turn = params.get("turnId") and params["turnId"] != self.turn_id
            self.emit({"type": "usage.baseline" if previous_turn else "usage.updated",
                       "sessionId": self.session_id, "threadTotal": total})
        auto = self._auto_compact() if self._auto_compact else None
        context = context_from_usage(usage, updated_at=now_iso(), auto_compact_tokens=auto)
        self._last_used = context.used_tokens
        if self._on_context:
            self._on_context(context)
        else:
            self.emit({"type": "context.updated", "sessionId": self.session_id, "context": asdict(context)})
        if self._compaction_open and context.used_tokens is not None:
            item = self.items.get(self._compaction_open)
            if item is not None and item.data.get("state") == "started":
                self._after_compaction = context.used_tokens
            elif item is not None and item.data.get("state") == "completed":
                item.data["afterTokens"] = context.used_tokens
                self._compaction_open = None
                self._updated(item)

    def _compacted(self, params: dict[str, Any]) -> None:
        # Deprecated notification; the contextCompaction item is the primary signal.
        if self._compaction_seen:
            return
        self._compaction_seen = True
        item = Item(f"compaction:{self.turn_id or params.get('turnId') or now_iso()}",
                    self._seq("compaction"), "compaction", now_iso(),
                    {"state": "completed", "beforeTokens": self._last_used, "afterTokens": None})
        self._added(item)

    def _goal_updated(self, params: dict[str, Any]) -> None:
        if (params.get("_neyvia") or {}).get("emit") is False:
            return
        goal = params.get("goal") if isinstance(params.get("goal"), dict) else {}
        status = str(goal.get("status") or "")
        state = "achieved" if status == "complete" else "set" if goal.get("createdAt") == goal.get("updatedAt") else "updated"
        self._added(Item(f"goal:{self.thread_id}:{goal.get('updatedAt') or now_iso()}", self._seq(f"goal:{goal.get('updatedAt')}"),
                         "goal", now_iso(), {"state": state, "text": str(goal.get("objective") or ""), "status": status,
                                             "tokenBudget": goal.get("tokenBudget"), "tokensUsed": goal.get("tokensUsed")}))

    def _goal_cleared(self, params: dict[str, Any]) -> None:
        if (params.get("_neyvia") or {}).get("emit") is False:
            return
        stamp = now_iso()
        self._added(Item(f"goal:{self.thread_id}:cleared:{stamp}", self._seq(f"goal:cleared:{stamp}"), "goal", stamp,
                         {"state": "cleared", "text": ""}))

    def _notice(self, text: str, level: str, marker: str) -> None:
        self._notice_count += 1
        item_id = f"notice:{self.turn_id or self.thread_id}:{marker}:{self._notice_count}"
        self._added(Item(item_id, self._seq(item_id), "notice", now_iso(), {"text": text[:600], "level": level}))

    def _error(self, params: dict[str, Any]) -> None:
        error = params.get("error") if isinstance(params.get("error"), dict) else {}
        message = " ".join(str(error.get("message") or "Codex reported an error.").split())
        if params.get("willRetry"):
            self._notice(f"Codex is retrying: {message}", "warning", "retry")
        else:
            self._notice(message, "error", "error")

    def _warning(self, params: dict[str, Any]) -> None:
        self._notice(" ".join(str(params.get("message") or "").split()), "warning", "warning")

    def _rerouted(self, params: dict[str, Any]) -> None:
        self._notice(f"Codex switched from {params.get('fromModel')} to {params.get('toModel')}.", "info", "reroute")


_HANDLERS: dict[str, Callable[[ThreadStream, dict[str, Any]], None]] = {
    "item/started": ThreadStream._item_started,
    "item/completed": ThreadStream._item_completed,
    "item/agentMessage/delta": ThreadStream._agent_delta,
    "item/reasoning/summaryTextDelta": ThreadStream._reasoning_delta,
    "item/reasoning/textDelta": ThreadStream._reasoning_text_delta,
    "item/commandExecution/outputDelta": ThreadStream._output_delta,
    "item/mcpToolCall/progress": ThreadStream._mcp_progress,
    "item/fileChange/patchUpdated": ThreadStream._patch_updated,
    "item/plan/delta": ThreadStream._plan_delta,
    "turn/plan/updated": ThreadStream._plan_updated,
    "thread/tokenUsage/updated": ThreadStream._token_usage,
    "thread/compacted": ThreadStream._compacted,
    "thread/goal/updated": ThreadStream._goal_updated,
    "thread/goal/cleared": ThreadStream._goal_cleared,
    "error": ThreadStream._error,
    "warning": ThreadStream._warning,
    "model/rerouted": ThreadStream._rerouted,
}
