from __future__ import annotations

import argparse
import base64
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:1420/control?preview-control=1&fixture=live_review&mode=builder&surface=workbench"
DEFAULT_BACKEND_URL = "http://127.0.0.1:1420"
DEFAULT_MISSION_ID = "workbench_program_bridge"
DEFAULT_PASSWORD_FILE = ROOT / ".agent_control" / "neyvia_admin_password.txt"

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from control_route_interaction_smoke import Cdp, DevToolsSocket, free_port, wait_for_devtools
from control_route_visual_smoke import find_browser, image_stats


def checked_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp() -> str:
    return "".join(char for char in checked_at() if char.isdigit())[:14]


def make_check(check_id: str, passed: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": bool(passed),
        "detail": detail,
        **extra,
    }


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def load_login(password_file: Path, username: str = "", password: str = "") -> tuple[str, str]:
    if username and password:
        return username, password
    text = read_text(password_file)
    next_username = username
    next_password = password
    for line in text.splitlines():
        if not next_username:
            match = re.match(r"\s*Username:\s*(.+?)\s*$", line, flags=re.IGNORECASE)
            if match:
                next_username = match.group(1).strip()
        if not next_password:
            match = re.match(r"\s*Password:\s*(.+?)\s*$", line, flags=re.IGNORECASE)
            if match:
                next_password = match.group(1).strip()
    if not next_username:
        try:
            account = json.loads(read_text(ROOT / ".agent_control" / "neyvia_web_admin.json") or "{}")
        except json.JSONDecodeError:
            account = {}
        next_username = str(account.get("username") or "admin")
    if not next_username or not next_password:
        raise RuntimeError("Missing Fluxio account username or password for workbench bridge verification.")
    return next_username, next_password


