"""Independently verify the frozen live cross-harness comparison receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from grant_agent.harness_comparison import (
    PROTOCOL_ID,
    SCHEMA,
    TASKS,
    WINNER_RULE,
    grade_output,
    select_leader,
    summarize_attempts,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify(proof_dir: Path, *, require_live: bool, require_neyvia_leader: bool) -> dict[str, Any]:
    report_path = proof_dir / "comparison.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    _require(report.get("schema") == SCHEMA, "Comparison schema is not canonical.")
    _require(report.get("protocolId") == PROTOCOL_ID, "Comparison protocol is not frozen.")
    _require(report.get("winnerRule") == WINNER_RULE, "Winner rule changed after measurement.")
    _require(len(report.get("tasks") or []) == len(TASKS) >= 2, "Comparison task sample is incomplete.")
    for fixture in report.get("fixtures") or []:
        path = Path(__file__).resolve().parents[1] / str(fixture.get("path") or "")
        _require(path.is_file(), f"Fixture is missing: {path}")
        _require(hashlib.sha256(path.read_bytes()).hexdigest() == fixture.get("sha256"), f"Fixture changed: {path}")
    included = {
        str(row.get("harnessId"))
        for row in report.get("eligibility") or []
        if row.get("included") is True
    }
    _require(len(included) >= 2, "Comparison has fewer than two eligible harnesses.")
    excluded = [row for row in report.get("eligibility") or [] if row.get("included") is not True]
    _require(all(str(row.get("reason") or "").strip() for row in excluded), "An exclusion has no reason.")
    attempts = report.get("attempts") or []
    expected_pairs = {(harness_id, task["id"]) for harness_id in included for task in TASKS}
    actual_pairs = {(str(row.get("harnessId")), str(row.get("taskId"))) for row in attempts}
    _require(actual_pairs == expected_pairs, "Eligible harness/task attempt coverage is incomplete or inflated.")
    recomputed_attempts = []
    for attempt in attempts:
        task_id = str(attempt.get("taskId"))
        grade = grade_output(task_id, attempt.get("output"))
        _require(grade == attempt.get("grade"), f"Stored grade is not reproducible: {attempt.get('jobId')}")
        if attempt.get("receiptFile"):
            receipt_path = proof_dir / str(attempt["receiptFile"])
            _require(receipt_path.is_file(), f"Raw receipt is missing: {receipt_path}")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            _require(receipt.get("id") == attempt.get("jobId"), "Raw receipt job id does not match attempt.")
            _require(receipt.get("status") == attempt.get("status"), "Raw receipt status does not match attempt.")
        if require_live:
            _require(str(attempt.get("jobId") or "").startswith("harness-job-"), "A live attempt has no durable job id.")
            _require(attempt.get("status") in {"completed", "failed", "cancelled"}, "A live attempt is not terminal.")
            _require(bool(attempt.get("receiptFile")), "A live attempt has no raw terminal receipt.")
        recomputed_attempts.append(attempt)
    catalog_harnesses = report.get("catalogHarnesses") or []
    _require(bool(catalog_harnesses), "Comparison has no captured catalog evidence.")
    recomputed_summaries = summarize_attempts(catalog_harnesses, recomputed_attempts)
    _require(
        recomputed_summaries == (report.get("summaries") or []),
        "Stored summaries are not reproducible from raw attempts and catalog evidence.",
    )
    leader = select_leader(recomputed_summaries)
    _require(leader == report.get("leader"), "Stored leader is not reproducible from summary metrics.")
    if require_neyvia_leader:
        _require(leader.get("status") == "measured-leader", "Comparison has no unique measured leader.")
        _require(leader.get("harnessId") == "neyvia-agent", "Neyvia is not the measured leader.")
    return {
        "eligibleHarnesses": len(included),
        "excludedHarnesses": len(excluded),
        "attempts": len(attempts),
        "leader": leader,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-dir", type=Path, required=True)
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--require-neyvia-leader", action="store_true")
    args = parser.parse_args()
    summary = verify(
        args.proof_dir.resolve(),
        require_live=args.require_live,
        require_neyvia_leader=args.require_neyvia_leader,
    )
    print(json.dumps(summary, sort_keys=True))
    print("harness comparison verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
