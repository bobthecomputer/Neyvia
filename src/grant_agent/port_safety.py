from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


DEFAULT_PROBE_COOLDOWN_SECONDS = 20
DEFAULT_PROBE_WINDOW_SECONDS = 60
DEFAULT_PROBE_MAX_ATTEMPTS = 6
LOCK_STALE_SECONDS = 45


def _now() -> float:
    return time.time()


def _safe_key(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)[:180]


def _state_dir(root: Path | str | None = None) -> Path:
    base = Path(root or os.environ.get("FLUXIO_PORT_SAFETY_ROOT") or Path.cwd()).expanduser()
    return base / ".agent_control"


def _state_path(root: Path | str | None = None) -> Path:
    return _state_dir(root) / "port_safety.json"


def _lock_path(root: Path | str | None = None) -> Path:
    return _state_dir(root) / "port_safety.lock"


@contextmanager
def _file_lock(root: Path | str | None = None, *, timeout_seconds: float = 5.0) -> Iterator[None]:
    lock_path = _lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = _now() + max(0.1, timeout_seconds)
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"pid": os.getpid(), "createdAt": _now()}))
            break
        except FileExistsError:
            try:
                if _now() - lock_path.stat().st_mtime > LOCK_STALE_SECONDS:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if _now() >= deadline:
                raise RuntimeError(f"Timed out waiting for port safety lock: {lock_path}")
            time.sleep(0.1)
    try:
        yield
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "probes": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "probes": {}}
    probes = payload.get("probes")
    if not isinstance(probes, dict):
        payload["probes"] = {}
    payload.setdefault("version", 1)
    return payload


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def reserve_port_probe(
    *,
    host: str,
    port: int,
    purpose: str,
    identity: str = "",
    root: Path | str | None = None,
    cooldown_seconds: int = DEFAULT_PROBE_COOLDOWN_SECONDS,
    window_seconds: int = DEFAULT_PROBE_WINDOW_SECONDS,
    max_attempts: int = DEFAULT_PROBE_MAX_ATTEMPTS,
    force: bool = False,
) -> dict[str, Any]:
    """Reserve permission to touch a network port without stampeding it."""

    normalized_host = str(host or "").strip().lower()
    normalized_purpose = str(purpose or "probe").strip().lower() or "probe"
    normalized_identity = str(identity or "").strip().lower()
    key = _safe_key(f"{normalized_purpose}:{normalized_host}:{int(port)}:{normalized_identity}")
    now = _now()
    path = _state_path(root)
    with _file_lock(root):
        state = _load_state(path)
        probes = state.setdefault("probes", {})
        entry = probes.get(key) if isinstance(probes.get(key), dict) else {}
        attempts = [
            float(item)
            for item in entry.get("attempts", [])
            if isinstance(item, (int, float)) and now - float(item) <= max(1, window_seconds)
        ]
        last_attempt = float(entry.get("lastAttemptAt") or 0)
        if not force and last_attempt > 0 and now - last_attempt < max(0, cooldown_seconds):
            retry_after = int(max(1, round(cooldown_seconds - (now - last_attempt))))
            return {
                "allowed": False,
                "reason": "cooldown",
                "retryAfterSeconds": retry_after,
                "key": key,
                "attemptsInWindow": len(attempts),
                "statePath": str(path),
            }
        if not force and len(attempts) >= max(1, max_attempts):
            oldest = min(attempts) if attempts else now
            retry_after = int(max(1, round(window_seconds - (now - oldest))))
            return {
                "allowed": False,
                "reason": "rate_limited",
                "retryAfterSeconds": retry_after,
                "key": key,
                "attemptsInWindow": len(attempts),
                "statePath": str(path),
            }
        attempts.append(now)
        probes[key] = {
            "host": normalized_host,
            "port": int(port),
            "purpose": normalized_purpose,
            "identity": normalized_identity,
            "lastAttemptAt": now,
            "attempts": attempts[-max(1, max_attempts) :],
        }
        state["updatedAt"] = now
        _write_state(path, state)
    return {
        "allowed": True,
        "reason": "reserved",
        "retryAfterSeconds": 0,
        "key": key,
        "attemptsInWindow": len(attempts),
        "statePath": str(path),
    }


def tcp_port_accepts_connection(host: str, port: int, *, timeout_seconds: float = 0.25) -> bool:
    target_host = "127.0.0.1" if str(host or "").strip() in {"", "0.0.0.0", "::"} else str(host).strip()
    try:
        with socket.create_connection((target_host, int(port)), timeout=max(0.05, timeout_seconds)):
            return True
    except OSError:
        return False
