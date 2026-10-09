"""Mission metadata and branch supervision over the existing Night Shift engine."""
from __future__ import annotations

import hashlib
import json
import uuid

from .ui_command_bus import now

DEFINITIONS = [
    ("mission.from_plan", "Compile a Markdown plan with ## §0 shared rules, ## §1 track: title sections and a Track/Worktree/Backend/Vite table into Claude builds and one Codex integration verification requiring every build. Existing separate worktrees required; stored dormant.",
     {"planPath": {"type": "string"}, "folder": {"type": "string"}, "id": {"type": "string"}, "goal": {"type": "string"},
      "folders": {"type": "object", "additionalProperties": {"type": "string"}}, "builder": {"type": "object"}, "verifier": {"type": "object"},
      "holdAtPlanPercent": {"type": ["integer", "null"], "minimum": 1, "maximum": 100}, "budget": {"type": "object"},
      "acceptanceChecks": {"type": "array", "items": {"type": "string"}}}, ["planPath", "folder", "acceptanceChecks"]),
    ("mission.create", "Store a dormant mission. Tasks select routingProfile (planner/executor/verifier/classifier), or an explicit route; configured executor is the default. Routes freeze before approval.",
     {"id": {"type": "string"}, "goal": {"type": "string"}, "folder": {"type": "string"}, "tasks": {"type": "array", "items": {"type": "object", "properties": {
         **{key: {"type": "string"} for key in ("id", "prompt", "title", "folder", "harness", "owner", "model", "effort", "permissionMode", "transport")},
         "routingProfile": {"type": "string", "enum": ["planner", "executor", "verifier", "classifier"]},
         "needs": {"type": "array", "items": {"type": "string"}}, "requiresGpu": {"type": "boolean"}, "completionEvidence": {"type": "object"}}, "required": ["id", "prompt"]}},
      "budget": {"type": "object"}, "acceptanceChecks": {"type": "array", "items": {"type": "string"}}}, ["goal", "folder", "tasks", "acceptanceChecks"]),
    ("mission.list", "Read missions, their task trees, evidence and usage coverage.", {}, []),
    ("mission.control", "Supervise a mission branch: start requires owner approval; pause prevents new launches; stop cancels owned runs; redirect changes a dormant prompt/route.",
     {"id": {"type": "string"}, "action": {"type": "string", "enum": ["start", "pause", "stop", "redirect"]},
      "taskId": {"type": "string"}, "prompt": {"type": "string"}, "model": {"type": "string"}, "effort": {"type": "string"},
      "permissionMode": {"type": "string"}}, ["id", "action"]),
]


def initialize(service):
    with service.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS missions(id TEXT PRIMARY KEY, body TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, updated TEXT NOT NULL)")


def records(service):
    initialize(service)
    with service.connect() as db:
        return [{**json.loads(row["body"]), "status": row["status"], "updatedAt": row["updated"]}
                for row in db.execute("SELECT * FROM missions ORDER BY rowid")]


def usage(service, tasks):
    total, known, unknown = 0, [], []
    identities = {task["id"] for task in tasks}
    with service.connect() as db:
        attempts = []
        names = list(identities)
        for start in range(0, len(names), 500):
            subset = names[start:start + 500]
            attempts.extend(dict(row) for row in db.execute("SELECT * FROM attempts WHERE task IN (" + ",".join("?" for _ in subset) + ")", subset))
    captured = {row["run_id"] for row in attempts}
    attempts += [{"run_id": task["runId"], "task": task["id"], "usage": None} for task in tasks if task.get("runId") and task["runId"] not in captured]
    for attempt in attempts:
        reported = json.loads(attempt["usage"]) if attempt.get("usage") else {}
        if not reported:
            try:
                reported = service.broker.get_run(attempt["run_id"]).get("usage") or {}
            except Exception as exc:
                if getattr(exc, "code", None) != "run_not_found":
                    raise
        value = reported.get("totalTokens")
        if isinstance(value, int) and not isinstance(value, bool) and reported.get("reportedByTransport"):
            total += value
            known.append(attempt["run_id"])
        else:
            unknown.append(attempt["run_id"])
    return {"reportedTokens": total, "knownTasks": known, "unknownTasks": unknown, "complete": not unknown, "cashCost": None}


