"""Install Neyvia's Codex skills into ``$CODEX_HOME/skills/neyvia-*`` and keep them current.

Each installed skill folder carries ``.neyvia-skill.json`` (owner marker, Neyvia version,
per-file hashes). Only folders with that marker are ever updated or removed. A same-name
folder without it (for example one copied by hand before this installer existed) is left
alone unless ``adopt`` is true, and is then moved to ``.neyvia-backup`` first, never deleted.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .component_install import (REPO, app_version, copy_tree, now, tree_files, tree_hash,
                                unique_staging, verify_tree, write_receipt)
from .durability import atomic_write_json

MARK = ".neyvia-skill.json"
MARK_SCHEMA = "neyvia.codex_skill.v1"
SOURCE = REPO / ".codex" / "skills"
_NAME = re.compile(r"^(name:\s*)(.+?)\s*$", re.MULTILINE)


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex"


def skills_dir() -> Path:
    return codex_home() / "skills"


def installed_name(source_name: str) -> str:
    return source_name if source_name.startswith("neyvia-") else "neyvia-" + source_name


def sources(source: Path | None = None) -> dict[str, Path]:
    root = Path(source or SOURCE)
    return {installed_name(p.name): p for p in sorted(root.iterdir()) if (p / "SKILL.md").is_file()} if root.is_dir() else {}


def _rendered(folder: Path, name: str, staging: Path) -> list[tuple[str, str]]:
    """Copy one skill into staging under its installed name; the frontmatter name follows the folder."""
    rows = tree_files(folder)
    copy_tree(folder, staging, rows)
    skill = staging / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    if text.startswith("---"):
        head, _, rest = text[3:].partition("\n---")
        head = _NAME.sub(lambda m: m.group(1) + name, head, count=1) if _NAME.search(head) else head + f"\nname: {name}"
        skill.write_text("---" + head + "\n---" + rest, encoding="utf-8", newline="")
    return tree_files(staging)


def _marker(folder: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((folder / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == MARK_SCHEMA else None


def status(source: Path | None = None, target: Path | None = None) -> dict[str, Any]:
    """Per skill: not-installed, current, update-available, modified (hand edits), unmanaged (foreign folder)."""
    target = Path(target or skills_dir())
    wanted = sources(source)
    rows = []
    for name, folder in wanted.items():
        with tempfile.TemporaryDirectory(prefix="neyvia-probe-") as probe:
            bundled = tree_hash(_rendered(folder, name, Path(probe)))
        live = target / name
        mark = _marker(live)
        if not live.exists():
            state, have = "not-installed", None
        elif mark is None:
            state, have = "unmanaged", None
        else:
            have = mark.get("version")
            problems = verify_tree(live, mark.get("files") or {})
            state = "modified" if problems else "current" if mark.get("treeSha256") == bundled else "update-available"
        rows.append({"name": name, "state": state, "installedVersion": have, "bundledVersion": bundled[:12]})
    stale = []
    if target.is_dir():
        for live in sorted(target.glob("neyvia-*")):
            if live.name not in wanted and _marker(live):
                stale.append(live.name)
    return {"target": str(target), "skills": rows, "stale": stale, "appVersion": app_version()}


def install(source: Path | None = None, target: Path | None = None, *, adopt: bool = False,
            runtime_root: str | Path | None = None, only: list[str] | None = None) -> dict[str, Any]:
    """Install or update every skill (or ``only``); remove managed skills that no longer ship."""
    target = Path(target or skills_dir())
    wanted = sources(source)
    target.mkdir(parents=True, exist_ok=True)
    done, skipped, failed = [], [], []
    for name, folder in wanted.items():
        if only and name not in only:
            continue
        live = target / name
        mark = _marker(live)
        if live.exists() and mark is None and not adopt:
            skipped.append({"name": name, "reason": "A folder with this name exists that Neyvia did not install. Adopt it to back it up and replace it."})
            continue
        staging = unique_staging(target, "neyvia-stage")
        try:
            files = _rendered(folder, name, staging)
            digest = tree_hash(files)
            if mark and mark.get("treeSha256") == digest and not verify_tree(live, mark.get("files") or {}):
                shutil.rmtree(staging)
                done.append({"name": name, "action": "unchanged", "version": digest[:12]})
                continue
            version = app_version()
            atomic_write_json(staging / MARK, {"schema": MARK_SCHEMA, "name": name, "neyviaVersion": version,
                                               "version": digest[:12], "treeSha256": digest, "installedAt": now(),
                                               "files": dict(files)})
            backup_note = None
            if live.exists():
                if mark is None or verify_tree(live, mark.get("files") or {}):
                    backup = target / ".neyvia-backup" / (name + "-" + now().replace(":", ""))
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(live, backup)
                    backup_note = str(backup)
                else:
                    shutil.rmtree(live)
            os.replace(staging, live)
            done.append({"name": name, "action": "updated" if mark else "installed", "version": digest[:12],
                         "previousVersion": (mark or {}).get("version"), "backup": backup_note})
        except Exception as exc:  # noqa: BLE001 - reported per skill, others continue
            shutil.rmtree(staging, ignore_errors=True)
            failed.append({"name": name, "error": str(exc)[:300]})
    removed = []
    if not only:
        for live in sorted(target.glob("neyvia-*")):
            if live.name not in wanted and _marker(live):
                shutil.rmtree(live)
                removed.append(live.name)
    return write_receipt(runtime_root, {"component": "codex-skills", "action": "install", "ok": not failed,
                                        "status": "completed" if not failed else "partial", "target": str(target),
                                        "installed": done, "skipped": skipped, "failed": failed, "removed": removed})


def remove(target: Path | None = None, *, runtime_root: str | Path | None = None) -> dict[str, Any]:
    target = Path(target or skills_dir())
    removed = []
    for live in sorted(target.glob("neyvia-*")) if target.is_dir() else []:
        if _marker(live):
            shutil.rmtree(live)
            removed.append(live.name)
    return write_receipt(runtime_root, {"component": "codex-skills", "action": "remove", "ok": True,
                                        "status": "removed" if removed else "already_absent", "removed": removed})
