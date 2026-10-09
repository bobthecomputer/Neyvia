"""Source- and artifact-bound cache for a successful Vite build receipt."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re


SCHEMA = "neyvia.p22-vite-build-cache.v1"
EVIDENCE_ROOT = Path("D:/NeyviaRuns/P22").resolve()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
              "pnpm-lock.yml", "bun.lock", "bun.lockb"}
_EXCLUDED_DIRS = {".git", "node_modules", "cache", ".cache", "dist", "build", ".vite",
                  "coverage", "proof", "proofs", "evidence", "output", "outputs"}


def _under_evidence(path, label):
    path = Path(path).resolve()
    if not path.is_relative_to(EVIDENCE_ROOT):
        raise ValueError(f"{label} must stay under D:/NeyviaRuns/P22")
    return path


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _linked(path):
    path = Path(path)
    junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(junction and junction())


def _walk_files(root):
    """Yield lexical files while pruning links, junctions, and known outputs."""
    root = Path(root)
    for current, dirs, files in os.walk(root, followlinks=False):
        parent = Path(current)
        dirs[:] = sorted(name for name in dirs
                         if name.lower() not in _EXCLUDED_DIRS
                         and not _linked(parent / name))
        for name in files:
            path = parent / name
            if _linked(path):
                raise ValueError(f"Build input may not be a symlink or junction: {path}")
            yield path


def source_paths(repo):
    """Discover Vite web/public/config inputs, excluding known outputs and deps."""
    repo = Path(repo).resolve()
    web = repo / "web"
    selected = set()
    for root_name in ("package.json", *_LOCKFILES, "scripts/release-contracts.mjs"):
        path = repo / root_name
        if path.is_file():
            selected.add(path)
    for root_pattern in ("vite.config.*", "tsconfig*.json"):
        selected.update(path for path in repo.glob(root_pattern) if path.is_file())
    for dirname in ("public", "fonts"):
        directory = repo / dirname
        if directory.is_dir():
            if _linked(directory):
                raise ValueError(f"Vite source root may not be a symlink or junction: {directory}")
            selected.update(_walk_files(directory))
    if web.is_dir():
        if _linked(web):
            raise ValueError(f"Vite source root may not be a symlink or junction: {web}")
        selected.update(_walk_files(web))
    result = {}
    for path in sorted(selected):
        relative = path.relative_to(repo)
        if _linked(path) or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Vite source input escapes repository: {path}")
        result[relative.as_posix()] = _hash_file(path)
    return result


def _artifact_files(build_dir):
    root = Path(build_dir).resolve()
    if not root.is_dir():
        raise ValueError("Vite build output directory is missing")
    files = {}
    for current, dirs, names in os.walk(root, followlinks=False):
        parent = Path(current)
        dirs[:] = sorted(name for name in dirs if not _linked(parent / name))
        for name in names:
            path = parent / name
            if _linked(path):
                raise ValueError(f"Vite artifact may not escape output directory: {path}")
            files[path.relative_to(root).as_posix()] = _hash_file(path)
    if not files:
        raise ValueError("Vite build output contains no files")
    return files


def _validate_step(receipt_path, build_step):
    if (not isinstance(build_step, dict) or build_step.get("step") != "build"
            or build_step.get("ok") is not True or type(build_step.get("exitCode")) is not int
            or build_step.get("exitCode") != 0 or build_step.get("timedOut") is True
            or build_step.get("memoryExceeded") is True
            or ("sourceStable" in build_step and build_step.get("sourceStable") is not True)):
        raise ValueError("Only a successful, zero-exit, source-stable Vite build step can be cached")
    try:
        receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("Build receipt is missing or invalid") from error
    if not isinstance(receipt, dict) or receipt.get("sourceStable") is not True:
        raise ValueError("Build receipt did not validate source stability")
    rows = receipt.get("steps")
    if not isinstance(rows, list) or not any(
            isinstance(row, dict) and row.get("step") == "build"
            and row.get("ok") is True and type(row.get("exitCode")) is int
            and row.get("exitCode") == 0 and row.get("timedOut") is not True
            and row.get("memoryExceeded") is not True for row in rows):
        raise ValueError("Build receipt does not contain a successful Vite build step")
    return receipt


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def save(repo, cache_path, build_dir, source_bindings, build_step, receipt_path):
    """Persist a reusable build only after source, receipt, and output checks."""
    repo = Path(repo).resolve()
    cache_path = _under_evidence(cache_path, "Build cache")
    build_dir = _under_evidence(build_dir, "Build output")
    receipt_path = _under_evidence(receipt_path, "Build receipt")
    if not isinstance(source_bindings, dict) or any(
            not isinstance(name, str) or not isinstance(value, str) or not _SHA256.fullmatch(value)
            for name, value in source_bindings.items()):
        raise ValueError("Complete source bindings must map repository paths to SHA-256 digests")
    current_sources = source_paths(repo)
    if source_bindings != current_sources:
        raise ValueError("Vite inputs changed, were added, or were deleted since the source snapshot")
    receipt_before = _hash_file(receipt_path)
    _validate_step(receipt_path, build_step)
    artifact_files = _artifact_files(build_dir)
    if _hash_file(receipt_path) != receipt_before:
        raise ValueError("Build receipt changed while it was being bound")
    if source_paths(repo) != current_sources:
        raise ValueError("Vite inputs changed while the build cache was being saved")
    record = {
        "schema": SCHEMA,
        "build": str(build_dir),
        "sourceBindings": current_sources,
        "artifactFiles": artifact_files,
        "receipt": {"path": str(receipt_path), "sha256": receipt_before},
        "buildStep": {"step": "build", "ok": True, "exitCode": 0},
    }
    _atomic_json(cache_path, record)
    return record


def load(repo, cache_path):
    """Return only a source-, receipt-, and artifact-current build record."""
    try:
        repo = Path(repo).resolve()
        cache_path = _under_evidence(cache_path, "Build cache")
        record = json.loads(cache_path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or record.get("schema") != SCHEMA
                or set(record) != {"schema", "build", "sourceBindings", "artifactFiles", "receipt", "buildStep"}):
            return None
        build_dir = _under_evidence(record["build"], "Build output")
        if record["sourceBindings"] != source_paths(repo):
            return None
        receipt = record["receipt"]
        receipt_path = _under_evidence(receipt["path"], "Build receipt")
        if _hash_file(receipt_path) != receipt["sha256"]:
            return None
        # The receipt hash is the binding to the successful step validated at
        # save time; avoid reparsing potentially large historical receipts.
        current_artifacts = _artifact_files(build_dir)
        if current_artifacts != record["artifactFiles"]:
            return None
        return {"build": build_dir, "receipt": receipt, "sourceBindings": record["sourceBindings"],
                "artifactFiles": current_artifacts, "buildStep": record["buildStep"]}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
