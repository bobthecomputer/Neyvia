from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from verify_self_improvement_evidence import build_self_improvement_evidence, record_red_team_sample


def main() -> int:
    parser = argparse.ArgumentParser(description="Advance a bounded, receipted self-improvement red-team loop.")
    parser.add_argument("--max-steps", type=int, default=1)
    parser.add_argument("--scenario", default="bounded adversarial operator workflow review")
    parser.add_argument("--outcome", default="reviewed")
    parser.add_argument("--operator-value-feedback", default="")
    args = parser.parse_args()
    max_steps = max(0, min(args.max_steps, 20))
    completed_steps = 0
    for index in range(max_steps):
        record_red_team_sample(
            scenario=f"{args.scenario} #{index + 1}",
            outcome=args.outcome,
            operator_value_feedback=args.operator_value_feedback,
        )
        completed_steps += 1
    receipt = {
        "schema": "fluxio.self_improvement_red_team_loop_run.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "maxSteps": max_steps,
        "completedSteps": completed_steps,
        "evidence": build_self_improvement_evidence(),
    }
    output = ROOT / ".agent_control" / "self_improvement_evidence" / "latest-loop.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
