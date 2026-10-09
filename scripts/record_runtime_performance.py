#!/usr/bin/env python3
"""Record bounded, build-bound Neyvia runtime performance evidence.

The recorder launches the supplied runtime once per startup sample. It records
only measurements it can obtain and leaves unavailable metrics explicitly
unproven. It never writes the command, URLs, local paths, response bodies, or
process output to the evidence file.
"""

from __future__ import annotations

import argparse
import ctypes
import ipaddress
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from ctypes import wintypes
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from verify_performance_budget import (
    RECORDER_SCHEMA,
    RUNTIME_SCHEMA,
    EVIDENCE_BINDING_SCHEMA,
    _evidence_digest,
    _read_json,
    _validate_config,
    config_fingerprint,
    measure_build,
)


DEFAULT_LIMITS = {
    "minStartupSamples": 3,
    "maxSamplesPerMetric": 20,
    "maxCaptureDurationSeconds": 1800,
    "maxHttpRequestsPerSample": 64,
    "maxResponseBytes": 5_000_000,
    "requestTimeoutSeconds": 10,
    "startupTimeoutSeconds": 30,
    "pollIntervalMs": 100,
}
BATTERY_SOURCE_IDS = (
    "external-power-meter",
    "os-battery-telemetry",
    "windows-energy-report",
)
METRICS = (
    "bootstrapPayloadBytes",
    "startupP95Ms",
    "memoryP95MiB",
    "cpuP95Percent",
    "networkInitialBytes",
    "batteryDrainPercentPerHour",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


class CaptureDeadlineExceeded(RuntimeError):
    pass


def _remaining(deadline: float, monotonic: Callable[[], float]) -> float:
    seconds = deadline - monotonic()
    if seconds <= 0:
        raise CaptureDeadlineExceeded("capture wall-clock deadline exceeded")
    return seconds


def _sleep_bounded(seconds: float, deadline: float, monotonic: Callable[[], float]) -> None:
    time.sleep(min(seconds, _remaining(deadline, monotonic)))
    _remaining(deadline, monotonic)


def _redact_error(value: object) -> str:
    """Return a bounded diagnostic with likely secrets and paths removed."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text)
    text = re.sub(
        r'''(?i)(["']?(?:token|password|secret|api[_-]?key|authorization)["']?\s*[:=]\s*)(["'])(.*?)\2''',
        r"\1\2[redacted]\2",
        text,
    )
    text = re.sub(
        r'''(?i)(["']?(?:token|password|secret|api[_-]?key|authorization)["']?\s*[:=]\s*)([^"',;&\s}]+)''',
        r"\1[redacted]",
        text,
    )
    text = re.sub(r"(?i)(https?://)(?:[^/@\s]+@)?([^/?#\s]+)(?:[/?#][^\s]*)?", r"\1\2/[redacted]", text)
    text = re.sub(r"\\\\[^\\\s]+\\[^\\\s]+(?:\\[^\s]*)?", "[local-path]", text)
    text = re.sub(r"(?<!:)//[^/\s]+/[^/\s]+(?:/[^\s,;]*)?", "[local-path]", text)
    text = re.sub(r"(?i)\b[A-Z]:[\\/][^\r\n,;]+", "[local-path]", text)
    text = re.sub(
        r"(?<!\w)/(?:home|users|tmp|var|volume1|mnt|workspace|opt|srv)/[^\s,;]+",
        "[local-path]",
        text,
    )
    return text[:240] or "measurement unavailable"


def _limits(config: dict[str, Any]) -> dict[str, int | float]:
    configured = config.get("evidenceLimits")
    merged = dict(DEFAULT_LIMITS)
    if isinstance(configured, dict):
        merged.update({key: configured[key] for key in DEFAULT_LIMITS if key in configured})
    for name, value in merged.items():
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or value <= 0
        ):
            raise ValueError(f"evidenceLimits.{name} must be a positive number")
    if int(merged["minStartupSamples"]) > int(merged["maxSamplesPerMetric"]):
        raise ValueError("minStartupSamples cannot exceed maxSamplesPerMetric")
    return merged


class _InitialResourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.references.append(str(values["src"]))
        if tag == "link" and values.get("href"):
            rel = set(str(values.get("rel") or "").lower().split())
            if rel.intersection({"stylesheet", "modulepreload", "preload"}):
                self.references.append(str(values["href"]))


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


def _validate_http_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("endpoint must be an HTTP(S) URL without user information")
    host = parsed.hostname.lower()
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError("endpoint must use a loopback host unless explicitly allowed")


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, expected_origin: tuple[str, str, int | None]) -> None:
        super().__init__()
        self.expected_origin = expected_origin

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        _validate_http_url(newurl)
        if _origin(newurl) != self.expected_origin:
            raise urllib.error.URLError("cross-origin redirect rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(url: str) -> urllib.request.OpenerDirector:
    _validate_http_url(url)
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _SameOriginRedirectHandler(_origin(url))
    )


def _fetch(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    deadline: float,
    monotonic: Callable[[], float],
) -> tuple[bytes, str]:
    if max_bytes <= 0:
        raise ValueError("response exceeds configured byte limit")
    request = urllib.request.Request(url, headers={"User-Agent": "neyvia-performance-recorder/1"})
    bounded_timeout = min(timeout, _remaining(deadline, monotonic))
    with _opener(url).open(request, timeout=bounded_timeout) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > max_bytes:
            raise ValueError("response exceeds configured byte limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            if response.isclosed():
                break
            remaining = min(timeout, _remaining(deadline, monotonic))
            _set_response_socket_timeout(response, remaining)
            chunk = response.read1(min(64 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("response exceeds configured byte limit")
        body = b"".join(chunks)
        content_type = str(response.headers.get("Content-Type") or "")
    return body, content_type


def _set_response_socket_timeout(response: Any, timeout: float) -> None:
    candidates = [
        ("fp", "raw", "_sock"),
        ("fp", "raw", "_fp", "fp", "raw", "_sock"),
    ]
    for attributes in candidates:
        current = response
        for attribute in attributes:
            current = getattr(current, attribute, None)
            if current is None:
                break
        if current is not None and hasattr(current, "settimeout"):
            try:
                current.settimeout(max(0.001, timeout))
            except OSError:
                if getattr(current, "_closed", False):
                    return
                raise
            return
    raise OSError("response socket timeout control is unavailable")


def measure_initial_network_bytes(
    app_url: str,
    *,
    timeout: float,
    max_bytes: int,
    max_requests: int,
    deadline: float,
    monotonic: Callable[[], float],
) -> tuple[int, int]:
    """Fetch the HTML and its static initial resources within fixed bounds."""
    html, content_type = _fetch(
        app_url,
        timeout=timeout,
        max_bytes=max_bytes,
        deadline=deadline,
        monotonic=monotonic,
    )
    total = len(html)
    requests = 1
    if "html" not in content_type.lower():
        return total, requests
    parser = _InitialResourceParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    base = urllib.parse.urlsplit(app_url)
    seen: set[str] = set()
    for reference in parser.references:
        resolved = urllib.parse.urljoin(app_url, reference)
        parsed = urllib.parse.urlsplit(resolved)
        if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
            continue
        clean = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
        if clean in seen:
            continue
        seen.add(clean)
        if requests >= max_requests:
            raise ValueError("initial resource count exceeds configured request limit")
        body, _ = _fetch(
            clean,
            timeout=timeout,
            max_bytes=max_bytes - total,
            deadline=deadline,
            monotonic=monotonic,
        )
        total += len(body)
        requests += 1
    return total, requests


class _ProcessMonitor:
    """Best-effort root-process memory and CPU monitor using local OS APIs."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.memory_mib: list[float] = []
        self.cpu_percent: list[float] = []
        self.source = "unavailable"
        self._last_cpu: float | None = None
        self._last_wall: float | None = None
        if os.name == "nt":
            self.source = "windows-root-process"
        elif Path(f"/proc/{pid}/stat").is_file():
            self.source = "procfs-root-process"

    def _windows_values(self) -> tuple[float, float]:
        process_query = 0x0400
        process_vm_read = 0x0010
        handle = ctypes.windll.kernel32.OpenProcess(process_query | process_vm_read, False, self.pid)
        if not handle:
            raise OSError("process metrics unavailable")
        try:
            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                raise OSError("process memory unavailable")
            created = wintypes.FILETIME()
            exited = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not ctypes.windll.kernel32.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
            ):
                raise OSError("process CPU unavailable")

            def seconds(value: wintypes.FILETIME) -> float:
                return ((value.dwHighDateTime << 32) | value.dwLowDateTime) / 10_000_000

            return counters.WorkingSetSize / (1024 * 1024), seconds(kernel) + seconds(user)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    def _procfs_values(self) -> tuple[float, float]:
        fields = Path(f"/proc/{self.pid}/stat").read_text(encoding="ascii").split()
        ticks = float(os.sysconf("SC_CLK_TCK"))
        page_size = float(os.sysconf("SC_PAGE_SIZE"))
        return float(fields[23]) * page_size / (1024 * 1024), (float(fields[13]) + float(fields[14])) / ticks

    def sample(self) -> None:
        try:
            memory, cpu_seconds = self._windows_values() if os.name == "nt" else self._procfs_values()
        except (OSError, ValueError, IndexError):
            return
        now = time.monotonic()
        self.memory_mib.append(memory)
        if self._last_cpu is not None and self._last_wall is not None and now > self._last_wall:
            self.cpu_percent.append(max(0.0, (cpu_seconds - self._last_cpu) / (now - self._last_wall) * 100.0))
        self._last_cpu = cpu_seconds
        self._last_wall = now


