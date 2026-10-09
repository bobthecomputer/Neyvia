from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_PATH = ROOT / ".agent_control/release_candidates/public-web/release-candidate.json"
DEPLOYMENT_PATH = ROOT / ".agent_control/deployment_evidence/public-web.json"


def _run(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


def _local_source_state() -> dict:
    head = _run("git", "rev-parse", "HEAD")
    status = _run("git", "status", "--porcelain")
    return {
        "headSha": head.stdout.strip() if head.returncode == 0 else "",
        "sourceWorkingTreeClean": status.returncode == 0 and not status.stdout.strip(),
    }


def _dist_manifest() -> list[dict]:
    dist = ROOT / "web" / "dist"
    rows: list[dict] = []
    if not dist.is_dir():
        return rows
    for path in sorted(item for item in dist.rglob("*") if item.is_file()):
        rows.append({
            "path": path.relative_to(dist).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    return rows


def build_distribution_receipt() -> dict:
    source = _local_source_state()
    files = _dist_manifest()
    return {
        "schema": "fluxio.public_web_distribution.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if files and any(row["path"] == "index.html" for row in files) else "blocked",
        "source": source,
        "files": files,
    }


def record_live_pages_deployment_receipt(page_url: str, deployed_sha: str) -> dict:
    source = _local_source_state()
    deployed_sha = deployed_sha.strip()
    receipt = {
        "schema": "fluxio.public_web_deployment.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "pageUrl": page_url,
        "localHeadSha": source["headSha"],
        "deployedSha": deployed_sha,
        "deployedShaMatchesLocalHead": bool(deployed_sha and deployed_sha == source["headSha"]),
        "sourceWorkingTreeClean": source["sourceWorkingTreeClean"],
    }
    receipt["publicationCurrent"] = bool(
        receipt["deployedShaMatchesLocalHead"] and receipt["sourceWorkingTreeClean"]
    )
    DEPLOYMENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEPLOYMENT_PATH.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the public web artifact and optionally record a live Pages deployment.")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--record-live-pages", action="store_true")
    parser.add_argument("--page-url", default="")
    parser.add_argument("--deployed-sha", default="")
    args = parser.parse_args()
    receipt = build_distribution_receipt()
    if args.record_live_pages:
        deployed_sha = args.deployed_sha
        if not deployed_sha:
            run = _run("gh", "api", "repos/{owner}/{repo}/deployments?environment=github-pages&per_page=1")
            if run.returncode != 0:
                receipt["status"] = "blocked"
                receipt["pagesError"] = (run.stderr or run.stdout).strip()
            else:
                try:
                    deployments = json.loads(run.stdout)
                    deployed_sha = str(deployments[0].get("sha") or "")
                except (json.JSONDecodeError, IndexError, AttributeError, TypeError):
                    receipt["status"] = "blocked"
                    receipt["pagesError"] = "GitHub returned no Pages deployment SHA."
        receipt["deployment"] = record_live_pages_deployment_receipt(args.page_url, deployed_sha)
        receipt["status"] = (
            "passed" if receipt["deployment"]["publicationCurrent"] else "blocked"
        )
    if args.write:
        CANDIDATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        candidate = {
            "schema": "fluxio.release_candidate.v1",
            "generatedAt": receipt["generatedAt"],
            "status": receipt["status"],
            "distribution": receipt,
        }
        CANDIDATE_PATH.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
