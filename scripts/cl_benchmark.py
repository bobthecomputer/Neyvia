"""Run the fixed five-layer paired Connected Language evaluation on real models."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.benchmark import run
from grant_agent.cl.benchmark_provider import propose


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO / ".agent_control/cl/benchmark/run")
    parser.add_argument("--tasks", nargs="+")
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--arms", nargs="+", choices=("a", "b", "c"))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--chart-observation", type=Path, help="Reuse an actual raw image transcription across paired cohorts")
    parser.add_argument("--context-mode", choices=("compact", "production"), default="compact")
    args = parser.parse_args()
    if args.smoke:
        for model in args.models or ("gpt-6-luna", "gpt-6.1-sol"):
            print(propose("Return only READY. Do not call tools.", model, args.output / model), flush=True)
    else:
        run(args.output, args.tasks, args.models, args.arms, args.chart_observation, args.context_mode)


if __name__ == "__main__":
    main()
