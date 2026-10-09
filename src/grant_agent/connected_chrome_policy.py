"""Approval boundaries for actions taken in the user's connected browser.

Driving an authenticated browser means every click carries the user's real
identity and, on a compute console, their real money. This module decides which
actions Neyvia may take on its own and which require the user to say yes first.

Two rules shape the design:

* Assessment is based on what the *page* says, not on what a model intends. The
  label of the control being clicked and the surrounding page text are the
  evidence, because those are what the user would read before clicking it.
* Approval is bound to a specific action via a fingerprint. A yes for "stop
  instance gpu-01" cannot be replayed to authorise stopping anything else, and
  cannot be widened into standing permission.

When classification is uncertain the answer is to ask. A missed approval prompt
is an annoyance; an unrequested one that turns out to cost money or destroy a
checkpoint is not recoverable.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

#: Safe to perform without asking: reading, looking, moving around.
RISK_ROUTINE = "routine"
#: Costs money, changes capacity, or starts/stops work. Ask first.
RISK_CONSEQUENTIAL = "consequential"
#: Destroys state that may not be recoverable. Ask first, and say what is at risk.
RISK_DESTRUCTIVE = "destructive"

_RISK_ORDER = {RISK_ROUTINE: 0, RISK_CONSEQUENTIAL: 1, RISK_DESTRUCTIVE: 2}


class ApprovalRequired(RuntimeError):
    """Raised when an action needs the user's explicit approval and lacks it."""

    def __init__(self, assessment: "Assessment") -> None:
        super().__init__(assessment.summary)
        self.assessment = assessment


# Patterns are matched against the control's label and nearby page text. They are
# deliberately broad: over-asking is cheap, under-asking is not.
_DESTRUCTIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bdelete\b", "deletes something"),
    (r"\bdestroy\b", "destroys a resource"),
    (r"\bterminate\b", "terminates a resource"),
    (r"\bremove\b", "removes something"),
    (r"\bwipe\b", "erases data"),
    (r"\breset\b", "resets state"),
    (r"\brevoke\b", "revokes access"),
    (r"\bcancel subscription\b", "cancels a subscription"),
)

_CONSEQUENTIAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bstart\b", "starts a resource that may be billed"),
    (r"\blaunch\b", "launches a resource that may be billed"),
    (r"\bdeploy\b", "deploys a resource"),
    (r"\bcreate\b", "creates a resource that may be billed"),
    (r"\bstop\b", "stops running work"),
    (r"\bpause\b", "pauses running work"),
    (r"\brestart\b", "restarts running work"),
    (r"\bresize\b", "changes provisioned capacity"),
    (r"\bupgrade\b", "changes provisioned capacity"),
    (r"\bdowngrade\b", "changes provisioned capacity"),
    (r"\bmachine type\b", "changes machine type"),
    (r"\bgpu\b.*\bchange\b", "changes GPU allocation"),
    (r"\bstorage\b", "changes storage, which may be billed"),
    (r"\bbilling\b|\bpayment\b|\bpurchase\b|\bsubscribe\b", "affects billing"),
    (r"\bupload\b", "uploads data off this machine"),
    (r"\bdownload\b", "downloads data"),
    (r"\bpublic\b|\bexpose\b|\bport\b", "may change network exposure"),
    (r"\bsubmit\b|\bconfirm\b|\bapply\b", "commits a change"),
    (r"\btrain\b|\bjob\b|\brun\b", "starts or changes a compute job"),
)


@dataclass
class Assessment:
    risk: str
    reasons: list[str]
    summary: str
    fingerprint: str
    requires_approval: bool
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "reasons": self.reasons,
            "summary": self.summary,
            "fingerprint": self.fingerprint,
            "requiresApproval": self.requires_approval,
            "evidence": self.evidence,
        }


