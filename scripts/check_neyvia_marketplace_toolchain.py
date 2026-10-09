from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from grant_agent.marketplace_toolchain import (
    MarketplaceToolchainUpdateManager,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify Neyvia's pinned marketplace tools and discover official "
            "stable release candidates without changing the active toolchain."
        )
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument(
        "--skip-local-integrity",
        action="store_true",
        help="Use only on clean CI workers that do not host the pinned binaries.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--require-current", action="store_true")
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()

    manager = MarketplaceToolchainUpdateManager(arguments.root)
    local = (
        {
            "schema": "neyvia.marketplace-toolchain-integrity/v1",
            "healthy": True,
            "state": "not-run",
            "reason": "The clean maintenance worker does not host local binaries.",
        }
        if arguments.skip_local_integrity
        else manager.local_integrity()
    )
    latest = (
        None
        if arguments.local_only
        else manager.check_latest(force=arguments.force)
    )
    report = {
        "schema": "neyvia.marketplace-toolchain-maintenance/v1",
        "localIntegrity": local,
        "latestReleases": latest,
        "activationPolicy": (
            "Portable dependency candidates become active only through a "
            "tested, signed Neyvia release."
        ),
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.report:
        target = arguments.report.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized, encoding="utf-8")
    print(serialized)

    if not local["healthy"]:
        return 1
    if arguments.require_current and latest is not None:
        summary = latest["summary"]
        if summary["errors"] or summary["updatesAvailable"]:
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
