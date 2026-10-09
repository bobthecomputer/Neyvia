from __future__ import annotations

import json
from pathlib import Path


def _verification_block(results: list[dict]) -> str:
    if not results:
        return "- No verification commands were run."
    lines: list[str] = []
    for item in results:
        status = item.get("status", "executed")
        code = item.get("return_code", 1)
        cmd = item.get("command", "")
        risk = item.get("risk_level", "low")
        lines.append(f"- `{cmd}` -> code={code}, status={status}, risk={risk}")
    return "\n".join(lines)


def write_run_report(
    session_path: Path,
    objective: str,
    session_lineage: list[str],
    handoff_paths: list[str],
    state: dict,
) -> dict[str, str]:
    report_path = session_path / "run_report.md"
    tweet_path = session_path / "tweet_thread.txt"

    completed = state.get("completed_steps", [])
    remaining = [step for step in state.get("plan_steps", []) if step not in completed]
    skills = state.get("retrieved_skills", [])
    verification = state.get("verification_results", [])
    context = state.get("context", {})
    doc_evidence = state.get("doc_evidence", [])
    readable_docs = len([item for item in doc_evidence if item.get("status") == "ok"])
    memory_items = state.get("memory_item_ids", [])

    report = "\n".join(
        [
            "# Run Report",
            "",
            "## Objective",
            objective,
            "",
            "## Session Stats",
            f"- Session lineage length: {len(session_lineage)}",
            f"- Handoff packets: {len(handoff_paths)}",
            f"- Context usage ratio: {context.get('usage_ratio', 0)}",
            f"- Context status: {context.get('status', 'unknown')}",
            f"- Readable docs: {readable_docs}/{len(doc_evidence)}",
            f"- Memory items written: {len(memory_items)}",
            "",
            "## Plan Progress",
            "- Completed steps:",
            *[f"  - {step}" for step in completed],
            "- Remaining steps:",
            *([f"  - {step}" for step in remaining] if remaining else ["  - none"]),
            "",
            "## Retrieved Skills",
            *([f"- {skill}" for skill in skills] if skills else ["- none"]),
            "",
            "## Verification",
            _verification_block(verification),
            "",
        ]
    )
    report_path.write_text(report + "\n", encoding="utf-8")

    tweet_lines = [
        "Thread draft:",
        f"1/ Built a docs-first autonomous coding run for: {objective}",
        (
            "2/ Added context rollover with handoff packets so sessions continue "
            f"without losing progress ({len(handoff_paths)} handoffs in this run)."
        ),
        (
            "3/ Added safety rails: preflight policy + risky command blocking + "
            "verification traces."
        ),
        (
            "4/ Added skill retrieval and run artifacts for replay/debugging "
            f"(lineage depth {len(session_lineage)})."
        ),
        "5/ Next: GUI cockpit + model adapters + benchmark dashboards.",
    ]
    tweet_path.write_text("\n".join(tweet_lines) + "\n", encoding="utf-8")

    summary_path = session_path / "public_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "objective": objective,
                "lineage": session_lineage,
                "handoff_count": len(handoff_paths),
                "context": context,
                "skills": skills,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "report_path": str(report_path),
        "tweet_thread_path": str(tweet_path),
        "public_summary_path": str(summary_path),
    }