def _wait_ready(
    process: subprocess.Popen[bytes],
    ready_url: str,
    *,
    timeout: float,
    poll_seconds: float,
    monitor: _ProcessMonitor,
    deadline: float,
    monotonic: Callable[[], float],
) -> float:
    started = monotonic()
    startup_deadline = min(deadline, started + timeout)
    opener = _opener(ready_url)
    while monotonic() < startup_deadline:
        if process.poll() is not None:
            raise RuntimeError("runtime exited before readiness")
        monitor.sample()
        try:
            request_timeout = min(1.0, startup_deadline - monotonic(), _remaining(deadline, monotonic))
            with opener.open(ready_url, timeout=request_timeout) as response:
                if 200 <= int(response.status) < 400:
                    return (monotonic() - started) * 1000
        except (OSError, urllib.error.URLError):
            pass
        _sleep_bounded(min(poll_seconds, max(0.0, startup_deadline - monotonic())), deadline, monotonic)
    raise TimeoutError("runtime readiness timed out")


def _endpoint_is_unavailable(
    url: str,
    *,
    deadline: float,
    monotonic: Callable[[], float],
) -> bool:
    _validate_http_url(url)
    parsed = urllib.parse.urlsplit(url)
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    host = str(parsed.hostname)
    probes: list[socket.socket] = []
    try:
        for family, socktype, proto, _, address in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
            probe = socket.socket(family, socktype, proto)
            probes.append(probe)
            probe.settimeout(min(0.5, _remaining(deadline, monotonic)))
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(address)
        return True
    except OSError:
        return False
    finally:
        for probe in probes:
            probe.close()


