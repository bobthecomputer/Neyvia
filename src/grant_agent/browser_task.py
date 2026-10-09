"""Goal-checked browser cascade on the existing tab and action receipt seams."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from .browser_site_manuals import fresh_observation
from .browser_scripts import goal as check_predicates

PROPERTIES = {"tabId": {"type": "string"}, "goal": {"type": "string", "maxLength": 12000},
    "requirements": {"type": "array", "minItems": 1, "maxItems": 24, "items": {"type": "string", "maxLength": 2000}},
    "checks": {"type": "array", "maxItems": 12, "items": {"type": "object"}},
    "script": {"type": "string"}, "inputs": {"type": "object"}, "layaContext": {"type": "object"},
    "allowModel": {"type": "boolean"}, "maxActions": {"type": "integer", "minimum": 0, "maximum": 24},
    "maxModelCalls": {"type": "integer", "minimum": 1, "maximum": 8}}


def _normalized(value):
    return " ".join(str(value).split())


def _wall(observation):
    import re
    content = str(observation.get("title", "")) + " " + str(observation.get("text", ""))[:5000]
    from urllib.parse import urlsplit
    page = urlsplit(observation.get("url", ""))
    if re.search(r"(?:^|\.)google\.[a-z.]+$", page.hostname or "") and page.path.startswith("/sorry/") and re.search(r"trafic exceptionnel|non un robot|unusual traffic", content, re.I):
        return "access_wall"
    if re.search(r"captcha|verify (?:you are|that you are) human|unusual traffic", content, re.I) or any(re.search(r"recaptcha|hcaptcha", str(f.get("url", f.get("src", ""))), re.I) for f in observation.get("frames", [])):
        return "captcha"
    if re.search(r"^just a moment|checking (?:your )?browser", content.strip(), re.I):
        return "javascript_challenge"
    if observation.get("authentication", {}).get("required"):
        return "authentication"
    if re.search(r"access denied|security check", content, re.I):
        return "access_wall"
    return None


def handoff(service, args, *, owner=False):
    """Retain the actual blocked page; renderer acknowledgement is separate proof."""
    from .neyvia_browser import fail
    from .durability import atomic_write_json
    from .cl.renderer_effects import show
    from .neyvia_workspace_tools import workspace_for
    observation = fresh_observation(service, args["tabId"], owner)
    if not owner and not service.tab(args)["agentGranted"]:
        fail("tab_not_granted", "A task may hand off only its owner-granted tab")
    reason = _wall(observation)
    if not reason:
        fail("wall_not_observed", "Owner handoff requires a freshly observed access wall")
    task_id = uuid.uuid4().hex
    prompt = "Paul, please resolve this page's human check or sign-in in Neyvia's right pane, then select Resume task. The agent is paused."
    saved = {key: value for key, value in args.items() if key in PROPERTIES}
    value = {"ok": True, "status": "needs_owner", "taskId": task_id, "tabId": args["tabId"],
        "reason": reason, "prompt": prompt, "ownerHandoff": True, "args": saved,
        "observation": observation, "paneStatus": "pending_renderer", "resumed": False}
    service.request("tab.grant", {"tabId": args["tabId"], "enabled": False}, owner=True)
    with service.lock:
        tab = service.tab(args)
        tab.update(pinned=True, ownerTask={key: value[key] for key in ("taskId", "status", "reason", "prompt")})
        service.state["activeTabId"] = tab["id"]
        service.save()
    pane_request = {"kind": "browser", "target": args["tabId"],
        "placement": "side", "side": "right", "ownerTaskId": task_id}
    if tab.get("engine") == "obscura" and service.headless:
        pane_request["runtimeSessionId"] = service.headless.status()["sessionId"]
    pane = show(workspace_for(service.root), pane_request)
    value.update(paneId=pane["paneId"], paneEventId=str(pane["event"]["id"]))
    atomic_write_json(service.directory / "tasks" / (task_id + "-handoff.json"), value)
    return value


def resume(service, args, *, owner=False):
    from .neyvia_browser import fail
    from .durability import atomic_write_json
    import re
    if not owner:
        fail("owner_required", "Only Paul may resume an owner handoff")
    task_id = args.get("taskId", "")
    if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{32}", task_id):
        fail("invalid_task", "Use the persisted handoff task id")
    path = service.directory / "tasks" / (task_id + "-handoff.json")
    with service.lock:
        if not path.is_file():
            fail("invalid_task", "The persisted handoff does not exist")
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved["resumed"]:
            fail("task_resumed", "This handoff was already resumed; inspect its saved outcome")
        tab = service.tab({"tabId": saved["tabId"]})
        if tab.get("ownerTask", {}).get("taskId") != task_id:
            fail("task_superseded", "This tab has a newer owner handoff; resume its current task")
        observation = fresh_observation(service, tab["id"], True)
        if _wall(observation):
            return {"ok": True, "status": "needs_owner", "taskId": task_id, "reason": _wall(observation), "ownerHandoff": True, "observation": observation}
        saved["resumed"] = True
        atomic_write_json(path, saved)
        service.request("tab.grant", {"tabId": tab["id"], "enabled": True}, owner=True)
        tab["ownerTask"]["status"] = "resuming"
        service.save()
    result = run(service, saved["args"], owner=True)
    result.update(ownerHandoff=True, resumedFrom=task_id)
    atomic_write_json(service.directory / "tasks" / (task_id + "-resumed.json"), result)
    with service.lock:
        tab["ownerTask"]["status"] = result["status"]
        service.save()
    return result


def _model(service, goal, requirements, observation, documents, stages, uncertain_actions):
    payload = {"goal": goal, "requirements": requirements, "uncertainActions": list(uncertain_actions), "current": {**observation, "documentIndex": len(documents) - 1},
               "finishOnly": bool(stages and stages[-1]["stage"] == "answer-required"),
               "documents": [{**document, "index": index} for index, document in enumerate(documents)],
               "previousStages": stages[-20:], "asOf": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return _model_request(service, payload)


def _model_request(service, payload):
    directory = service.directory / "tasks" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    worker = Path(__file__).resolve().parents[2] / "scripts" / "browser_luna.cjs"
    node = shutil.which("node")
    if not node or not worker.is_file():
        raise ValueError("Installed Node/Codex planner is unavailable; no model substitution")
    result = subprocess.run([node, str(worker), str(directory)], input=json.dumps(payload),
        capture_output=True, text=True, encoding="utf-8", timeout=135,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ValueError("Luna planner failed: " + result.stderr[-1000:])
    return json.loads(result.stdout)


def run(service, args, *, owner=False):
    from .neyvia_browser import fail
    from .laya_service import browser_decide
    goal, requirements = args.get("goal"), args.get("requirements")
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 12000 or not isinstance(requirements, list) or not 1 <= len(requirements) <= 24 or any(not isinstance(v, str) or not v.strip() or len(v) > 2000 for v in requirements):
        fail("invalid_goal", "Supply bounded goal text and independent all-clause requirements")
    tab_id = args["tabId"]
    with service.lock:
        if not service.tab(args)["agentGranted"]:
            fail("tab_not_granted", "Owner tab grant is required for browser tasks")
    checks = args.get("checks", [])
    if not isinstance(checks, list) or len(checks) > 12:
        fail("invalid_goal", "Supply bounded explicit goal predicates")
    # Validate before any effect. Predicate scope is supplied by the caller;
    # without predicates, only all-clause fresh evidence can finish the task.
    from .browser_verification import validate_expect
    for predicate in checks:
        validate_expect({"expect": predicate})
    began = time.monotonic()
    stages, documents, models = [], [], []
    steps = 0
    uncertain_actions = set()

    def action_key(action, page):
        element = next((e for e in page.get("elements", []) if e["id"] == action.get("element")), {})
        return (page.get("url"), action.get("kind"), action.get("value"), element.get("name"))
    maximum = args.get("maxActions", 8)
    model_maximum = args.get("maxModelCalls", 4)
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 0 <= maximum <= 24 or isinstance(model_maximum, bool) or not isinstance(model_maximum, int) or not 1 <= model_maximum <= 8:
        fail("invalid_goal", "Task budgets are bounded integers")
    observation = fresh_observation(service, tab_id, owner)

    def capture(value):
        nonlocal observation
        observation = value
        documents.append(value)

    capture(observation)

    def result(status, **extra):
        value = {"ok": status == "done", "status": status, "goal": goal, "tabId": tab_id,
                 "stages": stages, "modelCalls": len(models), "modelReceipts": models,
                 "steps": steps, "observation": observation, "durationMs": round((time.monotonic() - began) * 1000, 2), **extra}
        from .durability import atomic_write_json
        if status == "needs_owner" and _wall(observation):
            paused = handoff(service, args, owner=owner)
            value.update(taskId=paused["taskId"], ownerHandoff=True, prompt=paused["prompt"], paneStatus=paused["paneStatus"], paneId=paused["paneId"], paneEventId=paused["paneEventId"])
        atomic_write_json(service.directory / "tasks" / (uuid.uuid4().hex + "-task.json"), value)
        return value

    if _wall(observation):
        # Ordinary engine retry belongs to the explicitly private-desktop host;
        # this service never creates a visible window or solves a challenge.
        wall = _wall(observation)
        return result("needs_owner", reason=wall)
    if args.get("script"):
        try:
            name = args["script"]
            import re
            if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
                fail("invalid_script", "Use an existing bounded compiled procedure name")
            script_path = service.directory / "compiled" / (name + ".json")
            if script_path.is_file() and len(json.loads(script_path.read_text(encoding="utf-8")).get("steps", [])) > maximum:
                return result("frontier", reason="Compiled procedure exceeds the caller's action budget; zero dispatches")
            compiled = service.request("script.run", {"tabId": tab_id, "name": args["script"], "inputs": args.get("inputs", {})}, owner=owner)
            capture(compiled["observation"])
            steps += len(compiled.get("receipts", []))
            stages.append({"stage": "compiled", "verification": compiled.get("verification"), "modelCalls": 0})
            if any(receipt.get("verification", {}).get("verified") is not True and receipt.get("actionId") for receipt in compiled.get("receipts", [])):
                capture(fresh_observation(service, tab_id, owner))
                stages.append({"stage": "read-only-recovery", "status": "observed", "actionReplays": 0, "effectVerified": False})
        except ValueError as error:
            stages.append({"stage": "compiled", "status": "frontier", "reason": str(error), "replaySafe": False})
            if getattr(error, "code", None) not in {"script_missing", "script_scope", "script_quarantined", "invalid_script", "stale_projection", "invalid_target", "effect_unconfirmed", "fresh_observation_unavailable"}:
                return result("frontier", reason=str(error), replaySafe=False)
            capture(fresh_observation(service, tab_id, owner))
    verification = check_predicates(observation, checks)
    if verification["verified"]:
        return result("done", verification=verification)
    if args.get("layaContext"):
        decision = browser_decide(service, {"tabId": tab_id, "question": "grounded_action", "context": args["layaContext"]}, owner=owner)
        stages.append({"stage": "laya", "policy": decision.get("browser_policy"), "status": decision.get("status")})
        selected = decision.get("selected_action")
        if selected and steps < maximum:
            effect = service.request("action", selected, owner=owner)
            if effect.get("actionId"):
                effect = service.request("wait", {"actionId": effect["actionId"], "timeoutMs": 30000}, owner=owner).get("result", {})
            steps += 1
            capture(effect.get("observation") or fresh_observation(service, tab_id, owner))
            if effect.get("verification", {}).get("verified") is not True:
                uncertain_actions.add(action_key({"kind": selected.get("action"), "element": selected.get("element"), "value": selected.get("value")}, observation))
                capture(fresh_observation(service, tab_id, owner))
                stages.append({"stage": "read-only-recovery", "status": "observed", "actionReplays": 0, "effectVerified": False})
            verification = check_predicates(observation, checks)
            if verification["verified"]:
                return result("done", verification=verification)
    else:
        advisory = browser_decide(service, {"tabId": tab_id, "question": "calibrated_advisory", "context": {
            "goal": "What is the observed document loading state?", "decision_profile": "public_observed_fields@1",
            "advisory_field": "readyState", "options": [{"id": "a", "description": observation.get("readyState", "loading")},
            {"id": "b", "description": "loading" if observation.get("readyState") == "complete" else "complete"}]}}, owner=owner)
        stages.append({"stage": "laya", "status": advisory.get("status"), "policy": advisory.get("decision_policy"),
            "acceptedDecision": advisory.get("accepted_decision"), "goalVerified": False,
            "reason": "Whole-goal planning is outside the frozen explicit-control calibration"})
    if args.get("allowModel") is not True:
        return result("model_required", reason="Goal remains unverified or LAYA confidence/scope is insufficient")
    for _ in range(model_maximum):
        if len(models) >= model_maximum:
            return result("frontier", reason="Bounded model-call budget exhausted")
        if _wall(observation):
            return result("needs_owner", reason=_wall(observation))
        try:
            planned = _model(service, goal, requirements, observation, documents, stages, uncertain_actions)
        except (ValueError, subprocess.TimeoutExpired) as error:
            return result("frontier", reason=str(error))
        models.append(planned["receipt"])
        decision = planned["decision"]
        stages.append({"stage": "luna", "status": decision["status"], "reason": decision["reason"]})
        if decision["status"] == "done":
            clauses = decision.get("clauses", [])
            verified = bool(decision.get("answer", "").strip())
            for requirement in requirements:
                rows = [c for c in clauses if c.get("requirement") == requirement]
                if len(rows) != 1 or not rows[0].get("met"):
                    verified = False
                    continue
                clause = rows[0]
                document_index = clause.get("document")
                if isinstance(document_index, bool) or not isinstance(document_index, int) or not 0 <= document_index < len(documents):
                    verified = False
                    continue
                document = documents[document_index]
                content = _normalized(" ".join([document.get("url", ""), document.get("title", ""), document.get("text", ""), json.dumps(document.get("tables", [])), json.dumps([e.get("name", "") for e in document.get("elements", []) if e.get("role") == "image"], ensure_ascii=False)]))
                quotes = [v for v in [clause.get("quote", ""), *clause.get("quotes", [])] if _normalized(v)]
                if not quotes or any(_normalized(v) not in content for v in quotes):
                    verified = False
            predicates_passed = False
            if checks:
                predicates_passed = check_predicates(observation, checks)["verified"]
                verified = verified and predicates_passed
            verification = {"verified": verified, "clauses": clauses}
            stages.append({"stage": "goal", "verification": verification,
                "reason": None if verified else "Quote, exact document index, or predicate failed; correct against supplied indexed fresh documents"})
            if verified and predicates_passed:
                # The goal predicates are deterministic and passed on the live page, and every requirement quote
                # is present in the observed documents: a second model call would only repeat the check.
                stages.append({"stage": "completion-judge", "verdict": True, "skipped": "deterministic-checks-passed", "modelCalls": 0})
                return result("done", answer=decision["answer"], verification=verification)
            if verified:
                if len(models) >= model_maximum:
                    return result("frontier", reason="Completion judge requires remaining model-call budget")
                try:
                    judged = _model_request(service, {"mode": "judge", "goal": goal, "requirements": requirements,
                        "answer": decision["answer"], "documents": documents, "previousStages": stages[-10:]})
                except (ValueError, subprocess.TimeoutExpired) as error:
                    return result("frontier", reason=str(error))
                models.append(judged["receipt"])
                verdict = judged["decision"]
                stages.append({"stage": "completion-judge", **verdict})
                if verdict["verdict"]:
                    return result("done", answer=decision["answer"], verification=verification)
                if verdict["reached_captcha"]:
                    return result("needs_owner", reason=verdict["failure_reason"])
            continue
        action = decision["action"]
        if decision["status"] == "act" and action["kind"] == "none":
            stages.append({"stage": "answer-required", "reason": "No action was selected or dispatched. Return the complete requested answer with status done if all cited facts satisfy the goal; otherwise return frontier. The completion judge still checks every requirement."})
            continue
        if decision["status"] != "act" or steps >= maximum:
            return result("needs_owner" if decision["status"] == "needs_owner" and _wall(observation) else "frontier", reason=decision["reason"])
        element = next((e for e in observation["elements"] if e["id"] == action["element"] and not e.get("secret") and e.get("enabled", True)), None)
        if action["kind"] == "observe":
            capture(fresh_observation(service, tab_id, owner))
            continue
        if action["kind"] == "native":
            return result("native_retry_required", reason="Insufficient JavaScript result rendering")
        if not element or action["kind"] not in {"click", "fill", "select", "submit", "follow"}:
            return result("frontier", reason="Planner target is not observed and enabled")
        key = action_key(action, observation)
        if key in uncertain_actions:
            stages.append({"stage": "plan-rejected", "reason": "Unconfirmed effect cannot be replayed", "dispatched": False})
            capture(fresh_observation(service, tab_id, owner))
            continue
        try:
            if action["kind"] == "follow" and element.get("href"):
                effect = service.request("tab.navigate", {"tabId": tab_id, "url": element["href"]}, owner=owner)
            else:
                from .browser_site_manuals import target_for
                fresh = fresh_observation(service, tab_id, owner)
                if fresh["url"] != observation["url"]:
                    return result("frontier", reason="Navigation changed during planning; replan before dispatch")
                capture(fresh)
                target = target_for(element)
                matching = [row for row in fresh["elements"] if all(row.get(key) == value for key, value in target.items()) and not row.get("secret") and row.get("enabled", True)]
                if len(matching) > 1 and any(row["id"] == element["id"] for row in matching):
                    target["id"] = element["id"]
                effect = service.request("action.batch", {"tabId": tab_id, "revision": fresh["revision"],
                    "steps": [{"target": target, "action": action["kind"], "value": action["value"]}]}, owner=owner)
            if effect.get("actionId"):
                effect = service.request("wait", {"actionId": effect["actionId"], "timeoutMs": 30000}, owner=owner).get("result", {})
            steps += 1
            verified_effect = effect.get("verification", {}).get("verified") is True or (effect.get("ok") is True and bool(effect.get("receipts")) and all(r.get("verification", {}).get("verified") is True for r in effect["receipts"]))
            if action["kind"] != "follow" and not verified_effect:
                uncertain_actions.add(key)
                capture(fresh_observation(service, tab_id, owner))
                stages.append({"stage": "read-only-recovery", "status": "observed", "action": action,
                    "dispatchReceipts": effect.get("receipts", []), "steps": steps, "actionReplays": 0, "effectVerified": False})
                continue
            capture(effect.get("observation") or fresh_observation(service, tab_id, owner))
            stages.append({"stage": "action", "action": action, "verification": effect.get("verification"), "afterUrl": observation["url"], "steps": steps})
        except ValueError as error:
            if getattr(error, "code", None) in {"effect_unconfirmed", "fresh_observation_unavailable"}:
                uncertain_actions.add(key)
                steps += 1
                try:
                    capture(fresh_observation(service, tab_id, owner))
                except ValueError as observe_error:
                    return result("frontier", reason=str(observe_error), replaySafe=False)
                stages.append({"stage": "read-only-recovery", "status": "observed", "actionReplays": 0, "effectVerified": False})
                continue
            return result("frontier", reason=str(error), replaySafe=False)
    return result("frontier", reason="Bounded model-call budget exhausted")
