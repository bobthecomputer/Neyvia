"""Copy an explicitly selected installed Python and its backend dependency closure.

This is a local release snapshot, never an installer: no pip, downloads, registry,
PATH, venv modifications or writes to the source interpreter.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import shutil
import site as python_site
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO = Path(__file__).resolve().parents[1]


def stage(output: Path, allow_existing_versions: bool = False) -> dict:
    output = output.resolve()
    target = (REPO / "src-tauri/target").resolve()
    if not output.is_relative_to(target) or output == target:
        raise ValueError("Output must be a fresh directory inside this worktree src-tauri/target")
    if output.exists():
        raise ValueError("Output exists; choose a fresh directory to preserve earlier snapshots")
    home = Path(sys.base_prefix).resolve()
    site = (home / "Lib/site-packages").resolve()
    allowed_sites = {site, Path(python_site.getusersitepackages()).resolve()}
    if not (home / "python.exe").is_file():
        raise ValueError("Run this helper with the explicitly selected Windows Python executable")
    declared = tomllib.loads((REPO / "pyproject.toml").read_text("utf-8"))["project"]["dependencies"]
    # The release validator uses the maintained PEP 440 parser, rather than a
    # second, approximate implementation of Python dependency constraints.
    pending = [Requirement(row) for row in declared] + [Requirement("packaging")]
    selected: dict[str, metadata.Distribution] = {}
    mismatches = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    while pending:
        required = pending.pop()
        if required.marker and not required.marker.evaluate({"extra": ""}):
            continue
        name = canonicalize_name(required.name)
        visit = (name, tuple(sorted(required.extras)))
        if visit in seen:
            continue
        dist = metadata.distribution(required.name)
        if required.specifier and not required.specifier.contains(dist.version, prereleases=True):
            mismatch = f"Installed {name} {dist.version} does not satisfy {required.specifier}"
            if not allow_existing_versions:
                raise ValueError(mismatch + "; provide an approved portable runtime instead")
            mismatches.append(mismatch)
        selected[name] = dist
        seen.add(visit)
        extras = required.extras | {""}
        for raw in dist.requires or []:
            dependency = Requirement(raw)
            if dependency.marker and not any(dependency.marker.evaluate({"extra": extra}) for extra in extras):
                continue
            dependency.marker = None  # Already evaluated against the selected parent extras.
            pending.append(dependency)

    output.mkdir(parents=True)
    excluded = {"site-packages", "__pycache__"}
    ignore = lambda _directory, names: [name for name in names if name in excluded or name.endswith((".pyc", ".pyo"))]
    for folder in ("Lib", "DLLs"):
        shutil.copytree(home / folder, output / folder, ignore=ignore)
    for source in home.iterdir():
        if source.is_file() and (source.suffix.lower() in {".exe", ".dll"} or source.name == "LICENSE.txt"):
            shutil.copy2(source, output / source.name)
    rows = []
    for name, dist in sorted(selected.items()):
        if not dist.files:
            raise ValueError(f"Installed distribution has no file inventory: {name}")
        count = 0
        distribution_root = Path(dist.locate_file("")).resolve()
        if distribution_root not in allowed_sites:
            raise ValueError(f"Distribution is outside selected interpreter site directories: {name}")
        for item in dist.files:
            source = Path(dist.locate_file(item)).resolve()
            if not source.is_relative_to(distribution_root):
                if source.is_relative_to(home / "Scripts"):
                    continue  # Console entrypoints are invoked as modules by the backend.
                raise ValueError(f"Distribution file outside selected interpreter: {name}: {item}")
            if source.suffix in {".pyc", ".pyo"} or "__pycache__" in source.parts:
                continue
            if not source.is_file() or source.is_symlink():
                raise ValueError(f"Missing or linked distribution payload: {name}: {item}")
            destination = output / "Lib/site-packages" / source.relative_to(distribution_root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            count += 1
        rows.append({"name": name, "version": dist.version, "files": count})
    (output / f"python{sys.version_info.major}{sys.version_info.minor}._pth").write_text(".\nDLLs\nLib\nLib/site-packages\n../src\nimport site\n", encoding="utf-8")
    files = [file for file in output.rglob("*") if file.is_file()]
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    receipt = {"schema": "neyvia.portable-python-snapshot/v1", "python": sys.version.split()[0], "distributionLock": rows,
               "distributionLockSha256": digest, "files": len(files), "bytes": sum(file.stat().st_size for file in files),
               "networkDownloads": 0, "systemWrites": 0, "requirementsMatch": not mismatches,
               "versionMismatches": sorted(set(mismatches)), "scope": "local-proof" if mismatches else "release-candidate"}
    (output / "runtime-provenance.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-existing-versions", action="store_true", help="Local proof only: record installed version mismatches explicitly")
    arguments = parser.parse_args()
    try:
        print(json.dumps(stage(arguments.output, arguments.allow_existing_versions), indent=2))
    except (ValueError, metadata.PackageNotFoundError) as error:
        parser.exit(1, f"{error}\n")
