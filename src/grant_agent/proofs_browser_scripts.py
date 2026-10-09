"""Bounded outcomes for browser procedure binding and goal admission."""
from __future__ import annotations

import json
import time
from pathlib import Path

CONTRACTS = (
    "browser-script.input-binding",
    "browser-script.goal-observation",
    "browser-script.query-binding",
    "browser-script.invalid-name",
)


def input_binding():
    from .browser_scripts import bind

    template = {
        "steps": [{"action": "fill", "target": {"role": "searchbox", "name": "Search"},
                   "value": {"$input": "query"}}],
        "checks": [{"path": "/url", "contains": {"$input": "queryParameter"}},
                   {"path": "/results/count", "equals": 3}],
    }
    result = bind(template, {"query": "green tea", "queryParameter": "q=green%20tea"})
    expected = {
        "steps": [{"action": "fill", "target": {"role": "searchbox", "name": "Search"},
                   "value": "green tea"}],
        "checks": [{"path": "/url", "contains": "q=green%20tea"},
                   {"path": "/results/count", "equals": 3}],
    }
    if result != expected:
        raise ValueError(f"Bound browser procedure differed from its concrete inputs: {result!r}")
    return {"boundProcedure": result}


def goal_observation():
    from .browser_scripts import goal

    observation = {"rendered": {"message": "Order confirmed: A-17"},
                   "results": [{"name": "Green tea"}, {"name": "Mint tea"}]}
    checks = [{"path": "/rendered/message", "contains": "A-17"},
              {"path": "/results/1/name", "equals": "Mint tea"}]
    result = goal(observation, checks)
    expected = {"verified": True, "checks": [{"predicate": checks[0], "passed": True},
                                               {"predicate": checks[1], "passed": True}]}
    if result != expected:
        raise ValueError(f"Observed browser goals were not returned exactly: {result!r}")

    miss = goal(observation, [{"path": "/results/1/name", "equals": "Chamomile"}])
    expected_miss = {"verified": False, "checks": [{"predicate": {"path": "/results/1/name", "equals": "Chamomile"},
                                                      "passed": False}]}
    if miss != expected_miss:
        raise ValueError(f"A nonmatching observed result was admitted: {miss!r}")
    return {"matchedObservation": result, "nonmatchingObservation": miss}


def query_binding():
    from .browser_scripts import observed_input_bindings

    template = {
        "steps": [{"action": "fill", "value": {"$input": "query"}}],
        "checks": [{"path": "/url", "contains": {"$input": "queryParameter"}}],
    }
    inputs = {"query": "green tea", "queryParameter": "q=green%20tea"}
    observation = {"url": "https://shop.example.test/search?q=green%20tea"}
    result = observed_input_bindings(template, inputs, observation)
    expected = {"queryParameter": {"urlQueryParameter": "q", "sourceInput": "query", "encoding": "percent"}}
    if result != expected:
        raise ValueError(f"Observed query binding lost its parameter provenance: {result!r}")
    return {"observedBindings": result}


def invalid_name():
    from .browser_scripts import execute
    from .neyvia_browser import BrowserError

    class NoObservationService:
        directory = Path(".")

    # Invalid names must be rejected before observing a tab or reading/writing a procedure.
    try:
        execute(NoObservationService(), "script.run", {"name": "../escape", "tabId": "unused"})
    except BrowserError as error:
        if error.code != "invalid_script" or str(error) != "Supply a bounded procedure name":
            raise ValueError(f"Invalid procedure name returned the wrong error: {error.code}: {error}") from error
    else:
        raise ValueError("Path-like procedure name reached browser observation")
    return {"rejectedName": "../escape", "errorCode": "invalid_script",
            "errorMessage": "Supply a bounded procedure name", "observationAttempted": False}


def self_check(root):
    from .contract_gate import wants
    root = Path(root) / "browser-scripts"
    root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases = []
    for identity, contract, action in (
        ("input-binding", CONTRACTS[0], input_binding),
        ("goal-observation", CONTRACTS[1], goal_observation),
        ("query-binding", CONTRACTS[2], query_binding),
        ("invalid-name", CONTRACTS[3], invalid_name),
    ):
        if not wants(contract):continue
        try:
            observed = action()
            cases.append({"id": identity, "contracts": [contract], "ok": True, "observed": observed})
        except Exception as error:
            cases.append({"id": identity, "contracts": [contract], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    report = {"ok": bool(cases) and all(case["ok"] for case in cases), "cases": cases,
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    (root / "outcomes.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
