"""Run the frozen read-only protocol across every eligible live NAS harness."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import shutil
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from grant_agent.harness_comparison import (
    PROTOCOL_ID,
    SCHEMA,
    TASKS,
    WINNER_RULE,
    eligibility,
    grade_output,
    select_leader,
    summarize_attempts,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://nas.example.invalid:47880"
DEFAULT_ACCOUNT = ROOT / ".agent_control" / "grand_agent_admin_password.txt"
DEFAULT_PROOF = ROOT / "proof" / "harness-comparison-20260825"
REMOTE_WORKSPACE = "/volume1/Saclay/projects/vibe-coding-platform"


def _progress(message: str) -> None:
    print(f"[harness-comparison] {message}", file=sys.stderr, flush=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_account(path: Path) -> tuple[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip().lower()] = value.strip()
    password = values.get("password", "")
    if not password:
        raise RuntimeError("Structured Neyvia password field is missing.")
    return values.get("username", "admin"), password


def _post(opener: urllib.request.OpenerDirector, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=60) as response:
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


def _fixture_manifest(root: Path) -> list[dict[str, Any]]:
    rows = []
    for task in TASKS:
        for relative in task["fixturePaths"]:
            path = root / relative
            rows.append(
                {
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    return sorted({row["path"]: row for row in rows}.values(), key=lambda row: row["path"])


def _sync_fixtures(mapped_root: Path | None) -> None:
    if mapped_root is None:
        return
    source = ROOT / "tests" / "fixtures" / "harness_comparison"
    destination = mapped_root / "tests" / "fixtures" / "harness_comparison"
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.is_file():
            shutil.copy2(path, destination / path.name)
    for path in source.iterdir():
        if path.is_file() and path.read_bytes() != (destination / path.name).read_bytes():
            raise RuntimeError(f"NAS fixture verification failed: {path.name}")


def _wait_for_job(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    job_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        jobs = _backend(opener, base_url, "list_harness_jobs_command", {"limit": 200}).get("jobs", [])
        current = next((row for row in jobs if row.get("id") == job_id), None)
        if current and current.get("status") in {"completed", "failed", "cancelled"}:
            return current
        time.sleep(1)
    try:
        _backend(opener, base_url, "cancel_harness_job_command", {"jobId": job_id})
    except Exception:
        pass
    cancellation_deadline = time.monotonic() + 20
    while time.monotonic() < cancellation_deadline:
        jobs = _backend(opener, base_url, "list_harness_jobs_command", {"limit": 200}).get("jobs", [])
        current = next((row for row in jobs if row.get("id") == job_id), None)
        if current and current.get("status") in {"completed", "failed", "cancelled"}:
            return current
        time.sleep(1)
    raise TimeoutError(
        f"Harness job {job_id} did not expose a terminal receipt after the "
        f"{timeout_seconds}-second limit and cancellation."
    )


def _attempt(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    harness: dict[str, Any],
    task: dict[str, Any],
    profile_by_harness: dict[str, dict[str, Any]],
    receipts_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    harness_id = str(harness["harnessId"])
    adapter = str(harness.get("executionAdapter") or harness_id)
    catalog_model = str(harness.get("defaultModel") or "").strip()
    profile = profile_by_harness.get(harness_id) or {}
    requested_model = str(profile.get("model") or "").strip()
    if not requested_model and catalog_model not in {"provider-selected", "route-selected", "auto"}:
        requested_model = catalog_model
    payload = {
        "mode": "direct",
        "exactRoute": True,
        "routePolicy": "exact",
        "authorizedSecurity": False,
        "taskLane": "standard",
        "harnessId": harness_id,
        "harnessLabel": harness.get("label") or harness_id,
        "runtime": adapter,
        "runtimeId": adapter,
        "defaultRuntime": adapter,
        "harnessProfileId": str(profile.get("id") or ""),
        "model": requested_model,
        "route": {
            "provider": adapter,
            "model": requested_model,
            "role": "executor",
            "effort": "high",
            "benchmarkProtocol": PROTOCOL_ID,
        },
        "workspacePath": REMOTE_WORKSPACE,
        "message": task["objective"],
        "objective": task["objective"],
    }
    started_at = _utc_now()
    job = _backend(opener, base_url, "start_harness_job_command", payload)
    job_id = str(job.get("id") or "")
    _progress(f"{harness_id} / {task['id']} started as {job_id}")
    terminal = _wait_for_job(opener, base_url, job_id, timeout_seconds)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_name = f"{harness_id}--{task['id']}--{job_id}.json"
    receipt_path = receipts_dir / receipt_name
    receipt_path.write_text(json.dumps(terminal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    result = terminal.get("result") if isinstance(terminal.get("result"), dict) else {}
    route = result.get("route") if isinstance(result.get("route"), dict) else {}
    runtime_fallback = result.get("runtimeFallback")
    actual_runtime = str(result.get("runtime") or "")
    provider_substitution = bool(runtime_fallback) or (
        bool(actual_runtime) and actual_runtime not in {adapter, harness_id}
    )
    output = str(result.get("reply") or result.get("output") or "")
    metrics = terminal.get("metrics") if isinstance(terminal.get("metrics"), dict) else {}
    read_only = result.get("readOnly") if isinstance(result.get("readOnly"), dict) else {}
    attempt = {
        "harnessId": harness_id,
        "harnessLabel": harness.get("label") or harness_id,
        "taskId": task["id"],
        "jobId": job_id,
        "startedAt": started_at,
        "finishedAt": terminal.get("finishedAt") or terminal.get("updatedAt"),
        "status": terminal.get("status"),
        "runtime": actual_runtime or adapter,
        "provider": route.get("provider"),
        "model": route.get("model") or route.get("model_id") or requested_model,
        "transport": route.get("transport"),
        "providerSubstitution": provider_substitution,
        "readOnlyEnforced": read_only.get("enforced") is True,
        "changedFiles": result.get("filesChanged") or [],
        "receiptPresent": bool(metrics.get("receiptPresent")),
        "metrics": metrics,
        "timeline": terminal.get("timeline") or [],
        "output": output,
        "error": terminal.get("error") or result.get("error") or "",
        "grade": grade_output(task["id"], output),
        "receiptFile": f"receipts/{receipt_name}",
    }
    _progress(
        f"{harness_id} / {task['id']} -> {attempt['status']}, "
        f"{attempt['grade']['points']}/{attempt['grade']['maxPoints']} exact fields"
    )
    return attempt


def run(args: argparse.Namespace) -> dict[str, Any]:
    mapped_root = args.nas_mapped_root.resolve() if args.nas_mapped_root else None
    _sync_fixtures(mapped_root)
    username, password = _load_account(args.account.resolve(strict=True))
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookies),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    _progress("authenticating to the private Neyvia NAS")
    login = _post(
        opener,
        f"{args.base_url.rstrip('/')}/api/auth/login",
        {"username": username, "password": password},
    )
    password = ""
    if login.get("ok") is not True:
        raise RuntimeError("Neyvia local account login failed.")
    catalog = _backend(
        opener,
        args.base_url,
        "get_harness_catalog_command",
        {"workspacePath": REMOTE_WORKSPACE},
    )
    harnesses = [row for row in catalog.get("harnesses") or [] if isinstance(row, dict)]
    eligibility_rows = []
    eligible = []
    for harness in harnesses:
        included, reason = eligibility(harness)
        eligibility_rows.append(
            {
                "harnessId": harness.get("harnessId"),
                "label": harness.get("label"),
                "included": included,
                "reason": reason,
                "readiness": harness.get("readiness"),
                "version": harness.get("version"),
            }
        )
        if included:
            eligible.append(harness)
    if len(eligible) < 2:
        raise RuntimeError("Fewer than two comparable live harnesses are eligible.")
    _progress("eligible: " + ", ".join(str(row.get("harnessId")) for row in eligible))
    profiles = {
        str(row.get("harnessId") or ""): row
        for row in catalog.get("profiles") or []
        if isinstance(row, dict)
    }
    attempts: list[dict[str, Any]] = []
    receipts_dir = args.proof_dir / "receipts"
    for task_index, task in enumerate(TASKS):
        order = eligible[task_index:] + eligible[:task_index]
        for harness in order:
            try:
                attempts.append(
                    _attempt(
                        opener,
                        args.base_url,
                        harness,
                        task,
                        profiles,
                        receipts_dir,
                        args.job_timeout,
                    )
                )
            except Exception as exc:
                _progress(f"{harness.get('harnessId')} / {task['id']} launch failed: {type(exc).__name__}")
                attempts.append(
                    {
                        "harnessId": harness.get("harnessId"),
                        "harnessLabel": harness.get("label"),
                        "taskId": task["id"],
                        "jobId": None,
                        "startedAt": _utc_now(),
                        "finishedAt": _utc_now(),
                        "status": "launch-failed",
                        "runtime": harness.get("executionAdapter"),
                        "provider": None,
                        "model": profiles.get(str(harness.get("harnessId")), {}).get("model")
                        or harness.get("defaultModel"),
                        "transport": None,
                        "providerSubstitution": False,
                        "readOnlyEnforced": False,
                        "changedFiles": [],
                        "receiptPresent": False,
                        "metrics": {},
                        "timeline": [],
                        "output": "",
                        "error": f"{type(exc).__name__}: {exc}",
                        "grade": grade_output(task["id"], ""),
                        "receiptFile": None,
                    }
                )
    summaries = summarize_attempts(harnesses, attempts)
    leader = select_leader(summaries)
    report = {
        "schema": SCHEMA,
        "protocolId": PROTOCOL_ID,
        "capturedAt": _utc_now(),
        "environment": {
            "baseUrl": args.base_url,
            "workspace": REMOTE_WORKSPACE,
            "activeRelease": args.active_release,
            "catalogGeneratedAt": catalog.get("generatedAt"),
            "jobTimeoutSeconds": args.job_timeout,
        },
        "winnerRule": WINNER_RULE,
        "limitations": [
            "This compares installed routes on one NAS, not every possible model or machine.",
            "The sample is two deterministic read-only tasks; it does not measure long mutation missions.",
            "Latency includes each configured model provider and is reported separately from harness correctness.",
            "Declared capability coverage comes from inspected native adapters; task correctness comes only from live receipts.",
        ],
        "fixtures": _fixture_manifest(ROOT),
        "tasks": [
            {
                "id": task["id"],
                "fixturePaths": task["fixturePaths"],
                "expectedFields": list(task["expected"]),
                "maxPoints": len(task["expected"]),
            }
            for task in TASKS
        ],
        "eligibility": eligibility_rows,
        "catalogHarnesses": harnesses,
        "attempts": attempts,
        "summaries": summaries,
        "leader": leader,
    }
    args.proof_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.proof_dir / "comparison.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if mapped_root is not None:
        destination = mapped_root / ".agent_control" / "harness_comparison" / "latest.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(report_path.read_bytes())
        temporary.replace(destination)
        proof_destination = mapped_root / ".agent_control" / "proof" / args.proof_dir.name
        shutil.copytree(args.proof_dir, proof_destination, dirs_exist_ok=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_URL)
    parser.add_argument("--account", type=Path, default=DEFAULT_ACCOUNT)
    parser.add_argument("--proof-dir", type=Path, default=DEFAULT_PROOF)
    parser.add_argument("--nas-mapped-root", type=Path, default=Path("Y:/projects/vibe-coding-platform"))
    parser.add_argument("--active-release", default="neyvia-candidate-20260825-native-harness-evidence-r4")
    parser.add_argument("--job-timeout", type=int, default=90)
    args = parser.parse_args()
    args.proof_dir = args.proof_dir.resolve()
    if args.nas_mapped_root and not args.nas_mapped_root.exists():
        args.nas_mapped_root = None
    report = run(args)
    print(
        json.dumps(
            {
                "ok": True,
                "eligible": [row["harnessId"] for row in report["eligibility"] if row["included"]],
                "attempts": len(report["attempts"]),
                "leader": report["leader"],
                "proof": str(args.proof_dir / "comparison.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