def request_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def backend_command_from_page(
    opener: urllib.request.OpenerDirector,
    backend_url: str,
    command: str,
    payload: dict[str, Any],
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    endpoint = urllib.parse.urljoin(backend_url.rstrip("/") + "/", "/api/backend")
    response = request_json(opener, endpoint, {"command": command, "payload": payload}, timeout=timeout)
    if not response.get("ok"):
        raise RuntimeError(str(response.get("error") or f"{command} failed"))
    data = response.get("data")
    return data if isinstance(data, dict) else {"value": data}


def login_backend_from_page(
    opener: urllib.request.OpenerDirector,
    backend_url: str,
    *,
    username: str,
    password: str,
) -> dict[str, Any]:
    endpoint = urllib.parse.urljoin(backend_url.rstrip("/") + "/", "/api/auth/login")
    response = request_json(opener, endpoint, {"username": username, "password": password}, timeout=15)
    if not response.get("ok"):
        raise RuntimeError(str(response.get("error") or "Fluxio login failed"))
    data = response.get("data")
    return data if isinstance(data, dict) else {"authenticated": True}


def probe_backend_health(opener: urllib.request.OpenerDirector, backend_url: str) -> dict[str, Any]:
    endpoint = urllib.parse.urljoin(backend_url.rstrip("/") + "/", "/api/health")
    return request_json(opener, endpoint, timeout=5)


def command_check(
    opener: urllib.request.OpenerDirector,
    backend_url: str,
    command: str,
    payload: dict[str, Any],
    check_id: str,
    *,
    timeout: float = 25.0,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        result = backend_command_from_page(opener, backend_url, command, payload, timeout=timeout)
    except Exception as exc:
        return make_check(check_id, False, str(exc), command=command), None
    return make_check(check_id, True, f"{command} returned data.", command=command), result


def run_runtime_flow(
    opener: urllib.request.OpenerDirector,
    backend_url: str,
    root: Path,
    mission_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    artifacts: dict[str, Any] = {}
    quickstart_check, quickstart = command_check(
        opener,
        backend_url,
        "quickstart_control_room_mission_command",
        {
            "root": str(root),
            "missionId": mission_id,
            "objective": "Verify the workbench program bridge can start a real mission and return proof.",
            "route": "planner/executor/verifier",
        },
        "quickstart_control_room_mission_command",
        timeout=40,
    )
    checks.append(quickstart_check)
    if quickstart:
        artifacts["quickstart"] = quickstart

    quickstart_mission = quickstart.get("mission") if isinstance(quickstart, dict) else {}
    detail_mission_id = str(
        (quickstart or {}).get("missionId")
        or (quickstart or {}).get("id")
        or (quickstart_mission or {}).get("mission_id")
        or (quickstart_mission or {}).get("missionId")
        or mission_id
    )
    detail_check, detail = command_check(
        opener,
        backend_url,
        "get_control_room_mission_detail_command",
        {"root": str(root), "missionId": detail_mission_id, "eventLimit": 60},
        "get_control_room_mission_detail_command",
        timeout=30,
    )
    checks.append(detail_check)
    if detail:
        artifacts["missionDetail"] = detail

    runtime_events = []
    mission_state = {}
    if isinstance(detail, dict):
        mission_payload = detail.get("mission") if isinstance(detail.get("mission"), dict) else {}
        mission_state = mission_payload.get("state") if isinstance(mission_payload.get("state"), dict) else {}
        events = detail.get("events") or detail.get("timeline") or []
        if isinstance(events, list):
            runtime_events = [
                item for item in events
                if isinstance(item, dict)
                and str(item.get("kind") or item.get("type") or "").lower() in {"command.execution", "runtime.output", "agent.reply"}
            ]
    runtime_status = str(mission_state.get("status") or "").lower()
    queue_reason = str(mission_state.get("queue_reason") or "").strip()
    execution_proven = bool(detail) and bool(runtime_events)
    checks.append(
        make_check(
            "runtime-execution-proof-present",
            execution_proven,
            (
                "Mission detail includes runtime execution proof."
                if runtime_events
                else "Mission detail did not expose runtime execution proof yet."
            ),
            missionId=detail_mission_id,
            missionStatus=runtime_status,
            queueReason=queue_reason,
            eventCount=len(runtime_events),
        )
    )
    return checks, artifacts


def wait_for_selector(cdp: Cdp, selector: str, timeout: float = 12.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    expression = f"""
(() => {{
  const node = document.querySelector({json.dumps(selector)});
  if (!node) return {{ found: false }};
  const rect = node.getBoundingClientRect();
  return {{
    found: true,
    tagName: node.tagName,
    src: node.getAttribute("src") || "",
    width: Math.round(rect.width),
    height: Math.round(rect.height),
    visible: rect.width > 20 && rect.height > 20,
    text: (node.innerText || "").slice(0, 500),
  }};
}})()
"""
    while time.time() < deadline:
        value = cdp.eval(expression)
        if isinstance(value, dict) and value.get("found"):
            return value
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for selector: {selector}")


def cdp_eval(cdp: Cdp, expression: str) -> Any:
    return cdp.eval(expression)


def click_selector(cdp: Cdp, selector: str) -> dict[str, Any]:
    result = cdp.eval(
        f"""
(() => {{
  const node = document.querySelector({json.dumps(selector)});
  if (!node) return {{ clicked: false, selector: {json.dumps(selector)} }};
  const rect = node.getBoundingClientRect();
  node.click();
  return {{
    clicked: true,
    selector: {json.dumps(selector)},
    text: (node.innerText || node.getAttribute('aria-label') || '').slice(0, 200),
    width: Math.round(rect.width),
    height: Math.round(rect.height)
  }};
}})()
"""
    )
    return result if isinstance(result, dict) else {"clicked": False, "selector": selector, "result": result}


def url_with_surface(url: str, surface: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["surface"] = surface
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def capture_screenshot(cdp: Cdp, path: Path) -> str:
    result = cdp.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
    encoded = result.get("data") if isinstance(result, dict) else None
    if not isinstance(encoded, str):
        raise RuntimeError("CDP screenshot did not return image data.")
    path.write_bytes(base64.b64decode(encoded))
    return str(path)


def verify_browser_preview(
    base_url: str,
    out_dir: Path,
    browser: str,
    browser_path: str,
    username: str,
    password: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    report: dict[str, Any] = {"baseUrl": base_url, "screenshots": {}}
    folder_browser_payload: dict[str, Any] = {
        "selector": '[data-browser-workspace="true"]',
        "visible": False,
    }
    port = free_port()
    executable = find_browser(browser, browser_path)
    profile = tempfile.TemporaryDirectory(prefix="fluxio-program-bridge-")
    process = subprocess.Popen(
        [
            executable,
            "--headless",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-sandbox",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile.name}",
            "--window-size=1440,1200",
            "about:blank",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    ws: DevToolsSocket | None = None
    try:
        tabs = wait_for_devtools(port)
        ws = DevToolsSocket(str(tabs[0]["webSocketDebuggerUrl"]))
        cdp = Cdp(ws)
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Page.navigate", {"url": base_url})
        time.sleep(0.75)
        if not username or not password:
            checks.append(make_check("browser-login-authenticated", False, "Browser proof did not receive local account credentials."))
        else:
            login_result = cdp.eval(
                f"""
(async () => {{
  const response = await fetch('/api/auth/login', {{
    method: 'POST',
    credentials: 'include',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ username: {json.dumps(username)}, password: {json.dumps(password)} }})
  }});
  const body = await response.json().catch(() => ({{}}));
  return {{ ok: response.ok && body && body.ok !== false, status: response.status, authenticated: Boolean(body?.data?.authenticated) }};
}})()
""",
                await_promise=True,
            )
            checks.append(
                make_check(
                    "browser-login-authenticated",
                    isinstance(login_result, dict) and bool(login_result.get("ok")),
                    "Browser context logged into the local Fluxio account.",
                    status=login_result.get("status") if isinstance(login_result, dict) else None,
                    authenticated=login_result.get("authenticated") if isinstance(login_result, dict) else None,
                )
            )

        cdp.send("Page.navigate", {"url": base_url})
        wait_for_selector(cdp, ".fluxos-shell", timeout=18.0)
        agent_thread = wait_for_selector(cdp, '[data-agent-chat-thread="true"]', timeout=15.0)
        checks.append(
            make_check(
                "agent-shell-authenticated",
                bool(agent_thread.get("visible")),
                "Authenticated Agent shell is ready before browser handoff.",
                agentThread=agent_thread,
                url=base_url,
            )
        )

        browser_click = click_selector(cdp, 'button[aria-label="Open Browser"]')
        workbench = wait_for_selector(cdp, '[data-browser-workspace="true"]', timeout=18.0)
        checks.append(
            make_check(
                "workbench-computer-use-surface-visible",
                bool(browser_click.get("clicked")) and bool(workbench.get("visible")),
                "Workbench handoff opens the browser/computer-use workspace from the rail.",
                browserClick=browser_click,
                workbench=workbench,
                url=base_url,
            )
        )

        folder_browser_payload = cdp_eval(
            cdp,
            """(() => {
  const node = document.querySelector('[data-browser-workspace="true"]');
  if (!node) return { selector: '[data-browser-workspace="true"]', visible: false };
  const rect = node.getBoundingClientRect();
  return {
    selector: '[data-browser-workspace="true"]',
    visible: rect.width > 20 && rect.height > 20,
    width: Math.round(rect.width),
    height: Math.round(rect.height)
  };
})()""",
        )
        checks.append(
            make_check(
                "browser-workspace-preview-not-black-box",
                bool(isinstance(folder_browser_payload, dict) and folder_browser_payload.get("visible")),
                "Browser workspace preview is visible.",
                folderBrowser=folder_browser_payload,
                url=base_url,
            )
        )
        screenshot_path = out_dir / "browser-workspace-preview.png"
        capture_screenshot(cdp, screenshot_path)
        screenshotStats = image_stats(screenshot_path)
        checks.append(
            make_check(
                "screenshot-nonblank",
                bool(screenshotStats.get("nonBlank")),
                "Preview screenshot has enough pixel variance to be useful.",
                screenshotStats=screenshotStats,
            )
        )
        report["screenshots"] = {"browserWorkspacePreview": str(screenshot_path)}
        report["screenshotStats"] = screenshotStats
    finally:
        if ws:
            ws.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        profile.cleanup()
    return checks, report, folder_browser_payload if isinstance(folder_browser_payload, dict) else {}


def write_report(root: Path, mission_id: str, report: dict[str, Any]) -> Path:
    out_dir = root / ".agent_control" / "mission_artifacts" / mission_id / "workbench_program_bridge"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{stamp()}_workbench_program_bridge.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def run_bounded_program_fixtures(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Exercise the real bounded process path without pretending to capture an OS window."""

    checks: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="neyvia-program-fixtures-", dir=str(root)) as temp_dir:
        fixture_root = Path(temp_dir)
        success_target = fixture_root / "success_fixture.py"
        failure_target = fixture_root / "failure_fixture.py"
        success_target.write_text("print('NEYVIA_PROGRAM_SUCCESS')\n", encoding="utf-8")
        failure_target.write_text("import sys\nprint('NEYVIA_PROGRAM_FAILURE', file=sys.stderr)\nsys.exit(7)\n", encoding="utf-8")
        for check_id, target, expected_code, expected_marker in (
            ("program-fixture-success", success_target, 0, "NEYVIA_PROGRAM_SUCCESS"),
            ("program-fixture-failure", failure_target, 7, "NEYVIA_PROGRAM_FAILURE"),
        ):
            started = time.perf_counter()
            completed = subprocess.run(
                [sys.executable, str(target)],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            execution = {
                "target": str(target),
                "command": [sys.executable, str(target)],
                "exitCode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
                "processObserved": True,
                "visualCapture": {
                    "status": "unsupported",
                    "detail": "This verifier records bounded process evidence; OS-window capture requires a separate sandbox adapter.",
                },
            }
            executions.append(execution)
            checks.append(
                make_check(
                    check_id,
                    completed.returncode == expected_code and expected_marker in (completed.stdout + completed.stderr),
                    f"Observed process exit={completed.returncode}; target={target.name}.",
                    execution=execution,
                )
            )
    return checks, {
        "status": "bounded_process_receipts",
        "visualCapture": "unsupported_without_sandbox_adapter",
        "executions": executions,
    }


def attach_proof(
    opener: urllib.request.OpenerDirector,
    backend_url: str,
    root: Path,
    mission_id: str,
    report_path: Path,
    checks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    artifact_payload = {
        "kind": "workbench_program_bridge_report",
        "path": str(report_path),
        "status": "passed" if all(item.get("passed") for item in checks) else "incomplete",
    }
    proofAttachment_check, proofAttachment = command_check(
        opener,
        backend_url,
        "attach_verifier_proof_command",
        {
            "root": str(root),
            "missionId": mission_id,
            "flowId": "workbench-program-bridge",
            "reportPath": str(report_path),
            "artifacts": [artifact_payload],
            "checks": checks,
        },
        "proof-attaches-verifier-artifacts",
        timeout=25,
    )
    proofAttachment_check["proofAttachment"] = proofAttachment
    return [proofAttachment_check], proofAttachment


def record_preview_bridge_proof(
    opener: urllib.request.OpenerDirector,
    backend_url: str,
    root: Path,
    mission_id: str,
    base_url: str,
    report_path: Path,
    report: dict[str, Any],
    folder_browser_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    check, result = command_check(
        opener,
        backend_url,
        "record_preview_bridge_proof_command",
        {
            "root": str(root),
            "missionId": mission_id,
            "baseUrl": base_url,
            "programUrl": base_url,
            "previewUrl": base_url,
            "reportPath": str(report_path),
            "screenshots": report["screenshots"],
            "folderBrowser": folder_browser_payload,
            "clicks": 1,
            "checks": report.get("checks", []),
        },
        "preview-bridge-proof-attached-to-run",
        timeout=25,
    )
    return [check], result


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    root = Path(args.root).expanduser().resolve()
    mission_id = args.mission_id
    out_dir = root / ".agent_control" / "mission_artifacts" / mission_id / "workbench_program_bridge"
    out_dir.mkdir(parents=True, exist_ok=True)
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    checks: list[dict[str, Any]] = []
    command_artifacts: dict[str, Any] = {}
    browser_report: dict[str, Any] = {"screenshots": {}}
    folder_browser_payload: dict[str, Any] = {"selector": '[data-browser-workspace="true"]', "visible": False}

    try:
        health = probe_backend_health(opener, args.backend_url)
        checks.append(make_check("backend-health", bool(health.get("ok")), "Backend health endpoint responded.", health=health))
    except Exception as exc:
        checks.append(make_check("backend-health", False, str(exc)))

    env_username = os.environ.get("FLUXIO_WEB_USERNAME") or os.environ.get("SYNTELOS_ACCOUNT_USERNAME")
    env_password = os.environ.get("FLUXIO_WEB_PASSWORD") or os.environ.get("SYNTELOS_ACCOUNT_PASSWORD")
    username = ""
    password = ""
    try:
        username, password = load_login(Path(args.password_file), args.username or env_username or "", args.password or env_password or "")
        try:
            login = login_backend_from_page(opener, args.backend_url, username=username, password=password)
            checks.append(make_check("backend-login", bool(login.get("authenticated")), "Backend login succeeded."))
        except Exception as exc:
            checks.append(make_check("backend-login", False, str(exc)))
    except Exception as exc:
        checks.append(make_check("backend-login", False, str(exc), passwordFile=str(Path(args.password_file))))

    storage_check, storage = command_check(
        opener,
        args.backend_url,
        "get_nas_storage_pressure_command",
        {"root": str(root), "path": str(root), "writeLatest": True},
        "nas-live-storage-pressure-refresh",
        timeout=25,
    )
    checks.append(storage_check)
    if storage:
        command_artifacts["storagePressure"] = storage

    if args.run_runtime_flow:
        runtime_checks, runtime_artifacts = run_runtime_flow(opener, args.backend_url, root, mission_id)
        checks.extend(runtime_checks)
        command_artifacts["runtimeFlow"] = runtime_artifacts

    program_checks, program_execution = run_bounded_program_fixtures(root)
    checks.extend(program_checks)
    command_artifacts["programExecution"] = program_execution

    if args.with_browser:
        try:
            browser_checks, browser_report, folder_browser_payload = verify_browser_preview(
                args.base_url,
                out_dir,
                args.browser,
                args.browser_path,
                username,
                password,
            )
            checks.extend(browser_checks)
        except Exception as exc:
            checks.append(make_check("browser-preview-cdp", False, str(exc)))
    else:
        checks.append(make_check("browser-preview-cdp", False, "Browser CDP proof skipped; pass --with-browser to run it."))

    report = {
        "schema": "fluxio.workbench_program_bridge.v1",
        "checkedAt": checked_at(),
        "root": str(root),
        "baseUrl": args.base_url,
        "backendUrl": args.backend_url,
        "missionId": mission_id,
        "status": "passed" if checks and all(item.get("passed") for item in checks) else "incomplete",
        "checks": checks,
        "screenshots": browser_report.get("screenshots", {}),
        "screenshotStats": browser_report.get("screenshotStats", {}),
        "commands": command_artifacts,
        "folderBrowser": folder_browser_payload,
    }
    report_path = write_report(root, mission_id, report)
    report["reportPath"] = str(report_path)

    attachment_checks, attachment = attach_proof(opener, args.backend_url, root, mission_id, report_path, checks)
    checks.extend(attachment_checks)
    if attachment:
        report["proofAttachment"] = attachment

    preview_checks, preview_attachment = record_preview_bridge_proof(
        opener,
        args.backend_url,
        root,
        mission_id,
        args.base_url,
        report_path,
        report,
        folder_browser_payload,
    )
    checks.extend(preview_checks)
    if preview_attachment:
        report["previewBridgeAttachment"] = preview_attachment

    report["status"] = "passed" if checks and all(item.get("passed") for item in checks) else "incomplete"
    report["checks"] = checks
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report, 0 if report["status"] == "passed" or args.allow_incomplete else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Fluxio workbench program bridge and attach durable proof.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--mission-id", default=DEFAULT_MISSION_ID)
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument(
        "--password-file",
        default=str(DEFAULT_PASSWORD_FILE),
        help="Ignored local account password file. The verifier never prints the secret.",
    )
    parser.add_argument("--run-runtime-flow", action="store_true")
    parser.add_argument("--with-browser", action="store_true")
    parser.add_argument("--browser", choices=["auto", "chrome", "chromium", "edge", "zen"], default="auto")
    parser.add_argument("--browser-path", default="")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()

    report, exit_code = build_report(args)
    failed = [item for item in report.get("checks", []) if not item.get("passed")]
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "summary": f"{len(report.get('checks', [])) - len(failed)}/{len(report.get('checks', []))} workbench bridge checks passed.",
                "reportPath": report.get("reportPath"),
                "failedChecks": [
                    {"id": item.get("id"), "detail": item.get("detail")}
                    for item in failed[:8]
                ],
            },
            indent=2,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
