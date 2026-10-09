#!/usr/bin/env python3
"""Configure NAS consumers for Neyvia's provider-scoped auth broker.

This script never reads, copies, or prints an upstream OAuth refresh token.
CLIProxyAPI remains the sole OpenAI Codex OAuth refresh owner. Consumers get a
loopback base URL and the proxy's local client credential through a mode-0600
environment file.
"""

from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path
from typing import Any

import paramiko


ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS_PATH = ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"
CORE_RUNTIME = "/volume1/Saclay/projects/syntelos/runtime"
PROXY_RUNTIME = "/volume1/Saclay/runtime"
DEFAULT_WORKSPACE = "/volume1/Saclay/projects/vibe-coding-platform"
MANAGED_PYTHON = f"{CORE_RUNTIME}/bin/python"


def _credentials() -> dict[str, Any]:
    payload = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    return {
        "host": payload.get("host") or "192.0.2.10",
        "port": int(payload.get("port") or 22),
        "username": payload.get("username") or payload.get("user") or "nas-user",
        "password": payload.get("password") or payload.get("secret") or "",
    }


def _connect() -> paramiko.SSHClient:
    details = _credentials()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=details["host"],
        port=details["port"],
        username=details["username"],
        password=details["password"],
        look_for_keys=False,
        allow_agent=False,
        timeout=25,
    )
    return client


def _runtime_preflight(client: paramiko.SSHClient) -> dict[str, Any]:
    command = (
        "set -eu; "
        f"test -x {MANAGED_PYTHON}; "
        f"{MANAGED_PYTHON} -c "
        "'import json,sys; print(json.dumps({"
        '"executable":sys.executable,"version":list(sys.version_info[:3])'
        "}))'; "
        f"{CORE_RUNTIME}/bin/node --version; "
        f"{PROXY_RUNTIME}/bin/node --version"
    )
    _stdin, stdout, stderr = client.exec_command(command, timeout=30)
    output = stdout.read().decode("utf-8", "replace").splitlines()
    error = stderr.read().decode("utf-8", "replace").strip()
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0 or len(output) < 3:
        raise RuntimeError(
            error or "Neyvia managed runtime preflight did not complete."
        )
    python = json.loads(output[0])
    version = tuple(int(part) for part in python.get("version", []))
    if version < (3, 10):
        raise RuntimeError(
            f"Neyvia managed Python must be >=3.10, found {version!r}."
        )
    return {
        "managedPython": python,
        "coreNode": output[1],
        "proxyNode": output[2],
        "systemPythonUsedForNeyvia": False,
    }


def _remote_python(client: paramiko.SSHClient, source: str) -> str:
    stdin, stdout, stderr = client.exec_command("python3 -", timeout=60)
    stdin.write(source)
    stdin.channel.shutdown_write()
    output = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0:
        raise RuntimeError(error.strip() or f"Remote Python exited {exit_code}.")
    return output


def _read_text(client: paramiko.SSHClient, path: str) -> str:
    encoded = _remote_python(
        client,
        (
            "import base64\n"
            "from pathlib import Path\n"
            f"print(base64.b64encode(Path({path!r}).read_bytes()).decode('ascii'))\n"
        ),
    ).strip()
    return base64.b64decode(encoded).decode("utf-8", "replace")


def _atomic_private_text(
    client: paramiko.SSHClient,
    path: str,
    content: str,
    *,
    backup: bool = True,
) -> str | None:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = f"{path}.bak.{stamp}" if backup else None
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    result = _remote_python(
        client,
        (
            "import base64\n"
            "from pathlib import Path\n"
            f"path = Path({path!r})\n"
            f"backup = Path({backup_path!r}) if {bool(backup_path)!r} else None\n"
            f"temporary = Path({(path + '.tmp.' + stamp)!r})\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            "if backup is not None and path.exists():\n"
            "    backup.write_bytes(path.read_bytes())\n"
            "    backup.chmod(0o600)\n"
            f"temporary.write_bytes(base64.b64decode({encoded!r}))\n"
            "temporary.chmod(0o600)\n"
            "temporary.replace(path)\n"
            "path.chmod(0o600)\n"
            "print('ok')\n"
        ),
    ).strip()
    if result != "ok":
        raise RuntimeError(f"Unexpected remote write result for {path}.")
    return backup_path


def _parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.removeprefix("export ").strip()] = value.strip().strip("\"'")
    return values


