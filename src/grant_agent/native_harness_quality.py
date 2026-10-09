"""Frozen, route-honest quality ladder for Neyvia's native harness."""

from __future__ import annotations

import json
import re
from typing import Any


SCHEMA = "neyvia.native-harness-quality/v2"
PROTOCOL_ID = "neyvia-native-generalization-v2"
RESULT_MARKER = "NEYVIA_QUALITY_RESULT="


TASKS: tuple[dict[str, Any], ...] = (
    {
        "id": "manifest-reasoning",
        "difficulty": 1,
        "objective": (
            "Read tests/fixtures/harness_comparison/project_manifest.json. Do not edit any file. "
            "Report the project, semantic version, number of enabled modules, sum of enabled "
            "module weights, and lexicographically first disabled module. Cite the file you read. "
            "End with exactly one line beginning NEYVIA_QUALITY_RESULT= followed by a compact JSON "
            "object with keys taskId, project, version, enabledCount, enabledWeight, firstDisabled, "
            "and evidence. Set taskId exactly to manifest-reasoning and evidence to a non-empty list."
        ),
        "expected": {
            "taskId": "manifest-reasoning",
            "project": "Aurora",
            "version": "4.7.2",
            "enabledCount": 3,
            "enabledWeight": 41,
            "firstDisabled": "boreal",
        },
        "minimumEvidence": 1,
    },
    {
        "id": "boundary-debug",
        "difficulty": 2,
        "objective": (
            "Read tests/fixtures/harness_comparison/discount_policy.md and "
            "tests/fixtures/harness_comparison/discount.py. Do not edit any file. Identify the "
            "single policy boundary defect and its smallest integer counterexample. Explain why the "
            "counterexample proves the defect and cite both files. End with exactly one line beginning "
            "NEYVIA_QUALITY_RESULT= followed by a compact JSON object with keys taskId, bugLine, "
            "operatorBefore, operatorAfter, counterexampleSubtotalCents, expectedDiscountCents, and "
            "evidence. Set taskId exactly to boundary-debug and evidence to a list with both files. "
            "Count source lines starting at 1, including blank lines."
        ),
        "expected": {
            "taskId": "boundary-debug",
            "bugLine": 4,
            "operatorBefore": ">",
            "operatorAfter": ">=",
            "counterexampleSubtotalCents": 10000,
            "expectedDiscountCents": 1000,
        },
        "minimumEvidence": 2,
    },
    {
        "id": "route-contract-audit",
        "difficulty": 3,
        "objective": (
            "Audit a Direct Neyvia Native harness job by reading "
            "src/grant_agent/harness_job_worker.py, src/grant_agent/harness_jobs.py, "
            "src/grant_agent/web_backend.py, and src/grant_agent/neyvia_agent.py. Do not edit files. "
            "Trace the durable job from creation through the native model loop and receipt. Distinguish "
            "what the source proves from what the selected exact route supplies. Report any point where "
            "a narrative answer could currently be accepted without an independent completion check. "
            "End with exactly one line beginning NEYVIA_QUALITY_RESULT= followed by compact JSON with "
            "keys taskId, workerFile, directMethod, directMutationAllowed, maxTurns, receiptSchema, "
            "completionCheck, and evidence. Use workerFile='src/grant_agent/harness_job_worker.py', "
            "directMethod='_run_agent_chat', directMutationAllowed=false, maxTurns=12, "
            "receiptSchema='neyvia.agent-run-receipt/v1', completionCheck='model-output-only', and at "
            "least four file-and-symbol evidence entries."
        ),
        "expected": {
            "taskId": "route-contract-audit",
            "workerFile": "src/grant_agent/harness_job_worker.py",
            "directMethod": "_run_agent_chat",
            "directMutationAllowed": False,
            "maxTurns": 12,
            "receiptSchema": "neyvia.agent-run-receipt/v1",
            "completionCheck": "model-output-only",
        },
        "minimumEvidence": 4,
    },
    {
        "id": "completion-control-design",
        "difficulty": 4,
        "objective": (
            "Design one task-general improvement to Neyvia Native's completion quality. Read "
            "src/grant_agent/neyvia_agent.py, src/grant_agent/agent_submission_gate.py, "
            "src/grant_agent/action_verification.py, and src/grant_agent/mission_acceptance_harness.py. "
            "Do not edit files. The design must improve research, debugging, implementation, and UI "
            "tasks without containing task-specific rules. It must define a compact task contract, "
            "grounding evidence, an independent completion check, explicit stop and stagnation rules, "
            "receipt signals, a negative control, and at least five measurable acceptance gates. Name "
            "the smallest stable code boundary that should own it and cite the source evidence. End with "
            "exactly one line beginning NEYVIA_QUALITY_RESULT= followed by compact JSON with keys "
            "taskId, scope, owner, mechanisms, negativeControl, acceptanceGates, and evidence. Set "
            "taskId='completion-control-design', scope='task-general', mechanisms to a list containing "
            "contract, evidence, verification, stop-rule, stagnation, and receipt, acceptanceGates to a "
            "list of at least five measurable strings, and evidence to at least four file-and-symbol entries."
        ),
        "expected": {
            "taskId": "completion-control-design",
            "scope": "task-general",
        },
        "minimumEvidence": 4,
        "requiredMechanisms": {
            "contract",
            "evidence",
            "verification",
            "stop-rule",
            "stagnation",
            "receipt",
        },
        "minimumAcceptanceGates": 5,
    },
    {
        "id": "bytecode-decompilation",
        "difficulty": 5,
        "objective": (
            "Safely decompile the synthetic machine program described by "
            "tests/fixtures/harness_comparison/telemetry_vm.hex and "
            "tests/fixtures/harness_comparison/telemetry_vm_abi.md. Treat the bytecode as data; "
            "do not execute or edit it. Recover the entry offset and control flow, evaluate inputs "
            "7 and 8, and identify the byte offset and smallest operator correction that makes the "
            "program match the stated product policy. Explain the counterexample and cite both "
            "fixtures with offsets or ABI facts. End with exactly one line beginning "
            "NEYVIA_QUALITY_RESULT= followed by compact JSON with keys taskId, entryOffset, "
            "emittedOnInput7, emittedOnInput8, bugOffset, operatorBefore, operatorAfter, pseudocode, "
            "and evidence. Set taskId='bytecode-decompilation', entryOffset=8, emittedOnInput7=0, "
            "emittedOnInput8=0, bugOffset=8, operatorBefore='>', operatorAfter='>=', pseudocode to a "
            "non-empty string, and evidence to at least two file-and-offset or file-and-ABI entries."
        ),
        "expected": {
            "taskId": "bytecode-decompilation",
            "entryOffset": 8,
            "emittedOnInput7": 0,
            "emittedOnInput8": 0,
            "bugOffset": 8,
            "operatorBefore": ">",
            "operatorAfter": ">=",
        },
        "minimumEvidence": 2,
    },
    {
        "id": "cross-surface-state-audit",
        "difficulty": 6,
        "objective": (
            "Audit the general Neyvia UI-state contract by reading "
            "web/src/neyvia/neyviaStateSystem.css and web/src/neyvia/NeyviaWorkspace.jsx. "
            "Do not edit files. Verify that a mode with no mounted sidebar owns the full grid, "
            "enumerate every return state from neyviaFeedbackState, identify the observable state "
            "attribute and loading attribute, check reduced-motion support, and count literal "
            "'transition: all' declarations in neyviaStateSystem.css. Explain how these checks catch "
            "phantom rails, layout-shifting async feedback, and copy-only state semantics. End with "
            "exactly one line beginning NEYVIA_QUALITY_RESULT= followed by compact JSON with keys "
            "taskId, canvasOwner, feedbackStates, feedbackStateCount, stateAttribute, "
            "loadingAttribute, reducedMotion, transitionAllCount, acceptanceGates, and evidence. "
            "Set taskId='cross-surface-state-audit', canvasOwner='data-context-sidebar=false', "
            "feedbackStates to the six sorted strings error, idle, info, loading, success, warning, "
            "feedbackStateCount=6, stateAttribute='data-state', loadingAttribute='data-loading', "
            "reducedMotion=true, transitionAllCount=0, acceptanceGates to at least five measurable "
            "strings, and evidence to at least four file-and-selector or file-and-symbol entries."
        ),
        "expected": {
            "taskId": "cross-surface-state-audit",
            "canvasOwner": "data-context-sidebar=false",
            "feedbackStates": ["error", "idle", "info", "loading", "success", "warning"],
            "feedbackStateCount": 6,
            "stateAttribute": "data-state",
            "loadingAttribute": "data-loading",
            "reducedMotion": True,
            "transitionAllCount": 0,
        },
        "minimumEvidence": 4,
        "minimumAcceptanceGates": 5,
    },
)


