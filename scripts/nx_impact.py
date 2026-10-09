"""Impact map from the command line: what do these changed files connect to, and what is broken today?

    python scripts/nx_impact.py                     # uncommitted changes of this repository
    python scripts/nx_impact.py web/src/neyvia/next/nxApi.js src/grant_agent/neyvia_awareness.py
    python scripts/nx_impact.py --gaps --json       # static wiring gaps and review leads, as JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grant_agent.neyvia_impact import impact  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="List what changed files connect to.")
    parser.add_argument("paths", nargs="*", help="changed files (default: git's uncommitted changes)")
    parser.add_argument("--gaps", action="store_true", help="repository-wide static wiring gaps and review leads, with every item")
    parser.add_argument("--no-gaps", action="store_true", help="skip the repository-wide check")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args()
    if args.gaps:
        from grant_agent.neyvia_impact import find_gaps, index
        found = find_gaps(index())
        if args.json:
            print(json.dumps(found, indent=1))
        else:
            for value in found.values():
                print(f"{value['help']}: {len(value['items'])}")
                for item in value["items"]:
                    where = value.get("where", {}).get(item)
                    print("   " + item + (f"   ({', '.join(where)})" if where else ""))
        return 0
    result = impact(args.paths, gaps=not args.no_gaps)
    print(json.dumps(result, indent=1) if args.json else result["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
