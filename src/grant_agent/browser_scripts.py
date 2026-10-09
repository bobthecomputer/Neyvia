"""First-success browser procedures, parameterized and replayed without a model.

Only verified executions enter the selected-root registry. Content remains
untrusted; callers supply explicit bounded goal predicates, never a 'done' bit.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from urllib.parse import parse_qsl, quote, quote_plus, urlsplit

from .browser_site_manuals import action_batch, fresh_observation
from .browser_verification import validate_expect
from .durability import atomic_write_json


PROPERTIES = {"tabId": {"type": "string"}, "name": {"type": "string", "pattern": "^[a-zA-Z0-9_-]{1,80}$"},
              "inputs": {"type": "object", "maxProperties": 24},
              "steps": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "object"}},
              "checks": {"type": "array", "minItems": 1, "maxItems": 12, "items": {"type": "object"}}}


def bind(value, inputs):
    if isinstance(value, dict):
        if set(value) == {"$input"}:
            result = inputs[value["$input"]]
            if not isinstance(result, str) or len(result) > 20000:
                raise ValueError("Procedure inputs must be bounded strings")
            return result
        return {key: bind(item, inputs) for key, item in value.items()}
    if isinstance(value, list):
        return [bind(item, inputs) for item in value]
    return value


def goal(observation, checks):
    results = []
    for expected in checks:
        validate_expect({"expect": expected})
        actual = observation
        for key in expected["path"].split("/")[1:]:
            key = key.replace("~1", "/").replace("~0", "~")
            if isinstance(actual, dict):
                actual = actual.get(key)
            elif isinstance(actual, list) and key.isdigit() and str(int(key)) == key and int(key) < len(actual):
                actual = actual[int(key)]
            else:
                actual = None
        passed = actual == expected["equals"] if "equals" in expected else isinstance(actual, str) and expected["contains"] in actual
        results.append({"predicate": expected, "passed": passed})
    return {"verified": bool(results) and all(item["passed"] for item in results), "checks": results}


def observed_input_bindings(template, inputs, observation):
    """Retain proved URL parameter names, never the successful query values."""
    filled = [step.get("value", {}).get("$input") for step in template["steps"]
              if step.get("action") == "fill" and isinstance(step.get("value"), dict)]
    parameters = parse_qsl(urlsplit(observation["url"]).query, keep_blank_values=True)
    bindings = {}
    for check in template["checks"]:
        variable = check.get("contains", {})
        if check.get("path") != "/url" or not isinstance(variable, dict) or set(variable) != {"$input"}:
            continue
        output = variable["$input"]
        candidates = [(source, key, value) for source in filled for key, value in parameters
                      if source in inputs and inputs[source] == value and output != source
                      and inputs.get(output) in {key + "=" + quote(value, safe=""), key + "=" + quote_plus(value)}]
        if len(candidates) == 1:
            source, key, _ = candidates[0]
            bindings[output] = {"urlQueryParameter": key, "sourceInput": source,
                                "encoding": "percent" if "%20" in inputs[output] else "form"}
    return bindings


def execute(service, op, args, *, owner=False):
    from .neyvia_browser import fail
    began = time.monotonic()
    name = args.get("name", "")
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
        fail("invalid_script", "Supply a bounded procedure name")
    path = service.directory / "compiled" / (name + ".json")
    inputs = args.get("inputs", {})
    if not isinstance(inputs, dict) or len(inputs) > 24:
        fail("invalid_script", "Supply bounded typed input values")
    observation = fresh_observation(service, args["tabId"], owner)
    if observation.get("authentication", {}).get("required"):
        fail("auth_required", "Owner authentication is required; no procedure can bypass it")
    origin = urlsplit(observation["url"])
    scope = f"{origin.scheme}://{origin.netloc}"
    if op == "script.learn":
        # Existing tab-grant/action authorization is enforced by action_batch.
        # Admission itself is a reversible selected-root artifact write.
        template = {"schema": "neyvia.browser-script@1", "name": name, "origin": scope,
                    "steps": args.get("steps"), "checks": args.get("checks")}
        if not isinstance(template["steps"], list) or not 1 <= len(template["steps"]) <= 8 or not isinstance(template["checks"], list) or not 1 <= len(template["checks"]) <= 12:
            fail("invalid_script", "Supply one to eight steps and one to twelve independent goal checks")
        if any("id" in step.get("target", {}) or "id" in step.get("destination", {}) for step in template["steps"] if isinstance(step, dict)):
            fail("invalid_script", "Compiled procedures need durable semantic targets; transient projection IDs cannot be stored")
        if len(json.dumps(template).encode()) > 100000:
            fail("invalid_script", "Procedure is oversized")
    else:
        if not path.is_file():
            fail("script_missing", "No verified first-success procedure exists")
        template = json.loads(path.read_text(encoding="utf-8"))
        if template.get("origin") != scope:
            fail("script_scope", "Procedure belongs to another explicitly granted origin")
        if template.get("quarantined"):
            fail("script_quarantined", "Relearn changed controls before replay")
    try:
        steps, checks = bind(template["steps"], inputs), bind(template["checks"], inputs)
        for expected in checks:
            validate_expect({"expect": expected})
    except (ValueError, KeyError, TypeError) as error:
        fail("invalid_script", str(error))
    check = goal(observation, checks)
    result = {"ok": True, "receipts": [], "observation": observation}
    early = op == "script.run" and check["verified"]
    if not early:
        result = action_batch(service, {"tabId": args["tabId"], "revision": observation["revision"], "steps": steps}, owner=owner, initial_observation=observation)
        observation = result["observation"]
        check = goal(observation, checks)
    accepted = result.get("ok") is True and check["verified"]
    if op == "script.learn" and accepted:
        template["inputBindings"] = observed_input_bindings(template, inputs, observation)
        template["admission"] = {"at": time.time(), "everyEffectVerified": True, "goalVerified": True,
                                 "observationRevision": observation["revision"],
                                 "procedureSha256": hashlib.sha256(json.dumps(template, sort_keys=True).encode()).hexdigest()}
        atomic_write_json(path, template)
    elif op == "script.run" and not accepted:
        # Never replay a partially dispatched procedure automatically.
        template["quarantined"] = {"at": time.time(), "status": result.get("status"), "goal": check,
                                   "replaySafe": False}
        atomic_write_json(path, template)
    return {"ok": accepted, "status": "compiled" if op == "script.learn" and accepted else "done" if accepted else "frontier",
            "name": name, "compiled": accepted, "earlyExit": early, "modelCalls": 0, "tokens": 0,
            "paidModelCostUSD": 0, "durationMs": round((time.monotonic() - began) * 1000, 2),
            "verification": check, "receipts": result.get("receipts", []), "observation": observation,
            "error": result.get("error"), "replaySafe": False if not accepted else None}