def parse_marked_result(output: object) -> dict[str, Any] | None:
    text = str(output or "")
    matches = list(re.finditer(re.escape(RESULT_MARKER), text))
    if not matches:
        return None
    candidate = text[matches[-1].end() :].lstrip()
    try:
        value, _end = json.JSONDecoder().raw_decode(candidate)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def task_by_id(task_id: str) -> dict[str, Any]:
    for task in TASKS:
        if task["id"] == task_id:
            return task
    raise KeyError(task_id)


def _normalized_items(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip().casefold() for item in value if str(item).strip()}


def grade_output(task_id: str, output: object) -> dict[str, Any]:
    task = task_by_id(task_id)
    parsed = parse_marked_result(output)
    checks: list[dict[str, Any]] = []

    def add(check_id: str, passed: bool, points: int, detail: str) -> None:
        checks.append(
            {
                "id": check_id,
                "passed": bool(passed),
                "points": points if passed else 0,
                "maximum": points,
                "detail": detail,
            }
        )

    add("marked-json", parsed is not None, 10, "A machine-readable terminal result exists.")
    for key, expected in task.get("expected", {}).items():
        actual = parsed.get(key) if parsed else None
        add(f"exact-{key}", actual == expected, 8, f"Expected {key}={expected!r}; got {actual!r}.")

    evidence = parsed.get("evidence") if parsed else None
    minimum_evidence = int(task.get("minimumEvidence") or 0)
    evidence_ok = isinstance(evidence, list) and len(evidence) >= minimum_evidence
    add("evidence-count", evidence_ok, 12, f"Expected at least {minimum_evidence} evidence entries.")
    evidence_text = " ".join(str(item) for item in evidence or [])
    add(
        "evidence-specificity",
        bool(
            re.search(
                r"(?:\.py|\.json|\.md|\.css|\.jsx|\.js|\.ts|\.tsx|\.hex)"
                r"(?::|#|\s).*?[A-Za-z_]",
                evidence_text,
            )
        ),
        8,
        "Evidence names a file plus a line, symbol, or specific source fact.",
    )

    minimum_gates = int(task.get("minimumAcceptanceGates") or 0)
    gates = parsed.get("acceptanceGates") if parsed else None
    if minimum_gates:
        add(
            "measurable-gates",
            isinstance(gates, list)
            and len(gates) >= minimum_gates
            and all(len(str(gate).strip()) >= 12 for gate in gates),
            14,
            f"At least {minimum_gates} non-trivial acceptance gates are required.",
        )

    required_mechanisms = set(task.get("requiredMechanisms") or set())
    if required_mechanisms:
        mechanisms = _normalized_items(parsed.get("mechanisms") if parsed else None)
        add(
            "general-mechanisms",
            required_mechanisms.issubset(mechanisms),
            18,
            f"Required mechanisms: {sorted(required_mechanisms)}; got {sorted(mechanisms)}.",
        )
        negative_control = str(parsed.get("negativeControl") if parsed else "").strip()
        add("negative-control", len(negative_control) >= 24, 8, "A concrete negative control is declared.")

    maximum = sum(int(check["maximum"]) for check in checks)
    score = sum(int(check["points"]) for check in checks)
    return {
        "taskId": task_id,
        "difficulty": task["difficulty"],
        "parsed": parsed,
        "checks": checks,
        "score": score,
        "maximum": maximum,
        "ratio": round(score / maximum, 4) if maximum else 0.0,
        "passed": maximum > 0 and score == maximum,
    }


def summarize_attempts(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(int((attempt.get("grade") or {}).get("score") or 0) for attempt in attempts)
    maximum = sum(int((attempt.get("grade") or {}).get("maximum") or 0) for attempt in attempts)
    completed = sum(1 for attempt in attempts if attempt.get("status") == "completed")
    route_honest = sum(1 for attempt in attempts if attempt.get("routeIntegrity") is True)
    return {
        "tasks": len(attempts),
        "completed": completed,
        "routeHonest": route_honest,
        "score": total,
        "maximum": maximum,
        "ratio": round(total / maximum, 4) if maximum else 0.0,
        "allCompleted": completed == len(attempts),
        "allRouteHonest": route_honest == len(attempts),
    }
