from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_BIN_DIRS = [
    ROOT / ".agent_control" / "runtime" / "bin",
    ROOT.parent / "runtime" / "bin",
    ROOT.parent.parent / "runtime" / "bin",
    ROOT.parent / "syntelos" / "runtime" / "bin",
]
CORE_COMMANDS = ("node", "npm", "npx", "openclaw", "hermes", "python3", "python")
OPTIONAL_AGENT_COMMANDS = ("codex", "kimi", "claude", "grok", "cli-proxy-api", "cliproxyapi")
COMMANDS = (*CORE_COMMANDS, *OPTIONAL_AGENT_COMMANDS)
DEFAULT_CLIPROXY_PORT = 8317


def runtime_path_entries(extra_bin_dir: list[str] | None = None) -> list[str]:
    candidates = [Path(value) for value in extra_bin_dir or [] if value]
    candidates.extend(DEFAULT_RUNTIME_BIN_DIRS)
    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.exists():
            continue
        value = str(candidate.resolve())
        if value in seen:
            continue
        output.append(value)
        seen.add(value)
    return output


def runtime_env(extra_bin_dir: list[str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    path_entries = runtime_path_entries(extra_bin_dir)
    if path_entries:
        env["PATH"] = os.pathsep.join([*path_entries, env.get("PATH", "")])
    # Load cliproxy / provider overlays from adjacent runtime homes when present.
    for bin_dir in path_entries:
        home = Path(bin_dir).parent / "home"
        for name in (".fluxio_cliproxy_env", ".fluxio_provider_env"):
            path = home / name
            if not path.exists():
                continue
            for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key.startswith("export "):
                    key = key.removeprefix("export ").strip()
                if key and key not in env:
                    env[key] = value.strip().strip("\"'")
    local_env = ROOT / ".agent_control" / "cliproxy_local.env"
    if local_env.exists():
        for raw_line in local_env.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in env:
                env[key] = value.strip().strip("\"'")
    return env


def command_version(command: str, env: dict[str, str]) -> str:
    resolved = shutil.which(command, path=env.get("PATH"))
    if not resolved:
        return ""
    try:
        completed = subprocess.run(
            [resolved, "--version"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - defensive for live NAS installs.
        return f"error: {exc}"
    return (completed.stdout or completed.stderr or "").strip().splitlines()[0:1][0] if (
        completed.stdout or completed.stderr
    ).strip() else "installed"


def _cliproxy_status(extra_bin_dir: list[str] | None = None) -> dict[str, object]:
    """Recognize proxy-backed Claude (claudex) without requiring Anthropic login."""
    env = runtime_env(extra_bin_dir)
    proxy_bin = (
        shutil.which("cli-proxy-api", path=env.get("PATH"))
        or shutil.which("cliproxyapi", path=env.get("PATH"))
        or ""
    )
    base_url = str(env.get("ANTHROPIC_BASE_URL") or "").strip()
    port = str(env.get("CLIPROXY_PORT") or DEFAULT_CLIPROXY_PORT).strip()
    if not base_url:
        base_url = f"http://127.0.0.1:{port}"
    auth_token_present = bool(
        str(env.get("CLIPROXY_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    )
    runtime_homes = []
    for bin_dir in runtime_path_entries(extra_bin_dir):
        home = Path(bin_dir).parent / "home"
        runtime_homes.append(home)
    oauth_present = False
    cliproxy_env_present = False
    for home in runtime_homes:
        auth_dir = home / ".cli-proxy-api"
        if auth_dir.exists() and any(auth_dir.glob("*.json")):
            oauth_present = True
        if (home / ".fluxio_cliproxy_env").exists():
            cliproxy_env_present = True
            if not auth_token_present:
                auth_token_present = True
    listening = False
    health_detail = "not_probed"
    try:
        import urllib.request

        req = urllib.request.Request(
            base_url.rstrip("/") + "/",
            headers={"User-Agent": "nas-runtime-doctor-cliproxy"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            listening = int(getattr(resp, "status", 0) or 0) < 500
            health_detail = f"http_{getattr(resp, 'status', '?')}"
    except Exception as exc:  # pragma: no cover - live probe
        health_detail = f"unreachable:{type(exc).__name__}"
    ready = bool(proxy_bin and listening and (oauth_present or auth_token_present))
    return {
        "detected": bool(proxy_bin),
        "command": proxy_bin,
        "baseUrl": base_url,
        "port": port,
        "listening": listening,
        "health": health_detail,
        "oauthPresent": oauth_present,
        "cliproxyEnvPresent": cliproxy_env_present,
        "clientTokenPresent": auth_token_present,
        "claudeProxyBacked": bool(base_url and (proxy_bin or listening)),
        "ready": ready,
        "harnessProfileId": "claude-code-claudex",
        "note": (
            "Claude Code should use ANTHROPIC_BASE_URL -> CLIProxyAPI; "
            "do not require classical `claude auth login` for the claudex route."
        ),
    }


def inspect_commands(extra_bin_dir: list[str] | None = None) -> dict[str, object]:
    env = runtime_env(extra_bin_dir)
    commands = {}
    for command in COMMANDS:
        resolved = shutil.which(command, path=env.get("PATH"))
        commands[command] = {
            "detected": bool(resolved),
            "command": resolved or "",
            "version": command_version(command, env) if resolved else "",
        }
    cliproxy = _cliproxy_status(extra_bin_dir)
    claude_auth = (
        "proxy_backed"
        if cliproxy.get("claudeProxyBacked") and (cliproxy.get("oauthPresent") or cliproxy.get("clientTokenPresent"))
        else ("not_probed" if commands["claude"]["detected"] else "not_installed")
    )
    return {
        "runtimeBinDirs": runtime_path_entries(extra_bin_dir),
        "commands": commands,
        "ready": bool(
            commands["node"]["detected"]
            and commands["npm"]["detected"]
            and commands["openclaw"]["detected"]
            and commands["hermes"]["detected"]
        ),
        "managedCliDetected": {
            "codex": bool(commands["codex"]["detected"]),
            "kimi-code": bool(commands["kimi"]["detected"]),
            "claude-code": bool(commands["claude"]["detected"]),
            "grok-build": bool(commands["grok"]["detected"]),
            "cliproxyapi": bool(cliproxy.get("detected")),
        },
        "managedCliAuthentication": {
            "codex": "not_probed" if commands["codex"]["detected"] else "not_installed",
            "kimi-code": "not_probed" if commands["kimi"]["detected"] else "not_installed",
            "claude-code": claude_auth,
            "grok-build": "not_probed" if commands["grok"]["detected"] else "not_installed",
            "cliproxyapi": (
                "ready"
                if cliproxy.get("ready")
                else ("needs_oauth" if cliproxy.get("detected") else "not_installed")
            ),
        },
        "cliproxy": cliproxy,
        "installPlan": [
            "Run: python scripts/install_nas_runtime_stack.py --install-openclaw --install-hermes.",
            "Install managed coding harnesses with --install-kimi-code --install-claude-code --install-grok-build.",
            "For Claude-via-Codex (claudex): python scripts/nas_install_cliproxyapi.py then complete Codex OAuth in the browser (not `claude auth login`).",
            "Authenticate Kimi with kimi login, and Grok Build with grok login --device-auth or XAI_API_KEY.",
            "Leave OpenCodeGo OPENCODE_API_KEY alone when wiring CLIProxyAPI.",
            "Start the web backend with SYNTELOS_RUNTIME_BIN_DIR pointing to the runtime bin directory if it is not one of the default locations.",
            "Run openclaw onboard --install-daemon and configure provider auth before the first model request.",
            "Run hermes setup or connect provider auth before the first Hermes model request.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check NAS runtime binaries for Syntelos web missions.")
    parser.add_argument("--extra-bin-dir", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = inspect_commands(args.extra_bin_dir)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if payload["ready"] else 1

    print("Syntelos NAS runtime doctor")
    for name, item in payload["commands"].items():
        status = "ready" if item["detected"] else "missing"
        version = f" ({item['version']})" if item["version"] else ""
        print(f"- {name}: {status}{version}")
        if item["command"]:
            print(f"  {item['command']}")
    if payload["runtimeBinDirs"]:
        print("")
        print("Runtime bin directories:")
        for value in payload["runtimeBinDirs"]:
            print(f"  {value}")
    if not payload["ready"]:
        print("")
        print("Install plan:")
        for step in payload["installPlan"]:
            print(f"- {step}")
    return 0 if payload["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
