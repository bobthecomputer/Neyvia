"""Claude Code hook used by Neyvia's plan-limits (terminal) mode. Standard library only.

Claude Code runs it as ``python claude_hook.py <spool dir> <event>`` for the hooks that
``claude_terminal`` passes with ``--settings`` for one process. Every call is written to
``<spool>/events`` as one JSON file. For a permission request (``permission``) or a question
(``question``) it then waits for Neyvia's reply in ``<spool>/decisions/<request id>.json`` and prints
it, which is how a hook answers Claude Code. When no reply comes (Neyvia closed the run, so
``<spool>/closed`` exists) it prints nothing, and Claude Code falls back to its own prompt.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

WAIT_SECONDS = 24 * 60 * 60
WAITING_EVENTS = ("permission", "question")


def request_id(data: dict) -> str:
    raw = str(data.get("tool_use_id") or "") or uuid.uuid4().hex
    clean = "".join(ch for ch in raw if ch.isalnum() or ch in "_-")[:120]
    return clean or uuid.uuid4().hex


def write_json(folder: Path, name: str, value: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    temp = folder / f".{name}.tmp"
    temp.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temp, folder / name)
    # The hook runs as a standalone stdlib program; its action checks therefore
    # stay here rather than importing the application or the user's config.
    if json.loads((folder / name).read_text(encoding="utf-8")) != value or temp.exists():
        raise RuntimeError("providers.terminal.hook: atomic event receipt differs")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        return 0
    spool, event = Path(argv[1]), argv[2]
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    rid = request_id(data)
    write_json(spool / "events", f"{time.time_ns()}-{event}-{uuid.uuid4().hex[:6]}.json",
               {"event": event, "requestId": rid, "data": data})
    if event not in WAITING_EVENTS:
        return 0
    reply = spool / "decisions" / f"{rid}.json"
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if reply.exists():
            try:
                output = json.loads(reply.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                time.sleep(0.1)
                continue
            sys.stdout.write(json.dumps(output))
            sys.stdout.flush()
            return 0
        if (spool / "closed").exists():
            return 0
        time.sleep(0.2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
