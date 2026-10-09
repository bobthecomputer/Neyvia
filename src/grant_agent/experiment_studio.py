"""Isolated, hash-manifested local experiments without source-tree overwrite."""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .durability import atomic_write_json


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_id(value: str) -> str:
    value = str(value or "").strip()
    if not value or value in {".", ".."} or len(value) > 100 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in value):
        raise ValueError("experimentId must be a safe identifier")
    return value


class ExperimentStudio:
    schema = "neyvia.experiment_studio.v1"

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.base = self.root / ".agent_control" / "experiments"
        self.base.mkdir(parents=True, exist_ok=True)

    def _inside(self, path: Path, parent: Path) -> Path:
        resolved = path.expanduser().resolve()
        try:
            resolved.relative_to(parent.resolve())
        except ValueError as exc:
            raise ValueError("experiment path escapes its permitted root") from exc
        return resolved

    def _paths(self, source: Path):
        excluded = {".git", ".agent_control", "node_modules", "__pycache__", ".venv", "venv", ".cache"}
        for directory, folders, files in os.walk(source, followlinks=False):
            folders[:] = [name for name in folders if name not in excluded]
            for name in folders + files:
                if (Path(directory) / name).is_symlink(): raise ValueError("Symlinked experiment entries are not supported")
            for name in files:
                path = Path(directory) / name
                if name.lower().startswith(".env") or path.suffix.lower() in {".pem", ".key", ".dpapi"}: continue
                yield path

    def _files(self, source: Path) -> dict[str, str]:
        return {path.relative_to(source).as_posix(): _sha(path) for path in self._paths(source)}

    def create(self, experiment_id: str, *, source: str | Path | None = None,
               launch_recipe: dict[str, Any] | None = None,
               reset_recipe: dict[str, Any] | None = None,
               evidence_paths: Iterable[str] = ()) -> dict[str, Any]:
        identity = _safe_id(experiment_id)
        source_path = self._inside(Path(source or self.root), self.root)
        if not source_path.is_dir():
            raise ValueError("source must be an existing directory")
        control = (self.root / ".agent_control").resolve()
        if source_path == control or control in source_path.parents:
            raise ValueError("source must be a scoped directory outside experiment control state")
        source_files = list(self._paths(source_path))
        destination = self.base / identity / "source"
        if destination.exists():
            raise FileExistsError(f"experiment already exists: {identity}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.mkdir()
        for source_file in source_files:
            target = destination / source_file.relative_to(source_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)
        manifest = {"schema": self.schema, "experimentId": identity,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "source": str(source_path), "snapshot": str(destination),
                    "sourceSha256": {path.relative_to(source_path).as_posix(): _sha(path) for path in source_files}, "snapshotSha256": self._files(destination),
                    "launchRecipe": dict(launch_recipe or {}), "resetRecipe": dict(reset_recipe or {}),
                    "evidencePaths": [str(v) for v in evidence_paths]}
        manifest["manifestSha256"] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        path = self.base / identity / "manifest.json"
        atomic_write_json(path, manifest)
        return {"ok": True, "experimentId": identity, "manifestPath": str(path), "snapshotPath": str(destination), "manifest": manifest}

    def inspect(self, experiment_id: str) -> dict[str, Any]:
        identity = _safe_id(experiment_id)
        path = self.base / identity / "manifest.json"
        if not path.is_file():
            return {"experimentId": identity, "status": "not_found"}
        value = json.loads(path.read_text(encoding="utf-8"))
        expected = value.get("manifestSha256")
        body = dict(value); body.pop("manifestSha256", None)
        actual = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if expected != actual:
            raise ValueError("experiment manifest hash mismatch")
        snapshot = Path(str(value.get("snapshot") or "")).resolve()
        self._inside(snapshot, self.base / identity)
        if not snapshot.is_dir() or any(path.is_symlink() for path in snapshot.rglob("*")):
            raise ValueError("experiment snapshot is missing or contains symlinks")
        return value

    def compare(self, experiment_id: str) -> dict[str, Any]:
        manifest = self.inspect(experiment_id)
        if manifest.get("status") == "not_found":
            return manifest
        snapshot = Path(manifest["snapshot"])
        current = self._files(snapshot)
        expected = dict(manifest.get("snapshotSha256") or {})
        changed = sorted(set(current) ^ set(expected) | {key for key in current.keys() & expected.keys() if current[key] != expected[key]})
        return {"experimentId": manifest["experimentId"], "status": "unchanged" if not changed else "changed", "changedPaths": changed}

    def restore(self, experiment_id: str, destination: str | Path) -> dict[str, Any]:
        manifest = self.inspect(experiment_id)
        if manifest.get("status") == "not_found":
            raise FileNotFoundError(experiment_id)
        if self.compare(experiment_id).get("status") != "unchanged":
            raise ValueError("Experiment snapshot has changed; refusing restoration")
        target = self._inside(Path(destination), self.root / ".agent_control" / "experiment_restores")
        if target.exists():
            raise FileExistsError("restore destination already exists; refusing overwrite")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(manifest["snapshot"], target, ignore=shutil.ignore_patterns(".env", ".env.*", ".git"))
        if self._files(target) != manifest["snapshotSha256"]:
            raise ValueError("Restored experiment failed integrity verification")
        return {"ok": True, "experimentId": manifest["experimentId"], "restorePath": str(target), "sha256": self._files(target)}
