from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from .models import (
    EXECUTION_RECEIPT_SCHEMA_VERSION,
    PLAN_RECEIPT_SCHEMA_VERSION,
    ExecutionReceipt,
    PlanReceipt,
)

EXECUTOR_PHASE_INPUT_SCHEMA = "fluxio.executor_phase_input.v1"
VERIFIER_PHASE_INPUT_SCHEMA = "fluxio.verifier_phase_input.v1"
SKILL_RELEVANCE_CHECK_SCHEMA = "fluxio.skill_relevance_check.v1"


@dataclass
class ExecutorPhaseInput:
    schema: str
    original_goal: str
    plan_receipt: dict[str, Any]
    selected_skills: list[str]
    file_scope: list[str]


@dataclass
class VerifierPhaseInput:
    schema: str
    original_goal: str
    plan_receipt: dict[str, Any]
    execution_receipt: dict[str, Any]
    changed_files: list[str]
    proof_artifacts: list[str]


def build_executor_phase_input(
    *,
    original_goal: str,
    plan_receipt: PlanReceipt | dict[str, Any],
) -> ExecutorPhaseInput:
    payload = asdict(plan_receipt) if hasattr(plan_receipt, "__dataclass_fields__") else dict(plan_receipt)
    if payload.get("schema") != PLAN_RECEIPT_SCHEMA_VERSION:
        raise ValueError("executor input requires a PlanReceipt payload")
    selected_skills = _bounded_string_list(payload.get("selected_skills"), limit=24, text_limit=120)
    file_scope = _bounded_string_list(payload.get("file_scope"), limit=80, text_limit=240)
    capsule = ExecutorPhaseInput(
        schema=EXECUTOR_PHASE_INPUT_SCHEMA,
        original_goal=_compact_text(original_goal, 1000),
        plan_receipt=_compact_plan_receipt(payload),
        selected_skills=selected_skills,
        file_scope=file_scope,
    )
    from .proofs_c_missions import check_capsule
    check_capsule(capsule)
    return capsule


def build_verifier_phase_input(
    *,
    original_goal: str,
    plan_receipt: PlanReceipt | dict[str, Any],
    execution_receipt: ExecutionReceipt | dict[str, Any],
    changed_files: list[str] | None = None,
    proof_artifacts: list[str] | None = None,
) -> VerifierPhaseInput:
    plan_payload = asdict(plan_receipt) if hasattr(plan_receipt, "__dataclass_fields__") else dict(plan_receipt)
    execution_payload = (
        asdict(execution_receipt)
        if hasattr(execution_receipt, "__dataclass_fields__")
        else dict(execution_receipt)
    )
    if plan_payload.get("schema") != PLAN_RECEIPT_SCHEMA_VERSION:
        raise ValueError("verifier input requires a PlanReceipt payload")
    if execution_payload.get("schema") != EXECUTION_RECEIPT_SCHEMA_VERSION:
        raise ValueError("verifier input requires an ExecutionReceipt payload")
    receipt_changed_files = _bounded_string_list(
        execution_payload.get("changed_files"), limit=80, text_limit=240
    )
    merged_changed_files = _dedupe_preserving_order(
        [
            *_bounded_string_list(changed_files or [], limit=80, text_limit=240),
            *receipt_changed_files,
        ],
        limit=80,
    )
    receipt_proof_paths = _bounded_string_list(
        execution_payload.get("proof_paths"), limit=40, text_limit=240
    )
    merged_proof_artifacts = _dedupe_preserving_order(
        [
            *_bounded_string_list(proof_artifacts or [], limit=40, text_limit=240),
            *receipt_proof_paths,
        ],
        limit=40,
    )
    capsule = VerifierPhaseInput(
        schema=VERIFIER_PHASE_INPUT_SCHEMA,
        original_goal=_compact_text(original_goal, 1000),
        plan_receipt=_compact_plan_receipt(plan_payload),
        execution_receipt=_compact_execution_receipt(execution_payload),
        changed_files=merged_changed_files,
        proof_artifacts=merged_proof_artifacts,
    )
    from .proofs_c_missions import check_capsule
    check_capsule(capsule)
    return capsule


