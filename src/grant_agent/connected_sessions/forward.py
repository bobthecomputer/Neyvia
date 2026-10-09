"""Forward a connected-sessions command from the desktop bridge to the persistent PC service.

The installed desktop app runs every command in a short-lived ``python -m
grant_agent.desktop_bridge`` process, which exits after answering. The broker, its live runs
and its event buffer belong to the long-running service (``scripts/run_web_backend.py``), so
the bridge only carries the call over loopback HTTP. It signs in with the service's existing
local-session bootstrap (loopback only, no password), makes the call, and signs out again.

Failures come back as data, never as an exception: ``{"ok": false, "code": ..., "message": ...}``.
The Tauri command layer turns an envelope-level failure into a bare error string, which would lose
the code, so the bridge returns this dict as the command's result instead.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from .. import proofs_a_sessions as _proofs

DEFAULT_SERVICE_PORT = 47881
_OFFLINE = ("The Neyvia PC service is not running, so this session cannot be reached. "
            "Start Neyvia on the PC and try again.")


def service_port() -> int:
    for name in ("NEYVIA_CONNECTED_SERVICE_PORT", "NEYVIA_WEB_PORT", "FLUXIO_WEB_PORT"):
        try:
            value = int(os.environ.get(name) or 0)
        except ValueError:
            continue
        if 0 < value < 65536:
            return value
    return DEFAULT_SERVICE_PORT


def _timeout(command: str, payload: dict[str, Any]) -> float:
    if command in {"dictation_transcribe_command", "dictation_redecode_command"}:
        return 300
    if command == "dictation_stream_command" and payload.get("op") == "finish":
        return 180
    if command == "connected_events_poll_command":
        try:
            return min(20.0, max(0.0, float(payload.get("waitSeconds") or 0))) + 15
        except (TypeError, ValueError):
            return 35
    if command == "connected_session_new_command":
        return 45  # the service waits up to 15 s for the new session to be named
    if command == "connected_session_git_action_command":
        return 200
    return 30


def _failure(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "message": message, "error": message}


@_proofs.checked_result(lambda args, kwargs, result: _proofs.check_forward_result(result))
def forward_connected_command(state_root: Path, command: str, payload: dict[str, Any]) -> Any:
    inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    body = {"command": command, "payload": {**inner, "_expectedStateRoot": str(state_root)}}
    base = f"http://127.0.0.1:{service_port()}"
    _proofs.check_forward_request(state_root, command, inner, body, base)
    # Never route loopback through a system proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def post(path: str, value: dict[str, Any], timeout: float) -> Any:
        request = urllib.request.Request(base + path, data=json.dumps(value).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=timeout) as response:
            return json.load(response)

    def refusal(exc: urllib.error.HTTPError) -> dict[str, Any]:
        try:
            data = json.load(exc)
        except (ValueError, OSError):
            data = None
        if isinstance(data, dict) and data.get("code"):
            return data
        return _failure("pc_service_error", f"The Neyvia PC service answered with an error ({exc.code}).")

    try:
        post("/api/auth/local-session", {}, 10)
    except urllib.error.HTTPError as exc:
        return _failure("pc_service_auth", f"The Neyvia PC service did not accept this device's local sign-in ({exc.code}).")
    except (urllib.error.URLError, OSError):
        return _failure("pc_service_offline", _OFFLINE)
    try:
        answer = post("/api/backend", body, _timeout(command, inner))
        return answer.get("data") if isinstance(answer, dict) and answer.get("ok") else _failure(
            "pc_service_error", "The Neyvia PC service did not accept this request.")
    except urllib.error.HTTPError as exc:
        return refusal(exc)
    except (socket.timeout, TimeoutError):
        return _failure("pc_service_timeout", "The Neyvia PC service did not answer in time.")
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return _failure("pc_service_timeout", "The Neyvia PC service did not answer in time.")
        return _failure("pc_service_offline", _OFFLINE)
    finally:
        try:
            post("/api/auth/logout", {}, 5)
        except (urllib.error.URLError, OSError, ValueError):
            pass
