#!/usr/bin/env python3
"""Sync non-secret NAS system audit evidence into the local control root."""
from __future__ import annotations
import argparse
import json

NON_SECRET_EVIDENCE_FILES = [
    ".agent_control/cross_device_launch_rehearsals/receipts.jsonl",
    ".agent_control/deployment_evidence/public-web.json",
    ".agent_control/deployment_evidence/private-nas-web.json",
    ".agent_control/red_team_escalation_history.jsonl",
    ".agent_control/t3_code_benchmark_latest.json",
]

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    print(json.dumps({
        "schema": "fluxio.nas_system_audit_sync.v1",
        "root": args.root,
        "files": NON_SECRET_EVIDENCE_FILES,
    }, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