def check_selected_skill_relevance(
    *,
    original_goal: str,
    plan_receipt: PlanReceipt | dict[str, Any],
    skill_brief: Any | None = None,
) -> dict[str, Any]:
    plan_payload = asdict(plan_receipt) if hasattr(plan_receipt, "__dataclass_fields__") else dict(plan_receipt)
    if plan_payload.get("schema") != PLAN_RECEIPT_SCHEMA_VERSION:
        raise ValueError("skill relevance check requires a PlanReceipt payload")
    selected = _bounded_string_list(plan_payload.get("selected_skills"), limit=24, text_limit=120)
    brief_payload = asdict(skill_brief) if hasattr(skill_brief, "__dataclass_fields__") else dict(skill_brief or {})
    brief_rows = brief_payload.get("selected_skills") if isinstance(brief_payload.get("selected_skills"), list) else []
    context_by_id: dict[str, str] = {}
    for row in brief_rows:
        if not isinstance(row, dict):
            continue
        skill_id = str(row.get("skillId") or row.get("skill_id") or row.get("label") or "").strip()
        if not skill_id:
            continue
        context_by_id[skill_id] = " ".join(
            str(value or "")
            for value in (
                row.get("skillId"),
                row.get("label"),
                row.get("description"),
                " ".join(str(item) for item in row.get("actionKinds", []) if isinstance(row.get("actionKinds"), list)),
            )
        )
    goal_tokens = _phase_tokens(original_goal)
    checks: list[dict[str, Any]] = []
    for skill_id in selected:
        context = context_by_id.get(skill_id, skill_id.replace("_", " "))
        context_tokens = _phase_tokens(context)
        overlap = sorted(goal_tokens & context_tokens)
        prefix_match = any(
            len(goal_token) >= 5
            and any(context_token.startswith(goal_token[:5]) for context_token in context_tokens)
            for goal_token in goal_tokens
        )
        relevant = bool(overlap or prefix_match)
        checks.append(
            {
                "skillId": skill_id,
                "relevant": relevant,
                "matchingTokens": overlap[:8],
                "reason": (
                    "Skill overlaps the goal or SkillBrief context."
                    if relevant
                    else "No meaningful overlap with the goal or SkillBrief context."
                ),
            }
        )
    irrelevant = [item for item in checks if not item["relevant"]]
    status = "blocked" if not selected else "review" if irrelevant else "passed"
    result = {
        "schema": SKILL_RELEVANCE_CHECK_SCHEMA,
        "status": status,
        "selectedSkillCount": len(selected),
        "irrelevantSkillCount": len(irrelevant),
        "checks": checks,
        "nextAction": (
            "Planner must select at least one skill before executor/verifier work."
            if not selected
            else "Review or replace irrelevant selected skills before trusting verifier output."
            if irrelevant
            else "Selected skills are relevant enough for verifier review."
        ),
    }
    from .proofs_c_missions import check_relevance
    check_relevance(result)
    return result


def _compact_plan_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema",
        "receipt_id",
        "mission_id",
        "mission_run_id",
        "generated_at",
        "phase",
        "host",
        "runtime",
        "workspace",
        "status",
        "summary",
        "goal_restatement",
        "assumptions",
        "tasks",
        "file_scope",
        "selected_skills",
        "forbidden_paths",
        "expected_changed_files",
        "expected_artifacts",
        "verification_ladder",
        "risk_level",
        "maximum_repair_loops",
        "proof_paths",
        "next_action",
    }
    compact = {key: payload.get(key) for key in allowed if key in payload}
    compact["summary"] = _compact_text(compact.get("summary", ""), 240)
    compact["goal_restatement"] = _compact_text(compact.get("goal_restatement", ""), 500)
    compact["assumptions"] = _bounded_string_list(compact.get("assumptions"), limit=4, text_limit=180)
    compact["tasks"] = _compact_tasks(compact.get("tasks"))
    compact["file_scope"] = _bounded_string_list(compact.get("file_scope"), limit=80, text_limit=240)
    compact["selected_skills"] = _bounded_string_list(compact.get("selected_skills"), limit=24, text_limit=120)
    compact["forbidden_paths"] = _bounded_string_list(compact.get("forbidden_paths"), limit=40, text_limit=240)
    compact["expected_changed_files"] = _bounded_string_list(
        compact.get("expected_changed_files"), limit=80, text_limit=240
    )
    compact["expected_artifacts"] = _bounded_string_list(
        compact.get("expected_artifacts"), limit=40, text_limit=240
    )
    compact["verification_ladder"] = _bounded_string_list(
        compact.get("verification_ladder"), limit=12, text_limit=180
    )
    compact["proof_paths"] = _bounded_string_list(compact.get("proof_paths"), limit=20, text_limit=240)
    compact["next_action"] = _compact_text(compact.get("next_action", ""), 240)
    return compact


