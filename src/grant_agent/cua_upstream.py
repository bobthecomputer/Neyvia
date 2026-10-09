"""Private, process-owned MIT Cua Driver runtime; no global installation or daemon."""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any

from .mcp_broker import StdioJsonRpcTransport

DRIVER_VERSION = "0.32.0"
DRIVER_SHA256 = "d2477595e8b5ae850d119b48c8bbe5c16a1f229f3e99e706bd84622c2d7d98ae"
UIA_SHA256 = "a01d7a2b4cacce135e3b0b45e230f7850ac1eafbe22c5b9f62b230cdb8bacf81"
UPSTREAM_TOOLS = frozenset("list_apps list_windows get_window_state get_desktop_state launch_app click double_click right_click type_text press_key hotkey scroll drag set_value invoke_menu verify_state get_screen_size get_cursor_position start_session get_session list_sessions end_session".split())


RUNTIME_FILES = (("cua-driver.exe", DRIVER_SHA256), ("cua-driver-uia.exe", UIA_SHA256))
DOWNLOAD_MB = 31
# Plain words for the person; the technical route stays in "detail".
MISSING_REASON = "The screen-control helper isn't set up on this PC yet."
SETUP_DETAIL = ("Neyvia stages the pinned MIT cua-driver 0.32.0 (both executables, hash-checked) in {target}. "
                "Set it up from the Preview pane, or run scripts/install_cua_driver.py (--source <runtime-directory> "
                "copies an existing verified copy instead of downloading 31 MB).")
RELEASE_URL = f"https://github.com/trycua/cua/releases/download/cua-driver-rs-v{DRIVER_VERSION}/cua-driver-rs-{DRIVER_VERSION}-windows-x86_64-binary.zip"
ARCHIVE_SHA256 = "16aa3666f4ab4faba2fa6261ecb9349d2e9a0c97eca2a0b0960db5a311c2b1e1"
MAX_DOWNLOAD = 200_000_000


def checkout_runtime() -> Path:
    return Path(__file__).resolve().parents[2] / "tools/cua-driver-win/runtime"


def shared_runtime() -> Path:
    """One verified copy per user and driver version, outside any checkout, so every
    Neyvia install, release and worktree on this PC finds the same helper."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
    return Path(base) / "Neyvia/runtimes/cua-driver" / DRIVER_VERSION


def runtime_candidates() -> list[Path]:
    """Where the helper may live, in order: an explicit override, the shared per-user copy,
    then the running checkout's own tools/cua-driver-win/runtime."""
    explicit = str(os.environ.get("NEYVIA_CUA_DRIVER_DIR") or "").strip()
    rows = ([Path(explicit)] if explicit else []) + [shared_runtime(), checkout_runtime()]
    unique: list[Path] = []
    for row in rows:
        if row not in unique:
            unique.append(row)
    return unique


# Verified digests by (path, size, mtime): the Preview pane reads driver state often, and
# re-hashing 55 MB of executables on every read would stall the backend.
_DIGESTS: dict[tuple[str, int, int], str] = {}
_DIGESTS_LOCK = threading.Lock()


def _digest(path: Path) -> str:
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _DIGESTS_LOCK:
        known = _DIGESTS.get(key)
    if known is None:
        with path.open("rb") as stream:
            known = hashlib.file_digest(stream, "sha256").hexdigest()
        with _DIGESTS_LOCK:
            _DIGESTS[key] = known
    return known


def _check_directory(directory: Path) -> dict:
    for name, expected in RUNTIME_FILES:
        path = directory / name
        if not path.is_file():
            return {"available": False, "missing": name, "runtime": str(directory)}
        if _digest(path) != expected:
            return {"available": False, "mismatch": name, "runtime": str(directory)}
    return {"available": True, "reason": None, "runtime": str(directory)}


def runtime_directory() -> Path | None:
    """The first candidate holding both pinned, hash-verified executables."""
    return next((Path(row["runtime"]) for row in map(_check_directory, runtime_candidates()) if row["available"]), None)


def runtime_status(directory=None):
    """Report both required pinned executables before claiming driver readiness.

    With no directory, every candidate location is checked and the first verified one wins.
    A missing helper is reported in plain words with a setup offer; a hash mismatch is never
    overwritten and stays visible.
    """
    candidates = [Path(directory)] if directory is not None else runtime_candidates()
    checked = [_check_directory(row) for row in candidates]
    ready = next((row for row in checked if row["available"]), None)
    if ready:
        return ready
    target = shared_runtime() if directory is None else Path(directory)
    mismatch = next((row for row in checked if row.get("mismatch")), None)
    if mismatch:
        return {"available": False, "runtime": mismatch["runtime"], "code": "hash_mismatch",
                "reason": "The screen-control helper on this PC doesn't match the verified version, so Neyvia won't run it.",
                "detail": f"Pinned MIT runtime hash mismatch: {mismatch['mismatch']} in {mismatch['runtime']}; preserve the file and install a verified copy",
                "setup": None}
    return {"available": False, "runtime": str(target), "code": "missing", "reason": MISSING_REASON,
            "detail": f"Missing {checked[0].get('missing') or 'cua-driver.exe'}. " + SETUP_DETAIL.format(target=target),
            "setup": {"canInstall": True, "sizeMb": DOWNLOAD_MB, "target": str(target)}}


