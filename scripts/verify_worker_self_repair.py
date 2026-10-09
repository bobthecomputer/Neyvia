from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.cluster import ClusterRegistry, current_host_id  # noqa: E402
from grant_agent.self_repair import queue_self_repair_job  # noqa: E402
from grant_agent.worker import run_local_worker_once  # noqa: E402


GOOD_APP = """from __future__ import annotations

import sys


def health() -> str:
    return "healthy"


if __name__ == "__main__":
    print(health())
    raise SystemExit(0 if "--health" in sys.argv else 2)
"""

BROKEN_APP = """from __future__ import annotations

raise RuntimeError("controlled self-repair proof break")
"""


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def run_proof(proof_root: Path) -> dict[str, object]:
    proof_root = proof_root.expanduser().resolve()
    proof_root.mkdir(parents=True, exist_ok=False)
    good_path = proof_root / "app.known-good.py"
    app_path = proof_root / "app.py"
    good_path.write_text(GOOD_APP, encoding="utf-8")
    app_path.write_text(BROKEN_APP, encoding="utf-8")

    detect = [sys.executable, "app.py", "--health"]
    repair = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; "
            "Path('app.py').write_bytes(Path('app.known-good.py').read_bytes())"
        ),
    ]
    registry = ClusterRegistry(proof_root)
    job = queue_self_repair_job(
        registry,
        workspace=proof_root,
        detect_command=detect,
        repair_command=repair,
        verify_command=detect,
        tracked_paths=["app.py"],
        mission_id="mission_worker_self_repair_proof",
        workspace_id="workspace_worker_self_repair_proof",
        repair_id=f"worker_self_repair_{_timestamp()}",
        max_attempts=2,
        phase_timeout_seconds=20,
        total_timeout_seconds=60,
    )
    worker_result = run_local_worker_once(proof_root, host_id=current_host_id())
    completed_job = registry.get_job(job["jobId"])
    events = registry.list_events(job_id=job["jobId"], limit=40)
    with registry._connect() as db:
        artifact_row = db.execute(
            "SELECT kind, path FROM artifacts WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()
    result = worker_result.get("result") if isinstance(worker_result.get("result"), dict) else {}
    receipt = result.get("repairReceipt") if isinstance(result.get("repairReceipt"), dict) else {}
    receipt_path = Path(str(result.get("repairReceiptPath") or ""))
    proof = receipt.get("proof") if isinstance(receipt.get("proof"), dict) else {}

    checks = {
        "workerClaimedJob": bool(worker_result.get("claimed")),
        "clusterJobCompleted": completed_job.get("status") == "completed",
        "initialHealthFailed": bool(proof.get("initialDetectionFailed")),
        "repairCommandPassed": bool(proof.get("repairCommandPassed")),
        "finalHealthPassed": bool(proof.get("finalVerificationPassed")),
        "applicationRestored": app_path.read_text(encoding="utf-8") == GOOD_APP,
        "receiptExists": receipt_path.is_file(),
        "receiptRegisteredAsArtifact": bool(
            artifact_row
            and artifact_row["kind"] == "self_repair_receipt"
            and Path(artifact_row["path"]).resolve() == receipt_path.resolve()
        ),
        "repairEventsRecorded": {
            "repair.detected",
            "repair.applied",
            "repair.verified",
        }.issubset({str(event.get("kind") or "") for event in events}),
    }
    ok = all(checks.values())
    proof_bundle = {
        "schema": "fluxio.worker_self_repair_proof.v1",
        "ok": ok,
        "proofRoot": str(proof_root),
        "jobId": job["jobId"],
        "jobStatus": completed_job.get("status"),
        "checks": checks,
        "changedFiles": result.get("changedFiles", []),
        "eventKinds": [event.get("kind") for event in events],
        "repairReceiptPath": str(receipt_path),
        "registeredArtifact": (
            {"kind": artifact_row["kind"], "path": artifact_row["path"]}
            if artifact_row
            else {}
        ),
        "repairReceipt": receipt,
    }
    output_path = proof_root / ".agent_control" / "worker_self_repair_proof.json"
    output_path.write_text(json.dumps(proof_bundle, indent=2) + "\n", encoding="utf-8")
    proof_bundle["proofBundlePath"] = str(output_path)
    return proof_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Break a disposable app and prove the bundled Fluxio worker repairs it."
    )
    parser.add_argument(
        "--proof-root",
        default=str(ROOT / ".agent_control" / "self_repair_proofs" / _timestamp()),
        help="New directory in which the disposable proof app will be created.",
    )
    args = parser.parse_args(argv)
    try:
        proof = run_proof(Path(args.proof_root))
    except FileExistsError:
        print(json.dumps({"ok": False, "error": "proof_root_already_exists"}, indent=2))
        return 2
    print(json.dumps(proof, indent=2))
    return 0 if proof.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
