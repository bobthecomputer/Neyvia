"""Persist a chat turn's runtime compartment as its own data plus a reference.

After every reply the backend builds a compartment for the session: the turn's
receipt, route and timeline, plus a window over the whole session (the last
40 messages and the last 20 turn receipts). Copying that window into every
persisted turn made storage grow with the square of the conversation length.

A stored turn now keeps only the messages it added (``history.messagesDelta``)
and its own ``turnReceipt``, and names the turn whose window it extended
(``history.baseTurnId``; empty when the window started empty). Reading a turn
rebuilds both windows by following those references until the windows are
full or a turn that stores a full window is reached.

A reference is written only after the base turn's rebuilt window has been
checked against the window this turn actually extended, so a rebuilt window
is always exactly the one the runtime returned. When that check cannot pass
(the session also ran outside this conversation, a base turn is missing) the
turn keeps its full window as a checkpoint. Turns stored before this format
keep their full window and read unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

MESSAGE_WINDOW = 40
RECEIPT_WINDOW = 20
HISTORY_SCHEMA = "neyvia.turn-compartment.history/1"
WINDOW_KEYS = ("messages", "turnReceipts")
_REFS_KEY = "$refs"

Loader = Callable[[str], "dict[str, Any] | None"]


def window_digest(messages: object, receipts: object) -> str:
    """Identify a session window independently of key order and JSON spacing."""
    canonical = json.dumps(
        [messages if isinstance(messages, list) else [], receipts if isinstance(receipts, list) else []],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


EMPTY_WINDOW_DIGEST = window_digest([], [])


def history_marker(
    *,
    turn_id: str,
    previous: dict[str, Any],
    previous_messages: list[Any],
    previous_receipts: list[Any],
    messages: list[Any],
    receipts: list[Any],
    appended_messages: int,
) -> dict[str, Any]:
    """Describe how this turn's window extends the session's previous one."""
    previous_history = previous.get("history") if isinstance(previous.get("history"), dict) else {}
    return {
        "schema": HISTORY_SCHEMA,
        "turnId": str(turn_id or ""),
        "previousTurnId": str(previous_history.get("turnId") or ""),
        "previousDigest": window_digest(previous_messages, previous_receipts),
        "digest": window_digest(messages, receipts),
        "appendedMessages": int(appended_messages),
    }


def has_full_window(compartment: object) -> bool:
    return isinstance(compartment, dict) and isinstance(compartment.get("messages"), list)


def is_delta(compartment: object) -> bool:
    """A stored compartment whose windows must be rebuilt from its base turns."""
    if not isinstance(compartment, dict) or has_full_window(compartment):
        return False
    history = compartment.get("history")
    return (
        isinstance(history, dict)
        and history.get("schema") == HISTORY_SCHEMA
        and "baseTurnId" in history
        and isinstance(history.get("messagesDelta"), list)
    )


def _strip_receipt_copies(message: object, receipt: object) -> object:
    """The assistant message repeats the turn receipt; keep a reference instead."""
    if not isinstance(message, dict) or not isinstance(receipt, dict):
        return message
    refs: list[str] = []
    stored = dict(message)
    if "turnReceipt" in stored and stored["turnReceipt"] == receipt:
        del stored["turnReceipt"]
        refs.append("turnReceipt")
    if "activitySegments" in stored and stored["activitySegments"] == receipt.get("activitySegments", []):
        del stored["activitySegments"]
        refs.append("activitySegments")
    if refs:
        stored[_REFS_KEY] = refs
    return stored


def _restore_receipt_copies(message: object, receipt: object) -> object:
    if not isinstance(message, dict) or _REFS_KEY not in message:
        return message
    restored = {key: value for key, value in message.items() if key != _REFS_KEY}
    receipt = receipt if isinstance(receipt, dict) else {}
    refs = message.get(_REFS_KEY) or []
    if "turnReceipt" in refs:
        restored["turnReceipt"] = receipt
    if "activitySegments" in refs:
        restored["activitySegments"] = receipt.get("activitySegments", [])
    return restored


def delta_messages(compartment: dict[str, Any]) -> list[Any]:
    """The messages this turn added, with their receipt copies restored."""
    history = compartment.get("history") or {}
    receipt = compartment.get("turnReceipt")
    return [_restore_receipt_copies(item, receipt) for item in history.get("messagesDelta") or []]


def without_window(compartment: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in compartment.items() if key not in WINDOW_KEYS}


def as_delta(compartment: dict[str, Any], *, base_turn_id: str, appended_messages: int) -> dict[str, Any]:
    """Replace the full windows with this turn's own messages and a base reference."""
    messages = compartment.get("messages") if isinstance(compartment.get("messages"), list) else []
    count = max(0, min(int(appended_messages), len(messages)))
    receipt = compartment.get("turnReceipt")
    history = compartment.get("history") if isinstance(compartment.get("history"), dict) else {}
    stored = without_window(compartment)
    stored["history"] = {
        **history,
        "schema": HISTORY_SCHEMA,
        "baseTurnId": str(base_turn_id or ""),
        "messagesDelta": [_strip_receipt_copies(item, receipt) for item in messages[len(messages) - count:]] if count else [],
    }
    return stored


def as_checkpoint(compartment: dict[str, Any], reason: str) -> dict[str, Any]:
    """Keep the full window: no verified base turn can rebuild it."""
    history = compartment.get("history") if isinstance(compartment.get("history"), dict) else {}
    return {**compartment, "history": {**history, "checkpoint": True, "checkpointReason": reason}}


