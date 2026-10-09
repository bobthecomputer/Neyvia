"""Shared MCP catalog pagination and incoming notification dispatch."""

from __future__ import annotations

from collections import deque
import json
import re
import threading
from typing import Any, Callable


class NotificationDispatcher:
    """Keep a bounded observable history while delivering notifications immediately."""

    def __init__(self) -> None:
        self.handler: Callable[[dict[str, Any]], None] | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=128)
        self._lock = threading.Lock()

    def dispatch(self, message: dict[str, Any]) -> bool:
        if "id" in message or not isinstance(message.get("method"), str):
            return False
        event = {"method": message["method"], "params": message.get("params") or {}}
        with self._lock:
            self._events.append(event)
        if self.handler is not None:
            self.handler(event)
        return True

    def drain(self) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)
            self._events.clear()
            return events


def list_all_tools(request: Callable[..., Any]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    params: dict[str, Any] = {}
    seen: set[str] = set()
    while True:
        result = request("tools/list", params)
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise RuntimeError("MCP tools/list returned an invalid catalog")
        tools.extend(dict(tool) for tool in result["tools"] if isinstance(tool, dict))
        cursor = result.get("nextCursor")
        if cursor is None:
            return tools
        if not isinstance(cursor, str) or cursor in seen:
            raise RuntimeError("MCP tools/list returned an invalid or repeated cursor")
        seen.add(cursor)
        params = {"cursor": cursor}


class JsonRpcFrameDecoder:
    """Incremental framing supports both legacy Content-Length and standard JSONL."""

    def __init__(self, framing: str) -> None:
        if framing not in {"newline", "content_length"}:
            raise ValueError(f"unsupported stdio MCP framing: {framing}")
        self.framing = framing
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> list[dict[str, Any]]:
        self.buffer.extend(chunk)
        messages: list[dict[str, Any]] = []
        while True:
            if self.framing == "newline":
                end = self.buffer.find(b"\n")
                if end < 0:
                    break
                body = bytes(self.buffer[:end]).rstrip(b"\r")
                del self.buffer[:end + 1]
                if not body:
                    continue
            else:
                end = self.buffer.find(b"\r\n\r\n")
                if end < 0:
                    break
                header = bytes(self.buffer[:end]).decode("ascii", errors="replace")
                match = re.search(r"Content-Length:\s*(\d+)", header, re.IGNORECASE)
                if not match:
                    raise RuntimeError("stdio MCP missing Content-Length")
                length = int(match.group(1))
                start = end + 4
                if len(self.buffer) < start + length:
                    break
                body = bytes(self.buffer[start:start + length])
                del self.buffer[:start + length]
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("stdio MCP returned non-object JSON")
            messages.append(payload)
        return messages
