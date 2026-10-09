from __future__ import annotations

import re
from typing import Any

from .reasoning_capabilities import adapt_reasoning_route, normalize_reasoning_effort


ULTRA_REASONING_SCHEMA = "fluxio.mission.ultra_reasoning.v1"
ULTRA_PROFILE_VERSION = 1

ULTRA_DIRECTIVE = (
    "Ultra orchestration: treat the mission contract as immutable; investigate before editing; "
    "use deterministic checks as the acceptance authority; keep the best verified checkpoint; "
    "and stop rather than falling back to the primary workspace when isolation is unavailable."
)

ULTRA_SUCCESS_CHECK = (
    "Ultra proof gate passes: required verification succeeds in an isolated worktree with no "
    "blocking finding or pending approval."
)

_RISK_TERMS = {
    "auth",
    "authentication",
    "authorization",
    "billing",
    "concurrency",
    "database",
    "deploy",
    "deployment",
    "migration",
    "payment",
    "permission",
    "production",
    "runtime",
    "security",
    "session",
}

_UNCERTAINTY_TERMS = {
    "architecture",
    "best",
    "compare",
    "design",
    "explore",
    "investigate",
    "optimize",
    "research",
    "tradeoff",
    "unknown",
}

_SMALL_CHANGE_TERMS = {
    "copy",
    "label",
    "rename",
    "spelling",
    "text",
    "typo",
}

_VERIFICATION_TERMS = {
    "acceptance",
    "browser",
    "build",
    "integration",
    "lint",
    "smoke",
    "test",
    "typecheck",
    "verify",
}

_SURFACE_TERMS = {
    "frontend": {"browser", "component", "css", "frontend", "page", "preview", "ui", "ux"},
    "backend": {"api", "backend", "endpoint", "server", "service", "worker"},
    "data": {"cache", "data", "database", "db", "migration", "schema", "storage"},
    "runtime": {"deploy", "deployment", "process", "runtime", "session", "transport", "websocket"},
    "security": {"auth", "authentication", "authorization", "permission", "secret", "security"},
    "tooling": {"build", "ci", "cli", "lint", "test", "typecheck"},
}


def _tokens(value: object) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _bounded_score(value: int) -> int:
    return max(0, min(100, int(value)))


def _diagnose_task(
    *,
    objective: str,
    success_checks: list[str],
    budget_hours: float,
) -> dict[str, Any]:
    combined = " ".join([objective, *success_checks])
    words = _tokens(combined)
    objective_words = _tokens(objective)
    surfaces = [
        name
        for name, terms in _SURFACE_TERMS.items()
        if words.intersection(terms)
    ]
    risk_hits = sorted(words.intersection(_RISK_TERMS))
    uncertainty_hits = sorted(words.intersection(_UNCERTAINTY_TERMS))
    verification_hits = sorted(words.intersection(_VERIFICATION_TERMS))
    small_change_hits = sorted(objective_words.intersection(_SMALL_CHANGE_TERMS))

    size_score = 20
    size_score += min(30, max(0, len(objective.split()) - 12))
    size_score += max(0, len(surfaces) - 1) * 12
    size_score += min(20, len(success_checks) * 5)
    if small_change_hits and len(objective.split()) <= 18:
        size_score -= 25

    risk_score = len(risk_hits) * 12 + max(0, len(surfaces) - 2) * 8
    uncertainty_score = len(uncertainty_hits) * 15
    if "or" in objective_words:
        uncertainty_score += 8
    if "?" in objective:
        uncertainty_score += 8

    deterministic_oracle = bool(success_checks or verification_hits)
    parallelizable = len(surfaces) >= 2 or len(uncertainty_hits) >= 2
    size_score = _bounded_score(size_score)
    risk_score = _bounded_score(risk_score)
    uncertainty_score = _bounded_score(uncertainty_score)

    candidate_eligible = bool(
        deterministic_oracle
        and parallelizable
        and budget_hours >= 4
        and (uncertainty_score >= 45 or risk_score >= 60)
    )
    if size_score <= 25 and risk_score < 25 and uncertainty_score < 25:
        topology = "direct_verified"
        topology_label = "Direct + verify"
        topology_reason = "The change appears narrow, low risk, and independently verifiable."
    else:
        topology = "investigate_implement_verify"
        topology_label = "Investigate → implement → verify"
        topology_reason = (
            "The task benefits from evidence synthesis before one isolated implementation lane."
        )

    return {
        "taskSize": size_score,
        "risk": risk_score,
        "uncertainty": uncertainty_score,
        "affectedSurfaces": surfaces or ["workspace"],
        "riskSignals": risk_hits,
        "uncertaintySignals": uncertainty_hits,
        "verificationSignals": verification_hits,
        "deterministicOracleAvailable": deterministic_oracle,
        "parallelizable": parallelizable,
        "selectedTopology": topology,
        "selectedTopologyLabel": topology_label,
        "topologyReason": topology_reason,
        "candidateSearchEligible": candidate_eligible,
    }


