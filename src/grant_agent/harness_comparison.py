"""Deterministic, receipt-backed comparison for installed Neyvia harnesses."""

from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from typing import Any, Iterable
from .proofs_b_adapters import checked as _proofs_b_checked


SCHEMA = "neyvia.harness-comparison/v1"
PROTOCOL_ID = "neyvia-cross-harness-readonly-v1"
RESULT_MARKER = "HARNESS_BENCHMARK_RESULT="
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
WINNER_RULE = (
    "Maximize exact correctness, completion, receipt coverage, route integrity, and read-only "
    "coverage in that order; break a complete tie by declared essential capability coverage, "
    "then median execution time. A leader must reach 100% correctness, completion, receipt, "
    "route integrity, and read-only coverage. Missing attempts and provider substitution are "
    "disqualifying."
)

TASKS: tuple[dict[str, Any], ...] = (
    {
        "id": "manifest-reasoning",
        "fixturePaths": ["tests/fixtures/harness_comparison/project_manifest.json"],
        "expected": {
            "taskId": "manifest-reasoning",
            "project": "Aurora",
            "version": "4.7.2",
            "enabledCount": 3,
            "enabledWeight": 41,
            "firstDisabled": "boreal",
        },
        "objective": (
            "Read tests/fixtures/harness_comparison/project_manifest.json. Do not edit any file. "
            "Report the project, semantic version, number of enabled modules, sum of enabled "
            "module weights, and lexicographically first disabled module. End with exactly one "
            "line beginning HARNESS_BENCHMARK_RESULT= followed by a compact JSON object with "
            "keys taskId, project, version, enabledCount, enabledWeight, firstDisabled. Set "
            "taskId exactly to manifest-reasoning."
        ),
    },
    {
        "id": "boundary-debug",
        "fixturePaths": [
            "tests/fixtures/harness_comparison/discount_policy.md",
            "tests/fixtures/harness_comparison/discount.py",
        ],
        "expected": {
            "taskId": "boundary-debug",
            "bugLine": 4,
            "operatorBefore": ">",
            "operatorAfter": ">=",
            "counterexampleSubtotalCents": 10000,
            "expectedDiscountCents": 1000,
        },
        "objective": (
            "Read tests/fixtures/harness_comparison/discount_policy.md and discount.py. Do not "
            "edit any file. Identify the single policy boundary defect and its smallest integer "
            "counterexample. End with exactly one line beginning HARNESS_BENCHMARK_RESULT= followed "
            "by a compact JSON object with keys taskId, bugLine, operatorBefore, operatorAfter, "
            "counterexampleSubtotalCents, expectedDiscountCents. Set taskId exactly to "
            "boundary-debug. Count source lines starting at 1, including blank lines."
        ),
    },
)

CAPABILITY_GROUPS: dict[str, set[str]] = {
    "structuredExecution": {"agent_loop", "headless_json", "headless_log", "orchestration"},
    "durableSessions": {"sessions"},
    "toolUse": {"tools", "tool_search"},
    "projectInstructions": set(),
    "delegation": {"subagents", "orchestration"},
    "durableEvidence": {"proof", "queue", "ledger", "reports"},
    "safetyBoundary": {"approvals", "sandbox", "objectives"},
}


def task_by_id(task_id: str) -> dict[str, Any]:
    for task in TASKS:
        if task["id"] == task_id:
            return task
    raise KeyError(task_id)


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


@_proofs_b_checked("grade")
def grade_output(task_id: str, output: object) -> dict[str, Any]:
    task = task_by_id(task_id)
    expected = task["expected"]
    parsed = parse_marked_result(output)
    checks = {
        key: bool(parsed is not None and parsed.get(key) == value)
        for key, value in expected.items()
    }
    return {
        "parsed": parsed,
        "checks": checks,
        "points": sum(checks.values()),
        "maxPoints": len(checks),
        "correct": bool(checks) and all(checks.values()),
    }


@_proofs_b_checked("eligibility")
def eligibility(harness: dict[str, Any]) -> tuple[bool, str]:
    if harness.get("securityOnly"):
        return False, "security-only harness; not comparable to ordinary read-only coding work"
    if not harness.get("installed"):
        return False, "not installed"
    if not harness.get("detected"):
        return False, "installed runtime did not pass readiness inspection"
    readiness = str(harness.get("readiness") or "").strip().lower()
    if readiness == "provider-setup-required":
        return False, "provider setup required"
    if readiness == "provider-unverified":
        return False, "provider readiness unverified"
    if readiness in {"blocked", "not-installed"}:
        return False, readiness
    return True, "installed and ready for the common read-only protocol"


