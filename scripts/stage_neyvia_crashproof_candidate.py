from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SOURCE_DIRECTORIES = (
    ".github",
    "src/grant_agent",
    "src-tauri/capabilities",
    "src-tauri/src",
    "scripts",
    "sdk",
    "tests",
    "docs",
    "web/src",
    "web/public",
)

ROOT_SOURCE_FILES = (
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "README.md",
    "src-tauri/build.rs",
    "src-tauri/Cargo.lock",
    "src-tauri/Cargo.toml",
    "src-tauri/tauri.conf.json",
    "uv.lock",
    "vercel.json",
    "vite.config.mjs",
)

OVERLAYS = (
    "src/grant_agent/action_executor.py",
    "src/grant_agent/checkpoints.py",
    "src/grant_agent/cli.py",
    "src/grant_agent/crashproof.py",
    "src/grant_agent/durability.py",
    "src/grant_agent/flight_recorder.py",
    "src/grant_agent/mission_control.py",
    "src/grant_agent/model_catalog.py",
    "src/grant_agent/neyvia_coordinator.py",
    "src/grant_agent/neyvia_extension_worker.py",
    "src/grant_agent/neyvia_mcp.py",
    "src/grant_agent/opencode_go_models.py",
    "src/grant_agent/platform_config.py",
    "src/grant_agent/system_audit.py",
    "src/grant_agent/web_backend.py",
    "scripts/run_neyvia_crash_campaign.py",
    "scripts/stage_neyvia_crashproof_candidate.py",
    "scripts/verify_neyvia_crashproof_ui.mjs",
    "tests/test_action_executor.py",
    "tests/test_checkpoints.py",
    "tests/test_crashproof.py",
    "tests/test_flight_recorder.py",
    "tests/test_mission_control.py",
    "tests/test_neyvia_extensions.py",
    "tests/test_neyvia_mcp.py",
    "tests/test_web_backend.py",
    "web/index.html",
    "web/src/neyvia/NeyviaApp.tsx",
    "web/src/neyvia/NeyviaWorkspace.jsx",
    "web/src/neyvia/NeyviaProductModePanels.jsx",
    "web/src/neyvia/neyviaProductMode.css",
    "web/src/neyvia/neyviaProductMode.js",
    "web/src/neyvia/styles.css",
    "web/src/neyvia/stylesReference.css",
    "web/src/neyvia/stylesReferencePolish.css",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree(root: Path) -> dict:
    rows = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"candidate contains a symlink: {path}")
        if not path.is_file() or path.name == ".neyvia-candidate-complete.json":
            continue
        relative = path.relative_to(root).as_posix()
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    rows.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    digest = hashlib.sha256()
    for row in rows:
        digest.update(row["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(row["sha256"].encode("ascii"))
        digest.update(b"\n")
    return {"files": len(rows), "bytes": sum(row["bytes"] for row in rows), "sha256Manifest": rows, "manifestSha256": digest.hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage a sealed N-E-Y-V-I-A candidate from a verified base plus the reconciled source tree.")
    parser.add_argument("--base", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    base = Path(args.base).resolve(strict=True)
    staging_root = (ROOT / ".agent_control" / "candidate_staging").resolve()
    destination = (staging_root / args.name).resolve()
    destination.relative_to(staging_root)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(base, destination)
    (destination / ".neyvia-candidate-complete.json").unlink(missing_ok=True)
    for relative in SOURCE_DIRECTORIES:
        shutil.copytree(
            ROOT / relative,
            destination / relative,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
    for relative in ROOT_SOURCE_FILES:
        shutil.copy2(ROOT / relative, destination / relative)
    for relative in OVERLAYS:
        source = ROOT / relative
        if not source.is_file():
            raise RuntimeError(f"required overlay is missing: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    dist_target = destination / "web" / "dist"
    if dist_target.exists():
        shutil.rmtree(dist_target)
    shutil.copytree(ROOT / "web" / "dist", dist_target)
    proof_dir = destination / "proof"
    proof_dir.mkdir(parents=True, exist_ok=True)
    desktop_target = destination / "artifacts" / "desktop"
    desktop_target.mkdir(parents=True, exist_ok=True)
    for bundle in (
        ROOT / "src-tauri" / "target" / "release" / "bundle" / "msi" / "Neyvia_0.1.0_x64_en-US.msi",
        ROOT / "src-tauri" / "target" / "release" / "bundle" / "nsis" / "Neyvia_0.1.0_x64-setup.exe",
    ):
        if not bundle.is_file():
            raise RuntimeError(f"required desktop release artifact is missing: {bundle}")
        shutil.copy2(bundle, desktop_target / bundle.name)
    for receipt in (
        ROOT / ".agent_control" / "release_artifacts" / "ci-production-gate.json",
        ROOT / ".agent_control" / "mission_artifacts" / "cu_acceptance" / "suite_20260725T000909Z.json",
    ):
        if not receipt.is_file():
            raise RuntimeError(f"required final release receipt is missing: {receipt}")
        shutil.copy2(receipt, proof_dir / receipt.name)
    for source, target_name in (
        (
            ROOT / ".agent_control" / "runtime_proof" / "neyvia-crash-campaign-20260721.json",
            "neyvia-crash-campaign-20260721.json",
        ),
        (
            ROOT / ".agent_control" / "crash_proof_sequence.json",
            "crash_proof_sequence.json",
        ),
    ):
        if source.is_file():
            shutil.copy2(source, proof_dir / target_name)
    shutil.copy2(
        ROOT / ".agent_control" / "runtime_proof" / "neyvia-conversation-fabric-headless.json",
        proof_dir / "neyvia-conversation-fabric-headless.json",
    )
    shutil.copy2(
        ROOT / ".agent_control" / "runtime_proof" / "neyvia-conversation-fabric-headless.png",
        proof_dir / "neyvia-conversation-fabric-headless.png",
    )
    tree = _tree(destination)
    manifest = {
        "schema": "neyvia.crashproof-candidate.manifest.v1",
        "product": "N-E-Y-V-I-A",
        "candidate": args.name,
        "baseCandidate": base.name,
        "scope": {"auvHapsIncluded": False, "publicLiveChanged": False},
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **tree,
    }
    manifest_root = ROOT / ".agent_control" / "candidate_manifests"
    manifest_root.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_root / f"{args.name}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "candidate": str(destination), "manifest": str(manifest_path), "files": tree["files"], "bytes": tree["bytes"], "treeSha256": tree["manifestSha256"], "manifestFileSha256": _sha256(manifest_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
