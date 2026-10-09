"""Executable workflow adherence; measurements belong to host receipts, not prose."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

STAGES = {
    "hill-climb": ("baseline", "change", "measure", "decision", "log", "stop"),
    "creativity": ("reframe", "diverge", "criteria", "choose"),
    "critique-review": ("plan", "attack", "verify", "decision"),
    "efficiency": ("paths", "attempt", "measure", "log"),
    "research": ("question", "prior-art", "claim", "test", "result"),
    "design": ("reference", "details", "render", "critique", "decision"),
}
REPO = Path(__file__).resolve().parents[2]
INPUT_SCHEMA = {"type": "object", "properties": {
    "manual": {"type": "string", "enum": list(STAGES)}, "report": {"type": "object"},
    "evidence": {"type": "object", "additionalProperties": {"type": "object", "properties": {
        "path": {"type": "string", "minLength": 1}, "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}},
        "required": ["path", "sha256"], "additionalProperties": False}},
    "outcomeQuality": {"type": "number", "minimum": 0, "maximum": 1},
    "tokens": {"type": "integer", "minimum": 0}}, "required": ["manual", "report", "evidence", "outcomeQuality", "tokens"]}


def validate_workflow(manual_id, report, outcome_quality=0.0, tokens=1, evidence=None):
    """Score content and order. External callers independently judge outcome quality.

    Evidence is a host-owned mapping of receipt IDs to actual measurements. Text
    models cannot create authority by writing a receipt ID in their answer.
    """
    if manual_id not in STAGES:
        raise ValueError("Unknown workflow manual")
    if type(tokens) is not int or tokens < 0 or type(outcome_quality) not in (int, float) or not math.isfinite(outcome_quality) or not 0 <= outcome_quality <= 1:
        raise ValueError("Host token count and independently judged quality required")
    evidence = evidence if isinstance(evidence, dict) else {}
    events = report.get("events", []) if isinstance(report, dict) else []
    events = events if isinstance(events, list) else []
    errors, gates = [], []

    def gate(condition, message):
        gates.append(bool(condition))
        if not condition:
            errors.append(message)

    def text(value):
        return isinstance(value, str) and len(value.strip()) >= 3

    def strings(value, minimum=1):
        return isinstance(value, list) and len(value) >= minimum and all(text(v) for v in value)

    stages = [e.get("stage") for e in events if isinstance(e, dict)]
    required = STAGES[manual_id]
    gate(all(stages.count(s) == 1 for s in required) and [s for s in stages if s in required] == list(required), "Required stages must occur once in chronological order")
    rows = {e.get("stage"): e.get("data", {}) for e in events if isinstance(e, dict) and isinstance(e.get("data"), dict)}
    row = lambda stage: rows.get(stage, {})

    def receipt(stage, field="receipt"):
        identifier = row(stage).get(field)
        found = evidence.get(identifier) if isinstance(identifier, str) else None
        gate(isinstance(found, dict) and bool(found), stage + " needs a real host receipt")
        return found if isinstance(found, dict) else {}

    if manual_id == "hill-climb":
        baseline, measured = receipt("baseline"), receipt("measure")
        change, decision = row("change"), row("decision")
        gate(strings(change.get("changes")) and len(change["changes"]) == 1 and text(change.get("candidate")), "Change exactly one mechanism")
        comparable = text(baseline.get("checkHash")) and baseline.get("checkHash") == measured.get("checkHash")
        numeric = all(type(r.get("value")) in (int, float) and math.isfinite(r["value"]) for r in (baseline, measured))
        gate(comparable and numeric, "Measure against the identical frozen check")
        noise = baseline.get("noise", 0)
        noise_ok = type(noise) in (int, float) and math.isfinite(noise) and noise >= 0
        gate(noise_ok, "Noise threshold must be finite and nonnegative")
        better = comparable and numeric and noise_ok and measured["value"] > baseline["value"] + noise
        gate(type(decision.get("keep")) is bool and decision.get("keep") == better and text(decision.get("reason")), "Keep only beyond frozen noise; otherwise reject")
        logged = receipt("log")
        gate(logged.get("kind") == "research-ledger" and logged.get("measurement") == row("measure").get("receipt"), "Log must link the measured receipt in the research ledger")
        gate(text(row("stop").get("rule")), "Explicit stop rule required")
    elif manual_id == "creativity":
        reframed = row("reframe")
        gate(all(text(reframed.get(k)) for k in ("question", "borrowedField", "constraintFlip")), "Reframe, borrow from another field and flip a constraint")
        options = row("diverge").get("options", [])
        options = options if isinstance(options, list) else []
        usable = isinstance(options, list) and len(options) >= 3 and all(isinstance(o, dict) and all(text(o.get(k)) for k in ("id", "family", "mechanism", "benefit")) and type(o.get("cost")) in (int, float) and math.isfinite(o["cost"]) and o["cost"] >= 0 for o in options)
        gate(usable and all(len({o[key].strip().casefold() for o in options}) == len(options) for key in ("id", "family", "mechanism")), "Three distinct mechanism families, IDs and mechanisms with usefulness and finite cost")
        weights = row("criteria").get("weights", {})
        gate(isinstance(weights, dict) and all(type(weights.get(k)) in (int, float) and math.isfinite(weights[k]) and weights[k] > 0 for k in ("novelty", "usefulness", "cost")), "Explicit novelty, usefulness and cost criteria before choice")
        gate(row("choose").get("option") in [o.get("id") for o in options if isinstance(o, dict)] and text(row("choose").get("reason")), "Choose an option using the recorded criteria")
    elif manual_id == "critique-review":
        gate(text(row("plan").get("mechanism")), "State the plan's defining mechanism")
        risks = row("attack").get("risks", [])
        gate(isinstance(risks, list) and len(risks) >= 2 and all(isinstance(r, dict) and text(r.get("failure")) and text(r.get("evidence")) for r in risks), "Attack two concrete failure paths with evidence")
        ids = row("verify").get("receipts", [])
        ids = ids if isinstance(ids, list) else []
        gate(strings(ids) and all(i in evidence and isinstance(evidence[i], dict) for i in ids), "Verification must link host receipts")
        decision = row("decision")
        gate(type(decision.get("done")) is bool and isinstance(decision.get("missing"), list) and (not decision["done"] or not decision["missing"]), "Completion cannot hide a missing defining mechanism")
        gate(not decision.get("done") or all(evidence[i].get("success") is True for i in ids if i in evidence), "A failed receipt prevents completion")
    elif manual_id == "efficiency":
        paths = row("paths").get("available", [])
        paths = paths if isinstance(paths, list) else []
        order = ["script", "memory", "small-model", "big-model"]
        gate(strings(paths) and len(paths) == len(set(paths)) and all(p in order for p in paths), "Record available paths from the cheapest-first cascade")
        attempt, measured = receipt("attempt"), receipt("measure")
        chosen = row("attempt").get("path")
        gate(chosen in paths and text(row("attempt").get("reason")) and attempt.get("path") == chosen, "Attempt receipt must match selected path")
        cheaper = order[:order.index(chosen)] if chosen in order else order
        failures = attempt.get("cheaperFailures", [])
        failures = failures if isinstance(failures, list) else []
        gate(all(p not in paths or p in failures for p in cheaper), "Escalation needs observed failure of every available cheaper path")
        gate(type(measured.get("tokens")) is int and measured["tokens"] >= 0 and type(measured.get("latencyMs")) in (int, float) and math.isfinite(measured["latencyMs"]) and measured["latencyMs"] >= 0 and measured.get("path") == chosen, "Measure actual tokens and latency for the selected path")
        logged = receipt("log")
        gate(logged.get("kind") == "research-ledger" and logged.get("measurement") == row("measure").get("receipt"), "Cost log must link measured receipt")
    elif manual_id == "research":
        gate(text(row("question").get("question")), "Specific research question required")
        sources = row("prior-art").get("sources", [])
        gate(isinstance(sources, list) and len(sources) >= 2 and all(isinstance(s, dict) and text(s.get("source")) and text(s.get("finding")) for s in sources), "Compare at least two prior-art sources with findings")
        gate(all(text(row("claim").get(k)) for k in ("prediction", "falsifier")), "Prediction must have an explicit falsifier")
        measured = receipt("test")
        gate(type(measured.get("success")) is bool, "Smallest real test needs measured success/failure")
        result = row("result")
        gate(type(result.get("supported")) is bool and result.get("supported") == measured.get("success") and strings(result.get("limitations")), "Honest result matches the test and states limitations")
    else:
        gate(all(text(row("reference").get(k)) for k in ("source", "principle")), "Reference must yield a concrete design principle")
        choices = row("details").get("choices", [])
        gate(isinstance(choices, list) and len(choices) >= 2 and all(isinstance(c, dict) and text(c.get("pattern")) and text(c.get("purpose")) for c in choices), "Details library choices need a purpose")
        rendered = receipt("render")
        gate(rendered.get("rendered") is True, "Taste judgment requires a real rendered artifact")
        critique = row("critique")
        defects = critique.get("defects", [])
        gate(isinstance(defects, list) and all(isinstance(d, dict) and text(d.get("finding")) and text(d.get("evidence")) for d in defects) and text(critique.get("tasteReason")), "Taste critique must cite observed evidence")
        decision = row("decision")
        gate(type(decision.get("done")) is bool and isinstance(decision.get("remaining"), list) and (not decision["done"] or not decision["remaining"]), "Decision exposes all remaining design defects")
    adherence = sum(gates) / len(gates)
    return {"manual": manual_id, "accepted": all(gates), "adherence": adherence,
            "outcomeQuality": outcome_quality, "tokens": tokens,
            "fitness": outcome_quality * adherence / tokens if tokens else None,
            "fitnessUnavailableReason": "Zero model tokens; per-token fitness is undefined" if not tokens else None,
            "errors": errors, "gatesPassed": sum(gates), "gatesTotal": len(gates)}


def tool_specs(spec_type):
    specs = [spec_type(name="neyvia.workflow." + name, description=description,
        category="workflows", mutability_class="read" if name == "check" else "artifact_write",
        capabilities=("workflow." + name,), parallel_safe=False, input_schema=INPUT_SCHEMA)
        for name, description in [("check", "Validate workflow order, mechanism and host-bound evidence."),
                                   ("record", "Persist a validated workflow receipt; refuses unverified adherence.")]]
    specs.append(spec_type(name="neyvia.workflow.details", description="Read attributed interface details reference patterns and local inspection criteria.",
        category="workflows", mutability_class="read", capabilities=("workflow.details",), parallel_safe=True,
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": []}))
    return specs


def call_tool(root, name, args):
    if name == "details":
        library = json.loads((REPO / "config/design_details.json").read_text(encoding="utf-8"))
        query = args.get("query", "").casefold()
        return {**library, "patterns": [p for p in library["patterns"] if query in json.dumps(p).casefold()]}
    root = Path(root).resolve()
    evidence = {}
    for identity, descriptor in args["evidence"].items():
        if not isinstance(descriptor, dict) or set(descriptor) != {"path", "sha256"}:
            raise ValueError("Evidence needs a local receipt path and SHA256, never caller metrics")
        path = (root / descriptor["path"]).resolve()
        path.relative_to(root)
        if not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("Receipt absent or exceeds bounded JSON size")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != descriptor["sha256"]:
            raise ValueError("Receipt SHA256 mismatch")
        receipt = json.loads(content)
        if not isinstance(receipt, dict) or not receipt:
            raise ValueError("Receipt must contain an actual measurement object")
        evidence[identity] = receipt
    result = validate_workflow(args["manual"], args["report"], args["outcomeQuality"], args["tokens"], evidence)
    result["qualityAuthority"] = "caller-scored; independent task judge required for outcome claims"
    if name == "record":
        if not result["accepted"]:
            raise ValueError("Workflow evidence failed: " + "; ".join(result["errors"]))
        payload = {"schema": "neyvia.workflow-receipt.v1", **result, "report": args["report"], "evidenceFiles": args["evidence"]}
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        path = Path(root) / "workflow-receipts" / (digest + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        result.update(receipt=str(path), sha256=digest)
    return result
