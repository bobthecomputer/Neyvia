#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEWPORTS = (
    {"name": "phone", "width": 390, "height": 844},
    {"name": "tablet", "width": 834, "height": 1112},
    {"name": "desktop", "width": 1440, "height": 1200},
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture the real control route at phone, tablet, and desktop sizes.")
    parser.add_argument("--url", default="http://127.0.0.1:1420/control?preview-control=1&fixture=live_review&mode=builder&surface=workbench")
    parser.add_argument("--out-dir", default="tmp-ui-checks/responsive")
    parser.add_argument("--measure-performance", action="store_true")
    parser.add_argument("--assert-launch-interactions", action="store_true")
    parser.add_argument("--long-history-fixture", action="store_true")
    parser.add_argument("--expect", action="append", default=[])
    args = parser.parse_args()
    reports = []
    for viewport in VIEWPORTS:
        command = [
            sys.executable,
            "scripts/control_route_visual_smoke.py",
            "--url", args.url,
            "--out-dir", str(Path(args.out_dir) / viewport["name"]),
            "--name", viewport["name"],
            "--width", str(viewport["width"]),
            "--height", str(viewport["height"]),
        ]
        if args.measure_performance:
            command.append("--measure-performance")
        if args.assert_launch_interactions:
            command.append("--assert-launch-interactions")
        if args.long_history_fixture:
            command.extend(["--long-history-fixture", "--assert-launch-interactions"])
        for fragment in args.expect:
            command.extend(["--expect", fragment])
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        reports.append({
            **viewport,
            "passed": completed.returncode == 0,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        })
    receipt = {
        "schema": "fluxio.responsive_control_route.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(row["passed"] for row in reports) else "blocked",
        "viewports": reports,
    }
    output = ROOT / args.out_dir / "responsive-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
