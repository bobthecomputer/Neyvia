from __future__ import annotations

from .proofs_b_engine import checked as _proofs_b_checked

import json
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from .action_executor import (
    build_action_proposal,
    build_execution_policy,
    delegated_cycle_phase_for_step,
    normalize_execution_policy,
    execute_action,
    prepare_execution_scope,
    requested_scope_for_execution_target,
)
from .checkpoints import CheckpointStore
from .context_manager import ContextWindowManager
from .doc_ingestion import ingest_docs
from .engine import AutonomousEngine
from .handoff import create_handoff_packet, save_handoff_packet
from .mission_control import hermes_auth_store_candidates
from .models import (
    ActionExecutionRecord,
    ActionProposal,
    DerivedTask,
    ExecutionPolicy,
    ExecutionScope,
    HarnessExecutionContext,
    ImprovementQueueItem,
    ModelRouteConfig,
    Mission,
    PersonaProfile,
    PlanRevision,
    PlannedStep,
    PromptStack,
    RoutingDecision,
    RunState,
    TimelineEvent,
    VerificationResult,
    WorkspaceProfile,
    utc_now_iso,
)
from .planner import PlanBundle, build_docs_first_plan
from .profiles import PersonalizationProfile
from .prompts import build_prompt_stack
from .reporting import write_run_report
from .runtime_supervisor import DelegatedRuntimeSupervisor
from .session_store import SessionStore
from .skill_library import SkillLibrary
from .safety import risk_level_for_command
from .verification import VerificationRunner

DEFAULT_FLUXIO_MAX_TOKENS = 2600
DEFAULT_FLUXIO_MERGE_POLICY = "best_score"
VALID_MERGE_POLICIES = {"best_score", "consensus", "risk_averse"}
DELEGATED_FOLLOW_BUDGET_SECONDS = 12
AUTONOMY_HISTORY_LIMIT = 12
PREMIUM_OPENAI_MODEL = "gpt-5.6-sol"
EFFICIENT_OPENAI_MODEL = "gpt-5.4-mini"
CODEX_PLANNING_PROVIDER = "openai-codex"
CODEX_PLANNING_MODEL = "gpt-5.6-sol"
CODEX_EFFICIENT_PLANNING_MODEL = "gpt-5.6-sol"
FRONTEND_MINIMAX_MODEL = "MiniMax-M3"
MINIMAX_PROVIDER_IDS = {"minimax", "minimax-cn", "minimax-portal", "minimax-oauth"}
ROUTE_OVERRIDE_ROLES = {"planner", "backend", "frontend", "executor", "verifier"}
LEGACY_MINIMAX_MODELS = {
    "minimax-m2.7",
    "minimax-m2.7-highspeed",
    "minimax/m2.7",
    "minimax/minimax-m2.7",
    "minimax/minimax-m2.7-highspeed",
}


