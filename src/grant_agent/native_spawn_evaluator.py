"""Independent contract/evidence evaluation for Neyvia Native child agents."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


EVALUATION_SCHEMA = "neyvia.native-spawn-evaluation/v1"


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load(value: str | Path | dict[str, Any]) -> tuple[dict[str, Any], str]:
    if isinstance(value, dict):
        return dict(value), "inline"
    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8")), str(path)


def evaluate_spawn_receipt(
    value: str | Path | dict[str, Any],
    *,
    expected_parent_session_id: str = "",
    expected_plan_hash: str = "",
    required_evidence: Iterable[str] = (),
) -> dict[str, Any]:
    receipt, source = _load(value)
    failures: list[str] = []
    warnings: list[str] = []
    schema = str(receipt.get("schema") or "")
    if schema != "neyvia.native-spawn-receipt/v1":
        failures.append(f"unexpected schema: {schema or 'missing'}")
    if expected_parent_session_id and receipt.get("parentSessionId") != expected_parent_session_id:
        failures.append("parent session does not match the evaluator contract")
    if expected_plan_hash and receipt.get("planHash") != expected_plan_hash:
        failures.append("behavior plan hash does not match the evaluator contract")
    status = str(receipt.get("status") or "")
    if status != "completed":
        failures.append(f"child status is {status or 'missing'}, not completed")
    if not receipt.get("contractHash"):
        failures.append("spawn contract hash is missing")
    if not receipt.get("receiptHash"):
        failures.append("spawn receipt hash is missing")
    route = receipt.get("route") or {}
    for key in ("role", "provider", "model", "effort", "maximumTurns", "allowMutations"):
        if key not in route:
            failures.append(f"route field is missing: {key}")
    role = str(receipt.get("role") or route.get("role") or "")
    if role != "executor" and route.get("allowMutations") is True:
        failures.append("a non-executor child received mutation authority")
    output = str(receipt.get("output") or "")
    if not output.strip():
        failures.append("child returned no output")
    supplied_output_hash = str(receipt.get("outputHash") or "")
    if output and supplied_output_hash != hashlib.sha256(output.encode("utf-8")).hexdigest():
        failures.append("child output hash does not match the output")
    if receipt.get("error"):
        failures.append("child receipt contains a runtime error")
    requested_evidence = [str(item).strip().lower() for item in required_evidence if str(item).strip()]
    if not requested_evidence:
        requested_evidence = [
            str(item).strip().lower()
            for item in route.get("requiredEvidence") or ()
            if str(item).strip()
        ]
    output_lower = output.lower()
    present = [item for item in requested_evidence if item in output_lower]
    absent = [item for item in requested_evidence if item not in output_lower]
    if absent:
        warnings.append(
            "The output does not explicitly name all requested evidence labels; inspect the semantic result before promotion."
        )
    usage = receipt.get("usage") or {}
    if not usage.get("reportedByTransport"):
        warnings.append("The child transport did not report token usage.")
    run_items = receipt.get("runItems") or []
    if not run_items:
        warnings.append("No child run-item types were preserved.")
    contract_valid = not any(
        "schema" in failure
        or "session" in failure
        or "plan hash" in failure
        or "contract hash" in failure
        or "route field" in failure
        or "mutation authority" in failure
        for failure in failures
    )
    evidence_sufficient = bool(output.strip()) and status == "completed" and not receipt.get("error")
    accepted = contract_valid and evidence_sufficient and not failures
    result = {
        "schema": EVALUATION_SCHEMA,
        "spawnId": receipt.get("spawnId"),
        "source": source,
        "role": role,
        "model": route.get("model"),
        "effort": route.get("effort"),
        "contractValid": contract_valid,
        "evidenceSufficient": evidence_sufficient,
        "accepted": accepted,
        "status": "accepted" if accepted else "rejected",
        "requiredEvidence": requested_evidence,
        "explicitEvidenceLabelsPresent": present,
        "explicitEvidenceLabelsAbsent": absent,
        "failures": failures,
        "warnings": warnings,
        "truthBoundary": (
            "This evaluator proves route/lineage/receipt integrity and minimum evidence shape. "
            "It does not infer general intelligence or subjective answer quality from a pleasant response."
        ),
    }
    result["evaluationHash"] = _hash(result)
    from .proofs_d_native import check_evaluation
    check_evaluation(receipt, result, expected_parent_session_id, expected_plan_hash)
    return result


def evaluate_spawn_tree(
    spawn_tree: dict[str, Any],
    *,
    expected_plan_hash: str = "",
) -> dict[str, Any]:
    parent = str(spawn_tree.get("parentSessionId") or "")
    evaluations: list[dict[str, Any]] = []
    for child in spawn_tree.get("children") or []:
        receipt_path = str(child.get("receipt_path") or child.get("receiptPath") or "")
        if not receipt_path:
            evaluations.append(
                {
                    "schema": EVALUATION_SCHEMA,
                    "spawnId": child.get("spawn_id") or child.get("spawnId"),
                    "accepted": False,
                    "status": "pending",
                    "failures": ["child has no finished receipt"],
                    "warnings": [],
                }
            )
            continue
        try:
            evaluations.append(
                evaluate_spawn_receipt(
                    receipt_path,
                    expected_parent_session_id=parent,
                    expected_plan_hash=expected_plan_hash,
                )
            )
        except Exception as exc:
            evaluations.append(
                {
                    "schema": EVALUATION_SCHEMA,
                    "spawnId": child.get("spawn_id") or child.get("spawnId"),
                    "accepted": False,
                    "status": "rejected",
                    "failures": [f"receipt could not be evaluated: {type(exc).__name__}: {exc}"],
                    "warnings": [],
                }
            )
    accepted = sum(1 for row in evaluations if row.get("accepted"))
    rejected = sum(1 for row in evaluations if row.get("status") == "rejected")
    pending = sum(1 for row in evaluations if row.get("status") == "pending")
    result = {
        "schema": "neyvia.native-spawn-tree-evaluation/v1",
        "parentSessionId": parent,
        "expectedPlanHash": expected_plan_hash,
        "evaluations": evaluations,
        "counts": {
            "total": len(evaluations),
            "accepted": accepted,
            "rejected": rejected,
            "pending": pending,
        },
        "allAccepted": bool(evaluations) and accepted == len(evaluations),
    }
    result["evaluationHash"] = _hash(result)
    return result
