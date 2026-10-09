#!/usr/bin/env python3
"""Install and start CLIProxyAPI on the Neyvia NAS runtime host.

Uses .agent_control/nas_codex2_100_125_54_118.json (same pattern as pull_nas_tree.py).
Writes install/OAuth receipts under .agent_control/nas_transfers/.

Does not run classical Anthropic `claude auth login`. Codex OAuth is driven with
`--codex-login --no-browser` when possible; remaining browser click steps are
recorded in the receipt for the operator.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS_PATH = ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"
RECEIPT_DIR = ROOT / ".agent_control" / "nas_transfers"
DEFAULT_RUNTIME_ROOT = "/volume1/Saclay/runtime"
DEFAULT_PORT = 8317
RELEASE_TAG = "v7.2.142"
# Synology DSM often needs the portable no-plugin build.
ASSET_NAME = "CLIProxyAPI_7.2.142_linux_amd64_no-plugin.tar.gz"
ASSET_URL = (
    f"https://github.com/router-for-me/CLIProxyAPI/releases/download/"
    f"{RELEASE_TAG}/{ASSET_NAME}"
)
CHECKSUMS_URL = (
    f"https://github.com/router-for-me/CLIProxyAPI/releases/download/"
    f"{RELEASE_TAG}/checksums.txt"
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_credentials() -> dict:
    payload = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    return {
        "host": payload.get("host", "192.0.2.10"),
        "port": int(payload.get("port", 22)),
        "username": payload.get("username") or payload.get("user") or "nas-user",
        "password": payload.get("password") or payload.get("secret") or "",
        "remoteRoot": payload.get("remoteRoot") or "/volume1/Saclay/projects",
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


def _run(client: paramiko.SSHClient, command: str, *, timeout: int = 600) -> dict:
    started = time.time()
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return {
        "command": command[:500],
        "exitCode": code,
        "stdout": out[-16000:],
        "stderr": err[-4000:],
        "elapsedSec": round(time.time() - started, 2),
    }


def _remote_script(api_token: str, port: int) -> str:
    # Keep remote Python self-contained; no local f-string nesting surprises.
    return f"""
import hashlib, json, os, pathlib, shutil, subprocess, tarfile, urllib.request

runtime = pathlib.Path({DEFAULT_RUNTIME_ROOT!r})
bin_dir = runtime / "bin"
cfg_dir = runtime / "cliproxyapi"
home = runtime / "home"
auth_dir = home / ".cli-proxy-api"
bin_dir.mkdir(parents=True, exist_ok=True)
cfg_dir.mkdir(parents=True, exist_ok=True)
auth_dir.mkdir(parents=True, exist_ok=True)
home.mkdir(parents=True, exist_ok=True)

asset = {ASSET_NAME!r}
url = {ASSET_URL!r}
checksums_url = {CHECKSUMS_URL!r}
tarball = cfg_dir / asset
if not tarball.exists() or tarball.stat().st_size < 1_000_000:
    print("downloading", url)
    req = urllib.request.Request(url, headers={{"User-Agent": "neyvia-cliproxy-install"}})
    with urllib.request.urlopen(req, timeout=180) as resp, tarball.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    print("downloaded", tarball, tarball.stat().st_size)
else:
    print("reuse", tarball, tarball.stat().st_size)

checksums_req = urllib.request.Request(
    checksums_url,
    headers={{"User-Agent": "neyvia-cliproxy-install"}},
)
with urllib.request.urlopen(checksums_req, timeout=60) as resp:
    checksums = resp.read().decode("utf-8", "replace")
expected = next(
    (line.split()[0].lower() for line in checksums.splitlines() if line.strip().endswith(asset)),
    "",
)
actual = hashlib.sha256(tarball.read_bytes()).hexdigest().lower()
if not expected or actual != expected:
    raise SystemExit("CLIProxyAPI release checksum verification failed")
print("verified sha256", actual)

extract = cfg_dir / "extract"
if extract.exists():
    shutil.rmtree(extract)
