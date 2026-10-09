"""CL token measurements. Claude estimates are never reported as exact counts."""
from __future__ import annotations

from functools import lru_cache
from math import ceil
from typing import Any


@lru_cache(maxsize=1)
def _o200k():
    try:
        import tiktoken
    except ImportError as exc:
        raise RuntimeError("Exact o200k measurement requires the installed tiktoken package") from exc
    return tiktoken.get_encoding("o200k_base")


def count_tokens(text: str, tokenizer: str = "o200k") -> int:
    """Count text only, excluding provider message wrappers and hidden context.

    Claude's tokenizer is not publicly available locally. Its deliberately
    labelled estimate uses UTF-8 bytes / 3.5; provider usage is authoritative.
    """
    if tokenizer in {"o200k", "o200k_base"}:
        return len(_o200k().encode(text, disallowed_special=()))
    if tokenizer in {"claude", "claude_approx"}:
        return ceil(len(text.encode("utf-8")) / 3.5)
    raise ValueError(f"Unknown tokenizer: {tokenizer}")


def measure_tokens(text: str) -> dict[str, Any]:
    return {
        "characters": len(text),
        "utf8_bytes": len(text.encode("utf-8")),
        "o200k_tokens": count_tokens(text),
        "o200k_method": "tiktoken o200k_base; exact text encoding",
        "claude_approx_tokens": count_tokens(text, "claude_approx"),
        "claude_method": "approximation: ceil(UTF-8 bytes / 3.5); not a Claude tokenizer or billing count",
        "scope": "text only; excludes provider wrappers and hidden context",
    }
