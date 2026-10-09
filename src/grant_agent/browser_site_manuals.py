"""Observed site manuals and bounded semantic batches, using the real browser service.

Stored facts contain control structure, never query values, result text or answers.
Every reuse compares fresh structure; changed facts are quarantined, not executed.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from urllib.parse import urlsplit

from .durability import atomic_write_json


TARGET_SCHEMA = {"type": "object", "properties": {
    "id": {"type": "string", "maxLength": 100},
    "role": {"type": "string", "maxLength": 100},
    "name": {"type": "string", "maxLength": 2000},
    "inputName": {"type": "string", "maxLength": 500},
    "placeholder": {"type": "string", "maxLength": 1000},
    "frame": {"type": ["string", "null"], "maxLength": 100}},
    "required": ["role", "name"], "additionalProperties": False}


def target_for(row):
    # Compiled procedures retain semantic identity, never transient projection IDs.
    return {key: row[key] for key in TARGET_SCHEMA["properties"] if key != "id" and key in row}


def resolve_target(observation, target, action):
    """Exact semantic identity only: ambiguity escalates rather than picking first."""
    from .neyvia_browser import fail
    if not isinstance(target, dict) or not {"role", "name"} <= set(target) or set(target) - set(TARGET_SCHEMA["properties"]):
        fail("invalid_target", "Batch targets require exact observed role/name and optional inputName/placeholder/frame")
    matches = [row for row in observation.get("elements", [])
               if not row.get("secret") and row.get("enabled", True)
               and action in row.get("actions", [])
               and all(row.get(key) == value for key, value in target.items())]
    if len(matches) != 1:
        fail("ambiguous_target" if matches else "missing_target", "Fresh observation must contain exactly one enabled nonsecret semantic target")
    return matches[0]


def fresh_observation(service, tab_id, owner=False):
    from .neyvia_browser import wait_observation
    result = service.request("observe", {"tabId": tab_id}, owner=owner)
    return wait_observation(service, result) if result.get("actionId") else result


def _structure(observation):
    controls = []
    size = 0
    for row in observation.get("elements", []):
        if row.get("secret") or not row.get("actions") or row.get("nameTruncated"):
            continue
        # Content links change with results. Learn form controls and navigation
        # affordances; result links stay live observations, never cached routes.
        if row.get("role") == "link" and not re.search(r"search|next|previous|page|filter", row.get("name", ""), re.I):
            continue
        if row.get("role") not in {"button", "textbox", "searchbox", "combobox", "checkbox", "radio", "link"}:
            continue
        fact = {"target": target_for(row), "actions": sorted(row["actions"]),
                "enabled": row.get("enabled", True), "type": row.get("type"), "readOnly": row.get("readOnly", False)}
        if row.get("form"):
            # No endpoint guesses, query strings, hidden form fields or secrets.
            fact["form"] = {key: row["form"].get(key) for key in ("method", "role", "name")}
        if row.get("options") and not row.get("optionsTruncated"):
            fact["options"] = [{key: option.get(key) for key in ("label", "value", "enabled")} for option in row["options"]]
        fact_size = len(json.dumps(fact, ensure_ascii=False).encode())
        if fact_size > 32000:
            fact.pop("options", None)
            fact["optionsOmitted"] = True
            fact_size = len(json.dumps(fact, ensure_ascii=False).encode())
        if len(controls) >= 96 or size + fact_size > 300000:
            break
        size += fact_size
        controls.append(fact)
    return controls


def _procedures(controls):
    procedures = []
    for fact in controls:
        target = fact["target"]
        descriptor = " ".join(str(target.get(key, "")) for key in ("name", "inputName", "placeholder"))
        search = ("fill" in fact["actions"] and (target["role"] == "searchbox" or fact["type"] == "search"
                  or str(target.get("inputName", "")).lower() == "q" or fact.get("form", {}).get("role") == "search"
                  or re.search(r"search|query|keyword|find", descriptor, re.I)))
        if search:
            steps = [{"target": target, "action": "fill", "value": {"$input": "query"}}]
            if "submit" in fact["actions"]:
                steps.append({"target": target, "action": "submit"})
            procedures.append({"kind": "search-first", "steps": steps,
                "completion": "Inspect the new result text and controls; a generic changed-state receipt is not task completion"})
        elif target["role"] == "combobox":
            procedures.append({"kind": "filter", "target": target, "options": fact.get("options", []),
                "completion": "Choose an observed enabled option by its actual value, then verify applied value and result constraints"})
        elif re.search(r"^(next|previous)(?:\b|$)|page\s*\d", target["name"], re.I):
            procedures.append({"kind": "pagination", "target": target,
                "completion": "Record visited URLs/revisions and stop on a repeated page; use only observed enabled page controls"})
    return procedures


def site_manual(service, args, *, owner=False):
    """Learn on first visit, persist under selected root, validate before reuse."""
    from .neyvia_browser import fail
    from .cl.manuals import manual_to_cl
    observation = fresh_observation(service, args["tabId"], owner)
    if observation.get("authentication", {}).get("required"):
        fail("auth_required", "Paul must sign in; site manuals do not learn access walls")
    parsed = urlsplit(observation["url"])
    origin = parsed.scheme + "://" + parsed.netloc.lower()
    page = parsed.path or "/"
    facts = _structure(observation)
    fingerprint = hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = service.directory / "site-manuals" / (hashlib.sha256(origin.encode()).hexdigest()[:24] + ".json")
    with service.lock:
        stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema": "neyvia.browser-site.v1", "origin": origin, "pages": {}, "quarantine": []}
        previous = stored["pages"].get(page)
        reused = previous is not None and previous["fingerprint"] == fingerprint and not observation.get("truncated")
        changed = previous is not None and not reused
        if changed:
            stored["quarantine"].append({"page": page, "fingerprint": previous["fingerprint"], "at": time.time(),
                                         "reason": "Fresh observed control structure differs; prior procedures demoted"})
            stored["quarantine"] = stored["quarantine"][-24:]
        procedures = _procedures(facts)
        stored["pages"][page] = {"fingerprint": fingerprint, "controls": facts, "procedures": procedures, "validatedAt": time.time()}
        while len(stored["pages"]) > 32:
            stored["pages"].pop(next(iter(stored["pages"])))
        # Bound cached control descriptions even on pathological public pages.
        if len(json.dumps(stored, ensure_ascii=False).encode()) > 1_000_000:
            stored["pages"] = {page: stored["pages"][page]}
        atomic_write_json(path, stored)
    compiled = []
    for candidate in sorted((service.directory / "compiled").glob("*.json"))[:96]:
        record = json.loads(candidate.read_text(encoding="utf-8"))
        if record.get("origin") == origin and record.get("admission") and not record.get("quarantined"):
            compiled.append({"name": record["name"], "checks": record["checks"], "steps": record["steps"],
                             "inputBindings": record.get("inputBindings", {}),
                             "admission": record["admission"], "modelCalls": 0})
    document = _document(origin, facts, procedures, compiled)
    cl = manual_to_cl(document)
    return {"ok": True, "tabId": args["tabId"], "origin": origin, "page": page,
            "revision": observation["revision"], "fingerprint": fingerprint,
            "status": "reused" if reused else "relearned" if changed else "learned",
            "validation": {"fresh": True, "structureMatches": reused, "priorFactsDemoted": changed,
                           "ready": observation.get("readyState") == "complete", "projectionTruncated": bool(observation.get("truncated"))},
            "controls": facts, "procedures": procedures, "compiledProcedures": compiled, "cl": cl, "observation": observation,
            "trust": "untrusted-data", "quarantined": stored["quarantine"][-4:]}


def _document(origin, facts, procedures, compiled=()):
    from .neyvia_browser import DEFINITIONS
    schemas = {"neyvia." + name: {"type": "object", "properties": props, "required": required}
               for name, _, props, required in DEFINITIONS if name in {"browser.observe", "browser.action.batch", "browser.script.run"}}
    chapter = {"title": "Observed controls for " + origin, "state": {}, "actions": {}, "checks": {},
               "procedures": {}, "judge": {}, "pitfalls": [], "frontier": [], "guidance": []}
    tab_inputs = {"type": "object", "properties": {"tabId": {"type": "string"}}, "required": ["tabId"]}
    chapter["state"]["page"] = {"tool": "neyvia.browser.observe", "args": {"tabId": {"$input": "tabId"}},
        "inputs": tab_inputs, "shape": {"type": "object", "required": ["revision", "elements", "text"]}}
    for name in ("browser.observe", "browser.action.batch", "browser.script.run"):
        chapter["actions"][name] = {"tool": "neyvia." + name, "schema": "neyvia." + name,
            "returns": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
            "pre": "Owner grant, fresh revision and exact unique observed control identity for effects",
            "effect": "Observe actual shared tab" if name.endswith("observe") else "Replay admitted procedure with fresh controls and independent goals" if name.endswith("script.run") else "Execute bounded observed semantic actions once; stop on first failure",
            "reversible": name.endswith("observe")}
    chapter["checks"]["ready"] = {"tool": "neyvia.browser.observe", "args": {"tabId": {"$input": "tabId"}},
        "expect": {"op": "eq", "path": "readyState", "value": "complete"}}
    chapter["procedures"]["observe-before-action"] = {"goal": "Revalidate actual controls before using remembered facts",
        "inputs": tab_inputs, "steps": [{"action": "browser.observe", "args": {"tabId": {"$input": "tabId"}}, "save": "page", "check": "ready"}]}
    batch_inputs = schemas["neyvia.browser.action.batch"]
    chapter["procedures"]["grounded-batch"] = {"goal": "Run actual named controls with a fresh effect receipt after every step",
        "inputs": batch_inputs, "steps": [{"action": "browser.action.batch", "args": {key: {"$input": key} for key in batch_inputs["required"]}, "save": "batch"}]}
    for procedure in compiled:
        chapter["checks"]["compiled-goal"] = {"tool": "neyvia.browser.observe", "args": {"tabId": {"$input": "tabId"}},
            "expect": {"path": "text", "op": "contains", "value": {"$input": "expectedText"}}}
        chapter["procedures"]["compiled-" + procedure["name"]] = {
            "goal": "Replay a first-success admitted same-origin flow; stop immediately when its fresh goal passes",
            "inputs": {"type": "object", "properties": {"tabId": {"type": "string"}, "inputs": {"type": "object", "maxProperties": 24}, "expectedText": {"type": "string"}}, "required": ["tabId", "inputs", "expectedText"]},
            "steps": [{"action": "browser.script.run", "args": {"tabId": {"$input": "tabId"}, "name": procedure["name"], "inputs": {"$input": "inputs"}}, "save": "replay", "check": "compiled-goal"}]}
    for index, procedure in enumerate(procedures):
        if procedure["kind"] != "search-first" or len(procedure["steps"]) < 2:
            continue
        chapter["procedures"]["site-search-" + str(index)] = {
            "goal": "Search the observed associated form first, with actual single-dispatch fill and submit effect checks",
            "inputs": {"type": "object", "properties": {"tabId": {"type": "string"}, "revision": {"type": "string"},
                         "query": {"type": "string", "maxLength": 20000}}, "required": ["tabId", "revision", "query"]},
            "steps": [{"action": "browser.action.batch", "args": {"tabId": {"$input": "tabId"},
                        "revision": {"$input": "revision"}, "steps": procedure["steps"]}, "save": "searched"}]}
    chapter["judge"]["complete"] = {"question": "Does observed page evidence satisfy every user constraint?",
        "options": ["complete", "continue", "blocked"], "constraints": "Require source provenance, full extraction and requested formatting; never infer completion from a click receipt"}
    chapter["guidance"] = ["Learned controls (no stored IDs, values, result text or routes): " + json.dumps(facts, ensure_ascii=False, separators=(",", ":")),
                           "Search first when an observed search control exists: " + json.dumps(procedures, ensure_ascii=False, separators=(",", ":")),
                           "For tables preserve row/column correspondence. Check filters, pagination and truncation before extracting an answer."]
    chapter["pitfalls"] = [{"failure": "Remembered structure is stale or a semantic target is ambiguous",
                            "recovery": "Quarantine stale facts, relearn actual controls and escalate ambiguous intent; never guess a selector or replay a click"}]
    chapter["frontier"] = ["Observed control structure does not establish search-result quality, login access or general planning accuracy"]
    return {"schema": "neyvia.manual.v1", "id": "browser-site-" + hashlib.sha256(origin.encode()).hexdigest()[:16],
            "kind": "environment", "schemas": schemas, "chapters": {"site": chapter}}


def action_batch(service, args, *, owner=False, initial_observation=None):
    from .neyvia_browser import BrowserError, fail
    from .browser_verification import validate_expect
    steps = args.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        fail("invalid_batch", "Supply one to eight typed semantic actions")
    # Validate the entire input before the first real effect.
    from jsonschema import Draft202012Validator, ValidationError
    from .neyvia_browser import BATCH_PROPERTIES
    try:
        Draft202012Validator({"type": "object", "properties": BATCH_PROPERTIES,
                              "required": ["tabId", "revision", "steps"], "additionalProperties": False}).validate(args)
    except ValidationError:
        fail("invalid_batch", "Batch input does not satisfy the typed bounded action schema")
    for step in steps:
        validate_expect(step)
    # Compiled execution already acquired this exact snapshot for its goal
    # check. Avoid a redundant observation; every dispatched action still
    # checks the fresh revision in the actual page executor.
    observation = initial_observation if initial_observation is not None else fresh_observation(service, args["tabId"], owner)
    if observation["revision"] != args["revision"]:
        fail("stale_projection", "Batch initial revision differs from the fresh page")
    receipts = []
    for index, step in enumerate(steps):
        action_id = None
        try:
            if observation.get("authentication", {}).get("required"):
                fail("auth_required", "Paul must sign in before further actions")
            target = resolve_target(observation, step["target"], step["action"])
            request = {"tabId": args["tabId"], "revision": observation["revision"], "element": target["id"],
                       **{key: step[key] for key in ("action", "value", "expect") if key in step}}
            if step["action"] == "drag":
                destination = step.get("destination")
                if not isinstance(destination, dict) or set(destination) - set(TARGET_SCHEMA["properties"]):
                    fail("invalid_target", "Drag requires a fresh semantic destination")
                matches = [row for row in observation.get("elements", [])
                           if not row.get("secret") and row.get("enabled", True)
                           and all(row.get(key) == value for key, value in destination.items())]
                if len(matches) != 1:
                    fail("ambiguous_target", "Drag destination must resolve uniquely in the current observation")
                request["destination"] = matches[0]["id"]
            started = time.monotonic()
            result = service.request("action", request, owner=owner)
            if result.get("actionId"):
                action_id = result["actionId"]
                result = service.request("wait", {"actionId": result["actionId"], "timeoutMs": 10000}, owner=owner).get("result", {})
            verification = result.get("verification", {})
            receipts.append({"index": index, "action": step["action"], "target": step["target"],
                             "actionId": action_id, "verification": verification, "latencyMs": result.get("latencyMs"), "durationMs": round((time.monotonic() - started) * 1000, 2)})
            observation = result.get("observation") or fresh_observation(service, args["tabId"], owner)
            if verification.get("verified") is not True:
                fail("effect_unconfirmed", "Stop batch; the single dispatched effect did not pass its independent check")
        except (BrowserError, ValueError, KeyError) as exc:
            failed = getattr(exc, "receipt", None)
            if action_id and not failed:
                row = service.request("action.get", {"actionId": action_id}, owner=owner)
                native_result = row.get("result") or {}
                failed = {"verification": native_result.get("verification", {}), "observation": native_result.get("observation")}
            if failed:
                if failed.get("observation"):
                    observation = failed["observation"]
                receipts.append({"index": index, "action": step["action"], "target": step["target"],
                                 "status": failed.get("status", "failed"), "actionId": failed.get("actionId", action_id),
                                 "nativeStatus": failed.get("nativeStatus"), "verification": failed.get("verification", {}), "replaySafe": False})
            return {"ok": False, "status": "stopped", "completed": index, "failedStep": index,
                    "error": {"code": getattr(exc, "code", "invalid_request"), "message": str(exc)},
                    "receipts": receipts, "observation": observation, "replaySafe": False}
    return {"ok": True, "status": "done", "completed": len(steps), "receipts": receipts, "observation": observation,
            "verification": {"verified": True, "check": "every_single_dispatch_effect_verified"}, "taskCompletion": False}
