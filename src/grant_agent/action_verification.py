from __future__ import annotations

import re
from typing import Any


ACTION_VERIFICATION_SCHEMA = "neyvia.action_verification_plan.v1"
RISK_LEVELS = ("lightweight", "standard", "costly", "consequential")


def _normalized_kind(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", ".", str(value or "").strip().lower()).strip(".")


def classify_action_risk(
    action_kind: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind = _normalized_kind(action_kind)
    details = dict(context or {})
    destructive = bool(details.get("destructive"))
    public = bool(details.get("publicCommunication") or details.get("public"))
    credential_change = bool(details.get("credentialChange"))
    paid = bool(details.get("paid") or details.get("estimatedCost"))
    transfer_bytes = max(0, int(details.get("bytes") or details.get("sizeBytes") or 0))
    approval_threshold = str(details.get("approvalThreshold") or "costly").strip().lower()

    reasons: list[str] = []
    if destructive or public or credential_change:
        level = "consequential"
        if destructive:
            reasons.append("The action can delete or irreversibly replace external state.")
        if public:
            reasons.append("The action communicates or publishes outside the workspace.")
        if credential_change:
            reasons.append("The action changes authentication or credential state.")
    elif paid or any(
        token in kind
        for token in ("gpu", "thunder", "train", "compute.allocate", "instance.create")
    ):
        level = "costly"
        reasons.append("The action can consume paid or scarce compute.")
    elif kind in {
        "file.transfer",
        "file.copy",
        "file.move",
        "file.download",
        "file.upload",
    }:
        level = "standard" if transfer_bytes >= 1_000_000_000 else "lightweight"
        reasons.append(
            "Large transfer needs bounded integrity evidence."
            if level == "standard"
            else "Ordinary transfer needs only destination and integrity evidence."
        )
    elif any(
        token in kind
        for token in ("write", "edit", "patch", "browser", "ui", "code", "build")
    ):
        level = "standard"
        reasons.append("The action changes reversible workspace or browser state.")
    else:
        level = "lightweight"
        reasons.append("The action is read-only or has a small reversible footprint.")
    approval_required = (
        level == "consequential"
        or paid
        or (approval_threshold == "all-writes" and not any(
            token in kind for token in ("inspect", "read", "list", "search")
        ))
        or (approval_threshold == "costly" and level == "costly")
    )
    return {
        "level": level,
        "reasons": reasons,
        "approvalRequired": approval_required,
        "approvalThreshold": approval_threshold,
        "destructive": destructive,
        "paid": paid,
    }


def build_action_verification_plan(
    *,
    mission_id: str,
    action_kind: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind = _normalized_kind(action_kind)
    details = dict(context or {})
    risk = classify_action_risk(kind, details)

    if kind in {
        "file.transfer",
        "file.copy",
        "file.move",
        "file.download",
        "file.upload",
    }:
        checks = [
            _check(
                "destination_exists",
                "Confirm the intended destination exists.",
                evidence="destination path and observed metadata",
            ),
            _check(
                "transfer_integrity",
                "Compare one appropriate size or content hash.",
                evidence="size comparison or one digest comparison",
            ),
        ]
        forbidden = [
            "full frontend build",
            "browser acceptance campaign",
            "unrelated repository test suite",
        ]
    elif any(
        token in kind
        for token in ("gpu", "thunder", "train", "compute.allocate", "instance.create")
    ):
        checks = [
            _check(
                "approval_receipt",
                "Confirm paid or consequential authority before execution.",
                evidence="approval identity and approved scope",
                required=bool(risk["approvalRequired"] or details.get("requiresApproval", True)),
            ),
            _check(
                "provider_identity",
                "Confirm provider request, workspace, instance, and job identity.",
                evidence="provider receipt and stable external identifiers",
            ),
            _check(
                "provider_state",
                "Confirm the expected external state transition.",
                evidence="observed instance/job state with timestamp",
            ),
            _check(
                "checkpoint_or_artifact",
                "Confirm a checkpoint, metric, log, or output artifact appropriate to the step.",
                evidence="checkpoint path, bounded logs/metrics, or artifact identity",
            ),
            _check(
                "cost_and_release",
                "Confirm metering evidence and the configured release or idle policy.",
                evidence="meter data plus retained/released resource state",
            ),
        ]
        forbidden = [
            "rapid model-driven polling",
            "duplicate provider launch for verification",
            "unrelated local build",
        ]
    elif risk["level"] == "consequential":
        checks = [
            _check(
                "approval_receipt",
                "Confirm approval covers the exact consequential action.",
                evidence="approval identity, target, and scope",
            ),
            _check(
                "external_state",
                "Read the authoritative external state after execution.",
                evidence="provider or destination state",
            ),
            _check(
                "operation_receipt",
                "Preserve a concise durable operation receipt.",
                evidence="request identity, result, and recovery guidance",
            ),
        ]
        forbidden = ["repeating the action only to gain more evidence"]
    elif any(token in kind for token in ("ui", "frontend")):
        checks = [
            _check(
                "targeted_behavior",
                "Run the smallest check covering the changed behavior.",
                evidence="targeted check output",
            ),
            _check(
                "frontend_build",
                "Confirm the production frontend compiles.",
                evidence="one production build receipt",
            ),
            _check(
                "user_interaction",
                "Exercise the changed path once like a user when practical.",
                evidence="observed interaction and optional screenshot",
            ),
        ]
        forbidden = ["repeating equivalent browser checks without a new failure"]
    elif any(token in kind for token in ("code", "patch", "edit", "write")):
        checks = [
            _check(
                "syntax_or_type",
                "Confirm changed code parses or type-checks where applicable.",
                evidence="syntax, import, or type-check receipt",
            ),
            _check(
                "targeted_behavior",
                "Run focused tests for the changed behavior.",
                evidence="targeted test receipt",
            ),
        ]
        forbidden = ["unrelated full-suite repetition"]
    else:
        checks = [
            _check(
                "result_present",
                "Confirm the requested information or state was observed.",
                evidence="bounded result receipt",
            )
        ]
        forbidden = ["builds or test suites unrelated to the read-only request"]

    return {
        "schema": ACTION_VERIFICATION_SCHEMA,
        "missionId": str(mission_id or "")[:120],
        "actionKind": kind,
        "risk": risk,
        "checks": checks,
        "requiredCheckCount": sum(1 for item in checks if item["required"]),
        "maximumPlannedCheckCount": len(checks),
        "unrelatedChecksForbidden": True,
        "forbiddenChecks": forbidden,
        "nextAction": (
            "Run each required check once; add another check only when a concrete failure leaves the result uncertain."
        ),
    }


def _check(
    check_id: str,
    purpose: str,
    *,
    evidence: str,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "purpose": purpose,
        "evidence": evidence,
        "required": bool(required),
    }
