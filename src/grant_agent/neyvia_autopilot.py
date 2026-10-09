"""Intent-driven execution using grounded manuals, checks and compiled evidence.

Models return data at selection/judgement/frontier boundaries; they never execute
tools, approve actions, promote patches or declare an item done.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path

from jsonschema import Draft202012Validator

from .durability import atomic_write_json
from . import neyvia_manuals as manuals
from .manual_compiler import canonical, digest, compiled_index
from .neyvia_app_sdk import GOAL as APP_GOAL

TEXT = {"type": "string"}
START = {"requestId": {"type": "string", "minLength": 1, "maxLength": 160},
         "text": {"type": "string", "minLength": 1, "maxLength": 40000},
         "sessionId": TEXT, "scopeTools": {"type": "array", "items": TEXT, "minItems": 1, "maxItems": 100},
         "background": {"type": "boolean"},
         "efficiency": {"type": "boolean"},
         "appGoal": APP_GOAL,
         "maxModelCalls": {"type": "integer", "minimum": 1, "maximum": 50},
         "maxSeconds": {"type": "integer", "minimum": 10, "maximum": 3600}}
DEFINITIONS = [
    ("autopilot.start", "Complete an intent through scoped manuals and executable checks; models only decide branches. Retry requestId safely.", START, ["requestId", "text", "scopeTools"]),
    ("autopilot.get", "Read the durable checklist, actual model usage and per-item execution receipts.", {"runId": TEXT}, ["runId"]),
    ("autopilot.list", "List durable autopilot runs in this workspace.", {}, []),
    ("autopilot.stop", "Stop before the next action; retain all receipts and completed work.", {"runId": TEXT}, ["runId"]),
    ("autopilot.resume", "Continue a stopped run without replaying completed or uncertain effects; original scope cannot widen.", {"runId": TEXT, "background": {"type": "boolean"}, "scopeTools": {"type": "array", "items": TEXT}}, ["runId"]),
]
COMMANDS = frozenset("autopilot_" + name + "_command" for name in ("start", "get", "list", "stop", "resume"))

def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

VERIFY = obj({"tool": TEXT, "argsJson": TEXT, "path": TEXT,
              "op": {"enum": ["eq", "contains", "exists"]}, "expectedJson": TEXT})
SELECT = obj({"id": TEXT, "chapter": TEXT, "procedure": TEXT, "inputsJson": TEXT, "verify": VERIFY})
PLAN = obj({"items": {"type": "array", "minItems": 1, "maxItems": 30,
                      "items": obj({"ask": TEXT, "doneWhen": TEXT, "selection": SELECT})},
            "dropped": {"type": "array", "items": obj({"ask": TEXT, "reason": TEXT})},
            "needsPaul": {"type": "array", "items": TEXT}})
DECISION = obj({"option": TEXT, "confident": {"type": "boolean"}, "reason": TEXT})
RECOVERY = obj({"selection": SELECT, "guidance": TEXT, "reason": TEXT})
_LOCK = threading.RLock()
_ACTIVE = set()

def storage(service):
    folder = service.bus.root / ".neyvia" / "autopilot"
    folder.mkdir(parents=True, exist_ok=True)
    return folder

def state_path(service, identity):
    if not re.fullmatch(r"[a-f0-9]{32}", identity or ""):
        raise ValueError("runId must be a returned autopilot identity")
    return storage(service) / (identity + ".json")

def load(service, identity):
    return json.loads(state_path(service, identity).read_text(encoding="utf-8"))

@contextmanager
def state_lock(service, identity):
    folder = storage(service) / "state-locks" / identity
    folder.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 5
    while True:
        guard = manuals.execution_lock(folder)
        try:
            guard.__enter__()
            break
        except RuntimeError:
            if time.monotonic() > deadline:
                raise
            time.sleep(.01)
    try:
        yield
    finally:
        guard.__exit__(None, None, None)

def save(service, run, *, control=None):
    path = state_path(service, run["runId"])
    with _LOCK, state_lock(service, run["runId"]):
        if control == "stop":
            current = load(service, run["runId"])
            if current["status"] != "completed":
                current.update(stopRequested=True, status="stopped")
            run.clear()
            run.update(current)
        clear = run.pop("_clearStop", False)
        if path.exists() and not clear:
            if json.loads(path.read_text(encoding="utf-8")).get("stopRequested"):
                run["stopRequested"] = True
                if run["status"] != "completed":
                    run["status"] = "stopped"
        run["elapsedMs"] = int((time.time() - run["startedAt"]) * 1000)
        atomic_write_json(path, run)
    # The same bus drives both the future chat UI and the existing checklist.
    service.bus.put("autopilot:" + run["runId"], run)
    service.bus.emit("autopilot.state", {"run": run})
    if run.get("sessionId") and run["items"]:
        service.call("plan.update", {"sessionId": run["sessionId"], "plan": [
            {"step": row["ask"], "status": row["status"] if row["status"] in {"in_progress", "completed"} else "pending"}
            for row in run["items"]], "explanation": run.get("error", "Autopilot")[:300]})

def catalog(service, registry, scope):
    rows = []
    for record in manuals.records():
        _, sha, data = manuals.get_manual(record["id"], service.bus.root / ".neyvia")
        for chapter_id, chapter in data["chapters"].items():
            for name, procedure in chapter["procedures"].items():
                tools = {chapter["actions"][s["action"]]["tool"] for s in procedure["steps"] if "action" in s}
                tools |= {chapter["checks"][s["check"]]["tool"] for s in procedure["steps"] if s.get("check")}
                if tools.issubset(scope):
                    rows.append({"id": data["id"], "chapter": chapter_id, "procedure": name,
                                 "goal": procedure["goal"], "inputs": procedure["inputs"], "sha256": sha,
                                 "checks": list(chapter["checks"]), "judges": chapter["judge"]})
    return rows

def model(service, run, reason, prompt, schema, *, large=False, validate=None, normalize=None):
    from .autopilot_model import decide
    def budget():
        if stopped(service, run):
            raise RuntimeError("Stopped before the next model decision")
        remaining = run["maxSeconds"] - (time.time() - run["startedAt"])
        if remaining <= 1:
            raise RuntimeError("Autopilot elapsed-time budget reached")
        return min(120, remaining)

    small_model = os.environ.get("NEYVIA_AUTOPILOT_SMALL_MODEL", "gpt-6-luna")
    if small_model not in {"gpt-6-luna", "gpt-6.1-sol"}:
        raise ValueError("NEYVIA_AUTOPILOT_SMALL_MODEL must name a supported route")

    def provider(prompt, schema, root, model=None, timeout=120):
        model = model or small_model
        if len(run["models"]) >= run["maxModelCalls"]:
            raise RuntimeError("Autopilot model-call budget reached")
        timeout = min(timeout, budget())
        try:
            result = decide(prompt, schema, root, model=model, timeout=timeout)
        except Exception as exc:
            path = getattr(exc, "receipt_path", "")
            receipt = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
            row = {"model": model, "reason": reason, "status": "failed", "tokens": receipt.get("tokens") or {},
                   "usageKnown": receipt.get("tokens") is not None, "elapsedMs": receipt.get("elapsedMs"), "receiptPath": path}
            account(row)
            raise
        row = {key: result[key] for key in ("model", "tokens", "elapsedMs", "receiptPath")}
        row.update(reason=reason, status="completed", usageKnown=True)
        account(row)
        if normalize:
            normalize(result["answer"])
        return result

    def account(row):
        run["models"].append(row)
        for key, value in row["tokens"].items():
            if isinstance(value, (int, float)):
                run["tokens"][key] = run["tokens"].get(key, 0) + value
        save(service, run)

    timeout = budget()
    if run.get("efficiency", True):
        from .efficiency_cascade import Cascade
        def grounded(answer):
            if normalize:
                normalize(answer)
            Draft202012Validator(schema).validate(answer)
            return validate(answer) if validate else True
        try:
            result = Cascade(service.bus.root).decide(
                prompt, schema, scope={**run["cascadeScope"], "harness": "autopilot", "path": "autopilot:" + reason},
                preconditions={"intentSha256": digest(run["text"]), "promptSha256": digest(prompt)},
                validate=grounded, provider=provider, force_big=large, timeout=timeout,
                small_model=small_model)
        except Exception as exc:
            path = getattr(exc, "receipt_path", "")
            if path:
                failed = json.loads(Path(path).read_text(encoding="utf-8"))
                run.setdefault("cascade", []).append({"reason": reason, **{
                    key: failed.get(key) for key in ("route", "modelCalls", "elapsedMs", "receiptPath", "trace")}})
                save(service, run)
            raise
        run.setdefault("cascade", []).append({"reason": reason, **{
            key: result.get(key) for key in ("route", "modelCalls", "elapsedMs", "receiptPath", "trace")}})
        save(service, run)
    else:
        result = provider(prompt, schema, service.bus.root, model="gpt-6.1-sol" if large else small_model, timeout=timeout)
    if normalize:
        normalize(result["answer"])
    Draft202012Validator(schema).validate(result["answer"])
    if validate:
        validate(result["answer"])
    return result["answer"]


class ManualSelectionError(ValueError):
    """A planner guess that needs catalog correction before any execution."""


def resolve_manual_id(identity, rows, *, chapter="", procedure=""):
    """Resolve only unique live catalog identities; never invent an alias target."""
    identities = sorted({row["id"] for row in rows})
    if identity in identities:
        return identity
    if not isinstance(identity, str):
        raise ManualSelectionError("Manual selection must name a live catalog ID")

    def key(value):
        value = value.strip().casefold()
        value = re.sub(r"^(?:neyvia\.)?(?:manuals?[.:/])?", "", value)
        value = re.sub(r"\.manual(?:\.json)?$", "", value)
        return re.sub(r"[^a-z0-9]", "", value)

    # A chapter/procedure pair is stronger evidence than spelling similarity.
    matching = sorted({row["id"] for row in rows
                       if row["chapter"] == chapter and row["procedure"] == procedure})
    # Older planners marked an unknown alias as a frontier but retained the
    # exact live chapter/procedure. That unique ownership still grounds it.
    if identity == "":
        return matching[0] if len(matching) == 1 else ""
    candidates = matching or identities
    aliases = [value for value in candidates if key(value) == key(identity)]
    if len(aliases) == 1:
        return aliases[0]
    scored = sorted(((SequenceMatcher(None, key(identity), key(value)).ratio(), value)
                     for value in candidates), reverse=True)
    if scored and scored[0][0] >= .82 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= .08):
        return scored[0][1]
    if len(matching) == 1:
        return matching[0]
    raise ManualSelectionError("No unique live manual matches the planner selection")


def selection_model(service, run, reason, prompt, schema, rows, *, large=False, validate=None):
    """Constrain IDs to this live scoped index and retry one invalid selection."""
    schema = deepcopy(schema)
    selection_schema = (schema["properties"]["items"]["items"]["properties"]["selection"]
                        if "items" in schema["properties"] else schema["properties"]["selection"])
    selection_schema["properties"]["id"] = {"type": "string", "enum": ["", *sorted({row["id"] for row in rows})]}
    prompt += ("\nManual IDs must be exact live catalog IDs in the schema. The host resolves unique manual aliases "
               "and typos, so choose their canonical live IDs rather than treating alias spelling as a frontier. "
               "Empty id means no safe catalog route.")
    rejected = []

    def normalize(answer):
        selections = ([item["selection"] for item in answer["items"]]
                      if "items" in answer else [answer["selection"]])
        for selected in selections:
            original = selected["id"]
            try:
                resolved = resolve_manual_id(original, rows, chapter=selected["chapter"], procedure=selected["procedure"])
            except ManualSelectionError as exc:
                rejected.append(str(exc))
                raise
            if resolved != original:
                selected["id"] = resolved
                run.setdefault("manualResolutions", []).append({"from": original, "to": resolved,
                    "chapter": selected["chapter"], "procedure": selected["procedure"], "reason": reason})

    for attempt in range(2):
        rejected.clear()
        try:
            return model(service, run, reason, prompt, schema, large=large, validate=validate, normalize=normalize)
        except Exception:
            if not rejected:
                raise
            if attempt:
                raise ManualSelectionError("Planner could not select a live manual after one catalog retry") from None
            run.setdefault("manualSelectionRetries", []).append({"reason": reason, "error": rejected[-1]})
            save(service, run)
            prompt += "\nThe previous selection did not resolve to a unique live manual. Retry once using only the supplied catalog."

def decode_selection(selection):
    selected = {key: selection[key] for key in ("id", "chapter", "procedure")}
    selected["inputs"] = json.loads(selection["inputsJson"])
    verification = selection["verify"]
    selected["verify"] = {"tool": verification["tool"], "args": json.loads(verification["argsJson"]),
                          "expect": {"path": verification["path"], "op": verification["op"],
                                     "value": json.loads(verification["expectedJson"])}}
    return selected

def checked_selection(service, selected, registry, run):
    if not selected["id"]:
        raise ManualSelectionError("No safe scoped manual procedure was selected")
    rows = run.get("cascadeScope", {}).get("manuals", [])
    if rows:
        selected["id"] = resolve_manual_id(selected["id"], rows, chapter=selected["chapter"], procedure=selected["procedure"])
    _, sha, data = manuals.get_manual(selected["id"], service.bus.root / ".neyvia")
    manuals.validate(data, registry)
    _, chapter, procedure = manuals.chapter_entry(data, selected["chapter"], "procedures", selected["procedure"])
    Draft202012Validator(procedure["inputs"]).validate(selected["inputs"])
    verify = selected["verify"]
    if verify["tool"] not in run["scopeTools"]:
        raise PermissionError("Acceptance observer is outside the allowed scope")
    spec = registry.describe(verify["tool"])
    if spec["mutability_class"] not in {"read", "none"} or verify["tool"] not in SAFE_READS:
        raise PermissionError("Acceptance must use an observational tool")
    Draft202012Validator(spec["inputSchema"]).validate(verify["args"])
    for position, step in enumerate(procedure["steps"]):
        if "action" not in step:
            continue
        action = chapter["actions"][step["action"]]
        if action["tool"] not in run["scopeTools"]:
            raise PermissionError("Manual action is outside the allowed scope")
        if action["tool"] not in SAFE_READS | {"workspace.write"}:
            raise PermissionError("Action requires explicit irreversible/external approval: " + action["tool"])
        if action["tool"] == "workspace.write":
            source = next((s for s in procedure["steps"][:position] if s.get("save") == "before"), None)
            if (not step.get("check") or not source or chapter["actions"][source["action"]]["tool"] != "workspace.read" or
                    step["args"].get("expectedSha256") != {"$result": "before.sha256"} or
                    source["args"].get("path") != step["args"].get("path")):
                raise PermissionError("Automatic writes require saved source on the same path, CAS hash and executable readback")
    return sha, data, chapter

# Ordinary local observations and CAS edits can run unattended. Everything else
# remains an explicit authority boundary, even if a manual says reversible.
SAFE_READS = frozenset({"workspace.read", "workspace.search", "runtime.environment", "neyvia.manual.compiled",
                       "neyvia.manual.versions", "neyvia.manual.index", "neyvia.notes.list", "neyvia.notes.read",
                       "neyvia.files.list", "neyvia.files.stat", "neyvia.files.read", "neyvia.app_sdk.describe", "neyvia.app_sdk.state"})


def verify_app_goal(service, run, dispatch):
    """A caller-authorized live journey is required before an app run can finish."""
    goal = run.get("appGoal")
    if not goal:
        return
    if "neyvia.app_sdk.verify" not in run["scopeTools"]:
        raise PermissionError("App completion requires app_sdk.verify in the original caller scope")
    recovering = run.get("appGoalAttemptStatus") == "executing"
    if not recovering:
        run["appGoalAttempt"] = int(run.get("appGoalAttempt", 0)) + 1
        run["appGoalActionId"] = "autopilot:" + str(run.get("runId", "app-goal")) + ":app-goal:" + str(run["appGoalAttempt"])
    action_id = run["appGoalActionId"]
    run["appGoalAttemptStatus"] = "executing"
    if run.get("runId"):
        save(service, run)
    result = dispatch("neyvia.app_sdk.verify", goal, action_id=action_id)
    run["appGoalVerification"] = result
    run["appGoalAttemptStatus"] = "returned"
    observed = manuals.unwrap(result)
    run["appGoalVerification"] = observed
    if observed.get("ok") is not True:
        raise RuntimeError("Running app failed its goal checks; Autopilot cannot mark this run done")
    if recovering:
        # The prior intent is reconciled first; its saved result cannot supply
        # fresh completion evidence after the process was interrupted.
        verify_app_goal(service, run, dispatch)


def completed_response(service, run, dispatch):
    """Completed app runs are rechecked when retried or resumed, never replayed."""
    if run.get("status") == "completed" and run.get("appGoal"):
        try:
            verify_app_goal(service, run, dispatch)
        except Exception as exc:
            run.update(status="blocked", error=str(exc)[:2000])
        save(service, run)
    return {"ok": run["status"] == "completed", "run": run, "replayed": True}

def explore(service, run, item, rows, registry, dispatch, failure):
    """Observe the frontier, propose a quarantined patch and use a grounded route."""
    observer = "runtime.environment"
    observed = manuals.unwrap(dispatch(observer, {}, action_id="")) if observer in run["scopeTools"] else {"catalog": rows}
    prompt = ("An autopilot item met a manual frontier. Choose a current existing procedure that fulfills the ask, "
              "and a concise guidance patch explaining the discovered mapping. Never request promotion or tools outside scope. "
              "Empty id means no safe route. Return selection with a final observational verifier proving the exact ask.\n" +
              canonical({"intent": run["text"], "item": item, "failure": failure, "observed": observed, "catalog": rows}))
    def grounded(answer):
        selected = decode_selection(answer["selection"])
        if selected["id"]:
            checked_selection(service, selected, registry, run)
        return True
    answer = selection_model(service, run, "frontier: explored scoped observation and repair", prompt, RECOVERY,
                             rows, large=True, validate=grounded)
    selected = decode_selection(answer["selection"])
    if not selected["id"]:
        raise ManualSelectionError("No safe scoped manual procedure fulfills this ask")
    patch_id = selected["id"]
    _, sha, data = manuals.get_manual(patch_id, service.bus.root / ".neyvia")
    chapter = selected["chapter"] if selected["chapter"] in data["chapters"] else next(iter(data["chapters"]))
    from .manual_versions import quarantine
    from .manual_state import escape
    patch = quarantine(service.bus.root / ".neyvia", patch_id, sha, answer["reason"],
                       {"autopilotRun": run["runId"], "ask": item["ask"], "failure": failure, "observed": observed},
                       [{"op": "add", "path": "/chapters/" + escape(chapter) + "/guidance/-", "value": answer["guidance"]}])
    item.setdefault("frontier", []).append({**patch, "observed": observed, "reason": answer["reason"]})
    checked_selection(service, selected, registry, run)
    item["selection"] = selected
    save(service, run)

def stopped(service, run):
    saved = load(service, run["runId"])
    if saved.get("stopRequested"):
        run.update(status="stopped", stopRequested=True)
        return True
    if time.time() - run["startedAt"] > run["maxSeconds"]:
        raise RuntimeError("Autopilot elapsed-time budget reached")
    return False


def learn_completed(service, run, item):
    """Publish executable, scoped transitions only after real acceptance passes."""
    if not run.get("efficiency", True) or item.get("transitionId"):
        return
    from .transition_memory import TransitionStore
    store = TransitionStore(service.bus.root)
    selected = item["selection"]
    completed = [{"selectionSha256": digest(row["selection"]),
                  "verificationSha256": digest(row["verification"])}
                 for row in run["items"] if row is not item and row["status"] == "completed"]
    before = {"type": "autopilot.verified_state", "intentSha256": digest(run["text"]),
              "scopeSha256": digest(run["cascadeScope"]), "completed": completed}
    effect = {**before, "completed": completed + [{"selectionSha256": digest(selected),
                                                  "verificationSha256": digest(item["verification"])}]}
    args = {"scriptId": item["scriptId"], "inputs": selected["inputs"]} if item["route"] == "script" else {
        key: selected[key] for key in ("id", "chapter", "procedure", "inputs")}
    args["scopeTools"] = run["scopeTools"]
    operation = {"type": "manual.script.run" if item["route"] == "script" else "manual.run", "args": args,
                 "acceptance": {key: selected["verify"][key] for key in ("tool", "args", "expect")}}
    proof = {"status": "completed", "operation": operation, "effect": effect,
             "checks": [{"kind": "manual-completed", "passed": item["receipt"]["status"] == "completed"},
                        {"kind": "acceptance", "passed": item["verification"]["passed"]}],
             "manualReceipt": item["receipt"], "verification": item["verification"],
             "autopilotRunId": run["runId"]}
    path = storage(service) / run["runId"] / ("transition-" + str(run["items"].index(item)) + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, proof)
    row = store.learn(goal={"type": "autopilot.item", "ask": item["ask"], "doneWhen": item["doneWhen"]},
                      preconditions=before, operation=operation, effect=effect,
                      failure={"type": "escalate", "on": ["changed_scope", "changed_precondition", "failed_acceptance"],
                               "requires": "reconcile before any effect replay"},
                      receipt={"receiptPath": str(path)}, scope=run["cascadeScope"])
    item["transitionId"] = row["id"]
    run.setdefault("learnedTransitions", []).append(row)


def replay_completed(service, run, item, registry, dispatch, rows):
    """Reuse a checked operation, with fresh observation and unchanged authority."""
    if not run.get("efficiency", True):
        return False
    started = time.monotonic()
    from .transition_memory import TransitionStore
    selected = item["selection"]
    _, _, chapter = checked_selection(service, selected, registry, run)
    procedure = chapter["procedures"][selected["procedure"]]
    # A remembered judgement cannot authorize a fresh effect. Those paths keep
    # the ordinary grounded judgement loop, including its model budget.
    if any("judge" in step for step in procedure["steps"]):
        return False
    completed_items = [row for row in run["items"] if row is not item and row["status"] == "completed"]
    before = {"type": "autopilot.verified_state", "intentSha256": digest(run["text"]),
              "scopeSha256": digest(run["cascadeScope"]), "completed": [
                  {"selectionSha256": digest(row["selection"]), "verificationSha256": digest(row["verification"])}
                  for row in completed_items]}
    store = TransitionStore(service.bus.root)
    found = store.lookup({"type": "autopilot.item", "ask": item["ask"], "doneWhen": item["doneWhen"]},
                         before, run["cascadeScope"])
    if found["status"] == "conflict":
        item["memoryConflict"] = [row["id"] for row in found["rows"]]
        item["quarantinedMemoryTransitions"] = item["memoryConflict"]
        explore(service, run, item, rows, registry, dispatch,
                {"kind": "executable-memory-conflict", "transitionIds": item["memoryConflict"],
                 "instruction": "Reconcile through the current grounded catalog; disputed memory cannot execute."})
        return False
    if found["status"] != "match":
        return False
    row = found["row"]
    expected_args = {key: selected[key] for key in ("id", "chapter", "procedure", "inputs")}
    expected_args["scopeTools"] = run["scopeTools"]
    expected_operation = {"type": "manual.run", "args": expected_args, "acceptance": selected["verify"]}
    if row["operation"] != expected_operation:
        item["quarantinedMemoryTransitions"] = [row["id"]]
        explore(service, run, item, rows, registry, dispatch,
                {"kind": "executable-memory-selection-disagreement", "transitionIds": [row["id"]]})
        return False
    def observe():
        live = []
        for prior in completed_items:
            verify = prior["selection"]["verify"]
            observed = manuals.unwrap(dispatch(verify["tool"], verify["args"], action_id=""))
            passed = manuals.expect(observed, verify["expect"], {}, {}, service.bus.root)
            verification = {"passed": passed, "observed": observed, **verify}
            if not passed or verification != prior["verification"]:
                raise RuntimeError("A previously completed effect changed; memory escalation required")
            live.append({"selectionSha256": digest(prior["selection"]), "verificationSha256": digest(verification)})
        if item.get("receipt"):
            verify = selected["verify"]
            observed = manuals.unwrap(dispatch(verify["tool"], verify["args"], action_id=""))
            passed = manuals.expect(observed, verify["expect"], {}, {}, service.bus.root)
            item["verification"] = {"passed": passed, "observed": observed, **verify}
            if not passed:
                raise RuntimeError("Replayed operation failed fresh acceptance; reconcile effects")
            live.append({"selectionSha256": digest(selected), "verificationSha256": digest(item["verification"])})
        return {**before, "completed": live}
    def execute_operation(operation):
        checked_selection(service, selected, registry, run)
        item.update(effectUncertain=True, route="memory", memoryTransitionId=row["id"])
        save(service, run)
        receipt = manuals.call(service, operation["type"], operation["args"], dispatcher=dispatch, registry=registry)
        item["receipt"] = receipt
        save(service, run)
        if receipt["status"] != "completed":
            raise RuntimeError("Memory replay did not complete; reconcile effects before retrying")
        return receipt
    replay = store.replay(row, execute_operation, observe, run["cascadeScope"], before)
    elapsed = round((time.monotonic() - started) * 1000, 3)
    replay["elapsedMs"] = elapsed
    item.update(effectUncertain=False, memoryReplay=replay)
    run.setdefault("cascade", []).append({"reason": "executable item replay", "route": "memory",
                                          "modelCalls": [], "transitionId": row["id"], "elapsedMs": elapsed})
    save(service, run)
    return True


def learn_journey(service, run):
    rows = run.get("learnedTransitions", [])
    if len(rows) < 2 or run.get("journeyTransitionId"):
        return
    from .transition_memory import TransitionStore
    operation = {"type": "sequence", "steps": [{"operation": row["operation"],
                  "preconditions": row["preconditions"], "effect": row["effect"]} for row in rows]}
    path = storage(service) / run["runId"] / "journey-transition.json"
    atomic_write_json(path, {"status": "completed", "operation": operation, "effect": rows[-1]["effect"],
                            "checks": [{"kind": "all-items-completed-and-accepted", "passed": True}],
                            "autopilotRunId": run["runId"], "transitionIds": [row["id"] for row in rows]})
    row = TransitionStore(service.bus.root).compose(
        rows, goal={"type": "autopilot.journey", "intent": run["text"]},
        receipt={"receiptPath": str(path)}, scope=run["cascadeScope"])
    run["journeyTransitionId"] = row["id"]

def execute(service, identity, registry, dispatch):
    lockroot = storage(service) / identity
    lockroot.mkdir(exist_ok=True)
    try:
        with manuals.execution_lock(lockroot):
            return _execute(service, identity, registry, dispatch)
    except RuntimeError as exc:
        with _LOCK:
            _ACTIVE.discard((str(service.bus.root), identity))
        return {"ok": False, "run": load(service, identity), "error": str(exc)}

def _execute(service, identity, registry, original_dispatch):
    run = load(service, identity)
    def dispatch(tool, arguments, action_id=""):
        if tool not in run["scopeTools"]:
            raise PermissionError("Nested action/check is outside the original caller scope")
        if stopped(service, run):
            raise RuntimeError("Stopped before the next manual action")
        if tool == "workspace.write":
            current = manuals.unwrap(original_dispatch("workspace.read", {"path": arguments["path"]}, action_id=""))
            if current.get("truncated") or current["sha256"] != arguments.get("expectedSha256"):
                raise PermissionError("Write source changed or was truncated; reconcile before overwriting")
        return original_dispatch(tool, arguments, action_id=action_id)
    try:
        rows = catalog(service, registry, set(run["scopeTools"]))
        run["cascadeScope"] = {"workspace": str(service.bus.root.resolve()), "tools": sorted(run["scopeTools"]), "manuals": [
            {key: row[key] for key in ("id", "chapter", "procedure", "sha256")} for row in rows]}
        if not run["items"]:
            from .neyvia_awareness import intent_checklist
            rules = intent_checklist({"text": run["text"]})["prompt"]
            prompt = (rules + "\nFor each kept ask select a catalog procedure and exact JSON inputs, plus an observational tool "
                      "and executable eq/contains/exists expectation proving doneWhen. Never invent procedure names. "
                      "Empty id denotes a frontier. Tools never run in this model call. Preserve all asks; corrections go in dropped. "
                      "Output schema uses selection.inputsJson and verify.argsJson/expectedJson as JSON strings. "
                      "Tool result shapes: workspace.read -> {content:string,path:string,sha256:string}; "
                      "workspace.search -> {matches:[{path,line,snippet}],count:int,complete:bool,truncated:bool}. "
                      "Use path 'matches.0.path' eq the requested file, or 'matches.0.snippet' contains the query; "
                      "never test whether a string is contained in an array of objects. runtime.environment -> {workspaceRoot,executables,python}.\n" +
                      canonical({"catalog": rows, "scopeTools": run["scopeTools"]}))
            def grounded_plan(answer):
                for item in answer["items"]:
                    selected = decode_selection(item["selection"])
                    if selected["id"]:
                        checked_selection(service, selected, registry, run)
                return True
            answer = selection_model(service, run, "intent checklist and manual selection", prompt, PLAN,
                                     rows, validate=grounded_plan)
            run["dropped"], run["needsPaul"] = answer["dropped"], answer["needsPaul"]
            run["items"] = [{**item, "selection": decode_selection(item["selection"]), "status": "pending",
                             "modelReasons": [], "route": "manual"} for item in answer["items"]]
            run["status"] = "running"
            save(service, run)
        for number, item in enumerate(run["items"]):
            if item["status"] == "completed":
                continue
            if stopped(service, run):
                break
            item["status"] = "in_progress"
            save(service, run)
            if item.get("effectUncertain"):
                raise RuntimeError("Interrupted item needs reconciliation; no effect replay")
            try:
                checked_selection(service, item["selection"], registry, run)
            except PermissionError as exc:
                run.update(status="waiting_approval", waiting={"item": number, "reason": str(exc)})
                item["status"] = "blocked"
                break
            except (ValueError, KeyError) as exc:
                explore(service, run, item, rows, registry, dispatch, str(exc))
            selected = item["selection"]
            if not item.get("receipt"):
                scripts = compiled_index(service, {"id": selected["id"]})["scripts"]
                script = next((s for s in scripts if not s["stale"] and s["chapter"] == selected["chapter"] and
                               s["procedure"] == selected["procedure"] and s["inputSha256"] == digest(selected["inputs"])), None)
                if not script:
                    replay_completed(service, run, item, registry, dispatch, rows)
                    selected = item["selection"]
            if not item.get("receipt"):
                item["route"] = "script" if script else "manual"
                if script:
                    item["scriptId"] = script["scriptId"]
                # Saved before dispatch: a crash cannot create a fresh child and repeat writes.
                item["effectUncertain"] = True
                save(service, run)
                args = {"scriptId": script["scriptId"], "inputs": selected["inputs"]} if script else {
                    key: selected[key] for key in ("id", "chapter", "procedure", "inputs")}
                args["scopeTools"] = run["scopeTools"]
                receipt = manuals.call(service, "manual.script.run" if script else "manual.run", args,
                                       dispatcher=dispatch, registry=registry)
                item.update(receipt=receipt, effectUncertain=False)
                save(service, run)
            receipt = item["receipt"]
            while receipt["status"] == "judge":
                if stopped(service, run):
                    break
                judge = receipt["judge"]
                prompt = ("Choose exactly one offered option from this grounded manual judgement. Compare observed results "
                          "with the ask and doneWhen; confident=false on disagreement/incomplete evidence. No tools or approvals. "
                          "The caller already authorized reversible operations within scopeTools. An explicit request to replace "
                          "a file supplies authority; review its full saved before-content and requested replacement. Different "
                          "before/new text is intended, not a disagreement. CAS uses the observed hash to protect concurrent edits. "
                          "Decide only this item; other pending files are inspected and handled separately.\n" +
                          canonical({"intent": run["text"], "ask": item["ask"], "doneWhen": item["doneWhen"],
                                     "judge": judge, "inputs": selected["inputs"], "observed": receipt["results"]}))
                grounded_judge = lambda answer: answer["confident"] and answer["option"] in judge["options"]
                answer = model(service, run, "judgement: " + judge["id"], prompt, DECISION, validate=grounded_judge)
                if not answer["confident"] or answer["option"] not in judge["options"]:
                    answer = model(service, run, "disagreement: " + judge["id"], prompt + "\nSmall-model judgement: " + canonical(answer), DECISION, large=True, validate=grounded_judge)
                if not answer["confident"] or answer["option"] not in judge["options"]:
                    raise RuntimeError("Models disagree or cannot decide the grounded judgement")
                item["modelReasons"].append(answer["reason"])
                if stopped(service, run):
                    break
                item["effectUncertain"] = True
                save(service, run)
                args = {"scriptId": item["scriptId"]} if item["route"] == "script" else {
                    key: selected[key] for key in ("id", "chapter", "procedure")}
                args.update(runId=receipt["runId"], decisions={judge["id"]: answer["option"]}, scopeTools=run["scopeTools"])
                receipt = manuals.call(service, "manual.script.run" if item["route"] == "script" else "manual.run", args,
                                       dispatcher=dispatch, registry=registry)
                item.update(receipt=receipt, effectUncertain=False)
                save(service, run)
            if run["status"] == "stopped":
                item["status"] = "pending"
                break
            if receipt["status"] != "completed":
                # Explore once, preserve failed receipts, never retry partial effects.
                item["failedReceipt"] = receipt
                explore(service, run, item, rows, registry, dispatch, receipt)
                raise RuntimeError("Manual failed; explored quarantine saved, effect reconciliation required")
            verification = selected["verify"]
            observed = manuals.unwrap(dispatch(verification["tool"], verification["args"], action_id=""))
            passed = manuals.expect(observed, verification["expect"], {}, {}, service.bus.root)
            item["verification"] = {"passed": passed, "observed": observed, **verification}
            if not passed:
                item["failedVerification"] = item["verification"]
                explore(service, run, item, rows, registry, dispatch, {"kind": "acceptance-shape-frontier", "verification": item["verification"]})
                repaired = item["selection"]
                if any(repaired[key] != selected[key] for key in ("id", "chapter", "procedure", "inputs")):
                    raise RuntimeError("Frontier repair requires another procedure; completed effects require reconciliation")
                verification = repaired["verify"]
                observed = manuals.unwrap(dispatch(verification["tool"], verification["args"], action_id=""))
                passed = manuals.expect(observed, verification["expect"], {}, {}, service.bus.root)
                item["verification"] = {"passed": passed, "observed": observed, **verification}
                if not passed:
                    raise RuntimeError("Acceptance verifier failed after explored repair; checklist item stays incomplete")
            item["status"] = "completed"
            item["zeroTokenSteps"] = sum(1 for s in receipt.get("checks", []))
            learn_completed(service, run, item)
            save(service, run)
        if all(item["status"] == "completed" for item in run["items"]):
            if run.get("needsPaul"):
                run.update(status="waiting_approval", waiting={"reason": "Unresolved authority or scope", "asks": run["needsPaul"]})
            else:
                verify_app_goal(service, run, dispatch)
                run["status"] = "completed"
                learn_journey(service, run)
    except Exception as exc:
        run.update(status="stopped" if run.get("stopRequested") else "blocked", error=str(exc)[:2000])
        for item in run["items"]:
            if item["status"] == "in_progress":
                item["status"] = "blocked"
        if getattr(exc, "receipt_path", None):
            run["failedModelReceipt"] = str(exc.receipt_path)
    finally:
        save(service, run)
        with _LOCK:
            _ACTIVE.discard((str(service.bus.root), identity))
    return {"ok": run["status"] == "completed", "run": run}

def launch(service, run, registry, dispatch, background):
    key = (str(service.bus.root), run["runId"])
    with _LOCK:
        if key in _ACTIVE:
            return {"ok": True, "run": load(service, run["runId"]), "reattached": True}
        _ACTIVE.add(key)
    if background:
        threading.Thread(target=execute, args=(service, run["runId"], registry, dispatch), daemon=True,
                         name="autopilot-" + run["runId"][:8]).start()
        return {"ok": True, "run": run}
    return execute(service, run["runId"], registry, dispatch)

def call(service, name, args, *, registry=None, dispatcher=None):
    registry, dispatch = manuals.context(service, dispatcher, registry)
    if name == "autopilot.list":
        return {"ok": True, "runs": [json.loads(p.read_text(encoding="utf-8")) for p in storage(service).glob("*.json")]}
    if name == "autopilot.start":
        schema = {"type": "object", "properties": START, "required": ["requestId", "text", "scopeTools"], "additionalProperties": False}
        Draft202012Validator(schema).validate(args)
        for required in ("requestId", "text", "scopeTools"):
            if required not in args:
                raise ValueError(required + " is required")
        allowed = SAFE_READS | {"workspace.write"} | ({"neyvia.app_sdk.verify"} if args.get("appGoal") else set())
        if any(tool not in allowed for tool in args["scopeTools"]):
            raise PermissionError("Scope contains unsupported automatic actions; select local observations/CAS writes only")
        if args.get("appGoal") and "neyvia.app_sdk.verify" not in args["scopeTools"]:
            raise PermissionError("appGoal requires neyvia.app_sdk.verify in scopeTools")
        identity = hashlib.sha256(args["requestId"].encode()).hexdigest()[:32]
        fingerprint = digest({key: args.get(key) for key in ("text", "sessionId", "scopeTools", "maxModelCalls", "maxSeconds", "efficiency", "appGoal")})
        with _LOCK, manuals.execution_lock(storage(service)):
            path = state_path(service, identity)
            if path.exists():
                run = load(service, identity)
                if run["fingerprint"] != fingerprint:
                    raise ValueError("requestId is already bound to different intent or scope")
                return completed_response(service, run, dispatch) if run["status"] == "completed" else {"ok": True, "run": run, "replayed": True}
            run = {"schema": "neyvia.autopilot.v1", "runId": identity, "requestId": args["requestId"],
                   "fingerprint": fingerprint, "text": args["text"], "sessionId": args.get("sessionId", ""),
                   "scopeTools": args["scopeTools"], "efficiency": args.get("efficiency", True),
                   "appGoal": args.get("appGoal"),
                   "status": "planning", "items": [], "models": [], "cascade": [], "tokens": {},
                   "startedAt": time.time(), "maxSeconds": args.get("maxSeconds", 600), "maxModelCalls": args.get("maxModelCalls", 12)}
            save(service, run)
        return launch(service, run, registry, dispatch, args.get("background", False))
    run = load(service, args["runId"])
    if name == "autopilot.get":
        return {"ok": True, "run": run}
    if name == "autopilot.stop":
        with _LOCK:
            save(service, run, control="stop")
        return {"ok": True, "run": run}
    if name == "autopilot.resume":
        if (str(service.bus.root), run["runId"]) in _ACTIVE:
            return {"ok": False, "run": run, "error": "Worker is still stopping/running; resume after it returns"}
        if "scopeTools" in args and set(args["scopeTools"]) != set(run["scopeTools"]):
            raise PermissionError("Resume must retain original caller tool scope")
        if run["status"] == "completed":
            return completed_response(service, run, dispatch)
        if run["status"] in {"waiting_approval", "blocked"}:
            return {"ok": False, "run": run, "error": "Reconcile blocked effects/authority before resuming"}
        lockroot = storage(service) / run["runId"]
        lockroot.mkdir(exist_ok=True)
        with manuals.execution_lock(lockroot):
            run = load(service, args["runId"])
            run.update(stopRequested=False, _clearStop=True, status="running" if run["items"] else "planning")
            save(service, run)
        return launch(service, run, registry, dispatch, args.get("background", False))
    raise ValueError("Unknown autopilot operation")

def request(backend, operation, args):
    from .neyvia_workspace_tools import workspace_for
    from .neyvia_agent import NeyviaToolGateway
    service = workspace_for(backend.root, backend)
    if operation in {"get", "list", "stop"}:
        return call(service, "autopilot." + operation, args)
    from .native_access import mutation_tools_for_mode
    allowed_mutations = set(mutation_tools_for_mode("workspace"))
    goal_run = load(service, args["runId"]) if operation == "resume" and args.get("runId") else args
    if goal_run.get("appGoal") and "neyvia.app_sdk.verify" in goal_run.get("scopeTools", []):
        allowed_mutations.add("neyvia.app_sdk.verify")
    gateway = NeyviaToolGateway(backend.root, allow_mutations=True, permission_mode="workspace",
                               allowed_mutation_tools=allowed_mutations)
    return call(service, "autopilot." + operation, args, registry=gateway.native, dispatcher=gateway.call_native)

def forward_command(root, name, payload):
    import http.cookiejar
    import os
    import urllib.request
    try:
        port = int(os.environ.get("NEYVIA_AUTOPILOT_SERVICE_PORT") or os.environ.get("NEYVIA_CONNECTED_SERVICE_PORT") or os.environ.get("NEYVIA_WEB_PORT") or 0)
    except ValueError:
        port = 0
    if not (48191 <= port <= 48199 or 48541 <= port <= 48549):
        return {"ok": False, "error": "Autopilot requires an explicit isolated T17 or App SDK service port"}
    operation = name.removeprefix("autopilot_").removesuffix("_command")
    base = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def post(path, value):
        req = urllib.request.Request(base + path, data=json.dumps(value).encode(), headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=30) as response:
            return json.load(response)
    try:
        post("/api/auth/local-session", {})
        inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
        answer = post("/api/ui/autopilot", {**inner, "operation": operation, "background": True, "_expectedStateRoot": str(root)})
        return answer.get("data", answer)
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": "Autopilot service unavailable: " + str(exc)[:200]}
    finally:
        try:
            post("/api/auth/logout", {})
        except (OSError, ValueError):
            pass
