"""Bounded, authenticated chat event polling shared by web and desktop bridges."""

from __future__ import annotations

import json
import re
import time
from collections import deque
from pathlib import Path
from typing import Any
from .proofs_e_chat import check_read_snapshot, check_tool_display


_SAFE_TURN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_READ_BYTES = 128 * 1024
_MAX_EVENT_LINE_BYTES = 96 * 1024
_MAX_MESSAGE_CHARS_PER_EVENT = 4_000
_MAX_DATA_BYTES = 24 * 1024
_MAX_TOOL_DETAIL_CHARS = 12_000
_INLINE_MEDIA = re.compile(r"data:((?:image|audio|video)/[A-Za-z0-9.+-]+);base64,[A-Za-z0-9+/=\r\n]+", re.IGNORECASE)
_SENSITIVE_TOOL_KEY = re.compile(
    r"password|secret|credential|authorization|cookie|api.?key|access.?token|refresh.?token|private.?key",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = (
    re.compile(
        r"(?i)(\b(?:api[-_ ]?key|authorization|credential|password|private[-_ ]?key|secret|token|cookie)\b\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
    ),
    re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)


def _safe_tool_value(value: Any, depth: int = 0) -> Any:
    """Return bounded JSON-safe tool data with credential fields removed."""
    if depth > 8:
        return "[depth limit]"
    if isinstance(value, dict):
        return {
            str(key)[:160]: ("[REDACTED]" if _SENSITIVE_TOOL_KEY.search(str(key))
                             else _safe_tool_value(item, depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_tool_value(item, depth + 1) for item in value[:200]]
    if isinstance(value, str):
        # Keep the real media in the model/tool transport; the activity drawer
        # needs a readable receipt, not thousands of encoded image characters.
        safe = _INLINE_MEDIA.sub(lambda match: f"[{match.group(1)} payload omitted from activity]", value)
        for pattern in _SENSITIVE_TEXT:
            if pattern.groups:
                safe = pattern.sub(r"\1[REDACTED]", safe)
            else:
                safe = pattern.sub("[REDACTED PRIVATE KEY]", safe)
        return safe
    if value is None or isinstance(value, (bool, int, float)):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _safe_tool_value(model_dump(exclude_unset=True), depth + 1)
        except Exception:
            return "[unavailable]"
    return str(value)[:_MAX_TOOL_DETAIL_CHARS]


def safe_tool_display(value: Any, limit: int = _MAX_TOOL_DETAIL_CHARS) -> str:
    """Format a tool input/output for the UI without persisting secret fields."""
    original = value
    if value is None:
        return check_tool_display(original, limit, "")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            value = parsed
    safe = _safe_tool_value(value)
    if isinstance(safe, str):
        rendered = safe
    else:
        rendered = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    rendered = rendered[:max(0, limit)]
    was_truncated = len(rendered) < len(safe) if isinstance(safe, str) else len(
        json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    ) > max(0, limit)
    # Stream frames serialize metadata with ensure_ascii=True. Bound the escaped
    # representation too, so worst-case Unicode cannot consume its 24 KiB budget.
    while rendered and len(json.dumps(rendered, ensure_ascii=True).encode("ascii")) > 9_000:
        rendered = rendered[: max(1, len(rendered) * 3 // 4)]
        was_truncated = True
    if was_truncated:
        rendered = rendered.rstrip() + "… [truncated]"
    return check_tool_display(original, limit, rendered)


def _path(root: Path, turn_id: object) -> Path | None:
    value = str(turn_id or "").strip()
    if not _SAFE_TURN_ID.fullmatch(value):
        return None
    return root / ".agent_control" / "chat_streams" / f"{value}.jsonl"


def begin_chat_stream(root: Path, turn_id: object) -> bool:
    path = _path(root, turn_id)
    if path is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return True


def append_chat_stream(root: Path, turn_id: object, event: dict[str, Any]) -> None:
    path = _path(root, turn_id)
    if path is None or not path.parent.exists():
        return
    from .harness_jobs import _exclusive_job_lock
    # Windows append handles can race the EOF seek and overwrite another
    # producer's buffered frames. Keep every event batch and its close/flush
    # under the same crash-safe target lease, including the existence check.
    with _exclusive_job_lock(path, timeout_seconds=120):
        if not path.exists():
            return
        _append_chat_stream_locked(path, event)


def _append_chat_stream_locked(path: Path, event: dict[str, Any]) -> None:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    data_json = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    if len(data_json.encode("utf-8")) > _MAX_DATA_BYTES:
        data = {"truncated": True}
    message = str(event.get("message") or "")
    kind = str(event.get("kind") or "runtime.progress")[:80]
    status = str(event.get("status") or "")[:40]
    chunks = [message[index:index + _MAX_MESSAGE_CHARS_PER_EVENT]
              for index in range(0, len(message), _MAX_MESSAGE_CHARS_PER_EVENT)] or [""]
    # Wall-clock time lets a turn be attributed afterwards: time to first
    # token, model time per round, and the gaps between tool calls. A merged
    # delta keeps the time its first piece arrived.
    stamp = event.get("at")
    at = round(stamp if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) else time.time(), 3)
    rows = [
        {"kind": kind, "message": chunk, "status": status, "data": data, "at": at}
        for chunk in chunks
    ]
    from .proofs_a_control import check_stream_frames
    check_stream_frames(event, rows)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            encoded = json.dumps(row, ensure_ascii=True, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > _MAX_EVENT_LINE_BYTES:
                raise ValueError("Chat stream event exceeded the bounded frame size.")
            stream.write(encoded + "\n")


_MERGEABLE_KINDS = frozenset({"runtime.answer_delta", "runtime.reasoning_summary_delta", "runtime.thinking_delta"})
# Readers poll every 250 ms, so holding text for at most 100 ms is invisible to
# them. Providers send one or two words per delta; written one per line, a long
# reasoning summary became ~30k appends (~0.9 ms each on Windows) per turn.
COALESCE_SECONDS = 0.1


class StreamCoalescer:
    """Merge consecutive text deltas of one kind before they reach ``sink``.

    Any other event first flushes the pending text, so order is preserved.
    Callers flush when ``due()`` reaches zero and once more when the run ends.
    """

    def __init__(self, sink, window: float = COALESCE_SECONDS, clock=time.monotonic) -> None:
        self._sink, self._window, self._clock = sink, window, clock
        self._pending: dict[str, Any] | None = None
        self._started = 0.0
        self._source_events = deque()

    def _emit(self, event):
        from .proofs_a_control import check_stream_emission
        check_stream_emission(self._source_events, event)
        self._sink(event)

    def push(self, event: dict[str, Any]) -> None:
        self._source_events.append(dict(event))
        kind, message = event.get("kind"), event.get("message")
        pending = self._pending
        if (pending is not None and kind == pending["kind"] and isinstance(message, str)
                and event.get("data") == pending.get("data")
                and len(pending["message"]) + len(message) <= _MAX_MESSAGE_CHARS_PER_EVENT
                and self._clock() - self._started < self._window):
            pending["message"] += message
            return
        self.flush()
        if kind in _MERGEABLE_KINDS and isinstance(message, str):
            self._pending = {**event, "at": event.get("at", time.time())}
            self._started = self._clock()
        else:
            self._emit(event)

    def due(self) -> float | None:
        """Seconds until the pending text must be written, or None when nothing waits."""
        if self._pending is None:
            return None
        return max(0.0, self._window - (self._clock() - self._started))

    def flush_due(self) -> None:
        if self._pending is not None and self.due() == 0.0:
            self.flush()

    def flush(self) -> None:
        pending, self._pending = self._pending, None
        if pending is not None:
            self._emit(pending)


def last_stream_event(root: Path, turn_id: object, event_type: str, tail_bytes: int = 256 * 1024) -> dict[str, Any] | None:
    """The newest event whose ``data.eventType`` matches, scanning back from the end of the stream.

    Reading from the start would see only a long turn's first rounds.
    """
    path = _path(root, turn_id)
    if path is None or not path.exists():
        return None
    needle = json.dumps(event_type).encode("ascii")
    with path.open("rb") as stream:
        end = stream.seek(0, 2)
        carry = b""
        while end > 0:
            start = max(0, end - tail_bytes)
            stream.seek(start)
            block = stream.read(end - start) + carry
            lines = block.split(b"\n")
            # The first piece may be a partial line unless the block starts the file.
            carry, lines = (b"", lines) if start == 0 else (lines[0], lines[1:])
            for raw in reversed(lines):
                if needle not in raw:
                    continue
                try:
                    event = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    continue
                data = event.get("data") if isinstance(event, dict) else None
                if isinstance(data, dict) and data.get("eventType") == event_type:
                    return event
            end = start
    return None


def read_chat_stream(root: Path, turn_id: object, cursor: object = 0) -> dict[str, Any]:
    path = _path(root, turn_id)
    if path is None:
        raise ValueError("Invalid chat turn id.")
    if not path.exists():
        return check_read_snapshot(turn_id, 0, b"", {"events": [], "cursor": 0, "ready": False}, ready=False)
    try:
        offset = max(0, int(cursor or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid chat stream cursor.") from exc
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        if offset > size:
            offset = 0
        stream.seek(offset)
        chunk = stream.read(_MAX_READ_BYTES)
    complete = chunk.rfind(b"\n")
    if complete < 0:
        return check_read_snapshot(turn_id, offset, chunk, {"events": [], "cursor": offset, "ready": True})
    rows = []
    for raw in chunk[:complete + 1].splitlines():
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(event, dict):
            rows.append(event)
    return check_read_snapshot(turn_id, offset, chunk, {"events": rows, "cursor": offset + complete + 1, "ready": True})
