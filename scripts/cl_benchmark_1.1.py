"""Freeze/review/resume CL 1.1 cohorts; scored runs require reviewed task inputs."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.benchmark11 import freeze, run
from grant_agent.cl.provider11 import MODELS, proposal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe", "freeze-dev", "freeze-scored", "run", "report"))
    parser.add_argument("--output", type=Path, default=REPO / ".agent_control/cl11/cohort-1")
    parser.add_argument("--review-approved", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--arm", choices=("a", "b", "c", "codex-alone", "claude-alone"))
    parser.add_argument("--task", type=int)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--max-actions", type=int, default=48)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--port', type=int, default=48282,
                        help='First owned fixture port; one consecutive port per worker')
    parser.add_argument("--report", type=Path, default=REPO / "docs/evidence/cl-benchmark-1.1.md")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(REPO):
        parser.error("Cohort output must stay in nx-cl")
    if args.mode == "probe":
        for model in MODELS:
            receipt = proposal("Return only READY. Do not call tools.", model, output / model)
            print(json.dumps({k: receipt.get(k) for k in ("requestedModel", "passed", "usage", "errors", "stderr")}), flush=True)
    elif args.mode.startswith("freeze-"):
        manifest = freeze(output, scored=args.mode == "freeze-scored", approved=args.review_approved,
                          max_turns=args.max_turns, max_actions=args.max_actions, workers=args.workers)
        print(json.dumps({"scheduled": len(manifest["schedule"]), "manifest": str(output / "manifest.json")}), flush=True)
    else:
        summary = run(output, limit=0 if args.mode == "report" else args.limit,
                      report=args.report, arm=args.arm, task=args.task, port_start=args.port)
        print(json.dumps(summary["gates"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
