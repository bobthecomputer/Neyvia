"""Bounded file browsing and export for registered project workspaces.

This module deliberately accepts workspace IDs, never a caller-supplied root.  It
is intended for use by the authenticated local controller routes.
"""
from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import re
import stat
import tempfile
import zipfile
from datetime import datetime as _datetime
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO


class ProjectFilesError(ValueError):
    """A project export request was invalid or could not be completed safely."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Workspace:
    workspace_id: str
    name: str
    root: Path


@dataclass
class DownloadDescriptor:
    file: BinaryIO
    filename: str
    size: int
    content_type: str

    def close(self) -> None:
        self.file.close()


@dataclass
class ArchiveDescriptor:
    path: Path
    filename: str
    size: int
    manifest: dict[str, Any]

    def cleanup(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 250
MAX_LISTING_ENTRIES = 10_000
MAX_PREVIEW_BYTES = 256 * 1024
MAX_ARCHIVE_FILES = 25_000
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
_CONTROL_NAMES = {".agent_control", ".git", ".svn", ".hg", ".ssh"}
_CACHE_NAMES = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", ".nuxt", "dist-cache", "coverage", "target", ".cache", ".gradle", ".turbo", ".parcel-cache", ".vite", ".svelte-kit"}
_SECRET_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "known_hosts", "authorized_keys", "credentials", "credentials.json", "secrets.json", ".aws", ".azure", ".gnupg", ".kube", ".npmrc", ".pypirc", "netrc"}
_SECRET_SUFFIXES = {".pem", ".p12", ".pfx", ".key", ".keystore"}


def _workspace_rows(payload: Any) -> list[dict[str, Any]]:
    rows = payload if isinstance(payload, list) else payload.get("workspaces", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def resolve_registered_workspace(root: Path | str, workspace_id: str) -> Workspace:
    """Resolve a registered workspace, preferring its canonical root_path."""
    clean_id = str(workspace_id or "").strip()
    if not clean_id or len(clean_id) > 200:
        raise ProjectFilesError("A registered workspace ID is required.")
    state_root = Path(root).expanduser().resolve()
    registry = state_root / ".agent_control" / "workspaces.json"
    try:
        rows = _workspace_rows(json.loads(registry.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise ProjectFilesError("Workspace registry is unavailable.", 404) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectFilesError("Workspace registry could not be read.") from exc
    for row in rows:
        registered_id = str(row.get("workspace_id") or row.get("workspaceId") or row.get("id") or "").strip()
        if registered_id != clean_id:
            continue
        if row.get("enabled") is False or str(row.get("status") or "").strip().casefold() in {"disabled", "archived", "deleted"}:
            raise ProjectFilesError("This registered workspace is disabled.", 404)
        raw_path = row.get("root_path") or row.get("rootPath") or row.get("local_project_path") or row.get("localProjectPath")
        if not str(raw_path or "").strip():
            raise ProjectFilesError("Registered workspace has no local project path.")
        candidate = Path(str(raw_path)).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProjectFilesError("Registered project folder is unavailable.", 404) from exc
        if not resolved.is_dir():
            raise ProjectFilesError("Registered project path is not a folder.", 404)
        return Workspace(clean_id, str(row.get("name") or row.get("label") or clean_id), resolved)
    raise ProjectFilesError("Unknown registered workspace ID.", 404)


def _relative_parts(raw: str | None, *, allow_empty: bool = True) -> tuple[str, ...]:
    value = str(raw or "").strip()
    if not value and allow_empty:
        return ()
    if not value or value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        raise ProjectFilesError("Path must be relative to the registered project.")
    # Accept forward slash from URLs, reject Windows alternate data streams.
    if "\\" in value or "\x00" in value:
        raise ProjectFilesError("Invalid project-relative path.")
    parts = tuple(value.split("/"))
    if any(not part or part in {".", ".."} or ":" in part for part in parts):
        raise ProjectFilesError("Invalid project-relative path.")
    return parts


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_path(workspace: Workspace, relative: str | None, *, allow_root: bool = False) -> Path:
    parts = _relative_parts(relative)
    if not parts and not allow_root:
        raise ProjectFilesError("A project-relative path is required.")
    candidate = workspace.root
    for part in parts:
        candidate = candidate / part
        if _is_link_or_junction(candidate):
            raise ProjectFilesError("Symbolic links and junctions are excluded from project browsing and export.", 403)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProjectFilesError("Project file or folder was not found or is unavailable.", 404) from exc
    if not _inside(workspace.root, resolved):
        raise ProjectFilesError("Project path resolves outside its registered folder.", 403)
    return resolved


def _is_link_or_junction(path: Path) -> bool:
    try:
        junction_check = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(junction_check and junction_check())
    except OSError:
        return False


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


_TEXT_SUFFIXES = {".txt", ".md", ".rst", ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".html", ".htm", ".css", ".scss", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".rs", ".go", ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs", ".sh", ".ps1", ".bat", ".sql", ".svg", ".csv", ".log", ".gitignore", ".editorconfig", ".env.example", ".env.sample"}


def _blocked_name(name: str) -> str | None:
    folded = name.casefold()
    if folded in _CONTROL_NAMES:
        return "protected_metadata"
    if folded in _CACHE_NAMES:
        return "generated_dependency_or_cache"
    if folded in _SECRET_NAMES or (folded.startswith(".env") and not folded.startswith(".env.example") and not folded.startswith(".env.sample")):
        return "credential_or_secret"
    if Path(folded).suffix in _SECRET_SUFFIXES:
        return "credential_or_secret"
    return None


def _assert_visible_path(workspace: Workspace, path: Path) -> None:
    relative_parts = path.relative_to(workspace.root).parts
    for part in relative_parts:
        reason = _blocked_name(part)
        if reason:
            raise ProjectFilesError(f"Project path is excluded by export policy ({reason}).", 403)


def list_project_entries(
    root: Path | str,
    workspace_id: str,
    subpath: str = "",
    offset: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    workspace = resolve_registered_workspace(root, workspace_id)
    folder = _resolve_path(workspace, subpath, allow_root=True)
    _assert_visible_path(workspace, folder)
    if not folder.is_dir():
        raise ProjectFilesError("Selected project path is not a folder.")
    try:
        clean_offset = max(0, int(offset))
        clean_limit = min(MAX_PAGE_SIZE, max(1, int(limit)))
    except (TypeError, ValueError) as exc:
        raise ProjectFilesError("Pagination values must be integers.") from exc
    rows: list[dict[str, Any]] = []
    try:
        children = list(folder.iterdir())
        if len(children) > MAX_LISTING_ENTRIES:
            raise ProjectFilesError(f"Folder has more than {MAX_LISTING_ENTRIES:,} entries; open a subfolder or narrow the export.", 413)
        children.sort(key=lambda item: (not item.is_dir(), item.name.casefold()))
        for item in children:
            try:
                resolved = item.resolve(strict=True)
                if not _inside(workspace.root, resolved):
                    continue
                reason = _blocked_name(item.name)
                if reason:
                    continue
                # Do not expose symlink/junction targets as ordinary files.
                if _is_link_or_junction(item) or resolved != item.absolute():
                    continue
                metadata = item.stat(follow_symlinks=False)
                if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
                    continue
                relative = item.relative_to(workspace.root).as_posix()
                rows.append({
                    "name": item.name,
                    "path": relative,
                    "type": "directory" if stat.S_ISDIR(metadata.st_mode) else "file",
                    "size": 0 if stat.S_ISDIR(metadata.st_mode) else metadata.st_size,
                    "modified": _timestamp(metadata.st_mtime),
                    "modifiedAt": _timestamp(metadata.st_mtime),
                    "previewable": stat.S_ISREG(metadata.st_mode) and item.suffix.casefold() in _TEXT_SUFFIXES,
                })
            except (OSError, RuntimeError):
                # A listing is observational; changed or inaccessible children are
                # omitted here and will produce a concrete error if downloaded.
                continue
    except OSError as exc:
        raise ProjectFilesError("Project folder could not be listed.") from exc
    page = rows[clean_offset:clean_offset + clean_limit]
    next_offset = clean_offset + len(page)
    path_value = folder.relative_to(workspace.root).as_posix() if folder != workspace.root else ""
    parent_value = Path(path_value).parent.as_posix() if path_value and Path(path_value).parent.as_posix() != "." else ""
    has_more = next_offset < len(rows)
    return {
        "workspace": {"id": workspace.workspace_id, "name": workspace.name},
        "workspaceId": workspace.workspace_id,
        "workspaceName": workspace.name,
        "path": path_value,
        "parentPath": parent_value,
        "entries": page,
        "offset": clean_offset,
        "nextOffset": next_offset if has_more else None,
        "total": len(rows),
        "hasMore": has_more,
        "policySummary": "Downloads include project files and generated artifacts. Credentials, VCS/control metadata, dependency/cache folders, and symlinks are excluded from ZIP exports.",
        "policy": {"excludedNames": sorted(_CONTROL_NAMES | _CACHE_NAMES | _SECRET_NAMES), "credentialSuffixes": sorted(_SECRET_SUFFIXES), "symlinks": "excluded"},
    }


def preview_project_file(
    root: Path | str,
    workspace_id: str,
    relative_path: str,
    max_bytes: int = MAX_PREVIEW_BYTES,
) -> dict[str, Any]:
    workspace = resolve_registered_workspace(root, workspace_id)
    path = _resolve_path(workspace, relative_path)
    _assert_visible_path(workspace, path)
    if not path.is_file() or path.is_symlink():
        raise ProjectFilesError("Selected project path is not a regular file.")
    cap = min(MAX_PREVIEW_BYTES, max(1, int(max_bytes)))
    try:
        metadata = path.stat()
        with path.open("rb") as source:
            sample = source.read(cap + 1)
    except OSError as exc:
        raise ProjectFilesError("Project file could not be read.") from exc
    if b"\x00" in sample:
        raise ProjectFilesError("Binary files cannot be previewed; download the file instead.")
    truncated = len(sample) > cap or metadata.st_size > cap
    sample = sample[:cap]
    try:
        content = sample.decode("utf-8-sig")
        encoding = "utf-8"
    except UnicodeDecodeError:
        content = sample.decode("utf-8", errors="replace")
        encoding = "utf-8-replacement"
    return {"name": path.name, "path": path.relative_to(workspace.root).as_posix(), "size": metadata.st_size, "modified": _timestamp(metadata.st_mtime), "content": content, "truncated": truncated, "encoding": encoding, "maxBytes": cap}


def open_project_download(root: Path | str, workspace_id: str, relative_path: str) -> DownloadDescriptor:
    workspace = resolve_registered_workspace(root, workspace_id)
    path = _resolve_path(workspace, relative_path)
    _assert_visible_path(workspace, path)
    if path.is_symlink() or not path.is_file():
        raise ProjectFilesError("Selected project path is not a regular file.")
    try:
        handle = path.open("rb")
        opened = os.fstat(handle.fileno())
        current = path.stat()
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino, opened.st_size) != (current.st_dev, current.st_ino, current.st_size):
            handle.close()
            raise ProjectFilesError("Project file changed while the download was starting; retry.", 409)
        return DownloadDescriptor(handle, path.name, opened.st_size, mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    except ProjectFilesError:
        raise
    except OSError as exc:
        raise ProjectFilesError("Project file could not be opened for download.") from exc


def create_project_archive(root: Path | str, workspace_id: str, subpath: str = "") -> ArchiveDescriptor:
    workspace = resolve_registered_workspace(root, workspace_id)
    selected = _resolve_path(workspace, subpath, allow_root=True)
    _assert_visible_path(workspace, selected)
    if not selected.is_dir():
        raise ProjectFilesError("Archive source must be a project folder.")
    skipped: dict[str, int] = {"credential_or_secret": 0, "protected_metadata": 0, "generated_dependency_or_cache": 0, "symlink_or_escape": 0}
    files: list[tuple[Path, str, os.stat_result]] = []
    total_bytes = 0
    try:
        def walk_error(error: OSError) -> None:
            raise ProjectFilesError(f"Project folder could not be fully scanned; no partial archive was created: {error.filename or error}")

        for directory, dirnames, filenames in os.walk(selected, topdown=True, followlinks=False, onerror=walk_error):
            base = Path(directory)
            keep_dirs: list[str] = []
            for dirname in sorted(dirnames, key=str.casefold):
                candidate = base / dirname
                reason = _blocked_name(dirname)
                if reason:
                    skipped[reason] += 1
                    continue
                try:
                    resolved = candidate.resolve(strict=True)
                    if _is_link_or_junction(candidate) or not _inside(workspace.root, resolved):
                        skipped["symlink_or_escape"] += 1
                        continue
                    if not resolved.is_dir():
                        continue
                except (OSError, RuntimeError):
                    raise ProjectFilesError(f"Project folder changed or became unreadable: {candidate.relative_to(workspace.root).as_posix()}", 409)
                keep_dirs.append(dirname)
            dirnames[:] = keep_dirs
            for filename in sorted(filenames, key=str.casefold):
                candidate = base / filename
                reason = _blocked_name(filename)
                if reason:
                    skipped[reason] += 1
                    continue
                try:
                    resolved = candidate.resolve(strict=True)
                    if _is_link_or_junction(candidate) or not _inside(workspace.root, resolved):
                        skipped["symlink_or_escape"] += 1
                        continue
                    metadata = candidate.stat(follow_symlinks=False)
                    if not stat.S_ISREG(metadata.st_mode):
                        continue
                    if candidate.relative_to(workspace.root).parts != resolved.relative_to(workspace.root).parts:
                        skipped["symlink_or_escape"] += 1
                        continue
                except (OSError, RuntimeError):
                    raise ProjectFilesError(f"Project file changed or became unreadable: {candidate.relative_to(workspace.root).as_posix()}", 409)
                if len(files) >= MAX_ARCHIVE_FILES:
                    raise ProjectFilesError(f"Archive exceeds the {MAX_ARCHIVE_FILES:,}-file limit; choose a smaller folder.", 413)
                total_bytes += metadata.st_size
                if total_bytes > MAX_ARCHIVE_BYTES:
                    raise ProjectFilesError(f"Archive exceeds the {MAX_ARCHIVE_BYTES // (1024**3)} GiB limit; choose a smaller folder.", 413)
                files.append((candidate, candidate.relative_to(selected).as_posix(), metadata))
    except ProjectFilesError:
        raise
    except OSError as exc:
        raise ProjectFilesError("Project folder could not be fully scanned; no partial archive was created.") from exc

    temporary = tempfile.NamedTemporaryFile(prefix="neyvia-project-", suffix=".zip", delete=False)
    archive_path = Path(temporary.name)
    temporary.close()
    written = 0
    included_files: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for source_path, archive_name, expected in files:
                try:
                    current = source_path.stat()
                    if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (expected.st_dev, expected.st_ino, expected.st_size, expected.st_mtime_ns):
                        raise ProjectFilesError(f"Project file changed while the archive was being built: {source_path.relative_to(workspace.root).as_posix()}", 409)
                    zip_datetime = _datetime.fromtimestamp(expected.st_mtime).timetuple()[:6]
                    zip_datetime = (min(2107, max(1980, zip_datetime[0])), *zip_datetime[1:])
                    info = zipfile.ZipInfo(archive_name, date_time=zip_datetime)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    with source_path.open("rb") as source, archive.open(info, "w") as destination:
                        start = os.fstat(source.fileno())
                        if _is_link_or_junction(source_path) or (start.st_dev, start.st_ino, start.st_size, start.st_mtime_ns) != (expected.st_dev, expected.st_ino, expected.st_size, expected.st_mtime_ns):
                            raise ProjectFilesError(f"Project file changed as the archive was being built: {source_path.relative_to(workspace.root).as_posix()}", 409)
                        copied = 0
                        digest = hashlib.sha256()
                        while chunk := source.read(1024 * 1024):
                            destination.write(chunk)
                            digest.update(chunk)
                            copied += len(chunk)
                        if copied != expected.st_size:
                            raise ProjectFilesError(f"Project file changed during archive creation: {source_path.relative_to(workspace.root).as_posix()}", 409)
                        end = os.fstat(source.fileno())
                        if _is_link_or_junction(source_path) or (end.st_dev, end.st_ino, end.st_size, end.st_mtime_ns) != (start.st_dev, start.st_ino, start.st_size, start.st_mtime_ns):
                            raise ProjectFilesError(f"Project file changed during archive creation: {source_path.relative_to(workspace.root).as_posix()}", 409)
                    after = source_path.stat()
                    if _is_link_or_junction(source_path) or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (expected.st_dev, expected.st_ino, expected.st_size, expected.st_mtime_ns):
                        raise ProjectFilesError(f"Project file changed during archive creation: {source_path.relative_to(workspace.root).as_posix()}", 409)
                    written += 1
                    included_files.append({"path": archive_name, "size": expected.st_size, "sha256": digest.hexdigest()})
                except ProjectFilesError:
                    raise
                except OSError as exc:
                    raise ProjectFilesError(f"Project file became unreadable; no partial archive was created: {source_path.relative_to(workspace.root).as_posix()}", 409) from exc
            # Catch a file changing after it was copied but before the ZIP closes.
            for source_path, _, expected in files:
                try:
                    final = source_path.stat()
                except OSError as exc:
                    raise ProjectFilesError(f"Project file disappeared before archive completion: {source_path.relative_to(workspace.root).as_posix()}", 409) from exc
                if _is_link_or_junction(source_path) or (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) != (expected.st_dev, expected.st_ino, expected.st_size, expected.st_mtime_ns):
                    raise ProjectFilesError(f"Project file changed before archive completion: {source_path.relative_to(workspace.root).as_posix()}", 409)
            existing_names = {name.casefold() for _, name, _ in files}
            manifest_name = "NEYVIA_EXPORT.json"
            suffix = 1
            while manifest_name.casefold() in existing_names:
                manifest_name = f"NEYVIA_EXPORT.manifest-{suffix}.json"
                suffix += 1
            manifest = {
                "workspaceId": workspace.workspace_id,
                "workspaceName": workspace.name,
                "sourcePath": selected.relative_to(workspace.root).as_posix() if selected != workspace.root else "",
                "createdAt": _timestamp(datetime.now(tz=timezone.utc).timestamp()),
                "filesIncluded": written,
                "sourceBytes": total_bytes,
                "files": included_files,
                "skipped": skipped,
                "policy": {
                    "excluded": "credential files (.env except .example/.sample; key and certificate files), VCS/control metadata, dependency/cache directories, and all symlinks",
                    "manifestPath": manifest_name,
                },
            }
            archive.writestr(manifest_name, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        size = archive_path.stat().st_size
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", workspace.name).strip("-.") or "project"
        return ArchiveDescriptor(archive_path, f"{slug}.zip", size, manifest)
    except Exception:
        try:
            archive_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
