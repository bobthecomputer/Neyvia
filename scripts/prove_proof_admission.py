"""Exercise suite-scope admission against a real temporary source file."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main(*, evidence_path="scripts/evidence/PROOFS-admission.json"):
    from grant_agent.proof_verifier import coverage_report
    from grant_agent.durability import atomic_write_json
    baseline = coverage_report()
    if baseline["newScopedFiles"] or baseline["invalidMappings"]:
        raise RuntimeError("Existing scope/evidence violation must be reconciled first")
    path = REPO / "tests" / ("proofs-admission-" + uuid.uuid4().hex + ".test.mjs")
    content = b"export const contractFixture = true;\n"
    with path.open("xb") as fixture:
        fixture.write(content)
    try:
        changed = coverage_report()
        expected = path.relative_to(REPO).as_posix()
        if changed["newScopedFiles"] != [expected]:
            raise RuntimeError("New scoped test file escaped admission")
    finally:
        if path.read_bytes() != content:
            raise RuntimeError("Fixture changed unexpectedly; preserved for review: " + str(path))
        path.unlink()  # Only the exact new disposable bytes owned by this script.
    restored = coverage_report()
    if restored["newScopedFiles"] != baseline["newScopedFiles"]:
        raise RuntimeError("Scope did not recover after exact fixture cleanup")
    manifest = REPO / "config/proofs/awareness.json"
    original = manifest.read_bytes()
    changed_manifest = original + b" "  # Valid JSON; behavior stays identical but evidence is stale.
    manifest.write_bytes(changed_manifest)
    try:
        stale = coverage_report()
        cases = [row["case"] for row in stale["invalidMappings"]]
        if len(cases) != 4 or not all(case.startswith("tests/test_neyvia_awareness.py::") for case in cases):
            raise RuntimeError("Changed coverage manifest escaped evidence admission")
    finally:
        if manifest.read_bytes() != changed_manifest:
            raise RuntimeError("Manifest changed unexpectedly; preserved for review")
        manifest.write_bytes(original)
    reconciled = coverage_report()
    if reconciled["invalidMappings"]:
        raise RuntimeError("Exact manifest restoration did not recover admission")
    receipt = {"schema": "neyvia.proofs.scope-admission.v1", "ok": True,
        "newFileDetected": expected, "fixtureRemoved": not path.exists(),
        "baselineRemainingFiles": baseline["remainingScopedFiles"],
        "staleEvidenceRejectedCases": cases,
        "invalidMappings": restored["invalidMappings"], "inventoryError": restored["inventoryError"]}
    atomic_write_json(REPO / evidence_path, receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