def _configure_env(client: paramiko.SSHClient) -> dict[str, Any]:
    path = f"{PROXY_RUNTIME}/home/.fluxio_cliproxy_env"
    existing = _parse_env(_read_text(client, path))
    if not existing.get("CLIPROXY_API_KEY"):
        raise RuntimeError("CLIProxyAPI local client credential is missing.")
    existing.pop("FLUXIO_SUBSCRIPTION_RELAY_RISK_ACCEPTED", None)
    existing.update(
        {
            "ANTHROPIC_AUTH_TOKEN": existing["CLIPROXY_API_KEY"],
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:8317",
            "OPENAI_BASE_URL": "http://127.0.0.1:8317/v1",
            "OPENAI_API_KEY": existing["CLIPROXY_API_KEY"],
            "FLUXIO_HARNESS_COMPAT": "cliproxy",
            "FLUXIO_AUTH_BROKER_PROVIDER": "openai",
            "FLUXIO_AUTH_BROKER_MODE": "codex-oauth",
            "CLAUDE_CODE_SUBAGENT_MODEL": "gpt-5.6-sol",
            "CLAUDE_CODE_ALWAYS_ENABLE_EFFORT": "1",
            "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
        }
    )
    ordered = [
        "CLIPROXY_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "CLAUDE_CODE_SUBAGENT_MODEL",
        "CLAUDE_CODE_ALWAYS_ENABLE_EFFORT",
        "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY",
        "FLUXIO_HARNESS_COMPAT",
        "FLUXIO_AUTH_BROKER_PROVIDER",
        "FLUXIO_AUTH_BROKER_MODE",
    ]
    text = "# Generated by configure_nas_provider_auth_broker.py\n"
    text += "\n".join(f"{key}={existing[key]}" for key in ordered) + "\n"
    backup = _atomic_private_text(client, path, text)
    return {
        "path": path,
        "backupPath": backup,
        "keys": ordered,
        "secretValuesPrinted": False,
    }


