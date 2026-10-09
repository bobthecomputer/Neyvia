from __future__ import annotations

from .proofs_c_models import checked


@checked("advisor")
def recommend_improvements(metrics: dict, bundles: list[dict], top_k: int = 6) -> list[dict]:
    recs: list[dict] = []

    total = max(1, int(metrics.get("total_sessions", 0)))
    handoff_ratio = float(metrics.get("sessions_with_handoff", 0)) / total
    fail_count = int(metrics.get("verification_failures", 0))
    blocked = int(metrics.get("blocked_commands", 0))
    memory_runs = int(metrics.get("runs_with_memory_writes", 0))
    doc_runs = int(metrics.get("runs_with_doc_evidence", 0))

    probe_scores = [int(item.get("resistance_score", 0)) for item in bundles]
    avg_probe = round(sum(probe_scores) / len(probe_scores), 2) if probe_scores else 0

    if handoff_ratio > 0.45:
        recs.append(
            {
                "feature": "Context Compaction Tuning",
                "priority": "high",
                "why": "Handoff frequency is high; reduce context churn and preserve continuity.",
                "next_step": "Add stronger compaction snapshots and adaptive rollover thresholds by mode.",
            }
        )

    if fail_count > 0:
        recs.append(
            {
                "feature": "Verification Matrix",
                "priority": "high",
                "why": "Verification failures still occur in completed runs.",
                "next_step": "Map file-change categories to mandatory checks and retry policy.",
            }
        )

    if avg_probe < 75:
        recs.append(
            {
                "feature": "Adversarial Strategy Expansion",
                "priority": "high",
                "why": "Average probe resistance is below target.",
                "next_step": "Add stronger prompt-injection families and refusal consistency tests.",
            }
        )

    if memory_runs < max(2, total // 3):
        recs.append(
            {
                "feature": "Memory Coverage Boost",
                "priority": "medium",
                "why": "Memory is not used frequently enough across runs.",
                "next_step": "Store more granular memory items and auto-inject top memory into prompt stack.",
            }
        )

    if doc_runs < total:
        recs.append(
            {
                "feature": "Docs Reliability Monitor",
                "priority": "medium",
                "why": "Not every run has readable doc evidence.",
                "next_step": "Add doc fallback retrieval and explicit missing-doc action items.",
            }
        )

    if blocked >= 0:
        recs.append(
            {
                "feature": "Approval Gates",
                "priority": "medium",
                "why": "Safety blocking exists, but explicit human approval checkpoints improve trust.",
                "next_step": "Require manual approval for medium/high risk commands and sensitive file scopes.",
            }
        )

    recs.append(
        {
            "feature": "Dashboard Drill-Down",
            "priority": "low",
            "why": "Stakeholders need faster insight from many bundles.",
            "next_step": "Add trend charts and side-by-side bundle diff in proof dashboard.",
        }
    )

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(recs, key=lambda item: priority_rank.get(item.get("priority", "low"), 2))[:top_k]
