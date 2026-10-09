"""Bring what a runtime produced back into the session that opened it.

An inline runtime — a CLI, a coding agent — returns messages, artifacts,
receipts and file changes into its own record. Without a hand-back those results
die in that window: you close the CLI and the main conversation has no idea what
just happened, so the next thing you say has to re-explain work that was already
done three feet away.

Hand-back is deliberately *not* a merge. Two rules shape it:

* **Provenance survives.** Everything carried across is tagged with the runtime
  and invocation it came from. A message that originated in Claude Code must
  never read as though Neyvia said it — the reader needs to know which system
  made the claim in order to judge it.
* **Nothing is invented.** A runtime that returned no messages hands back no
  messages. The summary says what was actually produced, and says "no output"
  when that is the truth, rather than manufacturing a completion line.

Hand-back is also idempotent: handing the same invocation back twice does not
duplicate its content, because a runtime can be returned from more than once as
it is suspended and resumed.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

#: Kinds of returned content, in the order a reader wants them.
CARRIED_KINDS = ("messages", "changes", "artifacts", "receipts")


def _digest(value: Any) -> str:
    """Content hash used to avoid handing the same item back twice."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _as_list(value: Any) -> list[Any]:
    return [item for item in value if item is not None] if isinstance(value, list) else []


def summarize_returns(returns: dict[str, Any]) -> dict[str, Any]:
    """Count what a runtime actually produced, without embellishment."""
    counts = {kind: len(_as_list((returns or {}).get(kind))) for kind in CARRIED_KINDS}
    produced = sum(counts.values())
    return {
        "counts": counts,
        "produced": produced,
        # Said plainly, because "the runtime ran and returned nothing" is a real
        # and important outcome that a cheerful summary would hide.
        "empty": produced == 0,
    }


def describe_handback(runtime: str, summary: dict[str, Any]) -> str:
    """One line a person can read, derived only from what is there."""
    name = str(runtime or "The runtime").strip() or "The runtime"
    if summary["empty"]:
        return f"{name} returned no output."

    counts = summary["counts"]
    parts: list[str] = []
    if counts["messages"]:
        parts.append(f"{counts['messages']} message{'' if counts['messages'] == 1 else 's'}")
    if counts["changes"]:
        parts.append(f"{counts['changes']} file change{'' if counts['changes'] == 1 else 's'}")
    if counts["artifacts"]:
        parts.append(f"{counts['artifacts']} artifact{'' if counts['artifacts'] == 1 else 's'}")
    if counts["receipts"]:
        parts.append(f"{counts['receipts']} receipt{'' if counts['receipts'] == 1 else 's'}")

    if len(parts) > 1:
        listed = ", ".join(parts[:-1]) + f" and {parts[-1]}"
    else:
        listed = parts[0]
    return f"{name} returned {listed}."


def build_handback(
    invocation: dict[str, Any],
    *,
    already_carried: set[str] | None = None,
) -> dict[str, Any]:
    """Build the payload that moves a runtime's results into its parent session.

    ``already_carried`` holds digests handed back previously; pass the value from
    a prior call to keep repeated hand-backs idempotent.
    """
    if not isinstance(invocation, dict):
        raise TypeError("An invocation record is required.")

    invocation_id = str(invocation.get("invocationId") or "").strip()
    if not invocation_id:
        raise ValueError("The invocation has no identity, so its output cannot be attributed.")

    runtime = str(invocation.get("runtime") or "").strip()
    parent_session = invocation.get("parentSessionId")
    returns = invocation.get("returns") or {}
    seen = set(already_carried or ())

    carried: dict[str, list[dict[str, Any]]] = {kind: [] for kind in CARRIED_KINDS}
    skipped = 0

    for kind in CARRIED_KINDS:
        for item in _as_list(returns.get(kind)):
            digest = _digest([invocation_id, kind, item])
            if digest in seen:
                skipped += 1
                continue
            seen.add(digest)
            carried[kind].append(
                {
                    "item": item,
                    "digest": digest,
                    # Provenance travels with every single item, not once at the
                    # top, because items get reordered and quoted separately.
                    "origin": {
                        "runtime": runtime or "unknown",
                        "invocationId": invocation_id,
                        "kind": kind,
                    },
                }
            )

    summary = summarize_returns(returns)
    carried_total = sum(len(rows) for rows in carried.values())

    return {
        "schema": "neyvia.runtime.handback/1",
        "invocationId": invocation_id,
        "runtime": runtime or "unknown",
        "parentSessionId": str(parent_session) if parent_session else None,
        "carried": carried,
        "carriedCount": carried_total,
        "skippedCount": skipped,
        "summary": describe_handback(runtime, summary),
        "empty": summary["empty"],
        # Nothing new to carry is a normal outcome on a repeat hand-back, and is
        # distinct from the runtime having produced nothing at all.
        "nothingNew": carried_total == 0 and not summary["empty"],
        "counts": summary["counts"],
        "handedBackAt": time.time(),
        "digests": sorted(seen),
    }


def handback_messages(handback: dict[str, Any]) -> list[dict[str, Any]]:
    """Transcript entries for the parent session.

    Each entry keeps the runtime's name as its author, so the parent transcript
    shows who actually spoke rather than absorbing the text as Neyvia's own.
    """
    runtime = handback.get("runtime") or "runtime"
    rows: list[dict[str, Any]] = []
    for row in handback.get("carried", {}).get("messages", []):
        item = row["item"]
        if isinstance(item, dict):
            content = (
                item.get("content")
                or item.get("text")
                or item.get("summary")
                or item.get("message")
            )
        else:
            content = item
        if not str(content or "").strip():
            continue
        original_role = (
            str(item.get("role") or "").strip().lower()
            if isinstance(item, dict)
            else ""
        )
        role = "user" if original_role in {"user", "operator"} else "assistant"
        rows.append(
            {
                "role": role,
                "author": "You" if role == "user" else runtime,
                "content": content,
                "source": "runtime-handback",
                "origin": row["origin"],
                "digest": row["digest"],
            }
        )
    return rows


# Contracts apply equally to direct, CLI and tool callers.
from .proofs_d_runtime import checked as _checked
build_handback = _checked("d.runtime.handback.identity", build_handback)
handback_messages = _checked("d.runtime.handback.transcript", handback_messages)
