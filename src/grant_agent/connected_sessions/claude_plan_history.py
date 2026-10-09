"""Selective historical checklist scan; ordinary transcript text is never JSON-decoded here."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .claude_items import apply_tool_result
from .model import Item
from .plan import plan_op

_PLAN_NAME = re.compile(br'"name"\s*:\s*"(?:TodoWrite|TaskCreate|TaskUpdate)"')
_RESULT_ID = re.compile(br'"tool_use_id"\s*:\s*"([^"\\]+)"')


def apply_plan_result(item: Item, record: dict) -> None:
    """Apply only matching results, preserving TaskCreate IDs and refused/failed operations."""
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id") == item.id:
            apply_tool_result(item.data, text="", is_error=bool(block.get("is_error")), structured=record.get("toolUseResult"))


def read_plan_history(path: Path, end: int, seq_shift: int) -> list[Item]:
    """Read complete lines before the tail; retain only small plan operations and their real IDs.

    This runs once per tail boundary. Results need their own filter: looking for tool names alone
    would lose task IDs and incorrectly accept failed TodoWrite/TaskUpdate calls.
    """
    items: list[Item] = []
    by_id: dict[str, Item] = {}
    with path.open("rb") as handle:
        while (offset := handle.tell()) < end:
            line = handle.readline(end - offset)
            call = _PLAN_NAME.search(line)
            result_ids = [match.group(1).decode("utf-8", errors="replace") for match in _RESULT_ID.finditer(line)]
            if not call and not any(ident in by_id for ident in result_ids):
                continue
            try:
                record = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict) or record.get("isSidechain"):
                continue
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if record.get("type") == "assistant" and isinstance(content, list):
                for position, block in enumerate(content):
                    if not isinstance(block, dict) or block.get("type") != "tool_use" or not block.get("id"):
                        continue
                    op = plan_op(block.get("name"), block.get("input"))
                    if op is not None:
                        item = Item(str(block["id"]), (offset << seq_shift) | min(position, 63), "tool",
                                    record.get("timestamp"), {"plan": op, "status": "running"})
                        items.append(item)
                        by_id[item.id] = item
            elif record.get("type") == "user":
                for ident in result_ids:
                    if ident in by_id:
                        apply_plan_result(by_id[ident], record)
    return items
