"""Compile a sectioned Markdown plan into dormant, independently routed tasks."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


def compile_plan(text, *, folder, folders=None, builder=None, verifier=None):
    from .neyvia_workspace_tools import WorkspaceTools
    folder = WorkspaceTools.safe_path(folder)
    headings = list(re.finditer(r"^##\s+§(\d+)\s+([^\n]+)", text, re.MULTILINE))
    if not headings:
        raise ValueError("Plan needs ## §1 track: title sections")
    shared = ""
    sections = []
    for index, match in enumerate(headings):
        number, title = match.groups()
        content = text[match.end():headings[index + 1].start() if index + 1 < len(headings) else len(text)].strip()
        if number == "0":
            shared = content
            continue
        track = re.split(r"\s*[:·—]\s*|\s+", title.strip(), 1)[0].lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", track):
            raise ValueError("Section title must start with a track ID")
        sections.append((track, title, content))
    if not sections or len({row[0] for row in sections}) != len(sections):
        raise ValueError("Supply at least one unique track section")
    # Read only the table before the track sections (including shared §0).
    table_text = text[:next(match.start() for match in headings if match.group(1) != "0")]
    table, headers = {}, None
    for line in table_text.splitlines():
        if not line.strip().startswith("|"):
            headers = None
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        lower = [cell.lower() for cell in cells]
        if "track" in lower:
            headers = lower
            continue
        if not headers or len(cells) != len(headers) or all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
            continue
        row = dict(zip(headers, cells))
        track = row["track"].lower()
        if track in table:
            raise ValueError("Duplicate track table row: " + track)
        table[track] = row
    for route in (builder, verifier):
        if route is not None and (not isinstance(route, dict) or set(route) - {"model", "effort", "permissionMode", "transport"}):
            raise ValueError("Template routes select only model, effort, permissionMode and transport; harness and owner are fixed")
    builder = {"owner": "Claude", "harness": "claude-code", "permissionMode": "workspace", **(builder or {})}
    verifier = {"owner": "Codex", "harness": "codex", "permissionMode": "read-only", **(verifier or {})}
    tasks, allocations, paths, assigned_ports, contexts = [], [], set(), set(), []
    for track, title, content in sections:
        row = table.get(track)
        if not row:
            raise ValueError("Missing worktree/ports table row for " + track)
        worktree = (folders or {}).get(track) or row.get("worktree") or row.get("folder")
        if not worktree:
            raise ValueError("Track requires an explicit worktree: " + track)
        path = Path(worktree)
        path = WorkspaceTools.safe_path(Path(folder) / path if not path.is_absolute() else path)
        if not path.is_dir() or not (path / ".git").exists():
            raise ValueError("Track folder must be an existing Git checkout/worktree: " + str(path))
        if str(path).lower() in paths:
            raise ValueError("Tracks must use separate worktrees")
        paths.add(str(path).lower())
        ports = [int(value) for key, value in row.items() if key in {"backend", "vite", "ports"} for value in re.findall(r"\b\d+\b", value)]
        if not ports or any(not 1024 <= port <= 65535 or port in assigned_ports for port in ports) or len(set(ports)) != len(ports):
            raise ValueError("Supply unique valid assigned ports for " + track)
        assigned_ports.update(ports)
        allocation = {"track": track, "folder": str(path), "ports": ports}
        allocations.append(allocation)
        context = f"Plan track {track}. Work only in {path}. Assigned ports: {', '.join(map(str, ports))}.\nShared rules:\n{shared}\nYour section:\n{content}"
        contexts.append(f"Track {track}; worktree {path}; assigned ports {ports}; section:\n{content}")
        tasks.append({**builder, "id": track + "-build", "title": title, "folder": str(path), "needs": [],
                      "prompt": context + "\nImplement your section, run its real acceptance journey and report exact evidence. Preserve others' edits. Never push or merge."})
    tasks.append({**verifier, "id": "verify-all", "title": "Verify every track and their integration", "folder": str(Path(folder).resolve()),
                  "needs": [task["id"] for task in tasks],
                  "prompt": f"Lead verification workspace: {Path(folder).resolve()}.\nShared rules:\n{shared}\n" + "\n\n".join(contexts) +
                  "\nIndependently inspect every builder's actual files and rerun each section's acceptance checks from its assigned worktree, then check their integration. Report PASS or FAIL for each track and overall, exact commands, outputs and limitations honestly; do not modify files, commit, push or merge."})
    return {"tasks": tasks, "allocations": allocations, "planSha256": hashlib.sha256(text.encode()).hexdigest()}


def from_plan(service, args):
    from .neyvia_missions import create
    from .neyvia_workspace_tools import workspace_for
    path = workspace_for(service.root).safe_path(args["planPath"])
    if path.suffix.lower() != ".md":
        raise ValueError("Supply a Markdown plan")
    compiled = compile_plan(path.read_text(encoding="utf-8-sig"), folder=args["folder"], folders=args.get("folders"),
                            builder=args.get("builder"), verifier=args.get("verifier"))
    result = create(service, {**args, "goal": args.get("goal") or path.stem, "tasks": compiled["tasks"],
                              "holdAtPlanPercent": args.get("holdAtPlanPercent", 70),
                              "plan": {"path": str(path), "sha256": compiled["planSha256"], "allocations": compiled["allocations"]}})
    return {**result, "template": "lead-claude-codex", "allocations": compiled["allocations"],
            "note": "Stored dormant; approve exact mission intent and start explicitly. Plan hold applies before every launch."}
