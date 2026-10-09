"""Shared transparency vocabulary; only text actually exposed by a harness is shown."""
from __future__ import annotations

import json
from typing import Any

PAYLOAD_LIMIT = 256 * 1024
LABELS = {"codex": "Codex", "claude-code": "Claude Code", "opencode": "OpenCode"}


def bounded_text(value: Any, limit: int = PAYLOAD_LIMIT) -> tuple[str, bool]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n[… {len(text) - limit} characters omitted]", True


def reasoning_data(provider: str, text: str | None, *, source: str, exposure: str = "thinking",
                   pending: bool = False, withheld: bool = False) -> dict[str, Any]:
    summary, truncated = bounded_text(text or "")
    shared = bool(summary.strip())
    label = LABELS.get(provider, provider)
    return {"summary": summary or None, "hidden": not shared and not pending,
            "provider": provider, "source": source,
            "exposure": exposure if shared else "pending" if pending else "withheld" if withheld else "not_reported",
            "notice": None if shared or pending else (
                f"{label} withheld its reasoning for this step." if withheld else
                f"{label} didn't share its reasoning for this step."), "truncated": truncated}


def normalize_item(provider: str, kind: str, data: dict[str, Any]) -> None:
    """Add provider/availability fields without guessing missing measurements."""
    data.setdefault("provider", provider)
    if kind == "reasoning":
        if data.get("summary"):
            data["hidden"] = False
            data.setdefault("exposure", "summary" if provider == "codex" else "thinking")
            data["notice"] = None
        elif data.get("hidden"):
            data.setdefault("exposure", "not_reported")
            data.setdefault("notice", f"{LABELS.get(provider, provider)} didn't share its reasoning for this step.")
    elif kind == "tool":
        for key in ("exitCode", "durationMs"):
            data.setdefault(key, None)
        for field in ("input", "args", "command", "output"):
            if isinstance(data.get(field), str):
                data[field], truncated = bounded_text(data[field])
                if truncated:
                    data[field + "Truncated"] = True
