"""Per-action stream claims, independent of display and cursor implementations."""
from __future__ import annotations
import json
import re


class ChatContractViolation(ValueError):
    pass


def check_read_snapshot(turn_id, offset, chunk, result, *, ready=True):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", str(turn_id or "").strip()):
        raise ChatContractViolation("proofs-e.chat.desktop-stream")
    rows = []
    cut = chunk.rfind(b"\n")
    if cut >= 0:
        for row in chunk[:cut + 1].splitlines():
            try:
                parsed = json.loads(row)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
    expected = {"events": rows, "cursor": offset + cut + 1 if cut >= 0 else offset, "ready": ready}
    if result != expected:
        raise ChatContractViolation("proofs-e.chat.desktop-stream")
    return result


_PRIVATE = re.compile(r"password|secret|credential|authorization|cookie|api.?key|access.?token|refresh.?token|private.?key", re.I)
_MEDIA = re.compile(r"data:((?:image|audio|video)/[A-Za-z0-9.+-]+);base64,[A-Za-z0-9+/=\r\n]+", re.I)
_TEXT = (
    re.compile(r"(?i)(\b(?:api[-_ ]?key|authorization|credential|password|private[-_ ]?key|secret|token|cookie)\b\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"),
    re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)


def display_claim(value, depth=0):
    if depth > 8:
        return "[depth limit]"
    if isinstance(value, dict):
        return {str(k)[:160]: "[REDACTED]" if _PRIVATE.search(str(k)) else display_claim(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [display_claim(v, depth + 1) for v in value[:200]]
    if isinstance(value, str):
        answer = _MEDIA.sub(lambda m: f"[{m[1]} payload omitted from activity]", value)
        for pattern in _TEXT:
            answer = pattern.sub(r"\1[REDACTED]" if pattern.groups else "[REDACTED PRIVATE KEY]", answer)
        return answer
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if callable(getattr(value, "model_dump", None)):
        try:
            return display_claim(value.model_dump(exclude_unset=True), depth + 1)
        except Exception:
            return "[unavailable]"
    return str(value)[:12000]


def check_tool_display(value, limit, result):
    if value is None:
        expected = ""
    else:
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                decoded = None
            if isinstance(decoded, (dict, list)):
                value = decoded
        safe = display_claim(value)
        complete = safe if isinstance(safe, str) else json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
        expected = complete[:max(0, limit)]
        truncated = len(expected) < len(complete)
        while expected and len(json.dumps(expected, ensure_ascii=True).encode("ascii")) > 9000:
            expected = expected[:max(1, len(expected) * 3 // 4)]
            truncated = True
        if truncated:
            expected = expected.rstrip() + "… [truncated]"
    if result != expected:
        raise ChatContractViolation("proofs-e.chat.safe-display")
    return result
