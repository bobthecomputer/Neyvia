"""Import the TASKS markdown dialect used by Paul's shared plan board."""
from __future__ import annotations

import re
from pathlib import Path


ROW = re.compile(r"^- \[([ xX])\]\s*(?:\*\*)?([A-Z]\d+)\s*·\s*([^·\n]+?)\s*·\s*needs:\s*([^*·\n]+)(?:\*\*)?\s*·?\s*(.*)$", re.MULTILINE)


def parse_board(text):
    text = text.split("## TASKS", 1)[-1].split("## HANDOFF", 1)[0]
    matches = list(ROW.finditer(text))
    rows = []
    for index, match in enumerate(matches):
        checked, identity, owner, prerequisites, first = match.groups()
        tail = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        tail = re.split(r"\n\s*(?:#{1,6}\s|---)", tail, 1)[0].strip()
        prompt = (first + ("\n" + tail if tail else "")).strip()
        needs = re.findall(r"[A-Z]\d+", prerequisites)
        title = re.search(r"\*([^*]+)\*", first)
        folder = re.search(r"`([A-Za-z]:\\[^`]+)`", prompt)
        rows.append({"id": identity, "owner": owner, "needs": needs, "prompt": prompt,
                     "title": title.group(1) if title else prompt[:100], "checked": checked.lower() == "x",
                     "folder": folder.group(1) if folder else None})
    return rows


def import_board(service, body):
    text = body.get("text")
    if text is None:
        from .neyvia_workspace_tools import workspace_for
        path = workspace_for(service.root).safe_path(body["path"])
        if path.suffix.lower() != ".md":
            raise ValueError("Import a Markdown task board")
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Task board exceeds 2 MB")
        text = path.read_text(encoding="utf-8-sig")
    if not isinstance(text, str) or len(text.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Supply Markdown text up to 2 MB")
    rows = parse_board(text)
    if not rows:
        raise ValueError("No TASKS rows found")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate task IDs in board")
    imported, existing, prepared = [], [], []
    with service.lock:
        saved = {task["id"]: task for task in service.tasks()}
        for row in rows:
            if row["id"] in saved:
                existing.append(row["id"])
                continue
            row["folder"] = (body.get("folders") or {}).get(row["id"]) or row["folder"] or body.get("folder") or service.root
            prepared.append(service.prepare({**(body.get("defaults") or {}), **row}))
        graph = {**saved, **{task["id"]: task for task in prepared}}
        visited = set()
        def visit(identity, stack):
            if identity not in graph:
                raise ValueError("Missing prerequisite: " + identity)
            if identity in stack:
                raise ValueError("Cyclic prerequisites")
            if identity not in visited:
                for need in graph[identity]["needs"]:
                    visit(need, stack | {identity})
                visited.add(identity)
        for task in prepared:
            visit(task["id"], set())
        import json
        import os
        from .ui_command_bus import now
        with service.connect() as db:
            for task in prepared:
                db.execute("INSERT INTO tasks(id,body,status,folder,updated) VALUES(?,?,?,?,?)",
                           (task["id"], json.dumps(task), "waiting", os.path.normcase(task["folder"]), now()))
                imported.append(task["id"])
        for identity in imported:
            service.emit(identity)
    # A source checkbox alone is not fresh, verified execution evidence.
    return {"imported": imported, "existing": existing, "tasks": service.tasks(),
            "note": "Imported dormant. Tick with typed evidence and explicitly start selected IDs."}
