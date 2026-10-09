"""Secret-free, live authentication truth for Neyvia harnesses."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtimes.base import runtime_subprocess_env
from .subprocess_utils import hidden_windows_subprocess_kwargs


AUTH_SCHEMA = "neyvia.harness-auth-inventory/v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_probe_state = threading.local()


def probe_timed_out() -> bool:
    """True when a status command run on this thread since the last reset ran out of time."""
    return bool(getattr(_probe_state, "timed_out", False))


def reset_probe_timeout() -> None:
    _probe_state.timed_out = False


def _kill_tree(process: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, timeout=5, check=False,  # noqa: S603,S607
                           **hidden_windows_subprocess_kwargs())
        else:
            process.kill()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.communicate(timeout=2)
    except (OSError, subprocess.SubprocessError):
        pass


def _run(command: str, arguments: list[str], root: Path, timeout: float = 90.0) -> tuple[int, str]:
    args = [command, *arguments]
    if os.name == "nt" and Path(command).suffix.lower() in {".bat", ".cmd"}:
        args = ["cmd", "/d", "/s", "/c", subprocess.list2cmdline(args)]
    process = None
    try:
        process = subprocess.Popen(  # noqa: S603
            args,
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=runtime_subprocess_env(root),
            **hidden_windows_subprocess_kwargs(),
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # A .cmd shim leaves its child holding the pipes, so subprocess.run() would wait on them forever.
            _kill_tree(process)
            _probe_state.timed_out = True
            return 124, "status probe timed out"
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: status probe unavailable"
    completed = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    return completed.returncode, " ".join((completed.stdout or completed.stderr or "").split())[:1200]


def _base_result(row: dict[str, Any]) -> dict[str, Any]:
    installed = bool(row.get("installed"))
    provider_configured = row.get("providerConfigured")
    return {
        "harnessId": str(row.get("harnessId") or ""),
        "installed": installed,
        "providerConfigured": provider_configured,
        "authenticationOwner": "provider profile",
        "authState": "not-installed" if not installed else "unverified",
        "authenticatedLive": False,
        "benchmarkEligible": False,
        "setupAction": "Install the CLI first." if not installed else "Inspect the provider account for this CLI.",
        "evidence": "Executable presence is not authentication proof.",
    }


def _probe_row(row: dict[str, Any], root: Path) -> dict[str, Any]:
    result = _base_result(row)
    harness_id = result["harnessId"]
    command = str(row.get("command") or "").strip()
    if not result["installed"]:
        return result
    if bool(row.get("securityOnly")):
        result.update({
            "authenticationOwner": "bounded security profile",
            "authState": "security-scope-required",
            "setupAction": "Configure an authorized security profile; this route is excluded from the site benchmark.",
            "evidence": "Security-only harnesses are never admitted to general UI generation benchmarks.",
        })
        return result
    if harness_id == "neyvia-agent":
        result.update({
            "authenticationOwner": "selected model route",
            "authState": "route-dependent",
            "authenticatedLive": None,
            "setupAction": "Choose an authenticated exact model route; the resulting run receipt proves access.",
            "evidence": "Neyvia Native owns the harness; the selected provider owns model authentication.",
        })
        return result
    if harness_id == "fluxio-hybrid":
        result.update({
            "authenticationOwner": "each selected supervised route",
            "authState": "route-dependent",
            "authenticatedLive": None,
            "setupAction": "Inspect the exact executor, planner and verifier routes before starting.",
            "evidence": "Hybrid is an orchestration mode. It has no separate provider login.",
        })
        return result
    if not command:
        return result

    if harness_id == "codex":
        code, output = _run(command, ["login", "status"], root)
        authenticated = code == 0 and "logged in" in output.casefold()
        result.update({
            "providerConfigured": authenticated,
            "authenticationOwner": "Codex CLI",
            "authState": "authenticated-live" if authenticated else "account-action-required",
            "authenticatedLive": authenticated,
            "benchmarkEligible": authenticated,
            "setupAction": "Ready." if authenticated else "Run `codex login` and complete the official sign-in.",
            "evidence": "`codex login status` confirmed the active ChatGPT session." if authenticated else "Codex did not report an authenticated session.",
        })
        return result
    if harness_id == "claude-code":
        code, output = _run(command, ["auth", "status"], root)
        logged_in = False
        try:
            logged_in = bool(json.loads(output).get("loggedIn"))
        except (json.JSONDecodeError, AttributeError):
            logged_in = code == 0 and '"loggedIn":true' in output.replace(" ", "")
        result.update({
            "providerConfigured": logged_in,
            "authenticationOwner": "official Claude Code login",
            "authState": "authenticated-live" if logged_in else "account-action-required",
            "authenticatedLive": logged_in,
            "benchmarkEligible": logged_in,
            "setupAction": "Ready." if logged_in else "Complete `claude auth login` in the official Anthropic sign-in page.",
            "evidence": "`claude auth status` confirmed login." if logged_in else "Claude Code reports no logged-in account.",
        })
        from .harness_runtime_inspection import inspect_cli_proxy_api

        proxy = inspect_cli_proxy_api(root)
        result["alternativeRoutes"] = [{
            "id": "cliproxyapi",
            "label": "CLIProxyAPI",
            "installed": proxy.get("installed") is True,
            "serviceRunning": proxy.get("serviceRunning") is True,
            "authenticatedLive": proxy.get("ready") is True,
            "providerCount": int(proxy.get("providerCount") or 0),
            "modelCount": int(proxy.get("modelCount") or 0),
            "authenticationOwner": "CLIProxyAPI upstream provider",
            "evidence": (
                f"CLIProxyAPI exposes {int(proxy.get('modelCount') or 0)} live model route(s)."
                if proxy.get("ready") is True
                else str(proxy.get("blocker") or "CLIProxyAPI is not ready.")
            ),
        }]
        return result
    if harness_id == "grok-build":
        code, output = _run(command, ["models"], root)
        not_authenticated = "not authenticated" in output.casefold() or "login" in output.casefold()
        authenticated = code == 0 and not not_authenticated and "cached" not in output.casefold()
        result.update({
            "providerConfigured": authenticated,
            "authenticationOwner": "Grok CLI",
            "authState": "authenticated-live" if authenticated else "account-action-required",
            "authenticatedLive": authenticated,
            "benchmarkEligible": authenticated,
            "setupAction": "Ready." if authenticated else "Run the official Grok login flow; cached model names are not auth proof.",
            "evidence": "Grok returned a non-cached authenticated model response." if authenticated else "Grok explicitly reported that it is not authenticated.",
        })
        return result
    if harness_id in {"cursor", "cursor-agent"}:
        code, output = _run(command, ["status"], root)
        authenticated = code == 0 and "not logged in" not in output.casefold()
        result.update({
            "providerConfigured": authenticated,
            "authenticationOwner": "Cursor CLI",
            "authState": "authenticated-live" if authenticated else "account-action-required",
            "authenticatedLive": authenticated,
            "benchmarkEligible": authenticated,
            "setupAction": "Ready." if authenticated else "Run `cursor-agent login` and complete the account flow.",
            "evidence": "Cursor status confirmed login." if authenticated else "Cursor Agent reports that it is not logged in.",
        })
        return result
    if harness_id == "pi":
        code, _ = _run(command, ["auth", "check", "--provider", "openai-codex", "--json"], root)
        authenticated = code == 0
        result.update({
            "providerConfigured": authenticated,
            "authenticationOwner": "Pi provider auth",
            "authState": "authenticated-live" if authenticated else "provider-setup-required",
            "authenticatedLive": authenticated,
            "benchmarkEligible": authenticated,
            "setupAction": "Ready." if authenticated else "Connect an exact Pi provider; no provider passed its auth check.",
            "evidence": "Pi provider auth check passed." if authenticated else "Pi's OpenAI Codex provider auth check failed.",
        })
        return result
    if harness_id == "hermes":
        route_checks = {
            provider: _run(command, ["auth", "status", provider], root)
            for provider in ("openai-codex", "minimax-oauth", "anthropic")
        }
        authenticated_routes = [
            provider
            for provider, (code, output) in route_checks.items()
            if code == 0 and f"{provider}: logged in" in output.casefold()
        ]
        authenticated = bool(authenticated_routes)
        route_labels = {
            "openai-codex": "OpenAI Codex",
            "minimax-oauth": "MiniMax OAuth",
            "anthropic": "Anthropic / Claude (Hermes)",
        }
        result.update({
            "providerConfigured": authenticated,
            "authState": "authenticated-live" if authenticated else "route-setup-required",
            "authenticatedLive": authenticated,
            "benchmarkEligible": authenticated,
            "authenticatedRoutes": [route_labels[provider] for provider in authenticated_routes],
            "setupAction": "Ready; choose the exact supervised route." if authenticated else "Authenticate a Hermes-owned provider route. Claude OAuth is available through Hermes when the account meets Anthropic's documented plan requirements.",
            "evidence": (
                "Hermes auth status confirmed: "
                + ", ".join(route_labels[provider] for provider in authenticated_routes)
                + "."
                if authenticated
                else "No supervised Hermes provider route reported a live login."
            ),
        })
        return result
    if harness_id == "opencode":
        code, output = _run(command, ["auth", "list"], root)
        configured = code == 0 and any(name in output.casefold() for name in ("openai", "minimax", "openrouter"))
        result.update({
            "providerConfigured": configured,
            "authenticationOwner": "OpenCode provider store",
            "authState": "configured-unverified" if configured else "provider-setup-required",
            "authenticatedLive": False,
            "setupAction": "Run an exact OpenCode benchmark turn to prove live access." if configured else "Connect an OpenCode provider.",
            "evidence": "OpenCode lists configured providers; a model list is not counted as a live generation." if configured else "OpenCode lists no usable provider.",
        })
        return result
    if harness_id == "kimi-code":
        configured = row.get("providerConfigured") is True
        result.update({
            "providerConfigured": configured,
            "authenticationOwner": "Kimi provider profile",
            "authState": "configured-unverified" if configured else "provider-setup-required",
            "setupAction": "Run an exact Kimi generation to prove live access." if configured else "Configure a Kimi provider profile.",
            "evidence": "A configured provider still needs a generation receipt." if configured else "Kimi has no configured provider.",
        })
        return result
    if harness_id in {"deepseek-harness", "rook", "wallbreaker"}:
        configured = row.get("providerConfigured") is True
        result.update({
            "providerConfigured": configured,
            "authState": "configured-unverified" if configured else "provider-setup-required",
            "setupAction": "Run a bounded exact-route proof." if configured else "Configure an exact provider profile and credential reference.",
            "evidence": "Provider configuration is present but not a live generation proof." if configured else "No provider profile is configured.",
        })
        return result
    result["evidence"] = "No safe non-interactive live-auth probe is defined for this harness."
    return result


def build_harness_auth_inventory(root: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    rows = [row for row in catalog.get("harnesses", []) if isinstance(row, dict)]
    measured: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(rows)))) as pool:
        futures = {pool.submit(_probe_row, row, root): row for row in rows}
        for future in as_completed(futures):
            measured.append(future.result())
    measured.sort(key=lambda item: [row.get("harnessId") for row in rows].index(item["harnessId"]))
    return {
        "schema": AUTH_SCHEMA,
        "checkedAt": _utc_now(),
        "workspace": str(root),
        "harnesses": measured,
        "summary": {
            "installed": sum(bool(row.get("installed")) for row in measured),
            "configured": sum(row.get("providerConfigured") is True for row in measured),
            "authenticatedLive": sum(row.get("authenticatedLive") is True for row in measured),
            "alternativeRoutesLive": sum(
                route.get("authenticatedLive") is True
                for row in measured
                for route in row.get("alternativeRoutes", [])
                if isinstance(route, dict)
            ),
            "benchmarkEligible": sum(bool(row.get("benchmarkEligible")) for row in measured),
            "total": len(measured),
        },
    }


def merge_auth_inventory(catalog: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(catalog)
    by_id = {row.get("harnessId"): row for row in inventory.get("harnesses", []) if isinstance(row, dict)}
    for row in merged.get("harnesses", []):
        auth = by_id.get(row.get("harnessId"))
        if auth:
            row.update(auth)
    merged["authInventory"] = inventory
    merged["summary"] = inventory.get("summary", {})
    return merged
