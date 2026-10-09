"""Stage a safe, complete Neyvia source workspace for immutable NAS transfer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.proofs_e_sv import enforced


def _workspace_root() -> Path:
    operator_root = Path.cwd()
    if (
        (operator_root / "pyproject.toml").is_file()
        and (operator_root / "scripts").is_dir()
    ):
        return operator_root
    return Path(__file__).resolve().parents[1]


ROOT = _workspace_root()
STAGING_ROOT = ROOT / ".agent_control" / "wip_staging"

EXCLUDED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".tox",
    ".nox",
    ".venv",
    ".venv-win",
    "venv",
    "env",
    "node_modules",
    "bower_components",
    "__pycache__",
    "target",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".parcel-cache",
    ".turbo",
    ".vite",
    "coverage",
    "htmlcov",
    "memory",
    "memories",
    "browser-profile",
    "browser_profile",
    "chrome-profile",
    "chrome_profile",
    "tmp",
    "temp",
    "tmp-ui-checks",
    ".zsign_cache",
    ".codex-backups",
    ".codex-nas-stage",
    ".codex-release-staging",
    ".agent_runs",
    ".agent_runs_eval",
    ".agent_runs_replay",
    ".agent_runs_test",
    ".checkpoint_test",
    ".demo_bundle_test",
    ".demo_dashboard_test",
    ".doc_ingestion_test",
    ".suite_report_test",
}

EXCLUDED_ROOT_FILES = {
    ".agent_memory_test.json",
    ".neyvia-candidate-complete.json",
    "AGENTS.md",
    "HEARTBEAT.md",
    "IDENTITY.md",
    "MEMORY.md",
    "SOUL.md",
    "TOOLS.md",
    "USER.md",
    "openclaw-workspace-state.json",
    "repair_loop_log.md",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
    ".pid",
    ".tmp",
    ".temp",
    ".tar",
}

ALLOWED_AGENT_CONTROL_ROOTS = (
    Path("capability_os") / "qa",
    Path("runtime_proof"),
    Path("nas_transfers"),
)

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@enforced("sv.snapshot.private-filter")
def _is_excluded(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return True
    excluded_directories = {
        directory.casefold() for directory in EXCLUDED_DIRECTORIES
    }
    if any(
        part.casefold() in excluded_directories for part in parts[:-1]
    ):
        return True
    if parts[0] == ".agent_control":
        agent_relative = Path(*parts[1:])
        if not any(
            agent_relative == allowed
            or allowed in agent_relative.parents
            for allowed in ALLOWED_AGENT_CONTROL_ROOTS
        ):
            return True
    if len(parts) == 1 and parts[0] in EXCLUDED_ROOT_FILES:
        return True
    name = parts[-1]
    if name.startswith(".tmp"):
        return True
    if Path(name).suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    if name == ".env" or name.startswith(".env."):
        return True
    return False


def _stage(name: str) -> tuple[Path, dict[str, object]]:
    destination = (STAGING_ROOT / name).resolve()
    destination.relative_to(STAGING_ROOT.resolve())
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    rows: list[dict[str, object]] = []
    excluded: list[str] = []
    sources: list[Path] = []
    for current_root, directories, filenames in os.walk(ROOT):
        current_path = Path(current_root)
        relative_root = current_path.relative_to(ROOT)
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in EXCLUDED_DIRECTORIES
            and not (
                relative_root == Path(".agent_control")
                and directory not in {path.parts[0] for path in ALLOWED_AGENT_CONTROL_ROOTS}
            )
        )
        for filename in sorted(filenames):
            sources.append(current_path / filename)

    for source in sorted(sources):
        relative = source.relative_to(ROOT)
        if destination == source or destination in source.parents:
            continue
        if source.is_symlink():
            excluded.append(f"{relative.as_posix()}:symlink")
            continue
        if not source.is_file():
            continue
        if _is_excluded(relative):
            excluded.append(relative.as_posix())
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        rows.append(
            {
                "path": relative.as_posix(),
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }
        )

    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\n")
    manifest = {
        "schema": "neyvia.safe-workspace-wip.v1",
        "name": name,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "files": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "treeSha256": digest.hexdigest(),
        "sha256Manifest": rows,
        "exclusionPolicy": {
            "purpose": "Exclude credentials, agent identity/configuration, caches, installed dependencies, build intermediates, temporary state, and obsolete transfer archives.",
            "excludedCount": len(excluded),
        },
    }
    manifest_path = destination / "NEYVIA_WIP_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination, manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage a safe complete workspace for push_neyvia_wip_ssh.py."
    )
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    destination, manifest = _stage(str(args.name).strip().lower())
    print(
        json.dumps(
            {
                "ok": True,
                "destination": str(destination),
                "filesBeforeEmbeddedManifest": manifest["files"],
                "bytesBeforeEmbeddedManifest": manifest["bytes"],
                "treeSha256BeforeEmbeddedManifest": manifest["treeSha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
