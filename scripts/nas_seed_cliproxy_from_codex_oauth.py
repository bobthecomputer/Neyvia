#!/usr/bin/env python3
"""Seed CLIProxyAPI Codex auth from existing Neyvia/Fluxio OpenAI Codex OAuth tokens.

Neyvia missions document authPath=\"OpenAI Codex OAuth\" (browser redirect → ~/.codex/auth.json),
NOT device-code / signing-letter login. This script:

1. Loads tokens from local ~/.codex/auth.json (or NAS runtime home / OpenClaw auth-profiles)
2. Writes CLIProxyAPI CodexTokenStorage JSON under runtime home/.cli-proxy-api/
3. Restarts or pokes the proxy and verifies /v1/models is non-empty

Uses .agent_control/nas_codex2_100_125_54_118.json. Never prints secret token values.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paramiko

ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS_PATH = ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"
RECEIPT_DIR = ROOT / ".agent_control" / "nas_transfers"
RUNTIME = "/volume1/Saclay/runtime"
PORT = 8317


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_nas_credentials() -> dict[str, Any]:
    raw = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    return {
        "host": raw.get("host") or "192.0.2.10",
        "port": int(raw.get("port") or 22),
        "username": raw.get("username") or raw.get("user") or "nas-user",
        "password": raw.get("password") or raw.get("secret") or "",
    }


def _connect(creds: dict[str, Any]) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=creds["host"],
        port=creds["port"],
        username=creds["username"],
        password=creds["password"],
        look_for_keys=False,
        allow_agent=False,
        timeout=25,
    )
    return client


def _run(client: paramiko.SSHClient, cmd: str, timeout: int = 120) -> dict[str, Any]:
    started = time.time()
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return {
        "command": cmd[:900],
        "exitCode": code,
        "stdout": out[-25000:],
        "stderr": err[-4000:],
        "elapsedSec": round(time.time() - started, 2),
    }


def _extract_tokens_from_codex_auth(payload: dict[str, Any]) -> dict[str, str] | None:
    tokens = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else payload
    if not isinstance(tokens, dict):
        return None
    access = str(
        tokens.get("access_token")
        or tokens.get("access")
        or tokens.get("accessToken")
        or ""
    ).strip()
    refresh = str(
        tokens.get("refresh_token")
        or tokens.get("refresh")
        or tokens.get("refreshToken")
        or ""
    ).strip()
    id_token = str(
        tokens.get("id_token") or tokens.get("idToken") or tokens.get("id") or ""
    ).strip()
    account_id = str(
        tokens.get("account_id")
        or tokens.get("accountId")
        or payload.get("account_id")
        or ""
    ).strip()
    if not access or not refresh:
        return None
    return {
        "access_token": access,
        "refresh_token": refresh,
        "id_token": id_token,
        "account_id": account_id,
        "last_refresh": str(payload.get("last_refresh") or ""),
        "email": str(payload.get("email") or ""),
    }


def _extract_from_openclaw_profiles(payload: dict[str, Any]) -> dict[str, str] | None:
    profiles = payload.get("profiles") if isinstance(payload.get("profiles"), dict) else payload
    if not isinstance(profiles, dict):
        return None
    for _pid, cred in profiles.items():
        if not isinstance(cred, dict):
            continue
        provider = str(cred.get("provider") or cred.get("type") or _pid or "").lower()
        if "codex" not in provider and "openai" not in provider:
            # Still try if tokens look like oauth
            pass
        access = str(cred.get("access") or cred.get("access_token") or "").strip()
        refresh = str(cred.get("refresh") or cred.get("refresh_token") or "").strip()
        if access and refresh and ("codex" in provider or "openai" in provider or cred.get("id_token")):
            return {
                "access_token": access,
                "refresh_token": refresh,
                "id_token": str(cred.get("id_token") or cred.get("idToken") or "").strip(),
                "account_id": str(cred.get("accountId") or cred.get("account_id") or "").strip(),
                "last_refresh": "",
                "email": str(cred.get("email") or "").strip(),
            }
    return None


def _to_cliproxy_auth(tokens: dict[str, str]) -> dict[str, Any]:
    return {
        "id_token": tokens.get("id_token") or "",
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "account_id": tokens.get("account_id") or "",
        "last_refresh": tokens.get("last_refresh")
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "email": tokens.get("email") or "",
        "type": "codex",
        "expired": "",
    }


def _load_local_token_candidates() -> list[tuple[str, dict[str, str]]]:
    found: list[tuple[str, dict[str, str]]] = []
    home = Path.home()
    candidates = [
        ("local:~/.codex/auth.json", home / ".codex" / "auth.json"),
        (
            "local:~/.openclaw/agents/main/agent/auth-profiles.json",
            home / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json",
        ),
    ]
    for label, path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        tokens = _extract_tokens_from_codex_auth(payload) or _extract_from_openclaw_profiles(payload)
        if tokens:
            found.append((label, tokens))
    return found


def _read_api_token(client: paramiko.SSHClient) -> str:
    cfg = _run(client, f"cat {RUNTIME}/cliproxyapi/config.yaml")
    match = re.search(r'api-keys:\s*\n\s*-\s*"([^"]+)"', cfg.get("stdout") or "")
    if match:
        return match.group(1)
    env = _run(client, f"grep CLIPROXY_API_KEY {RUNTIME}/home/.fluxio_cliproxy_env 2>/dev/null || true")
    match2 = re.search(r"CLIPROXY_API_KEY=(.+)", env.get("stdout") or "")
    return (match2.group(1).strip() if match2 else "")


def main() -> int:
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    receipt_path = RECEIPT_DIR / f"nas_cliproxy_seed_codex_oauth_{stamp}.json"
    receipt: dict[str, Any] = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "goal": "Seed CLIProxyAPI from existing Neyvia OpenAI Codex OAuth tokens (NOT device-code)",
        "authMethodDocumentedBy": [
            ".agent_control/missions.json provider_runtime_truth.authPath=OpenAI Codex OAuth",
            "docs/OPENCODEGO_PROVIDER_SETUP.md (API key sibling path; Codex uses browser OAuth)",
            "scripts/nas_install_cliproxyapi.py primary path: -codex-login + localhost:1455",
            "src/grant_agent/codex_local_oauth_helper.py (Fluxio browser callback relay)",
        ],
        "deprecated": [
            "cli-proxy-api -codex-device-login",
            "auth.openai.com/codex/device signing letters",
        ],
        "sourceCandidates": [],
        "steps": [],
        "status": "started",
        "modelsNonEmpty": False,
        "openCodeGoNote": "OpenCodeGo OPENCODE_API_KEY / provider_secrets left untouched.",
    }

    local_hits = _load_local_token_candidates()
    receipt["sourceCandidates"] = [label for label, _ in local_hits]

    creds = _load_nas_credentials()
    if not creds["password"]:
        receipt["status"] = "failed"
        receipt["error"] = "Missing NAS password in credentials file"
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in receipt.items() if k != "seededAuthPreview"}, indent=2))
        print(f"receipt={receipt_path}")
        return 2

    client = _connect(creds)
    try:
        # Probe NAS for existing Codex OAuth stores (Neyvia runtime home + OpenClaw).
        probe = _run(
            client,
            (
                f"export HOME={RUNTIME}/home; "
                "python3 - <<'PY'\n"
                "import json, pathlib\n"
                f"home = pathlib.Path('{RUNTIME}/home')\n"
                "paths = [\n"
                "  home / '.codex' / 'auth.json',\n"
                "  home / '.openclaw' / 'agents' / 'main' / 'agent' / 'auth-profiles.json',\n"
                "  pathlib.Path('/volume1/Saclay/projects/syntelos/runtime/home') / '.codex' / 'auth.json',\n"
                "  pathlib.Path('/volume1/Saclay/projects/syntelos/runtime/home') / '.openclaw' / 'agents' / 'main' / 'agent' / 'auth-profiles.json',\n"
                "]\n"
                "out = []\n"
                "for p in paths:\n"
                "  item = {'path': str(p), 'exists': p.is_file(), 'keys': [], 'usable': False}\n"
                "  if p.is_file():\n"
                "    try:\n"
                "      data = json.loads(p.read_text(encoding='utf-8'))\n"
                "      item['keys'] = sorted(list(data.keys()))[:20]\n"
                "      tokens = data.get('tokens') if isinstance(data.get('tokens'), dict) else {}\n"
                "      if isinstance(tokens, dict) and tokens.get('access_token') and tokens.get('refresh_token'):\n"
                "        item['usable'] = True\n"
                "        item['kind'] = 'codex_auth_json'\n"
                "      elif isinstance(data.get('profiles'), dict):\n"
                "        for pid, cred in data['profiles'].items():\n"
                "          if not isinstance(cred, dict): continue\n"
                "          prov = str(cred.get('provider') or pid).lower()\n"
                "          if ('codex' in prov or 'openai' in prov) and (cred.get('access') or cred.get('access_token')) and (cred.get('refresh') or cred.get('refresh_token')):\n"
                "            item['usable'] = True\n"
                "            item['kind'] = 'openclaw_profiles'\n"
                "            break\n"
                "    except Exception as exc:\n"
                "      item['error'] = type(exc).__name__\n"
                "  out.append(item)\n"
                "print(json.dumps(out))\n"
                "PY"
            ),
            timeout=60,
        )
        receipt["steps"].append(
            {
                "name": "probe_nas_codex_stores",
                "exitCode": probe["exitCode"],
                "elapsedSec": probe["elapsedSec"],
                "stdout": probe.get("stdout", "")[-4000:],
                "stderr": probe.get("stderr", "")[-1000:],
            }
        )

        nas_usable: list[dict[str, Any]] = []
        try:
            nas_usable = json.loads((probe.get("stdout") or "").strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            nas_usable = []
        receipt["nasAuthStores"] = [
            {k: v for k, v in item.items() if k in {"path", "exists", "keys", "usable", "kind", "error"}}
            for item in nas_usable
        ]

        tokens: dict[str, str] | None = None
        source_label = ""

        # Prefer converting an existing NAS Neyvia/Syntelos Codex OAuth store in place
        # (no token pipe over SSH stdin — heredoc would swallow it).
        nas_source_path = ""
        for item in nas_usable:
            if item.get("usable") and item.get("kind") == "codex_auth_json":
                nas_source_path = str(item["path"])
                break

        if nas_source_path:
            source_label = f"nas:{nas_source_path}"
            convert = _run(
                client,
                (
                    "python3 - <<'PY'\n"
                    "import json, pathlib\n"
                    f"src = pathlib.Path({nas_source_path!r})\n"
                    f"dst_dir = pathlib.Path('{RUNTIME}/home/.cli-proxy-api')\n"
                    f"dst = dst_dir / 'codex-{stamp}.json'\n"
                    "data = json.loads(src.read_text(encoding='utf-8'))\n"
                    "tok = data.get('tokens') if isinstance(data.get('tokens'), dict) else {}\n"
                    "access = str(tok.get('access_token') or tok.get('access') or '').strip()\n"
                    "refresh = str(tok.get('refresh_token') or tok.get('refresh') or '').strip()\n"
                    "id_token = str(tok.get('id_token') or tok.get('idToken') or '').strip()\n"
                    "account_id = str(tok.get('account_id') or tok.get('accountId') or '').strip()\n"
                    "if not access or not refresh:\n"
                    "  raise SystemExit('missing access/refresh in source auth.json')\n"
                    "dst_dir.mkdir(parents=True, exist_ok=True)\n"
                    "out = {\n"
                    "  'id_token': id_token,\n"
                    "  'access_token': access,\n"
                    "  'refresh_token': refresh,\n"
                    "  'account_id': account_id,\n"
                    "  'last_refresh': str(data.get('last_refresh') or ''),\n"
                    "  'email': str(data.get('email') or ''),\n"
                    "  'type': 'codex',\n"
                    "  'expired': '',\n"
                    "}\n"
                    "dst.write_text(json.dumps(out, indent=2), encoding='utf-8')\n"
                    "try:\n"
                    "  dst.chmod(0o600)\n"
                    "except OSError:\n"
                    "  pass\n"
                    f"mirror = pathlib.Path('{RUNTIME}/home/.codex/auth.json')\n"
                    "mirror.parent.mkdir(parents=True, exist_ok=True)\n"
                    "if not mirror.exists():\n"
                    "  mirror.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')\n"
                    "print(json.dumps({'wrote': str(dst), 'bytes': dst.stat().st_size, 'fields': sorted([k for k,v in out.items() if v])}))\n"
                    "PY"
                ),
                timeout=60,
            )
            receipt["steps"].append(
                {
                    "name": "convert_nas_codex_auth_to_cliproxy",
                    "exitCode": convert["exitCode"],
                    "elapsedSec": convert["elapsedSec"],
                    "stdout": (convert.get("stdout") or "")[-2000:],
                    "stderr": (convert.get("stderr") or "")[-2000:],
                    "source": nas_source_path,
                }
            )
            if convert["exitCode"] != 0:
                receipt["status"] = "failed_convert_nas_auth"
                receipt["error"] = "NAS-side convert of existing Codex OAuth failed"
                receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
                print(json.dumps(receipt, indent=2))
                print(f"receipt={receipt_path}")
                return 4
            receipt["tokenSource"] = source_label
            try:
                meta = json.loads((convert.get("stdout") or "").strip().splitlines()[-1])
                receipt["tokenFieldsPresent"] = meta.get("fields") or []
                remote_path = str(meta.get("wrote") or f"{RUNTIME}/home/.cli-proxy-api/codex-{stamp}.json")
            except (json.JSONDecodeError, IndexError):
                remote_path = f"{RUNTIME}/home/.cli-proxy-api/codex-{stamp}.json"
                receipt["tokenFieldsPresent"] = ["access_token", "refresh_token", "type"]
        else:
            # Fall back to local ~/.codex/auth.json via base64 (avoids heredoc eating stdin).
            if local_hits:
                source_label, tokens = local_hits[0]
            if not tokens:
                api_token = _read_api_token(client)
                health = _run(
                    client,
                    (
                        f"curl -s -o /tmp/cpa_h.body -w '%{{http_code}}' http://127.0.0.1:{PORT}/ || true; echo; "
                        f"curl -s http://127.0.0.1:{PORT}/v1/models -H 'Authorization: Bearer {api_token}' | head -c 300; echo; "
                        f"ls -la {RUNTIME}/home/.cli-proxy-api 2>/dev/null || true"
                    ),
                )
                receipt["steps"].append({"name": "health_without_seed", **health})
                receipt["status"] = "blocked_no_existing_codex_oauth_tokens"
                receipt["operatorSteps"] = [
                    "Neyvia auth method for Codex is OpenAI Codex OAuth (browser redirect), same as Fluxio Tools/accounts.",
                    "Complete ONE browser OAuth (no device code / no signing letters):",
                    f"  ssh -L 1455:127.0.0.1:1455 {creds['username']}@{creds['host']}",
                    f"  export HOME={RUNTIME}/home PATH={RUNTIME}/bin:$PATH",
                    f"  cli-proxy-api -config {RUNTIME}/cliproxyapi/config.yaml -codex-login",
                    "  Open the printed https://auth.openai.com/oauth/authorize URL, approve, wait for localhost:1455 success.",
                    "Or: run Fluxio start_openai_codex_oauth_command (writes ~/.codex/auth.json), then re-run this script.",
                    "Do NOT use -codex-device-login.",
                ]
                receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
                print(json.dumps(receipt, indent=2))
                print(f"receipt={receipt_path}")
                return 3

            import base64

            auth_payload = _to_cliproxy_auth(tokens)
            receipt["tokenSource"] = source_label
            receipt["tokenFieldsPresent"] = sorted(
                [k for k, v in auth_payload.items() if v not in ("", None)]
            )
            remote_path = f"{RUNTIME}/home/.cli-proxy-api/codex-{stamp}.json"
            b64 = base64.b64encode(json.dumps(auth_payload).encode("utf-8")).decode("ascii")
            write_remote = _run(
                client,
                (
                    "python3 - <<'PY'\n"
                    "import base64, json, pathlib\n"
                    f"raw = base64.b64decode({b64!r})\n"
                    "payload = json.loads(raw.decode('utf-8'))\n"
                    f"path = pathlib.Path({remote_path!r})\n"
                    "path.parent.mkdir(parents=True, exist_ok=True)\n"
                    "path.write_text(json.dumps(payload, indent=2), encoding='utf-8')\n"
                    "try:\n"
                    "  path.chmod(0o600)\n"
                    "except OSError:\n"
                    "  pass\n"
                    "print('wrote', path, 'bytes', path.stat().st_size)\n"
                    "PY"
                ),
                timeout=60,
            )
            receipt["steps"].append(
                {
                    "name": "wrote_cliproxy_auth_from_local",
                    "exitCode": write_remote["exitCode"],
                    "elapsedSec": write_remote["elapsedSec"],
                    "stdout": (write_remote.get("stdout") or "")[-1500:],
                    "stderr": (write_remote.get("stderr") or "")[-1500:],
                    "path": remote_path,
                    "secretValuesPrinted": False,
                }
            )
            if write_remote["exitCode"] != 0:
                receipt["status"] = "failed_write_auth"
                receipt["error"] = "Remote write of CLIProxyAPI auth JSON failed"
                receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
                print(json.dumps(receipt, indent=2))
                print(f"receipt={receipt_path}")
                return 4

        # Prefer file-watcher reload; only start proxy if it is not listening.
        restart = _run(
            client,
            (
                f"chmod 600 '{remote_path}' 2>/dev/null || true; "
                f"ls -la {RUNTIME}/home/.cli-proxy-api; "
                f"code=$(curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{PORT}/ || true); "
                "echo health=$code; "
                "if [ \"$code\" != \"200\" ]; then "
                f"  pkill -f '{RUNTIME}/bin/cli-proxy-api' || true; sleep 1; "
                f"  export HOME={RUNTIME}/home; export PATH={RUNTIME}/bin:$PATH; "
                f"  nohup {RUNTIME}/bin/cli-proxy-api -config {RUNTIME}/cliproxyapi/config.yaml "
                f"  >> {RUNTIME}/cliproxyapi/cliproxyapi.log 2>&1 & echo $! > {RUNTIME}/cliproxyapi/cliproxyapi.pid; "
                "  sleep 3; "
                f"  ps -p $(cat {RUNTIME}/cliproxyapi/cliproxyapi.pid) -o pid,cmd || true; "
                "else "
                "  echo proxy_already_listening; "
                "  sleep 2; "
                "fi"
            ),
            timeout=60,
        )
        receipt["steps"].append({"name": "ensure_proxy", **{k: restart[k] for k in restart if k != "stdout"}, "stdout": (restart.get("stdout") or "")[-2000:]})

        api_token = _read_api_token(client)
        models = _run(
            client,
            (
                f"curl -s -o /tmp/cpa_models.body -w '%{{http_code}}' "
                f"http://127.0.0.1:{PORT}/v1/models -H 'Authorization: Bearer {api_token}'; echo; "
                "head -c 800 /tmp/cpa_models.body 2>/dev/null; echo; "
                f"tail -n 25 {RUNTIME}/cliproxyapi/cliproxyapi.log"
            ),
            timeout=40,
        )
        receipt["steps"].append(
            {
                "name": "verify_models",
                "exitCode": models["exitCode"],
                "stdout": (models.get("stdout") or "")[-3000:],
                "stderr": (models.get("stderr") or "")[-500:],
            }
        )
        body = models.get("stdout") or ""
        non_empty = False
        try:
            # Find JSON object in output
            json_start = body.find("{")
            if json_start >= 0:
                parsed = json.loads(body[json_start:].split("\n", 1)[0] if "\n" in body[json_start:] else body[json_start:])
                data = parsed.get("data") if isinstance(parsed, dict) else None
                non_empty = isinstance(data, list) and len(data) > 0
                receipt["modelsCount"] = len(data) if isinstance(data, list) else 0
                if isinstance(data, list) and data:
                    receipt["modelIdsSample"] = [
                        str(item.get("id") or item.get("name") or "")[:80]
                        for item in data[:8]
                        if isinstance(item, dict)
                    ]
        except json.JSONDecodeError:
            # Heuristic: non-empty if data array has objects
            non_empty = '"data":[]' not in body.replace(" ", "") and '"id"' in body

        receipt["modelsNonEmpty"] = bool(non_empty)
        receipt["status"] = "seeded_models_ok" if non_empty else "seeded_but_models_empty"
        receipt["neyviaLaunch"] = {
            "harnessProfileId": "claude-code-claudex",
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{PORT}",
            "docs": "docs/CLIPROXYAPI_CLAUDEX.md",
        }
        if not non_empty:
            receipt["nextSteps"] = [
                "Auth file written; if models still empty, tokens may be expired — refresh via Fluxio OpenAI Codex OAuth (browser) then re-run this script.",
                "Still do NOT use device-code login.",
            ]
    finally:
        client.close()

    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    print(f"receipt={receipt_path}")
    return 0 if receipt.get("modelsNonEmpty") else 1


if __name__ == "__main__":
    raise SystemExit(main())
