"""One strict notation for manuals; no eval, import paths or untyped procedure calls."""
from __future__ import annotations

# evolve-helper: skip-repeated-validation
import threading as _evolve_threading
_EVOLVE_VALIDATED = {}
_EVOLVE_VALIDATED_MAX = 4096
_EVOLVE_VALIDATED_LOCK = _evolve_threading.Lock()
def _evolve_once(label, call, *args):
    """Skip a repeated call of a PURE validator on an identical JSON input in this process.

    Purity assumption: the outcome depends only on the JSON value of the arguments, the call
    has no side effects, success returns None and failure raises. Only successes are kept;
    errors and non-None results are never remembered. Bounded LRU of SHA-256 digests.
    """
    import hashlib as _hashlib
    import json as _json
    try:
        payload = _json.dumps([label, args], sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return call(*args)
    key = _hashlib.sha256(payload.encode('utf-8')).digest()
    with _EVOLVE_VALIDATED_LOCK:
        if key in _EVOLVE_VALIDATED:
            _EVOLVE_VALIDATED[key] = _EVOLVE_VALIDATED.pop(key)
            return None
    result = call(*args)
    if result is None:
        with _EVOLVE_VALIDATED_LOCK:
            _EVOLVE_VALIDATED[key] = True
            while len(_EVOLVE_VALIDATED) > _EVOLVE_VALIDATED_MAX:
                del _EVOLVE_VALIDATED[next(iter(_EVOLVE_VALIDATED))]
    return result

import json
from jsonschema import Draft202012Validator

def obj(properties, required=None):
    return {"type": "object", "properties": properties, "required": list(properties) if required is None else required, "additionalProperties": False}

S = {"type": "string", "minLength": 1}
SCHEMA = {"type": "object"}
MAP = lambda schema: {"type": "object", "additionalProperties": schema}
ARRAY = lambda schema: {"type": "array", "items": schema}
CALL = {"tool": S, "args": SCHEMA}
RULE = obj({"path": {"oneOf": [{"type": "string"}, {"type": "array"}]}, "op": {"enum": ["exists", "eq", "contains", "schema"]}, "value": {}, "schema": SCHEMA}, ["path", "op"])
STATE = obj({**CALL, "inputs": SCHEMA, "shape": SCHEMA})
ACTION = obj({"tool": S, "schema": S, "returns": SCHEMA, "pre": S, "effect": S, "reversible": {"type": "boolean"}})
CHECK = obj({**CALL, "expect": RULE})
WHEN = obj({"judge": S, "option": S})
STEP = {"oneOf": [obj({"judge": S}), obj({"action": S, "args": SCHEMA, "save": S, "check": S, "when": WHEN}, ["action", "args", "save"])]}
PROCEDURE = obj({"goal": S, "inputs": SCHEMA, "steps": {**ARRAY(STEP), "minItems": 1}})
JUDGE = obj({"question": S, "options": {**ARRAY(S), "minItems": 2, "uniqueItems": True}, "constraints": S,
             "kind": {"enum": ["human", "model"]}, "evidence": {**ARRAY({"enum": ["screenshot", "artifact"]}), "minItems": 1, "uniqueItems": True}},
            ["question", "options", "constraints"])
CHAPTER = obj({"title": S, "state": MAP(STATE), "actions": MAP(ACTION), "checks": MAP(CHECK), "procedures": MAP(PROCEDURE), "judge": MAP(JUDGE),
               "pitfalls": ARRAY(obj({"failure": S, "recovery": S})), "frontier": ARRAY(S), "guidance": ARRAY(S)})
PROOF = obj({"id": S, "phase": {"enum": ["pre", "post", "invariant", "goal"]}, "claim": S,
             "checkedAt": {**ARRAY(S), "minItems": 1}, "impact": ARRAY(S)})
PROOFS = obj({"area": S, "contracts": {**ARRAY(PROOF), "minItems": 1}, "manifests": ARRAY(S),
              "startup": obj({"runner": S, "scratchRootRequired": {"const": True}, "procedures": ARRAY(S)})}, ["area", "contracts"])
MANUAL_SCHEMA = obj({"schema": {"const": "neyvia.manual.v1"}, "id": S, "kind": {"enum": ["environment", "workflow"]}, "schemas": MAP(SCHEMA), "chapters": {**MAP(CHAPTER), "minProperties": 1}, "proofs": PROOFS},
                    ["schema", "id", "kind", "schemas", "chapters"])

def validate_structure(data):
    Draft202012Validator(MANUAL_SCHEMA).validate(data)
    for schema in data["schemas"].values():
        _evolve_once('Draft202012Validator.check_schema', Draft202012Validator.check_schema, schema)
    for chapter in data["chapters"].values():
        for judge in chapter["judge"].values():
            if judge.get("kind", "human") == "model" and not judge.get("evidence"):
                raise ValueError("A model judgment must declare the evidence (screenshot/artifact) it is bound to")
            if judge.get("kind", "human") == "human" and "evidence" in judge:
                raise ValueError("Only a model judgment binds evidence; a human decision does not")
        for section in ("state", "actions", "procedures"):
            for row in chapter[section].values():
                for key in ("schema", "shape", "inputs", "returns"):
                    if key in row and isinstance(row[key], dict):
                        _evolve_once('Draft202012Validator.check_schema', Draft202012Validator.check_schema, row[key])
        for row in chapter["checks"].values():
            rule = row["expect"]
            if rule["op"] == "schema":
                Draft202012Validator.check_schema(rule["schema"])
            elif rule["op"] != "exists" and "value" not in rule:
                raise ValueError("Comparison check needs an expected value")

def schema_at(schema, path):
    for key in path.split(".") if path else []:
        if schema.get("type") == "array":
            if not key.isdigit():
                raise ValueError("Array result reference needs an index")
            schema = schema["items"]
        else:
            schema = schema.get("properties", {})[key]
    return schema

def template(arguments, target, inputs, results):
    """Check literals and typed references without executing an observer or action."""
    if isinstance(arguments, dict) and set(arguments) in ({"$input"}, {"$result"}, {"$path"}):
        if "$input" in arguments or "$path" in arguments:
            key = arguments.get("$input", arguments.get("$path"))
            source = inputs.get("properties", {}).get(key)
            if source is None or (key not in inputs.get("required", []) and "default" not in source):
                raise ValueError("Procedure reference requires a required input or declared default: " + key)
            if key not in inputs.get("required", []):
                # Both CL and typed runners materialize these defaults before
                # executing steps. Prove the same value here without acting.
                Draft202012Validator(source).validate(source["default"])
        else:
            name, _, path = arguments["$result"].partition(".")
            source = schema_at(results[name], path)
        # A constant source has exactly one admitted value. Prove that value
        # against both schemas rather than requiring identical range fields.
        if "const" in source:
            Draft202012Validator(source).validate(source["const"])
            Draft202012Validator(target).validate(source["const"])
            return
        # A source must prove all target restrictions, not merely share a base type.
        for key, value in target.items():
            if key not in {"description", "title", "default", "$schema", "examples"} and source.get(key) != value:
                raise ValueError("Reference does not satisfy target schema: " + json.dumps(arguments))
        return
    if isinstance(arguments, dict):
        Draft202012Validator({**target, "properties": {key: {} for key in target.get("properties", {})}}).validate(arguments)
        for key, value in arguments.items():
            template(value, target.get("properties", {}).get(key, {}), inputs, results)
    elif isinstance(arguments, list):
        Draft202012Validator({**target, "items": {}}).validate(arguments)
        for value in arguments:
            template(value, target.get("items", {}), inputs, results)
    else:
        Draft202012Validator(target).validate(arguments)

def validate_grounding(data, registry, *, canonical_controls=None):
    validate_structure(data)
    safe_manual_reads = {"neyvia.manual.index", "neyvia.manual.patches", "neyvia.manual.project", "neyvia.manual.versions", "neyvia.manual.compiled"}
    # Editing a selected manual is a bounded action. Running another manual from
    # inside a procedure is recursive execution and must remain forbidden.
    nonrecursive_manual_edits = {"neyvia.manual.frontier", "neyvia.manual.demote", "neyvia.manual.patch.apply"}
    for chapter_name, chapter in data["chapters"].items():
        schemas = {}
        for section in ("state", "actions", "checks"):
            for name, row in chapter[section].items():
                tool = row["tool"]
                # Action vocabulary may document manual controls. Nested execution
                # is checked on actual steps; observer/check recursion stays forbidden.
                if section != "actions" and tool.startswith("neyvia.manual.") and tool not in safe_manual_reads:
                    raise ValueError("Recursive manual execution is forbidden")
                live = registry.describe(tool)  # missing tool fails, never silently skipped
                if tool not in registry._handlers:
                    raise ValueError("Tool has no callable handler: " + tool)
                schemas[tool] = live["inputSchema"]
                if section == "actions" and data["schemas"][row["schema"]] != live["inputSchema"]:
                    raise ValueError("Action schema differs from live tool: " + tool)
                if section in {"state", "checks"}:
                    if live["mutability_class"] not in {"read", "none"}:
                        raise ValueError("Observer must be observational: " + tool)
                if section == "state":
                    template(row["args"], live["inputSchema"], row["inputs"], {})
        for procedure_name, procedure in chapter["procedures"].items():
            canonical_chapter = (canonical_controls or {}).get('chapters', {}).get(chapter_name, {})
            retained_control = (data['id'] == (canonical_controls or {}).get('id') == 'manuals-next'
                and canonical_chapter.get('procedures', {}).get(procedure_name) == procedure)
            results, judges, conditional = {}, set(), {}
            for step in procedure["steps"]:
                if "judge" in step:
                    if step["judge"] not in chapter["judge"] or step["judge"] in judges:
                        raise ValueError("Judge must be declared and occur once")
                    judges.add(step["judge"])
                    continue
                if step.get("when"):
                    branch = step["when"]
                    if branch["judge"] not in judges or branch["option"] not in chapter["judge"][branch["judge"]]["options"]:
                        raise ValueError("Branch must follow its judge and use an offered option")
                action = chapter["actions"][step["action"]]
                preserved_control = (retained_control
                    and canonical_chapter.get('actions', {}).get(step['action']) == action
                    and (not step.get('check') or canonical_chapter.get('checks', {}).get(step['check']) == chapter['checks'][step['check']]))
                if (action["tool"].startswith("neyvia.manual.")
                        and action["tool"] not in safe_manual_reads | nonrecursive_manual_edits
                        and not preserved_control):
                    raise ValueError("Recursive manual execution is forbidden")
                referenced = [step["args"]]
                if step.get("check"):
                    referenced += [chapter["checks"][step["check"]]]
                encoded = json.dumps(referenced)
                for name, condition in conditional.items():
                    if ('"$result": "' + name + '.') in encoded and step.get("when") != condition:
                        raise ValueError("Result reference may come from a skipped branch: " + name)
                template(step["args"], data["schemas"][action["schema"]], procedure["inputs"], results)
                if step["save"] in results:
                    raise ValueError("Procedure result names must be unique")
                results[step["save"]] = action["returns"]
                if step.get("when"):
                    conditional[step["save"]] = step["when"]
                if step.get("check"):
                    check = chapter["checks"][step["check"]]
                    template(check["args"], schemas[check["tool"]], procedure["inputs"], results)
                    def references(value):
                        if isinstance(value, dict):
                            if set(value) in ({"$input"}, {"$result"}, {"$path"}):
                                template(value, {}, procedure["inputs"], results)
                            else:
                                for item in value.values():
                                    references(item)
                        elif isinstance(value, list):
                            for item in value:
                                references(item)
                    references(check["expect"])
