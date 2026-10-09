from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path


def _workspace_root() -> Path:
    operator_root = Path.cwd()
    if (
        (operator_root / "pyproject.toml").is_file()
        and (operator_root / "scripts").is_dir()
    ):
        return operator_root
    return Path(__file__).resolve().parents[1]


ROOT = _workspace_root()
STAGING_ROOT = (ROOT / ".agent_control" / "candidate_staging").resolve()
MANIFEST_ROOT = (ROOT / ".agent_control" / "candidate_manifests").resolve()

REPLACED_DIRECTORIES = (
    ".github",
    "config",
    "docs",
    "scripts",
    "sdk",
    "src/grant_agent",
    "src/neyvia_runtime.egg-info",
    "src-tauri",
    "tests",
    "web",
)
OPTIONAL_DIRECTORIES = (
    "specs",
    "proof/20260826-neyvia-harness-html-pass",
    ".codex/skills",
    "proof/system-improvement",
)
PRUNED_DIRECTORIES = ("proof",)
ROOT_SOURCE_FILES = (
    ".gitattributes",
    "AGENTS.md",
    "GATES.md",
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "README.md",
    "uv.lock",
    "vercel.json",
    "vite.config.mjs",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_source_directory(relative: str, destination: Path) -> None:
    source = ROOT / relative
    if not source.is_dir():
        raise RuntimeError(f"required source directory is missing: {relative}")
    target = destination / relative
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            ".pytest_cache",
            "node_modules",
            "target",
            ".vite-build-receipt-temp",
            ".agent_control",
        ),
    )


def _tree(root: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"candidate contains a symlink: {path}")
        if not path.is_file() or path.name == ".neyvia-candidate-complete.json":
            continue
        relative = path.relative_to(root).as_posix()
        rows.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    rows.sort(key=lambda row: (str(row["path"]).casefold(), str(row["path"])))
    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return {
        "files": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "sha256Manifest": rows,
        "manifestSha256": digest.hexdigest(),
    }


def stage(base: Path, name: str) -> tuple[Path, Path, dict[str, object]]:
    base = base.resolve(strict=True)
    if not base.is_dir():
        raise RuntimeError("--base must be a directory")
    destination = (STAGING_ROOT / name).resolve()
    destination.relative_to(STAGING_ROOT)
    if destination.exists():
        raise RuntimeError("Candidate already exists; choose a new name to preserve its provenance")
    shutil.copytree(base, destination)
    for relative in PRUNED_DIRECTORIES:
        target = destination / relative
        if target.exists():
            shutil.rmtree(target)
    (destination / ".neyvia-candidate-complete.json").unlink(missing_ok=True)
    (destination / "NEYVIA_WIP_MANIFEST.json").unlink(missing_ok=True)

    for relative in REPLACED_DIRECTORIES:
        _copy_source_directory(relative, destination)
    for relative in OPTIONAL_DIRECTORIES:
        if (ROOT / relative).is_dir():
            _copy_source_directory(relative, destination)
    for relative in ROOT_SOURCE_FILES:
        source = ROOT / relative
        if not source.is_file():
            raise RuntimeError(f"required source file is missing: {relative}")
        shutil.copy2(source, destination / relative)

    # A Windows checkout can predate the repository's LF attributes. Normalize
    # shell entry points before sealing so bash sees the committed line endings.
    for shell_script in destination.rglob("*.sh"):
        content = shell_script.read_bytes()
        normalized = content.replace(b"\r\n", b"\n")
        if normalized != content:
            shell_script.write_bytes(normalized)

    tree = _tree(destination)
    manifest: dict[str, object] = {
        "schema": "neyvia.reconciled-candidate.manifest.v1",
        "product": "Neyvia",
        "candidate": name,
        "baseCandidate": base.name,
        "scope": {
            "sourceReconciliation": True,
            "publicLiveChanged": False,
            "secretsIncluded": False,
        },
        "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **tree,
    }
    MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = MANIFEST_ROOT / f"{name}.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return destination, manifest_path, manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage an immutable candidate from a verified NAS release plus the "
            "reconciled local source, tests, configuration, and frontend build."
        )
    )
    parser.add_argument("--base", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    name = str(args.name).strip()
    if not name.startswith("neyvia-candidate-"):
        raise RuntimeError("--name must start with neyvia-candidate-")
    destination, manifest_path, manifest = stage(Path(args.base), name)
    print(
        json.dumps(
            {
                "ok": True,
                "candidate": str(destination),
                "manifest": str(manifest_path),
                "files": manifest["files"],
                "bytes": manifest["bytes"],
                "treeSha256": manifest["manifestSha256"],
                "manifestFileSha256": _sha256(manifest_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
