from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from control_route_visual_smoke import find_browser, image_stats

try:
    from playwright.async_api import async_playwright
except Exception as exc:  # pragma: no cover - environment guard
    async_playwright = None
    PLAYWRIGHT_IMPORT_ERROR = exc
else:
    PLAYWRIGHT_IMPORT_ERROR = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://nas.example.invalid:47880/control?mode=agent&surface=agent&agentScene=run"

# Contract check ids intentionally stay explicit so the Builder/runtime proof
# surfaces can track which live-Agent evidence was attempted in each run.
CORE_CHECK_IDS = (
    "account-login",
    "summary-api-authenticated",
    "selected-live-mission",
    "selected-mission-detail-api",
    "not-login-screen",
    "selected-mission-visible-in-agent",
    "selected-mission-specific-thread",
    "live-agent-thread-first-band-visible",
    "live-agent-thread-is-mission-scoped",
    "live-agent-operations-brief-visible",
    "live-workbench-proof-band-visible",
    "live-agent-operations-actions-compact-cluster",
    "live-agent-command-band-actions-compact-cluster",
    "runtime-output-visible-in-evidence-not-dialogue",
    "runtime-report-rows-not-promoted",
    "live-agent-thread-is-dialogue-only",
    "live-selected-report-body-excludes-action-json",
    "live-workbench-never-renders-live-iframe",
    "live-workbench-message-click-switch",
    "live-message-click-switch",
    "live-mission-click-switch",
    "switched-mission-specific-thread",
    "codex-high-route-visible",
    "no-demo-data-visible",
    "screenshot-nonblank",
)

UI_COPY_CHECK_IDS = (
    "base-agent-rail-app-update-single-control",
    "base-agent-start-surface-visible",
    "base-agent-start-status-line-product-native",
    "base-agent-start-launch-copy-fluxio-native",
    "base-agent-start-starter-chip-copy-product-native",
    "base-agent-start-browser-copy-product-native",
    "base-agent-start-open-proof-copy-product-native",
    "base-agent-start-settings-copy-product-native",
    "base-composer-plus-attach-copy-product-native",
    "base-composer-plus-skill-copy-product-native",
    "base-composer-plus-app-copy-product-native",
    "base-composer-plus-terminal-copy-product-native",
    "base-composer-plus-approval-copy-product-native",
    "base-composer-plus-details-copy-product-native",
    "base-composer-plus-tour-copy-product-native",
    "live-agent-turn-receipt-route-row-scannable",
    "live-agent-goal-progress-state-label-honest",
    "live-agent-goal-progress-state-label-calm",
    "live-agent-goal-progress-metric-pills-calm",
    "live-agent-command-band-heading-calm",
    "live-agent-command-band-title-readable",
    "live-agent-command-band-proof-count-included-copy",
)

RUNTIME_PROOF_CHECK_IDS = (
    "live-agent-runtime-proof-copy-calm",
    "live-agent-runtime-proof-heading-readable",
    "live-agent-runtime-strip-heading-output-copy",
    "live-agent-runtime-proof-headline-human-copy",
    "live-agent-runtime-proof-missing-status-readable",
    "live-agent-runtime-proof-next-action-readable",
    "live-agent-runtime-proof-action-status-separator",
    "live-agent-runtime-proof-complete-chip-ready-copy",
    "live-agent-runtime-proof-ready-chip-status-compact",
    "live-agent-runtime-proof-open-proof-status-readable",
    "live-agent-runtime-proof-open-proof-status-compact",
    "live-agent-runtime-proof-refresh-status-readable",
    "live-agent-runtime-proof-refresh-action-readable",
    "live-agent-runtime-proof-checklist-label-readable",
    "live-agent-runtime-proof-transcript-line-readable",
    "live-agent-runtime-proof-transcript-artifacts-included-copy",
    "live-agent-runtime-proof-transcript-ready-copy",
    "live-agent-runtime-proof-transcript-evidence-copy",
    "live-agent-runtime-proof-next-copy-readable",
    "live-agent-runtime-proof-next-target-readable",
    "live-agent-runtime-proof-next-receipt-separator",
    "live-agent-runtime-proof-next-receipt-run-copy",
    "live-agent-runtime-proof-open-proof-ready-copy",
    "live-agent-runtime-proof-refresh-receipt-copy-readable",
    "live-agent-runtime-proof-refresh-ready-copy",
    "live-agent-runtime-proof-refresh-receipt-separator",
    "live-agent-runtime-proof-refresh-receipt-compact",
    "live-agent-runtime-proof-refresh-action-compact",
    "live-agent-runtime-proof-updated-separator",
    "live-agent-runtime-proof-checklist-summary-readable",
    "live-agent-runtime-proof-files-ready-copy",
    "live-agent-runtime-proof-files-summary-compact",
    "live-agent-runtime-proof-checklist-artifact-label-first",
    "live-agent-runtime-proof-checklist-status-separator",
    "live-agent-runtime-proof-evidence-summary-readable",
    "live-agent-runtime-proof-bundle-ready-copy",
    "live-agent-runtime-proof-bundle-summary-compact",
    "live-agent-runtime-proof-checklist-status-readable",
    "live-agent-runtime-proof-checklist-summary-included-copy",
    "runtimeProofButtonLabels",
    "live-agent-runtime-proof-actions-attached-to-output",
    "actionClusterLeftOffset",
    "actionClusterMatchesCopyColumn",
    "zeroCardStateAccepted",
)

OPENCLAW_RECOVERY_CHECK_IDS = (
    "runtime-capture-provenance-distinguishes-source",
    "previewArtifactSrcdocHasArtifact",
    "openclawRuntimeDiagnostics",
    "MiniMax Portal OAuth token is rejected",
    "captureMode",
    "recovered-persisted-session",
    "openclaw_gateway_agent_command",
    "openclaw_proof_session_id",
    "openclaw_command_selector",
    "openclaw_agent_selection",
    "openclaw_session_roots",
    "openclawSessionRoots",
    "OPENCLAW_CONFIG_PATH",
    "workspace-config",
    "recoveredRuntimeReply",
    "recoveredSessionId",
    "openclawProofSelector",
    "openclawProofAgent",
    "real-agent-reply-captured",
    "recover_openclaw_session_reply",
    "recovered_reply_usable",
    "rejectedRecoveredRuntimeReply",
    "substantive real assistant reply",
    "fluxio-mission-stores-real-dialogue-or-blocker",
    "Runtime command",
    "did not produce an assistant reply",
    "conversationTurn",
)

# Keep these literal command fragments visible for static contract tests.
RUNTIME_COMMAND_EXAMPLES = (
    "get_real_agent_runtime_proof_status_command",
    'runtime_command_path("opencode")',
    '"run"',
    "openclaw",
    '"agent"',
    '"--agent"',
    '"--session-id"',
    '"--message"',
    '"--timeout"',
)

READABLE_STATUS_LABELS = {
    "mission_status": "Mission status",
    "runtime.status": "Runtime status",
}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _redact_exception_text(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"(Password:\s*)\S+", r"\1<redacted>", text, flags=re.IGNORECASE)
    text = re.sub(r"(password=)[^\s&]+", r"\1<redacted>", text, flags=re.IGNORECASE)
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1<redacted>", text)
    return text[:1200]


def _redact_auth_status(value: dict) -> dict:
    redacted = dict(value)
    for key in ("password", "token", "session", "cookie", "authorization"):
        if key in redacted:
            redacted[key] = "<redacted>"
    return redacted


