"""User, bot and desktop access to the existing durable Night Shift engine."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ACTIONS = ("tasks", "task", "create", "edit", "reparent", "import", "tick", "start", "stop", "block", "resources", "summary", "begin")
COMMANDS = frozenset("nightshift_" + action + "_command" for action in ACTIONS)
TEXT = {"type": "string"}
TASK = {**{key: TEXT for key in ("id", "title", "prompt", "owner", "folder", "harness", "model", "effort", "permissionMode", "transport")},
        "needs": {"type": "array", "items": TEXT}, "requiresGpu": {"type": "boolean"},
        "limits": {"type": "object"}, "completionEvidence": {"type": "object"}}
DEFINITIONS = [
    ("nightshift.tasks", "Read the saved task graph, evidence and launch reasons.", {}, []),
    ("nightshift.task", "Observe one saved task before editing or checking its result.", {"id": TEXT}, ["id"]),
    ("nightshift.create", "Store a dormant task; needs are task IDs. Nothing runs until explicitly started.", TASK, ["prompt"]),
    ("nightshift.edit", "Edit a dormant unattempted task with its observed updatedAt; disarms it until explicitly started again.",
     {"id": TEXT, "patch": {"type": "object", "properties": {key: value for key, value in TASK.items() if key != "id"},
                             "additionalProperties": False}, "expectedUpdatedAt": TEXT}, ["id", "patch", "expectedUpdatedAt"]),
    ("nightshift.reparent", "Replace dormant task prerequisites; missing tasks and dependency cycles are refused; disarms the task.",
     {"id": TEXT, "needs": {"type": "array", "items": TEXT}, "expectedUpdatedAt": TEXT}, ["id", "needs", "expectedUpdatedAt"]),
    ("nightshift.import", "Import TASKS.md dormant; source checkboxes do not count as execution evidence.",
     {"text": TEXT, "path": TEXT, "folder": TEXT, "folders": {"type": "object"}, "defaults": {"type": "object"}}, []),
    ("nightshift.tick", "Complete a task with task-matching file change, commit, tool receipt or verifier-accepted result; transport completion alone needs review.",
     {"id": TEXT, "evidence": {"type": "object"}}, ["id", "evidence"]),
    ("nightshift.start", "Arm explicit task IDs under approved prompts/routes, prerequisites and saved resource policy.",
     {"ids": {"type": "array", "items": TEXT}}, ["ids"]),
    ("nightshift.stop", "Stop an owned task; active repository lock stays until terminal harness state.", {"id": TEXT}, ["id"]),
    ("nightshift.block", "Block a non-active task with a reason; completed evidence is immutable.", {"id": TEXT, "reason": TEXT}, ["id", "reason"]),
    ("nightshift.resources", "Read resource policy or request an owner-approved patch. Token limits use reported transport usage.",
     {**{key: {"type": ["integer", "null"]} for key in ("maxConcurrent", "maxTaskSeconds", "maxTaskTokens", "maxNightSeconds", "holdAtPlanPercent")},
      "paused": {"type": "boolean"}, "perHarness": {"type": "object"}, "perHarnessBudgets": {"type": "object"},
      "gpuReservedFor": {"type": ["string", "null"]}, "quietGpuHours": {"type": ["object", "null"]}}, []),
    ("nightshift.summary", "Read morning evidence, blockers, waiting on Paul, measured time and token coverage.", {}, []),
    ("nightshift.begin", "Begin a fresh explicit night budget period only with no running tasks; preserves history.", {}, []),
]


def request(service, action, args):
    return service.request(action, args, "GET" if action in {"tasks", "task", "summary"} or (action == "resources" and not args) else "POST")


def call(workspace, name, args):
    from .nightshift import nightshift_for
    action = name.removeprefix("nightshift.")
    if action not in ACTIONS:
        raise ValueError("Unknown Night Shift tool")
    service = nightshift_for(workspace.bus.root, workspace.backend)
    if action == "tick" and (args.get("evidence") or {}).get("type") == "command":
        raise ValueError("Command evidence is an owner submission; use verified file, commit or run evidence from a bot")
    if action in {"start", "begin"} or (action == "resources" and args):
        intent = {"action": action, "args": args, "tasks": [service.get(identity) for identity in args.get("ids", [])]}
        fingerprint = hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
        refusal = workspace.require_approval("nightshift:" + fingerprint, "Approve Night Shift " + action, intent)
        if refusal:
            return refusal
    result = request(service, action, args)
    # The task's lifecycle is data. A successful request to stop or block a
    # task must not be classified as a failed operation by the native registry.
    return {"ok": True, "task": result} if action in {"stop", "block"} else result


def handle_command(backend, name, args):
    from .nightshift import nightshift_for
    if name not in COMMANDS:
        raise ValueError("Unknown Night Shift command")
    expected = args.get("_expectedStateRoot")
    if expected and Path(expected).resolve() != Path(backend.root).resolve():
        raise ValueError("Night Shift service state root does not match the desktop request")
    action = name[len("nightshift_"):-len("_command")]
    return request(nightshift_for(backend.root, backend), action, {key: value for key, value in args.items() if key != "_expectedStateRoot"})


def respond(handler, backend, name, args):
    from .web_backend import _json_response
    session = backend.authenticated_session(handler)
    if not session or str(session.get("username") or "").casefold() != backend.username.casefold():
        _json_response(handler, 403, {"ok": False, "error": "The PC owner's account is required for Night Shift commands"})
        return
    try:
        _json_response(handler, 200, {"ok": True, "data": handle_command(backend, name, args or {})})
    except (ValueError, KeyError, TypeError) as exc:
        _json_response(handler, 400, {"ok": False, "error": str(exc)})
