from __future__ import annotations

import uuid
from typing import Any

from .models import SubAgentReceipt
from .proofs_e_sv import enforced

SUB_AGENT_ROLES = {
    "isolated_research",
    "review",
    "diagnostics",
    "parallel_file_inspection",
    "ui_verification",
    "log_summarization",
}
SUB_AGENT_STATUSES = {"completed", "blocked", "failed", "partial"}


@enforced("sv.subagent.advisory-bounds")
def build_sub_agent_receipt(
    *,
    mission_id: str,
    assignment: str,
    role: str,
    status: str,
    inputs: dict[str, Any] | None = None,
    files_inspected: list[str] | None = None,
    findings: list[dict[str, Any]] | None = None,
    confidence: float = 0.0,
    proof_paths: list[str] | None = None,
    next_recommendation: str = "",
    mission_run_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> SubAgentReceipt:
    normalized_role = _normalized_choice(role, SUB_AGENT_ROLES, "review")
    normalized_status = _normalized_choice(status, SUB_AGENT_STATUSES, "partial")
    bounded_findings = [_compact_finding(item) for item in (findings or []) if isinstance(item, dict)][:16]
    return SubAgentReceipt(
        receipt_id=f"receipt_sub_agent_{uuid.uuid4().hex[:12]}",
        mission_id=_compact_text(mission_id, 120),
        assignment=_compact_text(assignment, 500),
        role=normalized_role,
        status=normalized_status,
        inputs=_compact_inputs(inputs or {}),
        files_inspected=_bounded_strings(files_inspected or [], limit=80, text_limit=240),
        findings=bounded_findings,
        confidence=round(max(0.0, min(1.0, float(confidence or 0.0))), 3),
        proof_paths=_bounded_strings(proof_paths or [], limit=40, text_limit=240),
        next_recommendation=_compact_text(next_recommendation, 300),
        mission_run_id=_compact_text(mission_run_id, 120),
        metadata=_compact_inputs(metadata or {}, limit=20, text_limit=180),
    )


def _normalized_choice(value: str, allowed: set[str], fallback: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in allowed else fallback


def _compact_finding(item: dict[str, Any]) -> dict[str, Any]:
    severity = str(item.get("severity") or "info").strip().lower()
    if severity not in {"info", "low", "medium", "high", "critical"}:
        severity = "info"
    return {
        "severity": severity,
        "summary": _compact_text(item.get("summary") or item.get("title") or "", 220),
        "evidence": _bounded_strings(item.get("evidence") or [], limit=6, text_limit=180),
        "file": _compact_text(item.get("file") or "", 240),
        "line": item.get("line") if isinstance(item.get("line"), int) else None,
    }


def _compact_inputs(
    payload: dict[str, Any],
    *,
    limit: int = 24,
    text_limit: int = 240,
) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if len(compact) >= limit:
            break
        compact_key = _compact_text(key, 80)
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[compact_key] = _compact_text(value, text_limit) if isinstance(value, str) else value
        elif isinstance(value, list):
            compact[compact_key] = _bounded_strings(value, limit=12, text_limit=text_limit)
        elif isinstance(value, dict):
            compact[compact_key] = {
                _compact_text(inner_key, 80): _compact_text(inner_value, text_limit)
                for inner_key, inner_value in list(value.items())[:8]
            }
        else:
            compact[compact_key] = _compact_text(value, text_limit)
    return compact


def _bounded_strings(values: list[Any], *, limit: int, text_limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _compact_text(value, text_limit)
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
        if len(output) >= limit:
            break
    return output


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