def admission(service, identity):
    mission = next((row for row in records(service) if row["id"] == identity), None)
    if not mission or mission["status"] != "running":
        return "Mission is dormant, paused or stopped"
    tasks = [row for row in service.tasks() if row.get("missionId") == identity]
    budget = mission["budget"]
    if budget.get("maxTokens"):
        consumed = usage(service, tasks)
        if consumed["unknownTasks"]:
            return "Mission token budget waits for reported execution usage"
        if consumed["reportedTokens"] >= budget["maxTokens"]:
            return "Mission reported token budget reached"
        # Serialize a token-budgeted mission so concurrent branches cannot each spend its full remainder.
        if any(row["status"] == "running" for row in tasks):
            return "Mission token budget serializes its branches"
    return None


def remaining_limits(service, task):
    mission = next(row for row in records(service) if row["id"] == task["missionId"])
    budget = mission["budget"].get("maxTokens")
    limits = dict(task.get("limits", {}))
    if budget:
        consumed = usage(service, [row for row in service.tasks() if row.get("missionId") == mission["id"]])
        limits["maxTaskTokens"] = min(limits.get("maxTaskTokens") or budget, max(1, budget - consumed["reportedTokens"]))
    return limits


def create(service, args):
    from .nightshift_resources import positive
    initialize(service)
    identity = str(args.get("id") or uuid.uuid4().hex)
    goal, checks, rows = args.get("goal"), args.get("acceptanceChecks"), args.get("tasks")
    if not isinstance(goal, str) or not goal.strip() or not isinstance(checks, list) or not checks or not all(isinstance(item, str) and item.strip() for item in checks):
        raise ValueError("A goal and explicit acceptance checks are required")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("Supply 1–100 explicit tasks")
    budget = args.get("budget") or {}
    if not isinstance(budget, dict) or set(budget) - {"maxTokens", "maxTaskSeconds", "maxTaskTokens"}:
        raise ValueError("Use token and/or per-task time limits; cash budgets need actual billing data")
    budget = {key: positive(value, key) for key, value in budget.items()}
    from .neyvia_workspace_tools import workspace_for
    folder = str(workspace_for(service.root).safe_path(args["folder"]))
    names = [row.get("id") for row in rows if isinstance(row, dict)]
    if len(names) != len(rows) or any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        raise ValueError("Each task needs a unique local ID")
    mapping = {name: identity + ":" + name for name in names}
    prepared = []
    for row in rows:
        if any(need not in mapping for need in row.get("needs", [])):
            raise ValueError("Mission prerequisites must reference tasks in this mission")
        limits = {key: value for key, value in budget.items() if key != "maxTokens"}
        if budget.get("maxTokens"):
            limits["maxTaskTokens"] = min(limits.get("maxTaskTokens") or budget["maxTokens"], budget["maxTokens"])
        from .neyvia_runtime import mission_route
        routed = mission_route(service.root, row)
        prepared.append(service.prepare({**routed, "id": mapping[row["id"]], "folder": row.get("folder") or folder,
                                         "missionId": identity, "needs": [mapping[need] for need in row.get("needs", [])], "limits": limits}))
    tree = {row["id"]: row["needs"] for row in prepared}
    visited = set()
    def visit(node, stack):
        if node in stack:
            raise ValueError("Cyclic mission prerequisites")
        if node in visited:
            return
        for need in tree[node]:
            visit(need, stack | {node})
        visited.add(node)
    for node in tree:
        visit(node, set())
    body = {"id": identity, "goal": goal, "folder": folder, "budget": budget, "acceptanceChecks": checks, "taskIds": list(tree)}
    if "holdAtPlanPercent" in args:
        hold = args["holdAtPlanPercent"]
        if hold is not None and (not isinstance(hold, int) or isinstance(hold, bool) or not 1 <= hold <= 100):
            raise ValueError("holdAtPlanPercent must be 1-100 or null")
        body["holdAtPlanPercent"] = hold
    if args.get("plan"):
        body["plan"] = args["plan"]
    fingerprint = hashlib.sha256(json.dumps({"mission": body, "tasks": prepared}, sort_keys=True).encode()).hexdigest()
    with service.lock, service.connect() as db:
        old = db.execute("SELECT fingerprint FROM missions WHERE id=?", (identity,)).fetchone()
        if old:
            if old[0] != fingerprint:
                raise ValueError("Mission ID already represents different intent")
            return {"ok": True, "mission": next(row for row in records(service) if row["id"] == identity), "replayed": True}
        db.execute("INSERT INTO missions VALUES(?,?,?,?,?)", (identity, json.dumps(body), fingerprint, "draft", now()))
        for task in prepared:
            db.execute("INSERT INTO tasks(id,body,status,folder,updated) VALUES(?,?,?,?,?)", (task["id"], json.dumps(task), "waiting", task["folder"], now()))
    service.bus.emit("notify", {"message": "Mission stored: " + goal, "level": "info"})
    return {"ok": True, "mission": body, "status": "draft"}


