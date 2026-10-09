"""Validate an immutable Neyvia agent-submission receipt without source writes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from grant_agent.agent_submission_gate import validate_receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="source worktree to validate")
    parser.add_argument("--phase-policy", type=Path, help="optional phase-to-path policy JSON")
    arguments = parser.parse_args(argv)
    try:
        receipt = json.loads(arguments.receipt.read_text(encoding="utf-8"))
        policy = json.loads(arguments.phase_policy.read_text(encoding="utf-8")) if arguments.phase_policy else None
    except (OSError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "errors": [f"invalid input: {error}"]}))
        return 2
    if not isinstance(receipt, dict) or (policy is not None and not isinstance(policy, dict)):
        print(json.dumps({"ok": False, "errors": ["receipt and policy must be JSON objects"]}))
        return 2
    result = validate_receipt(receipt, root=arguments.root, phase_policy=policy)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