def action_fingerprint(action: dict[str, Any], *, label: str = "", url: str = "") -> str:
    """Stable identifier for one specific action on one specific target.

    Approval is granted against this value, which is what stops a yes from being
    reused for a different action later.
    """
    payload = {
        "kind": action.get("kind"),
        "url": action.get("url"),
        "text": action.get("text"),
        "key": action.get("key"),
        "x": action.get("x"),
        "y": action.get("y"),
        "label": label.strip().lower(),
        "page": url,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _assess(
    action: dict[str, Any],
    *,
    label: str = "",
    page_url: str = "",
    page_text: str = "",
) -> Assessment:
    """Classify an action's risk from the control's label and page context."""
    kind = str(action.get("kind") or "")
    fingerprint = action_fingerprint(action, label=label, url=page_url)

    # Reading and moving around are routine regardless of context. Enter is the
    # exception: it submits forms, so it inherits the surrounding page context
    # and falls through to the analysis below.
    submits_via_enter = kind == "key" and str(action.get("key") or "").lower() == "enter"
    if kind == "navigate" or (kind == "key" and not submits_via_enter):
        return Assessment(
            risk=RISK_ROUTINE,
            reasons=[],
            summary=f"Routine {kind} action.",
            fingerprint=fingerprint,
            requires_approval=False,
            evidence={"label": label, "pageUrl": page_url},
        )

    # The control's own label is the strongest signal; page text is weaker and
    # only consulted for typed/submitted input where there is no label.
    haystack = label.lower()
    if not haystack and kind in ("type", "key"):
        haystack = page_text.lower()[:2000]

    reasons: list[str] = []
    risk = RISK_ROUTINE

    for pattern, reason in _DESTRUCTIVE_PATTERNS:
        if re.search(pattern, haystack):
            reasons.append(reason)
            risk = RISK_DESTRUCTIVE

    if risk != RISK_DESTRUCTIVE:
        for pattern, reason in _CONSEQUENTIAL_PATTERNS:
            if re.search(pattern, haystack):
                reasons.append(reason)
                risk = RISK_CONSEQUENTIAL

    # An unlabelled click is a click on something we could not read. We do not
    # know what it does, so we do not do it unattended.
    if kind == "click" and not label.strip():
        risk = max(risk, RISK_CONSEQUENTIAL, key=lambda value: _RISK_ORDER[value])
        reasons.append("the control could not be identified, so its effect is unknown")

    requires_approval = risk != RISK_ROUTINE
    if requires_approval:
        detail = "; ".join(dict.fromkeys(reasons))
        target = f"'{label.strip()}'" if label.strip() else "an unidentified control"
        summary = f"This {kind} on {target} needs your approval because it {detail}."
    else:
        summary = f"Routine {kind} action on {label.strip() or 'the page'}."

    return Assessment(
        risk=risk,
        reasons=list(dict.fromkeys(reasons)),
        summary=summary,
        fingerprint=fingerprint,
        requires_approval=requires_approval,
        evidence={"label": label, "pageUrl": page_url},
    )


def assess(action: dict[str, Any], *, label: str = "", page_url: str = "", page_text: str = "") -> Assessment:
    result = _assess(action, label=label, page_url=page_url, page_text=page_text)
    from .proofs_a_control import check_chrome_assessment
    check_chrome_assessment(action, label, page_url, page_text, result)
    return result


def grant_approval(assessment: Assessment, *, granted_by: str, note: str = "") -> dict[str, Any]:
    """Record a user's approval for one assessed action."""
    return {
        "schema": "neyvia.connected_chrome.approval/1",
        "fingerprint": assessment.fingerprint,
        "risk": assessment.risk,
        "grantedBy": granted_by,
        "grantedAt": time.time(),
        "note": note,
        "summary": assessment.summary,
    }


def ensure_approved(assessment: Assessment, approval: dict[str, Any] | None) -> None:
    """Raise unless ``approval`` is a valid grant for exactly this action."""
    if not assessment.requires_approval:
        return
    if not isinstance(approval, dict):
        raise ApprovalRequired(assessment)
    if approval.get("fingerprint") != assessment.fingerprint:
        # Either a stale approval or an attempt to reuse one. Both are refusals.
        raise ApprovalRequired(assessment)
