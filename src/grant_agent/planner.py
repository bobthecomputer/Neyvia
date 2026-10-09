from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import uuid

from .models import PlanReceipt


@dataclass
class PlanBundle:
    plan_steps: list[str]
    creative_alternatives: list[str]
    acceptance_checks: list[str]


def build_docs_first_plan(objective: str, docs: list[str]) -> PlanBundle:
    lowered = objective.lower()
    execute_first = (
        "execute first" in lowered
        or "no preflight" in lowered
        or "first action must" in lowered
    )
    if execute_first:
        steps = [
            "Implement smallest vertical slice in product files",
            "Run focused verification checks and inspect diffs",
            "Prepare receipt with changed files and next product slice",
        ]
        alternatives = [
            "Patch the narrowest existing product model/UI surface before broadening scope",
            "Delegate the implementation lane directly, then verify only touched surfaces",
        ]
        checks = [
            "Product files changed before any verification command",
            "Focused verification runs only after implementation",
            "Receipt includes changed files, remaining gaps, and next idea",
        ]
        if "ui" in lowered or "preview" in lowered:
            checks.append("Preview reflects expected UI behavior on desktop and mobile")
        plan = PlanBundle(
            plan_steps=steps,
            creative_alternatives=alternatives,
            acceptance_checks=checks,
        )
        from .proofs_d_ui_planning import check_plan
        check_plan(objective, docs, plan)
        return plan

    doc_step = (
        "Review referenced docs and extract constraints"
        if docs
        else "Collect missing docs/spec links before implementation"
    )
    steps = [
        doc_step,
        "Draft implementation plan with milestones",
        "Implement smallest vertical slice",
        "Run verification checks and inspect diffs",
        "Prepare rollout notes and next iteration tasks",
    ]
    alternatives = [
        "Use a strict deterministic mode for lower cost and higher reproducibility",
        "Use a creative exploration mode for ideation, then switch to strict mode for execution",
    ]
    checks = [
        "All changed files compile or parse cleanly",
        "Relevant test command completes successfully",
        "Handoff packet includes unresolved risks and next actions",
    ]
    if "ui" in objective.lower() or "preview" in objective.lower():
        checks.append("Preview reflects expected UI behavior on desktop and mobile")
    plan = PlanBundle(plan_steps=steps, creative_alternatives=alternatives, acceptance_checks=checks)
    from .proofs_d_ui_planning import check_plan
    check_plan(objective, docs, plan)
    return plan


def build_docs_first_plan_receipt(
    *,
    objective: str,
    docs: list[str],
    mission_id: str,
    host: str,
    runtime: str,
    workspace: str,
    mission_run_id: str = "",
    file_scope: list[str] | None = None,
    selected_skills: list[str] | None = None,
    skill_brief: Any | None = None,
    forbidden_paths: list[str] | None = None,
    expected_changed_files: list[str] | None = None,
    expected_artifacts: list[str] | None = None,
    maximum_repair_loops: int = 1,
) -> PlanReceipt:
    plan = build_docs_first_plan(objective, docs)
    skill_brief_payload = _skill_brief_payload(skill_brief)
    explicit_selected_skills = (
        selected_skills
        if selected_skills is not None
        else _selected_skill_ids_from_brief(skill_brief_payload)
    )
    compact_tasks = [
        {
            "id": f"task_{index}",
            "title": _compact_text(step, 160),
            "status": "pending",
        }
        for index, step in enumerate(plan.plan_steps, start=1)
    ]
    receipt = PlanReceipt(
        receipt_id=f"receipt_plan_{uuid.uuid4().hex[:12]}",
        mission_id=mission_id,
        host=host,
        runtime=runtime,
        workspace=workspace,
        status="planned",
        summary=_compact_text(
            f"Planner produced {len(compact_tasks)} task(s) and {len(plan.acceptance_checks)} verifier check(s).",
            240,
        ),
        goal_restatement=_compact_text(objective, 500),
        assumptions=[_compact_text(item, 180) for item in plan.creative_alternatives[:4]],
        tasks=compact_tasks,
        file_scope=[_compact_text(item, 240) for item in (file_scope or []) if str(item or "").strip()][:80],
        selected_skills=[_compact_text(item, 120) for item in (explicit_selected_skills or []) if str(item or "").strip()][:24],
        forbidden_paths=[_compact_text(item, 240) for item in (forbidden_paths or []) if str(item or "").strip()][:40],
        expected_changed_files=[
            _compact_text(item, 240) for item in (expected_changed_files or []) if str(item or "").strip()
        ][:80],
        expected_artifacts=[
            _compact_text(item, 240) for item in (expected_artifacts or []) if str(item or "").strip()
        ][:40],
        verification_ladder=[_compact_text(item, 180) for item in plan.acceptance_checks[:12]],
        risk_level=_risk_level_for_objective(objective),
        maximum_repair_loops=max(0, int(maximum_repair_loops)),
        inputs={
            "objectiveLength": len(objective or ""),
            "docCount": len(docs or []),
            "docsTruncated": any(len(str(item or "")) > 500 for item in docs or []),
            "skillBriefId": skill_brief_payload.get("brief_id") or "",
            "skillBriefSchema": skill_brief_payload.get("schema") or "",
            "skillBriefSkillCount": len(skill_brief_payload.get("selected_skills", []) if isinstance(skill_brief_payload.get("selected_skills"), list) else []),
        },
        outputs={
            "taskCount": len(compact_tasks),
            "verificationCheckCount": len(plan.acceptance_checks),
        },
        next_action="Executor should consume this compact PlanReceipt plus current workspace facts.",
        mission_run_id=mission_run_id,
    )
    from .proofs_d_ui_planning import check_plan_receipt
    check_plan_receipt(receipt, objective, docs, selected_skills, skill_brief_payload, plan)
    return receipt


def _compact_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _skill_brief_payload(skill_brief: Any | None) -> dict[str, Any]:
    if skill_brief is None:
        return {}
    if hasattr(skill_brief, "__dataclass_fields__"):
        return asdict(skill_brief)
    if isinstance(skill_brief, dict):
        return dict(skill_brief)
    return {}


def _selected_skill_ids_from_brief(payload: dict[str, Any]) -> list[str]:
    selected = payload.get("selected_skills")
    if not isinstance(selected, list):
        return []
    skill_ids: list[str] = []
    for item in selected:
        if isinstance(item, dict):
            value = item.get("skillId") or item.get("skill_id") or item.get("label")
        else:
            value = item
        text = _compact_text(str(value or ""), 120)
        if text:
            skill_ids.append(text)
    return skill_ids[:24]


def _risk_level_for_objective(objective: str) -> str:
    lowered = str(objective or "").lower()
    high_markers = ("delete", "destructive", "production", "secret", "credential", "deploy")
    if any(marker in lowered for marker in high_markers):
        return "high"
    medium_markers = ("write", "edit", "implement", "change", "sync")
    if any(marker in lowered for marker in medium_markers):
        return "medium"
    return "low"
