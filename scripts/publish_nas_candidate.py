from __future__ import annotations

import argparse
import errno
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any


# This publisher is allowed to run from inside the immutable candidate it is
# validating.  Import caches created under that candidate would otherwise
# change the sealed tree before its digest is checked.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.nas_transfer import (  # noqa: E402
    BATCH_TRANSFER_SCHEMA,
    CANDIDATE_COMPLETION_FILENAME,
    CANDIDATE_COMPLETION_SCHEMA,
    candidate_tree_verification,
)


PUBLISH_SCHEMA = "neyvia.nas_publish.v1"
PUBLISH_LOCK_SCHEMA = "neyvia.nas_publish.lock.v1"
DEFAULT_BASE = Path("/volume1/Saclay/projects/syntelos")
DEFAULT_CONTROL_ROOT = Path("/volume1/Saclay/projects/vibe-coding-platform")
DEFAULT_PORT = 47880
DEFAULT_SERVICE_TIMEOUT_SECONDS = 3600
DEFAULT_LAUNCHER_SHUTDOWN_TIMEOUT_SECONDS = 3000
LAUNCHER_WAIT_POLL_SECONDS = 60


class PublishError(RuntimeError):
    pass


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    import hashlib

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


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"{label} is unavailable or invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise PublishError(f"{label} must be a JSON object: {path}")
    return payload


def _process_start_ticks(pid: int) -> str | None:
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
    except OSError:
        return None
    try:
        fields = raw.rsplit(")", 1)[1].split()
        return fields[19]
    except (IndexError, ValueError):
        return None


def _boot_id() -> str | None:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return None
    return value or None


def _lock_owner_description(path: Path) -> str:
    try:
        owner = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return "kernel lock is held but owner metadata is unavailable"
    if not isinstance(owner, dict) or owner.get("schema") != PUBLISH_LOCK_SCHEMA:
        return "kernel lock is held but owner metadata is untrusted"
    try:
        pid = int(owner.get("pid"))
    except (TypeError, ValueError):
        return "kernel lock is held but owner metadata is untrusted"
    trusted = (
        owner.get("state") == "held"
        and owner.get("bootId")
        and owner.get("bootId") == _boot_id()
        and owner.get("processStartTicks")
        and owner.get("processStartTicks") == _process_start_ticks(pid)
        and _pid_alive(pid)
    )
    if not trusted:
        return "kernel lock is held but owner metadata is stale or untrusted"
    return (
        f"trusted owner PID {pid} on {owner.get('host') or 'unknown-host'}, "
        f"candidate={owner.get('candidate') or 'unknown'}, acquiredAt={owner.get('acquiredAt') or 'unknown'}"
    )


