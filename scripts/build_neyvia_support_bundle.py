#!/usr/bin/env python3
"""Build a privacy-safe Neyvia diagnostic bundle from allowlisted local evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from grant_agent.support_bundle import (  # noqa: E402
    DEFAULT_MAX_JOBS,
    build_redacted_support_bundle,
)


def _default_output(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / ".agent_control" / "support_bundles" / f"neyvia-support-{stamp}.zip"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a bounded Neyvia support bundle that excludes prompts, raw results, "
            "raw logs, environment values, remote URLs, and credentials."
        )
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-jobs", type=int, default=DEFAULT_MAX_JOBS)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the requested output path if it already exists.",
    )
    args = parser.parse_args(argv)

    root = args.root.expanduser().resolve(strict=True)
    output = args.output.expanduser() if args.output else _default_output(root)
    result = build_redacted_support_bundle(
        root,
        output,
        max_jobs=args.max_jobs,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
