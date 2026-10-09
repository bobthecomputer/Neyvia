"""Audit Paul's exact PROOFS-b share and publish a compact evidence receipt."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

SCOPE = tuple("tests/test_" + name + ".py" for name in """
dashboard debugger_bundle delivery_receipt demo_runner dependency_inventory
desktop_bridge desktop_gateway desktop_ui_contract doc_ingestion
ecosystem_evidence_lifecycle ecosystem_fabric efficient_workflow encrypted_chat
engine eval fake_running_watchdog feature_suggester flight_recorder fluxio_harness
folder_sync git_reference_adapter github_release_source github_workflow_publication_integrity
glm_ocr_adapter glm_ui_redesign_proof handoff harness_blocked_ui_contract
harness_comparison harness_execution_capacity harness_execution_capacity_ui_contract
harness_job_admission harness_job_blocked_lifecycle harness_job_budget_cancellation
harness_job_lifecycle harness_job_lock_recovery harness_job_runtime_budget
harness_job_runtime_budget_limits harness_jobs harness_registry html_site_benchmark
""".split())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--host-receipt", type=Path)
    args = parser.parse_args()
    from grant_agent.durability import atomic_write_json
    from grant_agent.proof_contracts import file_digest, source_bindings
    from grant_agent.proof_verifier import coverage_report
    receipt_path = args.receipt.resolve()
    verification = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not verification["sourceStable"] or verification["sourceBindings"] != source_bindings():
        raise RuntimeError("Summary requires fresh, stable verification bound to current source")
    inventory = json.loads((REPO / "config/proofs/test-inventory.json").read_text(encoding="utf-8"))
    indexed = {row["path"]: row for row in inventory["files"]}
    rows = []
    for name in SCOPE:
        row = indexed[name]
        mapped = sum(bool(c["contract_ids"] and c["checked_at"] and c["self_checks"]) for c in row["cases"])
        deleted = not (REPO / name).exists()
        if deleted and (mapped != len(row["cases"]) or row["disposition"] != "covered"):
            raise RuntimeError("Uncovered deletion in owned share: " + name)
        rows.append({"file": name, "cases": len(row["cases"]), "mapped": mapped,
                     "deleted": deleted, "disposition": row["disposition"],
                     "pendingCases": [c["name"] for c in row["cases"] if not c["contract_ids"]]})
    live = coverage_report()
    total, mapped = sum(r["cases"] for r in rows), sum(r["mapped"] for r in rows)
    owned_areas = [r for r in verification["areas"] if r["area"].startswith("proofs-b-")]
    host = None
    if args.host_receipt:
        path = args.host_receipt.resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("ok") or not 48471 <= data["port"] <= 48479:
            raise RuntimeError("Host receipt must prove an owned PROOFS-b port")
        host_verification = data["verification"]
        if (not host_verification.get("sourceStable")
                or host_verification.get("sourceBindings") != source_bindings()
                or not host_verification.get("contractsOk")):
            raise RuntimeError("Host journey must prove the current source with passing contracts")
        host = {"path": path.relative_to(REPO).as_posix(), "sha256": file_digest(path),
                "observations": data["observations"], "durationMs": data["durationMs"], "port": data["port"]}
    evidence = {"schema": "neyvia.proofs-b.v1", "complete": mapped == total and all(r["deleted"] for r in rows),
        "contractsOk": verification["contractsOk"] and not live["invalidMappings"] and not live["uncoveredDeletedFiles"],
        "verification": {"path": receipt_path.relative_to(REPO).as_posix(), "sha256": file_digest(receipt_path),
                         "durationMs": verification["durationMs"], "failures": verification["failures"],
                         "blockedManualEntries": verification["blocked"], "complete": verification["complete"]},
        "share": {"files": len(rows), "cases": total, "mappedCases": mapped, "pendingCases": total - mapped,
                  "coveragePercent": round(100 * mapped / total, 3),
                  "contractsAdded": sum(len(r["contracts"]) for r in owned_areas),
                  "deletedCases": sum(r["cases"] for r in rows if r["deleted"]),
                  "deletedFiles": [r["file"] for r in rows if r["deleted"]]},
        "areas": owned_areas,
        "files": rows, "hostJourney": host,
        "limitations": ["Partial migration is not whole-suite replacement or an equivalent full-suite timing comparison",
                        "Unmapped tests remain; external provider/native/rendered UI journeys are not inferred from local fixtures"]}
    atomic_write_json(REPO / "scripts/evidence/PROOFS-b.json", evidence)
    print(json.dumps({"contractsOk": evidence["contractsOk"], "share": evidence["share"],
                      "durationMs": verification["durationMs"], "receipt": "scripts/evidence/PROOFS-b.json"}))
    return 0 if evidence["contractsOk"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