def install_runtime(source: Path | None = None, target: Path | None = None, *, fetch=None) -> dict:
    """Stage the pinned helper: copy hash-verified binaries from `source`, or download the pinned
    GitHub release archive (hash-checked) when no source is given. Never overwrites a mismatching
    file and never installs anything globally or starts a service."""
    import io
    import zipfile
    runtime = Path(target) if target is not None else shared_runtime()
    if _check_directory(runtime)["available"]:
        return {"ok": True, "version": DRIVER_VERSION, "runtime": str(runtime), "downloaded": False}
    for name, digest in RUNTIME_FILES:
        path = runtime / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Preserving unexpected runtime file: {path}; move it aside before installation")
    staged: dict[str, bytes] = {}
    if source is not None:
        source = Path(source).resolve()
        for name, digest in RUNTIME_FILES:
            path = source / name
            if not path.is_file():
                raise FileNotFoundError(f"Runtime source is missing {name}: {source}")
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != digest:
                raise RuntimeError("Runtime source hash mismatch: " + name)
            staged[name] = payload
        extra = {"source": str(source)}
    else:
        archive = (fetch or _download_release)()
        if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
            raise RuntimeError("Release archive SHA256 does not match the pinned GitHub release")
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            for name, digest in RUNTIME_FILES:
                matches = [m for m in package.infolist() if Path(m.filename).name == name and not m.is_dir()]
                if len(matches) != 1 or matches[0].file_size > MAX_DOWNLOAD:
                    raise RuntimeError("Invalid release member: " + name)
                payload = package.read(matches[0])
                if hashlib.sha256(payload).hexdigest() != digest:
                    raise RuntimeError("Pinned release binary hash mismatch: " + name)
                staged[name] = payload
        extra = {"archiveBytes": len(archive), "archiveSHA256": ARCHIVE_SHA256}
    runtime.mkdir(parents=True, exist_ok=True)
    for name, payload in staged.items():
        path = runtime / name
        if not path.exists():
            partial = path.with_name(path.name + ".partial")
            partial.write_bytes(payload)
            partial.replace(path)
    if not _check_directory(runtime)["available"]:
        raise RuntimeError("The staged helper did not verify after copying")
    return {"ok": True, "version": DRIVER_VERSION, "runtime": str(runtime), "downloaded": source is None,
            "hashes": dict(RUNTIME_FILES), **extra}


def _download_release() -> bytes:
    from urllib.request import urlopen
    with urlopen(RELEASE_URL, timeout=90) as response:
        declared = int(response.headers.get("Content-Length") or 0)
        if declared > MAX_DOWNLOAD:
            raise RuntimeError("Release exceeds the authorized 200 MB download limit")
        archive = response.read(MAX_DOWNLOAD + 1)
    if len(archive) > MAX_DOWNLOAD:
        raise RuntimeError("Release exceeds the authorized 200 MB download limit")
    return archive


class UpstreamDriver:
    """One backend owns one serialized stdio connection, closed with its backend.

    Discovery returns the runtime's definitions verbatim. Perception, browser,
    filesystem, maintenance and network tools are never exposed or callable.
    The calling PC service enforces owner grants before dispatching these tools.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        ready = runtime_status()
        if not ready["available"]:
            raise RuntimeError(ready["reason"])
        self.binary = Path(ready["runtime"]) / "cua-driver.exe"
        home = self.root / ".neyvia/cua/upstream"
        home.mkdir(parents=True, exist_ok=True)
        self._transport = StdioJsonRpcTransport(
            command=[str(self.binary), "mcp", "--direct", "--embedded", "--no-overlay"],
            cwd=str(self.root),
            env={"HOME": str(home), "USERPROFILE": str(home), "CUA_HOME": str(home / ".cua"),
                 "DO_NOT_TRACK": "1", "CUA_TELEMETRY": "false", "CUA_TELEMETRY_ENABLED": "false",
                 "CUA_DRIVER_RS_UPDATE_CHECK": "false", "CUA_DRIVER_EMBEDDED": "1"},
            protocol_version="2025-06-18", framing="newline", request_timeout_s=130,
        )
        self._catalog: list[dict[str, Any]] | None = None
        self._catalog_lock = threading.Lock()

    def list_tools(self) -> list[dict[str, Any]]:
        with self._catalog_lock:
            if self._catalog is None:
                self._catalog = [tool for tool in self._transport.list_tools() if tool.get("name") in UPSTREAM_TOOLS]
                missing = UPSTREAM_TOOLS - {tool["name"] for tool in self._catalog}
                if missing:
                    self.close()
                    raise RuntimeError("Pinned driver is missing contracted tools: " + ", ".join(sorted(missing)))
            return list(self._catalog)

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool not in UPSTREAM_TOOLS:
            raise PermissionError("Tool is outside the approved native Cua surface: " + str(tool))
        if not isinstance(args, dict):
            raise ValueError("Cua arguments must be an object")
        return self._transport.call_tool(tool, args)

    def close(self) -> None:
        # EOF lets the direct runtime finalize its native workers and sessions.
        proc = self._transport._proc
        if proc is not None and proc.poll() is None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
                proc.wait(timeout=3)
            except (OSError, TimeoutError):
                pass
            except Exception:
                # The transport's bounded terminate/kill fallback still reaps it.
                pass
        self._transport.close()

    def __enter__(self) -> "UpstreamDriver":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
