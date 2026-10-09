from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.neyvia_conversations import NeyviaConversationStore


PROBE = r"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from grant_agent.capability_evolution import NeyviaCapabilityEvolution


def receipt(turn_id: str, *, duration_ms: int, artifact_count: int) -> dict:
    return {
        "turnId": turn_id,
        "conversationId": "probe_conversation",
        "createdAt": "2026-07-29T08:00:00Z",
        "receipt": {
            "schema": "fluxio.turn_receipt.v1",
            "status": "completed",
            "exitCode": 0,
            "durationMs": duration_ms,
            "toolTimeline": [
                {
                    "kind": "verification.test",
                    "summary": "Receipt-binding contract verified.",
                    "status": "passed",
                }
            ],
            "proofArtifacts": [
                {"path": f"proof/{turn_id}-{index}.json"}
                for index in range(artifact_count)
            ],
            "assistantMessage": "Probe transcript must not enter evolution evidence.",
        },
    }


if not hasattr(NeyviaCapabilityEvolution, "record_receipt_comparison"):
    print(json.dumps({
        "schema": "neyvia.receipt_binding_probe.v1",
        "status": "failed",
        "reason": "receipt_binding_missing",
    }, sort_keys=True))
    raise SystemExit(2)

with tempfile.TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    service = NeyviaCapabilityEvolution(
        root,
        database_path=root / "ecosystem.sqlite3",
        hermes_import_dir=root / "missing-hermes",
    )
    trial = service.create_trial({
        "capabilityId": "receipt-binding-probe",
        "action": "prove",
        "context": {"conversationId": "probe_conversation"},
    })
    baseline = receipt("probe_baseline", duration_ms=12_000, artifact_count=1)
    candidate = receipt("probe_candidate", duration_ms=7_000, artifact_count=2)
    result = service.record_receipt_comparison(
        trial["trialId"],
        baseline_record=baseline,
        candidate_record=candidate,
        same_contract_confirmed=True,
        operator_value="candidate_better",
    )
    replay = service.record_receipt_comparison(
        trial["trialId"],
        baseline_record=baseline,
        candidate_record=candidate,
        same_contract_confirmed=True,
        operator_value="candidate_better",
    )
    encoded = json.dumps(result, sort_keys=True)
    passed = (
        result["state"] == "evidence_ready"
        and result["verdict"]["comparableRunCount"] == 1
        and replay["verdict"]["comparableRunCount"] == 1
        and result["verdict"]["candidateActivated"] is False
        and "Probe transcript" not in encoded
        and result["evidence"][0]["receiptPair"]["transcriptsIncluded"] is False
    )
    print(json.dumps({
        "schema": "neyvia.receipt_binding_probe.v1",
        "status": "passed" if passed else "failed",
        "candidateActivated": result["verdict"]["candidateActivated"],
        "comparableRunCount": result["verdict"]["comparableRunCount"],
        "idempotentRunCount": replay["verdict"]["comparableRunCount"],
        "transcriptsIncluded": result["evidence"][0]["receiptPair"]["transcriptsIncluded"],
    }, sort_keys=True))
    raise SystemExit(0 if passed else 1)
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_probe(source_root: Path) -> dict[str, Any]:
    source = source_root.resolve()
    capability_path = source / "src" / "grant_agent" / "capability_evolution.py"
    if not capability_path.is_file():
        raise FileNotFoundError(capability_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source / "src")
    started_at = utc_now()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as temp_dir:
        completed = subprocess.run(
            [sys.executable, "-c", PROBE],
            cwd=temp_dir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    ended_at = utc_now()
    elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
    stdout_lines = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    parsed: dict[str, Any] = {}
    if stdout_lines:
        try:
            candidate = json.loads(stdout_lines[-1])
            if isinstance(candidate, dict):
                parsed = candidate
        except json.JSONDecodeError:
            parsed = {}
    return {
        "sourceRoot": str(source),
        "sourceSha256": sha256_file(capability_path),
        "startedAt": started_at,
        "endedAt": ended_at,
        "durationMs": elapsed_ms,
        "exitCode": completed.returncode,
        "result": parsed,
    }


def write_report(
    output_dir: Path,
    *,
    batch_id: str,
    round_number: int,
    role: str,
    result: dict[str, Any],
) -> Path:
    path = output_dir / f"{batch_id}-round-{round_number}-{role}.json"
    payload = {
        "schema": "neyvia.receipt_binding_process_proof.v1",
        "batchId": batch_id,
        "round": round_number,
        "role": role,
        "sameContract": "neyvia.receipt_binding_probe.v1",
        "process": result,
        "transcriptsIncluded": False,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def turn_receipt(
    *,
    conversation_id: str,
    role: str,
    round_number: int,
    result: dict[str, Any],
    proof_path: Path,
) -> dict[str, Any]:
    passed = (
        int(result["exitCode"]) == 0
        and result.get("result", {}).get("status") == "passed"
    )
    return {
        "schema": "fluxio.turn_receipt.v1",
        "sessionId": conversation_id,
        "missionId": "neyvia-receipt-binding-proof",
        "sourceType": "capability-evolution-proof",
        "runtime": "python",
        "provider": "local-process",
        "model": "not_applicable",
        "effort": "bounded",
        "status": "completed" if passed else "failed",
        "exitCode": int(result["exitCode"]),
        "startedAt": result["startedAt"],
        "endedAt": result["endedAt"],
        "durationMs": int(result["durationMs"]),
        "toolTimeline": [
            {
                "kind": "verification.receipt_binding_contract",
                "at": result["endedAt"],
                "summary": (
                    f"Round {round_number} {role} receipt-binding contract "
                    f"{'passed' if passed else 'failed'}."
                ),
                "status": "passed" if passed else "failed",
            }
        ],
        "changedFiles": [],
        "proofArtifacts": [
            {
                "kind": "receipt-binding-proof",
                "path": str(proof_path.resolve()),
                "sha256": sha256_file(proof_path),
            }
        ],
        "permissionSummary": {
            "allowed": [
                "workspace.read",
                "workspace.write",
                "artifact.write",
                "process.execute",
            ],
            "approvalRequired": [
                "secret.use",
                "network.write",
                "external.side_effect",
            ],
            "denied": ["destructive"],
        },
        "runSummary": (
            f"Receipt-binding contract {'passed' if passed else 'failed'} "
            f"for the {role} source."
        ),
        "assistantMessage": (
            f"Recorded a real {role} process receipt for comparison round "
            f"{round_number}."
        ),
    }


def append_receipt_turn(
    store: NeyviaConversationStore,
    *,
    conversation_id: str,
    batch_id: str,
    round_number: int,
    role: str,
    receipt: dict[str, Any],
) -> str:
    turn_id = (
        f"receipt_binding_{batch_id}_round_{round_number}_{role}"
    )
    turn = store.append_turn(
        conversation_id,
        turn_id=turn_id,
        role="assistant",
        content=(
            f"Receipt-binding proof round {round_number}: {role} "
            f"{receipt['status']}."
        ),
        source="receipt-binding-proof",
        turn_kind="verification-receipt",
        metadata={
            "proofBatchId": batch_id,
            "comparisonRole": role,
            "comparisonRound": round_number,
            "turnReceipt": receipt,
        },
        idempotent=True,
    )
    return str(turn["turnId"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the same receipt-binding contract against a baseline and "
            "candidate source tree, then optionally attach real process "
            "receipts to a Neyvia conversation."
        )
    )
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, default=ROOT)
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "proof" / "neyvia-receipt-binding-20260729",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rounds = max(1, min(int(args.rounds), 8))
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    store = (
        NeyviaConversationStore(args.candidate_root.resolve())
        if args.conversation_id
        else None
    )
    if store is not None:
        store.get_conversation(args.conversation_id)

    records: list[dict[str, Any]] = []
    for round_number in range(1, rounds + 1):
        round_record: dict[str, Any] = {"round": round_number}
        for role, source_root in (
            ("baseline", args.baseline_root),
            ("candidate", args.candidate_root),
        ):
            result = run_probe(source_root)
            report_path = write_report(
                output_dir,
                batch_id=batch_id,
                round_number=round_number,
                role=role,
                result=result,
            )
            receipt = turn_receipt(
                conversation_id=args.conversation_id,
                role=role,
                round_number=round_number,
                result=result,
                proof_path=report_path,
            )
            turn_id = ""
            if store is not None:
                turn_id = append_receipt_turn(
                    store,
                    conversation_id=args.conversation_id,
                    batch_id=batch_id,
                    round_number=round_number,
                    role=role,
                    receipt=receipt,
                )
            round_record[role] = {
                "status": receipt["status"],
                "exitCode": receipt["exitCode"],
                "turnId": turn_id,
                "proofPath": str(report_path),
                "sourceSha256": result["sourceSha256"],
            }
        records.append(round_record)

    summary = {
        "schema": "neyvia.receipt_binding_batch.v1",
        "status": "recorded",
        "batchId": batch_id,
        "conversationId": args.conversation_id,
        "rounds": records,
        "transcriptsIncluded": False,
    }
    summary_path = output_dir / f"{batch_id}-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps({**summary, "summaryPath": str(summary_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
