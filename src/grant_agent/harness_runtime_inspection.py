from __future__ import annotations

from .subprocess_utils import process_is_alive

import json
import os
import re
import secrets
import signal
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .runtimes.base import runtime_bin_candidates, runtime_subprocess_env, runtime_which
from .subprocess_utils import hidden_windows_subprocess_kwargs


CLAUDE_CODE_ROUTER_PACKAGE = "@musistudio/claude-code-router"
CLAUDE_CODE_ROUTER_DOCS_URL = "https://github.com/musistudio/claude-code-router"
CLAUDE_CODE_ROUTER_DEFAULT_GATEWAY = "http://127.0.0.1:3456"
CLAUDE_CODE_ROUTER_DEFAULT_MANAGEMENT = "http://127.0.0.1:3458"

CLI_PROXY_API_DOCS_URL = "https://help.router-for.me/"
CLI_PROXY_API_DEFAULT_BASE_URL = "http://127.0.0.1:8317"
CLI_PROXY_API_CREDENTIAL_ENV = "CLIPROXY_API_KEY"
CLI_PROXY_API_LEGACY_CREDENTIAL_ENV = "CLIPROXYAPI_AUTH_TOKEN"

NATIVE_HARNESS_COMMANDS = {
    "claude-code": "claude",
    "grok-build": "grok",
}


