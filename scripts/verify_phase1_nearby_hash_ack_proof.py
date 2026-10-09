"""Generate Phase 1 Nearby Send hash-ACK product proof (loopback only)."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from grant_agent.mesh_service import MeshService
from grant_agent.nearby_send import NearbySendService

ROOT = Path(__file__).resolve().parents[1]
PROOF_DIR = ROOT / ".agent_control" / "capability_os" / "qa"
NEARBY_DIR = ROOT / ".agent_control" / "nearby_send"


def _write_cancelled_receipt(
    service: NearbySendService,
    plan: dict,
    receipt_id: str,
) -> dict:
    file0 = plan["files"][0]
    cancelled = {
        "schema": "neyvia.nearby-transfer-receipt/v1",
        "receiptId": receipt_id,
        "planId": plan["planId"],
        "planHash": plan["planHash"],
        "ok": False,
        "status": "cancelled",
        "protocol": "localsend-v2.1",
        "recipient": plan["recipient"],
        "sessionDigest": "",
        "files": [
            {
                "fileId": file0["id"],
                "fileName": file0["fileName"],
                "path": file0["path"],
                "size": file0["size"],
                "sha256": file0["sha256"],
                "destinationSha256": "",
                "transportAccepted": False,
                "remoteHashVerified": False,
                "sourceMatchesDestination": False,
            }
        ],
        "summary": {
            "fileCount": 1,
            "totalBytes": file0["size"],
            "durationMs": 1,
            "transportAccepted": 0,
            "remoteHashVerified": 0,
            "sourceMatchesDestination": 0,
        },
        "tokensRetained": False,
        "completedAt": "2026-07-24T00:00:00Z",
    }
    service.receipt_root.mkdir(parents=True, exist_ok=True)
    (service.receipt_root / f"{receipt_id}.json").write_text(
        json.dumps(cancelled),
        encoding="utf-8",
    )
    return cancelled


def main() -> int:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    NEARBY_DIR.mkdir(parents=True, exist_ok=True)
    service = NearbySendService(ROOT)
    mesh = MeshService(ROOT)
    started = time.perf_counter()
    source = NEARBY_DIR / "phase1-hash-ack-proof.txt"
    body = b"NEYVIA phase1 remote hash ACK proof " + str(time.time()).encode()
    source.write_bytes(body)
    source_digest = hashlib.sha256(body).hexdigest()
    try:
        sidecar = service.start_receiver_sidecar(host="127.0.0.1", port=0)
        plan = service.build_plan([source], recipient_endpoint=sidecar["endpoint"])
        result = service.send(plan, approved=True)
        history = service.list_transfer_history(limit=5)
        cancel_idle = service.request_cancel_active_transfer()

        failed_source = NEARBY_DIR / "phase1-retry-proof.txt"
        failed_source.write_text("retry proof payload", encoding="utf-8")
        retry_plan = service.build_plan(
            [failed_source],
            recipient_endpoint=sidecar["endpoint"],
        )
        cancelled = _write_cancelled_receipt(
            service,
            retry_plan,
            "nearby_receipt_phase1retryproof00000000000001",
        )
        retried = service.retry_transfer(cancelled["receiptId"], approved=True)
        enrollment = mesh.enrollment_and_trust_status()
        dest = result["files"][0]["destinationSha256"]
        proof = {
            "schema": "neyvia.phase1-personal-mesh-product-proof/v1",
            "generatedAt": result["completedAt"],
            "lane": "PRODUCT_AND_PROOF",
            "phase": 1,
            "slices": [
                "enrollment-trust-ui-backend",
                "nearby-transfer-history-progress",
                "nearby-receiver-sidecar-hash-ack-cancel-retry",
            ],
            "mesh": {
                "enrollment": enrollment.get("enrollment"),
                "trustSummary": (enrollment.get("trust") or {}).get("summary"),
                "directActive": (
                    (enrollment.get("trust") or {}).get("summary") or {}
                ).get("directActive"),
                "relayedActive": (
                    (enrollment.get("trust") or {}).get("summary") or {}
                ).get("relayedActive"),
                "deviceRevocationImplemented": (
                    enrollment.get("services") or {}
                ).get("deviceRevocationImplemented"),
            },
            "nearby": {
                "ok": result["ok"],
                "status": result["status"],
                "durationMs": result["summary"]["durationMs"],
                "receiptId": result["receiptId"],
                "receiptPath": result["receiptPath"],
                "sidecar": {
                    "implemented": True,
                    "runningDuringProof": True,
                    "endpoint": sidecar["endpoint"],
                    "hashAckPath": sidecar["hashAckPath"],
                    "loopbackOnly": True,
                },
                "sourceHashes": {
                    row["fileId"]: row["sha256"] for row in result["files"]
                },
                "destinationHashes": {
                    row["fileId"]: row["destinationSha256"]
                    for row in result["files"]
                },
                "sourceMatchesDestination": {
                    row["fileId"]: row["sourceMatchesDestination"]
                    for row in result["files"]
                },
                "remoteHashVerifiedInReceipt": result["summary"][
                    "remoteHashVerified"
                ],
                "hashAck": result.get("hashAck"),
                "sourceDigestEqualsWrittenFile": (
                    source_digest == result["files"][0]["sha256"]
                ),
                "sourceEqualsDestination": source_digest == dest,
                "historyTransfers": history["summary"]["transfers"],
                "historyRemoteHashVerifiedCount": history["summary"][
                    "remoteHashVerifiedCount"
                ],
                "historySourceMatchesDestinationCount": history["summary"][
                    "sourceMatchesDestinationCount"
                ],
                "cancelWhenIdle": cancel_idle,
                "retry": {
                    "ok": retried.get("ok"),
                    "status": retried.get("status"),
                    "retriedFromReceiptId": retried.get("retriedFromReceiptId"),
                    "remoteHashVerified": (retried.get("summary") or {}).get(
                        "remoteHashVerified"
                    ),
                    "sourceMatchesDestination": (
                        retried.get("summary") or {}
                    ).get("sourceMatchesDestination"),
                },
                "activeAfterSend": service.get_active_transfer().get("active"),
                "physicalDeviceProof": history.get("physicalDeviceProof"),
            },
            "browserUi": {
                "panel": "personal-mesh",
                "entryPoints": [
                    "Lab > Personal Mesh",
                    "Command palette > Personal Mesh",
                ],
                "nearbyControls": [
                    "start/stop loopback sidecar",
                    "cancel active transfer",
                    "retry failed/cancelled",
                ],
            },
            "performance": {
                "productProofDurationMs": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
                "transferDurationMs": result["summary"]["durationMs"],
                "retryDurationMs": (retried.get("summary") or {}).get(
                    "durationMs"
                ),
            },
        }
        out = PROOF_DIR / "phase1-personal-mesh-product-proof-20260724.json"
        out.write_text(json.dumps(proof, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "proofPath": str(out),
                    "remoteHashVerified": result["summary"][
                        "remoteHashVerified"
                    ],
                    "sourceEqualsDestination": source_digest == dest,
                    "retryOk": retried.get("ok"),
                },
                indent=2,
            )
        )
        if not (
            result["ok"]
            and source_digest == dest
            and result["summary"]["remoteHashVerified"] == 1
            and retried.get("ok")
        ):
            return 1
        return 0
    finally:
        service.stop_receiver_sidecar()


if __name__ == "__main__":
    raise SystemExit(main())
