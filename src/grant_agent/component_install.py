"""Shared staging, hashing and receipt helpers for Neyvia's managed components.

Same pattern as ``cli_installer``: stage next to the target, hash every file, swap in
atomically, keep the previous copy for rollback, write a receipt. Nothing here touches
the operating system PATH or anything outside the paths it is given.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .durability import atomic_write_json
from .runtimes.base import neyvia_managed_runtime_root

RECEIPT_SCHEMA = "neyvia.component_receipt.v1"
MANIFEST_SCHEMA = "neyvia.component_manifest.v1"
REPO = Path(__file__).resolve().parents[2]
DEFAULT_IGNORE = frozenset({"node_modules", "__pycache__", ".git", ".DS_Store", "Thumbs.db"})


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def app_version() -> str:
    """The version of this Neyvia build (env override, then package.json)."""
    override = os.environ.get("NEYVIA_APP_VERSION", "").strip()
    if override:
        return override
    try:  # an installed backend carries the version the bundle script staged
        staged = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        if staged:
            return staged
    except OSError:
        pass
    try:
        return str(json.loads((REPO / "package.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""


def components_root(runtime_root: str | Path | None = None) -> Path:
    base = Path(runtime_root).resolve() if runtime_root else neyvia_managed_runtime_root()
    return base / "components"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_files(root: Path, ignore: Iterable[str] = (), skip: Iterable[str] = ()) -> list[tuple[str, str]]:
    """Sorted (relative posix path, sha256) for every regular file under root.

    ``ignore`` are folder or file names skipped anywhere; ``skip`` are root-relative posix
    prefixes skipped. Links and junctions are refused: a staged tree must be plain files.
    """
    ignored = DEFAULT_IGNORE | set(ignore)
    prefixes = tuple(p.rstrip("/") + "/" for p in skip)
    rows: list[tuple[str, str]] = []
    for directory, folders, names in os.walk(root, followlinks=False):
        here = Path(directory)
        folders[:] = sorted(f for f in folders if f not in ignored)
        for folder in folders:
            child = here / folder
            if child.is_symlink() or child.is_junction():
                raise ValueError(f"Component sources must not contain links or junctions: {child}")
        for name in sorted(names):
            if name in ignored:
                continue
            path = here / name
            relative = path.relative_to(root).as_posix()
            if relative.startswith(prefixes) or relative in {p.rstrip("/") for p in skip}:
                continue
            if path.is_symlink():
                raise ValueError(f"Component sources must not contain links: {path}")
            rows.append((relative, sha256_file(path)))
    rows.sort()
    return rows


def tree_hash(rows: list[tuple[str, str]]) -> str:
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def copy_tree(source: Path, destination: Path, rows: list[tuple[str, str]]) -> None:
    """Copy exactly the listed files, then verify each copy against its hash."""
    for relative, digest in rows:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
        if sha256_file(target) != digest:
            raise RuntimeError(f"Source changed while it was copied: {relative}")


def verify_tree(root: Path, expected: dict[str, str]) -> list[str]:
    """Problems found comparing a directory with its recorded hashes (empty = intact)."""
    problems: list[str] = []
    for relative, digest in expected.items():
        path = root / relative
        if not path.is_file():
            problems.append(f"missing {relative}")
        elif sha256_file(path) != digest:
            problems.append(f"changed {relative}")
    return problems


def swap_dir(staging: Path, live: Path, backup: Path) -> None:
    """Replace ``live`` with ``staging``; the old copy stays at ``backup`` until the next swap.

    A crash between the two renames is repaired by ``recover_dir`` on the next call.
    """
    recover_dir(live, backup)
    if backup.exists():
        shutil.rmtree(backup)
    if live.exists():
        os.replace(live, backup)
    try:
        os.replace(staging, live)
    except OSError:
        if backup.exists() and not live.exists():
            os.replace(backup, live)
        raise


def recover_dir(live: Path, backup: Path) -> None:
    if not live.exists() and backup.exists():
        os.replace(backup, live)


def unique_staging(parent: Path, label: str = "stage") -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f".{label}-{uuid.uuid4().hex[:10]}"
    path.mkdir()
    return path


def write_manifest(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload = {"schema": MANIFEST_SCHEMA, **payload, "updatedAt": now()}
    atomic_write_json(path, payload)
    return payload


def read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) and payload.get("schema") == MANIFEST_SCHEMA else None


def write_receipt(runtime_root: str | Path | None, payload: dict[str, Any]) -> dict[str, Any]:
    base = Path(runtime_root).resolve() if runtime_root else neyvia_managed_runtime_root()
    receipt_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}"
    path = base / "receipts" / f"{receipt_id}.json"
    payload = {"schema": RECEIPT_SCHEMA, "receiptId": receipt_id, "receiptPath": str(path),
               "generatedAt": now(), "systemPathChanged": False, **payload}
    atomic_write_json(path, payload)
    return payload


def human_size(count: int | None) -> str:
    if not count:
        return ""
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""
