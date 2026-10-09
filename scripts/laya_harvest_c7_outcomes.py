"""Harvest deduplicated, explicit operation outcomes from C7 receipts."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.laya_curriculum import outcome_input  # noqa: E402

C7 = Path(r"C:\Users\user\Projects\nx-c7-edge\scripts\evidence\C7.json")
ROOT = C7.parents[2]
OUTPUT = Path(r"D:\NeyviaRuns\laya-train\review\wave2\c7-outcomes.json")
FAILURE_STATES = {"failed", "failure", "error", "blocked", "refused", "rejected", "denied"}
FAILURE_CODES = {"permission_denied", "not_permitted", "tab_not_granted", "refused", "rejected", "denied"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def explicit_negative(value: Any) -> bool:
    """Read only outcome-bearing fields; never infer from arbitrary prose."""
    if isinstance(value, dict):
        for key, item in value.items():
            low = key.lower()
            if low in {"ok", "allowed", "granted", "permitted", "expectationmet"} and item is False:
                return True
            if low in {"refused", "rejected", "denied"} and item is True:
                return True
            if low == "verdict" and item == "unverified":
                return True
            if low in {"status", "state"} and isinstance(item, str) and item.lower() in FAILURE_STATES:
                return True
            if low in {"code", "errorcode", "reasoncode"} and isinstance(item, str) and item.lower().replace("-", "_") in FAILURE_CODES:
                return True
            if low == "error" and item not in (None, "", False):
                return True
            # Outcome envelopes may place the explicit native result one level down.
            if isinstance(item, dict) and explicit_negative(item):
                return True
    return False


def explicit_positive(value: Any) -> bool:
    if not isinstance(value, dict) or explicit_negative(value):
        return False
    if value.get("ok") is True or value.get("allowed") is True or value.get("granted") is True:
        return True
    status = value.get("status", value.get("state"))
    return isinstance(status, str) and status.lower() in {"done", "success", "succeeded", "verified"}


def label(value: Any) -> str | None:
    if explicit_negative(value):
        return "failure"
    if explicit_positive(value):
        return "success"
    return None


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    seal = json.loads(C7.read_text(encoding="utf-8"))
    records: dict[str, dict[str, Any]] = {}
    missing_receipts = no_operation_evidence = candidates = unlabelled = 0

    for family in seal["families"]:
        family_receipt = json.loads((ROOT / family["receipt"]["path"]).read_text(encoding="utf-8"))
        for case in family_receipt.get("rows", []):
            detail = case.get("detail", {})
            receipt_path = detail.get("receipt", "") if isinstance(detail, dict) else ""
            case_file = Path(receipt_path)
            if not case_file.is_file():
                missing_receipts += 1
                continue
            case_sha = digest(case_file)
            evidence = json.loads(case_file.read_text(encoding="utf-8"))
            parent_id = case.get("id")
            contract_families = case.get("contracts", [])
            occurrence: dict[tuple[str, str], int] = {}
            any_candidate = False

            def add(stream: str, operation: str, args: Any, observed: Any) -> None:
                nonlocal candidates, unlabelled, any_candidate
                candidates += 1
                any_candidate = True
                op_key = (stream, operation)
                nth = occurrence.get(op_key, 0)
                occurrence[op_key] = nth + 1
                outcome_label = label(observed)
                if outcome_label is None:
                    unlabelled += 1
                    return
                task = {"toolId": operation, "result": observed}
                key = compact([str(case_file.resolve()).lower(), case_sha, stream, operation, nth])
                row = records.get(key)
                if row is None:
                    row = {
                        "domain": "c7",
                        "input": outcome_input(task),
                        "label": outcome_label,
                        "family": ",".join(contract_families) or family["family"],
                        "source": {"path": str(case_file), "sha256": case_sha, "receiptFamily": family["family"]},
                        "evidence": {"operation": operation, "args": args, "observed": observed,
                                     "occurrence": nth, "parentCaseIds": [], "parentContractFamilies": []},
                    }
                    records[key] = row
                if parent_id and parent_id not in row["evidence"]["parentCaseIds"]:
                    row["evidence"]["parentCaseIds"].append(parent_id)
                for cf in contract_families:
                    if cf not in row["evidence"]["parentContractFamilies"]:
                        row["evidence"]["parentContractFamilies"].append(cf)

            calls = evidence.get("calls", [])
            if isinstance(calls, list):
                for call in calls:
                    if isinstance(call, dict) and call.get("op") and isinstance(call.get("result"), dict):
                        add("calls", str(call["op"]), call.get("args"), call["result"])
            for stream in ("actionRuns", "nativeRuns", "clickRuns", "toolRuns"):
                runs = evidence.get(stream, [])
                if isinstance(runs, list):
                    for run in runs:
                        if not isinstance(run, dict):
                            continue
                        operation = run.get("operation") or run.get("op") or run.get("tool") or run.get("backend")
                        if operation and any(k in run for k in ("status", "ok", "verdict", "error", "expectationMet")):
                            add(stream, str(operation), run.get("input", run.get("args")), run)
            events = evidence.get("nativePermissionEvents", [])
            if isinstance(events, list):
                for event in events:
                    if isinstance(event, dict) and isinstance(event.get("allowed"), bool):
                        operation = f"permission:{event.get('kind', 'unknown')}"
                        add("nativePermissionEvents", operation, {"kind": event.get("kind"), "tabId": event.get("tabId")}, event)
            if not any_candidate:
                no_operation_evidence += 1

    output_records = list(records.values())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "laya.outcomes.v1",
        "provenance": {"sealPath": str(C7), "sealSha256": digest(C7), "families": len(seal["families"])},
        "counts": {
            "independentOperations": len(output_records),
            "operationCandidatesBeforeDeduplication": candidates,
            "missingDetailReceipts": missing_receipts,
            "casesWithoutOperationEvidence": no_operation_evidence,
            "unlabelledOperationCandidates": unlabelled,
            "duplicateReferencesCollapsed": candidates - len(output_records) - unlabelled,
        },
        "records": output_records,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
