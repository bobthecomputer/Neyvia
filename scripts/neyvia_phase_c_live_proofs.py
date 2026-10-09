#!/usr/bin/env python3
"""Phase C live proof attempts for Claude Code, Grok Build, and OpenCode.

Probes NAS managed-CLI auth non-interactively, hits local/live control APIs when
reachable, and writes a receipt under .agent_control/nas_transfers/.
Does NOT invent success when interactive login is required.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS_PATH = ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"
RECEIPT_DIR = ROOT / ".agent_control" / "nas_transfers"

REMOTE_CMD = r"""
export PATH="/volume1/Saclay/runtime/bin:/volume1/Saclay/projects/syntelos/runtime/bin:$PATH"
echo '=== which ==='
command -v claude || true
command -v grok || true
command -v kimi || true
command -v opencode || true
command -v agent || true
echo '=== versions ==='
claude --version 2>&1 | head -3 || true
grok --version 2>&1 | head -3 || true
kimi --version 2>&1 | head -3 || true
(opencode --version 2>&1 || opencode version 2>&1) | head -5 || true
echo '=== auth_claude ==='
(timeout 20 claude auth status 2>&1 || timeout 20 claude /status 2>&1 || echo CLAUDE_AUTH_PROBE_FAILED) | head -60
echo '=== auth_grok ==='
(timeout 20 grok auth status 2>&1 || timeout 20 grok whoami 2>&1 || timeout 20 grok status 2>&1 || echo GROK_AUTH_PROBE_FAILED) | head -60
echo '=== auth_kimi ==='
(timeout 20 kimi status 2>&1 || timeout 20 kimi auth status 2>&1 || echo KIMI_AUTH_PROBE_FAILED) | head -60
echo '=== doctor ==='
python3 /volume1/Saclay/projects/vibe-coding-platform/scripts/nas_runtime_doctor.py --extra-bin-dir /volume1/Saclay/runtime/bin --json 2>&1 | head -200
echo '=== local_health ==='
(curl -sk -m 8 https://127.0.0.1:47880/api/health || curl -sk -m 8 http://127.0.0.1:47880/api/health || echo HEALTH_UNREACHABLE) | head -40
"""


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_credentials() -> dict:
    payload = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    return {
        "host": payload.get("host", "192.0.2.10"),
        "port": int(payload.get("port", 22)),
        "username": payload.get("username") or payload.get("user") or "nas-user",
        "password": payload.get("password") or payload.get("secret") or "",
    }


def _connect(credentials: dict) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=credentials["host"],
        port=credentials["port"],
        username=credentials["username"],
        password=credentials["password"],
        look_for_keys=False,
        allow_agent=False,
        timeout=20,
    )
    return client


def _run(client: paramiko.SSHClient, command: str, *, timeout: int = 180) -> dict:
    started = time.time()
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return {
        "exitCode": code,
        "stdout": out[-20000:],
        "stderr": err[-4000:],
        "elapsedSec": round(time.time() - started, 2),
    }


def _http_json(url: str, *, timeout: float = 8.0, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"raw": body[:2000]}
            return {"ok": True, "status": resp.status, "url": url, "body": payload}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": url, "error": str(exc)}


def _classify_auth(stdout: str, runtime: str) -> dict:
    text = stdout.lower()
    blockers = []
    authenticated = False
    if runtime == "claude-code":
        if "logged in" in text or "authenticated" in text or "email" in text:
            authenticated = True
        if "auth login" in text or "not logged" in text or "please run" in text or "login required" in text:
            blockers.append("claude auth login")
            authenticated = False
        if "CLAUDE_AUTH_PROBE_FAILED" in stdout:
            blockers.append("claude auth login")
    elif runtime == "grok-build":
        if "logged in" in text or "authenticated" in text or "api key" in text and "missing" not in text:
            authenticated = True
        if "login" in text or "device-auth" in text or "xai_api_key" in text or "GROK_AUTH_PROBE_FAILED" in stdout:
            blockers.append("grok login --device-auth  # or set XAI_API_KEY")
            authenticated = False
    elif runtime == "kimi-code":
        if "logged in" in text or "authenticated" in text:
            authenticated = True
        if "login" in text or "KIMI_AUTH_PROBE_FAILED" in stdout:
            blockers.append("kimi login")
            authenticated = False
    return {"authenticated": authenticated, "blockerCommands": blockers, "rawSnippet": stdout[-1500:]}


def _parse_sections(blob: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = "preamble"
    lines: list[str] = []
    for line in blob.splitlines():
        if line.startswith("=== ") and line.endswith(" ==="):
            sections[current] = "\n".join(lines).strip()
            current = line.strip("= ").strip()
            lines = []
        else:
            lines.append(line)
    sections[current] = "\n".join(lines).strip()
    return sections


def main() -> int:
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    receipt_path = RECEIPT_DIR / f"neyvia_phase_c_live_proofs_{stamp}.json"
    receipt: dict = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "phase": "C",
        "goal": "Chat + Orchestration live proofs for Claude Code, Grok Build, OpenCode",
        "status": "started",
        "localStack": {},
        "liveControl": {},
        "nasAuthProbes": {},
        "doctor": None,
        "uiModeSwitch": {"attempted": False, "verified": False, "notes": []},
        "proofs": {
            "claude-code": {"chat": "not_attempted", "orchestration": "not_attempted"},
            "grok-build": {"chat": "not_attempted", "orchestration": "not_attempted"},
            "opencode": {"chat": "not_attempted", "orchestration": "not_attempted"},
        },
        "remainingHumanAuthSteps": [],
        "blockerSummary": [],
    }

    # Local control/API probes (no secrets).
    receipt["localStack"] = {
        "frontend": _http_json("http://127.0.0.1:1420/", timeout=5.0),
        "backendHealth": _http_json("http://127.0.0.1:47880/api/health", timeout=5.0),
        "runtimes": _http_json("http://127.0.0.1:47880/api/runtimes", timeout=5.0),
        "control": _http_json("http://127.0.0.1:47880/control", timeout=5.0),
    }
    # Strip huge HTML bodies.
    for key, value in list(receipt["localStack"].items()):
        body = value.get("body")
        if isinstance(body, dict) and "raw" in body and isinstance(body["raw"], str) and len(body["raw"]) > 400:
            body["raw"] = body["raw"][:400] + "…"
        elif isinstance(body, str) and len(body) > 400:
            value["body"] = body[:400] + "…"

    receipt["liveControl"] = {
        "health": _http_json("https://nas.example.invalid:47880/api/health", timeout=10.0),
        "control": _http_json("https://nas.example.invalid:47880/control", timeout=10.0),
    }
    for key, value in list(receipt["liveControl"].items()):
        body = value.get("body")
        if isinstance(body, dict) and "raw" in body and isinstance(body["raw"], str) and len(body["raw"]) > 400:
            body["raw"] = body["raw"][:400] + "…"

    if not CREDENTIALS_PATH.exists():
        receipt["status"] = "blocked"
        receipt["blockerSummary"].append(f"Missing credentials file: {CREDENTIALS_PATH.name}")
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps({"receipt": str(receipt_path), "status": receipt["status"]}, indent=2))
        return 2

    credentials = _load_credentials()
    client = None
    try:
        client = _connect(credentials)
        probe = _run(client, REMOTE_CMD, timeout=180)
        receipt["nasProbe"] = {
            "exitCode": probe["exitCode"],
            "elapsedSec": probe["elapsedSec"],
            "stderrTail": probe["stderr"][-1500:],
        }
        sections = _parse_sections(probe["stdout"])
        receipt["nasSections"] = {k: v[-3000:] for k, v in sections.items()}

        doctor_raw = sections.get("doctor", "")
        try:
            receipt["doctor"] = json.loads(doctor_raw)
        except json.JSONDecodeError:
            receipt["doctor"] = {"raw": doctor_raw[-4000:], "parseError": True}

        receipt["nasAuthProbes"] = {
            "claude-code": _classify_auth(sections.get("auth_claude", ""), "claude-code"),
            "grok-build": _classify_auth(sections.get("auth_grok", ""), "grok-build"),
            "kimi-code": _classify_auth(sections.get("auth_kimi", ""), "kimi-code"),
            "binaries": sections.get("which", ""),
            "versions": sections.get("versions", ""),
        }

        for runtime, probe_info in receipt["nasAuthProbes"].items():
            if runtime in {"binaries", "versions"}:
                continue
            if not probe_info.get("authenticated"):
                for cmd in probe_info.get("blockerCommands") or []:
                    if cmd not in receipt["remainingHumanAuthSteps"]:
                        receipt["remainingHumanAuthSteps"].append(cmd)
                receipt["proofs"].setdefault(
                    runtime if runtime != "kimi-code" else "kimi-code",
                    {"chat": "blocked_auth", "orchestration": "blocked_auth"},
                )
                if runtime in receipt["proofs"]:
                    receipt["proofs"][runtime] = {
                        "chat": "blocked_auth",
                        "orchestration": "blocked_auth",
                    }

        # OpenCode binary may exist without managed-cli auth probes.
        versions = sections.get("versions", "")
        which = sections.get("which", "")
        if "opencode" not in which and "opencode" not in versions.lower():
            receipt["proofs"]["opencode"] = {
                "chat": "blocked_missing_or_unverified_binary",
                "orchestration": "blocked_missing_or_unverified_binary",
            }
            receipt["blockerSummary"].append(
                "OpenCode binary not clearly present on PATH in NAS probe; verify opencode install separately."
            )
        else:
            # Auth for OpenCode is provider-dependent; mark as attempted-blocked until live turn succeeds.
            receipt["proofs"]["opencode"] = {
                "chat": "blocked_pending_live_turn",
                "orchestration": "blocked_pending_live_turn",
                "note": "Binary/version seen; full chat/orchestration turn not completed in this non-interactive pass.",
            }

        doctor = receipt.get("doctor") or {}
        managed = doctor.get("managedCliDetected") or {}
        auth = doctor.get("managedCliAuthentication") or {}
        if doctor.get("ready") and managed.get("claude-code") and managed.get("grok-build"):
            receipt["verified"] = {
                "doctorReady": True,
                "managedCliDetected": managed,
                "managedCliAuthentication": auth,
            }
        else:
            receipt["verified"] = {
                "doctorReady": bool(doctor.get("ready")),
                "managedCliDetected": managed,
                "managedCliAuthentication": auth,
            }

        # Default remaining auth steps from doctor installPlan if probes were inconclusive.
        if not receipt["remainingHumanAuthSteps"]:
            for line in doctor.get("installPlan") or []:
                lower = line.lower()
                if "claude auth login" in lower or "kimi login" in lower or "grok login" in lower:
                    receipt["remainingHumanAuthSteps"].append(line)

        # Always include canonical blocker commands called out by Phase A.
        for cmd in [
            "claude auth login",
            "grok login --device-auth  # or export XAI_API_KEY=...",
            "kimi login",
        ]:
            # Only keep if that runtime is not authenticated.
            key = "claude-code" if cmd.startswith("claude") else "grok-build" if cmd.startswith("grok") else "kimi-code"
            probe_info = receipt["nasAuthProbes"].get(key) or {}
            if not probe_info.get("authenticated") and cmd not in receipt["remainingHumanAuthSteps"]:
                receipt["remainingHumanAuthSteps"].append(cmd)

        receipt["status"] = "blocked_auth"
        receipt["blockerSummary"].append(
            "Managed CLIs detected by doctor, but interactive auth is required before Chat/Orchestration live turns can succeed."
        )
        receipt["blockerSummary"].append(
            "UI Chat|Orchestration mode switch must be verified in browser; API/auth blockers prevent claiming runtime proofs."
        )
    except Exception as exc:  # noqa: BLE001
        receipt["status"] = "blocked"
        receipt["error"] = str(exc)
        receipt["blockerSummary"].append(f"NAS SSH probe failed: {exc}")
    finally:
        if client is not None:
            client.close()

    # Never store password.
    receipt.pop("password", None)
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"receipt": str(receipt_path), "status": receipt["status"], "remainingHumanAuthSteps": receipt["remainingHumanAuthSteps"]}, indent=2))
    return 0 if receipt["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
