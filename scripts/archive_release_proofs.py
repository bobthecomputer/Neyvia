from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_ROOT = ROOT / ".agent_control" / "release_artifacts"
ATTACHMENT_MANIFEST_SCHEMA = "fluxio.public_release_attachment_manifest.v1"
LIVE_NAS_SNAPSHOT_SCHEMA = "fluxio.live_nas_system_audit_snapshot.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _collect(patterns: tuple[str, ...], target: Path) -> list[dict]:
    rows: list[dict] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for source in sorted(ROOT.glob(pattern)):
            if not source.is_file() or source in seen:
                continue
            seen.add(source)
            relative = source.relative_to(ROOT)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            rows.append({
                "path": relative.as_posix(),
                "bytes": source.stat().st_size,
                "sha256": _sha256(source),
            })
    return rows


def _has_path(rows: list[dict], fragment: str) -> bool:
    return any(fragment in str(row.get("path") or "") for row in rows)


def _json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def archive(*, require_publication_packet: bool, capture_live_nas_system_audit: bool) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = RELEASE_ROOT / stamp
    patterns = (
        ".agent_control/release_artifacts/*.json",
        ".agent_control/proof_digests/*.md",
        ".agent_control/authenticated_live_control/**",
        ".agent_control/cross_device_launch_rehearsals/**",
        ".agent_control/live_nas_system_audit/**",
        ".agent_control/self_improvement_evidence/**",
        ".agent_control/deployment_evidence/**",
        ".agent_control/public_launch_readiness/**",
        "tmp-ui-checks/**",
    )
    rows = _collect(patterns, target)
    publication_notes = RELEASE_ROOT / "public-release-notes.md"
    publication_manifest = RELEASE_ROOT / "publication-manifest.json"
    attachment_manifest = RELEASE_ROOT / "publication-attachments.json"
    public_packet = publication_notes.is_file() and publication_manifest.is_file()
    public_attachments = attachment_manifest.is_file()
    if require_publication_packet and not (public_packet and public_attachments):
        raise RuntimeError("Required public publication packet or attachment manifest is missing.")

    authenticated_live_control = [row for row in rows if "authenticated_live_control" in row["path"]]
    cross_device = [row for row in rows if "cross_device_launch_rehearsals" in row["path"]]
    nas_snapshots = [row for row in rows if "live_nas_system_audit" in row["path"]]
    private_nas = [row for row in rows if row["path"].endswith("private-nas-web.json")]
    public_web = _json(ROOT / ".agent_control/deployment_evidence/public-web.json")
    self_improvement_evidence = [row for row in rows if "self_improvement_evidence" in row["path"]]
    manifest = {
        "schema": "fluxio.release_proof_archive.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "archivePath": str(target.relative_to(ROOT)).replace("\\", "/"),
        "artifacts": rows,
        "authenticatedLiveControlReports": len(authenticated_live_control),
        "crossDeviceLaunchReceiptSummary": {"count": len(cross_device)},
        "liveNasSystemAuditAttached": bool(nas_snapshots),
        "liveNasSystemAuditSnapshots": nas_snapshots,
        "captureLiveNasSystemAuditRequested": capture_live_nas_system_audit,
        "publicReleasePublicationPacketAttached": public_packet,
        "publicReleaseAttachmentManifestAttached": public_attachments,
        "privateNasWebDeploymentAttached": bool(private_nas),
        "privateNasWebDeploymentReceipts": private_nas,
        "publicWebDeploymentCurrent": bool(public_web.get("publicationCurrent")),
        "publicWebStatus": (
            "current"
            if public_web.get("publicationCurrent")
            else "public_web_reachable_but_source_stale"
            if public_web.get("pageUrl")
            else "not_deployed"
        ),
        "self_improvement_evidence": self_improvement_evidence,
    }
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    latest = {
        "schema": "fluxio.latest_release_artifact_pointer.v1",
        "generatedAt": manifest["generatedAt"],
        "manifestPath": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "releaseCandidatePath": ".agent_control/release_candidates/public-web/release-candidate.json",
        "counts": {
            "artifacts": len(rows),
            "publicReleaseAttachmentManifestArtifacts": 1 if public_attachments else 0,
        },
    }
    RELEASE_ROOT.mkdir(parents=True, exist_ok=True)
    (RELEASE_ROOT / "latest.json").write_text(json.dumps(latest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a checksummed, immutable release-proof archive.")
    parser.add_argument("--require-publication-packet", action="store_true")
    parser.add_argument("--capture-live-nas-system-audit", action="store_true")
    args = parser.parse_args()
    manifest = archive(
        require_publication_packet=args.require_publication_packet,
        capture_live_nas_system_audit=args.capture_live_nas_system_audit,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
