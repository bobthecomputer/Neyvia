"""Goal planning and frozen routed DAGs on the existing detached Harness workers.

The web process only admits/reads/controls jobs. The leased worker owns each
connected turn, so restarting the web process cannot resend its side effects.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from .harness_jobs import HarnessJobStore, _atomic_write_json, _exclusive_job_lock, _read_job_payload
from .ui_command_bus import bus_for

COMMANDS = frozenset("conductor_" + op + "_command" for op in ("plan", "get", "list", "control"))
MUTATIONS = COMMANDS - {"conductor_get_command", "conductor_list_command"}
TEXT = {"type": "string", "minLength": 1}
DEFINITIONS = [
    ("conductor.plan", "Plan a goal into a frozen routed task tree in a detached job; execution waits for Start.",
     {"requestId": TEXT, "goal": TEXT, "folder": TEXT, "acceptanceChecks": {"type": "array", "minItems": 1, "items": TEXT},
      "maxRuntimeSeconds": {"type": "integer", "minimum": 30, "maximum": 86400}}, ["requestId", "goal", "folder", "acceptanceChecks"]),
    ("conductor.get", "Read the saved task tree, active run IDs and verification receipts, including after app restart.", {"id": TEXT}, ["id"]),
    ("conductor.list", "Page durable conductor jobs, including interrupted jobs with saved evidence.",
     {"limit": {"type": "integer", "minimum": 1, "maximum": 100}, "offset": {"type": "integer", "minimum": 0}}, []),
    ("conductor.control", "Start the reviewed plan, pause after the current turn, resume pending work, or stop the owned worker tree.",
     {"id": TEXT, "action": {"type": "string", "enum": ["start", "pause", "resume", "stop"]}}, ["id", "action"]),
]


def _conductor_job(store, identity):
    from .connected_sessions.registry import ConnectedError
    try:
        job = store.load(identity)
    except KeyError as exc:
        raise ConnectedError("job_not_found", "That conductor job was not found", 404) from exc
    if not job.get("request", {}).get("conductor"):
        raise ValueError("That job is not a conductor job")
    return job


def call(service, name, args):
    return request(service.bus.root, name.removeprefix("conductor."), args)


def handle_command(backend, command, body):
    from .connected_sessions.registry import ConnectedError
    try:
        return request(backend.root, command.removeprefix("conductor_").removesuffix("_command"), body)
    except ValueError as exc:
        raise ConnectedError("invalid_request", str(exc), 400) from exc
    except FileNotFoundError as exc:
        raise ConnectedError("job_not_found", "That conductor job was not found", 404) from exc


def control_turn(root, command, body):
    """Deliver standard connected controls to the worker that owns this turn.

    Returns None for ordinary chat runs; those retain their existing broker path.
    """
    run_id = str(body.get("runId") or "")
    match = re.match(r"^(harness-job-conductor-[a-f0-9]{32})-", run_id)
    if not match or command not in {"connected_session_answer_command", "connected_session_stop_command"}:
        return None
    store = HarnessJobStore(root)
    identity = match[1]
    _conductor_job(store, identity)
    path = store.job_path(identity)
    with _exclusive_job_lock(path):
        job = _read_job_payload(path, identity)
        active = job.get("conductor", {}).get("activeRun") or {}
        if job["status"] != "running" or active.get("runId") != run_id or active.get("state") not in {"queued", "running", "waiting_approval", "waiting_input"}:
            raise ValueError("This conductor turn is no longer active")
        key = str(body.get("requestId") or "stop")
        messages = job.setdefault("conductorMessages", {})
        message_key = hashlib.sha256((run_id + ":" + key).encode()).hexdigest()
        message = {"command": command, "runId": run_id, "requestId": key, "response": body.get("response")}
        if message_key in messages:
            if messages[message_key]["message"] != message:
                raise ValueError("This turn control ID already represents another response")
        else:
            if command == "connected_session_answer_command" and (active.get("pendingRequest") or {}).get("requestId") != key:
                raise ValueError("This approval is no longer pending")
            messages[message_key] = {"message": message, "status": "queued"}
            _atomic_write_json(path, job)
    return {**active, "queued": True}


def request(root, operation, args):
    from .connected_sessions.registry import ConnectedError
    store = HarnessJobStore(root)
    if operation == "get":
        return {"ok": True, "job": _conductor_job(store, args.get("id"))}
    if operation == "list":
        limit, offset = args.get("limit", 25), args.get("offset", 0)
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ValueError("Use limit 1–100 and offset >= 0")
        rows = [row for row in store.list(limit=100) if row.get("request", {}).get("conductor")]
        next_offset = offset + limit if offset + limit < len(rows) else None
        return {"ok": True, "jobs": rows[offset:offset + limit], "total": len(rows), "offset": offset,
                "limit": limit, "nextOffset": next_offset}
    if operation == "plan":
        from .neyvia_workspace_tools import WorkspaceTools
        goal, checks, identity = args.get("goal"), args.get("acceptanceChecks"), args.get("requestId")
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 50000:
            raise ValueError("Supply a goal of 1–50000 characters")
        if not isinstance(identity, str) or not 1 <= len(identity) <= 200:
            raise ValueError("Supply a stable requestId")
        if not isinstance(checks, list) or not 1 <= len(checks) <= 30 or not all(isinstance(c, str) and c.strip() for c in checks):
            raise ValueError("Supply explicit acceptanceChecks")
        if not isinstance(args.get("folder"), str) or not args["folder"]:
            raise ValueError("Choose an existing working folder")
        folder = WorkspaceTools.safe_path(args["folder"])
        if not folder.is_dir():
            raise ValueError("Choose an existing working folder")
        budget = args.get("maxRuntimeSeconds", 1800)
        if type(budget) is not int or not 30 <= budget <= 86400:
            raise ValueError("maxRuntimeSeconds must be 30–86400")
        job_id = "harness-job-conductor-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
        intent = {"goal": goal.strip(), "folder": str(folder), "acceptanceChecks": checks, "maxRuntimeSeconds": budget}
        # A replay uses the saved routes, even when settings have changed since admission.
        if store.job_path(job_id).is_file():
            old = _conductor_job(store, job_id)
            if old["request"]["intent"] != intent:
                raise ConnectedError("request_id_conflict", "requestId already represents different intent", 409)
            return {"ok": True, "job": old, "replayed": True}
        profiles = bus_for(root).get("runtime.profiles", {})
        if any(not profiles.get(key) for key in ("planner", "executor", "verifier")):
            raise ValueError("Configure planner, executor and verifier routing profiles first")
        from .neyvia_runtime import enforce
        from .connected_sessions.broker import ConnectedBroker
        routes = {key: dict(value) for key, value in profiles.items() if key in {"planner", "executor", "verifier", "classifier"}}
        for route in routes.values():
            enforce(root, route["app"], ConnectedBroker._turn_options(route))
        saved = {"conductor": True, "intent": intent, "routes": routes, "message": goal.strip(),
                 "workspacePath": str(folder), "harnessId": routes["planner"]["app"], "maxRuntimeSeconds": budget}
        store.create(saved, job_id=job_id)
        # Serialize the queued -> running transition so simultaneous identical requests attach.
        try:
            store.start(job_id)
        except RuntimeError:
            if store.load(job_id)["status"] == "queued":
                raise
        return {"ok": True, "job": store.load(job_id)}
    if operation == "control":
        identity, action = args.get("id"), args.get("action")
        job = _conductor_job(store, identity)
        if action not in {"start", "pause", "resume", "stop"}:
            raise ValueError("Use start, pause, resume or stop")
        if action == "stop":
            return {"ok": True, "job": store.cancel(identity)}
        path = store.job_path(identity)
        with _exclusive_job_lock(path):
            job = _read_job_payload(path, identity)
            phase = job.get("conductor", {}).get("phase")
            if job["status"] != "running":
                raise ConnectedError("run_not_active", "This worker is not running; inspect saved receipts before any new attempt", 409)
            if action in {"start", "resume"} and phase not in {"ready", "paused", "running"}:
                raise ValueError("Wait for the saved plan before starting")
            job["conductorControl"] = {"approved": action in {"start", "resume"} or job.get("conductorControl", {}).get("approved", False),
                                       "paused": action == "pause"}
            _atomic_write_json(path, job)
        return {"ok": True, "job": store.load(identity)}
    raise ValueError("Unknown conductor operation")


def _json_reply(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Model must return a JSON object")
    return value


def _task_tree(value, routes, checks):
    rows = value.get("tasks")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 30:
        raise ValueError("Planner must return 1–30 tasks")
    tasks, names = [], set()
    for row in rows:
        if not isinstance(row, dict) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", str(row.get("id", ""))) or row["id"] in names:
            raise ValueError("Planner task IDs must be unique identifiers")
        names.add(row["id"])
        profile = row.get("routingProfile", "executor")
        if profile not in {"executor", "verifier", "classifier"} or profile not in routes:
            raise ValueError("Planner selected an unconfigured task profile")
        if not isinstance(row.get("prompt"), str) or not row["prompt"].strip() or len(row["prompt"]) > 20000:
            raise ValueError("Every planned task needs a bounded actionable prompt")
        needs = row.get("needs", [])
        if not isinstance(needs, list) or not all(isinstance(n, str) for n in needs) or len(set(needs)) != len(needs):
            raise ValueError("Task needs must be unique task IDs")
        tasks.append({"id": row["id"], "parentId": row.get("parentId"), "title": str(row.get("title") or row["id"])[:200],
                      "prompt": row["prompt"], "routingProfile": profile, "route": dict(routes[profile]), "needs": needs, "status": "waiting"})
    for task in tasks:
        if any(n not in names or n == task["id"] for n in task["needs"]) or task["parentId"] is not None and task["parentId"] not in names:
            raise ValueError("Unknown/self task dependency or parent")
    tree = {t["id"]: t["needs"] for t in tasks}
    visited = set()
    def visit(node, path):
        if node in path:
            raise ValueError("Cyclic task prerequisites")
        if node in visited:
            return
        for need in tree[node]:
            visit(need, path | {node})
        visited.add(node)
    for name in names:
        visit(name, set())
    for task in tasks:
        parents = set()
        current = task
        while current.get("parentId") is not None:
            if current["id"] in parents:
                raise ValueError("Cyclic task parents")
            parents.add(current["id"])
            current = next(t for t in tasks if t["id"] == current["parentId"])
    # A final verifier depends on *all* planned leaves, independent of model optimism.
    final_id = "acceptance-verifier"
    while final_id in names:
        final_id += "-final"
    tasks.append({"id": final_id, "parentId": None, "title": "Verify the whole goal", "routingProfile": "verifier",
                  "route": dict(routes["verifier"]), "needs": sorted(names), "status": "waiting",
                  "prompt": "Independently inspect the actual workspace and run the necessary checks. Acceptance checks: " + json.dumps(checks) +
                            '. Return only JSON {"passed":true|false,"checks":[{"check":"exact acceptance check text","passed":true|false,"evidence":"actual observation"}]}. Include each supplied acceptance check exactly once. Never infer success from another agent saying done.'})
    return tasks


def execute(backend, store, job_id):
    from .connected_sessions.broker import broker_for
    broker = broker_for(backend.root, backend)
    job = store.load(job_id, reconcile=False)
    request_data = job["request"]
    intent, routes = request_data["intent"], request_data["routes"]
    state = {"phase": "planning", **intent, "routes": routes, "tasks": [], "receipts": [],
             "classification": {"status": "not_configured"}}

    def save():
        store.update(job_id, conductor=state)

    def turn(identity, prompt, route, task=None):
        run_id = job_id + "-" + identity
        state["activeRun"] = {"runId": run_id, "state": "queued", "sessionId": None, "pendingRequest": None}
        if task is not None:
            task.update(status="running", runId=run_id)
        save()  # record intent before contacting the harness
        started = time.monotonic()
        message = ("Stay within this working folder and the supplied task. Do not download, install, publish, contact other local services, "
                   "or touch unrelated repositories. No delegation.\n" + prompt)
        run = broker.new(route["app"], intent["folder"], message, run_id, route)
        handled = set()
        while run["state"] in {"queued", "running", "waiting_approval", "waiting_input"}:
            state["activeRun"] = run
            if task is not None:
                task["sessionId"] = run.get("sessionId")
                task["pendingRequest"] = run.get("pendingRequest")
            save()
            messages = store.load(job_id, reconcile=False).get("conductorMessages", {})
            for key, entry in messages.items():
                message = entry["message"]
                if key in handled or entry["status"] != "queued" or message["runId"] != run_id:
                    continue
                try:
                    if message["command"] == "connected_session_stop_command":
                        broker.stop(run_id)
                    else:
                        broker.answer(run_id, message["requestId"], message["response"])
                    acknowledgement = {"status": "applied"}
                except Exception as exc:
                    acknowledgement = {"status": "refused", "error": str(exc)}
                handled.add(key)
                path = store.job_path(job_id)
                with _exclusive_job_lock(path):
                    current = _read_job_payload(path, job_id)
                    current["conductorMessages"][key].update(acknowledgement)
                    _atomic_write_json(path, current)
            # Approval policy stays the selected runtime's; we never auto-answer model requests.
            time.sleep(0.3)
            run = broker.get_run(run_id)
        receipt = {"runId": run_id, "sessionId": run.get("sessionId"), "route": route, "state": run["state"],
                   "usage": run.get("usage"), "durationMs": round((time.monotonic() - started) * 1000), "error": run.get("error")}
        state["receipts"].append(receipt)
        state["activeRun"] = run
        if task is not None:
            task.update(receipt=receipt, sessionId=run.get("sessionId"))
        save()
        if run["state"] != "completed":
            raise RuntimeError("Task " + identity + " " + run["state"] + ": " + str(run.get("error") or ""))
        page = broker.read(run["sessionId"], limit=200)
        assistants = [item.get("data", {}) for item in page.get("items", []) if item.get("kind") == "assistant"]
        final = [item for item in assistants if item.get("phase") in {"final_answer", "final"}]
        # Commentary is deliberately retained in the transcript but is not the
        # structured final result. Do not parse a progress announcement as JSON.
        text = str((final or assistants or [{}])[-1].get("text") or "")
        receipt["reply"] = text[-30000:]
        save()
        return text

    try:
        if routes.get("classifier"):
            state["phase"] = "classifying"
            state["classification"] = _json_reply(turn("classify", "Classify this goal; no edits. Return JSON {\"kind\":\"implementation|research|review\",\"risk\":\"low|medium|high\",\"reason\":\"short\"}. Goal: " + intent["goal"], routes["classifier"]))
        state["phase"] = "planning"
        prompt = ("Plan this goal into a small actionable task tree. Do not execute or edit. Return only JSON "
                  '{"tasks":[{"id":"build","parentId":null,"title":"...","prompt":"...","routingProfile":"executor","needs":[]}]}. '
                  "Profiles available: " + ",".join(routes) + ". Dependencies must be acyclic; prompts preserve every requested condition. "
                  "Goal: " + intent["goal"] + "\nAcceptance checks: " + json.dumps(intent["acceptanceChecks"]))
        state["tasks"] = _task_tree(_json_reply(turn("plan", prompt, routes["planner"])), routes, intent["acceptanceChecks"])
        state["phase"] = "ready"
        save()
        while True:
            control = store.load(job_id, reconcile=False).get("conductorControl", {})
            if not control.get("approved") or control.get("paused"):
                state["phase"] = "paused" if control.get("paused") else "ready"
                save()
                time.sleep(0.3)
                continue
            state["phase"] = "running"
            done = {task["id"] for task in state["tasks"] if task["status"] == "completed"}
            pending = [task for task in state["tasks"] if task["status"] == "waiting" and set(task["needs"]) <= done]
            if not pending:
                if len(done) != len(state["tasks"]):
                    raise RuntimeError("No runnable task remains")
                state["phase"] = "completed"
                save()
                return {"status": "completed", "conductor": state}
            task = pending[0]
            reply = turn(task["id"], task["prompt"], task["route"], task)
            if task is state["tasks"][-1]:
                verified = _json_reply(reply)
                observations = verified.get("checks")
                if verified.get("passed") is not True or not isinstance(observations, list) or len(observations) != len(intent["acceptanceChecks"]) or any(not isinstance(c, dict) or c.get("passed") is not True or not c.get("evidence") for c in observations) or sorted(c.get("check", "") for c in observations) != sorted(intent["acceptanceChecks"]):
                    raise RuntimeError("Final verifier did not prove every acceptance check")
                task["verification"] = verified
            task["status"] = "completed"
            save()
    except Exception as exc:
        state["phase"] = "failed"
        for task in state["tasks"]:
            if task["status"] == "running":
                task.update(status="failed", error=str(exc))
        save()
        return {"status": "failed", "error": str(exc), "conductor": state}