extract.mkdir(parents=True, exist_ok=True)
with tarfile.open(tarball, "r:gz") as tar:
    tar.extractall(extract)

candidates = list(extract.rglob("cli-proxy-api")) + list(extract.rglob("cliproxyapi"))
if not candidates:
    raise SystemExit("binary not found in archive")
src = candidates[0]
dst = bin_dir / "cli-proxy-api"
shutil.copy2(src, dst)
os.chmod(dst, 0o755)
# Convenience alias used by some docs/wrappers.
alias = bin_dir / "cliproxyapi"
if alias.exists() or alias.is_symlink():
    try:
        alias.unlink()
    except OSError:
        pass
try:
    alias.symlink_to(dst.name)
except OSError:
    shutil.copy2(dst, alias)
    os.chmod(alias, 0o755)
print("installed", dst, "->", dst.stat().st_size)

api_token = {api_token!r}
port = {port}
config_path = cfg_dir / "config.yaml"
config_path.write_text(
    "port: " + str(port) + "\\n"
    "host: 127.0.0.1\\n"
    "debug: false\\n"
    "api-keys:\\n"
    "  - \\"" + api_token + "\\"\\n"
    "remote-management:\\n"
    "  allow-remote: false\\n",
    encoding="utf-8",
)
print("wrote", config_path)

