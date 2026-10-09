"""Scope and proof contracts for authorized red/blue-team missions.

The policy is deliberately tool-neutral. It lets the runtime decide whether an
active security action is in bounds before choosing a local capability, native
tool, or brokered MCP operation. It also makes missing defensive coverage
visible instead of pretending that a generic "red team" tile is sufficient.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Iterable


SECURITY_SCOPE_SCHEMA = "neyvia.security_scope.v1"
SECURITY_ACTION_DECISION_SCHEMA = "neyvia.security_action_decision.v1"
PURPLE_TEAM_PLAN_SCHEMA = "neyvia.purple_team_plan.v1"
SECURITY_TOOL_COVERAGE_SCHEMA = "neyvia.security_tool_coverage.v1"

VALID_ENVIRONMENTS = {"lab", "staging", "production"}
VALID_MODES = {"passive", "active"}
HIGH_RISK_ACTION_CLASSES = {
    "credential_access",
    "destructive",
    "persistence",
    "external_delivery",
}

SECURITY_PHASE_TOOL_ALIASES = {
    "scope_and_threat_model": {
        "security.threat-model",
        "threat_model",
        "mcp.security.threat_model",
    },
    "bounded_red_probe": {
        "security.ai-red-team",
        "security.application-assessment",
        "run_bounded_probe",
        "mcp.security.run_bounded_probe",
    },
    "blue_detection": {
        "collect_detection_evidence",
        "mcp.security.collect_detection_evidence",
        "tool.windows-defender",
        "tool.grype",
        "tool.syft",
    },
    "remediation": {
        "security.remediate-and-retest",
        "apply_remediation",
        "mcp.security.apply_remediation",
    },
    "independent_retest": {
        "security.remediate-and-retest",
        "independent_retest",
        "mcp.security.independent_retest",
    },
}
SECURITY_CAPABILITY_IDS = (
    "security.threat-model",
    "security.ai-red-team",
    "security.application-assessment",
    "security.remediate-and-retest",
)
SECURITY_NATIVE_TOOL_QUERIES = (
    "defender",
    "grype",
    "syft",
    "semgrep",
    "zap",
)


def _strings(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def normalize_security_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(scope or {})
    environment = str(payload.get("environment") or "lab").strip().lower()
    mode = str(payload.get("mode") or "passive").strip().lower()
    try:
        max_probe_attempts = int(payload.get("maxProbeAttempts") or 3)
    except (TypeError, ValueError, OverflowError):
        max_probe_attempts = 3
    return {
        "schema": SECURITY_SCOPE_SCHEMA,
        "target": str(payload.get("target") or "").strip(),
        "authorizedBy": str(payload.get("authorizedBy") or "").strip(),
        "authorizationConfirmed": bool(payload.get("authorizationConfirmed", False)),
        "environment": environment if environment in VALID_ENVIRONMENTS else "invalid",
        "mode": mode if mode in VALID_MODES else "invalid",
        "allowedTargets": _strings(payload.get("allowedTargets")),
        "excludedTargets": _strings(payload.get("excludedTargets")),
        "allowedActionClasses": [
            item.lower() for item in _strings(payload.get("allowedActionClasses"))
        ],
        "allowCredentialAccess": bool(payload.get("allowCredentialAccess", False)),
        "allowDestructiveActions": bool(payload.get("allowDestructiveActions", False)),
        "allowPersistence": bool(payload.get("allowPersistence", False)),
        "allowExternalDelivery": bool(payload.get("allowExternalDelivery", False)),
        "maxProbeAttempts": max(1, min(max_probe_attempts, 50)),
        "dataHandling": str(payload.get("dataHandling") or "minimize-and-redact").strip(),
        "approvalId": str(payload.get("approvalId") or "").strip(),
    }


def validate_security_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_security_scope(scope)
    blockers: list[str] = []
    warnings: list[str] = []
    if not normalized["target"]:
        blockers.append("An explicit authorized target is required.")
    if normalized["environment"] == "invalid":
        blockers.append("Environment must be lab, staging, or production.")
    if normalized["mode"] == "invalid":
        blockers.append("Mode must be passive or active.")
    active = normalized["mode"] == "active"
    if active and not normalized["authorizationConfirmed"]:
        blockers.append("Active testing requires explicit authorization confirmation.")
    if active and not normalized["authorizedBy"]:
        blockers.append("Active testing requires an authorization owner.")
    if active and not normalized["allowedActionClasses"]:
        blockers.append("Active testing requires bounded allowed action classes.")
    if not normalized["allowedTargets"]:
        normalized["allowedTargets"] = [normalized["target"]] if normalized["target"] else []
    if normalized["target"] in set(normalized["excludedTargets"]):
        blockers.append("The target is also listed as excluded.")
    approval_required = bool(active and normalized["environment"] == "production")
    if approval_required and not normalized["approvalId"]:
        warnings.append("Production active testing requires an action-time approval receipt.")
    return {
        "schema": SECURITY_SCOPE_SCHEMA,
        "valid": not blockers,
        "activeTestingAllowed": active and not blockers,
        "approvalRequired": approval_required,
        "blockers": blockers,
        "warnings": warnings,
        "scope": normalized,
    }


def evaluate_security_action(
    scope: dict[str, Any] | None,
    action: dict[str, Any] | None,
) -> dict[str, Any]:
    validation = validate_security_scope(scope)
    normalized_scope = validation["scope"]
    proposal = dict(action or {})
    action_class = str(
        proposal.get("actionClass") or proposal.get("kind") or ""
    ).strip().lower()
    target = str(proposal.get("target") or normalized_scope.get("target") or "").strip()
    scope_active = normalized_scope.get("mode") == "active"
    proposal_active = bool(proposal.get("active", False))
    active = bool(scope_active or proposal_active or action_class in HIGH_RISK_ACTION_CLASSES)
    blockers = list(validation["blockers"])

    allowed_targets = set(normalized_scope.get("allowedTargets") or [])
    excluded_targets = set(normalized_scope.get("excludedTargets") or [])
    if target in excluded_targets:
        blockers.append("The proposed target is explicitly excluded.")
    elif allowed_targets and target not in allowed_targets:
        blockers.append("The proposed target is outside the authorized target set.")
    if active and not scope_active:
        blockers.append("Active actions require an active security scope.")
    if active and not normalized_scope.get("authorizationConfirmed"):
        blockers.append("Active actions require explicit authorization confirmation.")
    if active and not normalized_scope.get("authorizedBy"):
        blockers.append("Active actions require an authorization owner.")
    if active and action_class not in set(normalized_scope.get("allowedActionClasses") or []):
        blockers.append("The proposed action class is outside the authorized scope.")

    explicit_high_risk_allowances = {
        "credential_access": "allowCredentialAccess",
        "destructive": "allowDestructiveActions",
        "persistence": "allowPersistence",
        "external_delivery": "allowExternalDelivery",
    }
    allowance = explicit_high_risk_allowances.get(action_class)
    if allowance and not normalized_scope.get(allowance):
        blockers.append(f"{action_class} is not explicitly authorized.")

    approval_required = bool(
        validation["approvalRequired"]
        or action_class in HIGH_RISK_ACTION_CLASSES
        or proposal.get("externalSideEffect")
    )
    approval_id = str(proposal.get("approvalId") or normalized_scope.get("approvalId") or "")
    scope_allowed = not blockers
    approval_satisfied = not approval_required or bool(approval_id)
    result = {
        "schema": SECURITY_ACTION_DECISION_SCHEMA,
        "allowed": scope_allowed and approval_satisfied,
        "scopeAllowed": scope_allowed,
        "approvalRequired": approval_required,
        "approvalSatisfied": approval_satisfied,
        "blockers": blockers,
        "target": target,
        "actionClass": action_class,
        "active": active,
        "maxProbeAttempts": normalized_scope.get("maxProbeAttempts"),
        "scope": copy.deepcopy(normalized_scope),
        "nextAction": (
            "Correct the authorization scope before running this action."
            if blockers
            else "Request action-time approval before execution."
            if approval_required and not approval_id
            else "Execute within the bounded scope and preserve evidence."
        ),
    }
    from .proofs_c_missions import check_security
    check_security(result)
    return result


def build_purple_team_plan(scope: dict[str, Any] | None) -> dict[str, Any]:
    validation = validate_security_scope(scope)
    phases = [
        {
            "id": "scope_and_threat_model",
            "owner": "auditor",
            "proof": ["authorization", "target-boundary", "threat-model"],
        },
        {
            "id": "bounded_red_probe",
            "owner": "red",
            "proof": ["attempt-ledger", "reproduction-evidence"],
        },
        {
            "id": "blue_detection",
            "owner": "blue",
            "proof": ["detection-evidence", "coverage-gap"],
        },
        {
            "id": "remediation",
            "owner": "defender",
            "proof": ["change-receipt", "targeted-regression"],
        },
        {
            "id": "independent_retest",
            "owner": "auditor",
            "proof": ["independent-verdict", "residual-risk"],
        },
    ]
    result = {
        "schema": PURPLE_TEAM_PLAN_SCHEMA,
        "ready": validation["valid"],
        "scope": validation,
        "phases": phases,
        "stopConditions": [
            "authorization_boundary_reached",
            "attempt_budget_exhausted",
            "unexpected_third_party_target",
            "evidence_handling_violation",
        ],
    }
    from .proofs_c_missions import check_security_plan
    check_security_plan(result)
    return result


def audit_security_tool_coverage(tool_ids: Iterable[object]) -> dict[str, Any]:
    normalized: set[str] = set()
    unavailable: list[dict[str, Any]] = []
    for item in tool_ids:
        if isinstance(item, dict):
            identifier = str(
                item.get("qualifiedName")
                or item.get("toolId")
                or item.get("capabilityId")
                or item.get("name")
                or ""
            ).strip().lower()
            if not identifier:
                continue
            ready = item.get(
                "executionReady",
                item.get("available", item.get("ready", False)),
            )
            if ready is True:
                normalized.add(identifier)
            else:
                unavailable.append(
                    {
                        "id": identifier,
                        "state": str(item.get("state") or item.get("readiness") or "not_ready"),
                        "reason": str(
                            item.get("readinessDetail")
                            or item.get("detail")
                            or "No execution-ready runtime receipt."
                        ),
                    }
                )
            continue
        identifier = str(item or "").strip().lower()
        if identifier:
            normalized.add(identifier)
    phases: list[dict[str, Any]] = []
    for phase, aliases in SECURITY_PHASE_TOOL_ALIASES.items():
        matches = sorted(normalized & {alias.lower() for alias in aliases})
        phases.append(
            {
                "phase": phase,
                "ready": bool(matches),
                "matchedTools": matches,
                "acceptedAliases": sorted(aliases),
            }
        )
    missing = [item["phase"] for item in phases if not item["ready"]]
    result = {
        "schema": SECURITY_TOOL_COVERAGE_SCHEMA,
        "ready": not missing,
        "phases": phases,
        "missingPhases": missing,
        "unavailableCandidates": unavailable,
        "nextAction": (
            "The scoped purple-team runtime has tool coverage for every phase."
            if not missing
            else "Connect or implement tools for: " + ", ".join(missing)
        ),
    }
    from .proofs_c_missions import check_security_coverage
    check_security_coverage(result)
    return result


def audit_installed_security_runtime(
    root: str | Path,
    *,
    service: Any | None = None,
    delegation_ready: bool = False,
    delegation_detail: str = "",
) -> dict[str, Any]:
    """Audit real local capability/tool readiness without executing a probe."""

    if service is None:
        from .capability_service import CapabilityService

        service = CapabilityService(Path(root).resolve())
    candidates: list[dict[str, Any]] = []
    for capability_id in SECURITY_CAPABILITY_IDS:
        described = service.describe(capability_id)
        descriptor = (
            described.get("adapterDescriptor")
            if isinstance(described.get("adapterDescriptor"), dict)
            else {}
        )
        adapter_available = bool(described.get("available", False))
        supports_execution = bool(descriptor.get("supportsExecution", False))
        delegated = bool(
            adapter_available
            and not supports_execution
            and delegation_ready
        )
        execution_ready = bool(
            adapter_available and (supports_execution or delegated)
        )
        candidates.append(
            {
                "capabilityId": capability_id,
                "executionReady": execution_ready,
                "available": adapter_available,
                "adapter": str(described.get("adapter") or ""),
                "state": (
                    "execution_ready"
                    if supports_execution and adapter_available
                    else "delegated_ready"
                    if delegated
                    else "delegation_required"
                    if adapter_available
                    else "adapter_unavailable"
                ),
                "detail": (
                    str(delegation_detail or "A connected provider lane can execute this capability.")
                    if delegated
                    else (
                        str(
                            descriptor.get("reason")
                            or described.get("availabilityReason")
                            or "The adapter was discovered."
                        )
                        + " No approved direct execution handler is registered; "
                        "connect a provider lane for durable delegation."
                    )
                    if adapter_available and not supports_execution
                    else str(
                        descriptor.get("reason")
                        or described.get("availabilityReason")
                        or "No execution-ready adapter receipt."
                    )
                ),
            }
        )
    seen_tools: set[str] = set()
    for query in SECURITY_NATIVE_TOOL_QUERIES:
        result = service.search_tool_suite({"query": query, "limit": 20})
        for row in result.get("results") or []:
            if not isinstance(row, dict):
                continue
            tool_id = str(row.get("toolId") or "")
            if not tool_id or tool_id in seen_tools:
                continue
            seen_tools.add(tool_id)
            candidates.append(dict(row))
    coverage = audit_security_tool_coverage(candidates)
    return {
        "schema": "neyvia.installed_security_runtime_audit.v1",
        "ready": coverage["ready"],
        "coverage": coverage,
        "delegationReady": bool(delegation_ready),
        "delegationDetail": str(
            delegation_detail
            or (
                "A connected provider lane is available."
                if delegation_ready
                else "Connect a model provider before counting agent-delegated security phases as ready."
            )
        ),
        "capabilityCount": len(SECURITY_CAPABILITY_IDS),
        "nativeToolCandidateCount": len(seen_tools),
        "nextAction": coverage["nextAction"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit Neyvia's installed red/blue-team runtime coverage."
    )
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    result = audit_installed_security_runtime(args.root)
    print(json.dumps(result, indent=2))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
