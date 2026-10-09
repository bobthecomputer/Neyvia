"""Collect Claude's documented status-line windows, or launch its UI without an AI turn.

No credential access, HTTP request, global settings edit, or raw stdin logging.
--launch supplies a collector with --settings for this process only.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.connected_sessions.plan_limits import record_claude_statusline


def launch_settings(root: Path) -> dict:
    command = subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve()), "--root", str(root.resolve())])
    return {"statusLine": {"type": "command", "command": command}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Neyvia's state root for last-known limits")
    parser.add_argument("--launch", action="store_true", help="Open official Claude UI; type /usage there")
    args = parser.parse_args()
    if args.launch:
        cli = shutil.which("claude.exe") or shutil.which("claude.cmd") or shutil.which("claude")
        if not cli:
            parser.error("Claude Code is not installed on PATH")
        return subprocess.call([cli, "--settings", json.dumps(launch_settings(args.root))])
    try:
        # Status-line input is tiny; cap it rather than accepting unbounded or malformed data.
        raw = sys.stdin.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("oversized input")
        payload = json.loads(raw)
        rows = record_claude_statusline(payload, args.root)
    except (ValueError, OSError):
        print("Claude usage unavailable")
        return 0  # A collector error must not prevent Claude's interactive UI from running.
    values = [f"{row['label']} {row['usedPercent']}%" for row in rows
              if isinstance(row.get("usedPercent"), (int, float)) and math.isfinite(row["usedPercent"])]
    print(" · ".join(values) if values else "Claude usage not reported yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