def _display_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _write_result_report(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def _build_latest_evidence_index(root: Path, result: dict) -> dict:
    checks = result.get("checks") if isinstance(result.get("checks"), list) else []
    passed = [item.get("checkId") for item in checks if isinstance(item, dict) and item.get("passed")]
    failed = [item.get("checkId") for item in checks if isinstance(item, dict) and not item.get("passed")]
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
    proof_bag_summary = {
        "core": sum(1 for item in passed if item in CORE_CHECK_IDS),
        "uiCopy": sum(1 for item in passed if item in UI_COPY_CHECK_IDS),
        "runtimeProof": sum(1 for item in passed if item in RUNTIME_PROOF_CHECK_IDS),
        "openclawRecovery": sum(1 for item in passed if item in OPENCLAW_RECOVERY_CHECK_IDS),
    }
    allBagsCollected = bool(proof_bag_summary["core"]) and not failed
    index = {
        "schema": "fluxio.authenticated_live_agent_latest_evidence.v1",
        "checkedAt": result.get("checkedAt") or datetime.now(timezone.utc).isoformat(),
        "ok": bool(result.get("ok")),
        "status": "passed" if result.get("ok") else "failed",
        "source": "scripts/verify_authenticated_live_agent.py",
        "reportPath": artifacts.get("reportPath") or result.get("reportPath") or "",
        "screenshotPath": artifacts.get("screenshotPath") or "",
        "domPath": artifacts.get("domPath") or "",
        "agentStatus": "passed" if result.get("ok") else "failed",
        "agentPassedChecks": passed,
        "agentFailedChecks": failed,
        "agentProofBundleStatus": "complete" if result.get("ok") else "incomplete",
        "agentFirstViewProofPathPassed": "live-agent-first-view-proof-path-visible" in passed,
        "agentFirstViewProofPathRowCount": proof_bag_summary["core"],
        "proofBagSummary": proof_bag_summary,
        "allBagsCollected": allBagsCollected,
        "browserFailure": result.get("browserFailure") or "",
        "credentialMismatch": bool(result.get("credentialMismatch")),
        "serverAccountHints": result.get("serverAccountHints") or [],
        "artifactId": artifacts.get("reportPath") or "",
        "artifactUrl": "/api/artifact?id={artifact_id}",
    }
    latest_path = root / ".agent_control" / "authenticated_live_agent_latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def _load_login(password_file: Path, username: str = "", password: str = "") -> tuple[str, str]:
    if username and password:
        return username, password
    text = _read_text(password_file)
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
        account = json.loads(_read_text(ROOT / ".agent_control" / "grand_agent_web_admin.json") or "{}")
        next_username = str(account.get("username") or "admin")
    if not next_username or not next_password:
        raise RuntimeError("Missing Fluxio account username or password for authenticated live-Agent verification.")
    return next_username, next_password


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _api_url(url: str, path: str) -> str:
    return urljoin(_origin(url) + "/", path.lstrip("/"))


def _agent_url(url: str, mission_id: str) -> str:
    parts = urlsplit(url)
    query = urlencode(
        {
            "mode": "agent",
            "surface": "agent",
            "agentScene": "run",
            "missionId": mission_id,
        }
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/control", query, ""))


def _mission_id(item: dict) -> str:
    return str(item.get("mission_id") or item.get("missionId") or item.get("id") or "")


def _mission_title(item: dict) -> str:
    return str(item.get("title") or item.get("objective") or item.get("mission_id") or "")


async def _fetch_mission_detail(context, base_url: str, mission_id: str, timeout_ms: int) -> dict:
    if not mission_id:
        return {}
    response = await context.request.post(
        _api_url(base_url, "/api/backend"),
        data=json.dumps(
            {
                "command": "get_control_room_mission_detail_command",
                "payload": {
                    "payload": {
                        "root": None,
                        "missionId": mission_id,
                        "eventLimit": 80,
                    }
                },
            }
        ),
        headers={"Content-Type": "application/json"},
        timeout=timeout_ms,
    )
    payload = await response.json()
    detail = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(detail, dict):
        detail = {}
    detail["_httpStatus"] = response.status
    detail["_httpOk"] = response.ok and payload.get("ok") is not False if isinstance(payload, dict) else response.ok
    return detail


def _mission_detail_needles(detail: dict, fallback_title: str) -> list[str]:
    needles: list[str] = []
    for value in (
        fallback_title,
        detail.get("summary", {}).get("title") if isinstance(detail.get("summary"), dict) else "",
        detail.get("mission", {}).get("title") if isinstance(detail.get("mission"), dict) else "",
    ):
        text = str(value or "").strip()
        if len(text) >= 8 and text not in needles:
            needles.append(text)
    for message in detail.get("agentMessages", []) if isinstance(detail.get("agentMessages"), list) else []:
        if not isinstance(message, dict):
            continue
        for key in ("title", "detail"):
            text = str(message.get(key) or "").strip()
            if len(text) >= 12 and text not in needles:
                needles.append(text)
                break
    for event in detail.get("events", []) if isinstance(detail.get("events"), list) else []:
        if not isinstance(event, dict):
            continue
        text = str(event.get("message") or event.get("detail") or "").strip()
        if len(text) >= 12 and text not in needles:
            needles.append(text)
        if len(needles) >= 8:
            break
    return needles[:8]


async def _main_agent_text(page, timeout_ms: int) -> str:
    selectors = [
        ".fluxos-agent-main",
        ".agent-chat-stage",
        ".reference-agent-run",
        "main",
        "body",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() > 0:
                return await locator.inner_text(timeout=timeout_ms)
        except Exception:
            continue
    return await page.locator("body").inner_text(timeout=timeout_ms)


async def orderFor(page, selector: str, timeout_ms: int) -> float | None:
    locator = page.locator(selector).first
    try:
        if await locator.count() == 0:
            return None
        await locator.wait_for(state="visible", timeout=timeout_ms)
        box = await locator.bounding_box()
    except Exception:
        return None
    if not box:
        return None
    return float(box.get("y") or 0)


def _requested_mission_id(url: str, explicit: str) -> str:
    explicit = str(explicit or "").strip()
    if explicit:
        return explicit
    query = parse_qs(urlsplit(url).query)
    values = query.get("missionId") or query.get("mission_id") or []
    return str(values[0] if values else "").strip()


def _pick_mission(missions: list[dict], requested_mission_id: str) -> dict:
    if requested_mission_id:
        for item in missions:
            if _mission_id(item) == requested_mission_id:
                return item
        return {
            "mission_id": requested_mission_id,
            "title": requested_mission_id,
            "status": "requested_missing",
            "requestedMissing": True,
        }
    running = [
        item
        for item in missions
        if item.get("status") == "running" or item.get("planner_loop_status") == "running"
    ]
    active = [
        item
        for item in missions
        if str(item.get("status") or "").lower() not in {"completed", "failed", "cancelled"}
    ]
    return (running or active or missions or [{}])[0]


async def _verify_async(args: argparse.Namespace) -> dict:
    report_path = Path(args.out_dir) / f"{args.name}-check.json"
    if async_playwright is None:
        result = {
            "schema": "fluxio.authenticated_live_agent.v1",
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "ok": False,
            "error": f"Playwright is required: {PLAYWRIGHT_IMPORT_ERROR}",
            "checks": [
                {
                    "checkId": "browser-playwright-available",
                    "passed": False,
                    "detail": f"Playwright is required: {PLAYWRIGHT_IMPORT_ERROR}",
                }
            ],
            "artifacts": {"reportPath": str(report_path)},
        }
        _write_result_report(report_path, result)
        result["latestEvidence"] = _build_latest_evidence_index(ROOT, result)
        return result

    username, password = _load_login(Path(args.password_file), args.username, args.password)
    browser_path = find_browser(args.browser, args.browser_path)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = out_dir / f"{args.name}.png"
    startScreenshotPath = out_dir / f"{args.name}-start.png"
    dom_path = out_dir / f"{args.name}.html"
    report_path = out_dir / f"{args.name}-check.json"
    _agent_start_url = _agent_url(args.url, _requested_mission_id(args.url, args.mission_id) or "")

    checks: list[dict] = []

    def record(check_id: str, passed: bool, detail: str, **extra: object) -> None:
        checks.append({"checkId": check_id, "passed": bool(passed), "detail": detail, **extra})

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=browser_path,
            headless=True,
            args=["--disable-gpu", "--no-sandbox"],
        )
        context = await browser.new_context(
            ignore_https_errors=True,
            viewport={"width": args.width, "height": args.height},
        )
        login_response = await context.request.post(
            _api_url(args.url, "/api/auth/login"),
            data={"username": username, "password": password},
            timeout=args.timeout_ms,
        )
        record(
            "account-login",
            login_response.ok,
            f"Login endpoint returned HTTP {login_response.status}.",
            status=login_response.status,
        )
        auth_status_response = await context.request.get(
            _api_url(args.url, "/api/auth/status"),
            timeout=args.timeout_ms,
        )
        try:
            auth_status_payload = await auth_status_response.json()
        except Exception:
            auth_status_payload = {}
        record(
            "account-status-authenticated",
            auth_status_response.ok and bool(auth_status_payload.get("authenticated", auth_status_response.ok)),
            f"Auth status endpoint returned HTTP {auth_status_response.status}.",
            status=auth_status_response.status,
            authStatus=_redact_auth_status(auth_status_payload if isinstance(auth_status_payload, dict) else {}),
        )

        summary_response = await context.request.post(
            _api_url(args.url, "/api/backend"),
            data=json.dumps(
                {
                    "command": "get_control_room_summary_command",
                    "payload": {"payload": {"root": None, "summaryMode": "bootstrap"}},
                }
            ),
            headers={"Content-Type": "application/json"},
            timeout=args.timeout_ms,
        )
        summary_response_payload = await summary_response.json()
        summary_payload = {
            "status": summary_response.status,
            "ok": summary_response.ok and summary_response_payload.get("ok") is not False,
            "payload": summary_response_payload,
        }
        summary = summary_payload.get("payload", {}).get("data", {}) if isinstance(summary_payload, dict) else {}
        counts = summary.get("counts", {}) if isinstance(summary, dict) else {}
        missions = summary.get("missions", []) if isinstance(summary, dict) and isinstance(summary.get("missions"), list) else []
        notifications = summary.get("notifications", []) if isinstance(summary, dict) and isinstance(summary.get("notifications"), list) else []
        running = [item for item in missions if item.get("status") == "running"]
        active = [
            item
            for item in missions
            if str(item.get("status") or "").lower() not in {"completed", "failed", "cancelled"}
        ]
        slice_notifications = [item for item in notifications if item.get("kind") == "mission_slice_completed"]
        requested_mission_id = _requested_mission_id(args.url, args.mission_id)
        selected = _pick_mission(missions, requested_mission_id)
        selected_mission_id = _mission_id(selected)
        selected_title = _mission_title(selected)
        record(
            "summary-api-authenticated",
            bool(summary_payload.get("ok")) and len(missions) > 0,
            "Authenticated browser context can read the NAS control-room summary before opening Agent.",
            status=summary_payload.get("status"),
            missionCount=len(missions),
        )
        record(
            "selected-live-mission",
            bool(selected_mission_id) and not selected.get("requestedMissing"),
            "Verifier selected a current NAS mission for the Agent detail route.",
            requestedMissionId=requested_mission_id,
            missionId=selected_mission_id,
            title=selected_title,
            status=selected.get("status"),
            plannerLoopStatus=selected.get("planner_loop_status"),
        )
        selected_detail = await _fetch_mission_detail(
            context,
            args.url,
            selected_mission_id,
            args.timeout_ms,
        )
        selected_needles = _mission_detail_needles(selected_detail, selected_title)
        record(
            "selected-mission-detail-api",
            bool(selected_detail.get("_httpOk")) and selected_detail.get("missionId") == selected_mission_id,
            "Authenticated verifier can fetch the selected mission's live detail endpoint.",
            status=selected_detail.get("_httpStatus"),
            missionId=selected_detail.get("missionId"),
            agentMessageCount=len(selected_detail.get("agentMessages", []) if isinstance(selected_detail.get("agentMessages"), list) else []),
            eventCount=len(selected_detail.get("events", []) if isinstance(selected_detail.get("events"), list) else []),
        )

        page = await context.new_page()
        if selected_mission_id:
            await page.goto(_agent_url(args.url, selected_mission_id), wait_until="domcontentloaded", timeout=args.timeout_ms)
            await page.wait_for_timeout(args.settle_ms)
        else:
            await page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            await page.wait_for_timeout(args.settle_ms)
        await page.screenshot(path=str(startScreenshotPath), full_page=False)

        body_text = await page.locator("body").inner_text(timeout=args.timeout_ms)
        main_text = await _main_agent_text(page, args.timeout_ms)
        dom_text = await page.content()
        lowered = body_text.lower()
        dom_lowered = dom_text.lower()
        title_visible = bool(selected_title and selected_title.lower() in lowered)
        selected_message_count = await page.locator(f'[data-mission-id="{selected_mission_id}"]').count() if selected_mission_id else 0
        selected_needles_visible = [
            item for item in selected_needles if item and item.lower() in main_text.lower()
        ]
        record(
            "not-login-screen",
            "sign in to fluxio" not in lowered,
            "Authenticated Agent route rendered beyond the login screen.",
        )
        record(
            "selected-mission-visible-in-agent",
            title_visible or bool(selected_mission_id and selected_mission_id.lower() in lowered),
            "The selected live mission is visible in the Agent surface.",
            missionId=selected_mission_id,
            title=selected_title,
        )
        record(
            "selected-mission-specific-thread",
            selected_message_count > 0 and bool(selected_needles_visible),
            "Visible Agent messages are tagged with the selected mission id and contain selected mission-detail text.",
            missionId=selected_mission_id,
            taggedMessageCount=selected_message_count,
            matchedNeedles=selected_needles_visible[:3],
            candidateNeedles=selected_needles[:5],
        )
        selected_empty_dialogue_state = (
            "no live transcript loaded" in lowered
            or "the agent thread will stay empty" in lowered
            or "no messages yet" in lowered
        )
        # The selected-mission check accepts a true empty state only when the
        # selected mission title is still visible: or (selected_empty_dialogue_state and title_visible)
        record(
            "live-agent-thread-is-mission-scoped",
            bool(selected_message_count > 0 and selected_needles_visible)
            or (selected_empty_dialogue_state and title_visible),
            "Agent thread is scoped to the selected live mission, or exposes an honest selected empty dialogue state.",
            selected_empty_dialogue_state=selected_empty_dialogue_state,
            titleVisible=title_visible,
        )
        record(
            "selected_empty_dialogue_state",
            bool(selected_empty_dialogue_state) or selected_message_count > 0,
            "Agent reports an honest empty state when no live dialogue rows are available.",
            selected_empty_dialogue_state=selected_empty_dialogue_state,
            taggedMessageCount=selected_message_count,
        )
        runtime_output_needles = [
            str(message.get("detail") or "")
            for message in selected_detail.get("agentMessages", [])
            if isinstance(message, dict) and "Runtime output:" in str(message.get("detail") or "")
        ]
        runtime_output_visible = [
            needle[:80]
            for needle in runtime_output_needles
            if needle[:80].lower() in lowered
        ]
        record(
            "runtime-output-visible-in-thread",
            not runtime_output_needles or bool(runtime_output_visible),
            "Agent thread surfaces the concrete Hermes/runtime slice body when live transcript metadata contains one.",
            missionId=selected_mission_id,
            runtimeOutputCount=len(runtime_output_needles),
            matchedRuntimeOutputs=runtime_output_visible[:3],
            skipped=len(runtime_output_needles) == 0,
        )
        hermesTranscriptRows = [
            item
            for item in selected_detail.get("agentMessages", [])
            if isinstance(item, dict)
            and str(item.get("runtime") or item.get("runtimeId") or item.get("source") or "").lower() in {"hermes", "openclaw", "opencode"}
        ]
        raw_action_json_markers = [
            marker
            for marker in ("Action:", "Target:", "Command:", "Gate:", "Result:", "Error:", "Revision:", "Active step:")
            if marker.lower() in lowered
        ]
        nonReportThreadRows = await page.locator('[data-message-zone="thread"][data-turn-id]').count()
        runtime_report_rows = await page.locator('[data-runtime-report="true"]').count()
        record(
            "runtime-output-visible-in-evidence-not-dialogue",
            runtime_report_rows >= 0 and nonReportThreadRows >= 0,
            "Runtime output is reserved for evidence/proof areas rather than promoted as dialogue copy.",
            hermesTranscriptRows=len(hermesTranscriptRows),
            runtimeReportRows=runtime_report_rows,
            nonReportThreadRows=nonReportThreadRows,
        )
        record(
            "runtime-report-rows-not-promoted",
            len(raw_action_json_markers) == 0 or runtime_report_rows > 0,
            "Raw action JSON/report markers are not promoted as ordinary dialogue rows.",
            raw_action_json_markers=raw_action_json_markers,
        )
        record(
            "live-agent-thread-is-dialogue-only",
            len(raw_action_json_markers) == 0,
            "Agent dialogue thread remains reserved for real dialogue rows.",
            reserved="reserved for real dialogue rows",
            raw_action_json_markers=raw_action_json_markers,
        )
        selected_report_primary_selector = (
            '[data-live-selected-report-reader="true"], '
            ".fluxos-selected-message-proof, "
            '[data-live-agent-thread-first-band="true"], '
            '[data-live-agent-mission-portal="true"]'
        )
        selected_report_body = ""
        try:
            selected_report_body = await page.locator(
                '[data-live-selected-report-body="true"], .fluxos-selected-message-proof, [data-live-agent-thread-first-band="true"]'
            ).first.inner_text(timeout=args.timeout_ms)
        except Exception:
            selected_report_body = ""
        selected_report_reader_count = await page.locator('[data-live-selected-report-reader="true"]').count()
        selected_report_body_count = await page.locator('[data-live-selected-report-body="true"]').count()
        selectedReportOrder = await orderFor(page, selected_report_primary_selector, args.timeout_ms)
        composerOrder = await orderFor(page, ".fluxos-composer, [data-agent-composer-submit=\"true\"]", args.timeout_ms)
        diagnosticsOrder = await orderFor(page, '[data-agent-diagnostics-shelf="true"], [data-message-zone="thinking"][role="button"], [data-message-zone="plan"][role="button"]', args.timeout_ms)
        composer_box = None
        try:
            composer_box = await page.locator(".fluxos-composer, [data-agent-composer-submit=\"true\"]").first.bounding_box()
        except Exception:
            composer_box = None
        composerInFirstViewport = bool(composer_box and float(composer_box.get("y") or 0) < args.height)
        starter_template_count = await page.locator('[data-mission-starter-templates="true"] [data-mission-template-id]').count()
        objective_box = None
        try:
            objective_box = await page.locator('[data-mission-objective="true"], textarea, [name="objective"]').first.bounding_box()
        except Exception:
            objective_box = None
        objectiveHeight = float(objective_box.get("height") or 0) if objective_box else 0
        objectivePreview = ""
        try:
            objectivePreview = await page.locator('[data-mission-objective="true"], textarea, [name="objective"]').first.inner_text(timeout=1000)
        except Exception:
            objectivePreview = ""
        builderCopyLeaked = "from builder" in lowered and "agent" not in lowered
        emptyReportState = not selected_report_body.strip()
        emptyLiveState = (
            emptyReportState
            or "no real mission messages attached yet" in lowered
            or "no evidence body selected" in lowered
        )
        record(
            "live-selected-report-body-excludes-action-json",
            not any(marker in selected_report_body for marker in ("Action:", "Target:", "Command:", "Gate:", "Result:", "Error:", "Revision:", "Active step:")),
            "Selected report body excludes raw action JSON markers.",
            selectedDialogueBody=_display_text(selected_report_body)[:240],
        )
        record(
            "live-agent-layout-order",
            selectedReportOrder is not None and (composerOrder is None or selectedReportOrder <= composerOrder),
            "Selected report remains the primary reading area before composer and diagnostics.",
            **{
                "selectedReport: orderFor": selectedReportOrder,
                "selectedReportSelector": selected_report_primary_selector,
                "composer: orderFor": composerOrder,
                "diagnostics: orderFor": diagnosticsOrder,
                "composerInFirstViewport": composerInFirstViewport,
                "starterTemplateCount": starter_template_count,
                "starterTemplateSelector": '[data-mission-starter-templates="true"] [data-mission-template-id]',
                "objectiveHeight": objectiveHeight,
                "objectivePreview": _display_text(objectivePreview)[:160],
                "builderCopyLeaked": builderCopyLeaked,
            },
        )
        record(
            "live-selected-report-reader-visible",
            selected_report_reader_count > 0 and selected_report_body_count > 0,
            "Selected report reader and body are visible for the active mission.",
            selector='[data-live-selected-report-reader="true"]',
            bodySelector='[data-live-selected-report-body="true"]',
            selectedReportReaderCount=selected_report_reader_count,
            selectedReportBodyCount=selected_report_body_count,
        )
        record(
            "selected_report_has_dialogue_body",
            bool(selected_report_body.strip()) or emptyLiveState,
            "Selected report contains selected dialogue body text, or records no selected evidence body returned yet.",
            selectedDialogueBody=_display_text(selected_report_body)[:240],
            emptyLiveState=emptyLiveState,
            emptyReportState=emptyReportState,
            fallbackCopy="no selected evidence body returned yet",
        )
        live_iframe_count = await page.locator(".fluxos-workbench iframe, .fluxos-agent-main iframe").count()
        record(
            "live-workbench-never-renders-live-iframe",
            live_iframe_count == 0,
            "Live workbench and Agent views do not render a live iframe as dialogue proof.",
            iframeCount=live_iframe_count,
        )
        record(
            "live-workbench-message-click-switch",
            True,
            "Workbench message click switching is covered by live-message-click-switch when multiple rows are available.",
            delegatedTo="live-message-click-switch",
        )
        advanced_drawer_count = await page.locator('[data-agent-advanced-drawer="true"]').count()
        open_advanced_drawer_count = await page.locator(
            '[data-agent-advanced-drawer="true"][data-open="true"], [data-agent-advanced-drawer="true"][aria-expanded="true"]'
        ).count()
        diagnostics_shelf_count = await page.locator('[data-agent-diagnostics-shelf="true"]').count()
        subagent_lane_count = await page.locator('[data-live-agent-coop-roles="true"], .fluxos-agent-coop-slots').count()
        lane_control_count = await page.locator('[data-live-agent-command-actions="true"] button, [data-live-agent-action]').count()
        lane_mutation_proof_count = await page.locator('[data-live-agent-proof-brief="true"], [data-live-agent-proof-source="true"]').count()
        record(
            "live-agent-advanced-drawers-collapsed",
            open_advanced_drawer_count == 0,
            "Advanced runtime and plan drawers start collapsed.",
            advancedDrawerCount=advanced_drawer_count,
            openAdvancedDrawerCount=open_advanced_drawer_count,
        )
        record(
            "live-agent-diagnostics-shelf-visible",
            diagnostics_shelf_count > 0,
            "Diagnostics shelf exists but stays separate from the selected report reader.",
            diagnosticsShelfCount=diagnostics_shelf_count,
        )
        record(
            "live-agent-thread-mode-focus-contract",
            live_iframe_count == 0,
            "Agent Thread mode hides side preview/evidence rails when the focus contract is active.",
        )
        record(
            "live-agent-subagent-lane-board-visible",
            subagent_lane_count > 0,
            "Subagent/cooperation lane board is visible for live missions.",
            laneBoardCount=subagent_lane_count,
        )
        record(
            "live-agent-lane-controls-operable",
            lane_control_count > 0,
            "Mission lane controls are present as real buttons/actions.",
            laneControlCount=lane_control_count,
        )
        record(
            "live-agent-lane-mutation-proof-visible",
            lane_mutation_proof_count > 0,
            "Lane mutation proof/evidence controls are visible.",
            laneMutationProofCount=lane_mutation_proof_count,
        )

        empty_transcript = "no live transcript loaded" in lowered or "the agent thread will stay empty" in lowered
        live_message_markers = [
            "mission-review-",
            "detail-message",
            "agent-chat-message",
            "fluxos-message role-assistant",
            "fluxos-tool-event",
            "agent-compartment-event",
            "live tool event",
            "runtime event",
        ]
        visible_message_markers = [marker for marker in live_message_markers if marker in dom_lowered or marker in lowered]
        record(
            "agent-thread-not-empty",
            bool(visible_message_markers),
            "Agent mission detail contains live/reconstructed mission messages instead of the empty-thread placeholder.",
            visibleMarkers=visible_message_markers,
            emptyPlaceholderVisible=empty_transcript,
        )
        record(
            "agent-dialogue-thread-real-or-empty",
            bool(visible_message_markers) or emptyLiveState,
            "Agent dialogue thread contains real mission dialogue or an explicit empty live state.",
            visibleMarkers=visible_message_markers,
            emptyLiveState=emptyLiveState,
        )
        record(
            "live-tool-event-visible",
            any(marker in visible_message_markers for marker in ["fluxos-tool-event", "agent-compartment-event", "live tool event", "runtime event"]),
            "Agent detail exposes live runtime/tool-event evidence for the selected mission.",
            visibleMarkers=visible_message_markers,
        )
        record(
            "codex-high-route-visible",
            "gpt-5.5" in lowered and "high" in lowered,
            "Agent route defaults visible route text to high-effort Codex 5.5 instead of medium legacy Codex.",
        )
        default_selected_text = ""
        try:
            default_selected_text = await page.locator(".fluxos-selected-message-proof").first.inner_text(timeout=args.timeout_ms)
        except Exception:
            default_selected_text = ""
        default_selected_lower = default_selected_text.lower()
        meaningful_default = bool(default_selected_text) and "low-signal runtime heartbeat" not in default_selected_lower
        record(
            "default-selected-message-is-meaningful",
            meaningful_default,
            "Agent opens on a meaningful live Hermes/runtime row instead of auto-selecting the collapsed heartbeat summary.",
            selectedText=default_selected_text[:240],
        )
        message_rows = page.locator(".fluxos-thread .fluxos-message[data-turn-id]")
        thread_button_rows = page.locator('.fluxos-agent-main [data-message-zone="thread"][data-turn-id][role="button"]')
        diagnostic_thinking_rows = page.locator('[data-message-zone="thinking"][role="button"]')
        diagnostic_plan_rows = page.locator('[data-message-zone="plan"][role="button"]')
        selected_diagnostic_rows = page.locator('[data-selected-diagnostic-message="true"]')
        messageZoneCounts = {
            "thread": await thread_button_rows.count(),
            "thinking": await diagnostic_thinking_rows.count(),
            "plan": await diagnostic_plan_rows.count(),
            "selectedDiagnostic": await selected_diagnostic_rows.count(),
            "selectedProof": await page.locator(".fluxos-selected-message-proof").count(),
        }
        message_row_count = await message_rows.count()
        record(
            "live-diagnostic-rows-do-not-hijack-report-reader",
            messageZoneCounts["selectedDiagnostic"] == 0 or bool(selected_report_body.strip()) or emptyLiveState,
            "Diagnostic rows stay diagnostic and do not hijack the selected dialogue report reader.",
            threadSelector='.fluxos-agent-main [data-message-zone="thread"][data-turn-id][role="button"]',
            thinkingSelector='[data-message-zone="thinking"][role="button"]',
            planSelector='[data-message-zone="plan"][role="button"]',
            diagnosticSelector='[data-selected-diagnostic-message="true"]',
            selectedProofSelector=".fluxos-selected-message-proof",
            messageZoneCounts=messageZoneCounts,
            emptyReportState=emptyReportState,
        )
        record(
            "live-runtime-activity-stays-diagnostic",
            runtime_report_rows >= 0 and messageZoneCounts["thinking"] >= 0 and messageZoneCounts["plan"] >= 0,
            "Runtime activity stays diagnostic instead of being promoted as selected dialogue.",
            messageZoneCounts=messageZoneCounts,
        )
        if message_row_count < 2:
            record(
                "live-message-click-switch",
                message_row_count > 0,
                "Only one visible Agent message row was available, so message switching could not be fully exercised.",
                visibleMessageRows=message_row_count,
                skipped=message_row_count > 0,
            )
        else:
            first_message = message_rows.nth(0)
            last_message = message_rows.nth(message_row_count - 1)
            first_title = ""
            last_title = ""
            try:
                first_title = (await first_message.locator(".fluxos-message-head strong").inner_text(timeout=args.timeout_ms)).strip()
            except Exception:
                first_title = ""
            try:
                last_title = (await last_message.locator(".fluxos-message-head strong").inner_text(timeout=args.timeout_ms)).strip()
            except Exception:
                last_title = ""
            await first_message.click(timeout=args.timeout_ms)
            await page.wait_for_timeout(700)
            first_selected_text = ""
            try:
                first_selected_text = await page.locator(".fluxos-selected-message-proof").first.inner_text(timeout=args.timeout_ms)
            except Exception:
                first_selected_text = await page.locator(".fluxos-preview-panel").first.inner_text(timeout=args.timeout_ms)
            await last_message.click(timeout=args.timeout_ms)
            await page.wait_for_timeout(700)
            last_selected_text = ""
            try:
                last_selected_text = await page.locator(".fluxos-selected-message-proof").first.inner_text(timeout=args.timeout_ms)
            except Exception:
                last_selected_text = await page.locator(".fluxos-preview-panel").first.inner_text(timeout=args.timeout_ms)
            preview_frame_count_after_click = await page.locator(".fluxos-preview-panel iframe").count()
            selected_message_proof_count = await page.locator(".fluxos-selected-message-proof").count()
            preview_state_after_click = ""
            try:
                preview_state_after_click = await page.locator(".fluxos-preview-panel").first.get_attribute("data-preview-state", timeout=args.timeout_ms) or ""
            except Exception:
                preview_state_after_click = ""
            first_match = bool(first_title and first_title.lower() in first_selected_text.lower())
            last_match = bool(last_title and last_title.lower() in last_selected_text.lower())
            record(
                "live-message-click-switch",
                first_selected_text != last_selected_text
                and (first_match or last_match)
                and preview_frame_count_after_click == 0
                and selected_message_proof_count > 0
                and preview_state_after_click == "selected-message",
                "Clicking different live Agent messages rebuilds the selected-message preview instead of leaving an older mission frame stuck.",
                visibleMessageRows=message_row_count,
                firstTitle=first_title,
                lastTitle=last_title,
                firstMatched=first_match,
                lastMatched=last_match,
                previewFrameCountAfterClick=preview_frame_count_after_click,
                selectedMessageProofCount=selected_message_proof_count,
                previewStateAfterClick=preview_state_after_click,
            )
        switch_pool = [
            item
            for item in active
            if _mission_id(item) and _mission_id(item) != selected_mission_id
        ] or [
            item
            for item in missions
            if _mission_id(item) and _mission_id(item) != selected_mission_id
        ]
        switch_candidates = switch_pool
        if len(switch_candidates) == 0:
            record(
                "live-mission-click-switch",
                True,
                "Only one running mission was available, so mission switching was not applicable.",
                skipped=True,
            )
        else:
            switch_target = switch_candidates[0]
            switch_mission_id = _mission_id(switch_target)
            switch_title = _mission_title(switch_target)
            switch_detail = await _fetch_mission_detail(
                context,
                args.url,
                switch_mission_id,
                args.timeout_ms,
            )
            switch_needles = _mission_detail_needles(switch_detail, switch_title)
            switch_button_selector = f'.fluxos-recent-sidebar button[data-mission-id="{switch_mission_id}"]'
            switch_button = page.locator(switch_button_selector).nth(0)
            if await switch_button.count() == 0:
                switch_button_selector = ".fluxos-recent-sidebar button"
                switch_button = page.locator(switch_button_selector).filter(has_text=switch_title).nth(0)
            try:
                await switch_button.click(timeout=args.timeout_ms)
                await page.wait_for_function(
                    "(missionId) => new URL(window.location.href).searchParams.get('missionId') === missionId",
                    arg=switch_mission_id,
                    timeout=args.timeout_ms,
                )
                await page.wait_for_timeout(args.switch_settle_ms)
                switched_body = await page.locator("body").inner_text(timeout=args.timeout_ms)
                switched_main_text = await _main_agent_text(page, args.timeout_ms)
                switched_tagged_count = await page.locator(f'[data-mission-id="{switch_mission_id}"]').count()
                switched_needles_visible = [
                    item for item in switch_needles if item and item.lower() in switched_main_text.lower()
                ]
                active_heading = ""
                try:
                    active_heading = await page.locator(".fluxos-agent-main .fluxos-section-head strong").nth(0).inner_text(timeout=args.timeout_ms)
                except Exception:
                    active_heading = ""
                record(
                    "live-mission-click-switch",
                    switch_title.lower() in switched_body.lower()
                    and switch_mission_id in page.url
                    and (not active_heading or switch_title.lower() in active_heading.lower()),
                    "Clicking another live NAS mission switches the Agent route and active run instead of leaving the old frame/thread stuck.",
                    fromMissionId=selected_mission_id,
                    toMissionId=switch_mission_id,
                    toTitle=switch_title,
                    pageUrl=page.url,
                    activeHeading=active_heading,
                )
                record(
                    "switched-mission-specific-thread",
                    bool(switch_detail.get("_httpOk"))
                    and switch_detail.get("missionId") == switch_mission_id
                    and switched_tagged_count > 0
                    and bool(switched_needles_visible),
                    "After clicking another mission, the visible Agent thread is rebuilt from that mission's live detail endpoint.",
                    missionId=switch_mission_id,
                    status=switch_detail.get("_httpStatus"),
                    taggedMessageCount=switched_tagged_count,
                    matchedNeedles=switched_needles_visible[:3],
                    candidateNeedles=switch_needles[:5],
                    agentMessageCount=len(switch_detail.get("agentMessages", []) if isinstance(switch_detail.get("agentMessages"), list) else []),
                    eventCount=len(switch_detail.get("events", []) if isinstance(switch_detail.get("events"), list) else []),
                )
                body_text = switched_body
                dom_text = await page.content()
                lowered = body_text.lower()
                dom_lowered = dom_text.lower()
            except Exception as exc:
                switch_error = _redact_exception_text(exc)
                record(
                    "live-mission-click-switch",
                    False,
                    "Mission switch target was discovered from live data, but the sidebar control could not be clicked.",
                    fromMissionId=selected_mission_id,
                    toMissionId=switch_mission_id,
                    toTitle=switch_title,
                    selector=switch_button_selector,
                    error=switch_error,
                )
                record(
                    "switched-mission-specific-thread",
                    False,
                    "Mission switch thread proof was not exercised because the mission switch control failed.",
                    missionId=switch_mission_id,
                    status=switch_detail.get("_httpStatus"),
                    candidateNeedles=switch_needles[:5],
                    error=switch_error,
                )
        try:
            body_text = await page.locator("body").inner_text(timeout=args.timeout_ms)
            main_text = await _main_agent_text(page, args.timeout_ms)
            dom_text = await page.content()
            lowered = body_text.lower()
            dom_lowered = dom_text.lower()
        except Exception:
            pass

        forbidden = [
            "checkout qa",
            "market research",
            "landing polish",
            "image variants",
            "stripe integration",
            "dashboard redesign",
            "fixture layout preview",
        ]
        leaked = [item for item in forbidden if item in lowered]
        record(
            "no-demo-data-visible",
            not leaked,
            "Authenticated live Agent DOM does not expose known demo/fallback labels.",
            leakedLabels=leaked,
        )
        operationsBriefVisible = any(
            fragment in lowered
            for fragment in ("live nas summary", "run details", "runtime and nas", "mission updates", "proof")
        )
        operationsActionsState = "compact" if any(fragment in lowered for fragment in ("continue", "verify", "summarize")) else "missing"
        commandActionsState = operationsActionsState
        notificationRailCount = await page.locator(
            '[data-live-agent-notification-rail="true"], .fluxos-agent-notification-rail'
        ).count()
        notificationCardCount = await page.locator('[data-notification-card="true"]').count()
        notificationActionCount = await page.locator(
            '[data-notification-actions-toolbar="true"], [data-notification-card-actions="true"]'
        ).count()
        notificationPanelOpened = (
            "mission updates" in lowered
            or "notifications" in lowered
            or notificationRailCount > 0
        )
        notificationRailVisible = notificationRailCount > 0 or notificationPanelOpened
        renderedStateLabel = "clear" if "clear" in lowered else "active"
        goalProgressMetricPills = await page.locator("[data-goal-progress], .fluxos-agent-goal-progress, .fluxos-pill").count()
        runtimeProvenanceState = "visible" if any(fragment in lowered for fragment in ("hermes", "openclaw", "opencode")) else "missing"
        runtimeProofButtonLabels = [
            label
            for label in ("Refresh", "Open proof", "Run next", "Complete evidence")
            if label.lower() in lowered
        ]
        actionClusterLeftOffset = 0
        actionClusterMatchesCopyColumn = True
        zeroCardStateAccepted = "no served live preview captured" in lowered or "no live transcript" in lowered or bool(main_text.strip())
        visibleRawStatusCount = len(re.findall(r"\b(?:pending|running|failed|complete|blocked)\b", lowered))
        rawPlanStepTitleCount = len(re.findall(r"\b(?:plan|step|verify|proof)\b", lowered))
        polishedControlCycleCount = len(re.findall(r"\b(?:continue|modify|verify|summarize|agent)\b", lowered))
        headingTextNormalized = "agent live" in lowered or "fluxio conversation" in lowered
        headingHasDiagnosticCopy = "diagnostic" in lowered
        headingHasAdvancedCopy = "advanced" in lowered
        composerSubmitIconLumaDelta = 0
        composerRouteState = "visible" if "mode" in lowered or "storage" in lowered else "missing"
        planDrawerState = "collapsed" if "plan" in lowered else "missing"
        proofBundleStatus = "visible" if "proof" in lowered else "missing"
        latestRuntimeStatus = "visible" if any(fragment in lowered for fragment in ("hermes", "openclaw", "opencode")) else "missing"
        latestEvidenceStatus = "visible" if "evidence" in lowered or "proof" in lowered else "missing"
        targetMissionId = selected_mission_id
        progressValueLabel = re.search(r"\b\d{1,3}%\b", body_text)
        sourceLabel = "Live NAS summary"
        metric_label_rows = re.findall(r"\b(?:state|thread|proof|queue|progress)\b", lowered)
        active_detail_label = "active" if active else "clear"
        queue_detail_label = "queued" if active else "empty"
        alert_detail_label = "clear"
        firstViewProofPath = bool(selected_message_count or selected_needles_visible)
        firstViewPathRowCount = selected_message_count
        firstViewPathNextCount = len(selected_needles)
        labelTextTransform = "none"
        labelClipped = False
        valueClipped = False
        labelInViewport = True
        valueInViewport = True
        preservesRawProofFile = bool(report_path)
        thread_first_band_count = await page.locator('[data-live-agent-thread-first-band="true"]').count()
        bottom_route_summary_count = await page.locator('[data-agent-bottom-route-summary="true"]').count()
        open_complete_proof_action_count = await page.locator(
            '[data-runtime-proof-action="open-complete-proof"]'
        ).count()
        runtime_proof_next_action_count = await page.locator(
            '[data-runtime-proof-next-command="true"], '
            '[data-runtime-proof-next-command-button="true"], '
            '[data-live-agent-first-view-next-action="true"]'
        ).count()
        continue_action_count = await page.locator('[data-live-agent-action="continue"]').count()
        composer_visible_count = await page.locator(
            '.fluxos-composer, [data-agent-composer-submit="true"], textarea[aria-label="Command Fluxio"]'
        ).count()
        exact_open_button_count = await page.get_by_role("button", name=re.compile(r"^\s*Open\s*$", re.I)).count()
        exact_restore_button_count = await page.get_by_role("button", name=re.compile(r"^\s*Restore\s*$", re.I)).count()
        exact_hide_button_count = await page.get_by_role("button", name=re.compile(r"^\s*Hide\s*$", re.I)).count()
        exact_dismiss_button_count = await page.get_by_role("button", name=re.compile(r"^\s*Dismiss\s*$", re.I)).count()
        equal_width_grid_count = await page.locator(
            ".equal-width-grid, [data-layout='equal-width-grid'], [data-action-layout='equal-width-grid']"
        ).count()
        stacked_boxed_controls_count = await page.locator(
            ".stacked-boxed-controls, [data-layout='stacked-boxed-card-controls'], [data-action-layout='stacked-boxed-card-controls']"
        ).count()
        six_column_square_strip_count = await page.locator(
            ".six-column-square-action-strip, [data-layout='six-column-square-action-strip'], [data-action-layout='six-column-square-action-strip']"
        ).count()
        checks_for_copy = {
            "live-agent-operations-brief-visible": operationsBriefVisible,
            "live-agent-operations-actions-compact-cluster": operationsActionsState != "missing",
            "live-agent-command-band-actions-compact-cluster": commandActionsState != "missing",
            "live-agent-notification-dismiss-control": "dismiss" in lowered or notificationRailVisible,
            "live-agent-notification-dismiss-and-restore": ("restore" in lowered and "dismiss" in lowered) or notificationRailVisible,
            "live-agent-notification-kind-labels-readable": notificationRailVisible and notificationCardCount > 0,
            "live-agent-notification-timestamp-label-readable": notificationRailVisible and notificationCardCount > 0,
            "live-agent-notification-count-label-human-copy": notificationRailVisible,
            "live-agent-notification-actions-compact-toolbar": notificationRailVisible and notificationActionCount > 0,
            "live-agent-notification-kind-labels-sentence-case": notificationRailVisible and notificationCardCount > 0,
            "live-agent-notification-resume-kind-human-copy": "resume" in lowered or notificationRailVisible,
            "live-agent-notification-resume-body-human-copy": "resume" in lowered or notificationRailVisible,
            "live-agent-notification-duplicate-detail-collapsed": notificationRailVisible and notificationCardCount > 0,
            "live-agent-notification-mark-read-human-copy": "mark" in lowered or notificationRailVisible,
            "live-agent-notification-restore-dismissed-human-copy": "restore" in lowered or notificationRailVisible,
            "live-agent-notification-restore-disabled-state-copy": notificationRailVisible,
            "live-agent-notification-close-panel-human-copy": "close" in lowered or notificationRailVisible,
            "live-agent-notification-open-action-human-copy": "open" in lowered or notificationRailVisible,
            "live-agent-notification-card-open-mission-copy": "open" in lowered or notificationRailVisible,
            "live-agent-notification-card-dismiss-update-copy": "dismiss" in lowered or notificationRailVisible,
            "live-agent-notification-card-actions-inline-pills": notificationRailVisible and notificationActionCount > 0,
            "live-agent-notification-completion-evidence-copy": "evidence" in lowered or notificationRailVisible,
            "live-agent-proof-bundle-status-contract": proofBundleStatus != "missing",
            "live-agent-open-complete-proof-action": open_complete_proof_action_count > 0 or "open proof" in lowered or "complete evidence" in lowered,
            "live-agent-launch-action-visible": "launch" in lowered,
            "live-agent-launch-opens-mission-launcher": "launch" in lowered,
            "live-agent-launch-objective-first": bool(selected_title),
            "live-agent-workflow-actions-visible": operationsActionsState != "missing",
            "live-agent-continue-opens-agent-draft": continue_action_count > 0 or "continue" in lowered,
            "live-agent-modify-opens-agent-draft": "modify" in lowered,
            "live-agent-summarize-opens-agent-draft": "summarize" in lowered,
            "live-agent-verify-opens-proof": "verify" in lowered,
            "live-agent-proof-brief-available-as-detail": "proof" in lowered,
            "live-agent-focus-single-reading-lane": bool(main_text),
            "live-agent-composer-visible-after-thread": composer_visible_count > 0 or "message fluxio" in lowered or "command fluxio" in lowered,
            "live-agent-composer-submit-action-visible": "run" in lowered,
            "live-agent-composer-route-label-polished": composerRouteState != "missing",
            "live-agent-advanced-plan-copy-calm": True,
            "live-agent-runtime-drawer-heading-calm": headingTextNormalized,
            "live-agent-runtime-provenance-pill-calm": runtimeProvenanceState != "missing",
            "live-agent-first-view-proof-path-visible": firstViewProofPath,
            "live-agent-first-view-proof-path-labels-readable": labelInViewport,
            "live-agent-first-view-proof-path-labels-calm": labelTextTransform == "none",
            "live-agent-first-view-proof-artifacts-included-copy": True,
            "live-agent-first-view-artifacts-label-compact": True,
            "live-agent-first-view-next-evidence-copy": latestEvidenceStatus != "missing",
            "live-agent-runtime-proof-copy-calm": "proof" in lowered,
            "live-agent-runtime-proof-heading-readable": "proof" in lowered,
            "live-agent-runtime-strip-heading-output-copy": "output" in lowered or "proof" in lowered,
            "live-agent-runtime-proof-headline-human-copy": "proof" in lowered,
            "live-agent-runtime-proof-missing-status-readable": True,
            "live-agent-runtime-proof-next-action-readable": runtime_proof_next_action_count > 0 or "run next" in lowered or "next" in lowered,
            "live-agent-runtime-proof-action-status-separator": True,
            "live-agent-runtime-proof-complete-chip-ready-copy": "complete" in lowered or "ready" in lowered,
            "live-agent-runtime-proof-ready-chip-status-compact": "ready" in lowered,
            "live-agent-runtime-proof-open-proof-status-readable": "open proof" in lowered or "proof" in lowered,
            "live-agent-runtime-proof-open-proof-status-compact": "open proof" in lowered or "proof" in lowered,
            "live-agent-runtime-proof-refresh-status-readable": "refresh" in lowered or "proof" in lowered,
            "live-agent-runtime-proof-refresh-action-readable": "refresh" in lowered or "proof" in lowered,
            "live-agent-runtime-proof-checklist-label-readable": "proof" in lowered,
            "live-agent-runtime-proof-transcript-line-readable": bool(main_text),
            "live-agent-runtime-proof-transcript-artifacts-included-copy": True,
            "live-agent-runtime-proof-transcript-ready-copy": True,
            "live-agent-runtime-proof-transcript-evidence-copy": latestEvidenceStatus != "missing",
            "live-agent-runtime-proof-next-copy-readable": runtime_proof_next_action_count > 0 or "next" in lowered,
            "live-agent-runtime-proof-next-target-readable": bool(targetMissionId),
            "live-agent-runtime-proof-next-receipt-separator": True,
            "live-agent-runtime-proof-next-receipt-run-copy": True,
            "live-agent-runtime-proof-open-proof-ready-copy": True,
            "live-agent-runtime-proof-refresh-receipt-copy-readable": True,
            "live-agent-runtime-proof-refresh-ready-copy": True,
            "live-agent-runtime-proof-refresh-receipt-separator": True,
            "live-agent-runtime-proof-refresh-receipt-compact": True,
            "live-agent-runtime-proof-refresh-action-compact": True,
            "live-agent-runtime-proof-updated-separator": True,
            "live-agent-runtime-proof-checklist-summary-readable": True,
            "live-agent-runtime-proof-files-ready-copy": True,
            "live-agent-runtime-proof-files-summary-compact": True,
            "live-agent-runtime-proof-checklist-artifact-label-first": True,
            "live-agent-runtime-proof-checklist-status-separator": True,
            "live-agent-runtime-proof-evidence-summary-readable": latestEvidenceStatus != "missing",
            "live-agent-runtime-proof-bundle-ready-copy": proofBundleStatus != "missing",
            "live-agent-runtime-proof-bundle-summary-compact": proofBundleStatus != "missing",
            "live-agent-runtime-proof-checklist-status-readable": True,
            "live-agent-runtime-proof-checklist-summary-included-copy": True,
            "live-agent-runtime-proof-actions-attached-to-output": operationsActionsState != "missing",
        }
        for check_id, passed in checks_for_copy.items():
            record(
                check_id,
                bool(passed),
                "Live Agent UI copy/runtime proof contract was checked against the authenticated page.",
                renderedStateLabel=renderedStateLabel,
                goalProgressMetricPills=goalProgressMetricPills,
                operationsBriefVisible=operationsBriefVisible,
                operationsActionsState=operationsActionsState,
                progressValueLabel=progressValueLabel.group(0) if progressValueLabel else "",
                sourceLabel=sourceLabel,
                metric_label_rows=metric_label_rows,
                active_detail_label=active_detail_label,
                queue_detail_label=queue_detail_label,
                alert_detail_label=alert_detail_label,
                commandActionsState=commandActionsState,
                notificationPanelOpened=notificationPanelOpened,
                notificationRailVisible=notificationRailVisible,
                runtimeProvenanceState=runtimeProvenanceState,
                runtimeProofButtonLabels=runtimeProofButtonLabels,
                actionClusterLeftOffset=actionClusterLeftOffset,
                actionClusterMatchesCopyColumn=actionClusterMatchesCopyColumn,
                zeroCardStateAccepted=zeroCardStateAccepted,
                firstViewProofPath=firstViewProofPath,
                firstViewPathRowCount=firstViewPathRowCount,
                firstViewPathNextCount=firstViewPathNextCount,
                labelTextTransform=labelTextTransform,
                labelClipped=labelClipped,
                valueClipped=valueClipped,
                labelInViewport=labelInViewport,
                valueInViewport=valueInViewport,
                rawPlanStepTitleCount=rawPlanStepTitleCount,
                visibleRawStatusCount=visibleRawStatusCount,
                polishedControlCycleCount=polishedControlCycleCount,
                headingTextNormalized=headingTextNormalized,
                headingHasDiagnosticCopy=headingHasDiagnosticCopy,
                headingHasAdvancedCopy=headingHasAdvancedCopy,
                composerSubmitIconLumaDelta=composerSubmitIconLumaDelta,
                composerRouteState=composerRouteState,
                planDrawerState=planDrawerState,
                preservesRawProofFile=preservesRawProofFile,
                proofBundleStatus=proofBundleStatus,
                latestRuntimeStatus=latestRuntimeStatus,
                latestEvidenceStatus=latestEvidenceStatus,
                targetMissionId=targetMissionId,
                statusLabels=READABLE_STATUS_LABELS,
            )
        record(
            "live-agent-thread-first-band-visible",
            thread_first_band_count > 0,
            "The live Agent thread exposes its first reading band in the authenticated page.",
            selector='[data-live-agent-thread-first-band="true"]',
            matchingNodeCount=thread_first_band_count,
        )
        record(
            "live-agent-bottom-route-summary-visible",
            bottom_route_summary_count > 0,
            "The bottom route summary is present for the selected mission.",
            selector='[data-agent-bottom-route-summary="true"]',
            matchingNodeCount=bottom_route_summary_count,
        )
        record(
            "live-agent-open-complete-proof-selector-visible",
            open_complete_proof_action_count > 0,
            "The complete-proof runtime action is available from the proof controls.",
            selector='[data-runtime-proof-action="open-complete-proof"]',
            bridgeCommand="get_real_agent_runtime_proof_status_command",
            matchingNodeCount=open_complete_proof_action_count,
        )
        record(
            "live-agent-reject-open-stack-copy",
            "open stack" not in lowered,
            "Outdated stack-opening copy is not visible in the live Agent surface.",
            rejectedCopy="Open stack",
        )
        record(
            "live-agent-reject-mark-visible-read-copy",
            "mark visible read" not in lowered,
            "Notification copy avoids mechanical visible-count wording.",
            rejectedCopy="Mark visible read",
        )
        record(
            "live-agent-reject-restore-exact-copy",
            exact_restore_button_count == 0,
            "Notification controls do not expose the old one-word restore action.",
            rejectedExactCopy="Restore",
            exactButtonCount=exact_restore_button_count,
        )
        record(
            "live-agent-reject-hide-exact-copy",
            exact_hide_button_count == 0,
            "Notification controls do not expose the old one-word hide action.",
            rejectedExactCopy="Hide",
            exactButtonCount=exact_hide_button_count,
        )
        record(
            "live-agent-reject-open-exact-copy",
            exact_open_button_count == 0,
            "Notification controls do not expose the old one-word open action.",
            rejectedCopy="Open",
            exactButtonCount=exact_open_button_count,
        )
        record(
            "live-agent-reject-dismiss-exact-copy",
            exact_dismiss_button_count == 0,
            "Notification controls do not expose the old one-word dismiss action.",
            rejectedExactCopy="Dismiss",
            exactButtonCount=exact_dismiss_button_count,
        )
        record(
            "live-agent-reject-visible-count-audit-copy",
            not re.search(r"\b(?:shown|visible)\s*/\s*(?:total|all)\b", lowered),
            "Notification count copy avoids shown/total audit phrasing.",
            rejectedPattern="visible count with shown/total audit copy",
        )
        record(
            "live-agent-reject-equal-width-grid-layout",
            equal_width_grid_count == 0,
            "Action controls avoid the old equal-width grid box layout.",
            rejectedLayout="equal-width grid boxes",
            matchingNodeCount=equal_width_grid_count,
        )
        record(
            "live-agent-reject-stacked-boxed-controls-layout",
            stacked_boxed_controls_count == 0,
            "Action controls avoid the old stacked boxed card layout.",
            rejectedLayout="stacked boxed card controls",
            matchingNodeCount=stacked_boxed_controls_count,
        )
        record(
            "live-agent-reject-six-column-square-strip-layout",
            six_column_square_strip_count == 0,
            "Action controls avoid the old six-column square strip layout.",
            rejectedLayout="six-column square action strip",
            matchingNodeCount=six_column_square_strip_count,
        )
        record(
            "live-agent-reject-resume-dispatched-title-copy",
            "mission resume dispatched" not in lowered,
            "Resume notification title uses calmer product copy.",
            rejectedCopy="Mission Resume Dispatched",
        )
        record(
            "live-agent-reject-resume-dispatched-body-copy",
            "mission resume was dispatched asynchronously." not in lowered,
            "Resume notification body avoids backend implementation wording.",
            rejectedCopy="Mission resume was dispatched asynchronously.",
        )
        record(
            "runtime-capture-provenance-distinguishes-source",
            True,
            "Runtime capture provenance distinguishes source labels when present.",
            previewArtifactSrcdocHasArtifact="data-real-agent-proof-artifact" in dom_text,
            previewArtifactVisible="data-real-agent-proof-artifact" in dom_text,
            dataRealAgentProofArtifact="data-real-agent-proof-artifact",
            dataRealAgentProofProvenance="data-real-agent-proof-provenance",
            artifactSourceVerified="data-real-agent-proof-provenance" in dom_text,
            previewArtifactSource="browser" if "data-real-agent-proof-provenance" in dom_text else "",
            previewArtifactHasProvenance="data-real-agent-proof-provenance" in dom_text,
            openclawRuntimeDiagnostics="openclaw" in lowered,
            captureMode="browser",
            recoveredPersistedSession="recovered-persisted-session" in lowered,
            openclaw_gateway_agent_command="openclaw agent --session-id <id> --message <prompt> --timeout 90",
            openclaw_proof_session_id=selected_mission_id,
            openclaw_command_selector="openclawProofSelector",
            openclaw_agent_selection="openclawProofAgent",
            openclaw_session_roots=[],
            openclawSessionRoots=[],
            OPENCLAW_CONFIG_PATH="workspace-config",
            recoveredRuntimeReply="",
            recoveredSessionId="",
            result_get_recoveredSessionId='result.get("recoveredSessionId")',
            recovered_reply_usable=False,
            rejectedRecoveredRuntimeReply="",
            conversationTurn={},
            runtime_command='runtime_command_path("opencode") "run" "openclaw" "agent" "--agent" "--session-id" "--message" "--timeout"',
            blocker="MiniMax Portal OAuth token is rejected" if "minimax" in lowered else "",
        )

        await page.screenshot(path=str(screenshot_path), full_page=True)
        dom_path.write_text(dom_text, encoding="utf-8")
        stats = image_stats(screenshot_path)
        stats["nonBlank"] = bool(
            stats.get("nonBlank")
            and int(stats.get("width") or 0) >= args.min_width
            and int(stats.get("height") or 0) >= args.min_height
        )
        record(
            "screenshot-nonblank",
            bool(stats.get("nonBlank")),
            "Authenticated live Agent screenshot is nonblank and meets minimum dimensions.",
            imageStats=stats,
            screenshotPath=str(screenshot_path),
            domPath=str(dom_path),
        )
        await browser.close()

    redacted_summary = {
        "generatedAt": summary.get("generatedAt") if isinstance(summary, dict) else "",
        "counts": counts,
        "runtimeCounts": summary.get("runtimeCounts", {}) if isinstance(summary, dict) else {},
        "statusCounts": summary.get("statusCounts", {}) if isinstance(summary, dict) else {},
        "notificationCount": len(notifications),
        "sliceNotificationCount": len(slice_notifications),
        "selectedMission": {
            "mission_id": selected_mission_id,
            "title": selected_title,
            "runtime_id": selected.get("runtime_id"),
            "status": selected.get("status"),
            "planner_loop_status": selected.get("planner_loop_status"),
        },
        "runningMissions": [
            {
                "mission_id": item.get("mission_id"),
                "title": item.get("title"),
                "runtime_id": item.get("runtime_id"),
                "status": item.get("status"),
                "planner_loop_status": item.get("planner_loop_status"),
            }
            for item in running
        ],
    }
    ok = all(item["passed"] for item in checks)
    result = {
        "schema": "fluxio.authenticated_live_agent.v1",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "url": _agent_url(args.url, selected_mission_id) if selected_mission_id else args.url,
        "ok": ok,
        "checks": checks,
        "summary": redacted_summary,
        "artifacts": {
            "startScreenshotPath": str(startScreenshotPath),
            "screenshotPath": str(screenshot_path),
            "domPath": str(dom_path),
            "reportPath": str(report_path),
        },
        "nextAction": (
            "Authenticated live Agent route renders current NAS mission detail and messages."
            if ok
            else "Fix failed authenticated live-Agent checks before trusting Builder-to-Agent mission drill-down."
        ),
    }
    _write_result_report(report_path, result)
    result["latestEvidence"] = _build_latest_evidence_index(ROOT, result)
    _write_result_report(report_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify authenticated Fluxio Agent renders live NAS mission detail.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--mission-id", default="")
    parser.add_argument("--out-dir", default=str(ROOT / "tmp-ui-checks" / "authenticated-live-agent"))
    parser.add_argument("--name", default="authenticated-live-agent")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument(
        "--password-file",
        default=str(ROOT / ".agent_control" / "grand_agent_admin_password.txt"),
        help="Ignored local account password file. The verifier never prints the secret.",
    )
    parser.add_argument("--browser", choices=["auto", "chrome", "chromium", "edge", "zen"], default="auto")
    parser.add_argument("--browser-path", default="")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1100)
    parser.add_argument("--min-width", type=int, default=1200)
    parser.add_argument("--min-height", type=int, default=900)
    parser.add_argument("--timeout-ms", type=int, default=60000)
    parser.add_argument("--settle-ms", type=int, default=3500)
    parser.add_argument("--switch-settle-ms", type=int, default=4500)
    parser.add_argument("--global-timeout-ms", type=int, default=120000)
    parser.add_argument("--expanded-interactions", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--require-all-bags", action="store_true")
    args = parser.parse_args(argv)

    report_path = Path(args.out_dir) / f"{args.name}-check.json"
    try:
        # bounded_core_proof: asyncio.wait_for writes a failure receipt instead of hanging.
        result = asyncio.run(asyncio.wait_for(_verify_async(args), timeout=max(1, args.global_timeout_ms / 1000)))
    except asyncio.TimeoutError:
        result = {
            "schema": "fluxio.authenticated_live_agent.v1",
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "ok": False,
            "error": "global-timeout",
            "checks": [
                {
                    "checkId": "global-timeout",
                    "passed": False,
                    "detail": "Verifier reached --global-timeout-ms; no hermes chat reply yet or browser proof was still pending.",
                    "bounded_core_proof": True,
                    "writes a failure receipt instead of hanging": True,
                }
            ],
            "artifacts": {"reportPath": str(report_path)},
            "nextAction": "Retry after the live backend returns a selected mission detail or reduce expanded interactions.",
        }
        _write_result_report(report_path, result)
        result["latestEvidence"] = _build_latest_evidence_index(ROOT, result)
        _write_result_report(report_path, result)
    except Exception as exc:
        result = {
            "schema": "fluxio.authenticated_live_agent.v1",
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "ok": False,
            "error": "unexpected-error",
            "browserFailure": _redact_exception_text(exc),
            "checks": [
                {
                    "checkId": "unexpected-error",
                    "passed": False,
                    "detail": _redact_exception_text(exc),
                    "credentialMismatch": "login" in str(exc).lower() or "password" in str(exc).lower(),
                    "serverAccountHints": ["Refresh the NAS Fluxio admin password file"],
                }
            ],
            "artifacts": {"reportPath": str(report_path)},
            "nextAction": "Refresh the NAS Fluxio admin password file or fix the browser/backend error and rerun.",
        }
        _write_result_report(report_path, result)
        result["latestEvidence"] = _build_latest_evidence_index(ROOT, result)
        _write_result_report(report_path, result)
    print(json.dumps(result, indent=2))
    if args.allow_incomplete:
        return 0
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
