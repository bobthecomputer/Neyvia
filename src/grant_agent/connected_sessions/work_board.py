"""Turn-scoped work awareness shared by connected harnesses."""
from pathlib import Path

from ..neyvia_awareness import board_list


def turn_note(root, cwd, session_id=None):
    if root is None or not cwd:
        return ""
    rows = board_list(root, {"files": [str(cwd)]})["claims"]
    lines = []
    for row in rows:
        if row["stale"] or (session_id and row.get("chat") == session_id):
            continue
        lines.append(f"{row['agent']} is editing {', '.join(row['files'])} for {row['intent']} "
                     f"since {row['since'][11:16]}; keep edits there small or ask.")
    return ("Current live work board (this snapshot replaces earlier work-board notes; "
            "only the claims below are currently active):\n" +
            ("\n".join(lines) if lines else "No other agents have live claims in this folder."))


def edited_paths(item, cwd):
    """Use the adapters' normalized edit items, never reads or declined edits."""
    data = item.get("data") or {}
    if item.get("kind") != "tool" or data.get("category") != "edit" or data.get("declined"):
        return []
    if data.get("status") in {"failed", "error", "declined"}:
        return []
    paths = []
    for value in data.get("files") or []:
        path = Path(value)
        if not path.is_absolute():
            if not cwd:
                continue
            path = Path(cwd) / path
        paths.append(str(path.resolve()))
    return paths
