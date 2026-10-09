#!/usr/bin/env python3
"""Discover Grok Build open surfaces on the NAS runtime (protocol flags only).

Uses .agent_control/nas_codex2_100_125_54_118.json. Does not reverse-engineer
binaries or capture device-auth secrets. Writes a receipt under nas_transfers/.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import paramiko


ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS_PATH = ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"
RECEIPT_DIR = ROOT / ".agent_control" / "nas_transfers"
DEFAULT_REMOTE_ROOT = "/volume1/Saclay/projects"
DEFAULT_RUNTIME_BIN = "/volume1/Saclay/runtime/bin"
DEFAULT_PROJECT = "vibe-coding-platform"

UPLOAD_FILES = [
    "src/grant_agent/harness_registry.py",
    "src/grant_agent/external_cli_bridge.py",
    "src/grant_agent/runtimes/managed_cli.py",
    "docs/GROK_BUILD_OPEN_SURFACES.md",
]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_credentials() -> dict:
    payload = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    return {
        "host": payload.get("host", "192.0.2.10"),
        "port": int(payload.get("port", 22)),
        "username": payload.get("username") or payload.get("user") or "nas-user",
        "password": payload.get("password") or payload.get("secret") or "",
        "remoteRoot": payload.get("remoteRoot") or DEFAULT_REMOTE_ROOT,
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


def _run(client: paramiko.SSHClient, command: str, *, timeout: int = 120) -> dict:
    started = time.time()
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return {
        "command": command,
        "exitCode": code,
        "stdout": out[-12000:],
        "stderr": err[-4000:],
        "elapsedSec": round(time.time() - started, 2),
    }


def _upload_via_ssh(client: paramiko.SSHClient, local_path: Path, remote_path: str) -> dict:
    remote_dir = str(PurePosixPath(remote_path).parent)
    mkdir = _run(client, f"mkdir -p '{remote_dir}'", timeout=30)
    if mkdir["exitCode"] != 0:
        return {"ok": False, "stage": "mkdir", **mkdir}
    payload = base64.b64encode(local_path.read_bytes()).decode("ascii")
    command = (
        "python3 - <<'PY'\n"
        "import base64, pathlib\n"
        f"path = pathlib.Path({remote_path!r})\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        f"path.write_bytes(base64.b64decode({payload!r}))\n"
        "print('uploaded', path, path.stat().st_size)\n"
        "PY"
    )
    result = _run(client, command, timeout=120)
    return {"ok": result["exitCode"] == 0, "stage": "write", **result}


def main() -> int:
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    receipt_path = RECEIPT_DIR / f"nas_grok_open_surfaces_discovery_{stamp}.json"
    creds = _load_credentials()
    project_root = f"{creds['remoteRoot'].rstrip('/')}/{DEFAULT_PROJECT}"
    path_export = (
        f"export PATH='{DEFAULT_RUNTIME_BIN}:/usr/local/bin:/usr/bin:/bin:$PATH'"
    )
    receipt: dict = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "phase": "Grok-open-surfaces",
        "goal": "Discover documented Grok Build CLI surfaces; upload pluggable harness hooks",
        "host": creds["host"],
        "projectRoot": project_root,
        "steps": [],
        "operatorSteps": [],
        "ok": False,
    }

    client = _connect(creds)
    try:
        probe = _run(
            client,
            (
                f"{path_export}; "
                "command -v grok; grok --version; "
                "grok --help > /tmp/grok_help.txt 2>&1; "
                "python3 -c \"print(open('/tmp/grok_help.txt',encoding='utf-8',errors='replace').read()[:4000])\""
            ),
            timeout=60,
        )
        receipt["steps"].append({"name": "grok_help_probe", **probe})

        models = _run(
            client,
            (
                f"{path_export}; "
                "grok models > /tmp/grok_models.txt 2>&1; echo exit:$?; "
                "python3 -c \"print(open('/tmp/grok_models.txt',encoding='utf-8',errors='replace').read()[:2000])\""
            ),
            timeout=60,
        )
        receipt["steps"].append({"name": "grok_models_probe", **models})

        acp_help = _run(
            client,
            (
                f"{path_export}; "
                "(grok agent --help || grok agent stdio --help || true) > /tmp/grok_acp.txt 2>&1; "
                "python3 -c \"print(open('/tmp/grok_acp.txt',encoding='utf-8',errors='replace').read()[:2000])\""
            ),
            timeout=60,
        )
        receipt["steps"].append({"name": "grok_acp_help_probe", **acp_help})

        env_surface = _run(
            client,
            (
                f"{path_export}; "
                "python3 - <<'PY'\n"
                "import os\n"
                "keys = sorted(k for k in os.environ if k.startswith(('XAI_', 'GROK_', 'ANTHROPIC_')))\n"
                "print('env_keys_present', keys)\n"
                "print('XAI_API_KEY_set', bool(os.environ.get('XAI_API_KEY') or os.environ.get('GROK_CODE_XAI_API_KEY')))\n"
                "PY"
            ),
            timeout=30,
        )
        receipt["steps"].append({"name": "auth_env_presence_no_values", **env_surface})

        uploaded = []
        upload_errors = []
        for rel in UPLOAD_FILES:
            local = ROOT / rel
            remote = f"{project_root}/{rel}"
            if not local.is_file():
                upload_errors.append({"path": rel, "error": "missing locally"})
                continue
            result = _upload_via_ssh(client, local, remote)
            if result.get("ok"):
                uploaded.append(rel)
            else:
                upload_errors.append({"path": rel, "error": result.get("stderr") or result.get("stdout")})
        receipt["steps"].append(
            {
                "name": "upload_pluggable_hooks",
                "uploaded": uploaded,
                "errors": upload_errors,
            }
        )

        smoke = _run(
            client,
            (
                f"{path_export}; cd '{project_root}' && "
                "python3 - <<'PY'\n"
                "from pathlib import Path\n"
                "import sys\n"
                "sys.path.insert(0, 'src')\n"
                "from grant_agent.harness_registry import harness_gateway_environment, save_harness_profile\n"
                "root = Path('.')\n"
                "profile = save_harness_profile(root, {\n"
                "  'id': 'grok-open-proxy-example',\n"
                "  'harnessId': 'grok-build',\n"
                "  'baseUrl': 'http://127.0.0.1:8317/v1',\n"
                "  'credentialEnv': 'XAI_API_KEY',\n"
                "  'compatibilityMode': 'openai-compatible',\n"
                "  'model': 'open-model',\n"
                "})\n"
                "env = harness_gateway_environment(root, 'grok-build', profile['id'], {'XAI_API_KEY': 'redacted'})\n"
                "print('profile_id', profile['id'])\n"
                "print('GROK_MODELS_BASE_URL', env.get('GROK_MODELS_BASE_URL'))\n"
                "print('has_xai_key', 'XAI_API_KEY' in env)\n"
                "PY"
            ),
            timeout=60,
        )
        receipt["steps"].append({"name": "harness_profile_smoke", **smoke})

        version_seen = "grok" in (probe.get("stdout") or "").lower()
        upload_ok = bool(uploaded) and not upload_errors
        smoke_ok = smoke["exitCode"] == 0 and "GROK_MODELS_BASE_URL" in (smoke["stdout"] or "")
        receipt["ok"] = version_seen and upload_ok and smoke_ok
        receipt["discoveryNotes"] = {
            "versionSeen": version_seen,
            "modelsProbeExit": models.get("exitCode"),
            "modelsLikelyNeedsAuth": "abort" in (models.get("stderr") or "").lower()
            or "login" in (models.get("stdout") or "").lower()
            or "api" in (models.get("stdout") or "").lower(),
            "acpHelpChars": len(acp_help.get("stdout") or ""),
            "apiKeyPresentInEnv": "XAI_API_KEY_set True" in (env_surface.get("stdout") or ""),
        }
        receipt["operatorSteps"] = [
            "Export XAI_API_KEY on the NAS runtime (or point credentialEnv at a proxy key) — do not rely on grok login alone.",
            "Optional: save a harness profile with baseUrl=http://127.0.0.1:<proxy>/v1 and compatibilityMode=openai-compatible (CLIProxyAPI-style).",
            "Pass harnessProfileId on chat/mission routes, or set FLUXIO_HARNESS_PROFILE.",
            "Keep Claude proxy on a different local port if both gateways run on the same host.",
            "ACP remains capability-only until a live grok agent stdio negotiation receipt is captured.",
            "Authenticate Claude Code separately with ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL profiles if using that harness.",
        ]
    finally:
        client.close()

    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(receipt_path), "ok": receipt["ok"]}, indent=2))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