def _compact_execution_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema",
        "receipt_id",
        "mission_id",
        "mission_run_id",
        "generated_at",
        "phase",
        "host",
        "runtime",
        "workspace",
        "status",
        "summary",
        "tasks_attempted",
        "tasks_completed",
        "changed_files",
        "commands_run",
        "stdout_summaries",
        "stderr_summaries",
        "errors_encountered",
        "skipped_work",
        "self_critique",
        "next_suggested_verifier_checks",
        "proof_paths",
        "next_action",
    }
    compact = {key: payload.get(key) for key in allowed if key in payload}
    compact["summary"] = _compact_text(compact.get("summary", ""), 240)
    compact["tasks_attempted"] = _bounded_string_list(
        compact.get("tasks_attempted"), limit=40, text_limit=180
    )
    compact["tasks_completed"] = _bounded_string_list(
        compact.get("tasks_completed"), limit=40, text_limit=180
    )
    compact["changed_files"] = _bounded_string_list(compact.get("changed_files"), limit=80, text_limit=240)
    compact["commands_run"] = _compact_commands(compact.get("commands_run"))
    compact["stdout_summaries"] = _bounded_string_list(
        compact.get("stdout_summaries"), limit=20, text_limit=240
    )
    compact["stderr_summaries"] = _bounded_string_list(
        compact.get("stderr_summaries"), limit=20, text_limit=240
    )
    compact["errors_encountered"] = _bounded_string_list(
        compact.get("errors_encountered"), limit=20, text_limit=240
    )
    compact["skipped_work"] = _bounded_string_list(compact.get("skipped_work"), limit=20, text_limit=240)
    compact["self_critique"] = _compact_text(compact.get("self_critique", ""), 500)
    compact["next_suggested_verifier_checks"] = _bounded_string_list(
        compact.get("next_suggested_verifier_checks"), limit=20, text_limit=180
    )
    compact["proof_paths"] = _bounded_string_list(compact.get("proof_paths"), limit=40, text_limit=240)
    compact["next_action"] = _compact_text(compact.get("next_action", ""), 240)
    return compact


def _compact_commands(value: Any) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        command = _compact_text(item.get("command") or item.get("cmd") or "", 240)
        if not command:
            continue
        commands.append(
            {
                "command": command,
                "exit_code": item.get("exit_code", item.get("return_code", "")),
                "status": _compact_text(item.get("status", ""), 80),
            }
        )
        if len(commands) >= 30:
            break
    return commands


def _compact_tasks(value: Any) -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []
    for index, item in enumerate(value if isinstance(value, list) else [], start=1):
        if isinstance(item, dict):
            title = item.get("title") or item.get("summary") or ""
            status = item.get("status") or "pending"
            task_id = item.get("id") or item.get("step_id") or f"task_{index}"
        else:
            title = str(item or "")
            status = "pending"
            task_id = f"task_{index}"
        if not str(title or "").strip():
            continue
        tasks.append(
            {
                "id": _compact_text(task_id, 80),
                "title": _compact_text(title, 160),
                "status": _compact_text(status, 40),
            }
        )
        if len(tasks) >= 40:
            break
    return tasks


def _phase_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) >= 3
    }


def _bounded_string_list(value: Any, *, limit: int, text_limit: int) -> list[str]:
    rows = value if isinstance(value, list) else []
    compact: list[str] = []
    for item in rows:
        text = _compact_text(item, text_limit)
        if text:
            compact.append(text)
        if len(compact) >= limit:
            break
    return compact


def _dedupe_preserving_order(values: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
        if len(output) >= limit:
            break
    return output


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
