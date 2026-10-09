"""Durable receipts around scheduled dispatch; downstream authority stays intact."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .verified_operations import VerifiedOperationStore
from .recovery_objects import RecoveryObjectStore
from .living_applications import SupervisedAutonomy


def dispatch_operation(root: Path, step: dict, context: dict, dispatch: Callable,
                       *, autonomy_policy_path: Path | None = None) -> dict[str, Any]:
    mission = str(context.get("mission_id") or context.get("missionId") or "stage-default")
    identity = {"plan": context.get("planHash"), "step": step.get("step_id"),
                "execution": context.get("executionId") or "default"}
    operation_id = "stage_" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    tool = str(step.get("tool") or "")
    scope = "stage:" + mission
    store = VerifiedOperationStore(root, scope)
    recovery_id = "recovery_" + operation_id

    def effect():
        # Only an operator-selected persisted policy can restrict autonomous dispatch.
        # Tool arguments and model context cannot supply or replace this policy.
        if autonomy_policy_path is not None:
            policy = SupervisedAutonomy.from_state_file(autonomy_policy_path)
            record = json.loads(autonomy_policy_path.read_text(encoding="utf-8"))
            admission = policy.authorize(tool, cost=1, evidence_count=0,
                                         authority=record.get("operatorAuthority") is True)
            if not admission["allowed"]:
                return {"ok": False, "summary": "Supervised autonomy admission denied",
                        "metadata": {"autonomy": admission}, "status": "blocked"}
        return dispatch(step, context)

    receipt = store.execute(operation_id, tool,
        authority={"granted": True, "boundary": "dispatch wrapper; downstream tool authority remains required"},
        effect=effect, recovery_ref=recovery_id,
        request={"step": step, "missionId": mission, **identity})
    result = receipt.get("result") or receipt
    raw = result.get("effect")
    if not isinstance(raw, dict):
        raw = {"ok": False, "summary": receipt.get("message") or "Scheduled dispatch requires reconciliation"}
    raw = {**raw, "metadata": {**(raw.get("metadata") or {}),
        "operationId": operation_id, "operationStatus": receipt.get("status"),
        "operationReceiptPath": receipt.get("operationReceiptPath"),
        "duplicateSuppressed": receipt.get("duplicateSuppressed", False)}}
    if receipt.get("status") in {"unknown_side_effects", "operation_conflict"} or raw.get("ok") is False:
        raw["ok"] = False
        recovery = RecoveryObjectStore(root, scope)
        try:
            recovery.load(recovery_id)
        except FileNotFoundError:
            recovery.create({"operationId": operation_id, "toolId": tool, "status": receipt.get("status")},
                recovery_id=recovery_id, operation_id=operation_id,
                uncertain_effects=[{"scope": "scheduled tool dispatch", "message": "Inspect downstream receipts before repeating"}],
                evidence=[{"operationReceiptPath": receipt.get("operationReceiptPath")}])
        raw["metadata"]["recoveryRef"] = recovery_id
    return raw
