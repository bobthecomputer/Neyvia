"""Write the deterministic Neyvia dependency inventory without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.dependency_inventory import DependencyInventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument(
        "--output",
        default=".agent_control/dependency_inventory.json",
        help="JSON report path relative to --root",
    )
    parser.add_argument(
        "--proof-output",
        default="",
        help="Optional compact proof-receipt path relative to --root",
    )
    parser.add_argument(
        "--require-updater-eligible",
        action="store_true",
        help="Fail unless every critical release dependency is resolved",
    )
    args = parser.parse_args()
    inventory = DependencyInventory(Path(args.root))
    output = inventory.write(args.output)
    print(output)
    if args.proof_output:
        payload = inventory.verify_written(output)
        receipt = inventory.proof_receipt(payload)
        receipt["rebuildVerification"] = {
            "performed": True,
            "comparison": "literal-canonical-bytes",
            "inventoryFileSha256": hashlib.sha256(
                output.read_bytes()
            ).hexdigest(),
        }
        receipt_path = Path(args.proof_output)
        if not receipt_path.is_absolute():
            receipt_path = inventory.root / receipt_path
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(receipt_path)
    if args.require_updater_eligible:
        inventory.verify_written(output, require_critical_resolved=True)
        print("updater-preflight-eligible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
