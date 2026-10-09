"""Shrink chat storage written before turns stored references instead of session windows.

Run it while no Neyvia backend is using the workspace:

    python -m grant_agent.chat_storage_compaction --root <workspace> [--dry-run] [--vacuum]

Old rows stay readable without it; it only reclaims space. Every converted
row is read back through the normal read path before it is kept.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .chat_run_control import compact_recorded_results
from .neyvia_conversations import NeyviaConversationStore


def compact_chat_storage(
    root: Path,
    *,
    database_path: Path | None = None,
    dry_run: bool = False,
    vacuum: bool = False,
) -> dict[str, Any]:
    store = NeyviaConversationStore(root, database_path=database_path)
    size_before = store.database_path.stat().st_size
    turns = store.compact_turn_compartments(dry_run=dry_run, vacuum=vacuum)
    return {
        "database": str(store.database_path),
        "databaseBytesBefore": size_before,
        "databaseBytesAfter": store.database_path.stat().st_size,
        "turns": turns,
        "results": compact_recorded_results(root, dry_run=dry_run),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, type=Path, help="Workspace containing .agent_control")
    parser.add_argument("--database", type=Path, default=None, help="Defaults to <root>/.agent_control/crashproof.sqlite3")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
    parser.add_argument("--vacuum", action="store_true", help="Return freed pages to the filesystem afterwards")
    args = parser.parse_args(argv)
    report = compact_chat_storage(args.root, database_path=args.database, dry_run=args.dry_run, vacuum=args.vacuum)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
