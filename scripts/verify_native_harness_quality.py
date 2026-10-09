#!/usr/bin/env python3
"""Independently verify Neyvia Native's frozen generalization evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXPECTED_PROTOCOL = "neyvia-native-generalization-v1"
EXPECTED_TASK_IDS = (
    "manifest-reasoning",
    "boundary-debug",
    "route-contract-audit",
    "completion-control-design",
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _attempts(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(attempt.get("taskId") or ""): attempt
        for attempt in report.get("attempts") or []
        if isinstance(attempt, dict)
    }


def _total_execution_ms(report: dict[str, Any]) -> int:
    return sum(
        int((attempt.get("metrics") or {}).get("executionDurationMs") or 0)
        for attempt in report.get("attempts") or []
        if isinstance(attempt, dict)
    )


def verify(proof_dir: Path) -> dict[str, Any]:
    baseline = _read(proof_dir / "baseline.json")
    candidate = _read(proof_dir / "candidate.json")
    rejected = _read(proof_dir / "completion-gate.json")
    decision = _read(proof_dir / "decision.json")

    reports = (baseline, candidate, rejected)
    for report in reports:
        _require(
            report.get("protocolId") == EXPECTED_PROTOCOL,
            "A report uses the wrong frozen protocol.",
        )
        task_ids = tuple(str(task.get("id") or "") for task in report.get("tasks") or [])
        _require(task_ids == EXPECTED_TASK_IDS, "The frozen task order or membership changed.")
        _require(
            all(
                str((report.get("exactRoute") or {}).get(key) or "") == expected
                for key, expected in {
                    "harness": "neyvia-agent",
                    "provider": "opencode-go",
                    "model": "deepseek-v4-flash",
                    "transport": "chat-completions",
                }.items()
            ),
            "A report changed the exact native route.",
        )
        _require(
            (report.get("exactRoute") or {}).get("fallbackAllowed") is False,
            "A report permits provider fallback.",
        )

    baseline_summary = baseline.get("summary") or {}
    candidate_summary = candidate.get("summary") or {}
    rejected_summary = rejected.get("summary") or {}
    _require(baseline_summary.get("completed") == 2, "Baseline completion count drifted.")
    _require(baseline_summary.get("score") == 156, "Baseline score drifted.")
    _require(candidate_summary.get("completed") == 4, "Accepted candidate did not complete all tasks.")
    _require(candidate_summary.get("routeHonest") == 4, "Accepted candidate substituted a route.")
    _require(candidate_summary.get("score") == 320, "Accepted candidate score drifted.")
    _require(candidate_summary.get("maximum") == 328, "Accepted candidate maximum drifted.")
    _require(
        float(candidate_summary.get("ratio") or 0) - float(baseline_summary.get("ratio") or 0) >= 0.49,
        "Accepted candidate improvement is smaller than the measured gain.",
    )

    baseline_attempts = _attempts(baseline)
    candidate_attempts = _attempts(candidate)
    _require(
        all(baseline_attempts[task_id].get("status") == "failed" for task_id in EXPECTED_TASK_IDS[2:]),
        "The baseline no longer contains both higher-difficulty failures.",
    )
    _require(
        all(candidate_attempts[task_id].get("status") == "completed" for task_id in EXPECTED_TASK_IDS),
        "The accepted candidate is missing a completed task.",
    )
    hard_runtime = int(
        (candidate_attempts["route-contract-audit"].get("metrics") or {}).get("executionDurationMs")
        or 0
    )
    _require(
        hard_runtime > 120_000,
        "The hard-task proof does not demonstrate survival beyond the former 120-second deadline.",
    )

    accepted_total = _total_execution_ms(candidate)
    rejected_total = _total_execution_ms(rejected)
    _require(
        rejected_summary.get("score") == candidate_summary.get("score"),
        "The completion-gate experiment no longer has the recorded no-gain score.",
    )
    _require(
        rejected_total > int(accepted_total * 1.2),
        "The completion-gate rejection is not backed by its measured latency cost.",
    )
    _require(
        str((decision.get("rejected") or {}).get("commit") or "") == "ebcfa1f",
        "The rejected experiment commit is missing from the decision receipt.",
    )

    result = {
        "schema": "neyvia.native-harness-quality-verification/v1",
        "status": "verified",
        "protocolId": EXPECTED_PROTOCOL,
        "baseline": {
            "completed": baseline_summary.get("completed"),
            "score": baseline_summary.get("score"),
            "maximum": baseline_summary.get("maximum"),
        },
        "accepted": {
            "completed": candidate_summary.get("completed"),
            "routeHonest": candidate_summary.get("routeHonest"),
            "score": candidate_summary.get("score"),
            "maximum": candidate_summary.get("maximum"),
            "hardAuditExecutionMs": hard_runtime,
            "totalExecutionMs": accepted_total,
        },
        "rejected": {
            "score": rejected_summary.get("score"),
            "maximum": rejected_summary.get("maximum"),
            "totalExecutionMs": rejected_total,
        },
        "marker": "NEYVIA_NATIVE_GENERALIZATION_IMPROVED",
    }
    (proof_dir / "verification.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-dir", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.proof_dir.resolve())
    print(json.dumps(result, ensure_ascii=False))
    print(result["marker"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