def _configure_openclaw(client: paramiko.SSHClient) -> dict[str, Any]:
    path = f"{CORE_RUNTIME}/home/.openclaw/openclaw.json"
    payload = json.loads(_read_text(client, path))
    models = payload.setdefault("models", {})
    providers = models.setdefault("providers", {})
    providers["neyvia-openai"] = {
        "baseUrl": "http://127.0.0.1:8317/v1",
        "apiKey": "${CLIPROXY_API_KEY}",
        "api": "openai-responses",
        "models": [
            {
                "id": "gpt-5.6-sol",
                "name": "GPT-5.6 Sol via Neyvia OpenAI broker",
                "reasoning": True,
                "input": ["text", "image"],
                "contextWindow": 200000,
                "maxTokens": 32000,
            }
        ],
    }
    backup = _atomic_private_text(
        client,
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    return {
        "path": path,
        "backupPath": backup,
        "provider": "neyvia-openai",
        "model": "neyvia-openai/gpt-5.6-sol",
        "credentialReference": "${CLIPROXY_API_KEY}",
        "secretValuesPrinted": False,
    }


def _configure_harness_profiles(
    client: paramiko.SSHClient,
    workspace: str,
) -> dict[str, Any]:
    path = f"{workspace.rstrip('/')}/.agent_control/harness_profiles.json"
    exists = json.loads(
        _remote_python(
            client,
            (
                "import json\n"
                "from pathlib import Path\n"
                f"print(json.dumps(Path({path!r}).exists()))\n"
            ),
        )
    )
    if not exists:
        return {"path": path, "present": False, "updatedProfiles": []}
    payload = json.loads(_read_text(client, path))
    updated: list[str] = []
    for profile in payload.get("profiles", []):
        if not isinstance(profile, dict):
            continue
        if str(profile.get("compatibilityMode") or "").strip().lower() != "cliproxy":
            continue
        model = str(profile.get("model") or "").strip().lower()
        if model.startswith(("gpt-", "o1", "o3", "o4")):
            profile["relayProvider"] = "openai"
            profile["relayAuthMode"] = "codex-oauth"
            profile["subscriptionRelayRiskAcceptedAt"] = ""
            profile["subscriptionRelayRiskNoticeVersion"] = ""
            updated.append(str(profile.get("id") or "unnamed"))
    backup = _atomic_private_text(
        client,
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    return {
        "path": path,
        "present": True,
        "backupPath": backup,
        "updatedProfiles": updated,
    }


def _retire_legacy_refresh_copies(client: paramiko.SSHClient) -> dict[str, Any]:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    direct_codex = f"{CORE_RUNTIME}/home/.codex/auth.json"
    retired_codex = f"{direct_codex}.retired-by-openai-broker.{stamp}"
    codex_result = json.loads(
        _remote_python(
            client,
            (
                "import json\n"
                "from pathlib import Path\n"
                f"source = Path({direct_codex!r})\n"
                f"target = Path({retired_codex!r})\n"
                "if source.exists():\n"
                "    source.replace(target)\n"
                "    target.chmod(0o600)\n"
                "    print(json.dumps({'retired': True, 'recoveryPath': str(target)}))\n"
                "else:\n"
                "    print(json.dumps({'retired': False, 'reason': 'not_present'}))\n"
            ),
        )
    )

    hermes_path = f"{CORE_RUNTIME}/home/.hermes/auth.json"
    hermes_payload = json.loads(_read_text(client, hermes_path))
    removed_hermes: list[str] = []
    for section_name in ("providers", "credential_pool"):
        section = hermes_payload.get(section_name)
        if not isinstance(section, dict):
            continue
        for provider_id in ("openai", "openai-api", "openai-codex"):
            if provider_id in section:
                section.pop(provider_id, None)
                removed_hermes.append(f"{section_name}.{provider_id}")
    hermes_backup = None
    if removed_hermes:
        hermes_backup = _atomic_private_text(
            client,
            hermes_path,
            json.dumps(hermes_payload, ensure_ascii=False, indent=2) + "\n",
        )

    sqlite_path = (
        f"{CORE_RUNTIME}/home/.openclaw/agents/main/agent/openclaw-agent.sqlite"
    )
    sqlite_result = json.loads(
        _remote_python(
            client,
            (
                "import json, shutil, sqlite3\n"
                "from pathlib import Path\n"
                f"path = Path({sqlite_path!r})\n"
                f"stamp = {stamp!r}\n"
                "result = {'present': path.exists(), 'removed': {}, 'backupPath': None}\n"
                "if path.exists():\n"
                "    backup = path.with_name(path.name + '.bak.' + stamp)\n"
                "    shutil.copy2(path, backup)\n"
                "    backup.chmod(0o600)\n"
                "    result['backupPath'] = str(backup)\n"
                "    try:\n"
                "        connection = sqlite3.connect(path)\n"
                "        try:\n"
                "            for (table,) in connection.execute(\"select name from sqlite_master where type='table'\"):\n"
                "                safe_table = table.replace('\"', '\"\"')\n"
                "                columns = [row[1] for row in connection.execute(f'pragma table_info(\"{safe_table}\")')]\n"
                "                provider_column = next((column for column in columns if column.lower() in {'provider', 'provider_id', 'providerid'}), None)\n"
                "                if not provider_column:\n"
                "                    continue\n"
                "                safe_column = provider_column.replace('\"', '\"\"')\n"
                "                cursor = connection.execute(\n"
                "                    f'delete from \"{safe_table}\" where lower(\"{safe_column}\") in (?, ?, ?)',\n"
                "                    ('openai', 'openai-api', 'openai-codex'),\n"
                "                )\n"
                "                if cursor.rowcount:\n"
                "                    result['removed'][table] = cursor.rowcount\n"
                "            connection.commit()\n"
                "        finally:\n"
                "            connection.close()\n"
                "    except Exception as error:\n"
                "        result['blockedBy'] = f'{type(error).__name__}: {error}'\n"
                "print(json.dumps(result))\n"
            ),
        )
    )
    return {
        "directCodex": codex_result,
        "hermes": {
            "removedEntries": removed_hermes,
            "backupPath": hermes_backup,
        },
        "openclaw": sqlite_result,
        "activeRefreshOwner": f"{PROXY_RUNTIME}/home/.cli-proxy-api",
        "recovery": "Every changed credential store has a timestamped recovery copy.",
    }


def _legacy_auth_inventory(client: paramiko.SSHClient) -> dict[str, Any]:
    candidates = [
        f"{CORE_RUNTIME}/home/.codex/auth.json",
        f"{CORE_RUNTIME}/home/.openclaw/agents/main/agent/auth-profiles.json",
        f"{CORE_RUNTIME}/home/.hermes/auth.json",
    ]
    present = json.loads(
        _remote_python(
            client,
            (
                "import json\n"
                "from pathlib import Path\n"
                f"paths = {candidates!r}\n"
                "print(json.dumps([path for path in paths if Path(path).exists()]))\n"
            ),
        )
    )
    return {
        "present": present,
        "activeRefreshOwner": f"{PROXY_RUNTIME}/home/.cli-proxy-api",
        "note": (
            "Legacy files are inventoried but not deleted automatically. "
            "All generated routes use the broker; direct refresh-token copying is retired."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    args = parser.parse_args(argv)
    client = _connect()
    try:
        report = {
            "schema": "neyvia.provider-auth-broker-setup/v1",
            "configuredAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "provider": "openai",
            "authMode": "codex-oauth",
            "refreshOwner": "cliproxyapi",
            "runtimePreflight": _runtime_preflight(client),
            "environment": _configure_env(client),
            "harnessProfiles": _configure_harness_profiles(client, args.workspace),
            "openclaw": _configure_openclaw(client),
            "retiredLegacyRefreshCopies": _retire_legacy_refresh_copies(client),
            "legacyAuthInventory": _legacy_auth_inventory(client),
            "anthropicPolicy": (
                "Claude Free/Pro/Max credentials are not routed through the proxy. "
                "Use official Claude login, API key, Bedrock, Vertex, Foundry, "
                "or an approved compatible gateway."
            ),
        }
    finally:
        client.close()
    serialized = json.dumps(report, indent=2)
    if args.report:
        target = args.report.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
