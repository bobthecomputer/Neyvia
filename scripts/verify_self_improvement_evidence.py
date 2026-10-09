from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / ".agent_control" / "self_improvement_evidence"
HISTORY = EVIDENCE_DIR / "red_team_escalation_history.jsonl"


def _history_rows() -> list[dict]:
    if not HISTORY.is_file():
        return []
    rows = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
        except json.JSONDecodeError:
            continue
    return rows


def record_red_team_sample(*, scenario: str, outcome: str, operator_value_feedback: str) -> dict:
    sample = {
        "schema": "fluxio.self_improvement_red_team_sample.v1",
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario,
        "outcome": outcome,
        "operator_value_feedback": operator_value_feedback,
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
    return sample


def build_self_improvement_evidence() -> dict:
    rows = _history_rows()
    useful = [row for row in rows if str(row.get("operator_value_feedback") or "").strip()]
    escalation_audit = {
        "sampleCount": len(rows),
        "distinctScenarioCount": len({str(row.get("scenario") or "") for row in rows}),
        "hasOperatorValueFeedback": bool(useful),
    }
    return {
        "schema": "fluxio.self_improvement_evidence.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if useful else "insufficient_evidence",
        "sampleCount": len(rows),
        "operatorFeedbackCount": len(useful),
        "escalationAudit": escalation_audit,
        "historyPath": str(HISTORY.relative_to(ROOT)).replace("\\", "/"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify evidence that Neyvia's self-improvement loop produced operator value.")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--record-red-team-sample", action="store_true")
    parser.add_argument("--scenario", default="")
    parser.add_argument("--outcome", default="")
    parser.add_argument("--operator-value-feedback", default="")
    args = parser.parse_args()
    if args.record_red_team_sample:
        if not args.scenario or not args.outcome:
            parser.error("--scenario and --outcome are required when recording a sample")
        record_red_team_sample(
            scenario=args.scenario,
            outcome=args.outcome,
            operator_value_feedback=args.operator_value_feedback,
        )
    receipt = build_self_improvement_evidence()
    if args.write:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / "latest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
