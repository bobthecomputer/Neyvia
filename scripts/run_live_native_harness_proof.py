#!/usr/bin/env python3
"""Run one authenticated, exact-route Neyvia Native proof without printing secrets."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://nas.example.invalid:47880"
DEFAULT_ACCOUNT = ROOT / ".agent_control" / "grand_agent_admin_password.txt"
DEFAULT_OUTPUT = ROOT / "proof" / "harness-improvement-20260825" / "live-native-run.json"


def _load_account(path: Path) -> tuple[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip().lower()] = value.strip()
    username = values.get("username", "admin")
    password = values.get("password", "")
    if not password:
        raise RuntimeError("Structured Neyvia password field is missing.")
    return username, password


def _post(opener: urllib.request.OpenerDirector, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def _backend(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    command: str,
    payload: dict[str, Any],
) -> Any:
    response = _post(opener, f"{base_url.rstrip('/')}/api/backend", {"command": command, "payload": payload})
    if response.get("ok") is not True:
        raise RuntimeError(str(response.get("error") or f"{command} failed"))
    return response.get("data")


def run(base_url: str, account_path: Path, output_path: Path) -> dict[str, Any]:
    def progress(message: str) -> None:
        print(f"[native-proof] {message}", file=sys.stderr, flush=True)

    username, password = _load_account(account_path)
    cookie_jar = http.cookiejar.CookieJar()
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar),
        urllib.request.HTTPSHandler(context=context),
    )
    progress("authenticating")
    login = _post(
        opener,
        f"{base_url.rstrip('/')}/api/auth/login",
        {"username": username, "password": password},
    )
    password = ""
    if login.get("ok") is not True:
        raise RuntimeError("Neyvia local account login failed.")

    progress("saving secret-free exact-route profile")
    profile = _backend(
        opener,
        base_url,
        "save_harness_profile_command",
        {
            "workspacePath": "/volume1/Saclay/projects/vibe-coding-platform",
            "profile": {
                "id": "neyvia-agent-default",
                "label": "OpenCode Go · DeepSeek V4 Flash",
                "harnessId": "neyvia-agent",
                "providerId": "opencode-go",
                "model": "deepseek-v4-flash",
                "baseUrl": "https://opencode.ai/zen/go/v1",
                "credentialEnv": "OPENCODE_API_KEY",
                "credentialKind": "api-key",
                "compatibilityMode": "openai-compatible",
            },
        },
    )
    objective = (
        "Reply exactly NATIVE_HARNESS_TIMELINE_PROVED after confirming the current "
        "workspace is readable. Do not edit files."
    )
    progress("starting native harness job")
    job = _backend(
        opener,
        base_url,
        "start_harness_job_command",
        {
            "mode": "direct",
            "harnessId": "neyvia-agent",
            "harnessLabel": "NEYVIA Native",
            "runtime": "neyvia-agent",
            "runtimeId": "neyvia-agent",
            "defaultRuntime": "neyvia-agent",
            "harnessProfileId": profile["id"],
            "model": "deepseek-v4-flash",
            "route": {
                "provider": "opencode-go",
                "model": "deepseek-v4-flash",
                "role": "executor",
                "effort": "high",
            },
            "workspacePath": "/volume1/Saclay/projects/vibe-coding-platform",
            "message": objective,
            "objective": objective,
        },
    )
    job_id = str(job.get("id") or "")
    progress(f"watching job {job_id}")
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        jobs = _backend(opener, base_url, "list_harness_jobs_command", {"limit": 60}).get("jobs", [])
        current = next((row for row in jobs if row.get("id") == job_id), None)
        if current and current.get("status") in {"completed", "failed", "cancelled"}:
            route = dict((current.get("result") or {}).get("route") or current.get("request", {}).get("route") or {})
            result = {
                "schema": "neyvia.native-harness-live-proof/v1",
                "jobId": job_id,
                "status": current.get("status"),
                "provider": route.get("provider"),
                "model": route.get("model") or route.get("model_id"),
                "transport": route.get("transport"),
                "output": str((current.get("result") or {}).get("reply") or "")[:500],
                "metrics": current.get("metrics"),
                "timeline": current.get("timeline"),
                "receiptPresent": bool((current.get("result") or {}).get("receiptPath")),
                "profile": {
                    "id": profile.get("id"),
                    "providerId": profile.get("providerId"),
                    "model": profile.get("model"),
                    "baseUrl": profile.get("baseUrl"),
                    "credentialEnv": profile.get("credentialEnv"),
                    "credentialValueStored": False,
                },
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            progress(f"job reached {result['status']}")
            print(json.dumps(result, indent=2))
            return result
        time.sleep(1)
    raise TimeoutError(f"Native harness job {job_id} did not become terminal within 240 seconds.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_URL)
    parser.add_argument("--account", type=Path, default=DEFAULT_ACCOUNT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.base_url, args.account, args.output)
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
