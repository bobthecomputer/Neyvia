"""Evidence-derived procedure plans; execution stays in the grounded manual runner.

Plans contain data, never Python source. A learned judgement is reusable only for
the identical inputs, manual hash and verified trace cohort that established it.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import re

from jsonschema import Draft202012Validator

from .durability import atomic_write_json

SCHEMA = "neyvia.manual-script.v1"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _root(service):
    root = service.bus.root / ".neyvia"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _events(root):
    grouped = defaultdict(list)
    path = root / "manual-runs.jsonl"
    if not path.exists():
        return grouped
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("runId"), str):
                raise ValueError("Missing run identity")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Run evidence log is malformed at line {number}") from exc
        grouped[row["runId"]].append(row)
    return grouped


def _verified_trace(root, events, data, chapter_name, chapter, procedure_name, procedure, manual_hash, registry):
    """Cross-check durable completion, chronological events, schemas and verifiers."""
    from .neyvia_manuals import expect

    identity = events[0]["runId"]
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("Unsupported run identity")
    path = root / "manual-runs" / (identity + ".json")
    state = json.loads(path.read_text(encoding="utf-8"))
    required = {"runId": identity, "id": data["id"], "chapter": chapter_name,
                "procedure": procedure_name, "sha256": manual_hash, "status": "completed",
                "nextStep": len(procedure["steps"])}
    if any(state.get(key) != value for key, value in required.items()):
        raise ValueError("Durable run is incomplete, stale or belongs to another procedure")
    if state.get("compiledArtifactId") or any(row.get("compiledArtifactId") for row in events):
        raise ValueError("Compiled executions cannot reinforce their own learned decisions")
    if events[0].get("event") != "start" or events[-1].get("event") != "completed":
        raise ValueError("Run lacks a complete start-to-completion receipt")
    allowed = {"start", "resume", "action", "check", "judge", "decision", "completed"}
    for row in events:
        if row.get("event") not in allowed:
            raise ValueError("Failed or unsupported run event")
        for key in ("runId", "id", "chapter", "procedure", "sha256"):
            if row.get(key) != required[key]:
                raise ValueError("Run event lacks current grounded identity metadata")
        if row["event"] in {"start", "resume"} and row.get("inputs") != state["inputs"]:
            raise ValueError("Run input evidence differs from durable inputs")
    if sum(row["event"] == "start" for row in events) != 1 or sum(row["event"] == "completed" for row in events) != 1:
        raise ValueError("Repeated start or completion receipt")
    Draft202012Validator(procedure["inputs"]).validate(state["inputs"])
    substantive = [row for row in events if row["event"] not in {"start", "resume", "completed"}]
    position, results, decisions, checks, actions = 0, {}, {}, [], []
    judge_contexts = {}

    def take(kind):
        nonlocal position
        if position >= len(substantive) or substantive[position]["event"] != kind:
            raise ValueError("Run event sequence does not match the executable procedure")
        row = substantive[position]
        position += 1
        return row

    for step_number, step in enumerate(procedure["steps"]):
        if "judge" in step:
            name = step["judge"]
            judge_contexts[name] = digest(results)
            judge = take("judge")
            if judge.get("judge") != {"id": name, **chapter["judge"][name]}:
                raise ValueError("Judge evidence differs from the manual")
            decision = take("decision").get("decisions")
            if not isinstance(decision, dict) or set(decision) != {name} or decision[name] not in chapter["judge"][name]["options"]:
                raise ValueError("Unverified judge decision")
            decisions.update(decision)
            continue
        if step.get("when") and decisions.get(step["when"]["judge"]) != step["when"]["option"]:
            continue
        action = chapter["actions"][step["action"]]
        row = take("action")
        if (row.get("step"), row.get("action"), row.get("tool")) != (step_number, step["action"], action["tool"]):
            raise ValueError("Action receipt differs from the manual")
        Draft202012Validator(action["returns"]).validate(row.get("result"))
        results[step["save"]] = row["result"]
        actions.append(step_number)
        if registry.describe(action["tool"])["mutability_class"] not in {"read", "none"} and not step.get("check"):
            raise ValueError("Mutating action has no executable verifier")
        if step.get("check"):
            receipt = take("check")
            check = chapter["checks"][step["check"]]
            if (receipt.get("step"), receipt.get("check"), receipt.get("passed")) != (step_number, step["check"], True):
                raise ValueError("Missing or failed executable verifier")
            if not expect(receipt.get("observed"), check["expect"], state["inputs"], results, root.parent):
                raise ValueError("Verifier result no longer proves its expected condition")
            checks.append({key: receipt[key] for key in ("step", "check", "passed", "observed")})
    if position != len(substantive) or not actions:
        raise ValueError("Unsupported extra events or procedure has no executed actions")
    if state.get("decisions") != decisions or state.get("results") != results or state.get("checks") != checks:
        raise ValueError("Durable results differ from logged verified effects")
    if events[-1].get("decisions") != decisions or events[-1].get("checks") != len(checks):
        raise ValueError("Completion metadata does not prove the trace")
    return {"runId": identity, "inputSha256": digest(state["inputs"]), "decisions": decisions,
            "actions": actions, "judgeContexts": judge_contexts,
            "evidenceSha256": digest({"events": events, "state": state})}


def _plan(data, chapter_name, procedure_name, procedure, manual_hash, traces, minimum):
    if type(minimum) is not int or not 2 <= minimum <= 100:
        raise ValueError("minRuns must be an integer between 2 and 100")
    if len({trace["runId"] for trace in traces}) != len(traces):
        raise ValueError("Compilation requires distinct successful runs")
    names = [step["judge"] for step in procedure["steps"] if "judge" in step]
    fixed, guards, variable = {}, {}, []
    for name in names:
        choices = {trace["decisions"][name] for trace in traces}
        contexts = {trace["judgeContexts"][name] for trace in traces}
        if data["chapters"][chapter_name]["judge"][name].get("kind", "human") == "model":
            variable.append(name)  # evidence-bound: every run needs fresh evidence, never a replayed answer
        elif len(choices) == 1 and len(contexts) == 1:
            fixed[name] = next(iter(choices))
            guards[name] = next(iter(contexts))
        else:
            variable.append(name)
    counts = Counter(canonical(trace["decisions"]) for trace in traces)
    if max(counts.values(), default=0) < minimum:
        raise ValueError(f"Compilation needs {minimum} identical successful decision traces")
    plan = {"schema": SCHEMA, "id": data["id"], "chapter": chapter_name, "procedure": procedure_name,
            "sha256": manual_hash, "inputSha256": traces[0]["inputSha256"], "minRuns": minimum,
            "fixedDecisions": fixed, "fixedDecisionGuards": guards, "variableJudges": variable, "zeroToken": not variable,
            "runner": "grounded-manual-runner", "steps": procedure["steps"],
            "sourceRuns": [{key: trace[key] for key in ("runId", "evidenceSha256")} for trace in traces],
            "branchCounts": [{"decisions": json.loads(key), "runs": count} for key, count in sorted(counts.items())]}
    plan["scriptId"] = digest(plan)
    return plan


def compile_procedure(service, args, registry):
    from . import neyvia_manuals as manuals

    minimum = args.get("minRuns", 3)
    if type(minimum) is not int or not 2 <= minimum <= 100:
        raise ValueError("minRuns must be an integer between 2 and 100")
    root = _root(service)
    _, manual_hash, data = manuals.get_manual(args["id"], root)
    manuals.validate(data, registry)
    chapter_name, chapter, procedure = manuals.chapter_entry(data, args.get("chapter"), "procedures", args["procedure"])
    traces, rejected = [], []
    wanted = digest(args["inputs"]) if "inputs" in args else None
    with manuals._LOCK, manuals.execution_lock(root):
        for identity, events in sorted(_events(root).items()):
            if not any(row.get("event") == "completed" and row.get("id") == data["id"] and row.get("procedure") == args["procedure"] for row in events):
                continue
            try:
                trace = _verified_trace(root, events, data, chapter_name, chapter, args["procedure"], procedure, manual_hash, registry)
                if wanted is None or trace["inputSha256"] == wanted:
                    traces.append(trace)
            except (ValueError, KeyError, TypeError, OSError, IndexError) as exc:
                rejected.append({"runId": identity, "reason": str(exc)})
        if len(traces) < minimum:
            raise ValueError(f"Compilation needs {minimum} verified successful runs; found {len(traces)}; rejected {len(rejected)}")
        if len({trace["inputSha256"] for trace in traces}) != 1:
            raise ValueError("Multiple learned input scopes; supply exact inputs to select one cohort")
        plan = _plan(data, chapter_name, args["procedure"], procedure, manual_hash, traces, minimum)
        path = root / "manual-scripts" / (plan["scriptId"] + ".json")
        atomic_write_json(path, plan)
    return {"ok": True, **plan, "path": str(path), "rejectedRuns": rejected,
            "authority": "Caller dispatch, nested tool restrictions and verifiers remain mandatory"}


def _load_plan(service, identity):
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{64}", identity):
        raise ValueError("scriptId must be a returned compiled script identity")
    plan = json.loads((_root(service) / "manual-scripts" / (identity + ".json")).read_text(encoding="utf-8"))
    if plan.get("scriptId") != identity or digest({key: value for key, value in plan.items() if key != "scriptId"}) != identity:
        raise ValueError("Compiled script integrity check failed")
    return plan


def compiled_index(service, args):
    from . import neyvia_manuals as manuals

    scripts = []
    for path in sorted((_root(service) / "manual-scripts").glob("*.json")):
        plan = _load_plan(service, path.stem)
        if args.get("id") and plan["id"] != args["id"]:
            continue
        _, current, _ = manuals.get_manual(plan["id"], _root(service))
        scripts.append({**plan, "stale": current != plan["sha256"]})
    return {"ok": True, "scripts": scripts}


def run_compiled(service, args, registry, dispatch):
    from . import neyvia_manuals as manuals

    root = _root(service)
    plan = _load_plan(service, args["scriptId"])
    _, manual_hash, data = manuals.get_manual(plan["id"], root)
    if manual_hash != plan["sha256"]:
        raise ValueError("Compiled script is stale; recompile the current manual")
    manuals.validate(data, registry)
    chapter_name, chapter, procedure = manuals.chapter_entry(data, plan["chapter"], "procedures", plan["procedure"])
    # Recreate the plan from its original successful evidence. A content hash alone
    # cannot make edited learned decisions trustworthy.
    traces, events = [], _events(root)
    for source in plan["sourceRuns"]:
        trace = _verified_trace(root, events[source["runId"]], data, chapter_name, chapter,
                                plan["procedure"], procedure, manual_hash, registry)
        if trace["evidenceSha256"] != source["evidenceSha256"] or trace["inputSha256"] != plan["inputSha256"]:
            raise ValueError("Compiled script provenance changed")
        traces.append(trace)
    if len(traces) < plan["minRuns"] or _plan(data, chapter_name, plan["procedure"], procedure, manual_hash, traces, plan["minRuns"]) != plan:
        raise ValueError("Compiled script differs from its grounded source evidence")
    known = {trace["runId"] for trace in traces}
    for identity, rows in events.items():
        if identity in known or not any(row.get("event") == "completed" and row.get("id") == plan["id"] and row.get("procedure") == plan["procedure"] for row in rows):
            continue
        try:
            trace = _verified_trace(root, rows, data, chapter_name, chapter, plan["procedure"], procedure, manual_hash, registry)
        except (ValueError, KeyError, TypeError, OSError, IndexError):
            continue
        if trace["inputSha256"] == plan["inputSha256"] and any(trace["decisions"].get(name) != option or trace["judgeContexts"].get(name) != plan["fixedDecisionGuards"][name] for name, option in plan["fixedDecisions"].items()):
            raise ValueError("New successful evidence varies a learned judgement; recompile to retain that JUDGE")
    inputs = args.get("inputs", {})
    if args.get("runId") and "inputs" not in args:
        identity = args["runId"]
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("runId must be a returned run identity")
        saved = json.loads((root / "manual-runs" / (identity + ".json")).read_text(encoding="utf-8"))
        inputs = saved["inputs"]
    if digest(inputs) != plan["inputSha256"]:
        raise ValueError("Compiled judgement is bound to learned inputs; use manual.run for new inputs")
    forwarded = {key: value for key, value in args.items() if key in {"inputs", "scopeTools", "runId", "decisions"}}
    forwarded.update(id=plan["id"], chapter=plan["chapter"], procedure=plan["procedure"])
    output = manuals.run(service, forwarded, registry, dispatch, compiled=plan)
    return {**output, "scriptId": plan["scriptId"], "modelCalls": 0,
            "zeroToken": plan["zeroToken"] and not output.get("compiledGuardEscalations"),
            "variableJudges": plan["variableJudges"]}
