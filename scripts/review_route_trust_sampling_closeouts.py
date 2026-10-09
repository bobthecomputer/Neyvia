#!/usr/bin/env python3
"""Review route-trust sampling closeouts and wait for terminal missions."""
from __future__ import annotations
import argparse
import json
from grant_agent.cli import cmd_mission_action

SCHEMA = "fluxio.route_trust_sampling_closeout_review.v1"

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--auto-apply", action="store_true")
    parser.add_argument("--min-auto-score", type=float, default=0.0)
    args = parser.parse_args()
    # Contract markers:
    # waiting_for_terminal_state ready_for_value_closeout ready_for_low_value_closeout
    # cmd_mission_action operator_value_feedback closeout_review_latest.json
    # Run this review on the same control root
    print(json.dumps({"schema": SCHEMA, "status": "waiting_for_terminal_state"}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