@_proofs_b_checked("capabilities")
def capability_coverage(harness: dict[str, Any]) -> dict[str, Any]:
    native_keys = {
        str(row.get("key") or "")
        for row in harness.get("capabilities") or []
        if isinstance(row, dict)
        and row.get("available") is not False
        and str(row.get("support") or "") == "native"
    }
    supported: list[str] = []
    for group, aliases in CAPABILITY_GROUPS.items():
        if group == "projectInstructions":
            present = bool(harness.get("instructionFiles"))
        else:
            present = bool(native_keys & aliases)
        if present:
            supported.append(group)
    return {
        "supported": supported,
        "count": len(supported),
        "total": len(CAPABILITY_GROUPS),
    }


def _median(values: Iterable[object]) -> int | None:
    measured = [int(value) for value in values if isinstance(value, (int, float)) and value >= 0]
    return round(statistics.median(measured)) if measured else None


@_proofs_b_checked("summaries")
def summarize_attempts(
    catalog_rows: list[dict[str, Any]], attempts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        grouped[str(attempt.get("harnessId") or "")].append(attempt)
    summaries: list[dict[str, Any]] = []
    task_count = len(TASKS)
    for harness in catalog_rows:
        harness_id = str(harness.get("harnessId") or "")
        is_eligible, reason = eligibility(harness)
        rows = grouped.get(harness_id, [])
        points = sum(int((row.get("grade") or {}).get("points") or 0) for row in rows)
        max_points = sum(int((row.get("grade") or {}).get("maxPoints") or 0) for row in rows)
        completed = sum(row.get("status") == "completed" for row in rows)
        receipts = sum(bool(row.get("receiptPresent")) for row in rows)
        route_integrity = sum(not bool(row.get("providerSubstitution")) for row in rows)
        read_only = sum(bool(row.get("readOnlyEnforced")) for row in rows)
        summaries.append(
            {
                "harnessId": harness_id,
                "label": harness.get("label") or harness_id,
                "eligible": is_eligible,
                "eligibilityReason": reason,
                "attemptCount": len(rows),
                "expectedAttemptCount": task_count if is_eligible else 0,
                "correctnessPoints": points,
                "correctnessMax": max_points,
                "correctnessRate": round(points * 100 / max_points) if max_points else None,
                "completionRate": round(completed * 100 / len(rows)) if rows else None,
                "receiptCoverage": round(receipts * 100 / len(rows)) if rows else None,
                "routeIntegrity": round(route_integrity * 100 / len(rows)) if rows else None,
                "readOnlyCoverage": round(read_only * 100 / len(rows)) if rows else None,
                "medianQueueMs": _median((row.get("metrics") or {}).get("queueLatencyMs") for row in rows),
                "medianExecutionMs": _median(
                    (row.get("metrics") or {}).get("executionDurationMs") for row in rows
                ),
                "capabilityCoverage": capability_coverage(harness),
                "models": sorted(
                    {
                        str(row.get("model") or "")
                        for row in rows
                        if str(row.get("model") or "").strip()
                    }
                ),
            }
        )
    return summaries


@_proofs_b_checked("leader")
def select_leader(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in summaries if row.get("eligible")]
    complete = [
        row
        for row in eligible
        if row.get("attemptCount") == row.get("expectedAttemptCount")
        and row.get("correctnessRate") == 100
        and row.get("completionRate") == 100
        and row.get("receiptCoverage") == 100
        and row.get("routeIntegrity") == 100
        and row.get("readOnlyCoverage") == 100
    ]
    if not complete:
        return {
            "status": "inconclusive",
            "harnessId": None,
            "rationale": "No harness completed the full sample with exact answers, receipts, intact routing, and read-only enforcement.",
        }
    ordered_metrics = ("correctnessRate", "completionRate", "receiptCoverage")
    finalists = complete
    rationale: list[str] = []
    for metric in ordered_metrics:
        best = max(int(row.get(metric) or 0) for row in finalists)
        finalists = [row for row in finalists if int(row.get(metric) or 0) == best]
        rationale.append(f"{metric}={best}%")
    best_capabilities = max(int((row.get("capabilityCoverage") or {}).get("count") or 0) for row in finalists)
    finalists = [
        row
        for row in finalists
        if int((row.get("capabilityCoverage") or {}).get("count") or 0) == best_capabilities
    ]
    rationale.append(f"essentialCapabilities={best_capabilities}/{len(CAPABILITY_GROUPS)}")
    if len(finalists) > 1:
        measured = [row for row in finalists if isinstance(row.get("medianExecutionMs"), int)]
        if measured:
            fastest = min(int(row["medianExecutionMs"]) for row in measured)
            finalists = [row for row in measured if row.get("medianExecutionMs") == fastest]
            rationale.append(f"medianExecutionMs={fastest}")
    if len(finalists) != 1:
        return {
            "status": "tie",
            "harnessId": None,
            "finalists": [row["harnessId"] for row in finalists],
            "rationale": "; ".join(rationale),
        }
    winner = finalists[0]
    return {
        "status": "measured-leader",
        "harnessId": winner["harnessId"],
        "label": winner["label"],
        "rationale": "; ".join(rationale),
    }
