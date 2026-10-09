from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Neyvia HTML benchmark proof bundle.")
    parser.add_argument("--proof-dir", type=Path, required=True)
    parser.add_argument("--require-live", action="store_true")
    args = parser.parse_args()
    pointer = json.loads((args.proof_dir / "latest.json").read_text(encoding="utf-8"))
    report_path = Path(pointer["report"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    attempts = report.get("attempts") or []
    completed = [row for row in attempts if row.get("status") == "completed"]
    if args.require_live and len(completed) < 2:
        raise SystemExit("At least two exact live routes must complete.")
    if any(row.get("exactRoute") is not True or row.get("fallbackAllowed") is not False for row in attempts):
        raise SystemExit("Every attempt must be exact-route with fallback disabled.")
    for row in completed:
        if not (report_path.parent / row["artifact"]).is_file():
            raise SystemExit(f"Missing artifact for {row['id']}")
        if not (report_path.parent / row["terminalReceipt"]).is_file():
            raise SystemExit(f"Missing terminal receipt for {row['id']}")
    if report.get("negativeControl", {}).get("passed") is not False:
        raise SystemExit("Negative control was not rejected.")
    if report.get("status") != "measured":
        raise SystemExit("Benchmark is not measured.")
    print(json.dumps({"status": "verified", "completed": len(completed), "leader": report.get("leader"), "report": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
