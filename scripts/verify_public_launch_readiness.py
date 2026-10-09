from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / ".agent_control/public_launch_readiness"


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _attachment_manifest_integrity(manifest: dict) -> bool:
    attachments = manifest.get("attachments") or []
    if not isinstance(attachments, list) or not attachments:
        return False
    for row in attachments:
        path = ROOT / str(row.get("path") or "")
        if not path.is_file():
            return False
        expected = str(row.get("sha256") or "")
        if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            return False
    return True


def build_readiness() -> dict:
    deployment = _json(ROOT / ".agent_control/deployment_evidence/public-web.json")
    packet = _json(ROOT / ".agent_control/release_artifacts/publication-manifest.json")
    attachments = _json(ROOT / ".agent_control/release_artifacts/publication-attachments.json")
    public_web_current = bool(deployment.get("publicationCurrent"))
    external_publication_proven = bool(packet and deployment.get("pageUrl"))
    attachment_manifest_integrity = _attachment_manifest_integrity(attachments)
    ready = public_web_current and external_publication_proven and attachment_manifest_integrity
    reason = "ready" if ready else "public_packet_ready_missing_current_web_and_publication"
    return {
        "schema": "fluxio.public_launch_readiness.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "reason": reason,
        "checks": {
            "public_web_current": public_web_current,
            "external_publication_proven": external_publication_proven,
            "attachment_manifest_integrity": attachment_manifest_integrity,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail closed until public web and publication evidence are current.")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    receipt = build_readiness()
    if args.write:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "readiness.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 2 if args.require_ready and not receipt["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
