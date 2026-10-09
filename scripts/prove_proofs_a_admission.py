"""Prove owned coverage admission refuses stale or unobserved evidence."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    from grant_agent.durability import atomic_write_json
    from grant_agent.proof_contracts import file_digest
    from grant_agent.proof_coverage import record_coverage, retirement_gate
    from grant_agent.proof_verifier import coverage_report

    scope = json.loads((REPO / "config/proofs-a/scope.json").read_text(encoding="utf-8"))
    inventory_path = REPO / "config/proofs/test-inventory.json"
    inventory_bytes = inventory_path.read_bytes()
    inventory = json.loads(inventory_bytes)
    original = json.loads(args.receipt.read_text(encoding="utf-8"))
    baseline = coverage_report()
    if baseline["invalidMappings"]:
        raise RuntimeError("Reconcile current evidence before checking rejection paths")
    root = REPO / ".agent_control/proofs-a/admission"
    root.mkdir(parents=True, exist_ok=True)
    observations = []

    def refuse(receipt, identity):
        path = root / (identity + ".json")
        atomic_write_json(path, receipt)
        try:
            record_coverage(path, paths=scope)
        except ValueError as exc:
            observations.append({"id": identity, "passed": True, "reason": str(exc)})
        else:
            raise RuntimeError("Untrusted evidence was admitted: " + identity)
        if inventory_path.read_bytes() != inventory_bytes:
            raise RuntimeError("Rejected evidence changed the coverage inventory")

    changed = copy.deepcopy(original)
    changed["sourceStable"] = False
    refuse(changed, "unstable-source-refused")
    changed = copy.deepcopy(original)
    changed["sourceBindings"]["src/grant_agent/proof_contracts.py"] = "0" * 64
    refuse(changed, "foreign-source-binding-refused")
    changed = copy.deepcopy(original)
    area = next(row for row in changed["areas"] if row["area"] == "a-livecontrol")
    area["contracts"] = []
    refuse(changed, "unobserved-contract-refused-before-map-write")

    manifest = REPO / "config/proofs/a-livecontrol.json"
    exact = manifest.read_bytes()
    expected = {case["id"] for row in inventory["files"] if row["path"] in scope
                for case in row["cases"] if case.get("manifest") == manifest.relative_to(REPO).as_posix()}
    if not expected:
        raise RuntimeError("Owned manifest has no recorded coverage to challenge")
    tampered = exact + b" "  # Valid JSON; tests admission rather than parsing.
    manifest.write_bytes(tampered)
    try:
        stale = coverage_report()
        rejected = {row["case"] for row in stale["invalidMappings"]}
        if rejected != expected:
            raise RuntimeError("Manifest-byte drift did not reject precisely its mapped cases")
        observations.append({"id": "changed-owned-manifest-refused", "passed": True,
                             "rejectedCases": sorted(rejected)})
    finally:
        if manifest.read_bytes() != tampered:
            raise RuntimeError("Concurrent manifest edit; preserved for review")
        manifest.write_bytes(exact)
    if coverage_report()["invalidMappings"]:
        raise RuntimeError("Exact manifest restoration did not restore admission")
    pending = next((row["path"] for row in inventory["files"]
                    if row["path"] in scope and row["disposition"] != "covered"
                    and (REPO / row["path"]).is_file()), None)
    if pending:
        try:
            retirement_gate([pending])
        except ValueError:
            observations.append({"id": "uncovered-owned-test-retirement-refused", "passed": True, "test": pending})
        else:
            raise RuntimeError("An uncovered owned test was admitted for deletion")
    if inventory_path.read_bytes() != inventory_bytes:
        raise RuntimeError("Admission journey changed the inventory")
    result = {"schema": "neyvia.proofs-a.admission.v1", "ok": True,
              "observations": observations, "inventoryUnchanged": True,
              "restoredManifestSha256": file_digest(manifest),
              "authority": "Own manifest restored byte-for-byte; rejected receipt copies never changed coverage"}
    atomic_write_json(args.output, result)
    print(json.dumps({"ok": True, "observations": len(observations), "receipt": str(args.output)}))


if __name__ == "__main__":
    main()