def rebuild_window(compartment: dict[str, Any], load: Loader) -> tuple[list[Any], list[Any], bool]:
    """Return the (messages, receipts) windows after this turn and whether they are complete.

    ``load(turn_id)`` returns another stored turn's compartment, or ``None``
    when that turn no longer exists.
    """
    if has_full_window(compartment):
        receipts = compartment.get("turnReceipts")
        return list(compartment["messages"]), list(receipts) if isinstance(receipts, list) else [], True
    collected: list[tuple[list[Any], Any]] = []
    base_messages: list[Any] = []
    base_receipts: list[Any] = []
    complete = True
    message_count = 0
    current: dict[str, Any] | None = compartment
    own_history = compartment.get("history") if isinstance(compartment.get("history"), dict) else {}
    seen: set[str] = {str(own_history.get("turnId") or "")} - {""}
    while current is not None:
        if has_full_window(current):
            base_messages, base_receipts, _ = rebuild_window(current, load)
            break
        if not is_delta(current):
            complete = False
            break
        own = delta_messages(current)
        collected.append((own, current.get("turnReceipt")))
        message_count += len(own)
        if message_count >= MESSAGE_WINDOW and len(collected) >= RECEIPT_WINDOW:
            break  # both windows are full; older turns cannot change them
        base_id = str(current["history"].get("baseTurnId") or "")
        if not base_id:
            break  # the session's window started empty at this turn
        if base_id in seen:
            complete = False
            break
        seen.add(base_id)
        current = load(base_id)
        if current is None:
            complete = False
    messages = list(base_messages)
    receipts = list(base_receipts)
    for own, receipt in reversed(collected):
        messages.extend(own)
        receipts.append(receipt)
    return messages[-MESSAGE_WINDOW:], receipts[-RECEIPT_WINDOW:], complete


def hydrate(compartment: object, load: Loader) -> object:
    """Return the compartment as the runtime produced it, windows included."""
    if not is_delta(compartment):
        return compartment
    assert isinstance(compartment, dict)
    messages, receipts, complete = rebuild_window(compartment, load)
    hydrated = {**compartment, "messages": messages, "turnReceipts": receipts}
    if not complete:
        hydrated["history"] = {**compartment["history"], "windowIncomplete": True}
    return hydrated


def for_storage(compartment: object, candidates: list[str], load: Loader) -> object:
    """Choose the stored form of a freshly produced compartment.

    ``candidates`` are turn ids, most likely first, whose window this turn may
    have extended. The first one whose rebuilt window matches the window this
    turn extended becomes the base; the delta is then checked to reproduce this
    turn's own window exactly before anything is dropped.
    """
    if not has_full_window(compartment):
        return compartment
    assert isinstance(compartment, dict)
    history = compartment.get("history")
    if not isinstance(history, dict) or history.get("schema") != HISTORY_SCHEMA:
        return compartment  # produced by an older backend; keep it whole
    receipts = compartment.get("turnReceipts") if isinstance(compartment.get("turnReceipts"), list) else []
    if window_digest(compartment["messages"], receipts) != history.get("digest"):
        return as_checkpoint(compartment, "window_changed_after_digest")
    appended = int(history.get("appendedMessages") or 0)
    base_id: str | None = None
    base_messages: list[Any] = []
    base_receipts: list[Any] = []
    if history.get("previousDigest") == EMPTY_WINDOW_DIGEST:
        base_id = ""
    else:
        for candidate in dict.fromkeys(item for item in candidates if item and item != history.get("turnId")):
            stored = load(candidate)
            if stored is None:
                continue
            messages, candidate_receipts, complete = rebuild_window(stored, load)
            if complete and window_digest(messages, candidate_receipts) == history.get("previousDigest"):
                base_id, base_messages, base_receipts = candidate, messages, candidate_receipts
                break
    if base_id is None:
        return as_checkpoint(compartment, "no_verified_base_turn")
    stored_form = as_delta(compartment, base_turn_id=base_id, appended_messages=appended)
    rebuilt_messages = (base_messages + delta_messages(stored_form))[-MESSAGE_WINDOW:]
    rebuilt_receipts = (base_receipts + [stored_form.get("turnReceipt")])[-RECEIPT_WINDOW:]
    if window_digest(rebuilt_messages, rebuilt_receipts) != history.get("digest"):
        return as_checkpoint(compartment, "delta_does_not_reproduce_window")
    return stored_form


def legacy_as_delta(
    compartment: dict[str, Any],
    *,
    base_turn_id: str,
    base_messages: list[Any],
    base_receipts: list[Any],
) -> dict[str, Any] | None:
    """Convert a full-window turn written before this format, if a delta reproduces it exactly."""
    if not has_full_window(compartment):
        return None
    messages = compartment["messages"]
    receipts = compartment.get("turnReceipts") if isinstance(compartment.get("turnReceipts"), list) else []
    receipt = compartment.get("turnReceipt")
    if (base_receipts + [receipt])[-RECEIPT_WINDOW:] != receipts:
        return None
    for appended in range(0, min(len(messages), 4) + 1):
        own = messages[len(messages) - appended:] if appended else []
        if (base_messages + own)[-MESSAGE_WINDOW:] == messages:
            history = compartment.get("history") if isinstance(compartment.get("history"), dict) else {}
            converted = as_delta(
                {**compartment, "history": {**history, "digest": window_digest(messages, receipts),
                                            "appendedMessages": appended, "migratedFrom": "full_window"}},
                base_turn_id=base_turn_id,
                appended_messages=appended,
            )
            return converted
    return None
