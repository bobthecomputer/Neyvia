"""Nogoods bound to durable failures and typed, explicitly selected recovery recipes."""
from __future__ import annotations
import hashlib
import json
import re
import uuid
from jsonschema import Draft202012Validator
from .durability import atomic_write_json
from .manual_state import encoded


def failed_run(root, identity):
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("Invalid run ID")
    row = json.loads((root / "manual-runs" / (identity + ".json")).read_text(encoding="utf-8"))
    if row["status"] != "failed":
        raise ValueError("Recovery requires an observed failed run")
    return row


def signature(failure):
    binding = {key: failure[key] for key in ("id", "sha256", "chapter", "procedure", "nextStep", "error", "inputs")}
    binding["scopeTools"] = failure.get("scopeTools")
    return hashlib.sha256(encoded(binding).encode()).hexdigest()


def recipes_for(root, failure):
    return [{"recipeId": row["recipeId"], "procedure": row["procedure"], "chapter": row["chapter"]}
            for path in (root / "manual-recoveries").glob("*.json")
            if (row := json.loads(path.read_text(encoding="utf-8")))["failureSignature"] == signature(failure)]


def call(service, name, args, registry, dispatch):
    from .neyvia_manuals import get_manual, chapter_entry, validate, run, _LOCK, execution_lock
    root = service.bus.root / ".neyvia"
    failure = failed_run(root, args["runId"])
    _, digest, data = get_manual(failure["id"], root)
    if digest != failure["sha256"]:
        raise ValueError("Failure belongs to an obsolete manual version")
    if name == "manual.recovery.bind":
        validate(data, registry)
        chapter, _, procedure = chapter_entry(data, args["chapter"], "procedures", args["procedure"])
        Draft202012Validator(procedure["inputs"]).validate(args["inputs"])
        recipe = {"recipeId": uuid.uuid4().hex, "failureSignature": signature(failure), "sourceRunId": failure["runId"],
                  "id": failure["id"], "sha256": digest, "chapter": chapter, "procedure": args["procedure"], "inputs": args["inputs"],
                  "scopeTools": failure.get("scopeTools"), "status": "bound", "policy": "Explicit selection; new run; original gateway/checks"}
        atomic_write_json(root / "manual-recoveries" / (recipe["recipeId"] + ".json"), recipe)
        return {"ok": True, **recipe}
    if not re.fullmatch(r"[a-f0-9]{32}", args["recipeId"]):
        raise ValueError("Invalid recipe ID")
    recipe_path = root / "manual-recoveries" / (args["recipeId"] + ".json")
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    if recipe["failureSignature"] != signature(failure):
        raise ValueError("Recovery recipe does not match this failure")
    call_args = {"id": recipe["id"], "chapter": recipe["chapter"], "procedure": recipe["procedure"], "inputs": recipe["inputs"]}
    original = recipe.get("scopeTools")
    requested = args.get("scopeTools")
    if original is not None or requested is not None:
        left = original if original is not None else requested
        right = requested if requested is not None else original
        call_args["scopeTools"] = sorted(set(left) & set(right))
    grounding = validate(data, registry)
    _, _, procedure = chapter_entry(data, recipe["chapter"], "procedures", recipe["procedure"])
    Draft202012Validator(procedure["inputs"]).validate(recipe["inputs"])
    if "scopeTools" in call_args:
        nested = next(row["tools"] for row in grounding["procedures"] if row["chapter"] == recipe["chapter"] and row["procedure"] == recipe["procedure"])
        if any(tool not in call_args["scopeTools"] for tool in nested):
            raise PermissionError("Recovery contains a tool outside the caller's nested-tool restriction")
    # Reserve an attempt before executing effects. A crash or a concurrent caller
    # must reconcile this reservation rather than automatically repeat a repair.
    with _LOCK, execution_lock(root):
        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        previous = recipe.setdefault("attempts", {}).get(failure["runId"])
        if previous:
            if previous.get("runId"):
                retained = json.loads((root / "manual-runs" / (previous["runId"] + ".json")).read_text(encoding="utf-8"))
                return {"ok": retained["status"] in {"completed", "judge"}, **retained, "replayed": True,
                        "recipeId": recipe["recipeId"], "recoveredFailureRunId": failure["runId"]}
            return {"ok": False, "status": "blocked", "error": "Recovery already executing or interrupted; reconcile it before another attempt", "recipeId": recipe["recipeId"]}
        recipe["attempts"][failure["runId"]] = {"status": "executing"}
        atomic_write_json(recipe_path, recipe)
    result = run(service, call_args, registry, dispatch)
    with _LOCK, execution_lock(root):
        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        recipe.update(status="verified" if result["status"] == "completed" else "unverified", recoveryRunId=result.get("runId"))
        recipe["attempts"][failure["runId"]] = {"status": result["status"], "runId": result.get("runId")}
        atomic_write_json(recipe_path, recipe)
    return {**result, "recipeId": recipe["recipeId"], "recoveredFailureRunId": failure["runId"]}
