"""Observe fail-closed coverage admission and source revalidation using owned fixtures."""
from __future__ import annotations

import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    from prove_proof_admission import main as scope_journey
    from grant_agent.proof_coverage import REVALIDATION
    from grant_agent.proof_verifier import coverage_report
    from grant_agent.durability import atomic_write_json
    scope_journey(evidence_path="scripts/evidence/PROOFS-b-scope-admission.json")
    before = coverage_report()
    original = REVALIDATION.read_bytes()
    evidence = json.loads(original)
    identities = set(evidence["cases"])
    evidence["receiptSha256"] = "0" * 64
    changed = (json.dumps(evidence, indent=2) + "\n").encode("utf-8")
    REVALIDATION.write_bytes(changed)
    try:
        refused = coverage_report()
        failed = {r["case"] for r in refused["invalidMappings"]}
        if failed != identities or refused["revalidatedCases"]:
            raise RuntimeError("Tampered revalidation evidence did not fail closed")
    finally:
        if REVALIDATION.read_bytes() != changed:
            raise RuntimeError("Revalidation fixture changed unexpectedly; preserved for review")
        REVALIDATION.write_bytes(original)
    after = coverage_report()
    if after != before:
        raise RuntimeError("Restoring exact evidence did not restore coverage admission")
    receipt = {"schema": "neyvia.proofs-b.admission.v1", "ok": True,
        "unchangedPriorCases": len(identities), "tamperedEvidenceRejectedCases": sorted(failed),
        "exactRestorationPassed": True, "coverage": after,
        "scopeAdmission": "scripts/evidence/PROOFS-b-scope-admission.json"}
    atomic_write_json(REPO / "scripts/evidence/PROOFS-b-admission.json", receipt)
    print(json.dumps({"ok": True, "rejectedTamperedCases": len(failed), "receipt": "scripts/evidence/PROOFS-b-admission.json"}))


if __name__ == "__main__":
    main()