def _merge_ultra_routes(
    route_overrides: list[dict] | None,
    ultra_config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = dict(ultra_config or {})
    worker_effort = normalize_reasoning_effort(config.get("workerEffort"), "default")
    configured_roles = config.get("roles") if isinstance(config.get("roles"), dict) else {}
    explicit_roles = {
        str(item.get("role") or "").strip().lower(): dict(item)
        for item in (route_overrides or [])
        if isinstance(item, dict)
        and str(item.get("role") or "").strip().lower() in {"planner", "executor", "verifier"}
    }
    preserved = [
        dict(item)
        for item in (route_overrides or [])
        if isinstance(item, dict)
        and str(item.get("role") or "").strip().lower()
        not in {"planner", "executor", "verifier"}
    ]
    defaults = [
        {
            "role": "planner",
            "provider": "openai-codex",
            "model": "gpt-5.6-sol",
            "effort": worker_effort if worker_effort != "default" else "low",
            "budgetClass": "efficient",
            "routeIntent": "ultra_evidence_synthesis",
        },
        {
            "role": "executor",
            "provider": "openai-codex",
            "model": "gpt-5.6-sol",
            "effort": worker_effort if worker_effort != "default" else "low",
            "budgetClass": "efficient",
            "routeIntent": "ultra_isolated_implementation",
        },
        {
            "role": "verifier",
            "provider": "openai-codex",
            "model": "gpt-5.6-luna",
            "effort": worker_effort if worker_effort != "default" else "xhigh",
            "budgetClass": "quality",
            "routeIntent": "ultra_adversarial_verification",
        },
    ]
    routes: list[dict[str, Any]] = []
    resolutions: list[dict[str, Any]] = []
    for default in defaults:
        role = default["role"]
        configured = configured_roles.get(role) if isinstance(configured_roles.get(role), dict) else {}
        merged = {**default, **configured, **explicit_roles.get(role, {})}
        terra_replaced = "gpt-5.6-terra" in str(merged.get("model") or "").lower()
        requested_model = str(merged.get("model") or "")
        if terra_replaced:
            merged["provider"] = default["provider"]
            merged["model"] = default["model"]
            merged["effort"] = default["effort"]
        merged["role"] = role
        merged["requestedEffort"] = normalize_reasoning_effort(merged.get("effort"), "default")
        adapted, resolution = adapt_reasoning_route(merged)
        resolution["role"] = role
        if terra_replaced:
            resolution.update(
                {
                    "operatorPolicy": "terra_excluded_from_delegated_ultra_workers",
                    "requestedModel": requested_model,
                    "effectiveModel": adapted.get("model"),
                }
            )
        routes.append(adapted)
        resolutions.append(resolution)
    return [*routes, *preserved], resolutions


def build_ultra_launch_profile(
    *,
    objective: str,
    success_checks: list[str] | None,
    route_overrides: list[dict] | None,
    budget_hours: object,
    mission_contract: dict[str, Any] | None = None,
    ultra_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile Ultra into a durable, deterministic mission contract."""
    checks = [str(item).strip() for item in (success_checks or []) if str(item).strip()]
    try:
        budget = max(1.0, float(budget_hours))
    except (TypeError, ValueError):
        budget = 4.0
    diagnostic = _diagnose_task(
        objective=str(objective or ""),
        success_checks=checks,
        budget_hours=budget,
    )
    candidate_eligible = bool(diagnostic["candidateSearchEligible"])
    routes, effort_resolutions = _merge_ultra_routes(route_overrides, ultra_config)
    orchestration = {
        "profile": "ultra",
        "version": ULTRA_PROFILE_VERSION,
        "controller": "deterministic",
        "status": "active",
        "diagnostic": diagnostic,
        "selectedTopology": diagnostic["selectedTopology"],
        "selectedTopologyLabel": diagnostic["selectedTopologyLabel"],
        "phases": [
            "contract",
            "diagnostic",
            "reconnaissance",
            "evidence_synthesis",
            "implementation",
            "verification",
            "targeted_repair",
            "proof_audit",
        ],
        "workerPolicy": {
            "allowedDelegatedProfiles": ["configured_routes", "native_ultra"],
            "planner": next(item for item in routes if item.get("role") == "planner"),
            "executor": next(item for item in routes if item.get("role") == "executor"),
            "verifier": next(item for item in routes if item.get("role") == "verifier"),
            "terraAllowed": False,
            "operatorConfig": dict(ultra_config or {}),
            "effortResolutions": effort_resolutions,
        },
        "isolation": {
            "required": True,
            "failClosed": True,
            "executionTargetPreference": "isolated_worktree",
        },
        "candidateSearch": {
            "eligible": candidate_eligible,
            "enabled": False,
            "reason": (
                "The task qualifies for an isolated candidate tournament, but Neyvia's current "
                "runtime does not yet provide independently scored candidate worktrees. Ultra "
                "will not simulate that capability."
                if candidate_eligible
                else "The deterministic diagnostic did not justify the extra candidate cost."
            ),
        },
        "verification": {
            "hardGate": True,
            "deterministicChecksFirst": True,
            "modelCannotOverrideFailedCheck": True,
            "requireArtifactProof": True,
        },
        "repair": {
            "maximumLoops": 2,
            "keepBestVerifiedCheckpoint": True,
            "revertRegressions": True,
        },
        "stopConditions": [
            "all acceptance criteria pass",
            "no blocking verifier finding remains",
            "no pending approval remains",
            "additional iteration does not improve verified evidence",
        ],
        "capabilities": {
            "adaptiveDiagnosis": True,
            "strictWorktreeIsolation": True,
            "proofGatedCompletion": True,
            "independentCandidateTournament": False,
            "cleanRoomPatchReplay": False,
        },
    }
    contract = dict(mission_contract or {})
    contract["schema"] = ULTRA_REASONING_SCHEMA
    contract["orchestration"] = orchestration
    contract["routeOverrides"] = routes
    contract["proofRequirements"] = {
        **(
            contract.get("proofRequirements")
            if isinstance(contract.get("proofRequirements"), dict)
            else {}
        ),
        "verifierReceipt": True,
        "primaryDeliverable": True,
    }
    return {
        "missionContract": contract,
        "routeOverrides": contract["routeOverrides"],
        "diagnostic": diagnostic,
        "executionTargetPreference": "isolated_worktree",
        "parallelAgents": 1,
        "mergePolicy": "risk_averse",
        "budgetHours": max(4.0, budget),
    }


def ultra_runtime_settings(mission_contract: object) -> dict[str, Any]:
    if not isinstance(mission_contract, dict):
        return {"enabled": False}
    if str(mission_contract.get("schema") or "") != ULTRA_REASONING_SCHEMA:
        return {"enabled": False}
    orchestration = mission_contract.get("orchestration")
    orchestration = orchestration if isinstance(orchestration, dict) else {}
    isolation = orchestration.get("isolation")
    isolation = isolation if isinstance(isolation, dict) else {}
    return {
        "enabled": True,
        "profile": "ultra",
        "selectedTopology": str(
            orchestration.get("selectedTopology") or "investigate_implement_verify"
        ),
        "selectedTopologyLabel": str(
            orchestration.get("selectedTopologyLabel") or "Investigate → implement → verify"
        ),
        "executionTargetPreference": str(
            isolation.get("executionTargetPreference") or "isolated_worktree"
        ),
        "requireIsolation": bool(isolation.get("required", True)),
        "failClosed": bool(isolation.get("failClosed", True)),
        "parallelAgents": 1,
        "mergePolicy": "risk_averse",
        "candidateSearch": orchestration.get("candidateSearch", {}),
        "capabilities": orchestration.get("capabilities", {}),
    }


def ultra_contract_summary(mission_contract: object) -> dict[str, Any]:
    settings = ultra_runtime_settings(mission_contract)
    if not settings.get("enabled"):
        return {}
    orchestration = mission_contract.get("orchestration") if isinstance(mission_contract, dict) else {}
    orchestration = orchestration if isinstance(orchestration, dict) else {}
    return {
        "profile": "ultra",
        "topology": settings["selectedTopology"],
        "topologyLabel": settings["selectedTopologyLabel"],
        "isolationRequired": settings["requireIsolation"],
        "candidateSearch": settings["candidateSearch"],
        "capabilities": settings["capabilities"],
        "workerPolicy": orchestration.get("workerPolicy", {}),
    }


def format_ultra_resume_boundaries(mission_contract: object) -> list[str]:
    """Render Ultra orchestration boundaries for runtime resume prompts."""
    settings = ultra_runtime_settings(mission_contract)
    if not settings.get("enabled"):
        return []
    orchestration = mission_contract.get("orchestration") if isinstance(mission_contract, dict) else {}
    orchestration = orchestration if isinstance(orchestration, dict) else {}
    worker_policy = orchestration.get("workerPolicy")
    worker_policy = worker_policy if isinstance(worker_policy, dict) else {}
    lines = [
        "Orchestration profile: Ultra",
        f"Topology: {settings.get('selectedTopologyLabel') or settings.get('selectedTopology')}",
    ]
    for role in ("planner", "executor", "verifier"):
        route = worker_policy.get(role)
        if not isinstance(route, dict):
            continue
        model = str(route.get("model") or "").strip()
        effort = str(route.get("effort") or "").strip()
        if model and effort:
            lines.append(f"{role} {model} {effort}")
        elif model:
            lines.append(f"{role} {model}")
    isolation = orchestration.get("isolation")
    isolation = isolation if isinstance(isolation, dict) else {}
    if bool(isolation.get("failClosed", settings.get("failClosed", True))):
        lines.append(
            "Isolation fail closed: stop rather than falling back to the primary workspace."
        )
    verification = orchestration.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    if verification.get("hardGate"):
        lines.append("Verification hard gate: deterministic checks are the acceptance authority.")
    return lines
