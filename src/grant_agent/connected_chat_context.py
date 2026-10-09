"""Public context counters reported by the source app, never inferred from text."""
from __future__ import annotations


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def context_from_events(app: str, events: list[dict]) -> dict:
    context = {"usedTokens": None, "windowTokens": None,
               "compactionThresholdTokens": None, "source": app, "updatedAt": None}
    for event in events:
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if event.get("type") == "compacted" or payload.get("type") == "context_compacted" or event.get("subtype") == "compact_boundary":
            context.update(usedTokens=None, updatedAt=event.get("timestamp"))
            continue
        if app == "codex" and payload.get("type") == "token_count":
            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            usage = info.get("last_token_usage") or {}
            if not isinstance(usage, dict):
                continue
            used = _count(usage.get("total_tokens"))
            if used is None:
                used = _count(usage.get("input_tokens"))
            if used is not None:
                context.update(usedTokens=used,
                               windowTokens=_count(info.get("model_context_window")),
                               updatedAt=event.get("timestamp"))
        elif app == "claude-code" and event.get("type") == "assistant":
            message = event.get("message") or {}
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            # Cache reads and creation are input context, not extra output.
            names = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
            if _count(usage.get("input_tokens")) is not None:
                used = sum(_count(usage.get(name)) or 0 for name in names)
                context.update(usedTokens=used, windowTokens=None, updatedAt=event.get("timestamp"))
    return context
