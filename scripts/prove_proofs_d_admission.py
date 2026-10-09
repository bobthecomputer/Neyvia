"""Exercise coverage admission refusals without retiring any test."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    from grant_agent.durability import atomic_write_json
    from grant_agent.proof_contracts import source_bindings
    from grant_agent.proof_coverage import record_coverage, retirement_gate
    from grant_agent.proof_verifier import coverage_report
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs

    started = time.perf_counter()
    scope = set(json.loads((REPO / "config/proofs-d-scope.json").read_text(encoding="utf-8")))
    inventory_path = REPO / "config/proofs/test-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    original = json.loads(subprocess.run(["git", "show", "HEAD:config/proofs/test-inventory.json"],
        cwd=REPO, check=True, capture_output=True, text=True,
        **hidden_windows_subprocess_kwargs()).stdout)
    foreign = {row["path"]: row for row in original["files"] if row["path"] not in scope}
    if foreign != {row["path"]: row for row in inventory["files"] if row["path"] not in scope}:
        raise RuntimeError("Another owner's inventory rows changed")
    report = json.loads(args.receipt.read_text(encoding="utf-8"))
    if not report["contractsOk"] or not report["sourceStable"] or report["sourceBindings"] != source_bindings():
        raise RuntimeError("Requires a passing, current, source-bound verification")
    observations = [{"id": "other-owner-inventory-rows-preserved", "passed": True}]

    def refuses(operation, identity, expected):
        try:
            operation()
        except ValueError as error:
            if expected not in str(error):
                raise
            observations.append({"id": identity, "passed": True, "reason": str(error)})
        else:
            raise RuntimeError("Admission unexpectedly accepted " + identity)

    remaining = [row for row in inventory["files"] if row["path"] in scope and row["disposition"] != "covered"]
    if not remaining:
        raise RuntimeError("Expected explicit incomplete cases in this bounded migration")
    refuses(lambda: retirement_gate([remaining[0]["path"]]), "partial-file-retirement-refused", "complete coverage")
    candidates = [row for row in inventory["files"] if row["path"] in scope and row["disposition"] == "covered"
                  and (REPO / row["path"]).is_file()]
    allowed = retirement_gate([row["path"] for row in candidates])
    observations.append({"id": "complete-current-originals-admitted", "passed": True, "files": len(allowed)})
    candidate = candidates[0]
    target = REPO / candidate["path"]
    before = target.read_bytes()
    try:
        target.write_bytes(before + b"\n# disposable admission perturbation\n")
        refuses(lambda: retirement_gate([candidate["path"]]), "changed-original-retirement-refused", "unchanged original")
    finally:
        target.write_bytes(before)

    manifest = REPO / candidate["cases"][0]["manifest"]
    before = manifest.read_bytes()
    try:
        manifest.write_bytes(before + b"\n")
        refuses(lambda: retirement_gate([candidate["path"]]), "changed-manifest-retirement-refused", "evidence changed")
        changed = coverage_report(current_runs=report["areas"], verified_sources=report["sourceBindings"])
        identities = {case["id"] for case in candidate["cases"]}
        failures = [row for row in changed["invalidMappings"] if row["case"] in identities]
        if not failures or not all("evidence changed" in row["reason"] for row in failures):
            raise RuntimeError("Fresh revalidation admitted a changed declaration manifest")
        observations.append({"id": "fresh-runs-cannot-admit-changed-manifest", "passed": True})
    finally:
        manifest.write_bytes(before)

    scratch = REPO / ".agent_control/proofs-d/admission"
    scratch.mkdir(parents=True, exist_ok=True)
    stale = {**report, "sourceBindings": {}}
    stale_path = scratch / "stale-receipt.json"
    atomic_write_json(stale_path, stale)
    refuses(lambda: record_coverage(stale_path, tests=scope), "stale-source-receipt-refused", "current proof source")
    if inventory_path.read_text(encoding="utf-8") != json.dumps(inventory, ensure_ascii=False, indent=2) + "\n":
        # Compare parsed data because the atomic writer's JSON formatting is not an admission invariant.
        if json.loads(inventory_path.read_text(encoding="utf-8")) != inventory:
            raise RuntimeError("Rejected admission modified the inventory")
    valid = coverage_report(current_runs=report["areas"], verified_sources=report["sourceBindings"])
    if valid["invalidMappings"] or valid["uncoveredDeletedFiles"]:
        raise RuntimeError("Restored source no longer verifies")
    retirement_gate([row["path"] for row in candidates])
    observations.append({"id": "exact-restoration-and-valid-coverage", "passed": True})
    evidence = {"schema": "neyvia.proofs.admission.v1", "ok": True, "observations": observations,
                "eligibleFiles": [row["path"] for row in candidates], "retainedFiles": [row["path"] for row in remaining],
                "durationMs": round((time.perf_counter() - started) * 1000)}
    atomic_write_json(REPO / "scripts/evidence/PROOFS-d-admission.json", evidence)
    print(json.dumps({"ok": True, "checks": len(observations), "eligibleFiles": len(candidates)}))


if __name__ == "__main__":
    main()