def _lock_file(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_lock_owner(handle: Any, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    handle.seek(0)
    handle.truncate(0)
    handle.write(encoded)
    handle.flush()
    os.fsync(handle.fileno())


class _PublisherLock:
    def __init__(self, base: Path, candidate: str | Path) -> None:
        self.path = base / ".agent_control" / "neyvia_publish" / "publisher.lock"
        self.candidate = str(candidate)
        self.handle: Any | None = None
        self.owner: dict[str, Any] | None = None

    def __enter__(self) -> "_PublisherLock":
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        open_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        if os.name != "nt":
            open_flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, open_flags, 0o600)
        except OSError as exc:
            raise PublishError(f"cannot open persistent publisher lock {self.path}: {exc}") from exc
        descriptor_info = os.fstat(descriptor)
        try:
            path_info = os.stat(self.path, follow_symlinks=False)
        except OSError as exc:
            os.close(descriptor)
            raise PublishError(f"publisher lock path changed while opening: {self.path}") from exc
        if (
            not stat.S_ISREG(descriptor_info.st_mode)
            or descriptor_info.st_nlink != 1
            or (descriptor_info.st_dev, descriptor_info.st_ino)
            != (path_info.st_dev, path_info.st_ino)
        ):
            os.close(descriptor)
            raise PublishError(f"publisher lock must be one stable regular file: {self.path}")
        handle = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            _lock_file(handle)
        except OSError as exc:
            handle.close()
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(
                exc, "winerror", None
            ) in {32, 33, 36}:
                raise PublishError(
                    f"another NAS publication owns {self.path}; {_lock_owner_description(self.path)}"
                ) from exc
            raise PublishError(f"cannot acquire persistent publisher lock {self.path}: {exc}") from exc
        owner = {
            "schema": PUBLISH_LOCK_SCHEMA,
            "state": "held",
            "ownerToken": uuid.uuid4().hex,
            "pid": os.getpid(),
            "processStartTicks": _process_start_ticks(os.getpid()),
            "bootId": _boot_id(),
            "host": socket.gethostname(),
            "candidate": self.candidate,
            "acquiredAt": _utc_now(),
        }
        try:
            _write_lock_owner(handle, owner)
        except OSError as exc:
            try:
                _unlock_file(handle)
            finally:
                handle.close()
            raise PublishError(f"cannot persist publisher lock ownership at {self.path}: {exc}") from exc
        self.handle = handle
        self.owner = owner
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        handle = self.handle
        if handle is None:
            return
        if self.owner is not None:
            released = {**self.owner, "state": "released", "releasedAt": _utc_now()}
            try:
                _write_lock_owner(handle, released)
            except OSError:
                pass
        try:
            _unlock_file(handle)
        finally:
            handle.close()
            self.handle = None


def _positive_environment_timeout(environment: dict[str, str], name: str, default: int) -> int:
    raw = str(environment.get(name) or default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise PublishError(f"{name} must be a positive integer: {raw}") from exc
    if value < 1:
        raise PublishError(f"{name} must be a positive integer: {raw}")
    return value


def _minimum_launcher_timeouts(environment: dict[str, str]) -> tuple[int, int]:
    service_stop = _positive_environment_timeout(
        environment, "FLUXIO_SERVICE_STOP_TIMEOUT_SECONDS", 30
    )
    backend_stop = _positive_environment_timeout(
        environment, "FLUXIO_BACKEND_STOP_TIMEOUT_SECONDS", 15
    )
    backend_start = _positive_environment_timeout(
        environment, "FLUXIO_BACKEND_START_TIMEOUT_SECONDS", 45
    )
    gateway_start = _positive_environment_timeout(
        environment, "FLUXIO_OPENCLAW_GATEWAY_START_TIMEOUT_SECONDS", 45
    )
    gateway_health = _positive_environment_timeout(
        environment, "FLUXIO_OPENCLAW_HEALTH_TIMEOUT_SECONDS", 45
    )
    worker_drain = _positive_environment_timeout(
        environment, "FLUXIO_WORKER_DRAIN_TIMEOUT_SECONDS", 300
    )
    worker_start = _positive_environment_timeout(
        environment, "FLUXIO_WORKER_START_TIMEOUT_SECONDS", 45
    )
    watchdog_start = _positive_environment_timeout(
        environment, "FLUXIO_WATCHDOG_START_TIMEOUT_SECONDS", 300
    )
    service_cohort_stop = 3 * (service_stop + 1)
    backend_cycle = backend_stop + 2 + backend_start * 6
    cohort_start = gateway_start * (gateway_health + 1) + worker_start + watchdog_start
    activation_estimate = (
        300 + worker_drain + service_cohort_stop + backend_cycle + cohort_start + 30
    )
    rollback_estimate = 60 + service_cohort_stop + backend_cycle + cohort_start + 30
    return (
        max(DEFAULT_SERVICE_TIMEOUT_SECONDS, activation_estimate),
        max(DEFAULT_LAUNCHER_SHUTDOWN_TIMEOUT_SECONDS, rollback_estimate),
    )


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text.casefold())


def _resolve_candidate(base: Path, candidate_value: str | Path) -> tuple[Path, Path]:
    base = base.expanduser().resolve(strict=True)
    releases = (base / "releases").resolve(strict=True)
    raw = Path(candidate_value).expanduser()
    if raw.is_absolute():
        candidate = raw
    elif raw.parts and raw.parts[0].casefold() == "releases":
        candidate = base / raw
    else:
        candidate = releases / raw
    if candidate.is_symlink():
        raise PublishError(f"candidate release cannot be a symlink: {candidate}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise PublishError(f"candidate release is unavailable: {candidate}") from exc
    if not resolved.is_dir() or resolved.parent != releases:
        raise PublishError(f"candidate must be one direct directory beneath {releases}: {resolved}")
    if resolved.name.startswith(".") or ".incomplete-" in resolved.name:
        raise PublishError(f"incomplete/staging release names cannot be published: {resolved.name}")
    return base, resolved


def _validate_candidate(
    base: Path,
    candidate_value: str | Path,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    if not _is_sha256(expected_manifest_sha256):
        raise PublishError("--expected-manifest-sha256 must be one complete SHA-256 digest")
    base, candidate = _resolve_candidate(base, candidate_value)
    expected_destination = PurePosixPath(base.name) / "releases" / candidate.name
    completion_path = candidate / CANDIDATE_COMPLETION_FILENAME
    proof = _read_json(completion_path, label="candidate completion proof")
    if proof.get("schema") != CANDIDATE_COMPLETION_SCHEMA or proof.get("status") != "complete":
        raise PublishError(f"candidate completion proof is not complete: {completion_path}")
    if str(proof.get("destinationRoot") or "") != expected_destination.as_posix():
        raise PublishError(
            "candidate completion proof destination does not match the selected release: "
            f"{proof.get('destinationRoot')}"
        )
    source_manifest_sha256 = str(proof.get("sourceManifestSha256") or "").casefold()
    if source_manifest_sha256 != expected_manifest_sha256.casefold():
        raise PublishError(
            "candidate source-manifest digest does not match --expected-manifest-sha256"
        )
    transfer_id = str(proof.get("transferId") or "").strip()
    if not transfer_id:
        raise PublishError("candidate completion proof has no transferId")

    tree = candidate_tree_verification(candidate)
    if tree["manifestSha256"] != proof.get("candidateTreeSha256"):
        raise PublishError("candidate tree digest does not match its completion proof")
    if tree["sha256Manifest"] != proof.get("sha256Manifest"):
        raise PublishError("candidate file manifest does not match its completion proof")
    if int(tree["files"]) != int(proof.get("files") or -1) or int(tree["bytes"]) != int(
        proof.get("bytes") or -1
    ):
        raise PublishError("candidate file totals do not match its completion proof")

    expected_receipt_relative = (
        PurePosixPath(".agent_control") / "neyvia_transfers" / "receipts" / f"{transfer_id}.json"
    )
    if str(proof.get("nasReceiptRelativePath") or "") != expected_receipt_relative.as_posix():
        raise PublishError("candidate completion proof points at an unexpected transfer receipt")
    projects_root = base.parent.resolve(strict=True)
    receipt_path = projects_root.joinpath(*expected_receipt_relative.parts)
    receipt = _read_json(receipt_path, label="NAS transfer receipt")
    if receipt.get("schema") != BATCH_TRANSFER_SCHEMA or receipt.get("status") != "completed":
        raise PublishError(f"NAS transfer receipt is not completed: {receipt_path}")
    expected_receipt_values = {
        "transferId": transfer_id,
        "destinationRoot": expected_destination.as_posix(),
        "sourceManifestSha256": source_manifest_sha256,
        "candidateStatus": "complete",
    }
    for key, expected in expected_receipt_values.items():
        if receipt.get(key) != expected:
            raise PublishError(f"NAS transfer receipt {key} does not match the candidate proof")
    verification = receipt.get("verification") or {}
    if verification.get("manifestSha256") != tree["manifestSha256"]:
        raise PublishError("NAS transfer receipt tree digest does not match the candidate")
    if receipt.get("completionProofSha256") != _sha256(completion_path):
        raise PublishError("NAS transfer receipt does not authenticate the current completion proof")

    launcher = candidate / "scripts" / "start_fluxio_services.sh"
    backend_launcher = candidate / "scripts" / "start_fluxio_backend.sh"
    if not launcher.is_file() or not backend_launcher.is_file():
        raise PublishError("candidate is missing the transactional service launchers")
    return {
        "base": base,
        "candidate": candidate,
        "completionPath": completion_path,
        "completion": proof,
        "receiptPath": receipt_path,
        "receipt": receipt,
        "tree": tree,
        "launcher": launcher,
        "backendLauncher": backend_launcher,
    }


def _current_release(base: Path) -> tuple[Path, str, Path]:
    current = base / "current"
    if not current.is_symlink():
        raise PublishError(f"current must be a symlink before atomic publication: {current}")
    old_link = os.readlink(current)
    try:
        old_release = current.resolve(strict=True)
    except OSError as exc:
        raise PublishError(f"current release symlink is broken: {current}") from exc
    releases = (base / "releases").resolve(strict=True)
    if not old_release.is_dir() or old_release.parent != releases:
        raise PublishError(f"current resolves outside the immutable releases directory: {old_release}")
    return current, old_link, old_release


def _pid_alive(pid: int) -> bool:
    if pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_cmdline(pid: int) -> list[str]:
    path = Path("/proc") / str(pid) / "cmdline"
    try:
        return [
            item.decode("utf-8", errors="surrogateescape")
            for item in path.read_bytes().split(b"\0")
            if item
        ]
    except OSError as exc:
        raise PublishError(f"cannot inspect backend PID {pid}: {path}") from exc


def _read_process_cwd(pid: int) -> Path:
    path = Path("/proc") / str(pid) / "cwd"
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise PublishError(f"cannot inspect backend PID {pid} working directory: {path}") from exc


def _argument_value(arguments: list[str], flag: str) -> str | None:
    for index, argument in enumerate(arguments):
        if argument == flag and index + 1 < len(arguments):
            return arguments[index + 1]
        prefix = f"{flag}="
        if argument.startswith(prefix):
            return argument[len(prefix) :]
    return None


def _same_path(value: str | None, expected: Path, *, relative_to: Path | None = None) -> bool:
    if not value:
        return False
    try:
        path = Path(value)
        if not path.is_absolute() and relative_to is not None:
            path = relative_to / path
        return path.resolve(strict=True) == expected.resolve(strict=True)
    except OSError:
        return False


def _redacted_command(arguments: list[str]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    sensitive = {"--password", "--token", "--api-key", "--secret"}
    for argument in arguments:
        if hide_next:
            redacted.append("[redacted]")
            hide_next = False
            continue
        folded = argument.casefold()
        if folded in sensitive:
            redacted.append(argument)
            hide_next = True
            continue
        if any(folded.startswith(f"{flag}=") for flag in sensitive):
            redacted.append(f"{argument.split('=', 1)[0]}=[redacted]")
            continue
        redacted.append(argument)
    return redacted


def _managed_python_for_release(base: Path, release: Path) -> Path:
    if (release / "scripts" / "resolve_release_python.py").is_file():
        from resolve_release_python import resolve
        try:
            return resolve(base, release)
        except (OSError, RuntimeError) as error:
            raise PublishError("Release dependency environment is not ready") from error
    return base / ".venv" / "bin" / "python"


def _validate_backend_command(
    arguments: list[str],
    *,
    base: Path,
    release: Path,
    control_root: Path,
    port: int,
    legacy: bool,
    process_cwd: Path,
) -> dict[str, Any]:
    if not arguments:
        raise PublishError("backend process has an empty command line")
    expected_python = _managed_python_for_release(base, release)
    # Do not resolve the executable symlink: two virtual environments can share
    # the same base binary while loading different dependencies.
    if os.path.abspath(arguments[0]) != os.path.abspath(expected_python):
        raise PublishError("backend PID does not use this release's managed Python environment")
    if process_cwd.resolve(strict=True) != release.resolve(strict=True):
        raise PublishError("backend PID working directory does not match the currently linked release")
    expected_runner = release / "scripts" / "run_web_backend.py"
    if not any(
        _same_path(argument, expected_runner, relative_to=process_cwd) for argument in arguments[1:]
    ):
        raise PublishError("backend PID runner does not belong to the currently linked release")
    if _argument_value(arguments, "--port") != str(port):
        raise PublishError(f"backend PID does not declare expected port {port}")
    root_value = _argument_value(arguments, "--root")
    expected_root = release if legacy else control_root
    if not _same_path(root_value, expected_root):
        expected_label = "legacy release root" if legacy else "persistent control root"
        raise PublishError(f"backend PID does not use the expected {expected_label}")
    if not _same_path(_argument_value(arguments, "--static-root"), release / "web" / "dist"):
        raise PublishError("backend PID static root does not belong to the currently linked release")
    host = str(_argument_value(arguments, "--host") or "")
    if host not in {"0.0.0.0", "127.0.0.1", "::"}:
        raise PublishError(f"backend PID has an unexpected bind host: {host or 'missing'}")
    cert = _argument_value(arguments, "--tls-cert-file")
    key = _argument_value(arguments, "--tls-key-file")
    cert_root = (base / "certs").resolve(strict=True)
    try:
        cert_path = Path(str(cert or "")).resolve(strict=True)
        key_path = Path(str(key or "")).resolve(strict=True)
    except OSError as exc:
        raise PublishError("backend PID TLS certificate paths are unavailable") from exc
    if cert_path.parent != cert_root or cert_path.suffix.casefold() not in {".crt", ".pem"}:
        raise PublishError("backend PID TLS certificate is outside the managed certificate directory")
    if key_path.parent != cert_root or key_path.suffix.casefold() not in {".key", ".pem"}:
        raise PublishError("backend PID TLS key is outside the managed certificate directory")
    if legacy and "--allow-port-reuse" not in arguments:
        raise PublishError("explicit legacy migration requires the verified --allow-port-reuse process shape")
    if not legacy and "--allow-port-reuse" in arguments:
        raise PublishError("managed backend unexpectedly uses legacy --allow-port-reuse")
    return {
        "pid": None,
        "release": str(release),
        "root": str(expected_root),
        "port": port,
        "runner": str(expected_runner),
        "staticRoot": str(release / "web" / "dist"),
        "tlsCertFile": str(cert_path),
        "tlsKeyFile": str(key_path),
        "legacy": legacy,
        "workingDirectory": str(process_cwd),
        "command": _redacted_command(arguments),
    }


def _listener_reachable(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _pid_listens_on_port(pid: int, port: int) -> bool:
    inodes: set[str] = set()
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            lines = table.read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "0A":
                continue
            try:
                local_port = int(fields[1].rsplit(":", 1)[1], 16)
            except (IndexError, ValueError):
                continue
            if local_port == port:
                inodes.add(fields[9])
    if not inodes:
        return False
    fd_root = Path("/proc") / str(pid) / "fd"
    try:
        descriptors = list(fd_root.iterdir())
    except OSError:
        return False
    for descriptor in descriptors:
        try:
            target = os.readlink(descriptor)
        except OSError:
            continue
        if target.startswith("socket:[") and target[8:-1] in inodes:
            return True
    return False


def _service_preflight(
    *,
    base: Path,
    old_release: Path,
    control_root: Path,
    port: int,
    legacy_backend_pid: int | None,
) -> dict[str, Any]:
    pid_file = control_root / ".agent_control" / f"web_backend_{port}.pid"
    listening = _listener_reachable(port)
    if pid_file.exists():
        if legacy_backend_pid is not None:
            raise PublishError("--legacy-backend-pid cannot be used while a managed backend PID file exists")
        raw_pid = pid_file.read_text(encoding="utf-8").strip()
        if not raw_pid.isdigit():
            raise PublishError(f"managed backend PID file is invalid: {pid_file}")
        pid = int(raw_pid)
        if not listening or not _pid_alive(pid):
            raise PublishError(f"managed backend PID file is stale; repair it before publishing: {pid_file}")
        if not _pid_listens_on_port(pid, port):
            raise PublishError(f"managed backend PID {pid} does not own listening port {port}")
        snapshot = _validate_backend_command(
            _read_cmdline(pid),
            base=base,
            release=old_release,
            control_root=control_root,
            port=port,
            legacy=False,
            process_cwd=_read_process_cwd(pid),
        )
        snapshot["pid"] = pid
        return {"status": "managed", "pid": pid, "pidFile": str(pid_file), "snapshot": snapshot}

    if not listening:
        if legacy_backend_pid is not None:
            raise PublishError(f"--legacy-backend-pid was supplied but port {port} is not listening")
        return {"status": "stopped", "pid": None, "pidFile": str(pid_file), "snapshot": None}
    if legacy_backend_pid is None:
        raise PublishError(
            f"port {port} is listening without the owned PID file {pid_file}; refusing automatic takeover. "
            "After independently verifying the legacy process, rerun once with --legacy-backend-pid PID."
        )
    legacy_pid_file = old_release / ".agent_control" / f"web_backend_{port}.pid"
    if not legacy_pid_file.is_file():
        raise PublishError(
            f"legacy backend PID cannot be bound to the current release because its historical PID file is missing: "
            f"{legacy_pid_file}"
        )
    legacy_pid_text = legacy_pid_file.read_text(encoding="utf-8").strip()
    if not legacy_pid_text.isdigit() or int(legacy_pid_text) != legacy_backend_pid:
        raise PublishError(
            f"--legacy-backend-pid does not match the current release's historical PID file: {legacy_pid_file}"
        )
    if not _pid_alive(legacy_backend_pid) or not _pid_listens_on_port(legacy_backend_pid, port):
        raise PublishError(f"legacy backend PID {legacy_backend_pid} does not own listening port {port}")
    snapshot = _validate_backend_command(
        _read_cmdline(legacy_backend_pid),
        base=base,
        release=old_release,
        control_root=control_root,
        port=port,
        legacy=True,
        process_cwd=_read_process_cwd(legacy_backend_pid),
    )
    snapshot["pid"] = legacy_backend_pid
    return {
        "status": "legacy-verified",
        "pid": legacy_backend_pid,
        "pidFile": str(pid_file),
        "legacyPidFile": str(legacy_pid_file),
        "snapshot": snapshot,
    }


def _stop_legacy_backend(pid: int, timeout_seconds: int) -> None:
    if not _pid_alive(pid):
        raise PublishError(f"verified legacy backend PID exited before migration: {pid}")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    raise PublishError(
        f"legacy backend PID {pid} did not stop within {timeout_seconds}s; current was not switched"
    )


def _prepare_symlink(current: Path, target: str, purpose: str) -> Path:
    temporary = current.parent / f".{current.name}.{purpose}-{uuid.uuid4().hex}"
    os.symlink(target, temporary, target_is_directory=True)
    return temporary


def _replace_current_link(prepared_link: Path, current: Path) -> None:
    if os.name == "nt":
        raise PublishError("NAS publication must run on the POSIX NAS host, not a Windows SMB client")
    os.replace(prepared_link, current)


def _stop_launcher_and_wait(
    process: subprocess.Popen[str],
    *,
    shutdown_timeout_seconds: int,
) -> tuple[str, str, bool, str | None]:
    signal_error: str | None = None
    try:
        process.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as exc:
        signal_error = str(exc)

    graceful_window_exceeded = False
    wait_timeout = shutdown_timeout_seconds
    while True:
        try:
            stdout, stderr = process.communicate(timeout=wait_timeout)
            return stdout or "", stderr or "", graceful_window_exceeded, signal_error
        except subprocess.TimeoutExpired:
            graceful_window_exceeded = True
            wait_timeout = LAUNCHER_WAIT_POLL_SECONDS


def _run_services(
    *,
    candidate: Path,
    target_release: Path,
    base: Path,
    control_root: Path,
    timeout_seconds: int,
    shutdown_timeout_seconds: int,
) -> dict[str, Any]:
    launcher = candidate / "scripts" / "start_fluxio_services.sh"
    backend_launcher = candidate / "scripts" / "start_fluxio_backend.sh"
    env = dict(os.environ)
    env.update(
        {
            "SYNTHELOS_BASE": str(base),
            "SYNTHELOS_ROOT": str(target_release),
            "FLUXIO_CONTROL_PROJECT_ROOT": str(control_root),
            "FLUXIO_BACKEND_LAUNCHER": str(backend_launcher),
        }
    )
    process = subprocess.Popen(
        ["bash", str(launcher)],
        cwd=str(target_release),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    timed_out = False
    interrupted = False
    graceful_window_exceeded = False
    signal_error: str | None = None
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        stdout, stderr, graceful_window_exceeded, signal_error = _stop_launcher_and_wait(
            process,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )
    except KeyboardInterrupt:
        interrupted = True
        stdout, stderr, graceful_window_exceeded, signal_error = _stop_launcher_and_wait(
            process,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )
    result = {
        "launcherPid": process.pid,
        "returnCode": process.returncode,
        "stdoutTail": stdout[-2000:],
        "stderrTail": stderr[-2000:],
        "timedOut": timed_out,
        "interrupted": interrupted,
        "gracefulShutdownWindowExceeded": graceful_window_exceeded,
    }
    if timed_out or interrupted:
        reason = (
            f"service launch exceeded {timeout_seconds}s"
            if timed_out
            else "service launch was interrupted"
        )
        signal_detail = f"; SIGTERM delivery failed: {signal_error}" if signal_error else ""
        wait_detail = (
            f"; EXIT handling exceeded {shutdown_timeout_seconds}s but publisher waited until launcher exit"
            if graceful_window_exceeded
            else "; launcher EXIT handling completed before publisher rollback"
        )
        raise PublishError(
            f"{reason} for {target_release}; launcher PID {process.pid} exited with "
            f"{process.returncode}{signal_detail}{wait_detail}: "
            f"{result['stderrTail'] or result['stdoutTail']}"
        )
    if process.returncode != 0:
        raise PublishError(
            f"service launch failed for {target_release} with exit {process.returncode}: "
            f"{result['stderrTail'] or result['stdoutTail']}"
        )
    return result


def _verify_managed_backend(
    *,
    base: Path,
    release: Path,
    control_root: Path,
    port: int,
) -> dict[str, Any]:
    pid_file = control_root / ".agent_control" / f"web_backend_{port}.pid"
    if not _listener_reachable(port) or not pid_file.is_file():
        raise PublishError(f"transactional launcher did not establish an owned backend on port {port}")
    raw_pid = pid_file.read_text(encoding="utf-8").strip()
    if not raw_pid.isdigit():
        raise PublishError(f"transactional launcher wrote an invalid backend PID: {pid_file}")
    pid = int(raw_pid)
    if not _pid_alive(pid) or not _pid_listens_on_port(pid, port):
        raise PublishError(f"transactional backend PID {pid} does not own port {port}")
    snapshot = _validate_backend_command(
        _read_cmdline(pid),
        base=base,
        release=release,
        control_root=control_root,
        port=port,
        legacy=False,
        process_cwd=_read_process_cwd(pid),
    )
    snapshot["pid"] = pid
    return snapshot


def _publish_candidate_locked(
    *,
    base: str | Path,
    candidate: str | Path,
    expected_manifest_sha256: str,
    control_root: str | Path,
    port: int,
    service_timeout_seconds: int,
    launcher_shutdown_timeout_seconds: int,
    legacy_backend_pid: int | None,
    legacy_stop_timeout_seconds: int,
    publisher_lock: _PublisherLock,
) -> dict[str, Any]:
    validated = _validate_candidate(Path(base), candidate, expected_manifest_sha256)
    base_path = Path(validated["base"])
    candidate_path = Path(validated["candidate"])
    control_path = Path(control_root).expanduser().resolve(strict=True)
    current, old_link, old_release = _current_release(base_path)
    if old_release == candidate_path:
        raise PublishError(f"candidate is already current: {candidate_path}")
    service_state = _service_preflight(
        base=base_path,
        old_release=old_release,
        control_root=control_path,
        port=port,
        legacy_backend_pid=legacy_backend_pid,
    )
    validated = _validate_candidate(base_path, candidate_path, expected_manifest_sha256)

    transaction_id = f"publish_{int(time.time())}_{uuid.uuid4().hex[:10]}"
    transaction_root = base_path / ".agent_control" / "neyvia_publish"
    transaction_path = transaction_root / "transactions" / f"{transaction_id}.json"
    receipt_path = transaction_root / "receipts" / f"{transaction_id}.json"
    transaction: dict[str, Any] = {
        "schema": PUBLISH_SCHEMA,
        "transactionId": transaction_id,
        "status": "preflight-complete",
        "candidate": str(candidate_path),
        "candidateTreeSha256": validated["tree"]["manifestSha256"],
        "sourceManifestSha256": expected_manifest_sha256.casefold(),
        "completionProofPath": str(validated["completionPath"]),
        "transferReceiptPath": str(validated["receiptPath"]),
        "previousRelease": str(old_release),
        "previousLinkTarget": old_link,
        "servicePreflight": service_state,
        "publisherLock": dict(publisher_lock.owner or {}),
        "createdAt": _utc_now(),
    }
    _atomic_json(transaction_path, transaction)

    candidate_link = os.path.relpath(candidate_path, current.parent)
    publish_link: Path | None = None
    rollback_link: Path | None = None
    try:
        publish_link = _prepare_symlink(current, candidate_link, "publish")
        rollback_link = _prepare_symlink(current, old_link, "rollback")
    except OSError:
        if publish_link is not None and publish_link.is_symlink():
            publish_link.unlink()
        raise
    switched = False
    legacy_stopped = False
    legacy_stop_attempted = False
    activation: dict[str, Any] | None = None
    rollback: dict[str, Any] | None = None
    try:
        if service_state["status"] == "legacy-verified":
            service_state = _service_preflight(
                base=base_path,
                old_release=old_release,
                control_root=control_path,
                port=port,
                legacy_backend_pid=int(service_state["pid"]),
            )
            legacy_stop_attempted = True
            _stop_legacy_backend(int(service_state["pid"]), legacy_stop_timeout_seconds)
            legacy_stopped = True
        assert publish_link is not None
        assert rollback_link is not None
        _replace_current_link(publish_link, current)
        switched = True
        transaction.update({"status": "activating", "switchedAt": _utc_now()})
        _atomic_json(transaction_path, transaction)
        activation = _run_services(
            candidate=candidate_path,
            target_release=candidate_path,
            base=base_path,
            control_root=control_path,
            timeout_seconds=service_timeout_seconds,
            shutdown_timeout_seconds=launcher_shutdown_timeout_seconds,
        )
        post_activation_validation = _validate_candidate(
            base_path,
            candidate_path,
            expected_manifest_sha256,
        )
        managed = _verify_managed_backend(
            base=base_path,
            release=candidate_path,
            control_root=control_path,
            port=port,
        )
        if rollback_link is not None and rollback_link.is_symlink():
            rollback_link.unlink()
        receipt = {
            **transaction,
            "status": "published",
            "publishedAt": _utc_now(),
            "current": str(current),
            "activeRelease": str(candidate_path),
            "activation": activation,
            "postActivationCandidateTreeSha256": post_activation_validation["tree"]["manifestSha256"],
            "managedBackend": managed,
            "receiptPath": str(receipt_path),
        }
        _atomic_json(receipt_path, receipt)
        _atomic_json(transaction_path, receipt)
        return receipt
    except Exception as publish_exc:
        rollback_errors: list[str] = []
        current_restored = not switched
        if publish_link is not None and publish_link.is_symlink():
            publish_link.unlink()
        if switched:
            try:
                assert rollback_link is not None
                _replace_current_link(rollback_link, current)
                current_restored = True
            except OSError as exc:
                rollback_errors.append(f"current-link restore failed: {exc}")
            except PublishError as exc:
                rollback_errors.append(f"current-link restore failed: {exc}")
        elif rollback_link is not None and rollback_link.is_symlink():
            rollback_link.unlink()
        legacy_needs_restart = bool(
            legacy_stop_attempted
            and service_state.get("pid")
            and not _pid_alive(int(service_state["pid"]))
        )
        if current_restored and (switched or legacy_stopped or legacy_needs_restart):
            try:
                rollback_launch = _run_services(
                    candidate=candidate_path,
                    target_release=old_release,
                    base=base_path,
                    control_root=control_path,
                    timeout_seconds=service_timeout_seconds,
                    shutdown_timeout_seconds=launcher_shutdown_timeout_seconds,
                )
                rollback_backend = _verify_managed_backend(
                    base=base_path,
                    release=old_release,
                    control_root=control_path,
                    port=port,
                )
                rollback = {
                    "status": "restored",
                    "release": str(old_release),
                    "launch": rollback_launch,
                    "managedBackend": rollback_backend,
                }
            except Exception as exc:
                rollback_errors.append(f"old-release service restore failed: {exc}")
        if rollback_errors:
            failure_status = "rollback-failed"
        elif switched or legacy_stopped or legacy_needs_restart:
            failure_status = "rolled-back"
        else:
            failure_status = "aborted"
        failed_receipt = {
            **transaction,
            "status": failure_status,
            "failedAt": _utc_now(),
            "errorType": type(publish_exc).__name__,
            "error": str(publish_exc),
            "activation": activation,
            "rollback": rollback,
            "rollbackErrors": rollback_errors,
            "receiptPath": str(receipt_path),
        }
        try:
            _atomic_json(receipt_path, failed_receipt)
            _atomic_json(transaction_path, failed_receipt)
        except OSError:
            pass
        if rollback_errors:
            detail = f"candidate publication failed; rollback requires intervention: {publish_exc}; {'; '.join(rollback_errors)}"
        elif failure_status == "rolled-back":
            detail = f"candidate publication failed and old release was restored: {publish_exc}"
        else:
            detail = f"candidate publication aborted before current changed: {publish_exc}"
        raise PublishError(detail) from publish_exc


def publish_candidate(
    *,
    base: str | Path,
    candidate: str | Path,
    expected_manifest_sha256: str,
    control_root: str | Path = DEFAULT_CONTROL_ROOT,
    port: int = DEFAULT_PORT,
    service_timeout_seconds: int = DEFAULT_SERVICE_TIMEOUT_SECONDS,
    launcher_shutdown_timeout_seconds: int = DEFAULT_LAUNCHER_SHUTDOWN_TIMEOUT_SECONDS,
    legacy_backend_pid: int | None = None,
    legacy_stop_timeout_seconds: int = 30,
) -> dict[str, Any]:
    if port < 1 or port > 65535:
        raise PublishError("port must be between 1 and 65535")
    if legacy_stop_timeout_seconds < 1:
        raise PublishError("legacy stop timeout must be positive")
    minimum_service_timeout, minimum_shutdown_timeout = _minimum_launcher_timeouts(dict(os.environ))
    if service_timeout_seconds < minimum_service_timeout:
        raise PublishError(
            "service timeout is shorter than the launcher's bounded startup windows: "
            f"{service_timeout_seconds}s < required {minimum_service_timeout}s"
        )
    if launcher_shutdown_timeout_seconds < minimum_shutdown_timeout:
        raise PublishError(
            "launcher shutdown timeout is shorter than the launcher's bounded EXIT rollback windows: "
            f"{launcher_shutdown_timeout_seconds}s < required {minimum_shutdown_timeout}s"
        )
    try:
        base_path = Path(base).expanduser().resolve(strict=True)
    except OSError as exc:
        raise PublishError(f"Syntelos base is unavailable: {base}") from exc
    with _PublisherLock(base_path, candidate) as publisher_lock:
        return _publish_candidate_locked(
            base=base_path,
            candidate=candidate,
            expected_manifest_sha256=expected_manifest_sha256,
            control_root=control_root,
            port=port,
            service_timeout_seconds=service_timeout_seconds,
            launcher_shutdown_timeout_seconds=launcher_shutdown_timeout_seconds,
            legacy_backend_pid=legacy_backend_pid,
            legacy_stop_timeout_seconds=legacy_stop_timeout_seconds,
            publisher_lock=publisher_lock,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate, atomically publish, and health-check one completed Neyvia NAS candidate.",
    )
    parser.add_argument("candidate", help="Candidate name, releases/name, or absolute direct release path")
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--control-root", type=Path, default=DEFAULT_CONTROL_ROOT)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--service-timeout",
        type=int,
        default=DEFAULT_SERVICE_TIMEOUT_SECONDS,
        help="Maximum launcher activation time; must cover all configured internal startup windows.",
    )
    parser.add_argument(
        "--launcher-shutdown-timeout",
        type=int,
        default=DEFAULT_LAUNCHER_SHUTDOWN_TIMEOUT_SECONDS,
        help="Grace window after SIGTERM for the launcher EXIT trap to roll back before continued waiting.",
    )
    parser.add_argument("--legacy-stop-timeout", type=int, default=30)
    parser.add_argument(
        "--legacy-backend-pid",
        type=int,
        help=(
            "One-time explicit migration of a verified unmanaged legacy backend. The PID must own the port "
            "and match the current release's exact runner/static/TLS/root command shape."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = publish_candidate(
            base=args.base,
            candidate=args.candidate,
            expected_manifest_sha256=args.expected_manifest_sha256,
            control_root=args.control_root,
            port=args.port,
            service_timeout_seconds=args.service_timeout,
            launcher_shutdown_timeout_seconds=args.launcher_shutdown_timeout,
            legacy_backend_pid=args.legacy_backend_pid,
            legacy_stop_timeout_seconds=args.legacy_stop_timeout,
        )
    except (PublishError, OSError) as exc:
        print(json.dumps({"schema": PUBLISH_SCHEMA, "status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
