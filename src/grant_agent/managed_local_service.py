"""Hash-pinned demand-start lifecycle for local model and tool services.

This supervisor is intentionally generic.  OCR, speech, translation, indexing,
and other capability domains can share it without gaining arbitrary shell access.
Only a fully declared argv is launched, health endpoints must be loopback-only,
and a persisted PID is never stopped until its executable identity is rechecked.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .subprocess_utils import hidden_windows_subprocess_kwargs


MANAGED_LOCAL_SERVICE_SCHEMA = "neyvia.managed_local_service.v1"
MANAGED_LOCAL_SERVICE_STATUS_SCHEMA = "neyvia.managed_local_service_status.v1"
_SERVICE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_IN_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_IN_PROCESS_LOCKS_GUARD = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            int(pid),
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(
                handle,
                ctypes.byref(exit_code),
            ):
                return False
            return int(exit_code.value) == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_process_path(pid: int) -> str:
    process_query_limited_information = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        int(pid),
    )
    if not handle:
        return ""
    try:
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle,
            0,
            buffer,
            ctypes.byref(size),
        ):
            return ""
        return str(buffer.value)
    finally:
        kernel32.CloseHandle(handle)


def _process_path(pid: int) -> str:
    if not _process_alive(pid):
        return ""
    if os.name == "nt":
        return _windows_process_path(pid)
    executable = Path(f"/proc/{pid}/exe")
    try:
        return str(executable.resolve(strict=True))
    except OSError:
        return ""


def _same_path(left: str | Path, right: str | Path) -> bool:
    first = os.path.normcase(os.path.abspath(str(left)))
    second = os.path.normcase(os.path.abspath(str(right)))
    return first == second


def _contains_value(payload: object, expected: str) -> bool:
    if isinstance(payload, dict):
        return any(_contains_value(value, expected) for value in payload.values())
    if isinstance(payload, list):
        return any(_contains_value(value, expected) for value in payload)
    return str(payload) == expected


def _loopback_url(value: str, *, field_name: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.port
    ):
        raise ValueError(f"{field_name} must be an explicit loopback HTTP URL")
    return value


@dataclass(frozen=True)
class ManagedServiceSpec:
    service_id: str
    executable: Path
    executable_sha256: str
    argv: tuple[str, ...]
    state_root: Path
    health_url: str
    health_expected: dict[str, Any]
    identity_url: str = ""
    identity_value: str = ""
    required_files: tuple[tuple[Path, str], ...] = ()
    cwd: Path | None = None
    environment: dict[str, str] = field(default_factory=dict)
    inherit_environment: bool = True
    startup_timeout_seconds: float = 90.0
    stop_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        normalized_id = self.service_id.strip().lower()
        if not _SERVICE_ID.fullmatch(normalized_id):
            raise ValueError(f"Invalid managed service id: {self.service_id!r}")
        object.__setattr__(self, "service_id", normalized_id)
        object.__setattr__(self, "executable", self.executable.resolve())
        object.__setattr__(self, "state_root", self.state_root.resolve())
        if self.cwd is not None:
            object.__setattr__(self, "cwd", self.cwd.resolve())
        digest = self.executable_sha256.strip().lower()
        if len(digest) != 64 or any(value not in "0123456789abcdef" for value in digest):
            raise ValueError("executable_sha256 must be a SHA-256 digest")
        object.__setattr__(self, "executable_sha256", digest)
        object.__setattr__(
            self,
            "health_url",
            _loopback_url(self.health_url, field_name="health_url"),
        )
        if self.identity_url:
            object.__setattr__(
                self,
                "identity_url",
                _loopback_url(self.identity_url, field_name="identity_url"),
            )
            if not self.identity_value:
                raise ValueError("identity_value is required with identity_url")
        normalized_required: list[tuple[Path, str]] = []
        for path, expected_hash in self.required_files:
            digest = str(expected_hash).strip().lower()
            if len(digest) != 64 or any(
                value not in "0123456789abcdef" for value in digest
            ):
                raise ValueError("required file hashes must be SHA-256 digests")
            normalized_required.append((Path(path).resolve(), digest))
        object.__setattr__(self, "required_files", tuple(normalized_required))
        normalized_environment: dict[str, str] = {}
        for key, value in self.environment.items():
            name = str(key)
            content = str(value)
            if not name or "\0" in name or "=" in name or "\0" in content:
                raise ValueError("Managed service environment entries are invalid")
            normalized_environment[name] = content
        object.__setattr__(self, "environment", normalized_environment)
        if not self.argv:
            raise ValueError("Managed service argv cannot be empty")
        if self.startup_timeout_seconds <= 0 or self.stop_timeout_seconds <= 0:
            raise ValueError("Managed service timeouts must be positive")

    @property
    def state_path(self) -> Path:
        return self.state_root / f"{self.service_id}.json"

    @property
    def lock_path(self) -> Path:
        return self.state_root / f"{self.service_id}.lock"

    @property
    def log_path(self) -> Path:
        return self.state_root / "logs" / f"{self.service_id}.log"

    @property
    def spec_hash(self) -> str:
        payload = {
            "schema": MANAGED_LOCAL_SERVICE_SCHEMA,
            "serviceId": self.service_id,
            "executable": str(self.executable),
            "executableSha256": self.executable_sha256,
            "argv": list(self.argv),
            "cwd": str(self.cwd) if self.cwd else "",
            "healthUrl": self.health_url,
            "healthExpected": self.health_expected,
            "identityUrl": self.identity_url,
            "identityValue": self.identity_value,
            "requiredFiles": [
                {"path": str(path), "sha256": digest}
                for path, digest in self.required_files
            ],
            "environment": dict(sorted(self.environment.items())),
            "inheritEnvironment": self.inherit_environment,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class ManagedLocalService:
    """Start, inspect, recover, and stop one exact loopback service."""

    def __init__(self, spec: ManagedServiceSpec) -> None:
        self.spec = spec

    @contextmanager
    def _locked(self, timeout_seconds: float = 15.0) -> Iterator[None]:
        key = str(self.spec.lock_path)
        with _IN_PROCESS_LOCKS_GUARD:
            local_lock = _IN_PROCESS_LOCKS.setdefault(key, threading.RLock())
        with local_lock:
            self.spec.state_root.mkdir(parents=True, exist_ok=True)
            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    descriptor = os.open(
                        self.spec.lock_path,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o600,
                    )
                    os.write(
                        descriptor,
                        json.dumps(
                            {"pid": os.getpid(), "createdAt": _utc_now()}
                        ).encode("utf-8"),
                    )
                    os.close(descriptor)
                    break
                except FileExistsError:
                    owner = _read_json(self.spec.lock_path)
                    owner_pid = int(owner.get("pid") or 0)
                    try:
                        age = time.time() - self.spec.lock_path.stat().st_mtime
                    except OSError:
                        age = 0
                    if (owner_pid and not _process_alive(owner_pid)) or age > 120:
                        try:
                            self.spec.lock_path.unlink()
                        except OSError:
                            pass
                        continue
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"Timed out waiting for {self.spec.service_id} lifecycle lock"
                        )
                    time.sleep(0.05)
            try:
                yield
            finally:
                try:
                    self.spec.lock_path.unlink()
                except OSError:
                    pass

    def _validate_installation(self) -> None:
        if not self.spec.executable.is_file():
            raise FileNotFoundError(self.spec.executable)
        actual = _sha256_file(self.spec.executable)
        if actual != self.spec.executable_sha256:
            raise RuntimeError(
                f"{self.spec.service_id} executable hash mismatch: {actual}"
            )
        for path, expected_hash in self.spec.required_files:
            if not path.is_file():
                raise FileNotFoundError(path)
            actual_hash = _sha256_file(path)
            if actual_hash != expected_hash:
                raise RuntimeError(
                    f"{self.spec.service_id} required file hash mismatch: "
                    f"{path} ({actual_hash})"
                )
        for value in self.spec.argv:
            if "\0" in value:
                raise ValueError("Managed service arguments cannot contain NUL")

    def _request_json(self, url: str, timeout: float) -> tuple[int, object]:
        request = Request(url, headers={"accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read(1024 * 1024)
            try:
                payload: object = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = raw.decode("utf-8", errors="replace")
            return int(response.status), payload

    def _health(self, timeout: float = 2.0) -> tuple[bool, dict[str, Any]]:
        try:
            status, payload = self._request_json(self.spec.health_url, timeout)
        except (OSError, ValueError):
            return False, {}
        if status != 200 or not isinstance(payload, dict):
            return False, {}
        for key, expected in self.spec.health_expected.items():
            if payload.get(key) != expected:
                return False, payload
        if self.spec.identity_url:
            try:
                identity_status, identity = self._request_json(
                    self.spec.identity_url,
                    timeout,
                )
            except (OSError, ValueError):
                return False, payload
            if identity_status != 200 or not _contains_value(
                identity,
                self.spec.identity_value,
            ):
                return False, payload
        return True, payload

    def status(self) -> dict[str, Any]:
        state = _read_json(self.spec.state_path)
        pid = int(state.get("pid") or 0)
        alive = _process_alive(pid)
        process_path = _process_path(pid) if alive else ""
        executable_matches = bool(
            process_path and _same_path(process_path, self.spec.executable)
        )
        spec_matches = state.get("specHash") == self.spec.spec_hash
        healthy, health = self._health() if alive and executable_matches else (False, {})
        if healthy and spec_matches:
            status = "running"
        elif alive and not executable_matches:
            status = "foreign_pid"
        elif alive and not spec_matches:
            status = "configuration_mismatch"
        elif alive:
            status = "unhealthy"
        elif state.get("status") == "stopped":
            status = "stopped"
        elif state.get("status") == "failed":
            status = "failed"
        elif state:
            status = "stale"
        else:
            status = "stopped"
        result = {
            "schema": MANAGED_LOCAL_SERVICE_STATUS_SCHEMA,
            "serviceId": self.spec.service_id,
            "status": status,
            "healthy": healthy,
            "pid": pid if alive else 0,
            "processPath": process_path,
            "executableMatches": executable_matches,
            "specMatches": spec_matches,
            "health": health,
            "statePath": str(self.spec.state_path),
            "logPath": str(self.spec.log_path),
            "specHash": self.spec.spec_hash,
            "startedAt": state.get("startedAt"),
            "checkedAt": _utc_now(),
        }
        from .proofs_c_runtime import check_service_status
        check_service_status(self.spec, result)
        return result

    def start(self) -> dict[str, Any]:
        with self._locked():
            self._validate_installation()
            current = self.status()
            if current["status"] == "running":
                result = {**current, "reused": True}
                from .proofs_c_runtime import check_service_started
                check_service_started(result)
                return result
            if current["status"] in {"foreign_pid", "configuration_mismatch"}:
                raise RuntimeError(
                    f"Refusing to replace {self.spec.service_id}: "
                    f"{current['status']}"
                )
            if current["status"] == "unhealthy":
                self._stop_locked(require_healthy_identity=False)

            self.spec.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self.spec.log_path.is_file() and self.spec.log_path.stat().st_size > 20 * 1024 * 1024:
                rotated = self.spec.log_path.with_name(
                    f"{self.spec.log_path.stem}-{int(time.time())}.log"
                )
                os.replace(self.spec.log_path, rotated)
            environment = os.environ.copy() if self.spec.inherit_environment else {}
            environment.update(self.spec.environment)
            with self.spec.log_path.open("ab") as log_handle:
                popen_kwargs: dict[str, Any] = {
                    "cwd": str(self.spec.cwd) if self.spec.cwd else None,
                    "env": environment,
                    "stdin": subprocess.DEVNULL,
                    "stdout": log_handle,
                    "stderr": subprocess.STDOUT,
                    "shell": False,
                    "close_fds": True,
                }
                if os.name == "nt":
                    popen_kwargs.update(
                        hidden_windows_subprocess_kwargs(new_process_group=True)
                    )
                    popen_kwargs["creationflags"] = int(
                        popen_kwargs.get("creationflags") or 0
                    ) | int(getattr(subprocess, "DETACHED_PROCESS", 0))
                else:
                    popen_kwargs["start_new_session"] = True
                process = subprocess.Popen(  # noqa: S603
                    [str(self.spec.executable), *self.spec.argv],
                    **popen_kwargs,
                )
            state = {
                "schema": MANAGED_LOCAL_SERVICE_SCHEMA,
                "serviceId": self.spec.service_id,
                "status": "starting",
                "pid": process.pid,
                "executable": str(self.spec.executable),
                "executableSha256": self.spec.executable_sha256,
                "specHash": self.spec.spec_hash,
                "startedAt": _utc_now(),
            }
            _atomic_json(self.spec.state_path, state)
            deadline = time.monotonic() + self.spec.startup_timeout_seconds
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    state.update(
                        {
                            "status": "failed",
                            "exitCode": process.returncode,
                            "failedAt": _utc_now(),
                        }
                    )
                    _atomic_json(self.spec.state_path, state)
                    raise RuntimeError(
                        f"{self.spec.service_id} exited during startup with "
                        f"code {process.returncode}"
                    )
                healthy, health = self._health()
                if healthy:
                    state.update(
                        {
                            "status": "running",
                            "healthyAt": _utc_now(),
                            "health": health,
                        }
                    )
                    _atomic_json(self.spec.state_path, state)
                    result = {**self.status(), "reused": False}
                    from .proofs_c_runtime import check_service_started
                    check_service_started(result)
                    return result
                time.sleep(0.1)
            try:
                process.terminate()
                process.wait(timeout=self.spec.stop_timeout_seconds)
            except Exception:
                process.kill()
            state.update({"status": "failed", "failedAt": _utc_now()})
            _atomic_json(self.spec.state_path, state)
            raise TimeoutError(
                f"{self.spec.service_id} did not become healthy within "
                f"{self.spec.startup_timeout_seconds:g} seconds"
            )

    def _stop_locked(self, *, require_healthy_identity: bool) -> dict[str, Any]:
        current = self.status()
        pid = int(current.get("pid") or 0)
        if not pid:
            state = {
                "schema": MANAGED_LOCAL_SERVICE_SCHEMA,
                "serviceId": self.spec.service_id,
                "status": "stopped",
                "pid": 0,
                "specHash": self.spec.spec_hash,
                "stoppedAt": _utc_now(),
            }
            _atomic_json(self.spec.state_path, state)
            result = {**self.status(), "alreadyStopped": True}
            from .proofs_c_runtime import check_service_stopped
            check_service_stopped(result)
            return result
        if not current.get("executableMatches") or not current.get("specMatches"):
            raise RuntimeError(
                f"Refusing to stop unverified PID {pid} for {self.spec.service_id}"
            )
        if require_healthy_identity and not current.get("healthy"):
            raise RuntimeError(
                f"Refusing to stop {self.spec.service_id} without healthy identity"
            )
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        deadline = time.monotonic() + self.spec.stop_timeout_seconds
        while _process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if _process_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except (AttributeError, OSError):
                pass
        if _process_alive(pid):
            raise RuntimeError(
                f"{self.spec.service_id} did not stop PID {pid}"
            )
        state = {
            "schema": MANAGED_LOCAL_SERVICE_SCHEMA,
            "serviceId": self.spec.service_id,
            "status": "stopped",
            "pid": 0,
            "specHash": self.spec.spec_hash,
            "stoppedAt": _utc_now(),
        }
        _atomic_json(self.spec.state_path, state)
        result = {**self.status(), "alreadyStopped": False}
        from .proofs_c_runtime import check_service_stopped
        check_service_stopped(result)
        return result

    def stop(self) -> dict[str, Any]:
        with self._locked():
            return self._stop_locked(require_healthy_identity=True)

    def restart(self) -> dict[str, Any]:
        with self._locked():
            current = self.status()
            if current.get("pid"):
                self._stop_locked(require_healthy_identity=True)
        return self.start()
