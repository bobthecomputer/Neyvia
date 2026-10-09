"""Bound model replay without deleting durable session history or splitting tools."""
from __future__ import annotations

import json


def bounded_history(items, *, character_budget=240_000, item_budget=400):
    if not isinstance(items, list):
        return items, 0
    sizes = [len(json.dumps(item, ensure_ascii=False)) for item in items]
    if sum(sizes) <= character_budget and len(items) <= item_budget:
        return items, 0
    # A user message begins a complete exchange. Never start replay in the
    # middle of a tool call/result pair, and never remove the current request.
    starts = [i for i, item in enumerate(items)
              if isinstance(item, dict) and item.get("role") == "user"]
    if not starts:
        return items, 0
    start = starts[-1]
    size = sum(sizes[start:])
    for earlier in reversed(starts[:-1]):
        added = sum(sizes[earlier:start])
        if size + added > character_budget or len(items) - earlier > item_budget:
            break
        start, size = earlier, size + added
    if not start:
        return items, 0
    notice = {"role": "user", "content": (
        f"[Neyvia session continuity: {start} earlier history records are omitted "
        "from this model request to stay within its context window. They remain "
        "saved in the session database and conversation history. The following "
        "are the most recent complete exchanges. Do not assume omitted work "
        "was not done; inspect saved action receipts before repeating actions.]"
    )}
    return [notice, *items[start:]], start
