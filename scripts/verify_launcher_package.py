from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "scripts/launch_fluxio.py",
    "scripts/fluxio-cli.mjs",
    "scripts/run_web_backend.py",
    "web/dist/index.html",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the installable one-command Neyvia launcher.")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "web/dist")
    parser.add_argument("--output", type=Path, default=ROOT / ".agent_control/launcher/package.json")
    args = parser.parse_args()
    missing = [path for path in REQUIRED if not (args.build_dir / "index.html" if path == "web/dist/index.html" else ROOT / path).is_file()]
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    checks = {
        "filesPresent": not missing,
        "binRegistered": package.get("bin", {}).get("fluxio") == "scripts/fluxio-cli.mjs",
        "startRegistered": package.get("scripts", {}).get("start") == "python scripts/launch_fluxio.py",
    }
    receipt = {
        "schema": "fluxio.launcher_package.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(checks.values()) else "blocked",
        "checks": checks,
        "missing": missing,
        "buildDir": str(args.build_dir.resolve()),
    }
    if args.write:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
