from __future__ import annotations

import argparse
import ctypes
import errno
import fnmatch
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any


TRANSFER_SCHEMA = "neyvia.nas_transfer.v1"
BATCH_TRANSFER_SCHEMA = "neyvia.nas_transfer.batch.v1"
MANIFEST_SCHEMA = "neyvia.nas_transfer.manifest.v1"
CANDIDATE_COMPLETION_SCHEMA = "neyvia.nas_transfer.candidate_completion.v1"
CANDIDATE_COMPLETION_FILENAME = ".neyvia-candidate-complete.json"
CANDIDATE_INCOMPLETE_SCHEMA = "neyvia.nas_transfer.candidate_incomplete.v1"
CANDIDATE_INCOMPLETE_FILENAME = ".neyvia-candidate-incomplete.json"
DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_PROJECTS_SUBDIR = "projects"
DEFAULT_SHARE = "Saclay"
DEFAULT_HOSTS = (
    "192.0.2.10",
    "192.0.2.10",
    "nas.example.invalid",
    "nas.example.invalid",
)
DEFAULT_POSIX_NAS_ROOTS = ("/volume1/Saclay/projects",)
DEFAULT_EXCLUDED_DIRECTORIES = (
    ".agent_control",
    ".agent_runs*",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "bower_components",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".gradle",
    ".angular",
    ".expo",
    ".dart_tool",
    ".ipynb_checkpoints",
    ".nyc_output",
    ".pnpm-store",
    ".serverless",
    ".terraform",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "out",
    "target",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".parcel-cache",
    ".turbo",
    ".vite",
    ".eggs",
    "*.egg-info",
    "cmake-build-*",
    "CMakeFiles",
    "DerivedData",
    "coverage",
    "htmlcov",
    "logs",
    "log",
    "tmp",
    "temp",
)
DEFAULT_EXCLUDED_FILES = (
    "*.log",
    "*.log.*",
    "*.tmp",
    "*.temp",
    "*.cache",
    "*.bak",
    "*.swp",
    "*.swo",
    "*~",
    "*.pyc",
    "*.pyo",
    ".coverage",
    ".coverage.*",
    "coverage.xml",
    "coverage.json",
    "lcov.info",
    "npm-debug.log*",
    "yarn-debug.log*",
    "yarn-error.log*",
    "pnpm-debug.log*",
    ".DS_Store",
    "Thumbs.db",
    ".env*",
    ".npmrc",
    ".npmrc.*",
    ".pypirc",
    ".netrc",
    "client_secret*",
    "client-secret*",
    "credentials.json",
    "credentials.*.json",
    "credential*.json",
    "secrets.json",
    "secret*.json",
    "token.json",
    "tokens.json",
    "auth_token*",
    "access_token*",
    "refresh_token*",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
)
EXPLICIT_GENERATED_SOURCE_DIRECTORIES = (
    "dist",
    "build",
    "out",
    "target",
)
WINDOWS_DRIVE_REMOTE = 4
WINDOWS_ERROR_MORE_DATA = 234


class NasTransferError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _safe_relative_destination(value: str | None, source_name: str) -> Path:
    if value:
        destination = Path(value.replace("\\", "/"))
        if destination.is_absolute() or destination.drive or any(part == ".." for part in destination.parts):
            raise NasTransferError("destination must be a relative path inside the NAS projects root")
        if not destination.parts:
            raise NasTransferError("destination cannot be empty")
        return destination
    hostname = platform.node().strip() or socket.gethostname().strip() or "workstation"
    safe_host = "".join(character if character.isalnum() or character in "-_" else "-" for character in hostname)
    return Path("agent-drop") / safe_host / source_name


def _is_syntelos_release_destination(destination: Path) -> bool:
    parts = tuple(part.casefold() for part in destination.parts)
    return len(parts) >= 2 and parts[:2] == ("syntelos", "releases")


def _windows_drive_type(path: Path) -> int:
    if os.name != "nt" or not path.drive:
        return 0
    root = f"{path.drive}\\"
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(root))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return 0


def _unc_location(value: str | Path) -> tuple[str, str, tuple[str, ...]] | None:
    """Return a normalized UNC server/share/tail without touching the network."""
    raw = str(value).replace("/", "\\")
    extended_prefix = "\\\\?\\UNC\\"
    if raw.casefold().startswith(extended_prefix.casefold()):
        raw = "\\\\" + raw[len(extended_prefix) :]
    elif raw.startswith("\\\\?\\"):
        return None
    if not raw.startswith("\\\\"):
        return None
    parts = tuple(part for part in raw[2:].split("\\") if part)
    if len(parts) < 2:
        return "", "", parts
    return parts[0], parts[1], parts[2:]


def _local_host_aliases() -> set[str]:
    aliases = {".", "localhost", "127.0.0.1", "::1", "[::1]"}
    for value in (platform.node(), socket.gethostname()):
        folded = value.strip().rstrip(".").casefold()
        if folded:
            aliases.add(folded)
            aliases.add(folded.split(".", 1)[0])
    return aliases


def _authoritative_nas_identity() -> tuple[set[str], set[str]]:
    config = _read_cowork_config()
    configured_host = str(config.get("nas_host") or "").strip().rstrip(".").casefold()
    configured_share = str(config.get("share_name") or "").strip().casefold()
    hosts = {item.strip().rstrip(".").casefold() for item in DEFAULT_HOSTS if item.strip()}
    shares = {DEFAULT_SHARE.casefold()}
    if configured_host:
        hosts.add(configured_host)
    if configured_share:
        shares.add(configured_share)
    return hosts, shares


