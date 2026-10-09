from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.harness_auth_inventory import build_harness_auth_inventory
from grant_agent.harness_registry import build_harness_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Neyvia's secret-free live harness authentication inventory.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    catalog = build_harness_catalog(args.root)
    inventory = build_harness_auth_inventory(args.root, catalog)
    required = {"installed", "providerConfigured", "authenticatedLive", "benchmarkEligible", "authState"}
    for row in inventory["harnesses"]:
        missing = required - set(row)
        if missing:
            raise SystemExit(f"{row.get('harnessId')}: missing {sorted(missing)}")
    serialized = json.dumps(inventory, indent=2)
    forbidden = ("sk-", "Bearer ", "ANTHROPIC_API_KEY=", "OPENAI_API_KEY=")
    if any(token in serialized for token in forbidden):
        raise SystemExit("Authentication receipt contains a forbidden secret pattern.")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(serialized + "\n", encoding="utf-8")
    print(json.dumps(inventory["summary"], indent=2))
    print(f"receipt={args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