def _require_endpoint_unavailable(
    url: str,
    *,
    deadline: float,
    monotonic: Callable[[], float],
) -> None:
    if not _endpoint_is_unavailable(
        url,
        deadline=deadline,
        monotonic=monotonic,
    ):
        raise RuntimeError("readiness endpoint availability precondition failed")


def _assign_windows_kill_job(process: subprocess.Popen[bytes]) -> int | None:
    if os.name != "nt":
        return None

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError("process-tree job creation failed")
    information = ExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job,
        9,  # JobObjectExtendedLimitInformation
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        kernel32.CloseHandle(job)
        raise OSError("process-tree job configuration failed")
    if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):
        kernel32.CloseHandle(job)
        raise OSError("process-tree job assignment failed")
    return int(job)


def _resume_windows_process(process: subprocess.Popen[bytes]) -> None:
    if os.name != "nt":
        return
    ntdll = ctypes.windll.ntdll
    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    ntdll.NtResumeProcess.restype = ctypes.c_long
    status = int(ntdll.NtResumeProcess(wintypes.HANDLE(process._handle)))
    if status != 0:
        raise OSError("suspended process resume failed")


CLEANUP_GRACE_SECONDS = 2.0


def _stop_process_tree(
    process: subprocess.Popen[bytes],
    *,
    deadline: float,
    monotonic: Callable[[], float],
    windows_job: int | None,
) -> None:
    """Terminate the spawned process group/tree and fail if it survives."""
    cleanup_uncertain = False
    if os.name == "nt":
        if not windows_job:
            cleanup_uncertain = True
        elif not ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(windows_job)):
            cleanup_uncertain = True
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        # The tree kill was already issued (job close or SIGTERM). Its exit is
        # verified within a fixed grace period: an expired capture deadline must
        # not shrink this to a few milliseconds and misreport a dead tree as
        # uncertain cleanup, hiding the deadline error itself.
        process.wait(timeout=CLEANUP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        cleanup_uncertain = True
        if os.name == "nt":
            # Popen.kill uses the retained process handle, not a reusable PID.
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("process tree cleanup failed") from exc
    if cleanup_uncertain:
        raise RuntimeError("process tree cleanup could not be verified")


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, CaptureDeadlineExceeded):
        return "CAPTURE_DEADLINE_EXCEEDED"
    if isinstance(exc, TimeoutError):
        return "STARTUP_TIMEOUT"
    message = str(exc).lower()
    if "availability precondition" in message:
        return "STARTUP_ENDPOINT_STATE_INVALID"
    if "exited before readiness" in message:
        return "STARTUP_PROCESS_EXITED"
    if "byte limit" in message or "request limit" in message:
        return "HTTP_BOUND_EXCEEDED"
    if isinstance(exc, (urllib.error.URLError, OSError)):
        return "HTTP_REQUEST_FAILED"
    return "MEASUREMENT_UNAVAILABLE"