def _validate_unc_nas_root(value: str | Path, *, label: str) -> bool:
    location = _unc_location(value)
    if location is None:
        return False
    server, share, tail = location
    folded_server = server.strip().rstrip(".").casefold()
    if not server or not share:
        raise NasTransferError(f"{label} UNC NAS root must include a server and share: {value}")
    if folded_server in _local_host_aliases() or folded_server.split(".", 1)[0] in _local_host_aliases():
        raise NasTransferError(f"{label} UNC NAS root points back to this local machine and was rejected: {value}")
    if share.endswith("$"):
        raise NasTransferError(f"{label} UNC NAS root cannot use an administrative drive share: {value}")
    if len(tail) != 1 or tail[0].casefold() != DEFAULT_PROJECTS_SUBDIR:
        raise NasTransferError(
            f"{label} UNC NAS root must be exactly \\\\server\\share\\{DEFAULT_PROJECTS_SUBDIR}: {value}"
        )
    allowed_hosts, allowed_shares = _authoritative_nas_identity()
    if folded_server not in allowed_hosts:
        expected = ", ".join(sorted(allowed_hosts))
        raise NasTransferError(
            f"{label} UNC NAS server is not an authoritative Neyvia host: {server}. "
            f"Expected one of: {expected}"
        )
    if share.casefold() not in allowed_shares:
        expected = ", ".join(sorted(allowed_shares))
        raise NasTransferError(
            f"{label} UNC NAS share is not an authoritative Neyvia share: {share}. "
            f"Expected one of: {expected}"
        )
    return True


def _windows_mapped_drive_unc(path: Path) -> str | None:
    if os.name != "nt" or not path.drive:
        return None
    try:
        length = ctypes.c_uint(2048)
        buffer = ctypes.create_unicode_buffer(length.value)
        result = int(
            ctypes.windll.mpr.WNetGetConnectionW(  # type: ignore[attr-defined]
                path.drive,
                buffer,
                ctypes.byref(length),
            )
        )
        if result == WINDOWS_ERROR_MORE_DATA:
            buffer = ctypes.create_unicode_buffer(length.value)
            result = int(
                ctypes.windll.mpr.WNetGetConnectionW(  # type: ignore[attr-defined]
                    path.drive,
                    buffer,
                    ctypes.byref(length),
                )
            )
        if result != 0:
            return None
        return str(buffer.value).strip() or None
    except (AttributeError, OSError, ValueError):
        return None


def _validate_mapped_drive_nas_root(path: str | Path, remote_root: str, *, label: str) -> None:
    windows_path = PureWindowsPath(str(path))
    if not windows_path.drive:
        raise NasTransferError(f"{label} mapped drive path has no drive identity: {path}")
    drive_root = PureWindowsPath(f"{windows_path.drive}\\")
    try:
        mapped_relative = windows_path.relative_to(drive_root)
    except ValueError as exc:
        raise NasTransferError(f"{label} mapped drive path is invalid: {path}") from exc
    _validate_unc_nas_root(PureWindowsPath(remote_root) / mapped_relative, label=label)


def _trusted_posix_nas_roots() -> set[Path]:
    configured = str(os.environ.get("NEYVIA_NAS_TRUSTED_PROJECTS_ROOT") or "").strip()
    values = [*DEFAULT_POSIX_NAS_ROOTS]
    if configured:
        values.extend(item for item in configured.split(os.pathsep) if item.strip())
    roots: set[Path] = set()
    for value in values:
        try:
            roots.add(Path(value).expanduser().resolve(strict=False))
        except OSError:
            continue
    return roots


