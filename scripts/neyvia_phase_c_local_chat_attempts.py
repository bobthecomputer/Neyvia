#!/usr/bin/env python3
"""Attempt local authenticated chat turns for Phase C; record auth/runtime blockers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".agent_control" / "nas_transfers"
BASE = "http://127.0.0.1:47880"


def _load_creds() -> tuple[str, str]:
    note = (ROOT / ".agent_control" / "neyvia_admin_password.txt").read_text(encoding="utf-8")
    entries = dict(line.split(": ", 1) for line in note.splitlines() if line.startswith(("Username: ", "Password: ")))
    if not entries.get("Username") or not entries.get("Password"):
        raise RuntimeError("The local Neyvia account note is incomplete.")
    return entries["Username"], entries["Password"]


def _request(opener, method: str, url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=90) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"raw": body[:2000]}
            return {"ok": True, "status": resp.status, "body": parsed}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw": body[:2000]}
        return {"ok": False, "status": exc.code, "body": parsed, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    user, password = _load_creds()
    receipt = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "phase": "C",
        "goal": "local authenticated chat turn attempts",
        "login": {},
        "turns": {},
    }

    # Common login paths used by Fluxio/Syntelos web backend.
    login_attempts = []
    for path, payload in [
        ("/api/auth/login", {"username": user, "password": password}),
        ("/api/login", {"username": user, "password": password}),
        ("/api/session/login", {"username": user, "password": password}),
        ("/api/account/login", {"username": user, "password": password}),
    ]:
        result = _request(opener, "POST", BASE + path, payload)
        login_attempts.append({"path": path, "ok": result.get("ok"), "status": result.get("status"), "body": result.get("body")})
        if result.get("ok"):
            receipt["login"] = {"path": path, "ok": True, "status": result.get("status"), "user": user}
            break
    else:
        receipt["login"] = {"ok": False, "attempts": login_attempts, "user": user}

    for runtime in ("claude-code", "grok-build", "opencode"):
        payload = {
            "runtime": runtime,
            "runtimeId": runtime,
            "prompt": "Reply with exactly: PHASE_C_PROOF_OK",
            "message": "Reply with exactly: PHASE_C_PROOF_OK",
            "sessionId": f"phase_c_{runtime.replace('-', '_')}",
            "workspacePath": str(ROOT),
            "route": {"provider": runtime, "model": "", "effort": "low", "role": "executor"},
        }
        # Try a few chat endpoints.
        turn = {"runtime": runtime, "attempts": []}
        for path in ("/api/agent/chat", "/api/chat", "/api/runtime/chat", "/api/control/agent-chat"):
            result = _request(opener, "POST", BASE + path, payload)
            turn["attempts"].append(
                {
                    "path": path,
                    "ok": result.get("ok"),
                    "status": result.get("status"),
                    "body": result.get("body"),
                    "error": result.get("error"),
                }
            )
            body = result.get("body") or {}
            if result.get("ok") or (isinstance(body, dict) and (body.get("error") or body.get("reply") is not None)):
                turn["selected"] = path
                turn["result"] = body
                # Classify
                err = str(body.get("error") or "")
                reply = str(body.get("reply") or "")
                if reply and "PHASE_C_PROOF_OK" in reply and not err:
                    turn["status"] = "success"
                elif any(token in (err + reply).lower() for token in ("auth", "login", "logged in", "not logged", "api key", "unauthorized")):
                    turn["status"] = "blocked_auth"
                elif result.get("status") in {401, 403}:
                    turn["status"] = "blocked_http_auth"
                elif not result.get("ok") and result.get("status") == 404:
                    continue
                else:
                    turn["status"] = "failed_or_blocked"
                break
        else:
            turn["status"] = "endpoint_not_found"
        receipt["turns"][runtime] = turn

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"neyvia_phase_c_local_chat_attempts_{stamp}.json"
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"receipt": str(path), "loginOk": bool((receipt.get("login") or {}).get("ok")), "turns": {k: v.get("status") for k, v in receipt["turns"].items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
