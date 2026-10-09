from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from grant_agent.harness_comparison import (
    TASKS,
    WINNER_RULE,
    grade_output,
    select_leader,
    summarize_attempts,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recompute a captured live harness comparison without changing its receipts."
    )
    parser.add_argument("--proof-dir", type=Path, required=True)
    parser.add_argument("--nas-mapped-root", type=Path, default=Path("Y:/projects/vibe-coding-platform"))
    args = parser.parse_args()
    proof_dir = args.proof_dir.resolve(strict=True)
    report_path = proof_dir / "comparison.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    attempts = report.get("attempts") or []
    for attempt in attempts:
        attempt["grade"] = grade_output(str(attempt.get("taskId") or ""), attempt.get("output"))
    catalog = report.get("catalogHarnesses") or []
    report["winnerRule"] = WINNER_RULE
    report["tasks"] = [
        {
            "id": task["id"],
            "fixturePaths": task["fixturePaths"],
            "expectedFields": list(task["expected"]),
            "maxPoints": len(task["expected"]),
        }
        for task in TASKS
    ]
    report["summaries"] = summarize_attempts(catalog, attempts)
    report["leader"] = select_leader(report["summaries"])
    report["gradedAt"] = datetime.now(timezone.utc).isoformat()
    report["gradingNote"] = (
        "Regraded from unchanged raw terminal receipts after correcting the frozen fixture's "
        "source-line expectation; model outputs and job evidence were not rerun or edited."
    )
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    mapped_root = args.nas_mapped_root
    if mapped_root.exists():
        latest = mapped_root / ".agent_control" / "harness_comparison" / "latest.json"
        latest.parent.mkdir(parents=True, exist_ok=True)
        temporary = latest.with_suffix(".tmp")
        temporary.write_bytes(report_path.read_bytes())
        temporary.replace(latest)
        shutil.copytree(
            proof_dir,
            mapped_root / ".agent_control" / "proof" / proof_dir.name,
            dirs_exist_ok=True,
        )
    print(json.dumps({"ok": True, "leader": report["leader"], "attempts": len(attempts)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
