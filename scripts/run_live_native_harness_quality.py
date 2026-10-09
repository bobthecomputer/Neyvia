#!/usr/bin/env python3
"""Run the frozen Neyvia Native quality ladder through one exact live route."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import shlex
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paramiko


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.native_harness_quality import (  # noqa: E402
    PROTOCOL_ID,
    SCHEMA,
    TASKS,
    grade_output,
    summarize_attempts,
)


DEFAULT_URL = "https://nas.example.invalid:47880"
DEFAULT_NAS_CREDENTIALS = (
    Path.home()
    / "Projects"
    / "vibe-coding-platform"
    / ".agent_control"
    / "nas_codex2_100_125_54_118.json"
)
DEFAULT_APP_ACCOUNT = (
    Path.home()
    / "Projects"
    / "vibe-coding-platform"
    / ".agent_control"
    / "grand_agent_web_admin.json"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_account(account_text: str) -> tuple[str, str]:
    try:
        decoded = json.loads(account_text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        username = str(decoded.get("username") or "admin").strip()
        password = str(decoded.get("password") or "").strip()
        if password:
            return username, password
    values: dict[str, str] = {}
    for line in account_text.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip().lower()] = value.strip()
    username = values.get("username", "admin")
    password = values.get("password", "")
    if not password:
        raise RuntimeError("The app account password field is missing.")
    return username, password


def _remote_accounts(
    credentials_path: Path,
    local_account_path: Path | None,
) -> tuple[list[tuple[str, str]], str]:
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=credentials.get("host", "192.0.2.10"),
        port=int(credentials.get("port", 22)),
        username=credentials.get("username", "nas-user"),
        password=credentials.get("password") or credentials.get("secret"),
        look_for_keys=False,
        allow_agent=False,
        timeout=20,
    )
    try:
        _stdin, stdout, stderr = client.exec_command(
            "readlink -f /volume1/Saclay/projects/syntelos/current",
            timeout=30,
        )
        active_root = stdout.read().decode("utf-8", "replace").strip()
        error = stderr.read().decode("utf-8", "replace")
        if stdout.channel.recv_exit_status() or not active_root:
            raise RuntimeError(f"Could not resolve NAS current: {error[-400:]}")
        repository_root = "/volume1/Saclay/projects/neyvia/repository"
        _stdin, stdout, _stderr = client.exec_command(
            f"test -d '{repository_root}' && printf present",
            timeout=30,
        )
        workspace_root = (
            repository_root
            if stdout.read().decode("utf-8", "replace").strip() == "present"
            and stdout.channel.recv_exit_status() == 0
            else active_root
        )
        account_roots = (
            workspace_root,
            active_root,
            "/volume1/Saclay/projects/vibe-coding-platform",
            "/volume1/Saclay/projects/syntelos",
        )
        candidates = tuple(
            f"{root}/.agent_control/{name}"
            for root in account_roots
            for name in (
                "grand_agent_admin_password.txt",
                "neyvia_admin_password.txt",
                "grand_agent_web_admin.json",
                "neyvia_web_admin.json",
            )
        )
        account_texts: list[str] = []
        for candidate in candidates:
            _stdin, stdout, _stderr = client.exec_command(
                f"test -f '{candidate}' && cat '{candidate}'",
                timeout=30,
            )
            value = stdout.read().decode("utf-8", "replace")
            if stdout.channel.recv_exit_status() == 0 and value.strip():
                account_texts.append(value)
    finally:
        client.close()

    if local_account_path is not None and local_account_path.is_file():
        account_texts.append(local_account_path.read_text(encoding="utf-8"))
    if not account_texts:
        raise RuntimeError("No readable active-release or local app account note was found.")
    accounts: list[tuple[str, str]] = []
    for account_text in account_texts:
        try:
            account = _parse_account(account_text)
        except RuntimeError:
            continue
        if account not in accounts:
            accounts.append(account)
    if not accounts:
        raise RuntimeError("Readable app account notes contained no usable password field.")
    return accounts, workspace_root


def _mirror_evaluation_workspace(
    credentials_path: Path,
    source_root: str,
    allowed_root: str,
    label: str,
) -> str:
    source = str(source_root or "").strip().rstrip("/")
    root = str(allowed_root or "").strip().rstrip("/")
    if not source.startswith("/") or not root.startswith("/"):
        raise RuntimeError("Evaluation source and allowed root must be absolute live-host paths.")
    slug = re.sub(r"[^a-z0-9]+", "-", str(label or "evaluation").lower()).strip("-")[:72]
    target_parent = f"{root}/.agent_control/runtime_proof/harness_evaluations"
    target = f"{target_parent}/{slug}"
    partial = f"{target}.partial-{uuid.uuid4().hex[:8]}"
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=credentials.get("host", "192.0.2.10"),
        port=int(credentials.get("port", 22)),
        username=credentials.get("username", "nas-user"),
        password=credentials.get("password") or credentials.get("secret"),
        look_for_keys=False,
        allow_agent=False,
        timeout=20,
    )
    quoted_source = shlex.quote(source)
    quoted_target = shlex.quote(target)
    quoted_parent = shlex.quote(target_parent)
    quoted_partial = shlex.quote(partial)
    marker = ".neyvia-wip-complete.json"
    command = (
        f"test -d {quoted_source}; test -f {shlex.quote(f'{source}/{marker}')}; "
        f"mkdir -p {quoted_parent}; "
        f"if test -d {quoted_target}; then "
        f"cmp -s {shlex.quote(f'{source}/{marker}')} {shlex.quote(f'{target}/{marker}')}; "
        f"else mkdir {quoted_partial}; "
        f"tar -C {quoted_source} -cf - . | tar -C {quoted_partial} -xf -; "
        f"test -f {shlex.quote(f'{partial}/{marker}')}; mv {quoted_partial} {quoted_target}; fi; "
        f"test \"$(find {quoted_source} -type f | wc -l)\" = "
        f"\"$(find {quoted_target} -type f | wc -l)\"; printf %s {quoted_target}"
    )
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=300)
        mirrored = stdout.read().decode("utf-8", "replace").strip()
        error = stderr.read().decode("utf-8", "replace")
        if stdout.channel.recv_exit_status() or mirrored != target:
            raise RuntimeError(f"Could not mirror evaluation workspace: {error[-800:]}")
    finally:
        client.close()
    return target


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
    response = _post(
        opener,
        f"{base_url.rstrip('/')}/api/backend",
        {"command": command, "payload": payload},
    )
    if response.get("ok") is not True:
        raise RuntimeError(str(response.get("error") or f"{command} failed"))
    return response.get("data")


def _terminal_job(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    job_id: str,
    timeout: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            jobs = _backend(
                opener,
                base_url,
                "list_harness_jobs_command",
                {"limit": 24},
            ).get("jobs", [])
        except (TimeoutError, urllib.error.URLError):
            time.sleep(1)
            continue
        current = next((row for row in jobs if row.get("id") == job_id), None)
        if current and current.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
            return current
        time.sleep(1)
    raise TimeoutError(f"Harness job {job_id} did not become terminal within {timeout} seconds.")


def run(args: argparse.Namespace) -> dict[str, Any]:
    accounts, discovered_root = _remote_accounts(
        args.nas_credentials.resolve(),
        args.app_account.resolve() if args.app_account else None,
    )
    workspace_root = str(args.workspace_root or discovered_root).strip()
    if not workspace_root.startswith("/"):
        raise RuntimeError("--workspace-root must be an absolute path on the live host.")
    if args.mirror_workspace and workspace_root != discovered_root:
        workspace_root = _mirror_evaluation_workspace(
            args.nas_credentials.resolve(), workspace_root, discovered_root, args.label
        )
    selected_ids = {str(task_id).strip() for task_id in (args.task or []) if str(task_id).strip()}
    selected_tasks = [task for task in TASKS if not selected_ids or task["id"] in selected_ids]
    unknown_ids = selected_ids - {task["id"] for task in TASKS}
    if unknown_ids:
        raise RuntimeError(f"Unknown quality task(s): {', '.join(sorted(unknown_ids))}")
    opener: urllib.request.OpenerDirector | None = None
    for username, password in accounts:
        candidate_opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        try:
            login = _post(
                candidate_opener,
                f"{args.base_url.rstrip('/')}/api/auth/login",
                {"username": username, "password": password},
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                continue
            raise
        if login.get("ok") is True:
            opener = candidate_opener
            break
    accounts.clear()
    if opener is None:
        raise RuntimeError("Neyvia app login failed for every current ignored account note.")

    profile = _backend(
        opener,
        args.base_url,
        "save_harness_profile_command",
        {
            "workspacePath": workspace_root,
            "profile": {
                "id": "neyvia-quality-deepseek-v4-flash",
                "label": "OpenCode Go - DeepSeek V4 Flash quality ladder",
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

    attempts: list[dict[str, Any]] = []
    for task in selected_tasks:
        print(f"[{args.label}] starting {task['id']}", flush=True)
        job = _backend(
            opener,
            args.base_url,
            "start_harness_job_command",
            {
                "mode": "direct",
                "harnessId": "neyvia-agent",
                "harnessLabel": "Neyvia Native",
                "runtime": "neyvia-agent",
                "runtimeId": "neyvia-agent",
                "defaultRuntime": "neyvia-agent",
                "harnessProfileId": profile["id"],
                "model": "deepseek-v4-flash",
                "exactRoute": True,
                "routePolicy": "exact",
                "route": {
                    "provider": "opencode-go",
                    "model": "deepseek-v4-flash",
                    "role": "executor",
                    "effort": "high",
                },
                "workspacePath": workspace_root,
                "_profileWorkspacePath": workspace_root,
                "sessionId": re.sub(
                    r"[^a-z0-9_-]+",
                    "-",
                    f"quality-{args.label}-{task['id']}".lower(),
                )[:96],
                "maxTurns": args.max_turns,
                "runtimeTimeoutSeconds": args.runtime_timeout_seconds,
                "message": task["objective"],
                "objective": task["objective"],
            },
        )
        terminal = _terminal_job(opener, args.base_url, str(job.get("id") or ""), args.job_timeout)
        result = terminal.get("result") if isinstance(terminal.get("result"), dict) else {}
        route = result.get("route") if isinstance(result.get("route"), dict) else {}
        reply = str(result.get("reply") or "")
        route_integrity = (
            terminal.get("status") == "completed"
            and str(route.get("provider") or "") == "opencode-go"
            and str(route.get("model") or route.get("model_id") or "").endswith("deepseek-v4-flash")
            and str(route.get("transport") or "") == "chat-completions"
            and not result.get("runtimeFallback")
        )
        attempt = {
            "taskId": task["id"],
            "difficulty": task["difficulty"],
            "jobId": terminal.get("id"),
            "status": terminal.get("status"),
            "error": str(terminal.get("error") or "")[:12000],
            "reply": reply,
            "route": route,
            "routeIntegrity": route_integrity,
            "receiptPath": str(result.get("receiptPath") or ""),
            "metrics": terminal.get("metrics"),
            "timeline": terminal.get("timeline"),
            "grade": grade_output(task["id"], reply),
        }
        attempts.append(attempt)
        print(
            f"[{args.label}] {task['id']}: {attempt['status']} "
            f"{attempt['grade']['score']}/{attempt['grade']['maximum']} route={route_integrity}",
            flush=True,
        )

    report = {
        "schema": SCHEMA,
        "protocolId": PROTOCOL_ID,
        "label": args.label,
        "createdAt": _utc_now(),
        "exactRoute": {
            "harness": "neyvia-agent",
            "provider": "opencode-go",
            "model": "deepseek-v4-flash",
            "transport": "chat-completions",
            "fallbackAllowed": False,
        },
        "workspace": workspace_root,
        "tasks": [
            {"id": task["id"], "difficulty": task["difficulty"], "objective": task["objective"]}
            for task in selected_tasks
        ],
        "attempts": attempts,
        "summary": summarize_attempts(attempts),
    }
    args.proof_dir.mkdir(parents=True, exist_ok=True)
    output = args.proof_dir / f"{args.label}.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"proof": str(output), "summary": report["summary"]}, ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Neyvia Native's frozen generalization ladder.")
    parser.add_argument("--base-url", default=DEFAULT_URL)
    parser.add_argument("--nas-credentials", type=Path, default=DEFAULT_NAS_CREDENTIALS)
    parser.add_argument("--app-account", type=Path, default=DEFAULT_APP_ACCOUNT)
    parser.add_argument("--proof-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--job-timeout", type=int, default=420)
    parser.add_argument("--max-turns", type=int, default=18)
    parser.add_argument("--runtime-timeout-seconds", type=int, default=360)
    parser.add_argument(
        "--task",
        action="append",
        help="Run one frozen task id; repeat to select more than one.",
    )
    parser.add_argument(
        "--workspace-root",
        help="Absolute live-host workspace to evaluate instead of the discovered repository root.",
    )
    parser.add_argument(
        "--mirror-workspace",
        action="store_true",
        help="Mirror the verified workspace into the allowed runtime-proof namespace before evaluation.",
    )
    args = parser.parse_args()
    report = run(args)
    summary = report["summary"]
    return 0 if summary["allCompleted"] and summary["allRouteHonest"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