def control(service, args):
    identity, action = args["id"], args["action"]
    with service.lock:
        mission = next((row for row in records(service) if row["id"] == identity), None)
        if not mission:
            raise ValueError("Unknown mission")
        tasks = {task["id"]: task for task in service.tasks() if task.get("missionId") == identity}
        selected = set(tasks)
        if args.get("taskId"):
            task_id = args["taskId"]
            if task_id not in tasks:
                raise ValueError("Unknown mission task")
            selected = {task_id}
            while True:
                expanded = selected | {key for key, row in tasks.items() if set(row["needs"]) & selected}
                if expanded == selected:
                    break
                selected = expanded
        if action == "redirect":
            task_id = args.get("taskId")
            if not task_id or tasks[task_id]["status"] in {"running", "done"}:
                raise ValueError("Redirect one dormant/blocked task; completed evidence is immutable")
            patch = {key: args[key] for key in ("prompt", "model", "effort", "permissionMode") if key in args}
            if not patch:
                raise ValueError("Supply a prompt or explicit route change")
            redirected = {**tasks[task_id], **patch}
            if any(key in patch for key in ("model", "effort", "permissionMode")):
                redirected.pop("routingProfile", None)
            task = service.prepare(redirected)
            with service.connect() as db:
                db.execute("UPDATE tasks SET body=?,armed=0,status='waiting',run_id=NULL,evidence=NULL,reason=NULL,updated=? WHERE id=?", (json.dumps(task), now(), task_id))
            service.emit(task_id)
        elif action == "start":
            from .neyvia_workspace_tools import workspace_for
            key = hashlib.sha256(json.dumps([mission, [tasks[key] for key in sorted(selected)]], sort_keys=True).encode()).hexdigest()
            refusal = workspace_for(service.root).require_approval("mission:" + key, "Approve mission prompts, routes, permissions and budget: " + mission["goal"],
                                                                  {"mission": mission, "tasks": [tasks[key] for key in sorted(selected)], "intentSha256": key})
            if refusal:
                return refusal
            service.start(sorted(selected), validate_only=True)
            with service.connect() as db:
                db.execute("UPDATE missions SET status='running',updated=? WHERE id=?", (now(), identity))
            service.start(sorted(selected))
        elif action in {"pause", "stop"}:
            with service.connect() as db:
                for task_id in selected:
                    if action == "stop" or tasks[task_id]["status"] != "running":
                        db.execute("UPDATE tasks SET armed=0,updated=? WHERE id=?", (now(), task_id))
                if not args.get("taskId"):
                    db.execute("UPDATE missions SET status=?,updated=? WHERE id=?", ("paused" if action == "pause" else "stopped", now(), identity))
            if action == "stop":
                for task_id in selected:
                    service.stop(task_id)
        else:
            raise ValueError("Unknown mission action")
        service.bus.emit("notify", {"message": "Mission " + action + ": " + identity, "level": "info"})
        return {"ok": True, "id": identity, "action": action, "tasks": list(selected)}


def summary(service):
    tasks = service.tasks()
    return {"tasks": [{key: task.get(key) for key in ("id", "title", "status", "reason", "evidence", "runId", "updatedAt", "missionId")} for task in tasks],
            "counts": {state: sum(task["status"] == state for task in tasks) for state in ("waiting", "running", "done", "blocked")},
            "usage": usage(service, tasks), "scope": "Saved task evidence and reported execution usage; no model-generated quality verdict"}


def call(service, name, args):
    if name == "mission.from_plan":
        from .neyvia_mission_plan import from_plan
        return from_plan(service, args)
    if name == "mission.create":
        return create(service, args)
    if name == "mission.control":
        return control(service, args)
    tasks = service.tasks()
    return {"ok": True, "missions": [{**row, "tasks": [task for task in tasks if task.get("missionId") == row["id"]],
            "executionStatus": "running" if any(task["status"] == "running" for task in tasks if task.get("missionId") == row["id"]) else
                               "finished" if all(task["status"] == "done" for task in tasks if task.get("missionId") == row["id"]) else
                               "blocked" if any(task["status"] == "blocked" for task in tasks if task.get("missionId") == row["id"]) else "waiting",
            "usage": usage(service, [task for task in tasks if task.get("missionId") == row["id"]]),
            "acceptance": "evidence_ready_for_review" if all(task["status"] == "done" for task in tasks if task.get("missionId") == row["id"]) else "pending"} for row in records(service)]}