def record(
    *,
    config: dict[str, Any],
    build_dir: Path,
    command: list[str],
    ready_url: str,
    app_url: str,
    bootstrap_url: str,
    sample_count: int,
    battery_samples: list[float] | None = None,
    battery_source: str | None = None,
    clock: Callable[[], datetime] = _utc_now,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if config.get("schema") != "neyvia.performance-budgets.v1":
        raise ValueError("unsupported performance budget schema")
    _validate_config(config)
    limits = _limits(config)
    minimum = int(limits["minStartupSamples"])
    maximum = int(limits["maxSamplesPerMetric"])
    if not minimum <= sample_count <= maximum:
        raise ValueError(f"sample count must be between {minimum} and {maximum}")
    if not command or not command[0].strip():
        raise ValueError("a runtime command is required")
    for endpoint in (ready_url, app_url, bootstrap_url):
        _validate_http_url(endpoint)
    endpoint_origins = {_origin(endpoint) for endpoint in (ready_url, app_url, bootstrap_url)}
    if len(endpoint_origins) != 1:
        raise ValueError("ready, app, and bootstrap endpoints must use the exact same loopback origin")
    battery_values = list(battery_samples or [])
    if battery_values:
        if battery_source not in BATTERY_SOURCE_IDS:
            raise ValueError("battery evidence requires an enumerated measurement source")
        if not 1 <= len(battery_values) <= maximum:
            raise ValueError(f"battery sample count must be between 1 and {maximum}")
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in battery_values
        ):
            raise ValueError("battery samples must be finite and non-negative")
    elif battery_source is not None:
        raise ValueError("battery source requires at least one battery sample")

    _, _, fingerprint = measure_build(build_dir)
    capture_started = clock()
    wall_started = monotonic()
    deadline = wall_started + float(limits["maxCaptureDurationSeconds"])
    raw: dict[str, list[float]] = {
        "startupP95Ms": [],
        "bootstrapPayloadBytes": [],
        "memoryP95MiB": [],
        "cpuP95Percent": [],
        "networkInitialBytes": [],
        "batteryDrainPercentPerHour": [float(value) for value in battery_values],
    }
    errors: dict[str, list[str]] = {name: [] for name in raw}
    process_sources: set[str] = set()
    network_request_counts: list[int] = []

    for _ in range(sample_count):
        _remaining(deadline, monotonic)
        try:
            _require_endpoint_unavailable(
                ready_url,
                deadline=deadline,
                monotonic=monotonic,
            )
        except Exception as exc:
            errors["startupP95Ms"].append(_error_code(exc))
            if isinstance(exc, CaptureDeadlineExceeded):
                raise
            break
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004  # CREATE_SUSPENDED
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        windows_job: int | None = None
        try:
            windows_job = _assign_windows_kill_job(process)
            _resume_windows_process(process)
        except OSError:
            # The retained process handle identifies this exact suspended process.
            if windows_job:
                ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(windows_job))
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            raise
        monitor = _ProcessMonitor(process.pid)
        sample_values: dict[str, float] = {}
        ready_completed = False
        post_stop_unavailable = False
        pending_deadline_error: CaptureDeadlineExceeded | None = None
        try:
            sample_values["startupP95Ms"] = _wait_ready(
                process,
                ready_url,
                timeout=float(limits["startupTimeoutSeconds"]),
                poll_seconds=float(limits["pollIntervalMs"]) / 1000,
                monitor=monitor,
                deadline=deadline,
                monotonic=monotonic,
            )
            ready_completed = True
            for _sample in range(3):
                monitor.sample()
                _sleep_bounded(float(limits["pollIntervalMs"]) / 1000, deadline, monotonic)
            try:
                bootstrap, _ = _fetch(
                    bootstrap_url,
                    timeout=float(limits["requestTimeoutSeconds"]),
                    max_bytes=int(limits["maxResponseBytes"]),
                    deadline=deadline,
                    monotonic=monotonic,
                )
                sample_values["bootstrapPayloadBytes"] = float(len(bootstrap))
            except CaptureDeadlineExceeded:
                raise
            except Exception as exc:
                errors["bootstrapPayloadBytes"].append(_error_code(exc))
            try:
                network_bytes, request_count = measure_initial_network_bytes(
                    app_url,
                    timeout=float(limits["requestTimeoutSeconds"]),
                    max_bytes=int(limits["maxResponseBytes"]),
                    max_requests=int(limits["maxHttpRequestsPerSample"]),
                    deadline=deadline,
                    monotonic=monotonic,
                )
                sample_values["networkInitialBytes"] = float(network_bytes)
                network_request_counts.append(request_count)
            except CaptureDeadlineExceeded:
                raise
            except Exception as exc:
                errors["networkInitialBytes"].append(_error_code(exc))
        except CaptureDeadlineExceeded as exc:
            pending_deadline_error = exc
        except Exception as exc:
            errors["startupP95Ms"].append(_error_code(exc))
        finally:
            monitor.sample()
            process_sources.add(monitor.source)
            _stop_process_tree(
                process,
                deadline=deadline,
                monotonic=monotonic,
                windows_job=windows_job,
            )
            try:
                _require_endpoint_unavailable(
                    ready_url,
                    deadline=deadline,
                    monotonic=monotonic,
                )
                post_stop_unavailable = True
            except Exception as exc:
                errors["startupP95Ms"].append(_error_code(exc))
                if isinstance(exc, CaptureDeadlineExceeded):
                    pending_deadline_error = exc
        if ready_completed and post_stop_unavailable and pending_deadline_error is None:
            for name, value in sample_values.items():
                raw[name].append(value)
            memory_capacity = max(0, maximum - len(raw["memoryP95MiB"]))
            cpu_capacity = max(0, maximum - len(raw["cpuP95Percent"]))
            raw["memoryP95MiB"].extend(monitor.memory_mib[:memory_capacity])
            raw["cpuP95Percent"].extend(monitor.cpu_percent[:cpu_capacity])
        if pending_deadline_error is not None:
            raise pending_deadline_error

    captured_at = clock()
    duration = monotonic() - wall_started
    if duration < 0 or duration > float(limits["maxCaptureDurationSeconds"]):
        raise RuntimeError("capture duration exceeds configured limit")

    metrics: dict[str, float | None] = {name: None for name in METRICS}
    metric_evidence: dict[str, dict[str, Any]] = {}
    aggregation = {
        "startupP95Ms": "p95",
        "bootstrapPayloadBytes": "maximum",
        "memoryP95MiB": "p95",
        "cpuP95Percent": "p95",
        "networkInitialBytes": "maximum",
        "batteryDrainPercentPerHour": "maximum",
    }
    source = {
        "startupP95Ms": "spawn-to-http-readiness-v1",
        "bootstrapPayloadBytes": "http-response-body-bytes-v1",
        "memoryP95MiB": "+".join(sorted(process_sources)),
        "cpuP95Percent": "+".join(sorted(process_sources)),
        "networkInitialBytes": "same-origin-initial-http-response-body-bytes-v1",
        "batteryDrainPercentPerHour": str(battery_source or ""),
    }
    for name in raw:
        values = [round(value, 6) for value in raw[name]]
        raw[name] = values
        value = max(values) if values and aggregation[name] == "maximum" else _percentile_95(values)
        if value is None or (name == "startupP95Ms" and len(values) != sample_count):
            metric_evidence[name] = {
                "status": "unproven",
                "reasonCode": errors[name][0] if errors[name] else (
                    "BATTERY_NOT_MEASURED"
                    if name == "batteryDrainPercentPerHour"
                    else "MEASUREMENT_UNAVAILABLE"
                ),
                "sampleCount": len(values),
            }
            continue
        metrics[name] = round(value, 3)
        metric_evidence[name] = {
            "status": "measured",
            "source": source[name],
            "aggregation": aggregation[name],
            "sampleCount": len(values),
        }
        if name == "networkInitialBytes":
            metric_evidence[name]["maxRequestCount"] = max(network_request_counts, default=0)

    evidence = {
        "schema": RUNTIME_SCHEMA,
        "recorderSchema": RECORDER_SCHEMA,
        "captureStartedAt": _iso(capture_started),
        "capturedAt": _iso(captured_at),
        "buildFingerprint": fingerprint,
        "budgetConfigFingerprint": config_fingerprint(config),
        "metrics": metrics,
        "metricEvidence": metric_evidence,
        "rawSamples": raw,
        "bounds": {
            "requestedStartupSamples": sample_count,
            "maxSamplesPerMetric": maximum,
            "maxCaptureDurationSeconds": int(limits["maxCaptureDurationSeconds"]),
            "maxHttpRequestsPerSample": int(limits["maxHttpRequestsPerSample"]),
            "maxResponseBytes": int(limits["maxResponseBytes"]),
            "loopbackOnly": True,
            "exactEndpointOrigin": True,
        },
    }
    evidence["evidenceBinding"] = {
        "schema": EVIDENCE_BINDING_SCHEMA,
        "algorithm": "sha256",
        "canonicalization": "json-sort-keys-compact-v1",
        "digest": _evidence_digest(evidence),
    }
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record bounded Neyvia runtime performance evidence")
    parser.add_argument("--config", type=Path, default=Path("config/neyvia_performance_budgets.json"))
    parser.add_argument("--build-dir", type=Path, default=Path("web/dist"))
    parser.add_argument("--output", type=Path, default=Path(".agent_control/performance/runtime-latest.json"))
    parser.add_argument("--ready-url", required=True)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--bootstrap-url", required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument(
        "--battery-drain-percent-per-hour",
        type=float,
        action="append",
        dest="battery_samples",
        help="repeat once per measured battery-drain sample",
    )
    parser.add_argument("--battery-measurement-source", choices=BATTERY_SOURCE_IDS)
    parser.add_argument("command", nargs=argparse.REMAINDER, help="runtime command, preceded by --")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        evidence = record(
            config=_read_json(args.config),
            build_dir=args.build_dir,
            command=command,
            ready_url=args.ready_url,
            app_url=args.app_url,
            bootstrap_url=args.bootstrap_url,
            sample_count=args.samples,
            battery_samples=args.battery_samples,
            battery_source=args.battery_measurement_source,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
        print("runtime performance recording failed: RUNTIME_RECORDING_FAILED", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if all(item["status"] == "measured" for item in evidence["metricEvidence"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
