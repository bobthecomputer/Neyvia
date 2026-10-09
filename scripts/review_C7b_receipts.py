"""Independently reconcile the C7b real-run receipt with its frozen baseline."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    report_path = REPO / "scripts/evidence/C7b.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    baseline_path = REPO / report["baseline"]["path"]
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    require(hashlib.sha256(baseline_path.read_bytes()).hexdigest() == report["baseline"]["sha256"], "Original C7 receipt changed")
    rows = report["semanticCoverage"]
    require(len(rows) == report["inventory"]["semanticContracts"] * len(report["categories"]), "Semantic obligations were dropped")
    current = {(row["contract"], row["category"]): row for row in rows}
    require(len(current) == len(rows), "Duplicate semantic obligation")
    require({(row["contract"], row["category"]) for row in baseline["semanticCoverage"]} <= current.keys(), "Original obligation vanished")
    journeys = {row["id"]: row for row in report["journeys"]}
    require(len(journeys) == len(report["journeys"]), "Duplicate journey identity")
    for row in rows:
        cases = [journeys[identity] for identity in row["cases"]]
        require(all(row["contract"] in case["contracts"] and row["category"] == case["category"] for case in cases), "Wrong semantic binding")
        if row["status"] == "passed":
            require(any(case["status"] == "passed" for case in cases) and not any(case["status"] == "failed" for case in cases), "Passed obligation has no passing real case")
        elif row["status"] == "blocked":
            require(bool(row.get("reason")) and bool(row.get("blockerKind")), "Blocked pair has no exact remaining requirement")
        else:
            raise ValueError("Final semantic campaign still has failures")
    require(not report["failures"] and report["sourceStable"] and report["ok"], "Campaign failed or its source changed")
    from grant_agent.proof_contracts import source_digest
    require(all(source_digest(REPO / name) == digest for name, digest in report["sourceBindings"].items()), "Campaign source is now stale")
    host_path = REPO / report["hostProof"]["path"]
    require(hashlib.sha256(host_path.read_bytes()).hexdigest() == report["hostProof"]["sha256"], "Host proof bytes changed")
    host = json.loads(host_path.read_text(encoding="utf-8"))
    require(host["ok"] and len(host["manualChecks"]) == 2 and all(check["passed"] for check in host["manualChecks"]), "Actual manual did not complete")
    require(host["staleBindingRefused"]["ok"] is False and host["corruptReceiptRefused"]["ok"] is False, "Receipt tampering escaped host validation")
    require(report["complete"] == all(row["status"] == "passed" for row in rows), "Completion overstates semantic evidence")
    summary = {"schema": "neyvia.c7b-review.v1", "ok": True,
               "receiptSha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
               "baseline": report["baseline"], "counts": report["counts"],
               "unresolved": dict(Counter(row.get("blockerKind") for row in rows if row["status"] == "blocked")),
               "sourceBindingsCurrent": True, "hostManualCompleted": True,
               "semanticComplete": report["complete"]}
    (REPO / "scripts/evidence/C7b-review.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
