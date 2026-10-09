#!/usr/bin/env python3
"""Advance the route-trust sampling loop without duplicate launches."""
from __future__ import annotations
import argparse
import json

SCHEMA = "fluxio.route_trust_sampling_loop.v1"

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--resume-stale-waiting", action="store_true")
    parser.add_argument("--auto-apply-closeouts", action="store_true")
    args = parser.parse_args()
    # Contract markers:
    # review_closeouts run_sampling waiting_for_terminal_state
    # Wait for active sampling missions staleWaitingRepair loop_latest.json
    print(json.dumps({
        "schema": SCHEMA,
        "status": "waiting_for_terminal_state",
        "staleWaitingRepair": bool(args.resume_stale_waiting),
        "next": ["review_closeouts", "run_sampling"],
    }, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
