"""Resolve a compatible per-user Node.js runtime for optional Neyvia CLIs.

The desktop installer intentionally stays small and does not bundle Node.js.
When an installed CLI raises its minimum Node version, Neyvia keeps that
dependency in its per-user runtime directory so image generation and other
optional capabilities do not require an administrator-level system upgrade.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from .subprocess_utils import hidden_windows_subprocess_kwargs


MANAGED_NODE_VERSION = "24.18.0"
MANAGED_NODE_WINDOWS_ARCHIVE = f"node-v{MANAGED_NODE_VERSION}-win-x64.zip"
MANAGED_NODE_WINDOWS_SHA256 = (
    "0ae68406b42d7725661da979b1403ec9926da205c6770827f33aac9d8f26e821"
)
MANAGED_NODE_WINDOWS_URL = (
    f"https://nodejs.org/dist/v{MANAGED_NODE_VERSION}/{MANAGED_NODE_WINDOWS_ARCHIVE}"
)


def managed_runtime_root() -> Path:
    override = str(os.environ.get("NEYVIA_MANAGED_RUNTIME_ROOT") or "").strip()
    if override:
        return Path(override).expanduser()
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if os.name == "nt" and local_app_data:
        return Path(local_app_data) / "Neyvia" / "runtimes"
    return Path.home() / ".neyvia" / "runtimes"


def _node_executable(directory: Path) -> Path:
    return directory / ("node.exe" if os.name == "nt" else "bin/node")


def _node_version(executable: Path) -> tuple[int, int, int] | None:
    if not executable.is_file():
        return None
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip().lower().lstrip("v")
    try:
        major, minor, patch = value.split(".", 2)
        return int(major), int(minor), int(patch.split("-", 1)[0])
    except (TypeError, ValueError):
        return None


def node_supports_current_openclaw(version: tuple[int, int, int] | None) -> bool:
    if version is None:
        from .proofs_c_runtime import check_node_version
        check_node_version(version, False)
        return False
    result = (
        (version >= (22, 22, 3) and version < (23, 0, 0))
        or (version >= (24, 15, 0) and version < (25, 0, 0))
        or version >= (25, 9, 0)
    )
    from .proofs_c_runtime import check_node_version
    check_node_version(version, result)
    return result


def _existing_compatible_node() -> Path | None:
    explicit = str(os.environ.get("NEYVIA_NODE_BIN") or "").strip()
    candidates: list[Path] = []
    if explicit:
        explicit_path = Path(explicit).expanduser()
        candidates.append(
            explicit_path.parent if explicit_path.is_file() else explicit_path
        )
    candidates.append(
        managed_runtime_root() / f"node-v{MANAGED_NODE_VERSION}-win-x64"
    )
    path_node = shutil.which("node")
    if path_node:
        candidates.append(Path(path_node).parent)

    seen: set[str] = set()
    for directory in candidates:
        key = os.path.normcase(str(directory))
        if key in seen:
            continue
        seen.add(key)
        executable = _node_executable(directory)
        if node_supports_current_openclaw(_node_version(executable)):
            return directory
    return None


def _safe_extract_node_archive(archive_path: Path, destination: Path) -> Path:
    expected_root = f"node-v{MANAGED_NODE_VERSION}-win-x64"
    with zipfile.ZipFile(archive_path) as archive:
        for item in archive.infolist():
            item_path = Path(item.filename)
            if item_path.is_absolute() or ".." in item_path.parts:
                raise RuntimeError("The managed Node.js archive contained an unsafe path.")
        archive.extractall(destination)
    extracted = destination / expected_root
    if not _node_executable(extracted).is_file():
        raise RuntimeError("The managed Node.js archive did not contain node.exe.")
    return extracted


def _download_managed_windows_node() -> Path:
    runtime_root = managed_runtime_root()
    runtime_root.mkdir(parents=True, exist_ok=True)
    final_root = runtime_root / f"node-v{MANAGED_NODE_VERSION}-win-x64"
    if node_supports_current_openclaw(_node_version(_node_executable(final_root))):
        return final_root

    with tempfile.TemporaryDirectory(
        prefix="neyvia-node-install-",
        dir=runtime_root,
    ) as temp_dir:
        temp_root = Path(temp_dir)
        archive_path = temp_root / MANAGED_NODE_WINDOWS_ARCHIVE
        request = Request(
            MANAGED_NODE_WINDOWS_URL,
            headers={"User-Agent": "Neyvia managed runtime installer"},
        )
        digest = hashlib.sha256()
        with urlopen(request, timeout=180) as response, archive_path.open("wb") as output:  # noqa: S310
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest().lower() != MANAGED_NODE_WINDOWS_SHA256:
            raise RuntimeError("The managed Node.js download failed SHA-256 verification.")

        extracted = _safe_extract_node_archive(archive_path, temp_root / "unpacked")
        try:
            extracted.replace(final_root)
        except OSError:
            if not node_supports_current_openclaw(
                _node_version(_node_executable(final_root))
            ):
                raise

    if not node_supports_current_openclaw(_node_version(_node_executable(final_root))):
        raise RuntimeError("The managed Node.js runtime failed its version check.")
    return final_root


def ensure_openclaw_node_bin() -> Path | None:
    existing = _existing_compatible_node()
    if existing is not None:
        return existing
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        return None
    return _download_managed_windows_node()


def prepend_openclaw_node_to_env(env: dict[str, str], *, resolved_bin: Path | None = None) -> dict[str, str]:
    """Prepend a resolved runtime; callers may reuse an already resolved bin."""
    node_bin = resolved_bin if resolved_bin is not None else ensure_openclaw_node_bin()
    if node_bin is None:
        from .proofs_c_runtime import check_node_env
        check_node_env(env, node_bin, env)
        return env
    updated = dict(env)
    existing_path = str(updated.get("PATH") or os.environ.get("PATH") or "")
    updated["PATH"] = os.pathsep.join(
        item for item in (str(node_bin), existing_path) if item
    )
    updated["NEYVIA_MANAGED_NODE_BIN"] = str(node_bin)
    from .proofs_c_runtime import check_node_env
    check_node_env(env, node_bin, updated)
    return updated
