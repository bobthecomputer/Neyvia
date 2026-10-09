"""Crash-aware per-user installer for optional npm-backed agent CLIs.

The installer never changes the operating system PATH. Each package is staged
under Neyvia's per-user runtime, checked against npm's published SHA-512
integrity, then exposed through one atomic launcher in ``runtime/bin``. A failed
install leaves the previous launcher and package untouched.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import weakref
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from .durability import atomic_write_bytes, atomic_write_json, atomic_write_text
from .runtimes import invalidate_runtime_status_cache
from .runtimes.base import neyvia_managed_runtime_root
from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proofs_a_cli import checked, installer_capture, installer_check


INSTALLER_SCHEMA = "neyvia.cli_installer_receipt.v1"
MANIFEST_SCHEMA = "neyvia.managed_cli_manifest.v1"
_SAFE_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,79}$")
_INSTALLER_THREAD_LOCKS = weakref.WeakValueDictionary()
_INSTALLER_THREAD_LOCKS_GUARD = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _entry(runtime_id: str) -> Any:
    from .cli_catalog import CATALOG

    entry = CATALOG.get(str(runtime_id or "").strip())
    if entry is None:
        raise ValueError(f"Unknown optional runtime: {runtime_id}")
    return entry


def _manifest_path(runtime_root: Path, runtime_id: str) -> Path:
    return runtime_root / "manifests" / f"{runtime_id}.json"


def load_manifest(
    runtime_id: str,
    *,
    runtime_root: str | Path | None = None,
) -> dict[str, Any] | None:
    root = Path(runtime_root or neyvia_managed_runtime_root()).resolve()
    path = _manifest_path(root, runtime_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != MANIFEST_SCHEMA:
        return None
    install_dir = Path(str(payload.get("installDir") or "")).resolve()
    try:
        install_dir.relative_to((root / "packages").resolve())
    except ValueError:
        return None
    return payload


def installer_support(entry: Any, *, runtime_id: str = "") -> dict[str, Any]:
    managed = bool(
        runtime_id
        and load_manifest(runtime_id) is not None
    )
    install_available = bool(
        entry is not None
        and entry.package_kind == "npm"
        and entry.package_name
        and entry.command_name
        and shutil.which("npm")
    )
    if entry is None or entry.package_kind != "npm" or not entry.package_name:
        detail = "No verified managed install route is available."
    elif not entry.command_name:
        detail = "The package is known, but its launcher identity is not verified."
    elif not shutil.which("npm"):
        detail = "Node.js/npm is required for this verified install route."
    else:
        detail = "Installs inside Neyvia's per-user runtime without changing system PATH."
    return {
        "kind": "managed_npm" if entry and entry.package_kind == "npm" else None,
        "installAvailable": install_available,
        "managed": managed,
        "detail": detail,
    }


def resolve_npm_release(
    package_name: str,
    *,
    version: str = "latest",
    timeout: float = 10.0,
) -> dict[str, Any]:
    encoded = urllib.parse.quote(str(package_name), safe="@")
    requested = urllib.parse.quote(str(version or "latest"), safe=".-_")
    url = f"https://registry.npmjs.org/{encoded}/{requested}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        raise RuntimeError(f"Could not resolve {package_name} from npm: {exc}") from exc
    resolved_version = str(payload.get("version") or "").strip()
    dist = payload.get("dist") if isinstance(payload.get("dist"), dict) else {}
    integrity = str(dist.get("integrity") or "").strip()
    tarball = str(dist.get("tarball") or "").strip()
    if not _SAFE_VERSION.fullmatch(resolved_version):
        raise RuntimeError("npm returned an invalid package version")
    if not integrity.startswith("sha512-"):
        raise RuntimeError("npm did not publish a SHA-512 integrity value")
    if not tarball.startswith("https://"):
        raise RuntimeError("npm did not publish a secure tarball URL")
    return {
        "package": package_name,
        "version": resolved_version,
        "integrity": integrity,
        "tarball": tarball,
        "downloadBytes": dist.get("size") if isinstance(dist.get("size"), int) else None,
        "unpackedBytes": (
            dist.get("unpackedSize") if isinstance(dist.get("unpackedSize"), int) else None
        ),
        "registry": "https://registry.npmjs.org",
    }


def _launcher_target(install_dir: Path, command_name: str) -> Path:
    suffix = ".cmd" if os.name == "nt" else ""
    return install_dir / "node_modules" / ".bin" / f"{command_name}{suffix}"


def _launcher_path(runtime_root: Path, command_name: str) -> Path:
    suffix = ".cmd" if os.name == "nt" else ""
    return runtime_root / "bin" / f"{command_name}{suffix}"


@contextmanager
def _installer_thread_lock(runtime_root: Path):
    # Queue callers in this process before starting the cross-process lock's
    # acquisition deadline. A valid install can itself take longer than that
    # deadline; competing threads must not time out behind our own owner.
    key = os.path.normcase(str(runtime_root.resolve()))
    with _INSTALLER_THREAD_LOCKS_GUARD:
        lock = _INSTALLER_THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _INSTALLER_THREAD_LOCKS[key] = lock
    with lock:
        yield


@contextmanager
def _installer_file_lock(runtime_root: Path):
    runtime_root.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_root / ".installer.lock"
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())
    deadline = time.monotonic() + 30
    acquired = False
    try:
        while not acquired:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out acquiring optional CLI installer lock: {lock_path}"
                    )
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _installer_locked(function):
    @wraps(function)
    def wrapped(workspace_root, runtime_id, action, *args, **kwargs):
        runtime_root = Path(
            kwargs.get("runtime_root") or neyvia_managed_runtime_root()
        ).resolve()
        kwargs["runtime_root"] = runtime_root
        with _installer_thread_lock(runtime_root), _installer_file_lock(runtime_root):
            capture = installer_capture(runtime_root, runtime_id)
            result = function(workspace_root, runtime_id, action, *args, **kwargs)
            installer_check(runtime_root, runtime_id, action, kwargs, result, capture)
            return result

    return wrapped


def _launcher_collision(
    runtime_root: Path,
    runtime_id: str,
    launcher: Path,
    previous: dict[str, Any] | None,
) -> dict[str, str] | None:
    expected = launcher.resolve()
    manifest_root = runtime_root / "manifests"
    if manifest_root.is_dir():
        for path in sorted(manifest_root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict) or payload.get("schema") != MANIFEST_SCHEMA:
                continue
            owner = str(payload.get("runtimeId") or path.stem).strip()
            if owner == runtime_id:
                continue
            claimed = str(payload.get("launcherPath") or "").strip()
            if claimed and Path(claimed).resolve() == expected:
                return {
                    "kind": "managed_launcher_collision",
                    "ownerRuntimeId": owner,
                    "launcherPath": str(expected),
                }
    if previous:
        claimed = str(previous.get("launcherPath") or "").strip()
        if not claimed or Path(claimed).resolve() != expected:
            return {
                "kind": "managed_launcher_identity_changed",
                "ownerRuntimeId": runtime_id,
                "launcherPath": str(expected),
            }
    elif launcher.exists():
        return {
            "kind": "unmanaged_launcher_collision",
            "ownerRuntimeId": "",
            "launcherPath": str(expected),
        }
    return None


def _launcher_text(target: Path) -> str:
    if os.name == "nt":
        return f'@echo off\r\ncall "{target}" %*\r\n'
    return f"#!/bin/sh\nexec {shlex.quote(str(target))} \"$@\"\n"


def _run(
    command: list[str] | str,
    *,
    cwd: Path,
    timeout: float,
    runner: Callable[..., Any],
) -> Any:
    return runner(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        **hidden_windows_subprocess_kwargs(),
    )


@checked('a-cli.installer.integrity')
def _verified_package_archive(
    npm: str,
    entry: Any,
    release: dict[str, Any],
    *,
    staging: Path,
    workspace: Path,
    runner: Callable[..., Any],
) -> Path:
    pack = _run(
        [
            npm,
            "pack",
            f"{entry.package_name}@{release['version']}",
            "--json",
            "--pack-destination",
            str(staging),
        ],
        cwd=workspace,
        timeout=180,
        runner=runner,
    )
    if int(pack.returncode) != 0:
        raise RuntimeError(
            f"npm pack failed ({pack.returncode}): "
            f"{str(pack.stderr or pack.stdout or '').strip()[:500]}"
        )
    try:
        rows = json.loads(str(pack.stdout or ""))
        filename = str(rows[0]["filename"])
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise RuntimeError("npm pack did not return a valid archive receipt") from exc
    archive = (staging / filename).resolve()
    try:
        archive.relative_to(staging.resolve())
    except ValueError as exc:
        raise RuntimeError("npm pack returned an archive outside the staging directory") from exc
    if not archive.is_file():
        raise RuntimeError("npm pack reported an archive that does not exist")
    hasher = hashlib.sha512()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.digest()
    actual_integrity = "sha512-" + base64.b64encode(digest).decode("ascii")
    if actual_integrity != release["integrity"]:
        raise RuntimeError("Downloaded npm archive failed the published SHA-512 integrity check")
    return archive


def _probe_command(target: Path) -> list[str] | str:
    if os.name == "nt":
        command = os.environ.get("COMSPEC") or "cmd.exe"
        # cmd's /c payload follows shell quoting, not the C argv quoting used
        # by subprocess.list2cmdline on a list's final element. Preserve its
        # outer quote pair so the actual staged launcher is executed.
        return subprocess.list2cmdline([command, "/d", "/s", "/c"]) + f' ""{target}" --version"'
    return [str(target), "--version"]


def _write_receipt(runtime_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    receipt_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}"
    path = runtime_root / "receipts" / f"{receipt_id}.json"
    payload["schema"] = INSTALLER_SCHEMA
    payload["receiptId"] = receipt_id
    payload["receiptPath"] = str(path)
    atomic_write_json(path, payload)
    return payload


def _safe_install_dir(runtime_root: Path, value: object) -> Path | None:
    if not value:
        return None
    candidate = Path(str(value)).resolve()
    try:
        candidate.relative_to((runtime_root / "packages").resolve())
    except ValueError:
        return None
    return candidate


def _remove_owned_path(path: Path, root: Path) -> None:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    if resolved.is_dir():
        shutil.rmtree(resolved)
    elif resolved.exists():
        resolved.unlink()


def _prune_old_installs(
    runtime_root: Path,
    runtime_id: str,
    *,
    keep: set[Path],
) -> None:
    package_root = (runtime_root / "packages" / runtime_id).resolve()
    if not package_root.exists():
        return
    keep_resolved = {item.resolve() for item in keep}
    for item in package_root.iterdir():
        if item.resolve() in keep_resolved:
            continue
        _remove_owned_path(item, package_root)


@_installer_locked
def perform_cli_action(
    workspace_root: str | Path,
    runtime_id: str,
    action: str,
    *,
    version: str = "latest",
    approved: bool = False,
    approval_id: str = "",
    runtime_root: str | Path | None = None,
    npm_path: str | None = None,
    resolver: Callable[..., dict[str, Any]] = resolve_npm_release,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Install, update, repair, or uninstall one Neyvia-managed CLI."""

    root = Path(runtime_root or neyvia_managed_runtime_root()).resolve()
    workspace = Path(workspace_root).resolve()
    operation = str(action or "").strip().lower()
    if operation not in {"install", "update", "repair", "uninstall"}:
        raise ValueError(f"Unsupported CLI installer action: {action}")
    if not approved or not str(approval_id or "").strip():
        return _write_receipt(
            root,
            {
                "ok": False,
                "status": "approval_required",
                "action": operation,
                "runtimeId": runtime_id,
                "generatedAt": _now(),
                "detail": "Optional runtime changes require action-time operator approval.",
            },
        )

    entry = _entry(runtime_id)
    if entry.package_kind != "npm" or not entry.package_name or not entry.command_name:
        return _write_receipt(
            root,
            {
                "ok": False,
                "status": "unsupported",
                "action": operation,
                "runtimeId": runtime_id,
                "generatedAt": _now(),
                "approvalId": approval_id,
                "detail": "This runtime has no verified managed npm route.",
            },
        )

    previous = load_manifest(runtime_id, runtime_root=root)
    launcher = _launcher_path(root, entry.command_name)
    collision = _launcher_collision(root, runtime_id, launcher, previous)
    if collision:
        return _write_receipt(
            root,
            {
                "ok": False,
                "status": "launcher_conflict",
                "action": operation,
                "runtimeId": runtime_id,
                "generatedAt": _now(),
                "approvalId": approval_id,
                "detail": (
                    "Neyvia did not change this runtime because its managed launcher "
                    "path is already owned or has changed identity."
                ),
                "collision": collision,
                "systemPathChanged": False,
            },
        )
    if operation == "uninstall":
        removed: list[str] = []
        if previous:
            owned_launcher = Path(str(previous.get("launcherPath") or "")).resolve()
            if owned_launcher == launcher.resolve() and launcher.exists():
                _remove_owned_path(launcher, (root / "bin").resolve())
                removed.append(str(launcher))
            package_root = root / "packages" / runtime_id
            if package_root.exists():
                _remove_owned_path(package_root, (root / "packages").resolve())
                removed.append(str(package_root))
            manifest_path = _manifest_path(root, runtime_id)
            if manifest_path.exists():
                _remove_owned_path(manifest_path, (root / "manifests").resolve())
                removed.append(str(manifest_path))
        invalidate_runtime_status_cache(workspace)
        return _write_receipt(
            root,
            {
                "ok": True,
                "status": "uninstalled" if removed else "already_absent",
                "action": operation,
                "runtimeId": runtime_id,
                "generatedAt": _now(),
                "approvalId": approval_id,
                "removed": removed,
                "systemPathChanged": False,
            },
        )

    npm = npm_path or shutil.which("npm")
    if not npm:
        return _write_receipt(
            root,
            {
                "ok": False,
                "status": "prerequisite_missing",
                "action": operation,
                "runtimeId": runtime_id,
                "generatedAt": _now(),
                "approvalId": approval_id,
                "detail": "Node.js/npm is not available.",
            },
        )

    requested = version
    if operation == "repair" and previous and previous.get("version"):
        requested = str(previous["version"])
    release = resolver(entry.package_name, version=requested)
    integrity_key = hashlib.sha256(release["integrity"].encode("utf-8")).hexdigest()[:12]
    install_id = f"{release['version']}-{integrity_key}-{uuid.uuid4().hex[:8]}"
    staging = root / "packages" / runtime_id / f".{install_id}.staging"
    final_dir = root / "packages" / runtime_id / install_id
    staging.mkdir(parents=True, exist_ok=False)
    manifest_path = _manifest_path(root, runtime_id)
    previous_launcher_bytes = (
        launcher.read_bytes()
        if launcher.is_file()
        else None
    )
    promotion_started = False
    try:
        archive = _verified_package_archive(
            str(npm),
            entry,
            release,
            staging=staging,
            workspace=workspace,
            runner=runner,
        )
        command = [
            str(npm),
            "install",
            "--prefix",
            str(staging),
            "--omit=dev",
            "--no-audit",
            "--no-fund",
            str(archive),
        ]
        completed = _run(command, cwd=workspace, timeout=300, runner=runner)
        if int(completed.returncode) != 0:
            raise RuntimeError(
                f"npm install failed ({completed.returncode}): "
                f"{str(completed.stderr or completed.stdout or '').strip()[:500]}"
            )
        target = _launcher_target(staging, entry.command_name)
        if not target.is_file():
            raise RuntimeError(
                f"Installed package did not expose the verified {entry.command_name} launcher."
            )
        probe = _run(_probe_command(target), cwd=workspace, timeout=20, runner=runner)
        if int(probe.returncode) != 0:
            raise RuntimeError(
                f"Installed launcher failed its version probe ({probe.returncode})."
            )
        os.replace(staging, final_dir)
        final_target = _launcher_target(final_dir, entry.command_name)
        previous_dir = _safe_install_dir(root, (previous or {}).get("installDir"))
        promoting = {
            "schema": MANIFEST_SCHEMA,
            "state": "promoting",
            "runtimeId": runtime_id,
            "package": entry.package_name,
            "commandName": entry.command_name,
            "version": release["version"],
            "integrity": release["integrity"],
            "installDir": str(final_dir),
            "launcherPath": str(launcher),
            "previousInstallDir": str(previous_dir) if previous_dir else None,
            "updatedAt": _now(),
        }
        promotion_started = True
        atomic_write_json(manifest_path, promoting)
        atomic_write_text(launcher, _launcher_text(final_target))
        if os.name != "nt":
            launcher.chmod(0o755)
        manifest = {**promoting, "state": "active"}
        atomic_write_json(manifest_path, manifest)
        keep = {final_dir}
        if previous_dir and previous_dir.exists():
            keep.add(previous_dir)
        _prune_old_installs(root, runtime_id, keep=keep)
        invalidate_runtime_status_cache(workspace)
        return _write_receipt(
            root,
            {
                "ok": True,
                "status": "completed",
                "action": operation,
                "runtimeId": runtime_id,
                "generatedAt": _now(),
                "approvalId": approval_id,
                "version": release["version"],
                "integrity": release["integrity"],
                "integrityAlgorithm": "sha512",
                "registry": release["registry"],
                "downloadBytes": release.get("downloadBytes"),
                "unpackedBytes": release.get("unpackedBytes"),
                "launcherPath": str(launcher),
                "systemPathChanged": False,
                "previousInstallRetained": bool(previous_dir and previous_dir.exists()),
                "probeOutput": str(probe.stdout or probe.stderr or "").strip()[:200],
            },
        )
    except Exception as exc:
        rollback_error = ""
        if promotion_started:
            try:
                if previous_launcher_bytes is None:
                    if launcher.exists():
                        _remove_owned_path(launcher, (root / "bin").resolve())
                else:
                    atomic_write_bytes(launcher, previous_launcher_bytes)
                    if os.name != "nt":
                        launcher.chmod(0o755)
                if previous:
                    atomic_write_json(manifest_path, previous)
                elif manifest_path.exists():
                    _remove_owned_path(manifest_path, (root / "manifests").resolve())
                if final_dir.exists():
                    _remove_owned_path(
                        final_dir,
                        (root / "packages" / runtime_id).resolve(),
                    )
            except Exception as rollback_exc:
                rollback_error = f" Rollback also failed: {rollback_exc}"
        if staging.exists():
            _remove_owned_path(staging, (root / "packages" / runtime_id).resolve())
        return _write_receipt(
            root,
            {
                "ok": False,
                "status": "failed",
                "action": operation,
                "runtimeId": runtime_id,
                "generatedAt": _now(),
                "approvalId": approval_id,
                "detail": f"{exc}{rollback_error}",
                "previousInstallPreserved": bool(previous),
                "systemPathChanged": False,
            },
        )


def installer_status(
    runtime_id: str,
    *,
    runtime_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(runtime_root or neyvia_managed_runtime_root()).resolve()
    entry = _entry(runtime_id)
    manifest = load_manifest(runtime_id, runtime_root=root)
    launcher = _launcher_path(root, entry.command_name) if entry.command_name else None
    ready = bool(
        manifest
        and manifest.get("state") == "active"
        and launcher
        and launcher.is_file()
    )
    return {
        "schema": "neyvia.cli_installer_status.v1",
        "runtimeId": runtime_id,
        "managed": manifest is not None,
        "ready": ready,
        "repairRequired": bool(manifest and not ready),
        "version": (manifest or {}).get("version"),
        "launcherPath": str(launcher) if launcher else None,
        "runtimeRoot": str(root),
        "systemPathChanged": False,
    }