def inspect_harness_runtime(root: Path, harness_id: str) -> dict[str, Any]:
    """Return bounded, secret-free evidence from the selected native harness."""

    root = Path(root).resolve()
    normalized_id = str(harness_id or "").strip().lower()
    command_name = NATIVE_HARNESS_COMMANDS.get(normalized_id)
    if not command_name:
        raise ValueError(f"Native inspection is not available for {normalized_id or 'missing harness'}.")
    env = runtime_subprocess_env(root)
    command = runtime_which(command_name, root)
    result: dict[str, Any] = {
        "schema": "fluxio.harness_runtime_inspection.v1",
        "harnessId": normalized_id,
        "commandName": command_name,
        "command": command or "",
        "installed": bool(command),
        "version": "",
        "ready": False,
        "checks": [],
    }
    if normalized_id == "grok-build":
        result["cliProxyApi"] = inspect_cli_proxy_api(root)
    if not command:
        result["checks"].append(
            {
                "key": "cli",
                "status": "blocked",
                "detail": f"{command_name} was not found in the managed runtime PATH.",
            }
        )
        return result

    version_probe = _run_probe([command, "--version"], root=root, env=env, timeout=10)
    result["version"] = _compact_probe_output(version_probe)
    result["checks"].append(
        {
            "key": "cli",
            "status": "ready" if version_probe.returncode == 0 else "degraded",
            "detail": result["version"] or f"Version probe exited with {version_probe.returncode}.",
        }
    )

    if normalized_id == "claude-code":
        result["cliProxyApi"] = inspect_cli_proxy_api(root)
        auth_probe = _run_probe(
            [command, "auth", "status", "--json"],
            root=root,
            env=env,
            timeout=12,
        )
        auth_payload = _parse_json_output(auth_probe.stdout or auth_probe.stderr)
        logged_in = bool(
            auth_probe.returncode == 0
            and isinstance(auth_payload, dict)
            and (auth_payload.get("loggedIn") or auth_payload.get("authenticated"))
        )
        supported_env_auth = (
            "anthropic-api-key"
            if str(env.get("ANTHROPIC_API_KEY") or "").strip()
            else "amazon-bedrock"
            if str(env.get("CLAUDE_CODE_USE_BEDROCK") or "").strip() == "1"
            else "google-vertex"
            if str(env.get("CLAUDE_CODE_USE_VERTEX") or "").strip() == "1"
            else "anthropic-gateway"
            if (
                str(env.get("ANTHROPIC_BASE_URL") or "").strip()
                and str(env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
            )
            else ""
        )
        authenticated = logged_in or bool(supported_env_auth)
        result["authentication"] = {
            "checked": True,
            "authenticated": authenticated,
            "method": (
                _safe_scalar(auth_payload, "authMethod", "method", "authType")
                or supported_env_auth
            ),
            "provider": _safe_scalar(auth_payload, "apiProvider", "provider"),
        }
        result["checks"].append(
            {
                "key": "authentication",
                "status": "ready" if authenticated else "blocked",
                "detail": (
                    f"Claude Code authentication is active ({supported_env_auth or 'official login'})."
                    if authenticated
                    else "Run `claude auth login` or configure an Anthropic-supported API or enterprise route."
                ),
            }
        )
        result["ready"] = version_probe.returncode == 0 and authenticated
        return result

    inspect_probe = _run_probe(
        [command, "inspect", "--json"],
        root=root,
        env=env,
        timeout=25,
    )
    inspect_payload = _parse_json_output(inspect_probe.stdout or inspect_probe.stderr)
    inspect_ok = inspect_probe.returncode == 0 and isinstance(inspect_payload, (dict, list))
    authentication = _grok_authentication_evidence(env)
    result["context"] = _summarize_grok_inspection(inspect_payload)
    result["authentication"] = authentication
    result["checks"].append(
        {
            "key": "workspace-context",
            "status": "ready" if inspect_ok else "blocked",
            "detail": (
                "Grok Build inspected the workspace through its native discovery command."
                if inspect_ok
                else f"`grok inspect --json` exited with {inspect_probe.returncode}."
            ),
        }
    )
    result["checks"].append(
        {
            "key": "authentication",
            "status": "ready" if authentication["configured"] else "blocked",
            "detail": (
                f"Grok Build authentication is configured through {authentication['method']}."
                if authentication["configured"]
                else "Run `grok login --device-code` or configure XAI_API_KEY in the managed runtime."
            ),
        }
    )
    result["ready"] = version_probe.returncode == 0 and inspect_ok and authentication["configured"]
    return result


def inspect_cli_proxy_api(root: Path) -> dict[str, Any]:
    """Inspect the managed CLIProxyAPI sidecar without returning credentials."""

    root = Path(root).resolve()
    env = runtime_subprocess_env(root)
    command = runtime_which("cli-proxy-api", root)
    paths = _cli_proxy_paths(root, command)
    state = _read_json_file(paths.get("state"))
    process_running = bool(state and _cli_proxy_process_matches(state))
    reachable, models = _cli_proxy_models(env)
    provider_counts = _cli_proxy_provider_counts(paths.get("auth"))
    installed = bool(command)
    service_running = process_running or reachable
    model_count = len(models)
    provider_count = sum(provider_counts.values())
    ready = installed and service_running and model_count > 0
    if not installed:
        blocker = "CLIProxyAPI is not installed in the managed runtime."
    elif not paths.get("config") or not paths["config"].is_file():
        blocker = "Start CLIProxyAPI once to create its private loopback configuration."
    elif not service_running:
        blocker = "CLIProxyAPI is installed and configured, but the local service is stopped."
    elif model_count <= 0:
        blocker = "No usable models are authenticated. Complete a Claude, Codex, Gemini, or xAI OAuth login."
    else:
        blocker = ""
    return {
        "schema": "fluxio.cli_proxy_api_status.v1",
        "docsUrl": CLI_PROXY_API_DOCS_URL,
        "installed": installed,
        "command": command or "",
        "version": _cli_proxy_version(root, env, command) if installed else "",
        "configured": bool(paths.get("config") and paths["config"].is_file()),
        "configPath": str(paths["config"]),
        "serviceRunning": service_running,
        "processManaged": process_running,
        "ready": ready,
        "providerCount": provider_count,
        "providerCounts": provider_counts,
        "modelCount": model_count,
        "models": models[:40],
        "baseUrl": CLI_PROXY_API_DEFAULT_BASE_URL if service_running else "",
        "recommendedBaseUrl": CLI_PROXY_API_DEFAULT_BASE_URL,
        "credentialEnv": CLI_PROXY_API_CREDENTIAL_ENV,
        "authenticationConfigured": provider_count > 0 or model_count > 0,
        "blocker": blocker,
    }


def manage_cli_proxy_api(root: Path, action: str) -> dict[str, Any]:
    """Control the installed CLIProxyAPI sidecar on loopback only."""

    root = Path(root).resolve()
    normalized_action = str(action or "status").strip().lower()
    if normalized_action not in {"status", "start", "stop", "restart", "connect-codex"}:
        raise ValueError(f"Unsupported CLIProxyAPI action: {normalized_action}")
    if normalized_action == "status":
        return {"ok": True, "action": normalized_action, "status": inspect_cli_proxy_api(root)}

    command = runtime_which("cli-proxy-api", root)
    if not command:
        raise RuntimeError("CLIProxyAPI is not installed in the managed runtime.")
    paths = _cli_proxy_paths(root, command)
    if normalized_action == "connect-codex":
        connection = _connect_existing_codex_login(paths)
        _stop_cli_proxy(paths)
        env = runtime_subprocess_env(root)
        _ensure_cli_proxy_config(paths, env)
        env = runtime_subprocess_env(root)
        _start_cli_proxy(command, paths, env)
        status = inspect_cli_proxy_api(root)
        return {
            "ok": status.get("ready") is True,
            "action": normalized_action,
            "message": (
                "Existing Codex login connected to CLIProxyAPI."
                if status.get("ready") is True
                else "Codex authorization was imported, but CLIProxyAPI exposes no models yet."
            ),
            "connection": connection,
            "status": status,
        }
    if normalized_action in {"stop", "restart"}:
        _stop_cli_proxy(paths)
    if normalized_action in {"start", "restart"}:
        env = runtime_subprocess_env(root)
        _ensure_cli_proxy_config(paths, env)
        env = runtime_subprocess_env(root)
        _start_cli_proxy(command, paths, env)

    status = inspect_cli_proxy_api(root)
    return {
        "ok": True,
        "action": normalized_action,
        "message": f"CLIProxyAPI {normalized_action} completed.",
        "status": status,
    }


def _connect_existing_codex_login(paths: dict[str, Path]) -> dict[str, Any]:
    """Import an existing Codex OAuth grant without returning any token value."""

    candidates = []
    codex_home = str(os.environ.get("CODEX_HOME") or "").strip()
    if codex_home:
        candidates.append(Path(codex_home).expanduser() / "auth.json")
    candidates.append(Path.home() / ".codex" / "auth.json")
    source: Path | None = None
    payload: dict[str, Any] = {}
    for candidate in candidates:
        current = _read_json_file(candidate)
        tokens = current.get("tokens") if isinstance(current.get("tokens"), dict) else current
        if (
            isinstance(tokens, dict)
            and str(tokens.get("access_token") or "").strip()
            and str(tokens.get("refresh_token") or "").strip()
        ):
            source = candidate
            payload = current
            break
    if source is None:
        raise RuntimeError(
            "No reusable Codex OAuth login was found. Complete `codex login` first."
        )

    tokens = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else payload
    imported = {
        "id_token": str(tokens.get("id_token") or "").strip(),
        "access_token": str(tokens.get("access_token") or "").strip(),
        "refresh_token": str(tokens.get("refresh_token") or "").strip(),
        "account_id": str(tokens.get("account_id") or payload.get("account_id") or "").strip(),
        "last_refresh": str(payload.get("last_refresh") or "").strip()
        or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "email": str(payload.get("email") or "").strip(),
        "type": "codex",
        "expired": "",
    }
    destination = paths["auth"] / "codex-imported.json"
    _write_private_file(destination, json.dumps(imported, indent=2) + "\n")
    return {
        "source": "existing Codex CLI OAuth store",
        "destination": destination.name,
        "fieldsPresent": sorted(key for key, value in imported.items() if value),
        "secretValuesReturned": False,
    }


def _cli_proxy_paths(root: Path, command: str | None) -> dict[str, Path]:
    runtime_root: Path | None = None
    if command:
        command_path = Path(command).expanduser()
        if command_path.parent.name == "bin":
            runtime_root = command_path.parent.parent
    if runtime_root is None:
        bins = runtime_bin_candidates(root)
        runtime_root = bins[0].parent if bins else root / "runtime"
    home = runtime_root / "home"
    config_root = home / ".cli-proxy-api"
    return {
        "runtime": runtime_root,
        "config_root": config_root,
        "config": config_root / "config.yaml",
        "auth": config_root / "auth",
        "client_key": config_root / "client.key",
        "provider_env": home / ".fluxio_provider_env",
        "state": runtime_root / "var" / "run" / "cli-proxy-api.json",
        "log": runtime_root / "var" / "log" / "cli-proxy-api.log",
    }


def _ensure_cli_proxy_config(paths: dict[str, Path], env: dict[str, str]) -> None:
    config_path = paths["config"]
    client_key_path = paths["client_key"]
    if config_path.exists():
        token = str(
            env.get(CLI_PROXY_API_CREDENTIAL_ENV)
            or env.get(CLI_PROXY_API_LEGACY_CREDENTIAL_ENV)
            or ""
        ).strip()
        if not token and client_key_path.is_file():
            try:
                token = client_key_path.read_text(encoding="utf-8").strip()
            except OSError:
                token = ""
        if not token:
            raise RuntimeError(
                "CLIProxyAPI already has a custom configuration, but Neyvia cannot find its client token. "
                f"Set {CLI_PROXY_API_CREDENTIAL_ENV} in the managed runtime environment."
            )
        _merge_private_provider_env(paths["provider_env"], CLI_PROXY_API_CREDENTIAL_ENV, token)
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    paths["auth"].mkdir(parents=True, exist_ok=True)
    token = str(env.get(CLI_PROXY_API_CREDENTIAL_ENV) or "").strip() or f"fluxio-{secrets.token_urlsafe(36)}"
    config = (
        "# Managed by Neyvia. The service is intentionally loopback-only.\n"
        'host: "127.0.0.1"\n'
        "port: 8317\n"
        "tls:\n"
        "  enable: false\n"
        "remote-management:\n"
        "  allow-remote: false\n"
        '  secret-key: ""\n'
        "  disable-control-panel: true\n"
        f"auth-dir: {json.dumps(str(paths['auth']))}\n"
        "api-keys:\n"
        f"  - {json.dumps(token)}\n"
        "debug: false\n"
        "logging-to-file: true\n"
        "usage-statistics-enabled: false\n"
        "plugins:\n"
        "  enabled: false\n"
    )
    _write_private_file(config_path, config)
    _write_private_file(client_key_path, token + "\n")
    _merge_private_provider_env(paths["provider_env"], CLI_PROXY_API_CREDENTIAL_ENV, token)


def _merge_private_provider_env(path: Path, key: str, value: str) -> None:
    try:
        existing = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        existing = []
    kept: list[str] = []
    matcher = re.compile(rf"^(?:export\s+)?{re.escape(key)}\s*=")
    for line in existing:
        if not matcher.match(line.strip()):
            kept.append(line)
    kept.append(f"{key}={value}")
    _write_private_file(path, "\n".join(kept).rstrip() + "\n")


def _write_private_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")
    temporary.write_text(content, encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _start_cli_proxy(command: str, paths: dict[str, Path], env: dict[str, str]) -> None:
    state = _read_json_file(paths.get("state"))
    if state and _cli_proxy_process_matches(state):
        return
    paths["state"].parent.mkdir(parents=True, exist_ok=True)
    paths["log"].parent.mkdir(parents=True, exist_ok=True)
    args = [command, "-config", str(paths["config"])]
    with paths["log"].open("a", encoding="utf-8") as log_handle:
        popen_kwargs: dict[str, Any] = {
            "cwd": str(paths["runtime"]),
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            popen_kwargs.update(hidden_windows_subprocess_kwargs())
            popen_kwargs["creationflags"] = int(popen_kwargs.get("creationflags") or 0) | int(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            ) | int(getattr(subprocess, "DETACHED_PROCESS", 0))
        else:
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(args, **popen_kwargs)  # noqa: S603
    state_payload = {
        "schema": "fluxio.cli_proxy_api_service.v1",
        "pid": process.pid,
        "command": command,
        "config": str(paths["config"]),
        "startedAtUnix": int(time.time()),
    }
    _write_private_file(paths["state"], json.dumps(state_payload, indent=2) + "\n")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = _cli_proxy_log_tail(paths["log"])
            raise RuntimeError(
                f"CLIProxyAPI exited during startup with code {process.returncode}"
                f"{f': {detail}' if detail else '.'}"
            )
        reachable, _models = _cli_proxy_models(env)
        if reachable:
            return
        time.sleep(0.1)
    raise RuntimeError("CLIProxyAPI did not open its loopback endpoint within 5 seconds.")


def _stop_cli_proxy(paths: dict[str, Path]) -> None:
    state = _read_json_file(paths.get("state"))
    pid = int(state.get("pid") or 0) if state else 0
    if pid > 0 and _cli_proxy_process_matches(state):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        deadline = time.monotonic() + 8
        while _process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if _process_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except (AttributeError, OSError):
                pass
    try:
        paths["state"].unlink(missing_ok=True)
    except OSError:
        pass


def _cli_proxy_process_matches(state: dict[str, Any]) -> bool:
    pid = int(state.get("pid") or 0)
    if not _process_alive(pid):
        return False
    command_line = _process_command_line(pid)
    if not command_line:
        return False
    expected_command = Path(str(state.get("command") or "cli-proxy-api")).name
    expected_config = str(state.get("config") or "")
    return expected_command in command_line and (not expected_config or expected_config in command_line)


def _process_command_line(pid: int) -> str:
    """Return a verified process command line, or an empty string when unknown."""

    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.is_file():
        try:
            return proc_cmdline.read_bytes().replace(b"\0", b" ").decode(
                "utf-8",
                errors="replace",
            )
        except OSError:
            return ""
    if os.name == "nt":
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "(Get-CimInstance Win32_Process -Filter "
                        f"'ProcessId = {int(pid)}').CommandLine"
                    ),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return completed.stdout.strip() if completed.returncode == 0 else ""
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _cli_proxy_models(env: dict[str, str]) -> tuple[bool, list[str]]:
    token = str(
        env.get(CLI_PROXY_API_CREDENTIAL_ENV)
        or env.get(CLI_PROXY_API_LEGACY_CREDENTIAL_ENV)
        or ""
    ).strip()
    headers = {"accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = Request(f"{CLI_PROXY_API_DEFAULT_BASE_URL}/v1/models", headers=headers, method="GET")
    try:
        with urlopen(request, timeout=2) as response:  # noqa: S310 - fixed loopback URL
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        return exc.code in {401, 403, 404}, []
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False, []
    rows = payload.get("data") if isinstance(payload, dict) else []
    models = sorted(
        {
            str(row.get("id") or "").strip()
            for row in rows
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
    ) if isinstance(rows, list) else []
    return True, models


def _cli_proxy_provider_counts(auth_dir: Path | None) -> dict[str, int]:
    if not auth_dir or not auth_dir.is_dir():
        return {}
    counts: dict[str, int] = {}
    for path in list(auth_dir.glob("*.json"))[:200]:
        payload = _read_json_file(path)
        provider = str(payload.get("type") or payload.get("provider") or "unknown").strip().lower()
        provider = re.sub(r"[^a-z0-9_.-]+", "-", provider)[:40] or "unknown"
        counts[provider] = counts.get(provider, 0) + 1
    return dict(sorted(counts.items()))


def _cli_proxy_version(root: Path, env: dict[str, str], command: str) -> str:
    completed = _run_probe([command, "-help"], root=root, env=env, timeout=10)
    match = re.search(r"CLIProxyAPI Version:\s*([^,\s]+)", f"{completed.stdout}\n{completed.stderr}")
    return match.group(1) if match else ""


def _read_json_file(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _cli_proxy_log_tail(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]
    except OSError:
        return ""
    return _redact_router_output(" ".join(lines))


def inspect_claude_code_router(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    env = runtime_subprocess_env(root)
    command = runtime_which("ccr", root)
    service = _read_router_service(env)
    service_alive = bool(service and _process_alive(int(service.get("pid") or 0)))
    gateway_status: dict[str, Any] = {}
    provider_count = 0
    profile_count = 0
    if service_alive:
        gateway_payload = _router_rpc(service, "getGatewayStatus")
        if isinstance(gateway_payload, dict):
            gateway_status = gateway_payload
        config_payload = _router_rpc(service, "getConfig")
        if isinstance(config_payload, dict):
            provider_count, profile_count = _configured_router_counts(config_payload)

    gateway_state = str(gateway_status.get("state") or "").strip().lower()
    gateway_running = gateway_state == "running"
    gateway_url = _gateway_url(gateway_status) if gateway_running else ""
    installed = bool(command)
    ready = installed and service_alive and gateway_running and provider_count > 0
    return {
        "schema": "fluxio.claude_code_router_status.v1",
        "package": CLAUDE_CODE_ROUTER_PACKAGE,
        "docsUrl": CLAUDE_CODE_ROUTER_DOCS_URL,
        "installed": installed,
        "command": command or "",
        "version": _router_version(root, env) if installed else "",
        "serviceRunning": service_alive,
        "gatewayState": gateway_state or ("unknown" if service_alive else "stopped"),
        "gatewayRunning": gateway_running,
        "providerCount": provider_count,
        "profileCount": profile_count,
        "ready": ready,
        "managementUrl": _safe_management_url(service),
        "gatewayUrl": gateway_url,
        "recommendedBaseUrl": gateway_url or CLAUDE_CODE_ROUTER_DEFAULT_GATEWAY,
        "defaultManagementUrl": CLAUDE_CODE_ROUTER_DEFAULT_MANAGEMENT,
        "lastError": _bounded_text(gateway_status.get("lastError"), 240),
    }


def manage_claude_code_router(root: Path, action: str) -> dict[str, Any]:
    """Install or control only the loopback-bound managed CCR service."""

    root = Path(root).resolve()
    normalized_action = str(action or "status").strip().lower()
    allowed = {"status", "install", "update", "start", "stop", "restart"}
    if normalized_action not in allowed:
        raise ValueError(f"Unsupported Claude Code Router action: {normalized_action}")
    if normalized_action == "status":
        return {"ok": True, "action": normalized_action, "status": inspect_claude_code_router(root)}

    env = runtime_subprocess_env(root)
    if normalized_action in {"install", "update"}:
        npm = runtime_which("npm", root)
        if not npm:
            raise RuntimeError("The managed Node.js runtime does not expose npm.")
        _run_router_action(
            [npm, "install", "-g", f"{CLAUDE_CODE_ROUTER_PACKAGE}@latest"],
            root=root,
            env=env,
            timeout=900,
            label=normalized_action,
        )
    else:
        command = runtime_which("ccr", root)
        if not command:
            raise RuntimeError("Claude Code Router is not installed in the managed runtime.")
        if normalized_action == "restart":
            _run_router_action([command, "stop"], root=root, env=env, timeout=30, label="stop")
            _run_router_action(
                [command, "start", "--host", "127.0.0.1", "--no-open", "--gateway"],
                root=root,
                env=env,
                timeout=60,
                label="start",
            )
        elif normalized_action == "start":
            _run_router_action(
                [command, "start", "--host", "127.0.0.1", "--no-open", "--gateway"],
                root=root,
                env=env,
                timeout=60,
                label="start",
            )
        else:
            _run_router_action([command, "stop"], root=root, env=env, timeout=30, label="stop")

    status = inspect_claude_code_router(root)
    return {
        "ok": True,
        "action": normalized_action,
        "message": f"Claude Code Router {normalized_action} completed.",
        "status": status,
    }


def _run_probe(
    args: list[str],
    *,
    root: Path,
    env: dict[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603
            args,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
            **hidden_windows_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 124, "", str(exc))


def _run_router_action(
    args: list[str],
    *,
    root: Path,
    env: dict[str, str],
    timeout: int,
    label: str,
) -> None:
    completed = _run_probe(args, root=root, env=env, timeout=timeout)
    if completed.returncode == 0:
        return
    detail = _redact_router_output(completed.stderr or completed.stdout)
    raise RuntimeError(
        f"Claude Code Router {label} failed with exit code {completed.returncode}"
        f"{f': {detail}' if detail else '.'}"
    )


def _router_version(root: Path, env: dict[str, str]) -> str:
    npm = runtime_which("npm", root)
    if not npm:
        return ""
    completed = _run_probe(
        [npm, "list", "-g", CLAUDE_CODE_ROUTER_PACKAGE, "--depth=0", "--json"],
        root=root,
        env=env,
        timeout=15,
    )
    payload = _parse_json_output(completed.stdout)
    dependencies = payload.get("dependencies") if isinstance(payload, dict) else {}
    package = dependencies.get(CLAUDE_CODE_ROUTER_PACKAGE) if isinstance(dependencies, dict) else {}
    return str(package.get("version") or "").strip() if isinstance(package, dict) else ""


def _router_service_candidates(env: dict[str, str]) -> list[Path]:
    candidates: list[Path] = []
    internal_home = str(env.get("CCR_INTERNAL_HOME_DIR") or "").strip()
    if internal_home:
        candidates.append(Path(internal_home) / ".claude-code-router/service.json")
    home = str(env.get("HOME") or "").strip()
    if home:
        candidates.append(Path(home) / ".claude-code-router/service.json")
    app_data = str(env.get("APPDATA") or env.get("LOCALAPPDATA") or "").strip()
    if app_data:
        candidates.append(Path(app_data) / "claude-code-router/service.json")
    candidates.append(Path.home() / ".claude-code-router/service.json")
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def _read_router_service(env: dict[str, str]) -> dict[str, Any]:
    for path in _router_service_candidates(env):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("url") and payload.get("pid"):
            return payload
    return {}


def _router_rpc(service: dict[str, Any], method: str) -> Any:
    try:
        parsed = urlparse(str(service.get("url") or ""))
        token = parse_qs(parsed.query).get("ccr_web_token", [""])[0]
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or not token:
            return None
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return None
        origin = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 3458}"
        request = Request(
            f"{origin}/api/ccr/rpc",
            data=json.dumps({"method": method, "args": []}).encode("utf-8"),
            headers={"content-type": "application/json", "x-ccr-web-auth": token},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:  # noqa: S310 - loopback URL is validated above
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return payload.get("value") if isinstance(payload, dict) and payload.get("ok") else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _configured_router_counts(config: dict[str, Any]) -> tuple[int, int]:
    providers = config.get("Providers") or config.get("providers") or []
    provider_count = len([row for row in providers if isinstance(row, dict) and row.get("enabled", True)]) if isinstance(providers, list) else 0
    profile_root = config.get("profile") if isinstance(config.get("profile"), dict) else {}
    profiles = profile_root.get("profiles") or config.get("profiles") or []
    profile_count = len([row for row in profiles if isinstance(row, dict) and row.get("enabled", True)]) if isinstance(profiles, list) else 0
    return provider_count, profile_count


def _gateway_url(status: dict[str, Any]) -> str:
    direct = str(status.get("url") or status.get("baseUrl") or "").strip()
    if re.match(r"^https?://(?:127\.0\.0\.1|localhost|\[?::1\]?)(?::\d+)?/?$", direct):
        return direct.rstrip("/")
    host = str(status.get("host") or "127.0.0.1").strip()
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    port = status.get("port") or 3456
    if host not in {"127.0.0.1", "localhost", "::1", "[::1]"}:
        host = "127.0.0.1"
    return f"http://{host}:{int(port)}"


def _safe_management_url(service: dict[str, Any]) -> str:
    try:
        parsed = urlparse(str(service.get("url") or ""))
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return ""
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 3458}"
    except ValueError:
        return ""


def _process_alive(pid: int) -> bool:
    return process_is_alive(pid)


def _parse_json_output(value: object) -> Any:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError:
            continue
    return None


def _summarize_grok_inspection(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"topLevelKind": "list", "entryCount": len(payload), "counts": {}}
    if not isinstance(payload, dict):
        return {"topLevelKind": "unreadable", "entryCount": 0, "counts": {}}
    aliases = {
        "instructions": ("instructions", "instructionFiles", "rules"),
        "skills": ("skills",),
        "agents": ("agents", "subagents"),
        "plugins": ("plugins",),
        "mcpServers": ("mcpServers", "mcp_servers", "mcp"),
        "hooks": ("hooks",),
    }
    counts: dict[str, int] = {}
    for label, keys in aliases.items():
        value = next((payload.get(key) for key in keys if key in payload), None)
        if isinstance(value, (list, dict)):
            counts[label] = len(value)
    return {
        "topLevelKind": "object",
        "entryCount": len(payload),
        "keys": sorted(str(key) for key in payload.keys())[:30],
        "counts": counts,
    }


def _grok_authentication_evidence(env: dict[str, str]) -> dict[str, Any]:
    if str(env.get("XAI_API_KEY") or "").strip():
        return {"checked": True, "configured": True, "method": "XAI_API_KEY"}
    home = str(env.get("HOME") or "").strip()
    candidates = [Path(home) / ".grok/auth.json"] if home else []
    candidates.append(Path.home() / ".grok/auth.json")
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 2:
                return {"checked": True, "configured": True, "method": "cached session"}
        except OSError:
            continue
    return {"checked": True, "configured": False, "method": "none"}


def _safe_scalar(payload: Any, *keys: str) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)):
            return _bounded_text(value, 100)
    return ""


def _compact_probe_output(completed: subprocess.CompletedProcess[str]) -> str:
    return _bounded_text(completed.stdout or completed.stderr, 180)


def _bounded_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _redact_router_output(value: object) -> str:
    text = _bounded_text(value, 400)
    text = re.sub(r"([?&]ccr_web_token=)[^\s&]+", r"\1<redacted>", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)(token|api[_-]?key|authorization)\s*[:=]\s*\S+", r"\1=<redacted>", text)
    return text