# Stop any prior listener on the target port (best effort).
subprocess.run(
    "pkill -f 'cli-proxy-api.*config.yaml' || true",
    shell=True,
    check=False,
)
env = os.environ.copy()
env["HOME"] = str(home)
env["PATH"] = str(bin_dir) + ":" + env.get("PATH", "")
log_path = cfg_dir / "cliproxyapi.log"
pid_path = cfg_dir / "cliproxyapi.pid"
log_fh = open(log_path, "ab", buffering=0)
proc = subprocess.Popen(
    [str(dst), "-config", str(config_path)],
    cwd=str(cfg_dir),
    env=env,
    stdout=log_fh,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
pid_path.write_text(str(proc.pid), encoding="utf-8")
print("started pid", proc.pid)

# Health probe
import time, urllib.error
ok = False
body = ""
for _ in range(20):
    time.sleep(0.5)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{{port}}/",
            headers={{"User-Agent": "neyvia-cliproxy-health"}},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read(200).decode("utf-8", "replace")
            ok = resp.status < 500
            if ok:
                break
    except Exception as exc:
        body = str(exc)
print(json.dumps({{"healthOk": ok, "healthBody": body[:300], "port": port, "pid": proc.pid}}))
"""


def main() -> int:
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    receipt_path = RECEIPT_DIR / f"nas_cliproxyapi_install_{stamp}.json"
    api_token = f"claudex-{secrets.token_hex(16)}"
    port = int(os.environ.get("CLIPROXY_PORT", str(DEFAULT_PORT)))

    receipt: dict = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "goal": "Install CLIProxyAPI for Claude Code -> Codex (claudex)",
        "proxyPort": port,
        "proxyUrl": f"http://127.0.0.1:{port}",
        "anthropicBaseUrl": f"http://127.0.0.1:{port}",
        "releaseTag": RELEASE_TAG,
        "asset": ASSET_NAME,
        "runtimeRoot": DEFAULT_RUNTIME_ROOT,
        "steps": [],
        "oauth": {"status": "not_started", "loginUrl": None, "operatorSteps": []},
        "status": "started",
        "openCodeGoNote": "OpenCodeGo auth left untouched.",
        "apiTokenEnv": "CLIPROXY_API_KEY",
    }

    if not CREDENTIALS_PATH.exists():
        receipt["status"] = "blocked"
        receipt["error"] = f"Missing credentials file: {CREDENTIALS_PATH}"
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        return 2

    credentials = _load_credentials()
    if not credentials["password"]:
        receipt["status"] = "blocked"
        receipt["error"] = "Credentials file has no password/secret."
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        return 2

    try:
        client = _connect(credentials)
    except Exception as exc:  # noqa: BLE001
        receipt["status"] = "blocked"
        receipt["error"] = f"SSH connect failed: {type(exc).__name__}: {exc}"
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        return 3

    try:
        probe = _run(
            client,
            "uname -a && id && which python3 || which python || true; "
            f"ls -la {DEFAULT_RUNTIME_ROOT}/bin 2>/dev/null | head -40 || true",
            timeout=60,
        )
        receipt["steps"].append({"name": "ssh_probe", **probe})

        install = _run(
            client,
            "python3 - <<'PY'\n" + _remote_script(api_token, port) + "\nPY",
            timeout=420,
        )
        install["command"] = "install checksum-verified CLIProxyAPI release in private NAS runtime"
        receipt["steps"].append({"name": "install_and_start", **install})
        if install["exitCode"] != 0:
            receipt["status"] = "failed"
            receipt["error"] = "Remote install/start failed"
            receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            print(json.dumps(receipt, indent=2))
            return 4

        # Persist token for runtime env overlay (no Anthropic classic login).
        token_write = _run(
            client,
            (
                f"mkdir -p '{DEFAULT_RUNTIME_ROOT}/home' && "
                f"umask 077 && "
                f"printf '%s\\n' "
                f"'# Generated by nas_install_cliproxyapi.py' "
                f"'CLIPROXY_API_KEY={api_token}' "
                f"'ANTHROPIC_AUTH_TOKEN={api_token}' "
                f"'ANTHROPIC_BASE_URL=http://127.0.0.1:{port}' "
                f"'CLAUDE_CODE_SUBAGENT_MODEL=gpt-5.6-sol' "
                f"'CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1' "
                f"'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1' "
                f"'FLUXIO_HARNESS_COMPAT=cliproxy' "
                f"> '{DEFAULT_RUNTIME_ROOT}/home/.fluxio_cliproxy_env' && "
                f"ls -la '{DEFAULT_RUNTIME_ROOT}/home/.fluxio_cliproxy_env' && "
                f"test -x '{DEFAULT_RUNTIME_ROOT}/bin/cli-proxy-api' && "
                f"'{DEFAULT_RUNTIME_ROOT}/bin/cli-proxy-api' --version 2>&1 | head -5 || true"
            ),
            timeout=60,
        )
        token_write["command"] = "write private CLIProxyAPI runtime environment"
        receipt["steps"].append({"name": "write_runtime_env", **token_write})

        # Attempt Codex OAuth without opening a browser on the NAS.
        oauth = _run(
            client,
            (
                f"export HOME='{DEFAULT_RUNTIME_ROOT}/home'; "
                f"export PATH='{DEFAULT_RUNTIME_ROOT}/bin':$PATH; "
                f"cd '{DEFAULT_RUNTIME_ROOT}/cliproxyapi'; "
                f"timeout 25 '{DEFAULT_RUNTIME_ROOT}/bin/cli-proxy-api' "
                f"-config '{DEFAULT_RUNTIME_ROOT}/cliproxyapi/config.yaml' "
                f"-codex-login -no-browser 2>&1 || true; "
                f"ls -la '{DEFAULT_RUNTIME_ROOT}/home/.cli-proxy-api' 2>/dev/null || true"
            ),
            timeout=90,
        )
        receipt["steps"].append({"name": "codex_oauth_no_browser", **oauth})
        login_url = None
        for line in (oauth.get("stdout") or "").splitlines():
            if "http://" in line or "https://" in line:
                for token in line.split():
                    if token.startswith("http://") or token.startswith("https://"):
                        login_url = token.strip().rstrip(").,;")
                        break
            if login_url:
                break

        auth_files = _run(
            client,
            f"ls -la '{DEFAULT_RUNTIME_ROOT}/home/.cli-proxy-api' 2>/dev/null; "
            f"find '{DEFAULT_RUNTIME_ROOT}/home/.cli-proxy-api' -maxdepth 2 -type f 2>/dev/null | head -40",
            timeout=30,
        )
        receipt["steps"].append({"name": "auth_dir_listing", **auth_files})
        has_auth = "json" in (auth_files.get("stdout") or "").lower()

        if has_auth:
            receipt["oauth"]["status"] = "completed_or_present"
        else:
            receipt["oauth"]["status"] = "needs_browser"
            receipt["oauth"]["loginUrl"] = login_url
            receipt["oauth"]["operatorSteps"] = [
                "On a machine that can open a browser (Windows PC is fine), SSH-tunnel the NAS OAuth callback if needed:",
                f"  ssh -L 1455:127.0.0.1:1455 {credentials['username']}@{credentials['host']}",
                "On the NAS (or via the same SSH session), re-run:",
                f"  export HOME={DEFAULT_RUNTIME_ROOT}/home",
                f"  export PATH={DEFAULT_RUNTIME_ROOT}/bin:$PATH",
                f"  cli-proxy-api -config {DEFAULT_RUNTIME_ROOT}/cliproxyapi/config.yaml -codex-login",
                "Browser steps:",
                "  1. Open the printed OpenAI/ChatGPT login URL (or the one captured in this receipt).",
                "  2. Sign in with the ChatGPT/Codex account that owns the subscription.",
                "  3. If prompted, pick the correct workspace (Personal / Team / Business).",
                "  4. Approve access for CLIProxyAPI / Codex.",
                "  5. Wait for the local callback on port 1455 to complete (page usually says success).",
                "  6. Confirm ~/.cli-proxy-api (runtime home) contains a new *.json auth file.",
                "  7. Restart the proxy if it was stopped for login, then: curl -s http://127.0.0.1:8317/v1/models -H \"Authorization: Bearer $CLIPROXY_API_KEY\"",
                "Do NOT run `claude auth login` — Claude Code talks only to ANTHROPIC_BASE_URL on the local proxy.",
            ]

        health = _run(
            client,
            f"curl -s -o /tmp/cliproxy_health.body -w '%{{http_code}}' http://127.0.0.1:{port}/ || true; "
            f"echo; head -c 200 /tmp/cliproxy_health.body 2>/dev/null; echo; "
            f"ss -ltnp 2>/dev/null | grep ':{port}' || netstat -ltnp 2>/dev/null | grep ':{port}' || true",
            timeout=30,
        )
        receipt["steps"].append({"name": "local_health", **health})
        receipt["status"] = "installed" if install["exitCode"] == 0 else "failed"
        receipt["neyviaLaunch"] = {
            "harnessProfileId": "claude-code-claudex",
            "env": {
                "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}",
                "ANTHROPIC_AUTH_TOKEN": "(from CLIPROXY_API_KEY / runtime .fluxio_cliproxy_env)",
                "CLAUDE_CODE_SUBAGENT_MODEL": "gpt-5.6-sol",
                "CLAUDE_CODE_ALWAYS_ENABLE_EFFORT": "1",
                "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
            },
            "windowsWrapper": "scripts/claudex.cmd",
            "note": "When Claude Code runs on the NAS worker, ANTHROPIC_BASE_URL must point at the NAS-local proxy. For Windows-local Claude, run CLIProxyAPI on Windows or tunnel port 8317.",
        }
    finally:
        client.close()

    # Local sidecar for Windows wrappers (same token as NAS config).
    local_env = ROOT / ".agent_control" / "cliproxy_local.env"
    local_env.write_text(
        "\n".join(
            [
                f"CLIPROXY_PORT={port}",
                f"CLIPROXY_API_KEY={api_token}",
                f"ANTHROPIC_AUTH_TOKEN={api_token}",
                f"ANTHROPIC_BASE_URL=http://127.0.0.1:{port}",
                "CLAUDE_CODE_SUBAGENT_MODEL=gpt-5.6-sol",
                "CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1",
                "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1",
                "FLUXIO_HARNESS_COMPAT=cliproxy",
                "",
            ]
        ),
        encoding="utf-8",
    )
    receipt["localEnvFile"] = str(local_env.as_posix())
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    print(f"receipt={receipt_path}")
    return 0 if receipt.get("status") == "installed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