def normalize_route_role(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "plan": "planner",
        "planning": "planner",
        "back-end": "backend",
        "back end": "backend",
        "server": "backend",
        "server-side": "backend",
        "api": "backend",
        "front-end": "frontend",
        "front end": "frontend",
        "client": "frontend",
        "client-side": "frontend",
        "ui": "frontend",
        "ux": "frontend",
        "execute": "executor",
        "execution": "executor",
        "verify": "verifier",
        "verification": "verifier",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in ROUTE_OVERRIDE_ROLES else ""
TASK_AWARE_ROUTE_PROFILES = {
    "frontend_design": {
        "keywords": (
            "frontend",
            "front-end",
            "ui",
            "ux",
            "interface",
            "design",
            "react",
            "css",
            "web app",
            "website",
            "visual",
            "prototype",
            "mobile",
            "tablet",
        ),
        "executorProvider": "minimax",
        "executorModel": FRONTEND_MINIMAX_MODEL,
        "executorEffort": "high",
        "executorBudgetClass": "specialist",
        "routeIntent": "visual_interface_execution",
        "reason": "Frontend/UI/design work routes execution to MiniMax while keeping Codex/OpenAI on planning and verification.",
    },
    "hardware_electrical": {
        "keywords": (
            "hardware",
            "electrical",
            "electronics",
            "pcb",
            "circuit",
            "sensor",
            "embedded",
            "microcontroller",
            "firmware",
            "mechatronic",
            "simulator",
            "simulation",
            "digital twin",
        ),
        "executorProvider": "openai",
        "executorModel": PREMIUM_OPENAI_MODEL,
        "executorEffort": "high",
        "executorBudgetClass": "premium",
        "routeIntent": "engineering_simulation_execution",
        "reason": "Hardware/electrical engineering missions use a premium execution lane for constraints, units, simulation reasoning, and verifier-friendly artifacts.",
    },
    "data_f1_analytics": {
        "keywords": (
            "f1",
            "formula 1",
            "formula one",
            "telemetry",
            "lap time",
            "racing",
            "analytics",
            "dataset",
            "dashboard",
            "visualization",
            "data app",
        ),
        "executorProvider": "openai",
        "executorModel": PREMIUM_OPENAI_MODEL,
        "executorEffort": "high",
        "executorBudgetClass": "premium",
        "routeIntent": "analytics_dashboard_execution",
        "reason": "F1/data analytics missions favor a premium high-effort execution lane for dashboards, datasets, and repeatable analysis while preserving premium verification.",
    },
    "research_analysis": {
        "keywords": (
            "research",
            "report",
            "analysis",
            "geoint",
            "rf",
            "wireless",
            "maritime",
            "forensics",
            "investigation",
            "intelligence",
        ),
        "executorProvider": "openai",
        "executorModel": PREMIUM_OPENAI_MODEL,
        "executorEffort": "high",
        "executorBudgetClass": "premium",
        "routeIntent": "research_synthesis_execution",
        "reason": "Research/report work keeps execution high-effort and leaves high-confidence planning and verification on Codex/OpenAI.",
    },
    "security_red_team": {
        "keywords": (
            "red team",
            "red-team",
            "defensive",
            "threat",
            "security",
            "vulnerability",
            "exploit",
            "hardening",
            "offensive",
            "attack surface",
        ),
        "executorProvider": "openai",
        "executorModel": PREMIUM_OPENAI_MODEL,
        "executorEffort": "high",
        "executorBudgetClass": "premium",
        "routeIntent": "adversarial_verification_execution",
        "reason": "Security/red-team missions use premium execution and verification so difficulty can escalate without losing defensive proof quality.",
    },
    "security_blue_team": {
        "keywords": (
            "blue team",
            "blue-team",
            "detection engineering",
            "incident response",
            "security operations",
            "soc",
            "containment",
            "forensic triage",
            "sigma rule",
            "yara rule",
            "threat hunting",
            "defender evidence",
        ),
        "executorProvider": "openai",
        "executorModel": PREMIUM_OPENAI_MODEL,
        "executorEffort": "high",
        "executorBudgetClass": "premium",
        "routeIntent": "defensive_detection_execution",
        "reason": "Blue-team missions keep detection, containment, remediation, and independent retest evidence on a high-confidence route.",
    },
}


def canonical_route_model(provider: object, model: object) -> str:
    normalized_provider = str(provider or "").strip().lower()
    value = str(model or "").strip()
    if normalized_provider in MINIMAX_PROVIDER_IDS and value.lower() in LEGACY_MINIMAX_MODELS:
        return FRONTEND_MINIMAX_MODEL
    return value
TASK_AWARE_ROUTE_KEYWORDS = {
    task_type: tuple(profile["keywords"])
    for task_type, profile in TASK_AWARE_ROUTE_PROFILES.items()
}
TASK_AWARE_ROUTE_PRIORITY = (
    "frontend_design",
    "hardware_electrical",
    "data_f1_analytics",
    "security_blue_team",
    "security_red_team",
    "research_analysis",
)
TASK_AWARE_ROUTE_LABELS = {
    "frontend_design": "Frontend/UI/design",
    "hardware_electrical": "Hardware/electrical engineering",
    "data_f1_analytics": "F1/data analytics",
    "research_analysis": "Research/OSINT analysis",
    "security_red_team": "Security/red-team",
    "security_blue_team": "Security/blue-team",
    "general_coding": "General coding",
}
OUTCOME_TREND_MIN_SAMPLES = 2
OUTCOME_TREND_MIN_SUCCESS_RATE = 60
OUTCOME_TREND_QUARANTINE_SUCCESS_RATE = 50
OUTCOME_TREND_QUARANTINE_OPERATOR_VALUE = 55
RUNTIME_CONSTITUTION_TEXT = (
    "Neyvia hybrid harness coordinates planning, execution, verification, delegated runtimes, "
    "and resumable continuity. Prefer small grounded actions, preserve proof, compact context "
    "before it overflows, and keep unattended progress safe. Active security work must carry "
    "an explicit authorized target and bounded scope; red-team findings require blue-team "
    "detection evidence, remediation, and an independent retest."
)


def guided_profile_defaults(name: str) -> dict:
    normalized = (name or "builder").strip().lower()
    defaults = {
        "beginner": {
            "autonomy_level": "guided",
            "approval_strictness": "high",
            "explanation_level": "high",
            "innovation_scope": "strict",
            "execution_scope": "isolated",
            "approval_mode": "strict",
            "delegation_aggressiveness": "low",
            "repeated_failure_broadening_threshold": 1,
            "learned_skill_aggressiveness": "low",
            "routing_strategy": "planner_premium_executor_efficient",
            "harness_experimentation_visibility": "hidden",
        },
        "builder": {
            "autonomy_level": "balanced",
            "approval_strictness": "medium",
            "explanation_level": "medium",
            "innovation_scope": "bounded",
            "execution_scope": "isolated",
            "approval_mode": "tiered",
            "delegation_aggressiveness": "balanced",
            "repeated_failure_broadening_threshold": 2,
            "learned_skill_aggressiveness": "medium",
            "routing_strategy": "uniform_quality",
            "harness_experimentation_visibility": "visible",
        },
        "advanced": {
            "autonomy_level": "high",
            "approval_strictness": "medium",
            "explanation_level": "low",
            "innovation_scope": "bounded",
            "execution_scope": "isolated",
            "approval_mode": "tiered",
            "delegation_aggressiveness": "balanced",
            "repeated_failure_broadening_threshold": 2,
            "learned_skill_aggressiveness": "medium",
            "routing_strategy": "uniform_quality",
            "harness_experimentation_visibility": "visible",
        },
        "experimental": {
            "autonomy_level": "high",
            "approval_strictness": "low",
            "explanation_level": "low",
            "innovation_scope": "bounded",
            "execution_scope": "isolated",
            "approval_mode": "hands_free",
            "delegation_aggressiveness": "high",
            "repeated_failure_broadening_threshold": 3,
            "learned_skill_aggressiveness": "high",
            "routing_strategy": "budget_first",
            "harness_experimentation_visibility": "wide",
        },
    }
    if normalized in defaults:
        return defaults[normalized]
    legacy_mapping = {
        "hands_free_builder": "experimental",
        "minimal_focus": "beginner",
        "research_sprint": "advanced",
        "safety_gate": "beginner",
    }
    return defaults.get(legacy_mapping.get(normalized, "builder"), defaults["builder"])


def normalize_route_overrides(route_overrides: object, *, canonicalize_models: bool = True) -> list[dict]:
    if not isinstance(route_overrides, list):
        return []
    normalized: list[dict] = []
    for item in route_overrides:
        if not isinstance(item, dict):
            continue
        role = normalize_route_role(item.get("role", ""))
        provider = str(item.get("provider", "")).strip().lower()
        model = (
            canonical_route_model(provider, item.get("model", ""))
            if canonicalize_models
            else str(item.get("model", "")).strip()
        )
        if not role or not provider or not model:
            continue
        row = {
            "role": role,
            "provider": provider,
            "model": model,
        }
        effort = str(item.get("effort", "")).strip().lower()
        if effort in {"ultra", "ultra-reasoning", "ultrareasoning"}:
            effort = "xhigh"
        if effort:
            row["effort"] = effort
        budget_class = str(item.get("budgetClass", item.get("budget_class", ""))).strip().lower()
        if budget_class:
            row["budgetClass"] = budget_class
        normalized.append(row)
    deduped: list[dict] = []
    seen_roles: set[str] = set()
    for item in normalized:
        if item["role"] in seen_roles:
            continue
        seen_roles.add(item["role"])
        deduped.append(item)
    return deduped


@_proofs_b_checked("proofs-b.engine.autotune")
def resolve_efficiency_autotune_policy(
    *,
    harness_lab_snapshot: dict,
    auto_optimize_routing: bool,
    requested_strategy: str,
) -> dict:
    efficiency = harness_lab_snapshot.get("efficiency", {})
    session_health = harness_lab_snapshot.get("sessionHealth", {})
    total_runs = int(efficiency.get("totalRuns", 0) or 0)
    completion_rate = int(efficiency.get("completionRate", 0) or 0)
    approval_pause_rate = int(efficiency.get("approvalPauseRate", 0) or 0)
    average_verification_failures = float(
        efficiency.get("averageVerificationFailures", 0.0) or 0.0
    )
    stale_heartbeat_count = int(session_health.get("staleHeartbeatCount", 0) or 0)
    normalized_requested = (requested_strategy or "profile_default").strip().lower()
    eligible = total_runs >= 3
    if not auto_optimize_routing:
        return {
            "enabled": False,
            "eligible": eligible,
            "reason": "Auto-optimize routing is disabled for this workspace.",
            "requestedStrategy": normalized_requested,
            "routingStrategy": normalized_requested,
            "appliedPolicy": {},
            "forcePauseOnFailure": False,
        }
    if not eligible:
        return {
            "enabled": True,
            "eligible": False,
            "reason": "Not enough local data yet (need at least 3 runs).",
            "requestedStrategy": normalized_requested,
            "routingStrategy": normalized_requested,
            "appliedPolicy": {},
            "forcePauseOnFailure": False,
        }
    if stale_heartbeat_count > 0 or completion_rate < 50:
        return {
            "enabled": True,
            "eligible": True,
            "reason": (
                "Stale runtime heartbeat or low completion rate triggered a safer routing policy."
            ),
            "requestedStrategy": normalized_requested,
            "routingStrategy": "uniform_quality",
            "appliedPolicy": {
                "policy": "safety_bias",
                "routingStrategy": "uniform_quality",
                "approvalMode": "tiered",
                "delegationAggressiveness": "low",
                "pauseOnVerificationFailure": True,
            },
            "forcePauseOnFailure": True,
        }
    if approval_pause_rate > 40:
        return {
            "enabled": True,
            "eligible": True,
            "reason": "Approval pauses are high, so delegation is reduced while keeping tiered approvals.",
            "requestedStrategy": normalized_requested,
            "routingStrategy": normalized_requested,
            "appliedPolicy": {
                "policy": "approval_pressure",
                "routingStrategy": normalized_requested,
                "approvalMode": "tiered",
                "delegationAggressiveness": "low",
                "pauseOnVerificationFailure": True,
            },
            "forcePauseOnFailure": True,
        }
    if (
        completion_rate >= 70
        and stale_heartbeat_count == 0
        and average_verification_failures <= 1.0
    ):
        return {
            "enabled": True,
            "eligible": True,
            "reason": "Local runs are stable, so Neyvia can use a more efficient executor profile.",
            "requestedStrategy": normalized_requested,
            "routingStrategy": "planner_premium_executor_efficient",
            "appliedPolicy": {
                "policy": "stable_efficiency",
                "routingStrategy": "planner_premium_executor_efficient",
                "approvalMode": "tiered",
                "delegationAggressiveness": "balanced",
                "pauseOnVerificationFailure": True,
            },
            "forcePauseOnFailure": True,
        }
    return {
        "enabled": True,
        "eligible": True,
        "reason": "No stronger local signal yet; Neyvia keeps the requested routing strategy.",
        "requestedStrategy": normalized_requested,
        "routingStrategy": normalized_requested,
        "appliedPolicy": {},
        "forcePauseOnFailure": False,
    }


def _budget_class_for_model(model: str, override_value: str = "") -> str:
    normalized_override = (override_value or "").strip().lower()
    if normalized_override:
        return normalized_override
    normalized_model = (model or "").strip().lower()
    if "mini" in normalized_model or "highspeed" in normalized_model:
        return "efficient"
    return "premium"


def infer_task_route_profile(objective: str | None = None) -> dict[str, object]:
    normalized = f" {objective or ''} ".lower()
    match_rows = []
    for task_type in TASK_AWARE_ROUTE_PRIORITY:
        keywords = TASK_AWARE_ROUTE_KEYWORDS.get(task_type, ())
        matched = [keyword for keyword in keywords if keyword in normalized]
        if matched:
            match_rows.append((task_type, matched))
    if match_rows:
        task_type, matched_keywords = max(
            match_rows,
            key=lambda item: (len(item[1]), -TASK_AWARE_ROUTE_PRIORITY.index(item[0])),
        )
        profile = dict(TASK_AWARE_ROUTE_PROFILES[task_type])
        profile["taskType"] = task_type
        profile["taskLabel"] = TASK_AWARE_ROUTE_LABELS.get(task_type, task_type)
        profile["matchedKeywords"] = matched_keywords[:6]
        profile["matchCount"] = len(matched_keywords)
        profile["fitScore"] = min(100, 58 + len(matched_keywords) * 14)
        from .proofs_c_missions import check_security_route
        check_security_route(profile)
        return profile
    return {
        "taskType": "general_coding",
        "taskLabel": TASK_AWARE_ROUTE_LABELS["general_coding"],
        "matchedKeywords": [],
        "matchCount": 0,
        "fitScore": 0,
        "routeIntent": "workspace_strategy_execution",
        "reason": "No task-specific model advantage was detected; workspace strategy controls the route.",
    }


def _operator_feedback_signal(feedback: object) -> dict[str, object]:
    if not isinstance(feedback, dict):
        return {}
    try:
        score = int(feedback.get("score"))
    except (TypeError, ValueError):
        score = -1
    outcome = str(feedback.get("outcome") or "").strip().lower()
    trust_signal = str(feedback.get("trustSignal") or feedback.get("trust_signal") or "").strip().lower()
    if score < 0 and not outcome and not trust_signal:
        return {}
    promoted = trust_signal == "promote" or outcome == "useful" or score >= 80
    deprioritized = trust_signal == "deprioritize" or outcome == "not_useful" or (0 <= score < 50)
    reviewed = trust_signal == "review" or outcome == "mixed" or (50 <= score < 80)
    return {
        "score": score,
        "outcome": outcome,
        "trustSignal": trust_signal,
        "promoted": promoted,
        "deprioritized": deprioritized,
        "reviewed": reviewed,
    }


def _append_route_outcome_sample(
    stats: dict[tuple[str, str, str, str], dict[str, object]],
    *,
    task_type: str,
    route_configs: object,
    succeeded: bool,
    failed: bool,
    source_id: str,
    source_kind: str,
    operator_signal: dict[str, object] | None = None,
) -> bool:
    if not isinstance(route_configs, list):
        return False
    appended = False
    for route in route_configs:
        if not isinstance(route, dict):
            continue
        role = str(route.get("role") or "").strip().lower()
        if role not in {"planner", "executor", "verifier"}:
            continue
        provider = str(route.get("provider") or "").strip()
        raw_model = str(route.get("model") or "").strip()
        model = canonical_route_model(provider, raw_model) if succeeded and not failed else raw_model
        if not provider or not model:
            continue
        key = (task_type, role, provider, model)
        row = stats.setdefault(
            key,
            {
                "taskType": task_type,
                "role": role,
                "provider": provider,
                "model": model,
                "sampleCount": 0,
                "completedCount": 0,
                "failedCount": 0,
                "operatorValueSampleCount": 0,
                "operatorValueScoreTotal": 0,
                "operatorPromoteCount": 0,
                "operatorReviewCount": 0,
                "operatorDeprioritizeCount": 0,
                "latestSessionId": source_id,
                "latestSourceKind": source_kind,
            },
        )
        row["sampleCount"] = int(row["sampleCount"]) + 1
        row["completedCount"] = int(row["completedCount"]) + (1 if succeeded else 0)
        row["failedCount"] = int(row["failedCount"]) + (1 if failed else 0)
        row["latestSessionId"] = source_id
        row["latestSourceKind"] = source_kind
        if operator_signal:
            score = int(operator_signal.get("score", -1) or -1)
            if score >= 0:
                row["operatorValueSampleCount"] = int(row["operatorValueSampleCount"]) + 1
                row["operatorValueScoreTotal"] = int(row["operatorValueScoreTotal"]) + score
            if operator_signal.get("promoted"):
                row["operatorPromoteCount"] = int(row["operatorPromoteCount"]) + 1
            elif operator_signal.get("deprioritized"):
                row["operatorDeprioritizeCount"] = int(row["operatorDeprioritizeCount"]) + 1
            elif operator_signal.get("reviewed"):
                row["operatorReviewCount"] = int(row["operatorReviewCount"]) + 1
        appended = True
    return appended


def build_route_outcome_trends(root: Path, limit: int = AUTONOMY_HISTORY_LIMIT) -> dict:
    runs_root = root / ".agent_runs"
    session_rows: list[tuple[float, Path]] = []
    if runs_root.exists():
        for path in runs_root.glob("session_*"):
            try:
                if not path.is_dir():
                    continue
                session_rows.append((path.stat().st_mtime, path))
            except OSError:
                continue
    session_paths = [
        path for _mtime, path in sorted(session_rows, key=lambda item: item[0], reverse=True)
    ]
    stats: dict[tuple[str, str, str, str], dict[str, object]] = {}
    scanned = 0
    for session_path in session_paths[: max(1, int(limit))]:
        state_path = session_path / "state.json"
        if not state_path.exists():
            continue
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("autopilot_status") or "").strip().lower()
        pause_reason = str(payload.get("autopilot_pause_reason") or "").strip().lower()
        succeeded = status == "completed"
        failed = status in {"failed", "blocked"} or pause_reason in {
            "verification_failed",
            "runtime_budget",
            "delegated_runtime_failed",
        }
        if not succeeded and not failed:
            continue
        task_profile = infer_task_route_profile(str(payload.get("objective") or ""))
        task_type = str(task_profile.get("taskType") or "general_coding")
        if _append_route_outcome_sample(
            stats,
            task_type=task_type,
            route_configs=payload.get("route_configs", []),
            succeeded=succeeded,
            failed=failed,
            source_id=session_path.name,
            source_kind="agent_run",
        ):
            scanned += 1

    missions_path = root / ".agent_control" / "missions.json"
    mission_scanned = 0
    try:
        missions_payload = json.loads(missions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        missions_payload = []
    if isinstance(missions_payload, list):
        mission_rows = [
            item for item in missions_payload
            if isinstance(item, dict)
        ]
        mission_rows.sort(
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )
        for mission in mission_rows[: max(1, int(limit))]:
            state = mission.get("state") if isinstance(mission.get("state"), dict) else {}
            operator_signal = _operator_feedback_signal(
                state.get("operator_value_feedback")
            )
            status = str(state.get("status") or mission.get("status") or "").strip().lower()
            succeeded = bool(operator_signal.get("promoted")) or status == "completed"
            failed = bool(operator_signal.get("deprioritized")) or status in {"failed", "blocked"}
            if not operator_signal and not succeeded and not failed:
                continue
            task_profile = infer_task_route_profile(str(mission.get("objective") or ""))
            task_type = str(task_profile.get("taskType") or "general_coding")
            if _append_route_outcome_sample(
                stats,
                task_type=task_type,
                route_configs=mission.get("route_configs", []),
                succeeded=succeeded,
                failed=failed,
                source_id=str(mission.get("mission_id") or ""),
                source_kind="mission_closeout",
                operator_signal=operator_signal,
            ):
                scanned += 1
                mission_scanned += 1
    route_stats = []
    for row in stats.values():
        sample_count = int(row["sampleCount"])
        completed_count = int(row["completedCount"])
        row["successRate"] = int(round((completed_count / sample_count) * 100)) if sample_count else 0
        operator_samples = int(row.get("operatorValueSampleCount", 0) or 0)
        operator_total = int(row.get("operatorValueScoreTotal", 0) or 0)
        row["operatorValueAverage"] = (
            int(round(operator_total / operator_samples)) if operator_samples else 0
        )
        row.pop("operatorValueScoreTotal", None)
        route_stats.append(row)
    route_stats.sort(
        key=lambda item: (
            str(item["taskType"]),
            str(item["role"]),
            -int(item["sampleCount"]),
            -int(item["successRate"]),
            -int(item.get("operatorValueAverage", 0) or 0),
            str(item["provider"]),
            str(item["model"]),
        )
    )
    recommendations: dict[str, dict[str, dict[str, object]]] = {}
    quarantined_routes: dict[str, dict[str, list[dict[str, object]]]] = {}
    for row in route_stats:
        sample_count = int(row["sampleCount"])
        success_rate = int(row.get("successRate", 0) or 0)
        operator_samples = int(row.get("operatorValueSampleCount", 0) or 0)
        operator_average = int(row.get("operatorValueAverage", 0) or 0)
        operator_deprioritize = int(row.get("operatorDeprioritizeCount", 0) or 0)
        operator_promote = int(row.get("operatorPromoteCount", 0) or 0)
        quarantine_reason = ""
        if operator_samples and (
            operator_average < OUTCOME_TREND_QUARANTINE_OPERATOR_VALUE
            or operator_deprioritize > operator_promote
        ):
            quarantine_reason = (
                f"operator value {operator_average}/100 across {operator_samples} closeout(s); "
                f"{operator_deprioritize} deprioritize vs {operator_promote} promote"
            )
        elif sample_count >= OUTCOME_TREND_MIN_SAMPLES and success_rate < OUTCOME_TREND_QUARANTINE_SUCCESS_RATE:
            quarantine_reason = (
                f"{success_rate}% success across {sample_count} similar run(s), below "
                f"{OUTCOME_TREND_QUARANTINE_SUCCESS_RATE}% quarantine threshold"
            )
        if quarantine_reason:
            quarantined_routes.setdefault(str(row["taskType"]), {}).setdefault(str(row["role"]), []).append(
                {
                    **dict(row),
                    "schema": "fluxio.route_outcome_quarantine.v1",
                    "status": "quarantined_until_clean_value_sample",
                    "quarantineReason": quarantine_reason,
                    "requiredAction": (
                        "Run a clean value-scored route-trust sample before this provider/model lane "
                        "can be selected automatically again."
                    ),
                }
            )
        if int(row["sampleCount"]) < OUTCOME_TREND_MIN_SAMPLES:
            continue
        if int(row["successRate"]) < OUTCOME_TREND_MIN_SUCCESS_RATE:
            continue
        operator_samples = int(row.get("operatorValueSampleCount", 0) or 0)
        if operator_samples and int(row.get("operatorValueAverage", 0) or 0) < 70:
            continue
        task_rows = recommendations.setdefault(str(row["taskType"]), {})
        role = str(row["role"])
        current = task_rows.get(role)
        if current is None or (
            int(row["successRate"]),
            int(row.get("operatorValueAverage", 0) or 0),
            int(row["sampleCount"]),
        ) > (
            int(current.get("successRate", 0)),
            int(current.get("operatorValueAverage", 0) or 0),
            int(current.get("sampleCount", 0)),
        ):
            task_rows[role] = dict(row)
    return {
        "schema": "fluxio.route_outcome_trends.v1",
        "scannedRuns": scanned,
        "scannedMissionCloseouts": mission_scanned,
        "sampleLimit": max(1, int(limit)),
        "minimumSamples": OUTCOME_TREND_MIN_SAMPLES,
        "minimumSuccessRate": OUTCOME_TREND_MIN_SUCCESS_RATE,
        "quarantineOperatorValueThreshold": OUTCOME_TREND_QUARANTINE_OPERATOR_VALUE,
        "quarantineSuccessRateThreshold": OUTCOME_TREND_QUARANTINE_SUCCESS_RATE,
        "routeStats": route_stats[:60],
        "recommendations": recommendations,
        "quarantinedRoutes": quarantined_routes,
    }


def _route_outcome_recommendation(
    trends: dict | None,
    *,
    task_type: str,
    role: str,
) -> dict[str, object]:
    if not isinstance(trends, dict):
        return {}
    recommendations = trends.get("recommendations")
    if not isinstance(recommendations, dict):
        return {}
    task_rows = recommendations.get(task_type)
    if not isinstance(task_rows, dict):
        return {}
    row = task_rows.get(role)
    return dict(row) if isinstance(row, dict) else {}


def _route_outcome_quarantine(
    trends: dict | None,
    *,
    task_type: str,
    role: str,
    provider: str,
    model: str,
) -> dict[str, object]:
    if not isinstance(trends, dict):
        return {}
    quarantined = trends.get("quarantinedRoutes")
    if not isinstance(quarantined, dict):
        return {}
    task_rows = quarantined.get(task_type)
    if not isinstance(task_rows, dict):
        return {}
    role_rows = task_rows.get(role)
    if not isinstance(role_rows, list):
        return {}
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    for row in role_rows:
        if not isinstance(row, dict):
            continue
        if (
            str(row.get("provider") or "").strip().lower() == normalized_provider
            and str(row.get("model") or "").strip().lower() == normalized_model
        ):
            return dict(row)
    return {}


@_proofs_b_checked("proofs-b.engine.routes")
def recommended_model_routes(
    profile_name: str,
    routing_strategy_override: str | None = None,
    route_overrides: list[dict] | None = None,
    objective: str | None = None,
    route_outcome_trends: dict | None = None,
) -> list[ModelRouteConfig]:
    defaults = guided_profile_defaults(profile_name)
    strategy = (routing_strategy_override or "profile_default").strip().lower()
    strategy_source = "strategy"
    if not strategy or strategy == "profile_default":
        strategy = defaults["routing_strategy"]
        strategy_source = "profile_default"
    override_map = {
        item["role"]: item for item in normalize_route_overrides(route_overrides or [])
    }
    if strategy == "uniform_quality":
        planner = (CODEX_PLANNING_PROVIDER, CODEX_PLANNING_MODEL)
        executor = ("openai", PREMIUM_OPENAI_MODEL)
    elif strategy == "budget_first":
        planner = (CODEX_PLANNING_PROVIDER, CODEX_EFFICIENT_PLANNING_MODEL)
        executor = ("openai", EFFICIENT_OPENAI_MODEL)
    else:
        planner = (CODEX_PLANNING_PROVIDER, CODEX_PLANNING_MODEL)
        executor = ("openai", EFFICIENT_OPENAI_MODEL)
    task_profile = infer_task_route_profile(objective)
    task_type = str(task_profile.get("taskType") or "general_coding")
    fit_score = int(task_profile.get("fitScore") or 0)
    executor_outcome = _route_outcome_recommendation(
        route_outcome_trends,
        task_type=task_type,
        role="executor",
    )
    verifier_outcome = _route_outcome_recommendation(
        route_outcome_trends,
        task_type=task_type,
        role="verifier",
    )
    if (
        task_profile.get("executorProvider")
        and "executor" not in override_map
        and strategy != "budget_first"
    ):
        executor = (
            str(task_profile["executorProvider"]),
            str(task_profile["executorModel"]),
        )
    specialist_executor_locked = bool(
        task_type == "frontend_design"
        and str(executor[0]).lower() == "minimax"
        and str(executor[1]) == FRONTEND_MINIMAX_MODEL
        and "executor" not in override_map
        and strategy != "budget_first"
    )
    if (
        executor_outcome
        and "executor" not in override_map
        and strategy_source == "profile_default"
        and not specialist_executor_locked
    ):
        executor = (
            str(executor_outcome.get("provider") or executor[0]),
            str(executor_outcome.get("model") or executor[1]),
        )
    executor_quarantine = _route_outcome_quarantine(
        route_outcome_trends,
        task_type=task_type,
        role="executor",
        provider=executor[0],
        model=executor[1],
    )
    if executor_quarantine and "executor" not in override_map:
        executor = (CODEX_PLANNING_PROVIDER, CODEX_PLANNING_MODEL)
    verifier = (
        str(task_profile.get("verifierProvider") or "openai"),
        str(task_profile.get("verifierModel") or PREMIUM_OPENAI_MODEL),
    )
    if verifier_outcome and "verifier" not in override_map and strategy_source == "profile_default":
        verifier = (
            str(verifier_outcome.get("provider") or verifier[0]),
            str(verifier_outcome.get("model") or verifier[1]),
        )
    verifier_quarantine = _route_outcome_quarantine(
        route_outcome_trends,
        task_type=task_type,
        role="verifier",
        provider=verifier[0],
        model=verifier[1],
    )
    if verifier_quarantine and "verifier" not in override_map:
        verifier = (CODEX_PLANNING_PROVIDER, CODEX_PLANNING_MODEL)
    executor_outcome_summary = (
        f"outcome trend: {executor_outcome.get('successRate')}% success across "
        f"{executor_outcome.get('sampleCount')} similar {task_type} executor run(s)"
        + (
            f", operator value {executor_outcome.get('operatorValueAverage')}/100 across "
            f"{executor_outcome.get('operatorValueSampleCount')} closeout(s)"
            if int(executor_outcome.get("operatorValueSampleCount", 0) or 0) > 0
            else ""
        )
        if executor_outcome
        else ""
    )
    verifier_outcome_summary = (
        f"outcome trend: {verifier_outcome.get('successRate')}% success across "
        f"{verifier_outcome.get('sampleCount')} similar {task_type} verifier run(s)"
        + (
            f", operator value {verifier_outcome.get('operatorValueAverage')}/100 across "
            f"{verifier_outcome.get('operatorValueSampleCount')} closeout(s)"
            if int(verifier_outcome.get("operatorValueSampleCount", 0) or 0) > 0
            else ""
        )
        if verifier_outcome
        else ""
    )
    routes = [
        ModelRouteConfig(
            role="planner",
            provider=planner[0],
            model=planner[1],
            effort="high",
            budget_class="specialist" if planner[0] == CODEX_PLANNING_PROVIDER else "premium",
            explanation=(
                "Planner route resolved from workspace strategy; the Codex planning lane stays responsible for decomposition, model choice, and route changes."
                if strategy_source == "strategy"
                else "Planner route resolved from profile default strategy; the Codex planning lane stays responsible for decomposition, model choice, and route changes."
            ),
            task_type=task_type,
            route_intent="mission_planning_and_route_control",
            fit_score=fit_score,
        ),
        ModelRouteConfig(
            role="executor",
            provider=executor[0],
            model=executor[1],
            effort=str(task_profile.get("executorEffort") or "high"),
            budget_class=str(
                task_profile.get("executorBudgetClass")
                or ("premium" if executor[1] == PREMIUM_OPENAI_MODEL else "efficient")
            ),
            explanation=(
                (
                    "Executor route rerouted by route-outcome quarantine: "
                    f"{executor_quarantine.get('provider')}/{executor_quarantine.get('model')} is held because "
                    f"{executor_quarantine.get('quarantineReason')}. Codex gpt-5.5 high is used until a clean value-scored sample clears the lane."
                )
                if executor_quarantine and "executor" not in override_map
                else (
                    f"Executor route selected from mission outcome history ({executor_outcome_summary})."
                    if executor_outcome
                    and "executor" not in override_map
                    and strategy_source == "profile_default"
                    and not specialist_executor_locked
                    else (
                    (
                        task_profile["reason"]
                        + (
                            f" Outcome history remains attached for scoring but does not override this specialist route ({executor_outcome_summary})."
                            if executor_outcome_summary
                            else ""
                        )
                    )
                    if specialist_executor_locked
                    else (
                        "Executor route resolved from workspace strategy."
                        if strategy_source == "strategy"
                        else "Executor route resolved from profile default strategy."
                    ))
                )
            ),
            task_type=task_type,
            route_intent=(
                "route_outcome_quarantine_reroute"
                if executor_quarantine and "executor" not in override_map
                else (
                    "outcome_trend_execution"
                    if executor_outcome
                    and "executor" not in override_map
                    and strategy_source == "profile_default"
                    and not specialist_executor_locked
                    else str(task_profile.get("routeIntent") or "workspace_strategy_execution")
                )
            ),
            fit_score=max(fit_score, int(executor_outcome.get("successRate", 0) or 0)),
            outcome_sample_count=int(executor_outcome.get("sampleCount", 0) or 0),
            outcome_success_rate=int(executor_outcome.get("successRate", 0) or 0),
            outcome_trend=(
                str(executor_quarantine.get("quarantineReason") or "")
                if executor_quarantine
                else executor_outcome_summary
            ),
        ),
        ModelRouteConfig(
            role="verifier",
            provider=verifier[0],
            model=verifier[1],
            effort="high",
            budget_class="premium",
            explanation=(
                (
                    "Verifier route rerouted by route-outcome quarantine: "
                    f"{verifier_quarantine.get('provider')}/{verifier_quarantine.get('model')} is held because "
                    f"{verifier_quarantine.get('quarantineReason')}. Codex gpt-5.5 high is used until a clean value-scored sample clears the lane."
                )
                if verifier_quarantine and "verifier" not in override_map
                else (
                    f"Verifier route selected from mission outcome history ({verifier_outcome_summary})."
                    if verifier_outcome
                    and "verifier" not in override_map
                    and strategy_source == "profile_default"
                    else "Verifier route resolved from profile confidence defaults."
                )
            ),
            task_type=task_type,
            route_intent=(
                "route_outcome_quarantine_reroute"
                if verifier_quarantine and "verifier" not in override_map
                else "outcome_trend_verification" if verifier_outcome else "independent_verification"
            ),
            fit_score=max(fit_score, int(verifier_outcome.get("successRate", 0) or 0)),
            outcome_sample_count=int(verifier_outcome.get("sampleCount", 0) or 0),
            outcome_success_rate=int(verifier_outcome.get("successRate", 0) or 0),
            outcome_trend=(
                str(verifier_quarantine.get("quarantineReason") or "")
                if verifier_quarantine
                else verifier_outcome_summary
            ),
        ),
        ModelRouteConfig(
            role="summarizer",
            provider="openai",
            model=EFFICIENT_OPENAI_MODEL,
            effort="medium",
            budget_class="efficient",
            explanation="Summaries stay efficient unless overridden.",
            task_type=task_type,
            route_intent="operator_summary",
            fit_score=fit_score,
        ),
        ModelRouteConfig(
            role="skill_curator",
            provider="openai",
            model=EFFICIENT_OPENAI_MODEL,
            effort="medium",
            budget_class="efficient",
            explanation="Skill curation is efficient and reviewable by default.",
            task_type=task_type,
            route_intent="skill_feedback_and_reuse",
            fit_score=fit_score,
        ),
        ModelRouteConfig(
            role="guide_author",
            provider="openai",
            model=EFFICIENT_OPENAI_MODEL,
            effort="medium",
            budget_class="efficient",
            explanation="Guidance and onboarding copy stay concise and adaptive to the selected profile.",
            task_type=task_type,
            route_intent="beginner_guidance",
            fit_score=fit_score,
        ),
    ]
    for index, route in enumerate(routes):
        override = override_map.get(route.role)
        if not override:
            continue
        routes[index] = ModelRouteConfig(
            role=route.role,
            provider=override.get("provider", route.provider),
            model=override.get("model", route.model),
            effort=override.get("effort", route.effort),
            budget_class=_budget_class_for_model(
                override.get("model", route.model),
                override.get("budgetClass", ""),
            ),
            fallback_policy="same_provider",
            explanation="Route override from workspace runtime contract.",
            task_type=route.task_type,
            route_intent="manual_workspace_override",
            fit_score=route.fit_score,
            outcome_sample_count=route.outcome_sample_count,
            outcome_success_rate=route.outcome_success_rate,
            outcome_trend=route.outcome_trend,
        )
    for role, route_intent, explanation in (
        (
            "backend",
            "backend_execution",
            "Backend route override from workspace runtime contract.",
        ),
        (
            "frontend",
            "frontend_execution",
            "Frontend route override from workspace runtime contract.",
        ),
    ):
        override = override_map.get(role)
        if not override or any(route.role == role for route in routes):
            continue
        routes.append(
            ModelRouteConfig(
                role=role,
                provider=override.get("provider", ""),
                model=override.get("model", ""),
                effort=override.get("effort", "high"),
                budget_class=_budget_class_for_model(
                    override.get("model", ""),
                    override.get("budgetClass", ""),
                ),
                fallback_policy="same_provider",
                explanation=explanation,
                task_type=task_type,
                route_intent=route_intent,
                fit_score=fit_score,
            )
        )
    return routes


class LegacyHarnessAdapter:
    harness_id = "legacy_autonomous_engine"

    def __init__(self, engine: AutonomousEngine) -> None:
        self.engine = engine

    def run(self, **kwargs: object) -> dict:
        return self.engine.run(**kwargs)


class FluxioHarness:
    harness_id = "fluxio_hybrid"

    def __init__(
        self,
        compatibility_harness: LegacyHarnessAdapter,
        session_store: SessionStore,
        verification_runner: VerificationRunner,
        skill_library: SkillLibrary,
    ) -> None:
        self.compatibility_harness = compatibility_harness
        self.session_store = session_store
        self.verification_runner = verification_runner
        self.skill_library = skill_library

    def run(
        self,
        objective: str,
        docs: list[str],
        project_profile: str,
        verify_commands: list[str],
        repo_path: Path,
        iterations: int,
        max_handoffs: int,
        max_runtime_seconds: int,
        mission_id: str | None = None,
        runtime_id: str = "hermes",
        profile_name: str = "builder",
        selected_profile: PersonalizationProfile | None = None,
        resume_from_session_id: str | None = None,
        resume_from_checkpoint_path: str | None = None,
        checkpoint_every: int = 1,
        autopilot_guardrails: dict | None = None,
        routing_strategy_override: str | None = None,
        route_overrides: list[dict] | None = None,
        execution_target_preference: str | None = None,
        max_tokens: int | None = None,
        parallel_agents: int | None = None,
        merge_policy: str | None = None,
        code_execution_config: dict | None = None,
    ) -> dict:
        guardrails = autopilot_guardrails or {
            "pause_on_handoff": True,
            "pause_on_verification_failure": True,
        }
        started_at = time.monotonic()
        resolved_mission_id = mission_id or f"mission_{uuid.uuid4().hex[:8]}"
        profile_defaults = guided_profile_defaults(profile_name)
        profile_agent = selected_profile.agent if selected_profile else None
        resolved_max_tokens = max(
            256,
            int(
                max_tokens
                if max_tokens is not None
                else (
                    profile_agent.max_tokens
                    if profile_agent and profile_agent.max_tokens is not None
                    else DEFAULT_FLUXIO_MAX_TOKENS
                )
            ),
        )
        resolved_parallel_agents = max(
            1,
            int(
                parallel_agents
                if parallel_agents is not None
                else (
                    profile_agent.parallel_agents
                    if profile_agent and profile_agent.parallel_agents is not None
                    else 1
                )
            ),
        )
        requested_merge_policy = (
            merge_policy
            or (
                profile_agent.merge_policy
                if profile_agent and profile_agent.merge_policy
                else DEFAULT_FLUXIO_MERGE_POLICY
            )
        )
        resolved_merge_policy = (
            requested_merge_policy
            if requested_merge_policy in VALID_MERGE_POLICIES
            else DEFAULT_FLUXIO_MERGE_POLICY
        )
        route_outcome_trends = build_route_outcome_trends(repo_path)
        route_configs = recommended_model_routes(
            profile_name,
            routing_strategy_override=routing_strategy_override,
            route_overrides=route_overrides,
            objective=objective,
            route_outcome_trends=route_outcome_trends,
        )
        execution_policy = normalize_execution_policy(build_execution_policy(profile_name))
        requested_execution_scope = (
            requested_scope_for_execution_target(execution_target_preference)
            or profile_defaults.get("execution_scope", "")
        )
        execution_scope = prepare_execution_scope(
            workspace_root=repo_path,
            mission_id=resolved_mission_id,
            requested_scope=requested_execution_scope,
            profile_name=profile_name,
        )
        execution_context = HarnessExecutionContext(
            mission_id=resolved_mission_id,
            workspace_root=str(repo_path),
            runtime_id=runtime_id,
            profile_name=profile_name,
            execution_scope=execution_scope,
            execution_policy=execution_policy,
            route_configs=route_configs,
            broadening_threshold=int(
                profile_defaults["repeated_failure_broadening_threshold"]
            ),
            innovation_scope=str(profile_defaults["innovation_scope"]),
            harness_id=self.harness_id,
        )
        context_manager = ContextWindowManager(max_tokens=resolved_max_tokens)
        prompt_stack = self._build_prompt_stack(
            objective=objective,
            project_profile=project_profile,
            profile_name=profile_name,
            selected_profile=selected_profile,
        )

        resumed_state: dict | None = None
        if resume_from_session_id:
            previous_path = self.session_store.get_session_path(resume_from_session_id)
            if previous_path and (previous_path / "state.json").exists():
                resumed_state = self.session_store.read_state(previous_path)
                if not docs:
                    docs = [
                        item.get("source", "")
                        for item in resumed_state.get("doc_evidence", [])
                        if item.get("source")
                    ]
        if resume_from_checkpoint_path:
            checkpoint_payload = CheckpointStore.load(Path(resume_from_checkpoint_path))
            resumed_state = checkpoint_payload.get("state", resumed_state)
            if not docs:
                docs = checkpoint_payload.get("doc_sources", docs)
        if resumed_state:
            loaded_scope = self._load_execution_scope(resumed_state)
            loaded_policy = self._load_execution_policy(resumed_state)
            loaded_routes = self._load_route_configs(resumed_state)
            if loaded_scope is not None:
                explicit_isolated_scope = (
                    requested_execution_scope == "isolated"
                    and bool(getattr(execution_scope, "isolated", False))
                )
                stale_direct_scope = not bool(getattr(loaded_scope, "isolated", False))
                if not (explicit_isolated_scope and stale_direct_scope):
                    execution_scope = loaded_scope
            if loaded_policy is not None:
                execution_policy = normalize_execution_policy(loaded_policy)
            keep_loaded_routes = bool(
                loaded_routes
                and not normalize_route_overrides(route_overrides or [])
                and (
                    not routing_strategy_override
                    or routing_strategy_override == "profile_default"
                )
            )
            if keep_loaded_routes:
                route_configs = loaded_routes
            execution_context.execution_scope = execution_scope
            execution_context.execution_policy = execution_policy
            execution_context.route_configs = route_configs

        session_path = self.session_store.create_session(
            objective=objective,
            parent_session_id=resume_from_session_id,
        )
        metadata = self.session_store.read_metadata(session_path)
        session_id = metadata["session_id"]
        lineage = []
        if resumed_state:
            lineage.extend(resumed_state.get("session_lineage", []))
        lineage.append(session_id)
        checkpoint_store = CheckpointStore(session_path)
        docs_evidence = ingest_docs(docs=docs, repo_path=repo_path, session_path=session_path)
        plan_bundle = build_docs_first_plan(objective=objective, docs=docs)

        plan_revisions = self._load_plan_revisions(resumed_state, plan_bundle)
        derived_tasks = self._load_derived_tasks(resumed_state)
        improvement_queue = self._load_improvement_queue(resumed_state)
        action_history = self._load_action_history(resumed_state)
        routing_decisions = self._load_routing_decisions(resumed_state)
        verification_failures = (
            list(resumed_state.get("verification_failures", []))
            if resumed_state
            else []
        )
        handoff_paths = list(resumed_state.get("handoff_packets", [])) if resumed_state else []
        handoff_count = len(handoff_paths)
        stable_success_streak = int(
            resumed_state.get("stable_success_streak", 0)
        ) if resumed_state else 0
        route_change_count = int(
            resumed_state.get("route_change_count", 0)
        ) if resumed_state else 0
        runtime_autonomy_history = (
            list(resumed_state.get("runtime_autonomy_history", []))
            if resumed_state
            else []
        )
        runtime_autonomy = (
            dict(resumed_state.get("runtime_autonomy", {}))
            if resumed_state
            else {}
        )
        blocker_history = (
            list(resumed_state.get("blocker_history", []))
            if resumed_state and isinstance(resumed_state.get("blocker_history"), list)
            else []
        )
        latest_blocker = (
            dict(resumed_state.get("latest_blocker", {}))
            if resumed_state and isinstance(resumed_state.get("latest_blocker"), dict)
            else {}
        )
        blocker_retry_counts = (
            dict(resumed_state.get("blocker_retry_counts", {}))
            if resumed_state and isinstance(resumed_state.get("blocker_retry_counts"), dict)
            else {}
        )
        code_execution = self._resolve_code_execution_config(
            requested_config=code_execution_config,
            resumed_state=resumed_state,
            mission_id=resolved_mission_id,
        )
        code_execution_state = self._load_code_execution_state(
            resumed_state=resumed_state,
            code_execution=code_execution,
        )
        selected_skills = self.skill_library.retrieve(task_brief=objective, top_k=4)
        skill_usage = list(resumed_state.get("skill_usage", [])) if resumed_state else []
        learned_skill_events = (
            list(resumed_state.get("learned_skill_events", [])) if resumed_state else []
        )
        skill_feedback_events = (
            list(resumed_state.get("skill_feedback_events", [])) if resumed_state else []
        )
        delegated_runtime_sessions = (
            list(resumed_state.get("delegated_runtime_sessions", []))
            if resumed_state
            else []
        )
        changed_files = list(resumed_state.get("changed_files", [])) if resumed_state else []
        decisions = list(resumed_state.get("decisions", [])) if resumed_state else []
        risks = list(resumed_state.get("risks", [])) if resumed_state else []
        completed_steps = (
            list(resumed_state.get("completed_steps", [])) if resumed_state else []
        )
        notes = list(resumed_state.get("notes", [])) if resumed_state else []
        autopilot_status = "running"
        autopilot_pause_reason = ""
        last_verification_results: list[VerificationResult] = []
        repeated_failure_count = (
            int(resumed_state.get("repeated_failure_count", 0)) if resumed_state else 0
        )
        context_seed = (
            list(resumed_state.get("context_seed", []))
            if resumed_state and isinstance(resumed_state.get("context_seed"), list)
            else []
        )
        if context_seed:
            context_manager.reset_with_seed(context_seed)
        else:
            context_manager.record("system", RUNTIME_CONSTITUTION_TEXT)
            context_manager.record("system", f"Project profile: {project_profile}")
            context_manager.record("user", objective)

        decisions.append("Neyvia hybrid harness orchestrated this mission.")
        if selected_profile:
            decisions.append(f"Resolved profile: {selected_profile.name}")
        notes.append(
            f"Role-based routing: {', '.join([item.role + '=' + item.model for item in route_configs])}"
        )
        notes.append(
            f"Selected skills: {', '.join([item['label'] for item in selected_skills]) or 'none'}"
        )
        notes.append(
            f"Execution scope: {execution_scope.strategy} at {execution_scope.execution_root or repo_path}"
        )
        notes.append(
            f"Execution policy: {execution_policy.approval_mode} approvals with {execution_policy.delegation_aggressiveness} delegation."
        )
        notes.append(
            f"Runtime controls: context={resolved_max_tokens} tokens, parallel_agents={resolved_parallel_agents}, merge_policy={resolved_merge_policy}."
        )
        if code_execution.get("enabled"):
            notes.append(
                "Code execution enabled with persistent container "
                f"{code_execution.get('container_id') or code_execution_state.get('container_id') or 'auto'}."
            )
        if resumed_state:
            context_manager.record(
                "system",
                (
                    f"Resumed from prior session with {len(completed_steps)} completed step(s), "
                    f"{len(verification_failures)} outstanding verification failure(s), and "
                    f"{len(delegated_runtime_sessions)} delegated lane(s)."
                ),
            )
        context_manager.record(
            "system",
            f"Resolved route contract: {', '.join([item.role + '=' + item.model for item in route_configs])}",
        )
        if code_execution.get("enabled"):
            context_manager.record(
                "system",
                (
                    "Mission code execution is enabled with container "
                    f"{code_execution_state.get('container_id') or code_execution.get('container_id') or 'auto'}."
                ),
            )
        execution_root = Path(execution_scope.execution_root or repo_path)
        runtime_supervisor = DelegatedRuntimeSupervisor(repo_path)

        self.session_store.append_timeline(
            session_path,
            TimelineEvent(
                kind="harness.started",
                message="Neyvia harness started mission execution.",
                metadata={
                    "mission_id": execution_context.mission_id,
                    "runtime_id": runtime_id,
                    "profile_name": profile_name,
                },
            ),
        )
        self.session_store.append_timeline(
            session_path,
            TimelineEvent(
                kind="runtime.controls",
                message="Neyvia resolved runtime continuity controls.",
                metadata={
                    "max_tokens": resolved_max_tokens,
                    "parallel_agents": resolved_parallel_agents,
                    "merge_policy": resolved_merge_policy,
                    "max_handoffs": max_handoffs,
                    "code_execution": bool(code_execution.get("enabled")),
                    "code_execution_container_id": code_execution_state.get("container_id", ""),
                },
            ),
        )

        for role in (
            "planner",
            "backend",
            "frontend",
            "executor",
            "verifier",
            "summarizer",
            "skill_curator",
            "guide_author",
        ):
            route = next((item for item in route_configs if item.role == role), None)
            if route:
                routing_decisions.append(
                    asdict(
                        RoutingDecision(
                            role=route.role,
                            provider=route.provider,
                            model=route.model,
                            reason=route.explanation,
                            budget_class=route.budget_class,
                            task_type=route.task_type,
                            route_intent=route.route_intent,
                            fit_score=route.fit_score,
                            outcome_sample_count=route.outcome_sample_count,
                            outcome_success_rate=route.outcome_success_rate,
                            outcome_trend=route.outcome_trend,
                        )
                    )
                )
        delegated_status = ""

        (
            route_configs,
            execution_policy,
            runtime_autonomy,
            autonomy_changed,
            route_change_count,
        ) = self._apply_runtime_autonomy(
            profile_name=profile_name,
            route_configs=route_configs,
            route_overrides=route_overrides or [],
            execution_policy=execution_policy,
            repeated_failure_count=repeated_failure_count,
            verification_failures=verification_failures,
            stable_success_streak=stable_success_streak,
            context_status=context_manager.status(),
            delegated_status="",
            route_change_count=route_change_count,
            parallel_agents=resolved_parallel_agents,
            merge_policy=resolved_merge_policy,
            max_tokens=resolved_max_tokens,
            requested_strategy_override=routing_strategy_override,
            objective=objective,
            workspace_root=repo_path,
        )
        if autonomy_changed:
            for route in route_configs:
                if route.role not in {"planner", "executor", "verifier"}:
                    continue
                routing_decisions.append(
                    asdict(
                        RoutingDecision(
                            role=route.role,
                            provider=route.provider,
                            model=route.model,
                            reason=runtime_autonomy["reason"],
                            budget_class=route.budget_class,
                            task_type=route.task_type,
                            route_intent=route.route_intent,
                            fit_score=route.fit_score,
                            outcome_sample_count=route.outcome_sample_count,
                            outcome_success_rate=route.outcome_success_rate,
                            outcome_trend=route.outcome_trend,
                        )
                    )
                )
            runtime_autonomy_history.append(runtime_autonomy)
            runtime_autonomy_history = runtime_autonomy_history[-AUTONOMY_HISTORY_LIMIT:]
            self.session_store.append_timeline(
                session_path,
                TimelineEvent(
                    kind="runtime.autonomy.updated",
                    message=runtime_autonomy["reason"],
                    metadata=runtime_autonomy,
                ),
            )
            context_manager.record("system", f"Runtime autonomy adjusted: {runtime_autonomy['reason']}")

        for iteration in range(1, iterations + 1):
            (
                delegated_runtime_sessions,
                delegated_status,
                delegated_replan_trigger,
            ) = self._reconcile_delegated_sessions(
                delegated_runtime_sessions=delegated_runtime_sessions,
                plan_revisions=plan_revisions,
                runtime_supervisor=runtime_supervisor,
                notes=notes,
                risks=risks,
                objective=objective,
                route_configs=route_configs,
            )
            if delegated_status == "running":
                (
                    delegated_runtime_sessions,
                    delegated_status,
                    delegated_replan_trigger,
                ) = self._follow_delegated_sessions(
                    delegated_runtime_sessions=delegated_runtime_sessions,
                    plan_revisions=plan_revisions,
                    runtime_supervisor=runtime_supervisor,
                    notes=notes,
                    risks=risks,
                    objective=objective,
                    route_configs=route_configs,
                    wait_seconds=self._delegated_follow_budget_seconds(
                        started_at=started_at,
                        max_runtime_seconds=max_runtime_seconds,
                        parallel_agents=resolved_parallel_agents,
                        context_status=context_manager.status(),
                    ),
                )
            if delegated_status == "waiting_for_approval":
                autopilot_status = "paused"
                autopilot_pause_reason = "approval_required"
                blocker_history, latest_blocker = self._remember_blocker(
                    blocker=self._classify_blocker(
                        reason="approval_required",
                        detail="Delegated runtime is waiting for operator approval.",
                        phase="execute",
                        runtime_id=runtime_id,
                    ),
                    blocker_history=blocker_history,
                )
                context_manager.record("system", "Delegated runtime is waiting for approval.")
                break
            if delegated_replan_trigger == "approval_rejected":
                repeated_failure_count += 1
                stable_success_streak = 0
                self._append_revised_plan(
                    plan_revisions=plan_revisions,
                    base_revision=plan_revisions[-1],
                    trigger="approval_rejected",
                    summary="Planner revised the mission after a delegated approval was rejected.",
                    extra_steps=[
                        PlannedStep(
                            step_id=f"step_{uuid.uuid4().hex[:8]}",
                            title="Replan after delegated approval rejection",
                            description="Find a safer path after the delegated lane was rejected.",
                            kind="derived",
                        )
                    ],
                )
                continue
            if delegated_replan_trigger == "delegated_runtime_failed":
                autopilot_status = "paused"
                autopilot_pause_reason = "delegated_runtime_failed"
                blocker_history, latest_blocker = self._remember_blocker(
                    blocker=self._classify_blocker(
                        reason="delegated_runtime_failed",
                        detail="Delegated runtime failed before producing a usable result. Repair runtime auth or route selection before continuing.",
                        phase="execute",
                        runtime_id=runtime_id,
                    ),
                    blocker_history=blocker_history,
                )
                context_manager.record(
                    "system",
                    "Delegated runtime failed; Neyvia paused instead of retrying the same failing lane.",
                )
                break
            if delegated_status == "running":
                blocker = self._classify_blocker(
                    reason="delegated_runtime_running",
                    detail="Delegated runtime is still running after the follow budget.",
                    phase="execute",
                    runtime_id=runtime_id,
                )
                retry_key = blocker["kind"]
                retry_count = int(blocker_retry_counts.get(retry_key, 0) or 0)
                if retry_count < 1:
                    blocker_retry_counts[retry_key] = retry_count + 1
                    decisions.append(
                        "Neyvia retried delegated lane follow-up once before pausing."
                    )
                    notes.append(
                        "Delegated runtime remained active; Neyvia is retrying the follow loop once."
                    )
                    context_manager.record(
                        "system",
                        "Delegated runtime is still running; Neyvia is retrying before pausing.",
                    )
                    continue
                autopilot_status = "paused"
                autopilot_pause_reason = "delegated_runtime_running"
                blocker_history, latest_blocker = self._remember_blocker(
                    blocker=blocker,
                    blocker_history=blocker_history,
                )
                context_manager.record("system", "Delegated runtime is still running after the follow budget.")
                break

            (
                route_configs,
                execution_policy,
                runtime_autonomy,
                autonomy_changed,
                route_change_count,
            ) = self._apply_runtime_autonomy(
                profile_name=profile_name,
                route_configs=route_configs,
                route_overrides=route_overrides or [],
                execution_policy=execution_policy,
                repeated_failure_count=repeated_failure_count,
                verification_failures=verification_failures,
                stable_success_streak=stable_success_streak,
                context_status=context_manager.status(),
                delegated_status=delegated_status,
                route_change_count=route_change_count,
                parallel_agents=resolved_parallel_agents,
                merge_policy=resolved_merge_policy,
                max_tokens=resolved_max_tokens,
                requested_strategy_override=routing_strategy_override,
                objective=objective,
                workspace_root=repo_path,
            )
            if autonomy_changed:
                for route in route_configs:
                    if route.role not in {"planner", "executor", "verifier"}:
                        continue
                    routing_decisions.append(
                        asdict(
                            RoutingDecision(
                                role=route.role,
                                provider=route.provider,
                                model=route.model,
                                reason=runtime_autonomy["reason"],
                                budget_class=route.budget_class,
                                task_type=route.task_type,
                                route_intent=route.route_intent,
                                fit_score=route.fit_score,
                                outcome_sample_count=route.outcome_sample_count,
                                outcome_success_rate=route.outcome_success_rate,
                                outcome_trend=route.outcome_trend,
                            )
                        )
                    )
                runtime_autonomy_history.append(runtime_autonomy)
                runtime_autonomy_history = runtime_autonomy_history[-AUTONOMY_HISTORY_LIMIT:]
                self.session_store.append_timeline(
                    session_path,
                    TimelineEvent(
                        kind="runtime.autonomy.updated",
                        message=runtime_autonomy["reason"],
                        metadata=runtime_autonomy,
                    ),
                )
                context_manager.record("system", f"Runtime autonomy adjusted: {runtime_autonomy['reason']}")

            if time.monotonic() - started_at >= max_runtime_seconds:
                autopilot_status = "paused"
                autopilot_pause_reason = "runtime_budget"
                decisions.append("Mission paused because runtime budget was exhausted.")
                blocker_history, latest_blocker = self._remember_blocker(
                    blocker=self._classify_blocker(
                        reason="runtime_budget",
                        detail="Mission paused because runtime budget was exhausted.",
                        phase="execute",
                        runtime_id=runtime_id,
                    ),
                    blocker_history=blocker_history,
                )
                break

            latest_revision = plan_revisions[-1]
            next_step = self._next_pending_step(latest_revision)
            if next_step is None:
                autopilot_status = "completed"
                break

            self.session_store.append_timeline(
                session_path,
                TimelineEvent(
                    kind="plan.revision",
                    message=f"Planner selected step: {next_step.title}",
                    metadata={
                        "revision_id": latest_revision.revision_id,
                        "active_step_id": next_step.step_id,
                    },
                ),
            )
            context_manager.record("system", f"Planner selected step: {next_step.title}")

            execution_record = None
            pending_approval = self._resolve_pending_action_if_any(
                action_history=action_history,
                workspace_root=execution_root,
                execution_scope=execution_scope,
                execution_policy=execution_policy,
            )
            if pending_approval is not None:
                if pending_approval.gate.status == "pending":
                    autopilot_status = "paused"
                    autopilot_pause_reason = "approval_required"
                    notes.append("Harness detected a pending approval gate and paused safely.")
                    blocker_history, latest_blocker = self._remember_blocker(
                        blocker=self._classify_blocker(
                            reason="approval_required",
                            detail="A pending operator approval blocked the next action.",
                            phase="execute",
                            runtime_id=runtime_id,
                        ),
                        blocker_history=blocker_history,
                    )
                    context_manager.record("system", "A pending operator approval blocked the next action.")
                    break
                if pending_approval.gate.status == "rejected":
                    repeated_failure_count += 1
                    stable_success_streak = 0
                    risks.append("Operator rejected a high-risk action; replanning required.")
                    self._append_revised_plan(
                        plan_revisions=plan_revisions,
                        base_revision=latest_revision,
                        trigger="approval_rejected",
                        summary="Planner revised the mission after a rejected high-risk action.",
                        extra_steps=[
                            PlannedStep(
                                step_id=f"step_{uuid.uuid4().hex[:8]}",
                                title="Inspect environment and dependency assumptions",
                                description="Broaden the search after the rejected action.",
                                kind="derived",
                            )
                        ],
                    )
                    action_history[-1] = asdict(pending_approval)
                    context_manager.record(
                        "system",
                        "Operator rejected a high-risk action and triggered replanning.",
                    )
                    continue
                execution_record = pending_approval
                action_history[-1] = asdict(execution_record)

            if execution_record is None:
                proposal = build_action_proposal(
                    step=next_step,
                    objective=objective,
                    workspace_root=repo_path,
                    verification_commands=verify_commands,
                    runtime_id=runtime_id,
                    execution_scope=execution_scope,
                    execution_policy=execution_policy,
                    route_configs=route_configs,
                )
                if proposal.kind == "runtime_delegate":
                    proposal.delegation_metadata["parent_mission_id"] = (
                        execution_context.mission_id
                    )
                self.session_store.append_timeline(
                    session_path,
                    TimelineEvent(
                        kind="action.proposed",
                        message=proposal.title,
                        metadata=asdict(proposal),
                    ),
                )
                context_manager.record(
                    "system",
                    f"Proposed action: {proposal.title}. Policy decision: {proposal.policy_decision}.",
                )

                execution_record = execute_action(
                    proposal,
                    repo_path,
                    execution_scope=execution_scope,
                    execution_policy=execution_policy,
                )
                action_history.append(asdict(execution_record))

            if execution_record.gate.status == "pending":
                autopilot_status = "paused"
                autopilot_pause_reason = "approval_required"
                risks.append("A high-risk action was proposed and is waiting for operator approval.")
                next_step.notes.append("Pending approval before execution.")
                latest_revision.active_step_id = next_step.step_id
                blocker_history, latest_blocker = self._remember_blocker(
                    blocker=self._classify_blocker(
                        reason="approval_required",
                        detail=f"Action waiting for approval: {execution_record.proposal.title}",
                        phase="execute",
                        runtime_id=runtime_id,
                    ),
                    blocker_history=blocker_history,
                )
                context_manager.record("system", f"Action is waiting for operator approval: {execution_record.proposal.title}")
                break

            if code_execution.get("enabled"):
                code_execution_state = self._record_code_execution_artifact(
                    code_execution_state=code_execution_state,
                    code_execution=code_execution,
                    execution_record=execution_record,
                )

            delegated_payload = execution_record.result.payload.get("delegatedSession", {})
            if execution_record.proposal.kind == "runtime_delegate" and delegated_payload:
                next_step.status = "in_progress"
                latest_revision.active_step_id = next_step.step_id
                delegated_runtime_sessions = [
                    item
                    for item in delegated_runtime_sessions
                    if item.get("delegated_id") != delegated_payload.get("delegated_id")
                ]
                delegated_runtime_sessions.append(delegated_payload)
                notes.append("Delegated runtime lane launched; Neyvia will resume once it completes.")
                context_manager.record(
                    "system",
                    f"Delegated runtime lane launched for step {next_step.title}.",
                )
                (
                    delegated_runtime_sessions,
                    delegated_status,
                    delegated_replan_trigger,
                ) = self._follow_delegated_sessions(
                    delegated_runtime_sessions=delegated_runtime_sessions,
                    plan_revisions=plan_revisions,
                    runtime_supervisor=runtime_supervisor,
                    notes=notes,
                    risks=risks,
                    objective=objective,
                    route_configs=route_configs,
                    wait_seconds=self._delegated_follow_budget_seconds(
                        started_at=started_at,
                        max_runtime_seconds=max_runtime_seconds,
                        parallel_agents=resolved_parallel_agents,
                        context_status=context_manager.status(),
                    ),
                )
                if delegated_replan_trigger == "approval_rejected":
                    repeated_failure_count += 1
                    stable_success_streak = 0
                    continue
                if delegated_replan_trigger == "delegated_runtime_failed":
                    autopilot_status = "paused"
                    autopilot_pause_reason = "delegated_runtime_failed"
                    blocker_history, latest_blocker = self._remember_blocker(
                        blocker=self._classify_blocker(
                            reason="delegated_runtime_failed",
                            detail="Delegated runtime failed after launch. Repair runtime auth or route selection before continuing.",
                            phase="execute",
                            runtime_id=runtime_id,
                        ),
                        blocker_history=blocker_history,
                    )
                    break
                if delegated_status == "waiting_for_approval":
                    autopilot_status = "paused"
                    autopilot_pause_reason = "approval_required"
                    blocker_history, latest_blocker = self._remember_blocker(
                        blocker=self._classify_blocker(
                            reason="approval_required",
                            detail="Delegated runtime requires approval after launch.",
                            phase="execute",
                            runtime_id=runtime_id,
                        ),
                        blocker_history=blocker_history,
                    )
                    break
                if delegated_status == "running":
                    blocker = self._classify_blocker(
                        reason="delegated_runtime_running",
                        detail="Delegated runtime is still running after launch follow budget.",
                        phase="execute",
                        runtime_id=runtime_id,
                    )
                    retry_key = blocker["kind"]
                    retry_count = int(blocker_retry_counts.get(retry_key, 0) or 0)
                    if retry_count < 1:
                        blocker_retry_counts[retry_key] = retry_count + 1
                        notes.append(
                            "Delegated runtime remained active after launch; Neyvia retries once before pausing."
                        )
                        continue
                    autopilot_status = "paused"
                    autopilot_pause_reason = "delegated_runtime_running"
                    blocker_history, latest_blocker = self._remember_blocker(
                        blocker=blocker,
                        blocker_history=blocker_history,
                    )
                    break
                context_manager.record(
                    "system",
                    f"Delegated runtime lane settled within the same control cycle for step {next_step.title}.",
                )
                continue

            if execution_record.result.ok:
                next_step.status = "completed"
                completed_steps.append(next_step.title)
                changed_files = list(
                    dict.fromkeys(changed_files + execution_record.result.changed_files)
                )
                repeated_failure_count = 0
                stable_success_streak += 1
                skill_record = self.skill_library.record_usage(
                    skill_id=selected_skills[0]["skillId"] if selected_skills else "curated:repo_scan",
                    label=selected_skills[0]["label"] if selected_skills else "Repo Scan",
                    step_id=next_step.step_id,
                    mission_id=execution_context.mission_id,
                    helped=True,
                    source_kind=selected_skills[0]["sourceKind"] if selected_skills else "curated",
                )
                skill_usage.append(asdict(skill_record))
            else:
                next_step.attempts += 1
                next_step.status = "blocked"
                repeated_failure_count += 1
                stable_success_streak = 0
                risks.append(
                    execution_record.result.error
                    or execution_record.result.stderr
                    or "Action execution failed."
                )
            context_manager.record(
                "system",
                self._execution_result_summary(execution_record),
            )

            high_risk_verification_commands = [
                command for command in verify_commands if risk_level_for_command(command) == "high"
            ]
            if high_risk_verification_commands:
                autopilot_status = "paused"
                autopilot_pause_reason = "approval_required"
                risks.append("A high-risk verification command is waiting for operator approval.")
                blocker_history, latest_blocker = self._remember_blocker(
                    blocker=self._classify_blocker(
                        reason="approval_required",
                        detail=(
                            "Verification command requires approval before execution: "
                            f"{high_risk_verification_commands[0]}"
                        ),
                        phase="verify",
                        runtime_id=runtime_id,
                    ),
                    blocker_history=blocker_history,
                )
                context_manager.record(
                    "system",
                    "Verification command requires operator approval before execution.",
                )
                break

            last_verification_results = self.verification_runner.run(
                verify_commands, execution_root
            )
            verification_failures = [
                item.command
                for item in last_verification_results
                if item.return_code != 0 or item.status != "executed"
            ]
            if verification_failures:
                stable_success_streak = 0
            context_manager.record(
                "system",
                self._verification_summary(last_verification_results),
            )
            slice_feedback = self.skill_library.record_slice_feedback(
                mission_id=execution_context.mission_id,
                step_id=next_step.step_id,
                selected_skills=selected_skills,
                execution_ok=execution_record.result.ok and not verification_failures,
                verification_failures=verification_failures,
                changed_files=execution_record.result.changed_files,
            )
            skill_feedback_events.extend(slice_feedback)
            learned_skill_events.extend(
                {
                    "kind": "skill.slice_feedback",
                    "label": item.get("label", ""),
                    "system_loss": item.get("systemLoss"),
                    "improvement_score": item.get("improvementScore"),
                    "next_action": item.get("nextAction"),
                    "timestamp": item.get("createdAt"),
                }
                for item in slice_feedback
            )
            if verification_failures:
                improvement_queue.extend(
                    [
                        ImprovementQueueItem(
                            item_id=f"improve_{uuid.uuid4().hex[:8]}",
                            title=f"Verification follow-up: {command}",
                            reason="Verification failed and needs explicit follow-up.",
                            priority="high",
                            in_mission_scope=True,
                            category="verification",
                            source_step_id=next_step.step_id,
                        )
                        for command in verification_failures
                    ]
                )
                auto_replanned_on_verification = False
                if guardrails.get("pause_on_verification_failure", True):
                    blocker = self._classify_blocker(
                        reason="verification_failed",
                        detail=self._verification_summary(last_verification_results),
                        phase="verify",
                        runtime_id=runtime_id,
                    )
                    retry_key = blocker["kind"]
                    retry_count = int(blocker_retry_counts.get(retry_key, 0) or 0)
                    if retry_count < 1:
                        blocker_retry_counts[retry_key] = retry_count + 1
                        auto_replanned_on_verification = True
                        decisions.append(
                            "Neyvia auto-replanned once after verification failure."
                        )
                        notes.append(
                            "Verification failed; Neyvia queued an automatic replan before pausing."
                        )
                        self._append_revised_plan(
                            plan_revisions=plan_revisions,
                            base_revision=latest_revision,
                            trigger="auto_replan_verification",
                            summary="Neyvia auto-replanned after verification failed.",
                            extra_steps=[
                                PlannedStep(
                                    step_id=f"step_{uuid.uuid4().hex[:8]}",
                                    title="Repair verification failure and rerun proof",
                                    description="Focus on failing checks before requesting operator input.",
                                    kind="derived",
                                )
                            ],
                        )
                        context_manager.record(
                            "system",
                            "Verification failed; Neyvia auto-replanned and will retry once.",
                        )
                    else:
                        autopilot_status = "paused"
                        autopilot_pause_reason = "verification_failed"
                        blocker_history, latest_blocker = self._remember_blocker(
                            blocker=blocker,
                            blocker_history=blocker_history,
                        )
                if auto_replanned_on_verification:
                    continue

            if repeated_failure_count >= execution_context.broadening_threshold:
                derived = DerivedTask(
                    task_id=f"derived_{uuid.uuid4().hex[:8]}",
                    title="Inspect dependencies, environment, and configuration",
                    reason="Repeated failures triggered Hermes-style problem broadening.",
                    source_step_id=next_step.step_id,
                    status="pending",
                    priority="high",
                    attempt_count=repeated_failure_count,
                )
                if not any(item.title == derived.title for item in derived_tasks):
                    derived_tasks.append(derived)
                self._append_revised_plan(
                    plan_revisions=plan_revisions,
                    base_revision=latest_revision,
                    trigger="repeated_failure_broadening",
                    summary="Planner broadened the search after repeated failures.",
                    extra_steps=[
                        PlannedStep(
                            step_id=f"step_{uuid.uuid4().hex[:8]}",
                            title=derived.title,
                            description=derived.reason,
                            kind="derived",
                        )
                    ],
                )
            else:
                self._append_revised_plan(
                    plan_revisions=plan_revisions,
                    base_revision=latest_revision,
                    trigger="action_completed" if execution_record.result.ok else "action_failed",
                    summary=(
                        "Planner revised the next steps after a successful action."
                        if execution_record.result.ok
                        else "Planner revised the next steps after an action failure."
                    ),
                    extra_steps=[],
                )

            promotion_candidates = self.skill_library.suggest_promotions(
                mission_id=execution_context.mission_id,
                objective=objective,
                selected_skills=selected_skills,
                verification_failures=verification_failures,
            )
            promoted = self.skill_library.promote_candidates(promotion_candidates)
            for item in promoted:
                learned_skill_events.append(
                    {
                        "kind": "skill.promoted",
                        "label": item.label,
                        "confidence": item.confidence,
                        "timestamp": utc_now_iso(),
                    }
                )

            if checkpoint_every and iteration % checkpoint_every == 0:
                checkpoint_store.save(
                    session_id=session_id,
                    iteration=iteration,
                    run_state=self._build_run_state(
                        objective=objective,
                        acceptance_checks=plan_bundle.acceptance_checks,
                        plan_revisions=plan_revisions,
                        completed_steps=completed_steps,
                        decisions=decisions,
                        changed_files=changed_files,
                        risks=risks,
                        verification_results=last_verification_results,
                        selected_skills=selected_skills,
                        notes=notes,
                    ),
                    context=self._context_snapshot(context_manager),
                    doc_sources=docs,
                )

            context_status = context_manager.status()
            if context_status in {"rollover", "hard_stop"}:
                if handoff_count >= max_handoffs:
                    autopilot_status = "paused"
                    autopilot_pause_reason = "handoff_budget"
                    risks.append(
                        f"Context rollover requested but max handoffs budget ({max_handoffs}) was reached."
                    )
                    self.session_store.append_timeline(
                        session_path,
                        TimelineEvent(
                            kind="runtime.context_budget",
                            message="Neyvia hit the handoff budget before it could compact context again.",
                            metadata={
                                "handoff_count": handoff_count,
                                "max_handoffs": max_handoffs,
                                "context_status": context_status,
                            },
                        ),
                    )
                    blocker_history, latest_blocker = self._remember_blocker(
                        blocker=self._classify_blocker(
                            reason="handoff_budget",
                            detail=(
                                f"Context rollover requested but max handoffs budget ({max_handoffs}) was reached."
                            ),
                            phase=context_status,
                            runtime_id=runtime_id,
                        ),
                        blocker_history=blocker_history,
                    )
                    break
                handoff_count += 1
                run_state = self._build_run_state(
                    objective=objective,
                    acceptance_checks=plan_bundle.acceptance_checks,
                    plan_revisions=plan_revisions,
                    completed_steps=completed_steps,
                    decisions=decisions,
                    changed_files=changed_files,
                    risks=risks,
                    verification_results=last_verification_results,
                    selected_skills=selected_skills,
                    notes=notes,
                )
                packet = create_handoff_packet(
                    session_id=session_id,
                    parent_session_id=metadata.get("parent_session_id"),
                    reason=f"context_{context_status}",
                    state=run_state,
                    prompt_stack=prompt_stack,
                    context_manager=context_manager,
                )
                handoff_path = save_handoff_packet(
                    packet=packet,
                    session_path=session_path,
                    sequence=handoff_count,
                )
                handoff_paths.append(str(handoff_path))
                context_seed = context_manager.compact_window()
                context_manager.reset_with_seed(context_seed)
                notes.append(
                    f"Context compacted after reaching {context_status}; rollover handoff packet {handoff_count} captured."
                )
                self.session_store.append_timeline(
                    session_path,
                    TimelineEvent(
                        kind="runtime.context_compacted",
                        message="Neyvia compacted the live context window and saved a rollover handoff packet.",
                        metadata={
                            "status": context_status,
                            "handoff_path": str(handoff_path),
                            "handoff_count": handoff_count,
                        },
                    ),
                )
                if guardrails.get("pause_on_handoff", True):
                    blocker = self._classify_blocker(
                        reason=f"context_{context_status}",
                        detail=(
                            f"Context {context_status} triggered compaction and a pause boundary."
                        ),
                        phase=context_status,
                        runtime_id=runtime_id,
                    )
                    retry_key = blocker["kind"]
                    retry_count = int(blocker_retry_counts.get(retry_key, 0) or 0)
                    if retry_count < 1:
                        blocker_retry_counts[retry_key] = retry_count + 1
                        decisions.append(
                            "Neyvia continued once after automatic context compaction."
                        )
                        notes.append(
                            "Context compacted; Neyvia resumed automatically once before pausing."
                        )
                        continue
                    autopilot_status = "paused"
                    autopilot_pause_reason = f"context_{context_status}"
                    blocker_history, latest_blocker = self._remember_blocker(
                        blocker=blocker,
                        blocker_history=blocker_history,
                    )
                    break

            if autopilot_pause_reason:
                break

        if autopilot_pause_reason and not latest_blocker:
            blocker_history, latest_blocker = self._remember_blocker(
                blocker=self._classify_blocker(
                    reason=autopilot_pause_reason,
                    detail=f"Mission paused due to {autopilot_pause_reason}.",
                    phase="execute",
                    runtime_id=runtime_id,
                ),
                blocker_history=blocker_history,
            )

        final_steps = [
            step.title for step in plan_revisions[-1].steps if step.status != "completed"
        ]
        if not final_steps and not autopilot_pause_reason:
            autopilot_status = "completed"

        (
            route_configs,
            execution_policy,
            runtime_autonomy,
            autonomy_changed,
            route_change_count,
        ) = self._apply_runtime_autonomy(
            profile_name=profile_name,
            route_configs=route_configs,
            route_overrides=route_overrides or [],
            execution_policy=execution_policy,
            repeated_failure_count=repeated_failure_count,
            verification_failures=verification_failures,
            stable_success_streak=stable_success_streak,
            context_status=context_manager.status(),
            delegated_status=autopilot_pause_reason or delegated_status,
            route_change_count=route_change_count,
            parallel_agents=resolved_parallel_agents,
            merge_policy=resolved_merge_policy,
            max_tokens=resolved_max_tokens,
            requested_strategy_override=routing_strategy_override,
            objective=objective,
            workspace_root=repo_path,
        )
        if autonomy_changed:
            for route in route_configs:
                if route.role not in {"planner", "executor", "verifier"}:
                    continue
                routing_decisions.append(
                    asdict(
                        RoutingDecision(
                            role=route.role,
                            provider=route.provider,
                            model=route.model,
                            reason=runtime_autonomy["reason"],
                            budget_class=route.budget_class,
                            task_type=route.task_type,
                            route_intent=route.route_intent,
                            fit_score=route.fit_score,
                            outcome_sample_count=route.outcome_sample_count,
                            outcome_success_rate=route.outcome_success_rate,
                            outcome_trend=route.outcome_trend,
                        )
                    )
                )
            runtime_autonomy_history.append(runtime_autonomy)
            runtime_autonomy_history = runtime_autonomy_history[-AUTONOMY_HISTORY_LIMIT:]

        if (
            context_manager.status() in {"rollover", "hard_stop"}
            and handoff_count < max_handoffs
        ):
            handoff_count += 1
            packet = create_handoff_packet(
                session_id=session_id,
                parent_session_id=metadata.get("parent_session_id"),
                reason=f"context_{context_manager.status()}",
                state=self._build_run_state(
                    objective=objective,
                    acceptance_checks=plan_bundle.acceptance_checks,
                    plan_revisions=plan_revisions,
                    completed_steps=completed_steps,
                    decisions=decisions,
                    changed_files=changed_files,
                    risks=risks,
                    verification_results=last_verification_results,
                    selected_skills=selected_skills,
                    notes=notes,
                ),
                prompt_stack=prompt_stack,
                context_manager=context_manager,
            )
            handoff_path = save_handoff_packet(
                packet=packet,
                session_path=session_path,
                sequence=handoff_count,
            )
            handoff_paths.append(str(handoff_path))
            context_seed = context_manager.compact_window()
            context_manager.reset_with_seed(context_seed)

        provider_truth = self._provider_truth_for_run(
            route_configs=route_configs,
            current_phase=(
                delegated_cycle_phase_for_step(
                    plan_revisions[-1].steps[0],
                    objective=objective,
                    route_configs=route_configs,
                )
                if plan_revisions and plan_revisions[-1].steps
                else "execute"
            ),
            code_execution=code_execution,
            code_execution_state=code_execution_state,
            action_history=action_history,
            latest_blocker=latest_blocker,
        )
        code_execution_payload = {
            **dict(code_execution),
            "last_started_at": str(code_execution_state.get("updated_at", "") or ""),
            "last_result": str(code_execution_state.get("last_result", "") or ""),
            "last_error": str(code_execution_state.get("last_error", "") or ""),
            "artifacts": list(code_execution_state.get("artifacts", [])),
        }
        context_seed = context_manager.compact_window()
        persisted_state = {
            "objective": objective,
            "doc_evidence": [asdict(item) for item in docs_evidence],
            "plan_steps": [item.title for item in plan_revisions[-1].steps],
            "acceptance_checks": plan_bundle.acceptance_checks,
            "completed_steps": completed_steps,
            "decisions": decisions,
            "changed_files": changed_files,
            "risks": risks,
            "next_actions": final_steps[:6],
            "verification_results": [asdict(item) for item in last_verification_results],
            "verification_failures": verification_failures,
            "retrieved_skills": [item["label"] for item in selected_skills],
            "notes": notes,
            "autopilot_status": autopilot_status,
            "autopilot_pause_reason": autopilot_pause_reason,
            "session_lineage": lineage,
            "profile": profile_name,
            "profile_defaults": profile_defaults,
            "execution_scope": asdict(execution_scope),
            "execution_policy": asdict(execution_policy),
            "route_configs": [asdict(item) for item in route_configs],
            "routing_decisions": routing_decisions,
            "plan_revisions": [asdict(item) for item in plan_revisions],
            "current_plan_revision_id": plan_revisions[-1].revision_id,
            "derived_tasks": [asdict(item) for item in derived_tasks],
            "improvement_queue": [asdict(item) for item in improvement_queue],
            "skill_usage": skill_usage,
            "learned_skill_events": learned_skill_events,
            "skill_feedback_events": skill_feedback_events[-120:],
            "action_history": action_history,
            "delegated_runtime_sessions": delegated_runtime_sessions,
            "repeated_failure_count": repeated_failure_count,
            "planner_loop_status": "paused" if autopilot_pause_reason else autopilot_status,
            "harness_id": self.harness_id,
            "runtime_id": runtime_id,
            "mission_id": execution_context.mission_id,
            "compatibility_harness_id": self.compatibility_harness.harness_id,
            "project_profile": project_profile,
            "prompt_stack": asdict(prompt_stack),
            "context": self._context_snapshot(context_manager),
            "context_seed": context_seed,
            "memory_item_ids": [],
            "handoff_packets": handoff_paths,
            "handoff_budget_used": handoff_count,
            "parallel_agents": resolved_parallel_agents,
            "merge_policy": resolved_merge_policy,
            "max_tokens": resolved_max_tokens,
            "vibe_next_steps": [item.title for item in improvement_queue[:3]],
            "pending_mutating_actions": sum(
                1
                for item in action_history
                if item.get("proposal", {}).get("mutability_class") == "write"
                and item.get("gate", {}).get("status") == "pending"
            ),
            "replay_action_cursor": action_history[-1]["proposal"].get("replay_cursor", "")
            if action_history
            else "",
            "tutorial_context": {
                "profile": profile_name,
                "explanationDepth": execution_policy.explanation_depth,
                "scope": execution_scope.strategy,
            },
            "stable_success_streak": stable_success_streak,
            "route_change_count": route_change_count,
            "runtime_autonomy": runtime_autonomy,
            "runtime_autonomy_history": runtime_autonomy_history[-AUTONOMY_HISTORY_LIMIT:],
            "blocker_history": blocker_history[-AUTONOMY_HISTORY_LIMIT:],
            "latest_blocker": latest_blocker,
            "blocker_retry_counts": blocker_retry_counts,
            "provider_truth": provider_truth,
            "code_execution": code_execution_payload,
            "code_execution_state": code_execution_state,
        }
        self.session_store.save_state(session_path, persisted_state)

        write_run_report(
            session_path=session_path,
            objective=objective,
            session_lineage=lineage,
            handoff_paths=handoff_paths,
            state=persisted_state,
        )

        return {
            "status": "ok",
            "session_path": str(session_path),
            "autopilot_status": autopilot_status,
            "autopilot_pause_reason": autopilot_pause_reason,
            "remaining_steps": final_steps,
            "verification_failures": verification_failures,
            "changed_files": changed_files,
            "route_configs": [asdict(item) for item in route_configs],
            "routing_decisions": routing_decisions,
            "execution_scope": asdict(execution_scope),
            "execution_policy": asdict(execution_policy),
            "plan_revisions": [asdict(item) for item in plan_revisions],
            "current_plan_revision_id": plan_revisions[-1].revision_id,
            "derived_tasks": [asdict(item) for item in derived_tasks],
            "improvement_queue": [asdict(item) for item in improvement_queue],
            "skill_usage": skill_usage,
            "learned_skill_events": learned_skill_events,
            "skill_feedback_events": skill_feedback_events[-120:],
            "action_history": action_history,
            "delegated_runtime_sessions": delegated_runtime_sessions,
            "harness_id": self.harness_id,
            "profile_defaults": profile_defaults,
            "repeated_failure_count": repeated_failure_count,
            "context": self._context_snapshot(context_manager),
            "context_seed": context_seed,
            "handoff_packets": handoff_paths,
            "parallel_agents": resolved_parallel_agents,
            "merge_policy": resolved_merge_policy,
            "max_tokens": resolved_max_tokens,
            "stable_success_streak": stable_success_streak,
            "route_change_count": route_change_count,
            "runtime_autonomy": runtime_autonomy,
            "runtime_autonomy_history": runtime_autonomy_history[-AUTONOMY_HISTORY_LIMIT:],
            "blocker_history": blocker_history[-AUTONOMY_HISTORY_LIMIT:],
            "latest_blocker": latest_blocker,
            "provider_truth": provider_truth,
            "code_execution": code_execution_payload,
            "code_execution_state": code_execution_state,
        }

    @staticmethod
    def _build_run_state(
        objective: str,
        acceptance_checks: list[str],
        plan_revisions: list[PlanRevision],
        completed_steps: list[str],
        decisions: list[str],
        changed_files: list[str],
        risks: list[str],
        verification_results: list[VerificationResult],
        selected_skills: list[dict],
        notes: list[str],
    ) -> RunState:
        return RunState(
            objective=objective,
            plan_steps=[item.title for item in plan_revisions[-1].steps],
            acceptance_checks=acceptance_checks,
            completed_steps=completed_steps,
            decisions=decisions,
            changed_files=changed_files,
            risks=risks,
            next_actions=[
                item.title for item in plan_revisions[-1].steps if item.status != "completed"
            ],
            verification_results=verification_results,
            retrieved_skills=[item["label"] for item in selected_skills],
            notes=notes,
        )

    @staticmethod
    def _build_prompt_stack(
        objective: str,
        project_profile: str,
        profile_name: str,
        selected_profile: PersonalizationProfile | None,
    ) -> PromptStack:
        persona = PersonaProfile(
            name=f"fluxio_{profile_name}",
            tone="direct",
            risk_tolerance="guarded" if profile_name == "beginner" else "balanced",
            creativity_level="bounded",
            coding_style="incremental",
            verbosity=(
                selected_profile.agent.explanation_depth
                if selected_profile and selected_profile.agent.explanation_depth
                else "medium"
            ),
        )
        return build_prompt_stack(
            constitution_text=RUNTIME_CONSTITUTION_TEXT,
            project_profile=project_profile,
            persona=persona,
            task_brief=objective,
        )

    @staticmethod
    def _context_snapshot(context_manager: ContextWindowManager) -> dict:
        return {
            "used_tokens": context_manager.used_tokens,
            "usage_ratio": round(context_manager.usage_ratio, 3),
            "status": context_manager.status(),
        }

    @staticmethod
    def _resolve_code_execution_config(
        *,
        requested_config: dict | None,
        resumed_state: dict | None,
        mission_id: str,
    ) -> dict:
        previous_config = (
            dict(resumed_state.get("code_execution", {}))
            if resumed_state and isinstance(resumed_state.get("code_execution"), dict)
            else {}
        )
        previous_state = (
            dict(resumed_state.get("code_execution_state", {}))
            if resumed_state and isinstance(resumed_state.get("code_execution_state"), dict)
            else {}
        )
        requested = dict(requested_config or {})
        enabled = bool(requested.get("enabled", previous_config.get("enabled", False)))
        memory_limit = str(
            requested.get("memory_limit", previous_config.get("memory_limit", "4g")) or "4g"
        ).strip().lower()
        container_id = str(
            requested.get("container_id")
            or previous_config.get("container_id")
            or previous_state.get("container_id")
            or ""
        ).strip()
        if enabled and not container_id:
            container_id = f"auto-{str(mission_id or 'mission').replace('_', '-')[:40]}"
        required = bool(requested.get("required", previous_config.get("required", False)))
        file_ids = list(requested.get("file_ids", previous_config.get("file_ids", [])) or [])
        return {
            "enabled": enabled,
            "memory_limit": memory_limit or "4g",
            "container_id": container_id,
            "required": required,
            "file_ids": file_ids,
        }

    @staticmethod
    def _load_code_execution_state(
        *,
        resumed_state: dict | None,
        code_execution: dict,
    ) -> dict:
        previous_state = (
            dict(resumed_state.get("code_execution_state", {}))
            if resumed_state and isinstance(resumed_state.get("code_execution_state"), dict)
            else {}
        )
        container_id = str(
            previous_state.get("container_id") or code_execution.get("container_id", "")
        ).strip()
        return {
            "enabled": bool(code_execution.get("enabled", False)),
            "container_id": container_id,
            "memory_limit": str(code_execution.get("memory_limit", "4g") or "4g"),
            "required": bool(code_execution.get("required", False)),
            "artifacts": list(previous_state.get("artifacts", [])),
            "last_result": str(previous_state.get("last_result", "") or ""),
            "last_error": str(previous_state.get("last_error", "") or ""),
            "updated_at": str(previous_state.get("updated_at", "") or ""),
        }

    @staticmethod
    def _record_code_execution_artifact(
        *,
        code_execution_state: dict,
        code_execution: dict,
        execution_record: ActionExecutionRecord,
    ) -> dict:
        if not bool(code_execution.get("enabled", False)):
            return dict(code_execution_state)
        updated = dict(code_execution_state)
        artifact = {
            "artifact_id": f"artifact_{uuid.uuid4().hex[:10]}",
            "created_at": utc_now_iso(),
            "action_id": execution_record.action_id,
            "kind": execution_record.proposal.kind,
            "title": execution_record.proposal.title,
            "ok": bool(execution_record.result.ok),
            "summary": str(
                execution_record.result.result_summary
                or execution_record.result.error
                or execution_record.result.stderr
                or execution_record.result.stdout
                or ""
            ).strip(),
            "files": list(execution_record.result.changed_files or [])[:12],
            "runtime": "delegated"
            if execution_record.proposal.kind == "runtime_delegate"
            else "local",
            "container_id": str(updated.get("container_id", "") or ""),
        }
        delegated = execution_record.result.payload.get("delegatedSession", {})
        if isinstance(delegated, dict) and delegated.get("delegated_id"):
            artifact["delegated_id"] = str(delegated.get("delegated_id"))
        artifacts = list(updated.get("artifacts", []))
        artifacts.append(artifact)
        updated["artifacts"] = artifacts[-24:]
        updated["last_result"] = artifact["summary"]
        if execution_record.result.ok:
            updated["last_error"] = ""
        else:
            updated["last_error"] = artifact["summary"] or "Code execution artifact failed."
        updated["updated_at"] = artifact["created_at"]
        updated["enabled"] = bool(code_execution.get("enabled", False))
        updated["memory_limit"] = str(code_execution.get("memory_limit", "4g") or "4g")
        updated["required"] = bool(code_execution.get("required", False))
        updated["container_id"] = str(
            updated.get("container_id") or code_execution.get("container_id", "")
        ).strip()
        return updated

    @staticmethod
    def _provider_truth_for_run(
        *,
        route_configs: list[ModelRouteConfig],
        current_phase: str,
        code_execution: dict,
        code_execution_state: dict,
        action_history: list[dict],
        latest_blocker: dict,
    ) -> dict:
        def role_for_phase(value: str) -> str:
            normalized = str(value or "execute").strip().lower()
            if normalized in {"plan", "replan"}:
                return "planner"
            if normalized == "verify":
                return "verifier"
            return "executor"

        phase = str(current_phase or "execute").strip().lower()
        active_route = FluxioHarness._route_for_phase(route_configs, phase)
        active_provider = active_route.provider if active_route is not None else ""
        active_model = active_route.model if active_route is not None else ""
        active_role = active_route.role if active_route is not None else role_for_phase(phase)

        def auth_store_has_provider(path: Path, provider_id: str) -> bool:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            needle = provider_id.strip().lower()

            def walk(value: object) -> bool:
                if isinstance(value, dict):
                    for key in ("providers", "credential_pool"):
                        nested = value.get(key)
                        if isinstance(nested, dict) and needle in {
                            str(item).strip().lower() for item in nested.keys()
                        }:
                            return True
                    provider = str(
                        value.get("provider")
                        or value.get("providerId")
                        or value.get("provider_id")
                        or ""
                    ).strip().lower()
                    if provider == needle:
                        return True
                    return any(walk(item) for item in value.values())
                if isinstance(value, list):
                    return any(walk(item) for item in value)
                return False

            return walk(payload)

        def provider_auth_status(provider_id: str) -> tuple[bool, str, str]:
            home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
            openclaw_state = Path(
                os.environ.get("OPENCLAW_STATE_DIR", str(home / ".openclaw"))
            ).expanduser()
            openclaw_auth = openclaw_state / "agents" / "main" / "agent" / "auth-profiles.json"
            hermes_auth_stores = hermes_auth_store_candidates(home)
            if provider_id in {"openai", "openai-codex"}:
                api_present = bool(os.environ.get("OPENAI_API_KEY"))
                oauth_present = bool(
                    os.environ.get("FLUXIO_OPENAI_CODEX_OAUTH_PRESENT")
                    or (home / ".codex" / "auth.json").exists()
                    or auth_store_has_provider(openclaw_auth, "openai-codex")
                    or any(auth_store_has_provider(path, "openai-codex") for path in hermes_auth_stores)
                )
                if api_present:
                    return True, "api", "API key"
                if oauth_present:
                    return True, "oauth", "OpenAI Codex OAuth"
                return False, "none", "not configured"
            if provider_id in {"minimax", "minimax-cn", "minimax-portal", "minimax-oauth"}:
                api_present = bool(os.environ.get("MINIMAX_API_KEY"))
                oauth_present = bool(
                    os.environ.get("FLUXIO_MINIMAX_OPENCLAW_OAUTH_PRESENT")
                    or (home / ".minimax" / "oauth_creds.json").exists()
                    or auth_store_has_provider(openclaw_auth, "minimax-portal")
                    or any(
                        auth_store_has_provider(path, hermes_provider)
                        for path in hermes_auth_stores
                        for hermes_provider in ("minimax-oauth", "minimax", "minimax-portal")
                    )
                )
                if api_present:
                    return True, "minimax-api", "API key"
                if oauth_present:
                    return True, "minimax-portal-oauth", "MiniMax broker OAuth"
                return False, "none", "not configured"
            return bool(provider_id), "", ""

        auth_present, auth_mode, auth_path = provider_auth_status(active_provider)
        last_success: dict = {}
        last_failure: dict = {}
        for row in reversed(action_history):
            if not isinstance(row, dict):
                continue
            proposal = dict(row.get("proposal", {}))
            delegation = dict(proposal.get("delegation_metadata", {}))
            entry_phase = str(delegation.get("cycle_phase", phase) or phase).strip().lower()
            route = FluxioHarness._route_for_phase(route_configs, entry_phase)
            provider = route.provider if route is not None else active_provider
            model = route.model if route is not None else active_model
            role = route.role if route is not None else role_for_phase(entry_phase)
            result = dict(row.get("result", {}))
            summary = str(
                result.get("result_summary")
                or result.get("error")
                or result.get("stderr")
                or result.get("stdout")
                or ""
            ).strip()
            if len(summary) > 220:
                summary = summary[:217].rstrip() + "..."
            payload = {
                "provider": provider,
                "model": model,
                "role": role,
                "phase": entry_phase,
                "at": str(row.get("executed_at", "") or ""),
                "source": "action_history",
                "summary": summary,
            }
            if bool(result.get("ok")):
                if not last_success:
                    last_success = payload
            elif not last_failure:
                last_failure = payload
            if last_success and last_failure:
                break
        if not last_failure and str(code_execution_state.get("last_error", "")).strip():
            last_failure = {
                "provider": active_provider,
                "model": active_model,
                "role": active_role,
                "phase": phase,
                "at": str(code_execution_state.get("updated_at", "") or utc_now_iso()),
                "source": "code_execution",
                "summary": str(code_execution_state.get("last_error", "")).strip(),
            }
        return {
            "currentPhase": phase,
            "activeRoute": {
                "role": active_role,
                "provider": active_provider,
                "model": active_model,
                "effort": active_route.effort if active_route is not None else "",
                "budgetClass": active_route.budget_class if active_route is not None else "",
                "taskType": active_route.task_type if active_route is not None else "general_coding",
                "routeIntent": active_route.route_intent if active_route is not None else "",
                "fitScore": active_route.fit_score if active_route is not None else 0,
            },
            "authPresent": auth_present,
            "authKnown": bool(active_provider),
            "authMode": auth_mode,
            "authPath": auth_path,
            "codeExecutionEnabled": bool(code_execution.get("enabled", False)),
            "codeExecutionContainerId": str(code_execution_state.get("container_id", "")),
            "lastSuccessfulCall": last_success,
            "lastFailure": last_failure,
            "blockerClass": str(latest_blocker.get("class", "") or ""),
            "updatedAt": utc_now_iso(),
        }

    @staticmethod
    def _route_signature(route_configs: list[ModelRouteConfig]) -> list[tuple[str, str, str, str, str, str, str, int]]:
        return [
            (
                item.role,
                item.provider,
                item.model,
                item.effort,
                item.budget_class,
                item.task_type,
                item.route_intent,
                item.fit_score,
            )
            for item in route_configs
        ]

    @staticmethod
    def _policy_signature(
        policy: ExecutionPolicy,
    ) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
        return (
            policy.approval_mode,
            policy.delegation_aggressiveness,
            tuple(policy.auto_allowed_kinds),
            tuple(policy.approval_required_kinds),
        )

    @staticmethod
    def _routing_strategy_for_routes(route_configs: list[ModelRouteConfig]) -> str:
        planner = next((item for item in route_configs if item.role == "planner"), None)
        executor = next((item for item in route_configs if item.role == "executor"), None)
        if not planner or not executor:
            return "profile_default"
        planner_is_codex = (
            planner.provider == CODEX_PLANNING_PROVIDER
            and planner.model == CODEX_PLANNING_MODEL
        )
        planner_is_efficient_codex = (
            planner.provider == CODEX_PLANNING_PROVIDER
            and planner.model == CODEX_EFFICIENT_PLANNING_MODEL
        )
        if planner_is_codex and executor.model == PREMIUM_OPENAI_MODEL:
            return "uniform_quality"
        if planner_is_efficient_codex and executor.model == EFFICIENT_OPENAI_MODEL:
            return "budget_first"
        if planner_is_codex and executor.model == EFFICIENT_OPENAI_MODEL:
            return "planner_premium_executor_efficient"
        return "custom"

    @staticmethod
    def _apply_runtime_autonomy(
        *,
        profile_name: str,
        route_configs: list[ModelRouteConfig],
        route_overrides: list[dict],
        execution_policy: ExecutionPolicy,
        repeated_failure_count: int,
        verification_failures: list[str],
        stable_success_streak: int,
        context_status: str,
        delegated_status: str,
        route_change_count: int,
        parallel_agents: int,
        merge_policy: str,
        max_tokens: int,
        requested_strategy_override: str | None = None,
        objective: str | None = None,
        workspace_root: Path | None = None,
    ) -> tuple[list[ModelRouteConfig], ExecutionPolicy, dict, bool, int]:
        current_strategy = FluxioHarness._routing_strategy_for_routes(route_configs)
        target_strategy = current_strategy
        target_approval_mode = execution_policy.approval_mode
        target_delegation = execution_policy.delegation_aggressiveness
        policy_name = "steady_state"
        reason = "Runtime posture stayed unchanged."
        explicit_strategy = str(requested_strategy_override or "").strip().lower()
        explicit_route_lock = bool(explicit_strategy and explicit_strategy != "profile_default")

        if verification_failures or repeated_failure_count >= 2:
            target_strategy = "uniform_quality"
            target_approval_mode = "tiered"
            target_delegation = "low"
            policy_name = "verification_guardrail"
            reason = "Verification pressure moved the mission onto the high-confidence route and reduced delegation."
        elif not explicit_route_lock and context_status in {"rollover", "hard_stop"}:
            target_strategy = "planner_premium_executor_efficient"
            target_approval_mode = "tiered"
            target_delegation = "low"
            policy_name = "context_compaction"
            reason = "Context pressure reduced delegation and kept execution on the efficient route."
        elif not explicit_route_lock and stable_success_streak >= 2 and delegated_status != "waiting_for_approval":
            target_strategy = "planner_premium_executor_efficient"
            if profile_name != "beginner":
                target_delegation = "high" if profile_name == "experimental" else "balanced"
            policy_name = "stable_progress"
            reason = "Recent cycles were stable, so Neyvia kept execution efficient and restart-safe."

        old_route_signature = FluxioHarness._route_signature(route_configs)
        old_policy_signature = FluxioHarness._policy_signature(execution_policy)

        updated_routes = route_configs
        if target_strategy != current_strategy and target_strategy != "custom":
            updated_routes = recommended_model_routes(
                profile_name,
                routing_strategy_override=target_strategy,
                route_overrides=route_overrides,
                objective=objective,
                route_outcome_trends=build_route_outcome_trends(workspace_root or Path.cwd()),
            )

        updated_policy = ExecutionPolicy(
            profile_name=execution_policy.profile_name,
            approval_mode=target_approval_mode,
            explanation_depth=execution_policy.explanation_depth,
            delegation_aggressiveness=target_delegation,
            auto_allowed_kinds=list(execution_policy.auto_allowed_kinds),
            approval_required_kinds=list(execution_policy.approval_required_kinds),
            destructive_requires_approval=execution_policy.destructive_requires_approval,
        )
        updated_policy = normalize_execution_policy(updated_policy)

        changed = bool(
            FluxioHarness._route_signature(updated_routes) != old_route_signature
            or FluxioHarness._policy_signature(updated_policy) != old_policy_signature
        )
        if changed:
            route_change_count += 1

        autonomy = {
            "policy": policy_name,
            "reason": reason,
            "routingStrategy": (
                FluxioHarness._routing_strategy_for_routes(updated_routes)
                if updated_routes
                else current_strategy
            ),
            "delegationAggressiveness": updated_policy.delegation_aggressiveness,
            "approvalMode": updated_policy.approval_mode,
            "contextStatus": context_status,
            "stableSuccessStreak": stable_success_streak,
            "verificationFailureCount": len(verification_failures),
            "repeatedFailureCount": repeated_failure_count,
            "delegatedStatus": delegated_status or "idle",
            "parallelAgents": parallel_agents,
            "mergePolicy": merge_policy,
            "maxTokens": max_tokens,
            "routeChangeCount": route_change_count,
            "changed": changed,
            "evaluatedAt": utc_now_iso(),
        }
        return updated_routes, updated_policy, autonomy, changed, route_change_count

    @staticmethod
    def _classify_blocker(
        *,
        reason: str,
        detail: str = "",
        phase: str = "execute",
        runtime_id: str = "",
    ) -> dict:
        normalized = str(reason or "").strip().lower() or "unknown"
        blocker_class = "operator_only"
        resolution = "pause_for_operator"
        if normalized in {"verification_failed", "verification_failure", "action_failed"}:
            blocker_class = "safe_to_replan"
            resolution = "auto_replan"
        elif normalized in {"delegated_runtime_failed", "delegated_runtime_failure"}:
            blocker_class = "operator_only"
            resolution = "runtime_auth_or_route_repair"
        elif normalized in {
            "delegated_runtime_running",
            "context_rollover",
            "context_hard_stop",
            "context_warning",
        }:
            blocker_class = "safe_to_self_resolve"
            resolution = "retry_or_continue"
        elif normalized in {"runtime_budget", "handoff_budget"}:
            blocker_class = "operator_only"
            resolution = "budget_boundary"
        elif normalized in {"approval_required", "needs_approval", "approval_waiting"}:
            blocker_class = "operator_only"
            resolution = "approval_required"
        summary = detail or f"{normalized.replace('_', ' ')} blocker."
        return {
            "kind": normalized,
            "class": blocker_class,
            "resolution": resolution,
            "phase": str(phase or "execute").strip().lower() or "execute",
            "runtimeId": runtime_id,
            "summary": summary,
            "at": utc_now_iso(),
        }

    @staticmethod
    def _remember_blocker(
        *,
        blocker: dict,
        blocker_history: list[dict],
    ) -> tuple[list[dict], dict]:
        updated = list(blocker_history)
        updated.append(dict(blocker))
        return updated[-AUTONOMY_HISTORY_LIMIT:], dict(blocker)

    @staticmethod
    def _delegated_follow_budget_seconds(
        *,
        started_at: float,
        max_runtime_seconds: int,
        parallel_agents: int,
        context_status: str,
    ) -> int:
        remaining = max(0, int(max_runtime_seconds - (time.monotonic() - started_at)))
        if remaining <= 0:
            return 0
        budget = min(
            DELEGATED_FOLLOW_BUDGET_SECONDS + max(0, parallel_agents - 1) * 2,
            remaining,
        )
        if context_status in {"rollover", "hard_stop"}:
            return min(budget, 4)
        return budget

    @staticmethod
    def _follow_delegated_sessions(
        *,
        delegated_runtime_sessions: list[dict],
        plan_revisions: list[PlanRevision],
        runtime_supervisor: DelegatedRuntimeSupervisor,
        notes: list[str],
        risks: list[str],
        objective: str,
        route_configs: list[ModelRouteConfig],
        wait_seconds: int,
    ) -> tuple[list[dict], str, str]:
        current_sessions, active_status, replan_trigger = FluxioHarness._reconcile_delegated_sessions(
            delegated_runtime_sessions=delegated_runtime_sessions,
            plan_revisions=plan_revisions,
            runtime_supervisor=runtime_supervisor,
            notes=notes,
            risks=risks,
            objective=objective,
            route_configs=route_configs,
        )
        if active_status != "running" or wait_seconds <= 0:
            return current_sessions, active_status, replan_trigger
        deadline = time.monotonic() + wait_seconds
        while active_status == "running" and time.monotonic() < deadline:
            time.sleep(1.0)
            current_sessions, active_status, replan_trigger = FluxioHarness._reconcile_delegated_sessions(
                delegated_runtime_sessions=current_sessions,
                plan_revisions=plan_revisions,
                runtime_supervisor=runtime_supervisor,
                notes=notes,
                risks=risks,
                objective=objective,
                route_configs=route_configs,
            )
        if active_status != "running":
            notes.append("Delegated runtime lane settled within the same control cycle.")
        return current_sessions, active_status, replan_trigger

    @staticmethod
    def _verification_summary(results: list[VerificationResult]) -> str:
        if not results:
            return "No verification commands were configured for this cycle."
        failed = [item.command for item in results if item.return_code != 0 or item.status != "executed"]
        if failed:
            return f"Verification failed: {', '.join(failed[:2])}"
        return f"Verification passed for {len(results)} command(s)."

    @staticmethod
    def _execution_result_summary(record: ActionExecutionRecord) -> str:
        if record.result.ok:
            return f"Completed action: {record.proposal.title}. {record.result.result_summary}"
        if record.gate.status == "pending":
            return f"Action is waiting for approval: {record.proposal.title}."
        return (
            f"Action failed: {record.proposal.title}. "
            f"{record.result.error or record.result.stderr or record.result.result_summary}"
        )

    @staticmethod
    def _route_for_phase(
        route_configs: list[ModelRouteConfig],
        phase: str,
    ) -> ModelRouteConfig | None:
        role = "executor"
        normalized = str(phase or "execute").strip().lower()
        if normalized in {"plan", "replan"}:
            role = "planner"
        elif normalized in {"backend", "api", "server", "server_side", "server-side"}:
            role = "backend"
        elif normalized in {"frontend", "ui", "client", "client_side", "client-side"}:
            role = "frontend"
        elif normalized == "verify":
            role = "verifier"
        return next((item for item in route_configs if item.role == role), None)

    @staticmethod
    @_proofs_b_checked("proofs-b.engine.route-equivalence")
    def _delegated_route_mismatch(
        session: object,
        *,
        desired_phase: str,
        desired_route: ModelRouteConfig | None,
    ) -> bool:
        desired_phase = str(desired_phase or "").strip().lower()
        session_phase = str(getattr(session, "target_phase", "") or "").strip().lower()
        if desired_phase and session_phase and desired_phase != session_phase:
            return True
        if desired_route is None:
            return False
        session_provider = str(getattr(session, "target_provider", "") or "").strip().lower()
        session_model = str(getattr(session, "target_model", "") or "").strip()
        session_effort = str(getattr(session, "target_effort", "") or "").strip().lower()
        desired_provider = str(desired_route.provider or "").strip().lower()
        equivalent_providers = {
            ("openai", "openai-codex"),
            ("openai-codex", "openai"),
        }
        if (
            session_provider
            and session_provider != desired_provider
            and (session_provider, desired_provider) not in equivalent_providers
        ):
            return True
        if session_model and session_model != desired_route.model:
            return True
        if session_effort and session_effort != desired_route.effort:
            return True
        if not session_provider and desired_provider:
            return True
        if not session_model and desired_route.model:
            return True
        return False

    @staticmethod
    def _handoff_reason_for_session(
        *,
        session: object,
        desired_phase: str,
        desired_route: ModelRouteConfig | None,
    ) -> str:
        previous_phase = str(getattr(session, "target_phase", "") or "execute").strip().lower()
        if desired_phase != previous_phase:
            return (
                f"Mission phase changed from {previous_phase} to {desired_phase}; "
                "handoff to the matching route."
            )
        if desired_route is None:
            return "Route contract changed; handoff to keep delegated lane aligned."
        previous_provider = str(getattr(session, "target_provider", "") or "unknown").strip().lower()
        previous_model = str(getattr(session, "target_model", "") or "unknown").strip()
        return (
            "Route contract changed for the delegated lane "
            f"({previous_provider}:{previous_model} -> {desired_route.provider}:{desired_route.model})."
        )

    @staticmethod
    def _handoff_delegated_session(
        *,
        session: object,
        step: PlannedStep | None,
        objective: str,
        desired_phase: str,
        route_configs: list[ModelRouteConfig],
        runtime_supervisor: DelegatedRuntimeSupervisor,
        reason: str,
    ):
        workspace_root = str(
            getattr(session, "workspace_root", "") or getattr(session, "execution_root", "")
        ).strip()
        execution_root = str(
            getattr(session, "execution_root", "") or workspace_root
        ).strip()
        delegated_scope = ExecutionScope(
            requested="isolated",
            strategy="delegated_runtime",
            execution_root=execution_root,
            workspace_root=workspace_root,
            status="ready",
            detail="Delegated lane relaunched after phase-aware route handoff.",
        )
        delegated_mission = Mission(
            mission_id=f"delegated_{uuid.uuid4().hex[:8]}",
            workspace_id="delegated",
            runtime_id=str(getattr(session, "runtime_id", "openclaw") or "openclaw"),
            objective=(
                f"{step.title}\n\nMission objective: {objective}"
                if step is not None and step.title
                else (objective or "Continue delegated mission work")
            ),
            success_checks=[],
            execution_scope=delegated_scope,
            route_configs=route_configs,
        )
        delegated_mission.state.current_cycle_phase = desired_phase or "execute"
        delegated_mission.state.status = "running"
        delegated_workspace = WorkspaceProfile(
            workspace_id="delegated",
            name=Path(execution_root or workspace_root or "delegated").name or "delegated",
            root_path=execution_root or workspace_root or ".",
            default_runtime=str(getattr(session, "runtime_id", "openclaw") or "openclaw"),
            workspace_type="general",
        )
        return runtime_supervisor.handoff_session(
            session=session,
            mission=delegated_mission,
            workspace=delegated_workspace,
            source_step_id=str(getattr(session, "source_step_id", "") or ""),
            reason=reason,
        )

    @staticmethod
    def _reconcile_delegated_sessions(
        delegated_runtime_sessions: list[dict],
        plan_revisions: list[PlanRevision],
        runtime_supervisor: DelegatedRuntimeSupervisor,
        notes: list[str],
        risks: list[str],
        objective: str,
        route_configs: list[ModelRouteConfig],
    ) -> tuple[list[dict], str, str]:
        if not delegated_runtime_sessions:
            return delegated_runtime_sessions, "", ""

        refreshed: list[dict] = []
        active_status = ""
        replan_trigger = ""
        latest_revision = plan_revisions[-1]
        step_lookup = {step.step_id: step for revision in plan_revisions for step in revision.steps}
        for item in delegated_runtime_sessions:
            session = runtime_supervisor.refresh_session(item)
            step = step_lookup.get(session.source_step_id)
            desired_phase = delegated_cycle_phase_for_step(
                step,
                objective=objective,
                route_configs=route_configs,
            ) if step is not None else str(session.target_phase or "execute")
            desired_phase = str(desired_phase or "execute").strip().lower()
            desired_route = FluxioHarness._route_for_phase(route_configs, desired_phase)
            can_handoff = session.status in {"running", "launching"}
            if can_handoff and FluxioHarness._delegated_route_mismatch(
                session,
                desired_phase=desired_phase,
                desired_route=desired_route,
            ):
                handoff_reason = FluxioHarness._handoff_reason_for_session(
                    session=session,
                    desired_phase=desired_phase,
                    desired_route=desired_route,
                )
                try:
                    session = FluxioHarness._handoff_delegated_session(
                        session=session,
                        step=step,
                        objective=objective,
                        desired_phase=desired_phase,
                        route_configs=route_configs,
                        runtime_supervisor=runtime_supervisor,
                        reason=handoff_reason,
                    )
                    notes.append(
                        f"Delegated lane auto-handoff on {session.runtime_id}: {handoff_reason}"
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    risks.append(
                        f"Delegated handoff failed for {session.runtime_id}: {exc}"
                    )
            if session.status in {"queued", "running", "launching"}:
                queued_attempts_before = step.attempts if step is not None else 0
                active_status = "running"
                if step is not None:
                    step.status = "in_progress"
                    latest_revision.active_step_id = step.step_id
                if session.status == "queued":
                    from .proofs_a_cli_scheduler import check_queued
                    check_queued(session, step, queued_attempts_before)
                    waiting_note = (
                        f"Delegated runtime {session.runtime_id} is queued for step "
                        f"{step.title if step is not None else session.source_step_id or 'unknown'}: "
                        f"{session.detail or 'waiting for worker capacity'}"
                    )
                    if waiting_note not in notes:
                        notes.append(waiting_note)
            elif session.status == "waiting_for_approval":
                active_status = "waiting_for_approval"
                if step is not None:
                    step.status = "in_progress"
                    latest_revision.active_step_id = step.step_id
                prompt = session.pending_approval.get("prompt", "Delegated runtime requested approval.")
                if prompt not in notes:
                    notes.append(f"Delegated approval required: {prompt}")
            elif not session.acknowledged and step is not None:
                if session.status == "completed":
                    step.status = "completed"
                    changed_count = len(getattr(session, "changed_files", []) or [])
                    changed_detail = (
                        f" Changed files captured: {changed_count}."
                        if changed_count
                        else ""
                    )
                    notes.append(
                        f"Delegated runtime {session.runtime_id} completed for step {step.title}: "
                        f"{session.last_event or session.detail}{changed_detail}"
                    )
                else:
                    step.status = "blocked"
                    step.attempts += 1
                    if session.status == "failed":
                        replan_trigger = "delegated_runtime_failed"
                    if any(
                        entry.get("status") == "rejected"
                        for entry in session.approval_history
                        if isinstance(entry, dict)
                    ):
                        replan_trigger = "approval_rejected"
                    risks.append(
                        f"Delegated runtime {session.runtime_id} stopped with status {session.status}: "
                        f"{session.last_event or session.detail}"
                    )
                session.acknowledged = True
            refreshed.append(asdict(session))
        return refreshed, active_status, replan_trigger

    @staticmethod
    def _load_plan_revisions(
        resumed_state: dict | None,
        plan_bundle: PlanBundle,
    ) -> list[PlanRevision]:
        if resumed_state and resumed_state.get("plan_revisions"):
            revisions: list[PlanRevision] = []
            for revision in resumed_state.get("plan_revisions", []):
                steps = [PlannedStep(**item) for item in revision.get("steps", [])]
                revisions.append(
                    PlanRevision(
                        revision_id=revision["revision_id"],
                        trigger=revision.get("trigger", "resume"),
                        summary=revision.get("summary", ""),
                        steps=steps,
                        active_step_id=revision.get("active_step_id"),
                        created_at=revision.get("created_at", utc_now_iso()),
                    )
                )
            return revisions

        return [
            PlanRevision(
                revision_id=f"rev_{uuid.uuid4().hex[:8]}",
                trigger="mission_start",
                summary="Initial Neyvia plan built from docs-first planning.",
                steps=[
                    PlannedStep(
                        step_id=f"step_{uuid.uuid4().hex[:8]}",
                        title=step,
                        description=step,
                        kind="primary",
                    )
                    for step in plan_bundle.plan_steps
                ],
            )
        ]

    @staticmethod
    def _load_derived_tasks(resumed_state: dict | None) -> list[DerivedTask]:
        if not resumed_state:
            return []
        return [DerivedTask(**item) for item in resumed_state.get("derived_tasks", [])]

    @staticmethod
    def _load_improvement_queue(
        resumed_state: dict | None,
    ) -> list[ImprovementQueueItem]:
        if not resumed_state:
            return []
        return [
            ImprovementQueueItem(**item)
            for item in resumed_state.get("improvement_queue", [])
        ]

    @staticmethod
    def _load_action_history(resumed_state: dict | None) -> list[dict]:
        if not resumed_state:
            return []
        return list(resumed_state.get("action_history", []))

    @staticmethod
    def _load_routing_decisions(resumed_state: dict | None) -> list[dict]:
        if not resumed_state:
            return []
        return list(resumed_state.get("routing_decisions", []))

    @staticmethod
    def _load_execution_scope(resumed_state: dict | None) -> ExecutionScope | None:
        if not resumed_state or not resumed_state.get("execution_scope"):
            return None
        return ExecutionScope(**resumed_state["execution_scope"])

    @staticmethod
    def _load_execution_policy(resumed_state: dict | None) -> ExecutionPolicy | None:
        if not resumed_state or not resumed_state.get("execution_policy"):
            return None
        return ExecutionPolicy(**resumed_state["execution_policy"])

    @staticmethod
    def _load_route_configs(
        resumed_state: dict | None,
    ) -> list[ModelRouteConfig]:
        if not resumed_state:
            return []
        routes: list[ModelRouteConfig] = []
        allowed = set(ModelRouteConfig.__dataclass_fields__.keys())
        aliases = {
            "budgetClass": "budget_class",
            "fallbackPolicy": "fallback_policy",
            "taskType": "task_type",
            "routeIntent": "route_intent",
            "fitScore": "fit_score",
            "outcomeSampleCount": "outcome_sample_count",
            "outcomeSuccessRate": "outcome_success_rate",
            "outcomeTrend": "outcome_trend",
        }
        for item in resumed_state.get("route_configs", []):
            if not isinstance(item, dict) or not item.get("role"):
                continue
            normalized = dict(item)
            for source, target in aliases.items():
                if source in normalized and target not in normalized:
                    normalized[target] = normalized[source]
            routes.append(
                ModelRouteConfig(
                    **{key: value for key, value in normalized.items() if key in allowed}
                )
            )
        return routes

    @staticmethod
    def _next_pending_step(revision: PlanRevision) -> PlannedStep | None:
        for step in revision.steps:
            if step.status == "pending":
                revision.active_step_id = step.step_id
                return step
        for step in revision.steps:
            if step.status != "completed":
                revision.active_step_id = step.step_id
                return step
        revision.active_step_id = None
        return None

    @staticmethod
    def _append_revised_plan(
        plan_revisions: list[PlanRevision],
        base_revision: PlanRevision,
        trigger: str,
        summary: str,
        extra_steps: list[PlannedStep],
    ) -> None:
        pending_existing = [
            PlannedStep(
                step_id=item.step_id,
                title=item.title,
                description=item.description,
                status=item.status,
                kind=item.kind,
                attempts=item.attempts,
                notes=list(item.notes),
            )
            for item in base_revision.steps
            if item.status != "completed"
        ]
        merged_steps = pending_existing + extra_steps
        if not merged_steps:
            return
        plan_revisions.append(
            PlanRevision(
                revision_id=f"rev_{uuid.uuid4().hex[:8]}",
                trigger=trigger,
                summary=summary,
                steps=merged_steps,
                active_step_id=merged_steps[0].step_id,
            )
        )

    @staticmethod
    def _resolve_pending_action_if_any(
        action_history: list[dict],
        workspace_root: Path,
        execution_scope: ExecutionScope,
        execution_policy: ExecutionPolicy,
    ) -> ActionExecutionRecord | None:
        if not action_history:
            return None
        last = action_history[-1]
        gate = last.get("gate", {})
        proposal = last.get("proposal", {})
        result = last.get("result", {})
        if gate.get("status") not in {"pending", "approved", "rejected"}:
            return None

        record = ActionExecutionRecord(
            action_id=last["action_id"],
            proposal=ActionProposal(**proposal),
        )
        record.gate.required = gate.get("required", False)
        record.gate.status = gate.get("status", "not_required")
        record.gate.risk_level = gate.get("risk_level", "low")
        record.gate.reason = gate.get("reason", "")
        record.gate.approved_by = gate.get("approved_by", "")
        record.gate.resolved_at = gate.get("resolved_at")
        record.result.ok = result.get("ok", False)
        record.result.exit_code = result.get("exit_code", 0)
        record.result.stdout = result.get("stdout", "")
        record.result.stderr = result.get("stderr", "")
        record.result.duration_ms = result.get("duration_ms", 0)
        record.result.error = result.get("error", "")
        record.result.changed_files = result.get("changed_files", [])
        record.result.payload = result.get("payload", {})
        record.attempts = int(last.get("attempts", 0))
        record.event_id = last.get("event_id", "")
        record.acked = bool(last.get("acked", False))
        record.replayed = bool(last.get("replayed", False))
        record.executed_at = last.get("executed_at")

        if (
            record.gate.status == "pending"
            and FluxioHarness._proposal_auto_allowed_under_policy(
                record.proposal,
                execution_policy,
            )
        ):
            record.proposal.requires_approval = False
            record.proposal.policy_decision = "auto_run"
            rerun = execute_action(
                record.proposal,
                workspace_root,
                execution_scope=execution_scope,
                execution_policy=execution_policy,
            )
            rerun.gate.reason = (
                "Stale approval gate auto-cleared under the current mission policy."
            )
            return rerun

        if record.gate.status == "approved" and record.result.ok:
            return None
        if record.gate.status == "approved" and not record.result.ok:
            rerun = execute_action(
                record.proposal,
                workspace_root,
                execution_scope=execution_scope,
                execution_policy=execution_policy,
                approval_override=True,
            )
            rerun.gate.approved_by = "operator"
            rerun.gate.resolved_at = utc_now_iso()
            return rerun
        return record

    @staticmethod
    def _proposal_auto_allowed_under_policy(
        proposal: ActionProposal,
        policy: ExecutionPolicy,
    ) -> bool:
        if (
            proposal.kind == "runtime_delegate"
            and os.environ.get("FLUXIO_RUNTIME_DELEGATION_MODE") == "local_shim"
        ):
            return proposal.risk_level != "high" and proposal.mutability_class != "destructive"
        if proposal.risk_level == "high" or proposal.mutability_class == "destructive":
            return False
        if proposal.kind in policy.approval_required_kinds:
            return False
        if proposal.kind in policy.auto_allowed_kinds:
            return True
        return policy.approval_mode == "hands_free"
