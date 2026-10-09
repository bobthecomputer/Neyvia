"""Opt-in Hermes subscription provider; credentials remain with official Claude CLI.

Readiness is not a certification of Anthropic permission or account eligibility.
Never copy OAuth tokens, spoof a client, or fall back to another paid provider.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .hermes_claude_subscription import _hermes_environment, _open_interactive_terminal
from .runtimes.base import runtime_which
from .subprocess_utils import hidden_windows_subprocess_kwargs

PROVIDER = "claude-subscription-directsdk-experimental"
PLUGIN = "claude-subscription-directsdk"
NOTICE = (
    "Experimental third-party subscription route. Uses the official Claude CLI, "
    "but Anthropic has not certified this integration. Account restrictions and "
    "billing are controlled by Anthropic; no ban-free guarantee. Disable extra "
    "usage in your Claude account if you do not want overage charges."
)


def _ack_path(root: Path) -> Path:
    return Path(root) / ".agent_control" / "claude_subscription_opt_in.json"


def subscription_environment(root: Path) -> dict:
    env = _hermes_environment(root)
    command = runtime_which("hermes", root)
    command_home = Path(command).resolve().parent.parent if command else Path()
    home = command_home if command_home.name == ".hermes" else Path(env.get("HOME") or Path.home()) / ".hermes"
    # Pin the same profile for metadata checks and execution. Hermes otherwise
    # may select its default profile during CLI startup.
    env.setdefault("HERMES_HOME", str(home))
    return env


def _metadata(command: str, args: list[str], root: Path, env: dict) -> str:
    try:
        result = subprocess.run([command, *args], cwd=str(root), env=env,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=25, check=False,
                                **hidden_windows_subprocess_kwargs())
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Could not check the installed CLI. No model request was sent.") from None
    if result.returncode:
        raise RuntimeError("CLI readiness check failed. No model request was sent.")
    return result.stdout


def subscription_status(root: Path, environment: dict | None = None) -> dict:
    root = Path(root)
    env = environment if environment is not None else subscription_environment(root)
    hermes = runtime_which("hermes", root)
    claude = runtime_which("claude", root)
    status = dict(provider=PROVIDER, ready=False, compatible=False,
                  pluginInstalled=False, authenticated=False, notice=NOTICE,
                  authenticationOwner="Official Claude CLI", installed=bool(hermes),
                  claudeInstalled=bool(claude), version="", message="",
                  acknowledged=_ack_path(root).is_file())
    if not hermes:
        return {**status, "message": "Install Hermes 0.21.4 or newer on this host first."}
    try:
        version = re.search(r"\bv?(\d+)\.(\d+)\.(\d+)\b", _metadata(hermes, ["--version"], root, env))
        if not version:
            raise RuntimeError("Hermes version could not be verified.")
        status["version"] = ".".join(version.groups())
        status["compatible"] = tuple(map(int, version.groups())) >= (0, 21, 4)
        if not status["compatible"]:
            return {**status, "message": f"Hermes {status['version']} is too old. This plugin requires 0.21.4 or newer. Existing chats have not been changed."}
        rows = json.loads(_metadata(hermes, ["plugins", "list", "--json"], root, env))
        status["pluginInstalled"] = any(
            isinstance(row, dict) and row.get("name") in {PLUGIN, PROVIDER}
            and not row.get("removed") and str(row.get("status", "")).lower() not in {"error", "failed", "disabled"}
            for row in rows if isinstance(rows, list))
        if not status["pluginInstalled"]:
            return {**status, "message": "Install the reviewed Hermes Claude Subscription DirectSDK plugin."}
        if not claude:
            return {**status, "message": "Install the official Claude Code CLI on this host, then sign in there."}
        auth = json.loads(_metadata(claude, ["auth", "status", "--json"], root, env))
        status["authenticated"] = auth.get("loggedIn") is True and auth.get("authMethod") == "claude.ai"
        status["ready"] = status["authenticated"]
        status["message"] = "Local prerequisites found. This does not verify entitlement or account safety." if status["ready"] else "Sign in with your subscription using the official Claude CLI. API-key login is not this route."
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        status["message"] = str(exc) if isinstance(exc, RuntimeError) else "CLI metadata could not be verified. No model request was sent."
    return status


def setup_subscription(root: Path, action: str, acknowledged: bool) -> dict:
    if action == "disable":
        _ack_path(root).unlink(missing_ok=True)
        return {"message": "Experimental subscription route disabled for this workspace."}
    if acknowledged is not True:
        raise RuntimeError("Read and acknowledge the experimental subscription route notice first.")
    if action == "acknowledge":
        status = subscription_status(root)
        if not status["ready"]:
            raise RuntimeError(status["message"])
        path = _ack_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"notice": NOTICE, "provider": PROVIDER}), encoding="utf-8")
        return {"message": "Experimental route enabled for this workspace. Readiness is checked before every run."}
    status = subscription_status(root)
    if not status["compatible"]:
        raise RuntimeError(status["message"])
    if action == "install":
        command, args = runtime_which("hermes", root), ["plugins", "install", PLUGIN]
    elif action == "login":
        command, args = runtime_which("claude", root), ["auth", "login"]
    else:
        raise RuntimeError("Unknown subscription setup action.")
    if not command:
        raise RuntimeError("Required CLI is missing on this host.")
    _open_interactive_terminal(command, args, Path(root), subscription_environment(root))
    return {"message": "Opened the official CLI setup on this host. Complete it there, then check readiness again."}


def require_subscription_route(root: Path, payload: dict, env: dict) -> None:
    """Fail before spawning Hermes; never silently reinterpret this provider."""
    if not _ack_path(root).is_file():
        raise RuntimeError("Acknowledge the experimental Claude subscription route in Provider connections first.")
    conflicts = [name for name in env if env.get(name) and (
        name in {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_SUBSCRIPTION_DIRECTSDK_COMMAND", "NODE_OPTIONS"}
        or name.startswith("CLAUDE_CODE_USE_"))]
    if conflicts:
        raise RuntimeError("Subscription route refuses credential, endpoint or runtime overrides: " + ", ".join(sorted(conflicts)))
    status = subscription_status(root, env)
    if not status["ready"]:
        raise RuntimeError(status["message"])
    # Do not inherit a configured paid fallback/auxiliary lane under the
    # subscription label. Inspect, never rewrite the user's Hermes profile.
    import yaml
    command = runtime_which("hermes", root)
    command_home = Path(command).resolve().parent.parent
    home = Path(env.get("HERMES_HOME") or (command_home if command_home.name == ".hermes" else Path.home() / ".hermes"))
    config_path = home / "config.yaml"
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        if not isinstance(config, dict):
            raise ValueError()
        if config.get("fallback_model") or config.get("fallback_providers") or config.get("fallback_models"):
            raise RuntimeError("This Hermes profile has fallback providers. Use a subscription-only profile without fallbacks.")
        for lane in (config.get("auxiliary") or {}).values():
            if isinstance(lane, dict) and (lane.get("provider") not in (None, "", "main", PROVIDER) or lane.get("base_url") or lane.get("api_key")):
                raise RuntimeError("This Hermes profile has auxiliary calls on another provider. Select main for those lanes before using the subscription route.")
    except (OSError, ValueError, AttributeError, yaml.YAMLError):
        raise RuntimeError("Hermes profile billing routes could not be verified; no model request was sent.") from None
