"""Local title/project clustering with reviewable, reversible moves and no model calls."""
from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from pathlib import Path

DEFINITIONS = [("session.cluster", "Preview subject/project groups locally. apply moves only confident matches; confirmIds explicitly accepts uncertain suggestions. Undo with undoId.",
                {"apply": {"type": "boolean"}, "minConfidence": {"type": "number", "minimum": 0.8, "maximum": 1},
                 "ids": {"type": "array", "items": {"type": "string"}}, "confirmIds": {"type": "array", "items": {"type": "string"}},
                 "undoId": {"type": "string"}}, [])]
_STOP = {"the", "and", "for", "with", "chat", "new", "fix", "update", "project", "code", "session", "this", "that", "from", "test", "tests", "codex", "claude", "opencode", "help", "please", "create"}


def words(text):
    return {word for word in re.findall(r"[\w]+", str(text).casefold()) if len(word) > 2 and word not in _STOP and not word.isdigit()}


def match(row, projects):
    title = words(row.get("title", ""))
    cwd = Path(row["cwd"]).resolve() if row.get("cwd") else None
    scored = []
    for path, project in projects.items():
        target = Path(path).resolve()
        direct = cwd is not None and (cwd == target or target in cwd.parents)
        tokens = words(project.get("name") or target.name)
        overlap = title & tokens
        score = 1.0 if direct else (.95 if overlap == tokens else .7) if overlap and tokens else 0
        if score:
            scored.append((score, path, "workspace ancestry" if direct else "project name in title"))
    scored.sort(reverse=True)
    if not scored:
        return None
    confidence, project, reason = scored[0]
    if len(scored) > 1 and scored[1][0] == confidence:
        confidence, reason = .5, "ambiguous project names; confirm explicitly"
    return {"project": project, "confidence": confidence, "reason": reason}


def cluster(service, args):
    bus = service.bus
    if not isinstance(args.get("apply", False), bool):
        raise ValueError("apply must be a boolean")
    for key in ("ids", "confirmIds"):
        if key in args and (not isinstance(args[key], list) or not all(isinstance(item, str) for item in args[key])):
            raise ValueError(key + " must be a list of session IDs")
    if args.get("undoId"):
        record = bus.get("cluster:" + args["undoId"])
        if not record:
            raise ValueError("Unknown clustering receipt")
        restored, changed = [], []
        for identity, patch in record["moves"].items():
            current = bus.get("sessions", {}).get(identity, {})
            if current.get("project") != patch["after"]:
                changed.append(identity)
                continue
            service.call("session.move", {"id": identity, "project": patch["before"]})
            restored.append(identity)
        return {"ok": True, "restored": restored, "skippedChanged": changed}
    threshold = args.get("minConfidence", .8)
    if isinstance(threshold, bool) or not isinstance(threshold, (float, int)) or not .8 <= threshold <= 1:
        raise ValueError("minConfidence must be between .8 and 1")
    projects = bus.get("projects", {})
    rows, offset = [], 0
    for _ in range(4):
        page = service.broker().list_sessions(limit=500, offset=offset, include_archived=False, include_harness=False)
        rows.extend(page.get("sessions", []))
        offset = page.get("nextOffset")
        if offset is None:
            break
    selected, confirmed = set(args.get("ids") or []), set(args.get("confirmIds") or [])
    suggestions, topics, skipped, subjects = [], {}, [], []
    overlay = bus.get("sessions", {})
    for row in rows:
        identity = row["id"]
        if selected and identity not in selected:
            continue
        saved = overlay.get(identity, {})
        if saved.get("archived") or row.get("archived") or row.get("status") in {"working", "waiting_approval", "waiting_input"}:
            skipped.append(identity)
            continue
        guess = match({**row, **saved}, projects)
        if guess:
            before = saved.get("project")
            if before == guess["project"]:
                continue
            suggestions.append({"id": identity, "title": saved.get("title") or row.get("title"), "before": before,
                                **guess, "needsConfirmation": before is not None or guess["confidence"] < threshold})
        else:
            subjects.append((identity, words(saved.get("title") or row.get("title"))))
    frequency = Counter(token for _, tokens in subjects for token in tokens)
    for identity, tokens in subjects:
        repeated = sorted((token for token in tokens if frequency[token] > 1), key=lambda token: (-frequency[token], token))
        topic = repeated[0] if repeated else "Other"
        topics.setdefault(topic, []).append(identity)
    moves = {}
    if args.get("apply"):
        for proposal in suggestions:
            if proposal["needsConfirmation"] and proposal["id"] not in confirmed:
                continue
            service.call("session.move", {"id": proposal["id"], "project": proposal["project"]})
            moves[proposal["id"]] = {"before": proposal["before"], "after": proposal["project"]}
    receipt = hashlib.sha256(os.urandom(32)).hexdigest()[:20] if moves else None
    if receipt:
        bus.put("cluster:" + receipt, {"moves": moves})
    result = {"ok": True, "suggestions": suggestions, "subjectGroups": [{"subject": topic, "ids": ids} for topic, ids in topics.items()],
              "moved": list(moves), "undoId": receipt, "skippedActiveOrArchived": skipped,
              "nextOffset": page.get("nextOffset"), "providerCalls": 0, "confidenceKind": "deterministic matching score, not a calibrated probability"}
    bus.emit("notify", {"message": f"Grouped {len(rows)} chats; moved {len(moves)}", "level": "info"})
    return result
