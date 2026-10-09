#!/usr/bin/env python3
"""Call /api/backend send_agent_chat_command for managed CLIs and record outcomes."""

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


def main() -> int:
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def post(path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            BASE + path,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with opener.open(req, timeout=120) as resp:
                return {"ok": True, "status": resp.status, "body": json.loads(resp.read().decode("utf-8", "replace"))}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"raw": raw[:2000]}
            return {"ok": False, "status": exc.code, "body": body, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    receipt = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "phase": "C",
        "goal": "local /api/backend send_agent_chat_command proofs",
        "login": None,
        "turns": {},
    }

    note = (ROOT / ".agent_control" / "neyvia_admin_password.txt").read_text(encoding="utf-8")
    entries = dict(line.split(": ", 1) for line in note.splitlines() if line.startswith(("Username: ", "Password: ")))
    if not entries.get("Username") or not entries.get("Password"):
        raise RuntimeError("The local Neyvia account note is incomplete.")
    login = post("/api/auth/login", {"username": entries["Username"], "password": entries["Password"]})
    receipt["login"] = {
        "ok": bool(login.get("ok")),
        "status": login.get("status"),
        "bodyKeys": sorted((login.get("body") or {}).keys()) if isinstance(login.get("body"), dict) else [],
    }
    for runtime in ("claude-code", "grok-build", "opencode"):
        payload = {
            "command": "send_agent_chat_command",
            "payload": {
                "runtime": runtime,
                "runtimeId": runtime,
                "prompt": f"PHASE_C_{runtime}_PROOF: reply with exactly OK",
                "message": f"PHASE_C_{runtime}_PROOF: reply with exactly OK",
                "sessionId": f"phase_c_{runtime.replace('-', '_')}",
                "workspacePath": str(ROOT),
                "route": {"provider": runtime, "model": "", "effort": "low", "role": "executor"},
            },
        }
        result = post("/api/backend", payload)
        body = result.get("body") or {}
        data = body.get("data") if isinstance(body, dict) else None
        turn = {
            "httpOk": bool(result.get("ok")),
            "status": result.get("status"),
            "error": result.get("error") or (body.get("error") if isinstance(body, dict) else None),
            "data": data,
        }
        text_blob = json.dumps(turn, ensure_ascii=False).lower()
        reply = ""
        if isinstance(data, dict):
            reply = str(data.get("reply") or "")
            err = str(data.get("error") or "")
            if reply and "ok" in reply.lower() and not err:
                turn["proofStatus"] = "success"
            elif any(tok in (err + reply + text_blob) for tok in ("auth", "login", "logged", "api key", "unauthorized", "not found on path")):
                turn["proofStatus"] = "blocked_auth_or_missing"
            elif err:
                turn["proofStatus"] = "failed"
            else:
                turn["proofStatus"] = "inconclusive"
        else:
            turn["proofStatus"] = "http_failed" if not result.get("ok") else "unexpected_shape"
        # Avoid huge raw dumps
        if isinstance(data, dict) and isinstance(data.get("raw"), (dict, list, str)):
            data = dict(data)
            raw = data.get("raw")
            data["raw"] = (json.dumps(raw)[:1200] + "…") if not isinstance(raw, str) else (raw[:1200] + ("…" if len(raw) > 1200 else ""))
            turn["data"] = data
        receipt["turns"][runtime] = turn

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"neyvia_phase_c_backend_chat_attempts_{stamp}.json"
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "receipt": str(path),
                "loginOk": bool((receipt.get("login") or {}).get("ok")),
                "turns": {k: v.get("proofStatus") for k, v in receipt["turns"].items()},
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
