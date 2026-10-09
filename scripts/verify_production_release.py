from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.cluster import ClusterRegistry
from grant_agent.mission_control import (
    _build_mission_watchdog_release_gate,
    _build_proving_cycle_readiness,
    _verify_desktop_script_contract,
    _verify_frontend_source_alignment,
    _verify_release_artifact_ci_contract,
)
from grant_agent.onboarding import detect_onboarding_status
from grant_agent.worker import build_worker_doctor


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact_rows(root: Path) -> list[dict]:
    candidates = [root / "web" / "dist" / "index.html"]
    candidates.extend(sorted((root / "src-tauri" / "target" / "release" / "bundle").glob("**/Neyvia*")))
    rows = []
    for path in candidates:
        if not path.is_file():
            continue
        rows.append(
            {
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return rows


def _git_state(root: Path) -> dict:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    rows = [line for line in result.stdout.splitlines() if line.strip()]
    return {"available": result.returncode == 0, "clean": not rows, "changedPathCount": len(rows)}


def build_receipt(root: Path, *, ci_mode: bool) -> dict:
    desktop_ok, desktop_detail = _verify_desktop_script_contract(root)
    frontend_ok, frontend_detail = _verify_frontend_source_alignment(root)
    release_ci_ok, release_ci_detail = _verify_release_artifact_ci_contract(root)
    proving = _build_proving_cycle_readiness(root)
    watchdog = _build_mission_watchdog_release_gate(root)
    worker = build_worker_doctor(root)
    scheduler = ClusterRegistry(root).scheduler_doctor()
    artifacts = _artifact_rows(root)

    checks = [
        {"id": "desktop_contract", "passed": desktop_ok, "detail": desktop_detail},
        {"id": "frontend_alignment", "passed": frontend_ok, "detail": frontend_detail},
        {"id": "release_ci_contract", "passed": release_ci_ok, "detail": release_ci_detail},
        {"id": "web_build_artifact", "passed": any(row["path"] == "web/dist/index.html" for row in artifacts), "detail": "web/dist/index.html exists after the production build."},
        {"id": "desktop_installer", "passed": any("bundle/" in row["path"] and row["path"].lower().endswith((".exe", ".msi")) for row in artifacts), "detail": "At least one hashed Neyvia installer exists."},
    ]
    if not ci_mode:
        onboarding = detect_onboarding_status(root, force=True)
        required_setup = onboarding.get("setupHealth", {}).get("serviceManagementSummary", {})
        checks.extend(
            [
                {"id": "required_setup", "passed": int(required_setup.get("totalItems", 0) or 0) > 0 and int(required_setup.get("healthyCount", 0) or 0) == int(required_setup.get("totalItems", 0) or 0), "detail": f"{required_setup.get('healthyCount', 0)}/{required_setup.get('totalItems', 0)} required setup services are healthy."},
                {"id": "hermes_proving_cycle", "passed": bool(proving.get("ready")), "detail": "; ".join(proving.get("missingProofs", [])) or "Hermes completion, approval, and continuity evidence are recorded."},
                {"id": "mission_watchdog", "passed": bool(watchdog.get("passed")), "detail": str(watchdog.get("details", ""))},
                {"id": "worker_capability", "passed": worker.get("status") in {"ready", "limited"}, "detail": f"Local worker doctor status: {worker.get('status', 'unknown')}."},
                {"id": "queued_job_liveness", "passed": not any(issue.get("kind") == "queued_jobs_without_online_hosts" for issue in scheduler.get("issues", [])), "detail": "An online worker is required only while cluster jobs are queued."},
            ]
        )

    failed = [check["id"] for check in checks if not check["passed"]]
    git_state = _git_state(root)
    return {
        "schema": "neyvia.production_release_proof.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mode": "ci" if ci_mode else "local",
        "status": "passed" if not failed else "blocked",
        "checks": checks,
        "failedChecks": failed,
        "proofReadiness": proving,
        "watchdog": watchdog,
        "workerStatus": worker.get("status"),
        "schedulerStatus": scheduler.get("status"),
        "artifacts": artifacts,
        "git": git_state,
        "warnings": [] if git_state.get("clean") else ["The working tree is not clean; use the artifact hashes for this candidate and create a reviewed release commit before public publication."],
        "longContextStressRun": False,
    }


def _write_receipt(root: Path, receipt: dict, output: str) -> Path:
    if output:
        path = Path(output)
        if not path.is_absolute():
            path = root / path
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = root / ".agent_control" / "release_artifacts" / f"production-gate-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    digest_path = root / ".agent_control" / "proof_digests" / "ci-release-proof.md"
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    digest_path.write_text(
        "# Neyvia production release proof\n\n"
        f"Status: **{receipt['status']}**\n\n"
        f"Mode: `{receipt['mode']}`\n\n"
        f"Receipt: `{path.relative_to(root).as_posix()}`\n\n"
        f"Long-context stress run: `{receipt['longContextStressRun']}`\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify and archive Neyvia production release evidence.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--ci", action="store_true", help="Check source/build artifacts without machine-specific runtime installation gates.")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    receipt = build_receipt(root, ci_mode=bool(args.ci))
    path = _write_receipt(root, receipt, args.output)
    print(json.dumps({"status": receipt["status"], "failedChecks": receipt["failedChecks"], "receipt": str(path), "artifactCount": len(receipt["artifacts"]), "longContextStressRun": False}, indent=2))
    return 0 if receipt["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
