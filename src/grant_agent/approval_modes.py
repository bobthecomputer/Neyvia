"""Approval modes for tool execution — the setting the product never had.

Today the only auto-approval in Neyvia is a watchdog in ``cli.py`` that approves
a pending action once it has waited long enough. That exists to stop a mission
hanging, and as a liveness mechanism it is reasonable. As the *only* path it is
not: it approves by timing out rather than by anyone deciding, which means the
difference between "the operator agreed" and "nobody was looking" is invisible
afterwards.

This module provides the decision the watchdog was standing in for.

Three modes, and the middle one is what makes the app usable day to day:

    ask     every call is confirmed
    safe    routine work runs; anything consequential still asks
    all     nothing asks — for the length of one session only

Two rules hold in every mode, including ``all``:

* **Some categories always ask.** Spending money, destroying data, sending on
  your behalf, and trusting a new MCP server are not things a blanket setting
  should be able to wave through. A mode that could disable them would make
  "approve everything" a footgun rather than a convenience.
* **Approval is bound to the action.** Grants carry the fingerprint of what was
  approved, so a yes cannot be replayed against something else.

``all`` is deliberately session-scoped and is never written to disk. A standing
"approve everything" preference that survives restarts is indistinguishable from
no permission system at all.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

MODE_ASK = "ask"
MODE_SAFE = "safe"
MODE_ALL = "all"

MODES = (MODE_ASK, MODE_SAFE, MODE_ALL)

MODE_LABELS = {
    MODE_ASK: "Ask every time",
    MODE_SAFE: "Auto-approve safe actions",
    MODE_ALL: "Approve everything this session",
}

#: Categories that ask in every mode. Naming them as data rather than burying
#: the checks makes the guarantee auditable, and makes it obvious when someone
#: proposes removing one.
ALWAYS_ASK = {
    "spend": "starts or continues something you are billed for",
    "destroy": "deletes or overwrites something that may not be recoverable",
    "send": "sends a message, email, or post on your behalf",
    "publish": "makes something publicly visible",
    "credential": "reads or changes stored credentials",
    "new_mcp_server": "is the first call to an MCP server this session",
}

#: Categories that are routine: reading, looking, computing locally.
ROUTINE = {
    "read": "reads a file, page, or record",
    "observe": "looks at the screen or a page",
    "search": "searches for information",
    "compute": "processes data without side effects",
    "navigate": "moves between pages or views",
}


class ApprovalRequired(RuntimeError):
    """Raised when an action needs approval it does not have."""

    def __init__(self, decision: "Decision") -> None:
        super().__init__(decision.reason)
        self.decision = decision


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    category: str
    mode: str
    fingerprint: str
    always_ask: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "category": self.category,
            "mode": self.mode,
            "fingerprint": self.fingerprint,
            "alwaysAsk": self.always_ask,
        }


def action_fingerprint(action: dict[str, Any]) -> str:
    """Stable identifier for one specific action, used to bind an approval."""
    payload = {
        key: action.get(key)
        for key in sorted(action)
        if key not in {"approval", "approvalToken"}
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


@dataclass
class SessionApprovals:
    """Per-session approval state. Deliberately in memory only.

    ``mode`` and ``trusted_servers`` both reset when the process restarts, which
    is the point: a blanket approval that outlives the session it was granted in
    is not a preference, it is the absence of a permission system.
    """

    mode: str = MODE_SAFE
    trusted_servers: set[str] = field(default_factory=set)
    granted: dict[str, dict[str, Any]] = field(default_factory=dict)

    def set_mode(self, mode: str) -> str:
        if mode not in MODES:
            raise ValueError(f"Unknown approval mode: {mode!r}. Expected one of {MODES}.")
        self.mode = mode
        return self.mode

    def trust_server(self, server: str) -> None:
        name = str(server or "").strip().lower()
        if name:
            self.trusted_servers.add(name)

    def grant(self, decision: "Decision", *, granted_by: str, note: str = "") -> dict[str, Any]:
        record = {
            "schema": "neyvia.approval.grant/1",
            "fingerprint": decision.fingerprint,
            "category": decision.category,
            "grantedBy": granted_by,
            "grantedAt": time.time(),
            "note": note,
        }
        self.granted[decision.fingerprint] = record
        return record

    def has_grant(self, fingerprint: str) -> bool:
        return fingerprint in self.granted


def categorize(action: dict[str, Any]) -> str:
    """Classify an action. Anything unrecognised is treated as consequential.

    Defaulting to "unknown" rather than "routine" is the safe direction: an
    unclassified action that turns out to be harmless costs one confirmation,
    while one that turns out to spend money costs money.
    """
    declared = str(action.get("category") or "").strip().lower()
    if declared in ALWAYS_ASK or declared in ROUTINE:
        return declared
    return "unknown"


def _evaluate(
    action: dict[str, Any],
    session: SessionApprovals,
    *,
    approval: dict[str, Any] | None = None,
) -> Decision:
    """Decide whether ``action`` may run now."""
    category = categorize(action)
    fingerprint = action_fingerprint(action)
    always = category in ALWAYS_ASK

    # A first call to an MCP server is always-ask regardless of its own
    # category, because trusting the server is the decision being made.
    server = str(action.get("mcpServer") or "").strip().lower()
    if server and server not in session.trusted_servers:
        always = True
        category = "new_mcp_server"

    granted = approval is not None and approval.get("fingerprint") == fingerprint
    if granted or session.has_grant(fingerprint):
        return Decision(True, "You approved this action.", category, session.mode, fingerprint, always)

    if always:
        return Decision(
            False,
            f"This needs your approval because it {ALWAYS_ASK.get(category, 'has effects Neyvia cannot classify')}.",
            category,
            session.mode,
            fingerprint,
            True,
        )

    if session.mode == MODE_ALL:
        return Decision(
            True,
            "Approve-everything is on for this session.",
            category,
            session.mode,
            fingerprint,
            False,
        )

    if session.mode == MODE_SAFE and category in ROUTINE:
        return Decision(
            True,
            f"Auto-approved: this only {ROUTINE[category]}.",
            category,
            session.mode,
            fingerprint,
            False,
        )

    if session.mode == MODE_SAFE:
        return Decision(
            False,
            "Auto-approve covers routine actions; Neyvia could not classify this one.",
            category,
            session.mode,
            fingerprint,
            False,
        )

    return Decision(False, "Approval mode is set to ask every time.", category, session.mode, fingerprint, False)


def evaluate(action: dict[str, Any], session: SessionApprovals, *, approval: dict[str, Any] | None = None) -> Decision:
    from .proofs_a_control import check_approval
    decision = _evaluate(action, session, approval=approval)
    check_approval(action, session, approval, decision)
    return decision


def require(action: dict[str, Any], session: SessionApprovals, *, approval: dict[str, Any] | None = None) -> Decision:
    """Evaluate and raise unless the action may run."""
    decision = evaluate(action, session, approval=approval)
    if not decision.allowed:
        raise ApprovalRequired(decision)
    return decision


def describe_modes() -> dict[str, Any]:
    """Data for the settings surface — including what never gets skipped."""
    result = {
        "schema": "neyvia.approval.modes/1",
        "modes": [
            {
                "id": mode,
                "label": MODE_LABELS[mode],
                "sessionOnly": mode == MODE_ALL,
            }
            for mode in MODES
        ],
        "alwaysAsk": [{"category": key, "because": why} for key, why in sorted(ALWAYS_ASK.items())],
        "routine": [{"category": key, "because": why} for key, why in sorted(ROUTINE.items())],
        "note": (
            "Approve-everything applies to this session only and is never saved. "
            "Actions that spend money, destroy data, send on your behalf, or trust a "
            "new MCP server ask in every mode."
        ),
    }
    from .proofs_a_control import check_modes
    check_modes(result)
    return result
