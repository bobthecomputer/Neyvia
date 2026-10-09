from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.html_site_benchmark import (  # noqa: E402
    FROZEN_PROMPT,
    PROTOCOL_ID,
    SCHEMA,
    combine_score,
    grade_html,
)


ROUTES = (
    {"id": "codex-gpt-5-6-sol", "harness": "Codex CLI", "provider": "openai-codex", "model": "gpt-5.6-sol"},
    {"id": "opencode-gpt-5-6-sol", "harness": "OpenCode", "provider": "openai", "model": "gpt-5.6-sol"},
    {"id": "claude-code-sonnet", "harness": "Claude Code", "provider": "anthropic-first-party", "model": "sonnet"},
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _command(route: dict[str, str], workdir: Path, output_file: Path) -> list[str]:
    if route["id"].startswith("codex-"):
        return [
            "codex", "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "workspace-write",
            "--model", route["model"], "--cd", str(workdir), "--output-last-message", str(output_file),
            FROZEN_PROMPT,
        ]
    if route["id"].startswith("opencode-"):
        return [
            "opencode", "run", "--pure", "--auto", "--dir", str(workdir),
            "--model", f"{route['provider']}/{route['model']}", "--variant", "high", FROZEN_PROMPT,
        ]
    return [
        "claude", "--print", "--model", route["model"], "--effort", "high",
        "--permission-mode", "acceptEdits", "--allowedTools", "Read,Write,Edit",
        "--no-session-persistence", "--output-format", "json", FROZEN_PROMPT,
    ]


def _launch(args: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(args[0]) or args[0]
    if os.name == "nt" and Path(executable).suffix.lower() in {".bat", ".cmd"}:
        shim_root = Path(executable).parent
        native_candidates = {
            "codex": [Path(shutil.which("codex.exe") or "")],
            "claude": [shim_root / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"],
            "opencode": [shim_root / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"],
        }.get(args[0], [])
        executable = str(next((candidate for candidate in native_candidates if candidate.is_file()), executable))
    resolved = [executable, *args[1:]]
    if os.name == "nt" and Path(executable).suffix.lower() in {".bat", ".cmd"}:
        resolved = ["cmd", "/d", "/s", "/c", subprocess.list2cmdline(resolved)]
    return subprocess.run(  # noqa: S603
        resolved,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _browser_grade(index_path: Path, screenshot_dir: Path) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"score": 0, "maximum": 20, "status": "playwright-unavailable", "checks": []}
    checks: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        errors: list[str] = []
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(index_path.as_uri(), wait_until="load")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_dir / "desktop.png"), full_page=True)
        desktop_overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")
        filter_button = page.get_by_role("button", name="Tasks", exact=True)
        filter_worked = False
        if filter_button.count():
            before = filter_button.first.get_attribute("aria-pressed")
            filter_button.first.click()
            after = filter_button.first.get_attribute("aria-pressed")
            filter_worked = before != after and after == "true"
        theme_button = page.locator('button[aria-label*="theme" i], button:has-text("Theme")')
        theme_worked = False
        if theme_button.count():
            before = page.locator("html").get_attribute("data-theme") or page.locator("body").get_attribute("data-theme")
            theme_button.first.click()
            after = page.locator("html").get_attribute("data-theme") or page.locator("body").get_attribute("data-theme")
            theme_worked = before != after
        page.set_viewport_size({"width": 390, "height": 844})
        page.reload(wait_until="load")
        page.screenshot(path=str(screenshot_dir / "mobile.png"), full_page=True)
        mobile_overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")
        checks = [
            {"id": "desktop-overflow", "passed": not desktop_overflow, "points": 5 if not desktop_overflow else 0, "maximum": 5},
            {"id": "mobile-overflow", "passed": not mobile_overflow, "points": 5 if not mobile_overflow else 0, "maximum": 5},
            {"id": "filter-interaction", "passed": filter_worked, "points": 4 if filter_worked else 0, "maximum": 4},
            {"id": "theme-interaction", "passed": theme_worked, "points": 3 if theme_worked else 0, "maximum": 3},
            {"id": "console", "passed": not errors, "points": 3 if not errors else 0, "maximum": 3, "detail": errors[:3]},
        ]
        browser.close()
    return {"score": sum(item["points"] for item in checks), "maximum": 20, "status": "graded", "checks": checks}


def _run_route(route: dict[str, str], run_dir: Path, timeout: int) -> dict[str, Any]:
    workdir = run_dir / "sites" / route["id"]
    workdir.mkdir(parents=True, exist_ok=True)
    output_file = run_dir / "terminal" / f"{route['id']}-last-message.txt"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    args = _command(route, workdir, output_file)
    started = time.monotonic()
    try:
        completed = _launch(args, workdir, timeout)
        error = ""
    except subprocess.TimeoutExpired:
        completed = None
        error = f"Timed out after {timeout} seconds."
    elapsed_ms = round((time.monotonic() - started) * 1000)
    stdout = completed.stdout if completed else ""
    stderr = completed.stderr if completed else error
    (run_dir / "terminal" / f"{route['id']}.stdout.txt").write_text(stdout[-200_000:], encoding="utf-8")
    (run_dir / "terminal" / f"{route['id']}.stderr.txt").write_text(stderr[-100_000:], encoding="utf-8")
    index_path = workdir / "index.html"
    static = grade_html(index_path)
    browser = _browser_grade(index_path, run_dir / "screenshots" / route["id"]) if index_path.is_file() else {"score": 0, "maximum": 20, "status": "missing", "checks": []}
    score = combine_score(static, browser)
    return {
        **route,
        "exactRoute": True,
        "fallbackAllowed": False,
        "started": True,
        "exitCode": completed.returncode if completed else None,
        "elapsedMs": elapsed_ms,
        "artifact": str(index_path.relative_to(run_dir)) if index_path.is_file() else None,
        "terminalReceipt": f"terminal/{route['id']}.stdout.txt",
        "score": score,
        "status": "completed" if completed and completed.returncode == 0 and index_path.is_file() else "failed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Neyvia's frozen live HTML site benchmark.")
    parser.add_argument("--proof-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    proof_dir = args.proof_dir.resolve()
    run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    run_dir = proof_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    attempts: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(ROUTES)) as pool:
        futures = {pool.submit(_run_route, route, run_dir, args.timeout): route for route in ROUTES}
        for future in as_completed(futures):
            route = futures[future]
            try:
                attempts.append(future.result())
            except Exception as exc:
                attempts.append({**route, "exactRoute": True, "fallbackAllowed": False, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            print(f"{route['id']}: {attempts[-1].get('status')}", flush=True)
    attempts.sort(key=lambda item: [route["id"] for route in ROUTES].index(item["id"]))
    negative_path = run_dir / "negative-control" / "index.html"
    negative_path.parent.mkdir(parents=True, exist_ok=True)
    negative_path.write_text("<html><body><h1>Lumen Notes</h1><p>Placeholder</p></body></html>\n", encoding="utf-8")
    negative = combine_score(grade_html(negative_path), {"score": 0, "maximum": 20, "status": "intentional-negative", "checks": []})
    completed = [item for item in attempts if item.get("status") == "completed"]
    ranked = sorted(completed, key=lambda item: (-int(item.get("score", {}).get("score") or 0), int(item.get("elapsedMs") or 10**12)))
    report = {
        "schema": SCHEMA,
        "protocolId": PROTOCOL_ID,
        "createdAt": _utc_now(),
        "runId": run_id,
        "frozenPrompt": FROZEN_PROMPT,
        "measurementUnit": "route-plus-model; same-model Codex/OpenCode rows isolate harness differences more closely",
        "attempts": attempts,
        "negativeControl": negative,
        "leader": ranked[0]["id"] if ranked else None,
        "status": "measured" if len(completed) >= 2 and not negative["passed"] else "inconclusive",
    }
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (proof_dir / "latest.json").write_text(json.dumps({"report": str(report_path), "runId": run_id}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "leader": report["leader"], "report": str(report_path)}, indent=2))
    return 0 if report["status"] == "measured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
