"""The live stream's memory: a bounded ring of cursor-stamped events with blocking reads.

Every event gets a monotonic cursor and the host's device id. The ring keeps at most a number of
events and a number of bytes; a client whose cursor has left the ring (or is newer than the service,
because the service restarted) is told to ``resync`` instead of being handed a gap. Nothing here
knows about sessions or runs, so the SSE stream and the long-poll read it the same way.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any

from .registry import jsonable
from .. import proofs_a_sessions as _proofs


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _shrink(value: dict[str, Any], limit: int) -> bool:
    """Trim the largest strings in ``value`` until it serializes under ``limit`` bytes."""
    trimmed = False
    for _ in range(12):
        overflow = _size(value) - limit
        if overflow <= 0:
            break
        found: tuple[Any, Any, int] | None = None
        stack: list[Any] = [value]
        while stack:
            node = stack.pop()
            for key, child in (node.items() if isinstance(node, dict) else enumerate(node)):
                if isinstance(child, str) and (found is None or len(child) > found[2]):
                    found = (node, key, len(child))
                elif isinstance(child, (dict, list)):
                    stack.append(child)
        if found is None or found[2] <= 64:
            break
        node, key, length = found
        marker = "\n... [truncated]"
        node[key] = node[key][:max(0, length - overflow - len(marker) - 16)] + marker
        trimmed = True
    return trimmed


def bound_event(value: Any, limit: int) -> dict[str, Any]:
    """A JSON-safe copy of an event, with its largest strings cut so it fits ``limit`` bytes."""
    event = jsonable(value)
    if not isinstance(event, dict):
        raise ValueError("Adapter events must be objects")
    if _size(event) > limit:
        if _shrink(event, limit - 64):  # room for the "truncated" marker
            event["truncated"] = True
        if _size(event) > limit:
            event = {"type": str(event.get("type") or "notice"), "sessionId": event.get("sessionId"), "truncated": True}
    return event


class EventBuffer:
    def __init__(self, host_device_id: str, *, max_events: int = 5000, max_bytes: int = 24 * 1024 * 1024,
                 max_event_bytes: int = 64 * 1024, start_cursor: int | None = None):
        self.host_device_id = host_device_id
        self.max_events, self.max_bytes, self.max_event_bytes = max_events, max_bytes, max_event_bytes
        self._cond = threading.Condition(threading.RLock())
        self._ring: deque[tuple[int, dict[str, Any], int]] = deque()
        self._bytes = 0
        # Time-seeded so a cursor from before a restart is always older than the buffer.
        self._next = (int(time.time() * 1000) if start_cursor is None else start_cursor) + 1
        self._closed = False

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        stamped = bound_event(event, self.max_event_bytes - 128)  # room for the cursor and host id
        with self._cond:
            cursor = self._next
            self._next += 1
            stamped["cursor"], stamped["hostDeviceId"] = cursor, self.host_device_id
            size = _size(stamped)
            previous_bytes, removed_bytes = self._bytes, 0
            self._ring.append((cursor, stamped, size))
            self._bytes += size
            while len(self._ring) > self.max_events or self._bytes > self.max_bytes:
                removed = self._ring.popleft()[2]
                self._bytes -= removed
                removed_bytes += removed
            _proofs.check_event_publish(self, stamped, cursor, previous_bytes, removed_bytes)
            self._cond.notify_all()
        return stamped

    def head(self) -> int:
        with self._cond:
            return self._next - 1

    def _since(self, cursor: int | None) -> tuple[list[dict[str, Any]], int, bool]:
        head = self._next - 1
        oldest = self._ring[0][0] if self._ring else head + 1
        if cursor is None:
            result = ([], head, False)
            _proofs.check_event_buffer(self, cursor, result)
            return result  # a new subscriber hears only what happens from now on
        if cursor > head or cursor < oldest - 1:
            result = ([], head, True)
            _proofs.check_event_buffer(self, cursor, result)
            return result
        events: list[dict[str, Any]] = []
        for stamp, event, _ in reversed(self._ring):
            if stamp <= cursor:
                break
            events.append(event)
        events.reverse()
        result = (events, head, False)
        _proofs.check_event_buffer(self, cursor, result)
        return result

    def since(self, cursor: int | None) -> tuple[list[dict[str, Any]], int, bool]:
        """(events after ``cursor``, new cursor, resync). Resync when the cursor left the buffer."""
        with self._cond:
            return self._since(cursor)

    def wait(self, cursor: int | None, timeout: float) -> tuple[list[dict[str, Any]], int, bool]:
        """Like ``since`` but waits up to ``timeout`` seconds for something to deliver."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._cond:
            while True:
                events, head, resync = self._since(cursor)
                remaining = deadline - time.monotonic()
                if events or resync or cursor is None or remaining <= 0 or self._closed:
                    return events, head, resync
                self._cond.wait(remaining)

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Wake every waiter for good; readers return at once from now on."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()
