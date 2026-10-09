"""Hermes-owned Anthropic OAuth connection helpers.

This integration delegates the complete Claude sign-in to the installed Hermes
CLI. Neyvia only reads Hermes' non-secret auth status and never receives or
relays Claude credentials.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .runtimes.base import runtime_subprocess_env, runtime_which
from .subprocess_utils import hidden_windows_subprocess_kwargs


HERMES_CLAUDE_SUBSCRIPTION_WARNING = (
    "Hermes' documented Anthropic OAuth route requires Claude Max with purchased "
    "extra-usage credits. Claude Pro is not supported; Hermes usage draws from "
    "extra usage rather than the included Max allowance."
)
_STATUS_LOCK = threading.Lock()
_STATUS_CACHE: dict[tuple[str, str, str, str], tuple[float, dict[str, Any]]] = {}


def _hermes_command(root: Path) -> str | None:
    return runtime_which("hermes", Path(root))


def _hermes_environment(root: Path) -> dict[str, str]:
    return runtime_subprocess_env(Path(root))


def hermes_anthropic_auth_status(root: Path) -> dict[str, Any]:
    """Return redacted Hermes Anthropic auth status without reading credentials."""
    root = Path(root)
    command = _hermes_command(root)
    result: dict[str, Any] = {
        "provider": "anthropic",
        "authenticationOwner": "Hermes CLI",
        "host": "Neyvia backend host",
        "installed": bool(command),
        "authenticated": False,
        "authState": "not-installed" if not command else "account-action-required",
        "credentialType": "unknown",
        "warning": HERMES_CLAUDE_SUBSCRIPTION_WARNING,
    }
    if not command:
        result["message"] = "Hermes CLI is not available on this Neyvia host."
        return result
    env = _hermes_environment(root)
    cache_key = (
        command,
        str(env.get("HERMES_HOME") or ""),
        str(env.get("HERMES_AUTH_STORE") or ""),
        str(env.get("HOME") or ""),
    )
    with _STATUS_LOCK:
        cached = _STATUS_CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < 2.0:
            return dict(cached[1])
    try:
        completed = subprocess.run(
            [command, "auth", "status", "anthropic"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            env=env,
            **hidden_windows_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result["authState"] = "status-unavailable"
        result["message"] = f"Hermes auth status could not be read ({type(exc).__name__})."
        return result

    # `hermes auth status` prints only metadata today. Parse a tiny allowlist and
    # never pass command output through to the UI or logs.
    lines = [" ".join(line.split()).casefold() for line in (completed.stdout or "").splitlines()]
    provider_authenticated = completed.returncode == 0 and any(
        line == "anthropic: logged in" for line in lines
    )
    credential_type = "unknown"
    for line in lines:
        if line.startswith("auth_type:"):
            candidate = line.partition(":")[2].strip().replace("-", "_")
            if candidate in {"oauth", "api_key", "manual", "external_oauth"}:
                credential_type = candidate
            break
    subscription_authenticated = provider_authenticated and credential_type in {
        "oauth",
        "external_oauth",
    }
    result.update(
        {
            "authenticated": subscription_authenticated,
            "providerAuthenticated": provider_authenticated,
            "authState": (
                "authenticated-live"
                if subscription_authenticated
                else "provider-auth-configured"
                if provider_authenticated
                else "account-action-required"
            ),
            "credentialType": credential_type,
            "message": (
                "Hermes reports an Anthropic OAuth login."
                if subscription_authenticated
                else "Hermes has Anthropic credentials, but the reported auth type is not subscription OAuth."
                if provider_authenticated
                else "Hermes does not report an active Anthropic login."
            ),
        }
    )
    with _STATUS_LOCK:
        _STATUS_CACHE[cache_key] = (time.monotonic(), dict(result))
    return result


def _open_interactive_terminal(command: str, arguments: list[str], root: Path, environment: dict[str, str] | None = None) -> None:
    # Intentionally visible: the user clicked sign-in and must type into this terminal.
    argv = [command, *arguments]
    env = environment if environment is not None else _hermes_environment(root)
    if os.name == "nt":
        if Path(command).suffix.casefold() in {".cmd", ".bat"}:
            argv = ["cmd.exe", "/d", "/k", subprocess.list2cmdline(argv)]
        subprocess.Popen(
            argv,
            cwd=str(root),
            env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010),
        )
        return
    if sys.platform == "darwin":
        import subprocess as sp

        shell_line = shlex.join(argv)
        escaped = shell_line.replace("\\", "\\\\").replace('"', '\\"')
        script = f'tell application "Terminal" to do script "{escaped}"'
        subprocess.Popen(["osascript", "-e", script], cwd=str(root), env=env)
        return
    terminal = next(
        (shutil.which(name) for name in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal") if shutil.which(name)),
        None,
    )
    if not terminal:
        raise RuntimeError("No interactive terminal is available on the Neyvia backend host.")
    if Path(terminal).name == "gnome-terminal":
        terminal_args = [terminal, "--", *argv]
    elif Path(terminal).name == "konsole":
        terminal_args = [terminal, "-e", *argv]
    else:
        terminal_args = [terminal, "-e", *argv]
    subprocess.Popen(terminal_args, cwd=str(root), env=env)


def start_hermes_anthropic_oauth(root: Path) -> dict[str, Any]:
    """Open Hermes' own interactive OAuth login; credentials stay in Hermes."""
    root = Path(root)
    status = hermes_anthropic_auth_status(root)
    if not status["installed"]:
        raise RuntimeError("Hermes CLI is not available on this Neyvia host.")
    if status["authenticated"]:
        return {
            "status": "authenticated",
            "authenticated": True,
            "message": "Hermes already reports an Anthropic login.",
            "warning": HERMES_CLAUDE_SUBSCRIPTION_WARNING,
        }
    command = _hermes_command(root)
    if not command:
        raise RuntimeError("Hermes CLI is not available on this Neyvia host.")
    arguments = [
        "auth",
        "add",
        "anthropic",
        "--type",
        "oauth",
        "--label",
        "neyvia-claude-subscription",
    ]
    _open_interactive_terminal(command, arguments, root)
    command_text = subprocess.list2cmdline([command, *arguments]) if os.name == "nt" else shlex.join([command, *arguments])
    return {
        "status": "manual_required",
        "authenticated": False,
        "method": "hermes-native-anthropic-oauth",
        "command": command_text,
        "host": "Neyvia backend host",
        "warning": HERMES_CLAUDE_SUBSCRIPTION_WARNING,
        "message": (
            "Hermes opened its own Claude OAuth login in a terminal on the Neyvia "
            "backend host. Finish the code prompt there; Neyvia never receives the credential."
        ),
    }