def _validated_nas_projects_root(
    value: str | Path,
    *,
    label: str,
    allow_local_root: bool = False,
) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise NasTransferError(f"{label} NAS root must be an absolute path: {path}")
    if path.name.casefold() != DEFAULT_PROJECTS_SUBDIR:
        raise NasTransferError(
            f"{label} NAS root must point to the '{DEFAULT_PROJECTS_SUBDIR}' directory, not: {path}"
        )
    if not path.exists() or not path.is_dir():
        raise NasTransferError(f"{label} NAS projects root is unavailable: {path}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise NasTransferError(f"{label} NAS projects root cannot be resolved: {path}") from exc
    if resolved.name.casefold() != DEFAULT_PROJECTS_SUBDIR:
        raise NasTransferError(
            f"{label} NAS root must point to the '{DEFAULT_PROJECTS_SUBDIR}' directory, not: {resolved}"
        )
    if allow_local_root:
        return resolved
    if os.name == "nt":
        raw_is_unc = _validate_unc_nas_root(path, label=label)
        resolved_is_unc = _validate_unc_nas_root(resolved, label=label)
        is_unc = raw_is_unc or resolved_is_unc
        is_mapped_network_drive = _windows_drive_type(path) == WINDOWS_DRIVE_REMOTE
        if not is_unc and not is_mapped_network_drive:
            raise NasTransferError(
                f"{label} NAS root is on a local Windows drive and was rejected: {resolved}. "
                "Use a UNC projects path or a mapped network drive."
            )
        if is_mapped_network_drive and not is_unc:
            remote_root = _windows_mapped_drive_unc(path)
            if not remote_root:
                raise NasTransferError(
                    f"{label} mapped drive identity could not be resolved and was rejected: {path}. "
                    "Use the authoritative UNC projects path or repair the mapped drive."
                )
            _validate_mapped_drive_nas_root(path, remote_root, label=label)
    else:
        trusted_roots = _trusted_posix_nas_roots()
        if resolved not in trusted_roots:
            expected = ", ".join(sorted(str(item) for item in trusted_roots))
            raise NasTransferError(
                f"{label} NAS root is not an authoritative Neyvia projects mount: {resolved}. "
                f"Expected one of: {expected}"
            )
    return resolved


def _cowork_config_candidates() -> list[Path]:
    cowork_root = Path(os.environ.get("NEYVIA_COWORK_ROOT") or (Path.home() / "Projects" / "Cowork"))
    return [
        cowork_root / "synology-direct-target.json",
        cowork_root / "synology-fast-target.json",
    ]


def _read_cowork_config() -> dict[str, Any]:
    for path in _cowork_config_candidates():
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _tcp_reachable(host: str, port: int = 445, timeout: float = 0.75) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _authenticate_share(share_root: str) -> None:
    if os.name != "nt":
        return
    password_configured = any(
        bool((os.environ.get(variable) or "").strip())
        for variable in ("NEYVIA_NAS_PASSWORD", "FLUXIO_NAS_PASSWORD")
    )
    suffix = (
        " Password environment variables are intentionally not consumed; unset them after moving the secret "
        "to Windows Credential Manager."
        if password_configured
        else ""
    )
    raise NasTransferError(
        f"NAS share is reachable but is not preauthenticated: {share_root}. "
        "Authenticate it outside Neyvia with Windows Credential Manager or an interactive mapped drive; "
        "Neyvia will not place a NAS password in a child-process command line."
        f"{suffix}"
    )


def discover_nas_projects_root(
    explicit: str | Path | None = None,
    *,
    allow_local_root: bool = False,
) -> tuple[Path | None, str]:
    """Find a ready NAS projects root without mounting, deleting, or replacing drives."""
    if explicit is not None and str(explicit).strip():
        return (
            _validated_nas_projects_root(
                explicit,
                label="Explicit",
                allow_local_root=allow_local_root,
            ),
            "explicit",
        )

    for variable in ("NEYVIA_NAS_TRANSFER_ROOT", "NEYVIA_NAS_ROOT", "FLUXIO_NAS_ROOT"):
        configured = os.environ.get(variable)
        if configured and configured.strip():
            return (
                _validated_nas_projects_root(
                    configured,
                    label=variable,
                    allow_local_root=allow_local_root,
                ),
                "environment",
            )

    config = _read_cowork_config()
    local_candidates: list[tuple[str | Path | None, str]] = [
        (config.get("target_root"), "cowork-config"),
        (Path("Y:/projects") if os.name == "nt" else None, "mapped-drive"),
    ]
    for raw, route in local_candidates:
        if not raw:
            continue
        path = Path(raw).expanduser()
        try:
            is_available = path.exists() and path.is_dir()
        except OSError:
            is_available = False
        if not is_available:
            continue
        try:
            return (
                _validated_nas_projects_root(
                    path,
                    label=route,
                    allow_local_root=allow_local_root,
                ),
                route,
            )
        except NasTransferError:
            continue

    if os.name != "nt":
        return None, "unavailable"

    share = str(config.get("share_name") or DEFAULT_SHARE).strip()
    projects_subdir = str(config.get("projects_subdir") or DEFAULT_PROJECTS_SUBDIR).strip("\\/")
    configured_host = str(config.get("nas_host") or "").strip()
    hosts = list(dict.fromkeys([configured_host, *DEFAULT_HOSTS]))
    authentication_error: NasTransferError | None = None
    for host in (item for item in hosts if item):
        if not _tcp_reachable(host):
            continue
        share_root = rf"\\{host}\{share}"
        projects_root = Path(share_root) / projects_subdir
        try:
            is_available = projects_root.exists() and projects_root.is_dir()
        except OSError:
            is_available = False
        if not is_available:
            try:
                _authenticate_share(share_root)
            except NasTransferError as exc:
                authentication_error = exc
                continue
        if projects_root.exists() and projects_root.is_dir():
            route = "tailscale" if host.startswith("100.") else "lan"
            return (
                _validated_nas_projects_root(
                    projects_root,
                    label=route,
                    allow_local_root=allow_local_root,
                ),
                route,
            )
    if authentication_error is not None:
        raise authentication_error
    return None, "unavailable"


def _copy_file_resumable(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.neyvia-partial")
    source_stat = source.stat()
    source_size = source_stat.st_size
    if _file_metadata_matches(source, destination):
        if partial.exists():
            partial.unlink()
        return {
            "files": 1,
            "bytes": source_size,
            "transferredBytes": 0,
            "resumedFromBytes": 0,
            "transferredFiles": 0,
            "skippedFiles": 1,
            "sha256": None,
        }
    resumed_from = partial.stat().st_size if partial.exists() else 0
    if resumed_from > source_size:
        partial.unlink()
        resumed_from = 0
    mode = "ab" if resumed_from else "wb"
    with source.open("rb") as reader, partial.open(mode) as writer:
        reader.seek(resumed_from)
        shutil.copyfileobj(reader, writer, length=8 * 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    if partial.stat().st_size != source_size:
        raise NasTransferError("file copy ended before all bytes were written")
    source_hash = _sha256(source)
    if _sha256(partial) != source_hash:
        raise NasTransferError("file checksum verification failed")
    os.replace(partial, destination)
    try:
        shutil.copystat(source, destination)
    except OSError:
        pass
    return {
        "files": 1,
        "bytes": source_size,
        "transferredBytes": source_size - resumed_from,
        "resumedFromBytes": resumed_from,
        "transferredFiles": 1,
        "skippedFiles": 0,
        "sha256": source_hash,
    }


def _file_metadata_matches(source: Path, destination: Path) -> bool:
    try:
        source_stat = source.stat()
        destination_stat = destination.stat()
    except OSError:
        return False
    return (
        destination.is_file()
        and source_stat.st_size == destination_stat.st_size
        and source_stat.st_mtime_ns == destination_stat.st_mtime_ns
    )


def _matches_any(name: str, patterns: tuple[str, ...]) -> bool:
    folded = name.casefold()
    return any(fnmatch.fnmatchcase(folded, pattern.casefold()) for pattern in patterns)


def _validate_sensitive_source(
    source: Path,
    *,
    include_all: bool,
    label: str,
    allow_excluded_root: bool = False,
) -> None:
    if include_all:
        return
    if source.is_file() and _matches_any(source.name, DEFAULT_EXCLUDED_FILES):
        raise NasTransferError(
            f"{label} is excluded by the safe secret/generated-file policy: {source.name}. "
            "Use --include-all only for an intentional trusted backup."
        )
    excluded_directory_root = source.is_dir() and _matches_any(
        source.name,
        DEFAULT_EXCLUDED_DIRECTORIES,
    )
    explicitly_allowed_generated_root = source.is_dir() and _matches_any(
        source.name,
        EXPLICIT_GENERATED_SOURCE_DIRECTORIES,
    )
    if allow_excluded_root and not explicitly_allowed_generated_root:
        raise NasTransferError(
            f"{label} cannot use allowExcludedRoot for state, dependency, cache, or ordinary roots: "
            f"{source.name}. The exception is limited to explicit generated artifact roots."
        )
    if excluded_directory_root and not (
        allow_excluded_root and explicitly_allowed_generated_root
    ):
        raise NasTransferError(
            f"{label} directory root is excluded by the safe state/generated-directory policy: "
            f"{source.name}. Immutable manifests may set allowExcludedRoot=true only for an "
            "intentional generated artifact root; use --include-all only for a trusted full backup."
        )


def _directory_inventory(source: Path, destination: Path, *, include_all: bool) -> dict[str, Any]:
    included_files: list[Path] = []
    included_directories: list[Path] = []
    excluded_directories: list[str] = []
    excluded_files: list[str] = []
    for current_raw, directory_names, file_names in os.walk(source, followlinks=False):
        current = Path(current_raw)
        relative_current = current.relative_to(source)
        included_directories.append(relative_current)
        kept_directories: list[str] = []
        for name in directory_names:
            relative = relative_current / name
            if not include_all and _matches_any(name, DEFAULT_EXCLUDED_DIRECTORIES):
                excluded_directories.append(relative.as_posix())
            else:
                kept_directories.append(name)
        directory_names[:] = kept_directories
        for name in file_names:
            relative = relative_current / name
            if not include_all and _matches_any(name, DEFAULT_EXCLUDED_FILES):
                excluded_files.append(relative.as_posix())
                continue
            source_file = source / relative
            if source_file.is_file():
                included_files.append(relative)
    changed_files = [
        relative
        for relative in included_files
        if not _file_metadata_matches(source / relative, destination / relative)
    ]
    total_bytes = sum((source / relative).stat().st_size for relative in included_files)
    transferred_bytes = sum((source / relative).stat().st_size for relative in changed_files)
    return {
        "files": included_files,
        "directories": included_directories,
        "changedFiles": changed_files,
        "bytes": total_bytes,
        "transferredBytes": transferred_bytes,
        "excludedDirectories": excluded_directories,
        "excludedFiles": excluded_files,
    }


def _verify_transferred_files(source: Path, destination: Path, relative_paths: list[Path]) -> dict[str, Any]:
    verified_files: list[dict[str, Any]] = []
    manifest_digest = hashlib.sha256()
    for relative in sorted(relative_paths, key=lambda item: item.as_posix().casefold()):
        source_file = source / relative
        destination_file = destination / relative
        if not source_file.is_file() or not destination_file.is_file():
            raise NasTransferError(f"transferred file is missing during verification: {relative.as_posix()}")
        source_hash = _sha256(source_file)
        if _sha256(destination_file) != source_hash:
            raise NasTransferError(f"file checksum verification failed: {relative.as_posix()}")
        path_text = relative.as_posix()
        size = source_file.stat().st_size
        manifest_digest.update(path_text.encode("utf-8"))
        manifest_digest.update(b"\0")
        manifest_digest.update(source_hash.encode("ascii"))
        manifest_digest.update(b"\n")
        verified_files.append({"path": path_text, "bytes": size, "sha256": source_hash})
    if not verified_files:
        return {
            "status": "not-required",
            "method": "unchanged-metadata",
            "files": 0,
            "bytes": 0,
            "sha256Manifest": [],
            "manifestSha256": None,
        }
    return {
        "status": "verified",
        "method": "sha256-transferred-files",
        "files": len(verified_files),
        "bytes": sum(int(item["bytes"]) for item in verified_files),
        "sha256Manifest": verified_files,
        "manifestSha256": manifest_digest.hexdigest(),
    }


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    """Return Path.is_relative_to semantics on the NAS Python 3.8 runtime."""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def candidate_tree_verification(root: str | Path) -> dict[str, Any]:
    candidate_root = Path(root).resolve(strict=True)
    rows: list[dict[str, Any]] = []
    reserved_root_files = {CANDIDATE_COMPLETION_FILENAME, CANDIDATE_INCOMPLETE_FILENAME}
    for current_raw, directory_names, file_names in os.walk(candidate_root, followlinks=False):
        current = Path(current_raw)
        for name in directory_names:
            directory = current / name
            if directory.is_symlink():
                raise NasTransferError(
                    f"candidate tree contains a directory symlink: {directory.relative_to(candidate_root).as_posix()}"
                )
        for name in file_names:
            path = current / name
            relative = path.relative_to(candidate_root)
            if len(relative.parts) == 1 and name in reserved_root_files:
                continue
            if path.is_symlink() or not path.is_file():
                raise NasTransferError(f"candidate tree contains a non-regular file: {relative.as_posix()}")
            rows.append(
                {
                    "path": relative.as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    rows.sort(key=lambda item: (str(item["path"]).casefold(), str(item["path"])))
    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return {
        "status": "verified",
        "method": "sha256-complete-candidate-tree",
        "files": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "sha256Manifest": rows,
        "manifestSha256": digest.hexdigest(),
    }


def _candidate_item_verification(items: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in items:
        item_root = Path(str(item["candidateRelativeDestination"]))
        verification = item.get("verification") or {}
        if int(item.get("transferredFiles") or 0) != int(item.get("files") or 0) or int(
            item.get("skippedFiles") or 0
        ):
            raise NasTransferError(
                f"fresh candidate item unexpectedly reused destination content: {item_root.as_posix()}"
            )
        if int(item.get("files") or 0) and verification.get("status") != "verified":
            raise NasTransferError(
                f"fresh candidate item was not fully verified: {item_root.as_posix()}"
            )
        for entry in verification.get("sha256Manifest", []):
            entry_path = Path(str(entry["path"]))
            candidate_path = item_root if str(entry_path) == "." else item_root / entry_path
            rows.append(
                {
                    "path": candidate_path.as_posix(),
                    "bytes": int(entry["bytes"]),
                    "sha256": str(entry["sha256"]),
                }
            )
    rows.sort(key=lambda item: (str(item["path"]).casefold(), str(item["path"])))
    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return {
        "status": "verified",
        "method": "sha256-transferred-candidate-files",
        "files": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "sha256Manifest": rows,
        "manifestSha256": digest.hexdigest(),
    }


def _atomic_rename_new(source: Path, destination: Path) -> None:
    if _path_lexists(destination):
        raise NasTransferError(f"candidate destination already exists and will not be replaced: {destination}")
    if sys.platform.startswith("linux"):
        try:
            renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
        except AttributeError:
            renameat2 = None
        if renameat2 is not None:
            renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            renameat2.restype = ctypes.c_int
            result = int(
                renameat2(
                    -100,
                    os.fsencode(source),
                    -100,
                    os.fsencode(destination),
                    1,
                )
            )
            if result == 0:
                return
            error_number = ctypes.get_errno()
            if error_number == errno.EEXIST:
                raise NasTransferError(
                    f"candidate destination already exists and will not be replaced: {destination}"
                )
            if error_number not in {errno.ENOSYS, errno.EINVAL}:
                raise OSError(error_number, os.strerror(error_number), str(destination))
    if _path_lexists(destination):
        raise NasTransferError(f"candidate destination already exists and will not be replaced: {destination}")
    os.rename(source, destination)


def _copy_directory(
    source: Path,
    destination: Path,
    timeout_seconds: int,
    *,
    include_all: bool,
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    inventory = _directory_inventory(source, destination, include_all=include_all)
    changed_files = list(inventory["changedFiles"])
    for relative_directory in inventory["directories"]:
        (destination / relative_directory).mkdir(parents=True, exist_ok=True)
    robocopy = shutil.which("robocopy") if os.name == "nt" else None
    transferred_bytes = int(inventory["transferredBytes"])
    resumed_from_bytes = 0
    if not changed_files:
        copy_method = "metadata-skip"
        transferred_bytes = 0
    elif robocopy:
        command = [
            robocopy,
            str(source),
            str(destination),
            "/E",
            "/Z",
            "/J",
            "/MT:16",
            "/R:2",
            "/W:1",
            "/COPY:DAT",
            "/DCOPY:DAT",
            "/XJ",
            "/NFL",
            "/NDL",
            "/NP",
            "/NJH",
            "/NJS",
        ]
        if not include_all:
            command.extend(["/XD", *DEFAULT_EXCLUDED_DIRECTORIES])
            command.extend(["/XF", *DEFAULT_EXCLUDED_FILES])
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise NasTransferError(f"folder transfer exceeded {timeout_seconds} seconds") from exc
        if completed.returncode >= 8:
            message = (completed.stderr or completed.stdout or "robocopy failed").strip()
            raise NasTransferError(f"folder transfer failed (robocopy {completed.returncode}): {message}")
        copy_method = "robocopy"
    else:
        copy_results: list[dict[str, Any]] = []
        for relative in changed_files:
            copy_results.append(_copy_file_resumable(source / relative, destination / relative))
        transferred_bytes = sum(int(result["transferredBytes"]) for result in copy_results)
        resumed_from_bytes = sum(int(result["resumedFromBytes"]) for result in copy_results)
        copy_method = "python-resumable-files"
    verification = _verify_transferred_files(source, destination, changed_files)
    return {
        "copyMethod": copy_method,
        "files": len(inventory["files"]),
        "bytes": int(inventory["bytes"]),
        "transferredBytes": transferred_bytes,
        "resumedFromBytes": resumed_from_bytes,
        "transferredFiles": len(changed_files),
        "skippedFiles": len(inventory["files"]) - len(changed_files),
        "verification": verification,
        "exclusions": {
            "enabled": not include_all,
            "directories": list(inventory["excludedDirectories"]),
            "files": list(inventory["excludedFiles"]),
        },
    }


class NasTransfer:
    def __init__(
        self,
        workspace_root: str | Path,
        nas_root: str | Path | None = None,
        *,
        allow_local_nas_root: bool = False,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.explicit_nas_root = nas_root
        self.allow_local_nas_root = allow_local_nas_root

    @staticmethod
    def _validate_source(source: str | Path) -> Path:
        source_path = Path(source).expanduser().resolve()
        if not source_path.exists():
            raise NasTransferError(f"source does not exist: {source_path}")
        if not source_path.is_file() and not source_path.is_dir():
            raise NasTransferError(f"source must be a regular file or folder: {source_path}")
        return source_path

    @staticmethod
    def _validate_timeout(timeout_seconds: int) -> None:
        if timeout_seconds < 1:
            raise NasTransferError("timeout_seconds must be at least 1")

    def _resolve_nas_root(self) -> tuple[Path, str]:
        nas_root, route = discover_nas_projects_root(
            self.explicit_nas_root,
            allow_local_root=self.allow_local_nas_root,
        )
        if nas_root is None:
            raise NasTransferError(
                "NAS projects root is unavailable. Map the Saclay share, set NEYVIA_NAS_TRANSFER_ROOT, "
                "or preauthenticate the authoritative share with Windows Credential Manager."
            )
        return nas_root, route

    def _preflight_authoritative_nas_root(self) -> tuple[Path, str] | None:
        has_explicit_root = self.explicit_nas_root is not None and bool(str(self.explicit_nas_root).strip())
        has_environment_root = any(
            bool((os.environ.get(variable) or "").strip())
            for variable in ("NEYVIA_NAS_TRANSFER_ROOT", "NEYVIA_NAS_ROOT", "FLUXIO_NAS_ROOT")
        )
        if has_explicit_root or has_environment_root:
            return self._resolve_nas_root()
        return None

    @staticmethod
    def _validated_destination_path(nas_root: Path, relative_destination: Path) -> Path:
        try:
            resolved_root = nas_root.resolve(strict=True)
            destination_path = resolved_root / relative_destination
            resolved_destination = destination_path.resolve(strict=False)
            resolved_destination.relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise NasTransferError(
                "destination resolves outside the validated NAS projects root: "
                f"{relative_destination.as_posix()}"
            ) from exc
        return destination_path

    @staticmethod
    def _transfer_item(
        source_path: Path,
        nas_root: Path,
        relative_destination: Path,
        *,
        timeout_seconds: int,
        include_all: bool,
    ) -> dict[str, Any]:
        destination_path = NasTransfer._validated_destination_path(nas_root, relative_destination)
        if source_path.is_file():
            details = _copy_file_resumable(source_path, destination_path)
            if details["transferredFiles"]:
                verification = {
                    "status": "verified",
                    "method": "sha256",
                    "files": 1,
                    "bytes": details["bytes"],
                    "sha256": details["sha256"],
                    "sha256Manifest": [
                        {"path": ".", "bytes": details["bytes"], "sha256": details["sha256"]}
                    ],
                    "manifestSha256": details["sha256"],
                }
            else:
                verification = {
                    "status": "not-required",
                    "method": "unchanged-metadata",
                    "files": 0,
                    "bytes": 0,
                    "sha256": None,
                    "sha256Manifest": [],
                    "manifestSha256": None,
                }
            return {
                "source": str(source_path),
                "destination": str(destination_path),
                "relativeDestination": relative_destination.as_posix(),
                "kind": "file",
                "copyMethod": "resumable-atomic-file",
                "files": details["files"],
                "bytes": details["bytes"],
                "transferredBytes": details["transferredBytes"],
                "resumedFromBytes": details["resumedFromBytes"],
                "transferredFiles": details["transferredFiles"],
                "skippedFiles": details["skippedFiles"],
                "verification": verification,
                "exclusions": {"enabled": False, "directories": [], "files": []},
            }
        details = _copy_directory(
            source_path,
            destination_path,
            timeout_seconds,
            include_all=include_all,
        )
        return {
            "source": str(source_path),
            "destination": str(destination_path),
            "relativeDestination": relative_destination.as_posix(),
            "kind": "directory",
            **details,
        }

    @staticmethod
    def _combined_verification(items: list[dict[str, Any]]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for item in items:
            item_root = Path(str(item["relativeDestination"]))
            for entry in item["verification"].get("sha256Manifest", []):
                entry_path = Path(str(entry["path"]))
                combined_path = item_root if str(entry_path) == "." else item_root / entry_path
                rows.append(
                    {
                        "path": combined_path.as_posix(),
                        "bytes": int(entry["bytes"]),
                        "sha256": str(entry["sha256"]),
                    }
                )
        rows.sort(key=lambda item: item["path"].casefold())
        if not rows:
            return {
                "status": "not-required",
                "method": "unchanged-metadata",
                "files": 0,
                "bytes": 0,
                "sha256Manifest": [],
                "manifestSha256": None,
            }
        digest = hashlib.sha256()
        for row in rows:
            digest.update(row["path"].encode("utf-8"))
            digest.update(b"\0")
            digest.update(row["sha256"].encode("ascii"))
            digest.update(b"\n")
        return {
            "status": "verified",
            "method": "sha256-transferred-files",
            "files": len(rows),
            "bytes": sum(int(row["bytes"]) for row in rows),
            "sha256Manifest": rows,
            "manifestSha256": digest.hexdigest(),
        }

    def _write_receipt(
        self,
        receipt: dict[str, Any],
        nas_root: Path,
        destination_paths: list[str],
    ) -> dict[str, Any]:
        transfer_id = str(receipt["transferId"])
        local_receipt = self.workspace_root / ".agent_control" / "nas_transfers" / f"{transfer_id}.json"
        nas_receipt = nas_root / ".agent_control" / "neyvia_transfers" / "receipts" / f"{transfer_id}.json"
        receipt["localReceiptPath"] = str(local_receipt)
        receipt["nasReceiptPath"] = str(nas_receipt)
        receipt["artifacts"] = [*destination_paths, str(nas_receipt)]
        _atomic_json(nas_receipt, receipt)
        _atomic_json(local_receipt, receipt)
        return receipt

    def send(
        self,
        source: str | Path,
        destination: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        *,
        include_all: bool = False,
    ) -> dict[str, Any]:
        started = time.monotonic()
        started_at = _utc_now()
        preflight_root = self._preflight_authoritative_nas_root()
        source_path = self._validate_source(source)
        _validate_sensitive_source(source_path, include_all=include_all, label="source")
        self._validate_timeout(timeout_seconds)
        nas_root, route = preflight_root or self._resolve_nas_root()
        relative_destination = _safe_relative_destination(destination, source_path.name)
        if _is_syntelos_release_destination(relative_destination):
            raise NasTransferError(
                "direct sends cannot mutate Syntelos release directories; use an immutable batch candidate manifest"
            )
        self._validated_destination_path(nas_root, relative_destination)
        transfer_id = f"nas_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        item = self._transfer_item(
            source_path,
            nas_root,
            relative_destination,
            timeout_seconds=timeout_seconds,
            include_all=include_all,
        )
        receipt: dict[str, Any] = {
            "schema": TRANSFER_SCHEMA,
            "transferId": transfer_id,
            "status": "completed",
            "nasRoot": str(nas_root),
            "route": route,
            "includeAll": include_all,
            **item,
            "startedAt": started_at,
            "durationMs": int((time.monotonic() - started) * 1000),
        }
        return self._write_receipt(receipt, nas_root, [str(item["destination"])])

    def send_manifest(
        self,
        manifest: str | Path,
        *,
        destination_root: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        include_all: bool = False,
    ) -> dict[str, Any]:
        started = time.monotonic()
        started_at = _utc_now()
        preflight_root = self._preflight_authoritative_nas_root()
        self._validate_timeout(timeout_seconds)
        manifest_path = Path(manifest).expanduser().resolve()
        if not manifest_path.is_file():
            raise NasTransferError(f"transfer manifest does not exist: {manifest_path}")
        try:
            manifest_bytes = manifest_path.read_bytes()
            payload = json.loads(manifest_bytes.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NasTransferError(f"transfer manifest is not valid JSON: {manifest_path}") from exc
        if not isinstance(payload, dict):
            raise NasTransferError("transfer manifest must be a JSON object")
        schema = str(payload.get("schema") or MANIFEST_SCHEMA)
        if schema != MANIFEST_SCHEMA:
            raise NasTransferError(f"unsupported transfer manifest schema: {schema}")
        transfer_mode = str(payload.get("transferMode") or "immutable-candidate")
        if transfer_mode != "immutable-candidate":
            raise NasTransferError(f"unsupported transfer manifest mode: {transfer_mode}")
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list) or not raw_entries:
            raise NasTransferError("transfer manifest must contain at least one entry")
        manifest_include_all = payload.get("includeAll", False)
        if not isinstance(manifest_include_all, bool):
            raise NasTransferError("transfer manifest includeAll must be true or false")
        effective_include_all = include_all or manifest_include_all
        requested_root = destination_root or payload.get("destinationRoot")
        if requested_root is not None and not isinstance(requested_root, str):
            raise NasTransferError("transfer manifest destinationRoot must be a string")
        relative_root = _safe_relative_destination(
            requested_root,
            f"batch-{manifest_path.stem}",
        )

        prepared: list[tuple[Path, Path]] = []
        destinations: list[Path] = []
        for index, raw_entry in enumerate(raw_entries):
            if not isinstance(raw_entry, dict):
                raise NasTransferError(f"transfer manifest entry {index} must be an object")
            allow_excluded_root = raw_entry.get("allowExcludedRoot", False)
            if not isinstance(allow_excluded_root, bool):
                raise NasTransferError(
                    f"transfer manifest entry {index} allowExcludedRoot must be true or false"
                )
            raw_source = raw_entry.get("source")
            if not isinstance(raw_source, str) or not raw_source.strip():
                raise NasTransferError(f"transfer manifest entry {index} requires source")
            unresolved_source = Path(raw_source).expanduser()
            if not unresolved_source.is_absolute():
                unresolved_source = manifest_path.parent / unresolved_source
            source_path = self._validate_source(unresolved_source)
            _validate_sensitive_source(
                source_path,
                include_all=effective_include_all,
                label=f"transfer manifest entry {index} source",
                allow_excluded_root=allow_excluded_root,
            )
            raw_destination = raw_entry.get("destination")
            if raw_destination is not None and not isinstance(raw_destination, str):
                raise NasTransferError(f"transfer manifest entry {index} destination must be a string")
            entry_destination = _safe_relative_destination(raw_destination, source_path.name)
            if entry_destination in {
                Path(CANDIDATE_COMPLETION_FILENAME),
                Path(CANDIDATE_INCOMPLETE_FILENAME),
            }:
                raise NasTransferError(
                    f"transfer manifest entry {index} uses a reserved candidate proof path"
                )
            for existing in destinations:
                if (
                    entry_destination == existing
                    or _path_is_relative_to(entry_destination, existing)
                    or _path_is_relative_to(existing, entry_destination)
                ):
                    raise NasTransferError(
                        "transfer manifest destinations must not duplicate or contain one another: "
                        f"{existing.as_posix()} and {entry_destination.as_posix()}"
                    )
            destinations.append(entry_destination)
            prepared.append((source_path, entry_destination))

        nas_root, route = preflight_root or self._resolve_nas_root()
        transfer_id = f"nas_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        final_path = self._validated_destination_path(nas_root, relative_root)
        if _path_lexists(final_path):
            raise NasTransferError(f"candidate destination already exists and will not be replaced: {final_path}")
        staging_name = f".{relative_root.name}.incomplete-{transfer_id}"
        staging_relative = relative_root.parent / staging_name
        staging_path = self._validated_destination_path(nas_root, staging_relative)
        if _path_lexists(staging_path):
            raise NasTransferError(f"candidate staging destination already exists: {staging_path}")
        for _, entry_destination in prepared:
            self._validated_destination_path(nas_root, staging_relative / entry_destination)
            self._validated_destination_path(nas_root, relative_root / entry_destination)

        source_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        nas_receipt_relative = (
            Path(".agent_control") / "neyvia_transfers" / "receipts" / f"{transfer_id}.json"
        )
        incomplete_payload: dict[str, Any] = {
            "schema": CANDIDATE_INCOMPLETE_SCHEMA,
            "status": "incomplete",
            "transferId": transfer_id,
            "destinationRoot": relative_root.as_posix(),
            "stagingRoot": staging_relative.as_posix(),
            "manifest": str(manifest_path),
            "sourceManifestSha256": source_manifest_sha256,
            "startedAt": started_at,
        }
        staging_path.parent.mkdir(parents=True, exist_ok=True)
        staging_path.mkdir(exist_ok=False)
        incomplete_path = staging_path / CANDIDATE_INCOMPLETE_FILENAME
        _atomic_json(incomplete_path, incomplete_payload)

        items: list[dict[str, Any]] = []
        try:
            for source_path, entry_destination in prepared:
                staging_destination = staging_relative / entry_destination
                item = self._transfer_item(
                    source_path,
                    nas_root,
                    staging_destination,
                    timeout_seconds=timeout_seconds,
                    include_all=effective_include_all,
                )
                item["stagingDestination"] = str(item["destination"])
                item["destination"] = str(final_path / entry_destination)
                item["relativeDestination"] = (relative_root / entry_destination).as_posix()
                item["candidateRelativeDestination"] = entry_destination.as_posix()
                items.append(item)

            transferred_verification = _candidate_item_verification(items)
            tree_verification = candidate_tree_verification(staging_path)
            if transferred_verification["sha256Manifest"] != tree_verification["sha256Manifest"]:
                raise NasTransferError(
                    "candidate tree does not exactly match the fully verified transferred-file manifest"
                )
            if transferred_verification["manifestSha256"] != tree_verification["manifestSha256"]:
                raise NasTransferError("candidate tree manifest digest changed after transfer verification")

            completion_payload: dict[str, Any] = {
                "schema": CANDIDATE_COMPLETION_SCHEMA,
                "status": "complete",
                "transferId": transfer_id,
                "destinationRoot": relative_root.as_posix(),
                "manifestSchema": MANIFEST_SCHEMA,
                "transferMode": transfer_mode,
                "manifest": str(manifest_path),
                "sourceManifestSha256": source_manifest_sha256,
                "candidateTreeSha256": tree_verification["manifestSha256"],
                "files": tree_verification["files"],
                "bytes": tree_verification["bytes"],
                "sha256Manifest": tree_verification["sha256Manifest"],
                "nasReceiptRelativePath": nas_receipt_relative.as_posix(),
                "completedAt": _utc_now(),
            }
            completion_path = staging_path / CANDIDATE_COMPLETION_FILENAME
            _atomic_json(completion_path, completion_payload)
            incomplete_path.unlink()
            _atomic_rename_new(staging_path, final_path)

            final_completion_path = final_path / CANDIDATE_COMPLETION_FILENAME
            receipt: dict[str, Any] = {
                "schema": BATCH_TRANSFER_SCHEMA,
                "manifestSchema": MANIFEST_SCHEMA,
                "transferMode": transfer_mode,
                "transferId": transfer_id,
                "status": "completed",
                "candidateStatus": "complete",
                "manifest": str(manifest_path),
                "sourceManifestSha256": source_manifest_sha256,
                "destinationRoot": relative_root.as_posix(),
                "candidateRoot": str(final_path),
                "stagingRoot": str(staging_path),
                "completionProofPath": str(final_completion_path),
                "completionProofSha256": _sha256(final_completion_path),
                "nasRoot": str(nas_root),
                "route": route,
                "kind": "immutable-candidate",
                "includeAll": effective_include_all,
                "items": items,
                "files": int(tree_verification["files"]),
                "bytes": int(tree_verification["bytes"]),
                "transferredFiles": sum(int(item["transferredFiles"]) for item in items),
                "skippedFiles": sum(int(item["skippedFiles"]) for item in items),
                "transferredBytes": sum(int(item["transferredBytes"]) for item in items),
                "resumedFromBytes": sum(int(item["resumedFromBytes"]) for item in items),
                "verification": tree_verification,
                "startedAt": started_at,
                "durationMs": int((time.monotonic() - started) * 1000),
            }
            return self._write_receipt(
                receipt,
                nas_root,
                [str(final_path), str(final_completion_path)],
            )
        except Exception as exc:
            if staging_path.is_dir():
                failure_payload = {
                    **incomplete_payload,
                    "status": "failed",
                    "failedAt": _utc_now(),
                    "completedItems": len(items),
                    "errorType": type(exc).__name__,
                    "error": str(exc),
                }
                try:
                    _atomic_json(incomplete_path, failure_payload)
                except OSError:
                    pass
            raise


from .proofs_d_runtime import checked as _checked
_copy_file_resumable = _checked("d.runtime.transfer.file", _copy_file_resumable)
_copy_directory = _checked("d.runtime.transfer.directory", _copy_directory)
NasTransfer._write_receipt = _checked("d.runtime.transfer.receipt", NasTransfer._write_receipt)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neyvia-transfer",
        description="Copy files, filtered folders, or a manifest to Neyvia's NAS with verification and one receipt.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    send = subparsers.add_parser("send", help="Send a file or folder to the NAS")
    send.add_argument("source", help="Local file or folder")
    send.add_argument("--destination", "-d", help="Relative path under the NAS projects root")
    send.add_argument("--nas-root", help="Explicit mounted/UNC NAS projects root")
    send.add_argument("--workspace", default=str(Path.cwd()), help="Local location for the transfer receipt")
    send.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Folder-copy timeout in seconds")
    send.add_argument(
        "--include-all",
        action="store_true",
        help="Include dependencies, caches, environments, builds, logs, and agent-control data",
    )
    batch = subparsers.add_parser(
        "batch",
        aliases=["manifest"],
        help="Stage and atomically finalize one immutable manifest candidate (alias: manifest)",
    )
    batch.add_argument("manifest", help="JSON manifest containing source/destination entries")
    batch.add_argument("--destination-root", help="Override the manifest destinationRoot")
    batch.add_argument("--nas-root", help="Explicit mounted/UNC NAS projects root")
    batch.add_argument("--workspace", default=str(Path.cwd()), help="Local location for the transfer receipt")
    batch.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Folder-copy timeout in seconds")
    batch.add_argument(
        "--include-all",
        action="store_true",
        help="Include dependencies, caches, builds, logs, agent state, and secret-like files",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "send":
            result = NasTransfer(args.workspace, args.nas_root).send(
                args.source,
                destination=args.destination,
                timeout_seconds=args.timeout,
                include_all=args.include_all,
            )
        elif args.command in {"batch", "manifest"}:
            result = NasTransfer(args.workspace, args.nas_root).send_manifest(
                args.manifest,
                destination_root=args.destination_root,
                timeout_seconds=args.timeout,
                include_all=args.include_all,
            )
        else:
            parser.error(f"unsupported command: {args.command}")
            return 2
    except (NasTransferError, OSError) as exc:
        schema = (
            BATCH_TRANSFER_SCHEMA
            if getattr(args, "command", None) in {"batch", "manifest"}
            else TRANSFER_SCHEMA
        )
        print(json.dumps({"schema": schema, "status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
