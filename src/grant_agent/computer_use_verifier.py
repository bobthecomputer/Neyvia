"""Primary change-verification facade for structured N-E-Y-V-I-A Computer Use."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from .capability_contracts import utc_now
from .computer_use_twin import ComputerUseTwinService
from .proofs_a_capabilities import checked_action
from .proofs_a_capability_tools import check_verification


COMPUTER_USE_VERIFICATION_SCHEMA = "neyvia.computer_use_verification.v1"
COMPUTER_USE_VERIFICATION_DISPATCH_SCHEMA = (
    "neyvia.computer_use_verification_dispatch.v1"
)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


class ComputerUseVerifierService:
    """Run or dispatch the new structured Computer Use as the product verifier."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.engine = ComputerUseTwinService(self.root)
        self.receipt_dir = (
            self.root
            / ".agent_control"
            / "mission_artifacts"
            / "computer_use_verification"
        )

    @staticmethod
    def _spec(payload: dict[str, Any]) -> dict[str, Any]:
        thresholds = dict(payload.get("thresholds") or {})
        thresholds.setdefault("requireLiveProof", True)
        return {
            "name": str(
                payload.get("name")
                or payload.get("changeLabel")
                or "Structured Computer Use change verification"
            ),
            "mode": str(payload.get("mode") or "live"),
            "baseUrl": str(payload.get("baseUrl") or ""),
            "flows": payload.get("flows"),
            "repetitions": int(payload.get("repetitions") or 1),
            "baselineReceiptPath": str(
                payload.get("baselineReceiptPath") or ""
            ),
            "replayReceiptPath": str(payload.get("replayReceiptPath") or ""),
            "thresholds": thresholds,
            "metadata": {
                **dict(payload.get("metadata") or {}),
                "changeId": str(payload.get("changeId") or ""),
                "changeLabel": str(payload.get("changeLabel") or ""),
                "verificationOwner": "computer_use_verifier",
            },
        }

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.engine.validate_spec(self._spec(payload))

    @checked_action(check_verification)
    def verify(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not bool(payload.get("approved")):
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermissions": [
                    "process.execute",
                    "external.side_effect",
                ],
            }
        saved = self.engine.save_spec(self._spec(payload), approved=True)
        if not saved.get("ok"):
            return {
                "ok": False,
                "status": "invalid",
                "validation": saved.get("validation"),
            }
        engine_result = self.engine.run(saved["spec"]["specId"])
        comparison = engine_result["comparison"]
        verification_id = f"cuverify_{uuid.uuid4().hex[:16]}"
        result = {
            "schema": COMPUTER_USE_VERIFICATION_SCHEMA,
            "verificationId": verification_id,
            "status": engine_result["status"],
            "pass": engine_result["status"] == "passed",
            "changeId": str(payload.get("changeId") or ""),
            "changeLabel": str(payload.get("changeLabel") or ""),
            "engine": {
                "name": "neyvia-structured-computer-use",
                "observationPrimary": "accessibility_graph_and_deltas",
                "visionPolicy": "fallback_only",
                "fullScreenshotEveryTurn": False,
                "underlyingRunId": engine_result["runId"],
            },
            "evidenceMode": engine_result["evidenceMode"],
            "liveProof": engine_result["liveProof"],
            "metrics": engine_result["metrics"],
            "comparison": comparison,
            "flows": [
                flow
                for receipt in engine_result.get("receipts", [])
                for flow in receipt.get("results", [])
                if isinstance(flow, dict)
            ],
            "claims": {
                "functionalChangeVerified": bool(
                    engine_result["status"] == "passed"
                    and engine_result["liveProof"]
                ),
                "fasterThanBaseline": bool(
                    comparison["comparativeClaimAllowed"]
                    and comparison.get("latencySpeedup") is not None
                    and float(comparison["latencySpeedup"]) > 1.0
                ),
                "atLeastAsAccurateAsBaseline": bool(
                    comparison["comparativeClaimAllowed"]
                    and comparison.get("accuracyDelta") is not None
                    and float(comparison["accuracyDelta"]) >= 0.0
                ),
                "comparisonAllowed": bool(
                    comparison["comparativeClaimAllowed"]
                ),
            },
            "sourceReceiptPath": engine_result["receiptPath"],
            "createdAt": utc_now(),
        }
        path = self.receipt_dir / f"{verification_id}.json"
        _atomic_json(path, result)
        result["receiptPath"] = str(path)
        return result

    def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not bool(payload.get("approved")):
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "external.side_effect",
            }
        saved = self.engine.save_spec(self._spec(payload), approved=True)
        if not saved.get("ok"):
            return {
                "ok": False,
                "status": "invalid",
                "validation": saved.get("validation"),
            }
        dispatched = self.engine.dispatch(
            saved["spec"]["specId"],
            preferred_host=str(payload.get("preferredHost") or ""),
            assign_now=bool(payload.get("assignNow")),
        )
        return {
            "schema": COMPUTER_USE_VERIFICATION_DISPATCH_SCHEMA,
            "status": dispatched["status"],
            "verificationEngine": "neyvia-structured-computer-use",
            "job": dispatched["job"],
            "assignment": dispatched.get("assignment"),
            "requiredCapabilities": dispatched["requiredCapabilities"],
            "nasExecutionAllowed": False,
            "portablePayloadBytes": dispatched["portablePayloadBytes"],
        }
