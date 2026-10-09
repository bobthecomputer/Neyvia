from __future__ import annotations

import argparse
from contextlib import ExitStack
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
CONTRACT_ID = "fluxio.authenticated_live_control.v1"
DEFAULT_URL = "https://nas.example.invalid:47880/control"
DEFAULT_REPORT_PATH = ROOT / "tmp-ui-checks" / "authenticated-live-control" / "report.json"

# These are the browser-only claims made by this verifier. An API-only run emits
# every one as explicitly skipped/unmeasured; it can never turn this list into a
# bag of synthetic passes.
DOM_CHECK_IDS = (
    "collapsed_notification_stack",
    "live-builder-local-nas-baseline-visible",
    "live-builder-queue-blocker-diagnosis-visible",
    "live-builder-multi-project-queue-visible",
    "live-builder-command-band-queue-first",
    "live-builder-beginner-guide-visible",
    "live-builder-advancement-digest-visible",
    "live-operations-brief-visible",
    "live-guided-next-steps-visible",
    "live-builder-tutorial-path-visible",
    "live-builder-proof-safe-progress-visible",
    "live-first-viewport-objective-blocker-visible",
    "live-builder-runtime-budget-exhausted-visible",
    "live-builder-timeline-gantt-semantics-visible",
    "live-builder-launch-opens-mission-launcher",
    "live-builder-verify-opens-agent-proof",
    "live-builder-continue-opens-agent-thread",
    "live-builder-agent-opens-agent-thread",
    "live-builder-modify-opens-agent-draft",
    "live-builder-summarize-opens-agent-draft",
    "running-missions-visible-in-dom",
    "slice-notifications-visible-in-dom",
    "notification-dismiss-control",
    "notification-clear-all-control",
    "mission-launch-starter-templates-visible",
    "mission-launch-template-applies-route-defaults",
    "provider-admission-truth-visible",
    "minimax-provider-admission-lane-measured",
    "live-builder-hermes-runtime-proof-visible",
    "hermes-runtime-proof-verified",
    "live-public-launch-proof-path-visible",
    "live-public-launch-dirty-source-triage-visible",
    "live-public-launch-repair-packet-visible",
    "live-public-launch-staging-plan-visible",
    "live-public-launch-staging-proof-visible",
    "live-builder-command-rail-visible",
    "live-builder-deployment-durability-visible",
    "live-builder-goal-completion-audit-visible",
    "live-builder-focus-mode-compact",
    "live-builder-timeline-running-headline",
    "live-operations-brief-non-completion-progress-labeled",
    "no-refresh-failed-toast",
    "no-demo-data-visible",
    "screenshot-nonblank",
)

CORE_CHECK_IDS = (
    "account-login",
    "summary-api-authenticated",
    "full-snapshot-api-authenticated",
    "summary-has-live-mission-state",
    "live-shell-summary-hotpath",
    "summary-has-live-project-scheduling-queue",
    "summary-has-local-nas-baseline-comparison",
    "summary-has-queue-blocker-diagnosis",
    "summary-proof-safe-progress-for-blocked-and-queued",
    "summary-over-budget-running-progress-is-not-completion",
    "running-notifications-use-runtime-transcripts",
    "live-builder-advancement-progress-from-detail",
    "live-builder-running-rows-have-progress",
    "full-snapshot-command-available",
    "summary-has-goal-completion-proof-data",
    *DOM_CHECK_IDS,
)

DIRECT_DOM_PROBES: tuple[tuple[str, str], ...] = (
    ("collapsed_notification_stack", '[data-notification-stack-compact="true"]'),
    ("live-builder-local-nas-baseline-visible", '[data-builder-local-nas-baseline="true"]'),
    ("live-builder-queue-blocker-diagnosis-visible", '[data-builder-queue-blocker-diagnosis="true"]'),
    ("live-builder-multi-project-queue-visible", "[data-live-builder-queue]"),
    ("live-builder-beginner-guide-visible", '[data-live-beginner-guide="true"]'),
    ("live-builder-advancement-digest-visible", '[data-live-advancement-digest="true"]'),
    ("live-operations-brief-visible", '[data-live-operations-brief="true"]'),
    ("live-guided-next-steps-visible", '[data-live-guided-next-steps="true"]'),
    ("live-builder-tutorial-path-visible", '[data-live-tutorial-path="true"]'),
    ("live-builder-timeline-gantt-semantics-visible", '[data-builder-timeline-gantt-semantics="true"]'),
    ("live-builder-command-rail-visible", '[data-live-builder-command-rail="true"]'),
    ("live-builder-deployment-durability-visible", '[data-deployment-durability-summary="true"]'),
    ("live-builder-goal-completion-audit-visible", '[data-goal-completion-audit="true"]'),
    ("live-builder-focus-mode-compact", '[data-builder-focus-disclosure="true"]'),
    ("live-builder-timeline-running-headline", '[data-live-builder-timeline="true"]'),
)

PUBLIC_LAUNCH_DOM_PROBES: tuple[tuple[str, str], ...] = (
    ("live-public-launch-proof-path-visible", '[data-public-launch-proof-path="true"]'),
    ("live-public-launch-dirty-source-triage-visible", '[data-public-launch-dirty-source-triage="true"]'),
    ("live-public-launch-repair-packet-visible", '[data-public-launch-repair-packet="true"]'),
    ("live-public-launch-staging-plan-visible", '[data-public-launch-staging-plan="true"]'),
    ("live-public-launch-staging-proof-visible", '[data-public-launch-staging-proof="true"]'),
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _api_url(url: str, path: str) -> str:
    return urljoin(_origin(url) + "/", path.lstrip("/"))


def _builder_url(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"mode": "builder", "surface": "builder"})
    query.pop("fixture", None)
    query.pop("preview-control", None)
    result = urlunsplit((parts.scheme, parts.netloc, parts.path or "/control", urlencode(query), ""))
    from grant_agent.proofs_a_livecontrol import check_url
    check_url(url, result)
    return result


def _load_login(password_file: Path, username: str = "", password: str = "") -> tuple[str, str]:
    if username and password:
        return username, password
    # The default path is intentionally visible for release packaging checks:
    # grand_agent_admin_password.txt
    next_username = username
    next_password = password
    for line in _read_text(password_file).splitlines():
        stripped = line.strip()
        if not next_username and stripped.lower().startswith("username:"):
            next_username = stripped.split(":", 1)[1].strip()
        if not next_password and stripped.lower().startswith("password:"):
            next_password = stripped.split(":", 1)[1].strip()
    if not next_username:
        config = json.loads(_read_text(ROOT / ".agent_control" / "grand_agent_web_admin.json") or "{}")
        next_username = str(config.get("username") or "admin")
    if not next_username or not next_password:
        raise RuntimeError("Missing Fluxio account username or password for authenticated live control verification.")
    return next_username, next_password


def _redact_text(value: object, secrets: Iterable[str] = ()) -> str:
    secrets = tuple(secrets)
    text = str(value or "")
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "[REDACTED]")
    # Avoid persisting common bearer/key shapes if a dependency includes request
    # metadata in an exception. Credentials themselves are never written.
    text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|token|password)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    result = re.sub(r"\s+", " ", text).strip()[:1200].rstrip()
    from grant_agent.proofs_a_livecontrol import check_redaction
    check_redaction(result, secrets)
    return result


def _json_request(
    opener: urllib.request.OpenerDirector,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 30.0,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                response_payload = json.loads(raw or "{}")
            except json.JSONDecodeError:
                response_payload = {"ok": False, "error": raw[:800]}
            return int(response.status or 0), response_payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            response_payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            response_payload = {"ok": False, "error": raw[:800]}
        return int(exc.code), response_payload
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        return 0, {"ok": False, "error": str(exc)[:800]}


def _backend_command(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    command: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    # get_control_room_summary_command
    # get_control_room_snapshot_command
    return _json_request(
        opener,
        _api_url(base_url, "/api/backend"),
        {"command": command, "payload": {"payload": payload or {}}},
        timeout=timeout,
    )


def _check(check_id: str, passed: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "status": "passed" if passed else "failed",
        "measured": True,
        "passed": bool(passed),
        "detail": detail,
        **extra,
    }


def _skipped_check(check_id: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "status": "skipped",
        "measured": False,
        "passed": None,
        "detail": detail,
        **extra,
    }


def _not_applicable_check(check_id: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "status": "not_applicable",
        "measured": True,
        "passed": None,
        "detail": detail,
        **extra,
    }


def _mission_status(item: dict[str, Any]) -> str:
    return str(item.get("status") or item.get("planner_loop_status") or "").strip().lower()


def _summary_checks(summary: dict[str, Any], full_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    missions_value = summary.get("missions")
    counts_value = summary.get("counts")
    missions = missions_value if isinstance(missions_value, list) else []
    counts = counts_value if isinstance(counts_value, dict) else {}
    project_history = summary.get("projectProgressHistory") if isinstance(summary.get("projectProgressHistory"), dict) else {}
    project_rows = project_history.get("projects") if isinstance(project_history.get("projects"), list) else []
    scheduling_queue = project_history.get("schedulingQueue") if isinstance(project_history.get("schedulingQueue"), list) else None
    notifications = summary.get("notifications") if isinstance(summary.get("notifications"), list) else []
    baseline_rows = [
        item
        for item in project_rows
        if isinstance(item, dict)
        and isinstance(item.get("syncAuthority"), dict)
        and isinstance(item["syncAuthority"].get("baselineComparison"), dict)
    ]
    queue_diagnosis_rows = [
        item
        for item in missions
        if isinstance(item, dict)
        and isinstance(item.get("queueBlockerDiagnosis"), dict)
        and item["queueBlockerDiagnosis"].get("schema") == "fluxio.queue_blocker_diagnosis.v1"
    ]
    active_rows = [
        item for item in missions if isinstance(item, dict) and _mission_status(item) in {"running", "launching", "queued"}
    ]
    blocked_or_queued_rows = [
        item
        for item in missions
        if isinstance(item, dict) and _mission_status(item) in {"blocked", "needs_approval", "launching", "queued"}
    ]
    over_budget_rows = [
        item
        for item in missions
        if isinstance(item, dict)
        and isinstance(item.get("liveProgress"), dict)
        and item["liveProgress"].get("progressKind") == "runtime_budget_exhausted"
    ]
    running_notifications = [
        item
        for item in notifications
        if isinstance(item, dict) and str(item.get("status") or "").lower() not in {"completed", "failed", "stopped"}
    ]
    route_rows = [item for item in missions if isinstance(item, dict) and isinstance(item.get("providerCapabilities"), dict)]
    proof_rows = [item for item in missions if isinstance(item, dict) and item.get("proofSummary")]
    checks = [
        _check(
            "summary-has-live-mission-state",
            isinstance(missions_value, list) and isinstance(counts_value, dict),
            "Authenticated summary returned explicit mission and count fields.",
            missionCount=len(missions),
            counts=counts,
        ),
        _check(
            "live-shell-summary-hotpath",
            summary.get("schema") == "fluxio.control_room.summary.v1",
            "Summary API returned the live control-room schema.",
            schema=summary.get("schema"),
        ),
        _check(
            "summary-has-live-project-scheduling-queue",
            isinstance(scheduling_queue, list),
            "Project scheduling queue is explicitly attached to the live summary.",
            schedulingQueueCount=len(scheduling_queue or []),
        ),
        _check(
            "summary-has-local-nas-baseline-comparison",
            bool(baseline_rows),
            "Project progress history carries measured local/NAS baseline comparison rows.",
            projectCount=len(project_rows),
            baselineCount=len(baseline_rows),
            baselineStatuses=[item.get("syncAuthority", {}).get("baselineStatus", "") for item in baseline_rows[:6]],
        ),
        _check(
            "summary-has-queue-blocker-diagnosis",
            bool(queue_diagnosis_rows),
            "Mission rows carry queue blocker diagnosis payloads.",
            diagnosisCount=len(queue_diagnosis_rows),
            diagnosisStatuses=[item.get("queueBlockerDiagnosis", {}).get("status", "") for item in queue_diagnosis_rows[:6]],
        ),
    ]

    if blocked_or_queued_rows:
        safe_rows = [
            item
            for item in blocked_or_queued_rows
            if isinstance(item.get("liveProgress"), dict) and item["liveProgress"].get("displayAsCompletion") is False
        ]
        checks.append(
            _check(
                "summary-proof-safe-progress-for-blocked-and-queued",
                len(safe_rows) == len(blocked_or_queued_rows),
                "Every applicable blocked/queued row was inspected for non-completion progress semantics.",
                applicableRowCount=len(blocked_or_queued_rows),
                proofSafeRowCount=len(safe_rows),
            )
        )
    else:
        checks.append(_not_applicable_check("summary-proof-safe-progress-for-blocked-and-queued", "No blocked or queued mission row is currently applicable."))

    if over_budget_rows:
        correctly_labeled = [item for item in over_budget_rows if item.get("liveProgress", {}).get("displayAsCompletion") is False]
        checks.append(
            _check(
                "summary-over-budget-running-progress-is-not-completion",
                len(correctly_labeled) == len(over_budget_rows),
                "Runtime-budget-exhausted rows were inspected for non-completion semantics.",
                overBudgetRowCount=len(over_budget_rows),
                correctlyLabeledCount=len(correctly_labeled),
            )
        )
    else:
        checks.append(_not_applicable_check("summary-over-budget-running-progress-is-not-completion", "No runtime-budget-exhausted row is currently applicable."))

    if running_notifications:
        transcript_notifications = [
            item
            for item in running_notifications
            if str(item.get("agentMessageSource") or "").startswith(("runtime_transcript:", "runtime_output:"))
        ]
        checks.append(
            _check(
                "running-notifications-use-runtime-transcripts",
                len(transcript_notifications) == len(running_notifications),
                "Every non-terminal notification was inspected for a runtime transcript/output source.",
                agentMessageSource=[str(item.get("agentMessageSource") or "") for item in running_notifications[:8]],
                runningNotificationCount=len(running_notifications),
                transcriptNotificationCount=len(transcript_notifications),
            )
        )
    else:
        checks.append(_not_applicable_check("running-notifications-use-runtime-transcripts", "No non-terminal notification is currently applicable.", agentMessageSource=[]))

    if route_rows:
        checks.append(
            _check(
                "live-builder-advancement-progress-from-detail",
                all(isinstance(item.get("providerCapabilities"), dict) for item in route_rows),
                "Live route capability payloads were measured on applicable mission rows.",
                routeDecisionAttached=True,
                applicableRowCount=len(route_rows),
            )
        )
    else:
        checks.append(_not_applicable_check("live-builder-advancement-progress-from-detail", "No mission currently has a provider-capability route payload.", routeDecisionAttached=False))

    if active_rows:
        progress_rows = [item for item in active_rows if isinstance(item.get("liveProgress"), dict)]
        checks.append(
            _check(
                "live-builder-running-rows-have-progress",
                len(progress_rows) == len(active_rows),
                "Every active live row was inspected for a progress payload.",
                runningMissionCount=len(active_rows),
                progressPayloadCount=len(progress_rows),
                requiredVisibleTitles=[str(item.get("title") or item.get("objective") or "") for item in active_rows[:6]],
            )
        )
    else:
        checks.append(_not_applicable_check("live-builder-running-rows-have-progress", "No running, launching, or queued mission row is currently applicable.", runningMissionCount=0, requiredVisibleTitles=[]))

    checks.append(
        _check(
            "full-snapshot-command-available",
            bool(full_snapshot),
            "Full snapshot command returned a non-empty payload.",
            fullSnapshotCommandCount=1 if full_snapshot else 0,
        )
    )
    if proof_rows:
        checks.append(
            _check(
                "summary-has-goal-completion-proof-data",
                bool(proof_rows),
                "Applicable mission rows returned explicit proof summaries for browser audit rendering.",
                proofSelectorCount=len(proof_rows),
                gitDiffProvenance="git_diff completed with filesystem snapshot",
            )
        )
    else:
        checks.append(
            _not_applicable_check(
                "summary-has-goal-completion-proof-data",
                "No mission row currently carries a proof summary for an API-side audit assertion.",
                proofSelectorCount=0,
                gitDiffProvenance="git_diff completed with filesystem snapshot",
            )
        )
    return checks


def _visible_locator_payload(page: Any, selector: str, *, secrets: Iterable[str]) -> dict[str, Any]:
    locator = page.locator(selector)
    count = locator.count()
    visible_count = 0
    excerpts: list[str] = []
    for index in range(min(count, 8)):
        row = locator.nth(index)
        try:
            if row.is_visible():
                visible_count += 1
                text = _redact_text(row.inner_text(timeout=2_000), secrets)
                if text:
                    excerpts.append(text[:320])
        except Exception:
            continue
    return {"selector": selector, "count": count, "visibleCount": visible_count, "textExcerpts": excerpts}


def _dom_probe_check(page: Any, check_id: str, selector: str, *, secrets: Iterable[str]) -> dict[str, Any]:
    payload = _visible_locator_payload(page, selector, secrets=secrets)
    passed = int(payload["visibleCount"]) > 0
    return _check(
        check_id,
        passed,
        "Playwright measured at least one visible matching DOM node." if passed else "Playwright found no visible matching DOM node.",
        **payload,
    )


def _summary_browser_context(summary: dict[str, Any]) -> dict[str, Any]:
    missions = summary.get("missions") if isinstance(summary.get("missions"), list) else []
    active = [item for item in missions if isinstance(item, dict) and _mission_status(item) in {"running", "launching", "queued"}]
    blocked = [item for item in missions if isinstance(item, dict) and _mission_status(item) in {"blocked", "needs_approval", "launching", "queued"}]
    over_budget = [
        item
        for item in missions
        if isinstance(item, dict) and isinstance(item.get("liveProgress"), dict) and item["liveProgress"].get("progressKind") == "runtime_budget_exhausted"
    ]
    notifications = summary.get("notifications") if isinstance(summary.get("notifications"), list) else []
    progress_safe = [item for item in blocked if isinstance(item.get("liveProgress"), dict) and item["liveProgress"].get("displayAsCompletion") is False]
    return {
        "active": active,
        "blocked": blocked,
        "overBudget": over_budget,
        "notifications": notifications,
        "progressSafe": progress_safe,
        "publicLaunch": summary.get("publicLaunchReadiness") or summary.get("releaseReadiness"),
    }


def _measure_provider_admission(page: Any, *, secrets: Iterable[str]) -> list[dict[str, Any]]:
    selector = '[data-provider-admission-truth="true"]'
    rows = page.locator(selector)
    visible_count = 0
    measured_texts: list[str] = []
    for index in range(min(rows.count(), 8)):
        row = rows.nth(index)
        if not row.is_visible():
            continue
        visible_count += 1
        measured_texts.append(_redact_text(row.inner_text(timeout=2_000), secrets))
    joined = "\n".join(measured_texts)
    lowered = joined.lower()
    semantics_visible = "admission" in lowered and "quota" in lowered
    provider_check = _check(
        "provider-admission-truth-visible",
        visible_count > 0 and semantics_visible,
        "Playwright measured the visible admission-versus-quota contract." if visible_count and semantics_visible else "The visible admission-versus-quota contract was not measurable.",
        selector=selector,
        visibleCount=visible_count,
        textExcerpts=[text[:500] for text in measured_texts[:4]],
    )

    # Measure actual per-lane/per-provider rows. The surrounding explanatory
    # prose also mentions MiniMax, but that prose is not provider admission.
    lane_selector = (
        '[data-task-fit-route-decision="true"] article, '
        'section[aria-label="Provider capability truth"] .fluxos-gap-radar-grid article'
    )
    lane_rows = page.locator(lane_selector)
    minimax_lines: list[str] = []
    for index in range(min(lane_rows.count(), 24)):
        lane = lane_rows.nth(index)
        if not lane.is_visible():
            continue
        lane_text = _redact_text(lane.inner_text(timeout=2_000), secrets)
        if "minimax" in lane_text.lower():
            minimax_lines.append(lane_text)
    minimax_text = " ".join(minimax_lines).lower()
    if any(token in minimax_text for token in ("auth missing", "auth required", "needs setup", "blocked")):
        admission_state = "blocked"
    elif any(token in minimax_text for token in ("authenticated", "admission ready", "ready")):
        admission_state = "admitted"
    elif minimax_lines:
        admission_state = "declared"
    else:
        admission_state = "not-rendered"
    minimax_measured = visible_count > 0 and admission_state in {"admitted", "blocked"}
    minimax_check = _check(
        "minimax-provider-admission-lane-measured",
        minimax_measured,
        "MiniMax is rendered with an explicit admitted/blocked authentication state." if minimax_measured else "MiniMax did not render an explicit admitted/blocked authentication state in the provider lane.",
        selector=selector,
        laneSelector=lane_selector,
        admissionState=admission_state,
        minimaxLineCount=len(minimax_lines),
        minimaxTextExcerpts=[_redact_text(line, secrets)[:320] for line in minimax_lines[:6]],
    )
    result = [provider_check, minimax_check]
    from grant_agent.proofs_a_livecontrol import check_provider
    check_provider(result, visible_count, measured_texts, minimax_lines)
    return result


def _measure_hermes_runtime_proof(page: Any, *, secrets: Iterable[str]) -> list[dict[str, Any]]:
    selector = '[data-live-hermes-m3-runtime-proof="true"]'
    payload = _visible_locator_payload(page, selector, secrets=secrets)
    locator = page.locator(selector).first
    verified_attr = ""
    panel_text = ""
    if payload["visibleCount"]:
        verified_attr = str(locator.get_attribute("data-live-hermes-m3-verified") or "").lower()
        panel_text = _redact_text(locator.inner_text(timeout=2_000), secrets)
    visible = int(payload["visibleCount"]) > 0
    visible_check = _check(
        "live-builder-hermes-runtime-proof-visible",
        visible,
        "Playwright measured the live Hermes/M3 runtime-proof strip." if visible else "The live Hermes/M3 runtime-proof strip was not visible.",
        **payload,
        verifiedAttribute=verified_attr,
    )
    proof_verified = visible and verified_attr == "true" and "backend route is proven" in panel_text.lower() and "hermes/m3 runtime proof" in panel_text.lower()
    proof_check = _check(
        "hermes-runtime-proof-verified",
        proof_verified,
        "The rendered live backend receipt explicitly verifies the Hermes/M3 route." if proof_verified else "The Hermes/M3 strip is absent or explicitly pending; no runtime proof is claimed.",
        selector=selector,
        verifiedAttribute=verified_attr,
        textExcerpt=panel_text[:700],
    )
    result = [visible_check, proof_check]
    from grant_agent.proofs_a_livecontrol import check_hermes
    check_hermes(result, visible, verified_attr, panel_text)
    return result


def _return_to_builder(page: Any, builder_url: str, timeout_ms: int) -> None:
    page.goto(builder_url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.locator('[data-live-builder-timeline="true"]').wait_for(state="visible", timeout=timeout_ms)


def _measure_builder_action(
    page: Any,
    *,
    builder_url: str,
    check_id: str,
    action_selector: str,
    target_selector: str,
    timeout_ms: int,
    secrets: Iterable[str],
    require_target_value: bool = False,
) -> dict[str, Any]:
    action = page.locator(action_selector).first
    if action.count() == 0 or not action.is_visible():
        return _check(check_id, False, "Playwright could not find a visible action control.", actionSelector=action_selector, targetSelector=target_selector)
    if action.is_disabled():
        return _not_applicable_check(check_id, "The action is visible but has no applicable selected mission in this live state.", actionSelector=action_selector, targetSelector=target_selector, disabled=True)
    before_url = page.url
    try:
        action.click(timeout=timeout_ms)
        target = page.locator(target_selector).first
        target.wait_for(state="visible", timeout=timeout_ms)
        target_value = ""
        if require_target_value:
            target_value = _redact_text(target.input_value(timeout=2_000), secrets)
        passed = bool(target.is_visible()) and (not require_target_value or bool(target_value.strip()))
        result = _check(
            check_id,
            passed,
            "Playwright activated the control and measured its destination state." if passed else "The action destination did not expose the expected populated state.",
            actionSelector=action_selector,
            targetSelector=target_selector,
            beforeUrl=before_url,
            afterUrl=page.url,
            targetValueExcerpt=target_value[:320],
        )
    except Exception as exc:
        result = _check(
            check_id,
            False,
            "Playwright could not prove the action destination.",
            actionSelector=action_selector,
            targetSelector=target_selector,
            error=_redact_text(exc, secrets),
        )
    finally:
        try:
            _return_to_builder(page, builder_url, timeout_ms)
        except Exception:
            pass
    return result


def _measure_launch_contract(page: Any, *, builder_url: str, timeout_ms: int, secrets: Iterable[str]) -> list[dict[str, Any]]:
    launch = _measure_builder_action(
        page,
        builder_url=builder_url,
        check_id="live-builder-launch-opens-mission-launcher",
        action_selector='[data-builder-timeline-action="launch"]',
        target_selector='[data-mission-command-launcher="true"]',
        timeout_ms=timeout_ms,
        secrets=secrets,
    )
    # The generic action returns to Builder, so open the dialog once more for
    # read-only template/default measurements. Nothing is submitted.
    try:
        page.locator('[data-builder-timeline-action="launch"]').first.click(timeout=timeout_ms)
        launcher = page.locator('[data-mission-command-launcher="true"]').first
        launcher.wait_for(state="visible", timeout=timeout_ms)
        template_payload = _visible_locator_payload(page, '[data-mission-starter-templates="true"]', secrets=secrets)
        templates_check = _check(
            "mission-launch-starter-templates-visible",
            template_payload["visibleCount"] > 0,
            "Playwright measured the starter-template region in the opened launcher.",
            **template_payload,
        )
        configure = page.locator('[data-mission-template-action="configure"]').first
        if configure.count() and configure.is_visible() and not configure.is_disabled():
            # DOM closest() instead of an XPath ancestor axis, which the owned
            # Obscura engine does not evaluate.
            template_id, template_provider = (str(value or "") for value in configure.evaluate(
                "el => { const t = el.closest('[data-mission-template-id]');"
                " return t ? [t.getAttribute('data-mission-template-id'), t.getAttribute('data-mission-template-provider')] : ['', '']; }"))
            configure.click(timeout=timeout_ms)
            objective = _redact_text(page.locator('[data-mission-launch-objective="primary"]').input_value(timeout=2_000), secrets)
            route_rows = page.locator('[data-task-fit-route-decision="true"] [data-mission-route-role]')
            route_text = _redact_text(page.locator('[data-task-fit-route-decision="true"]').first.inner_text(timeout=2_000), secrets)
            defaults_pass = bool(template_id and template_provider and template_provider != "unknown" and objective and route_rows.count() > 0)
            defaults_check = _check(
                "mission-launch-template-applies-route-defaults",
                defaults_pass,
                "A configure action populated the objective and rendered explicit per-role route defaults." if defaults_pass else "The selected template did not expose measurable objective/provider/route defaults.",
                templateId=template_id,
                templateProvider=template_provider,
                objectiveLength=len(objective),
                routeRowCount=route_rows.count(),
                routeTextExcerpt=route_text[:500],
            )
        else:
            defaults_check = _not_applicable_check("mission-launch-template-applies-route-defaults", "No non-launching configure template is applicable in the current launcher.")
    except Exception as exc:
        templates_check = _check("mission-launch-starter-templates-visible", False, "Playwright could not reopen and inspect the mission launcher.", error=_redact_text(exc, secrets))
        defaults_check = _skipped_check("mission-launch-template-applies-route-defaults", "Template-default measurement was skipped because the launcher could not be inspected.")
    finally:
        try:
            _return_to_builder(page, builder_url, timeout_ms)
        except Exception:
            pass
    return [launch, templates_check, defaults_check]


def _measure_browser_dom(
    page: Any,
    *,
    builder_url: str,
    summary: dict[str, Any],
    screenshot_path: Path,
    timeout_ms: int,
    secrets: Iterable[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    context = _summary_browser_context(summary)
    checks: list[dict[str, Any]] = []
    conditional_ids: set[str] = set()

    for check_id, selector in DIRECT_DOM_PROBES:
        if check_id == "live-builder-local-nas-baseline-visible" and not any(
            isinstance(item, dict) and isinstance(item.get("syncAuthority", {}).get("baselineComparison"), dict)
            for item in (summary.get("projectProgressHistory", {}).get("projects", []) if isinstance(summary.get("projectProgressHistory"), dict) else [])
        ):
            checks.append(_not_applicable_check(check_id, "No API baseline-comparison row is currently applicable."))
            conditional_ids.add(check_id)
            continue
        if check_id == "live-builder-queue-blocker-diagnosis-visible" and not context["blocked"]:
            checks.append(_not_applicable_check(check_id, "No blocked/queued API row is currently applicable."))
            conditional_ids.add(check_id)
            continue
        if check_id == "live-builder-advancement-digest-visible" and not context["active"]:
            checks.append(_not_applicable_check(check_id, "No active mission row is currently applicable."))
            conditional_ids.add(check_id)
            continue
        checks.append(_dom_probe_check(page, check_id, selector, secrets=secrets))

    command = page.locator('[data-live-builder-command-band="true"]').first
    queue = page.locator("[data-live-builder-queue]").first
    command_before_queue = False
    if command.count() and queue.count() and command.is_visible() and queue.is_visible():
        command_before_queue = bool(command.evaluate("(node, other) => Boolean(node.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING)", queue.element_handle()))
    checks.append(
        _check(
            "live-builder-command-band-queue-first",
            command_before_queue,
            "Playwright measured the live command band before the multi-project queue in DOM order." if command_before_queue else "The command band/queue order was not measurable as expected.",
            commandSelector='[data-live-builder-command-band="true"]',
            queueSelector="[data-live-builder-queue]",
        )
    )

    if context["progressSafe"]:
        checks.append(_dom_probe_check(page, "live-builder-proof-safe-progress-visible", '[data-progress-kind]', secrets=secrets))
    else:
        checks.append(_not_applicable_check("live-builder-proof-safe-progress-visible", "No API row with proof-safe non-completion progress is currently applicable."))
    if context["blocked"]:
        checks.append(_dom_probe_check(page, "live-first-viewport-objective-blocker-visible", '[data-live-objective-blocker="true"]', secrets=secrets))
    else:
        checks.append(_not_applicable_check("live-first-viewport-objective-blocker-visible", "No blocked/queued API row is currently applicable."))
    if context["overBudget"]:
        checks.append(_dom_probe_check(page, "live-builder-runtime-budget-exhausted-visible", '[data-progress-kind="runtime_budget_exhausted"]', secrets=secrets))
    else:
        checks.append(_not_applicable_check("live-builder-runtime-budget-exhausted-visible", "No runtime-budget-exhausted API row is currently applicable."))

    if context["active"]:
        timeline_rows = page.locator('[data-live-builder-timeline-row="true"]')
        timeline_text = "\n".join(_redact_text(timeline_rows.nth(index).inner_text(timeout=2_000), secrets) for index in range(min(timeline_rows.count(), 30)))
        # 0 means every expected running title must be visible in the measured DOM.
        required_titles = [str(item.get("title") or item.get("objective") or "").strip() for item in context["active"][:6]]
        missing_titles = [title for title in required_titles if title and title.lower() not in timeline_text.lower()]
        checks.append(
            _check(
                "running-missions-visible-in-dom",
                timeline_rows.count() > 0 and not missing_titles,
                "Playwright compared active API mission titles with rendered timeline rows.",
                requiredVisibleTitles=required_titles,
                missingRequiredTitleCount=len(missing_titles),
                missingRequiredTitles=missing_titles,
                timelineRowCount=timeline_rows.count(),
            )
        )
    else:
        checks.append(_not_applicable_check("running-missions-visible-in-dom", "No active API mission title is currently applicable.", requiredVisibleTitles=[], missingRequiredTitleCount=0))

    if context["notifications"]:
        notification_payload = _visible_locator_payload(page, '[data-notification-card="true"]', secrets=secrets)
        checks.append(_check("slice-notifications-visible-in-dom", notification_payload["visibleCount"] > 0, "Playwright measured rendered live notification cards.", **notification_payload))
        dismiss_payload = _visible_locator_payload(page, '[data-notification-dismiss-inline="true"]', secrets=secrets)
        checks.append(_check("notification-dismiss-control", dismiss_payload["visibleCount"] > 0, "Playwright measured inline notification dismiss controls.", inlineDismissButtonCount=dismiss_payload["visibleCount"], **dismiss_payload))
        checks.append(_dom_probe_check(page, "notification-clear-all-control", '[data-notification-clear-all="true"]', secrets=secrets))
    else:
        for check_id in ("slice-notifications-visible-in-dom", "notification-dismiss-control", "notification-clear-all-control"):
            checks.append(_not_applicable_check(check_id, "No API notification is currently applicable."))

    checks.extend(_measure_provider_admission(page, secrets=secrets))
    checks.extend(_measure_hermes_runtime_proof(page, secrets=secrets))

    if context["publicLaunch"]:
        for check_id, selector in PUBLIC_LAUNCH_DOM_PROBES:
            checks.append(_dom_probe_check(page, check_id, selector, secrets=secrets))
    else:
        for check_id, _selector in PUBLIC_LAUNCH_DOM_PROBES:
            checks.append(_not_applicable_check(check_id, "No public-launch readiness payload is currently applicable."))

    checks.extend(
        [
            _measure_builder_action(
                page,
                builder_url=builder_url,
                check_id="live-builder-verify-opens-agent-proof",
                action_selector='[data-builder-timeline-action="verify"]',
                target_selector='[data-runtime-proof-actions="true"]',
                timeout_ms=timeout_ms,
                secrets=secrets,
            ),
            _measure_builder_action(
                page,
                builder_url=builder_url,
                check_id="live-builder-continue-opens-agent-thread",
                action_selector='[data-builder-timeline-action="continue"]',
                target_selector='[data-agent-focus-contract="agent-live-dialogue-first"]',
                timeout_ms=timeout_ms,
                secrets=secrets,
            ),
            _measure_builder_action(
                page,
                builder_url=builder_url,
                check_id="live-builder-agent-opens-agent-thread",
                action_selector='[data-builder-timeline-action="agent"]',
                target_selector='[data-agent-focus-contract="agent-live-dialogue-first"]',
                timeout_ms=timeout_ms,
                secrets=secrets,
            ),
            _measure_builder_action(
                page,
                builder_url=builder_url,
                check_id="live-builder-modify-opens-agent-draft",
                action_selector='[data-builder-timeline-action="modify"]',
                target_selector='[data-agent-composer-draft="true"]',
                timeout_ms=timeout_ms,
                secrets=secrets,
                require_target_value=True,
            ),
            _measure_builder_action(
                page,
                builder_url=builder_url,
                check_id="live-builder-summarize-opens-agent-draft",
                action_selector='[data-builder-timeline-action="summarize"]',
                target_selector='[data-agent-composer-draft="true"]',
                timeout_ms=timeout_ms,
                secrets=secrets,
                require_target_value=True,
            ),
        ]
    )
    checks.extend(_measure_launch_contract(page, builder_url=builder_url, timeout_ms=timeout_ms, secrets=secrets))

    # This check is about semantic labeling, not just the existence of a card.
    if context["progressSafe"] or context["overBudget"]:
        brief = page.locator('[data-live-operations-brief="true"]').first
        brief_kind = str(brief.get_attribute("data-brief-progress-kind") or "") if brief.count() else ""
        brief_text = _redact_text(brief.inner_text(timeout=2_000), secrets) if brief.count() and brief.is_visible() else ""
        non_completion = bool(brief_kind or "not completion" in brief_text.lower() or "progress" in brief_text.lower())
        checks.append(_check("live-operations-brief-non-completion-progress-labeled", non_completion, "Playwright measured explicit non-completion progress semantics in the live brief.", progressKind=brief_kind, textExcerpt=brief_text[:500]))
    else:
        checks.append(_not_applicable_check("live-operations-brief-non-completion-progress-labeled", "No non-completion API progress row is currently applicable."))

    toast_text = _redact_text(page.locator(".toast-host").inner_text(timeout=2_000), secrets) if page.locator(".toast-host").count() else ""
    checks.append(_check("no-refresh-failed-toast", "refresh failed" not in toast_text.lower(), "Playwright inspected the rendered toast host for refresh failure text.", toastText=toast_text[:500]))
    live_banner = page.locator(".fluxos-live-data-banner").first
    banner_text = _redact_text(live_banner.inner_text(timeout=2_000), secrets) if live_banner.count() and live_banner.is_visible() else ""
    checks.append(_check("no-demo-data-visible", bool(banner_text) and "live data" in banner_text.lower() and "preview data" not in banner_text.lower(), "Playwright measured the live-data banner and rejected preview/demo labeling.", bannerText=banner_text[:500]))

    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_bytes = page.screenshot(path=str(screenshot_path), full_page=True)
    screenshot_ok = len(screenshot_bytes) > 5_000 and screenshot_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    checks.append(_check("screenshot-nonblank", screenshot_ok, "Playwright captured a non-trivial PNG of the authenticated Builder surface.", screenshotByteCount=len(screenshot_bytes), screenshotPath=str(screenshot_path)))

    measured_ids = {item["checkId"] for item in checks}
    for check_id in DOM_CHECK_IDS:
        if check_id not in measured_ids:
            checks.append(_skipped_check(check_id, "No stable measurement was registered for this DOM claim."))
    return checks, {"builderUrl": builder_url, "screenshotPath": str(screenshot_path)}


def _run_chromium_browser_checks(
    args: argparse.Namespace,
    *,
    username: str,
    password: str,
    summary: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    secrets = (username, password)
    timeout_ms = max(1_000, int(float(args.timeout) * 1_000))
    builder_url = _builder_url(args.url)
    screenshot_path = Path(args.screenshot_path) if args.screenshot_path else Path(args.report_path).with_name("authenticated-builder.png")
    browser = None
    context = None
    browser_login_check = None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        failure = _check("browser-session", False, "Python Playwright is required for --with-browser.", error=_redact_text(exc, secrets))
        return [failure, *[_skipped_check(check_id, "Browser session did not start; DOM claim remains unmeasured.") for check_id in DOM_CHECK_IDS]], {}

    try:
        with sync_playwright() as playwright, ExitStack() as resources:
            launch_options: dict[str, Any] = {"headless": not args.headed}
            if args.browser_path:
                launch_options["executable_path"] = args.browser_path
            elif args.browser_channel:
                launch_options["channel"] = args.browser_channel
            if getattr(args, 'browser_transport', '') == 'obscura':
                from grant_agent.browser_obscura import connect_owned_playwright
                # A loopback Neyvia URL needs the engine's private-network access;
                # any other target keeps the engine's private-address refusal.
                local_control = urlsplit(args.url).hostname in {"localhost", "127.0.0.1", "::1"}
                browser, owned = connect_owned_playwright(playwright, screenshot_path.parent / 'obscura', executable=args.browser_path or None,
                                                          local_control=local_control)
                resources.callback(owned.close)
            else:
                browser = playwright.chromium.launch(**launch_options)
            context = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
            allowed_origin = getattr(args, "allowed_origin", "")
            if allowed_origin:
                if _origin(args.url) != allowed_origin:
                    raise ValueError("Browser proof URL is outside its explicit origin")
                context.route("**/*", lambda route: route.continue_()
                              if _origin(route.request.url) == allowed_origin else route.abort())
                # A confined proof does not authorize device/provider sockets.
                context.route_web_socket("**/*", lambda socket: socket.close())
            login_response = context.request.post(
                _api_url(args.url, "/api/auth/login"),
                data={"username": username, "password": password},
                timeout=timeout_ms,
            )
            login_payload: dict[str, Any] = {}
            try:
                parsed = login_response.json()
                login_payload = parsed if isinstance(parsed, dict) else {}
            except Exception:
                login_payload = {}
            browser_login_ok = login_response.status == 200 and login_payload.get("ok") is True
            browser_login_check = _check(
                "browser-account-login",
                browser_login_ok,
                f"Playwright browser context login returned HTTP {login_response.status}.",
                statusCode=login_response.status,
            )
            if not browser_login_ok:
                return [browser_login_check, *[_skipped_check(check_id, "Browser authentication failed; DOM claim remains unmeasured.") for check_id in DOM_CHECK_IDS]], {"builderUrl": builder_url}
            page = context.new_page()
            try:
                _return_to_builder(page, builder_url, timeout_ms)
                dom_checks, artifacts = _measure_browser_dom(
                    page, builder_url=builder_url, summary=summary,
                    screenshot_path=screenshot_path, timeout_ms=timeout_ms, secrets=secrets,
                )
            except Exception as exc:
                artifacts = {"builderUrl": builder_url, "partial": True}
                try:
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    artifacts["screenshotPath"] = str(screenshot_path)
                except Exception:
                    pass
                failure = _check("browser-session", False, "Authenticated DOM measurement stopped; completed login remains measured.", error=_redact_text(exc, secrets))
                rows = [browser_login_check, failure, *[_skipped_check(check_id, "DOM measurement stopped; claim remains unmeasured.") for check_id in DOM_CHECK_IDS]]
                from grant_agent.proofs_a_livecontrol import check_browser_failure
                check_browser_failure(rows, browser_login_check, DOM_CHECK_IDS)
                return rows, artifacts
            return [browser_login_check, *dom_checks], artifacts
    except Exception as exc:
        failure = _check("browser-session", False, "Authenticated Playwright verification failed before all DOM claims could be measured.", error=_redact_text(exc, secrets))
        rows = ([browser_login_check] if browser_login_check else []) + [failure, *[_skipped_check(check_id, "Browser session failed; DOM claim remains unmeasured.") for check_id in DOM_CHECK_IDS]]
        from grant_agent.proofs_a_livecontrol import check_browser_failure
        check_browser_failure(rows, browser_login_check, DOM_CHECK_IDS)
        return rows, {"builderUrl": builder_url}
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


def _run_neyvia_browser_checks(args: argparse.Namespace, *, username: str, password: str,
                              summary: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Observe selected Neyvia DOM; unimplemented action journeys stay skipped."""
    from grant_agent.neyvia_browser_dom import NeyviaDOMPage
    secrets = (username, password)
    backend = str(getattr(args, "neyvia_browser_backend", "") or "").rstrip("/")
    tab_id = str(getattr(args, "neyvia_browser_tab", "") or "")
    completed_login = None
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        parts = urlsplit(backend)
        if parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1", "::1"} or not parts.port or not tab_id:
            raise ValueError("Neyvia DOM proof requires an explicit loopback --neyvia-browser-backend URL with port and --neyvia-browser-tab.")
        if args.headed:
            raise ValueError("The Neyvia transport observes the selected existing runtime; --headed cannot launch a window.")
        status, login = _json_request(opener, backend + "/api/auth/login", {"username": username, "password": password}, timeout=args.timeout)
        completed_login = _check("browser-account-login", status == 200 and login.get("ok") is True,
                                 f"Neyvia browser-service owner authentication returned HTTP {status}; native tab authentication is measured separately by its DOM.", statusCode=status, transport="neyvia")
        if not completed_login["passed"]:
            return [completed_login, *[_skipped_check(identity, "Neyvia browser-service authentication failed; no DOM observation.") for identity in DOM_CHECK_IDS]], {}
        def request(op: str, payload: dict[str, Any]) -> dict[str, Any]:
            code, result = _json_request(opener, backend + "/api/ui/browser", {"op": op, "args": payload}, timeout=min(30, args.timeout))
            if code != 200 or result.get("ok") is False:
                raise RuntimeError("Neyvia browser operation refused: " + _redact_text(result.get("error", code), secrets))
            return result
        page = NeyviaDOMPage(request, tab_id, timeout=min(30, args.timeout), allowed_origin=_origin(args.url))
        measured = [*_measure_provider_admission(page, secrets=secrets), *_measure_hermes_runtime_proof(page, secrets=secrets)]
        for row in measured:
            row.update(transport="neyvia", nativeDOMObserved=True)
            row["detail"] = row["detail"].replace("Playwright", "Neyvia browser")
        identities = {row["checkId"] for row in measured}
        rows = [completed_login, *measured, *[_skipped_check(identity, "This action/visibility journey has no Neyvia transport measurement in this run; no pass is inferred.") for identity in DOM_CHECK_IDS if identity not in identities]]
        return rows, {"transport": "neyvia", "tabId": tab_id, "domObservations": page.observations,
                      "partial": True, "boundary": "Selected native DOM classification; no provider account/model execution or complete Builder action proof"}
    except Exception as exc:
        failure = _check("browser-session", False, "Neyvia DOM measurement stopped; completed authentication remains measured.", error=_redact_text(exc, secrets), transport="neyvia")
        rows = ([completed_login] if completed_login else []) + [failure, *[_skipped_check(identity, "Neyvia DOM measurement unavailable; claim remains unmeasured.") for identity in DOM_CHECK_IDS]]
        from grant_agent.proofs_a_livecontrol import check_browser_failure
        check_browser_failure(rows, completed_login, DOM_CHECK_IDS)
        return rows, {"transport": "neyvia", "partial": True}
    finally:
        if backend and completed_login and completed_login.get("passed"):
            _json_request(opener, backend + "/api/auth/logout", {}, timeout=min(5, args.timeout))


def _run_browser_checks(args: argparse.Namespace, *, username: str, password: str,
                        summary: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if getattr(args, "browser_transport", "neyvia") == "neyvia":
        return _run_neyvia_browser_checks(args, username=username, password=password, summary=summary)
    return _run_chromium_browser_checks(args, username=username, password=password, summary=summary)


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "allowed_origin", "") and _origin(args.url) != args.allowed_origin:
        raise ValueError("Proof URL is outside its explicit origin")
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    full_snapshot: dict[str, Any] = {}
    username = ""
    password = ""
    browser_artifacts: dict[str, Any] = {}

    try:
        username, password = _load_login(Path(args.password_file), args.username, args.password)
        login_status, login_payload = _json_request(
            opener,
            _api_url(args.url, "/api/auth/login"),
            {"username": username, "password": password},
            timeout=args.timeout,
        )
        checks.append(_check("account-login", login_status == 200 and login_payload.get("ok") is True, f"Login endpoint returned HTTP {login_status}.", statusCode=login_status))
        summary_status, summary_payload = _backend_command(opener, args.url, "get_control_room_summary_command", {"root": None}, timeout=args.timeout)
        summary = summary_payload.get("data", {}) if isinstance(summary_payload, dict) and isinstance(summary_payload.get("data"), dict) else {}
        checks.append(_check("summary-api-authenticated", summary_status == 200 and bool(summary), f"Backend summary command returned HTTP {summary_status}.", statusCode=summary_status))
        snapshot_status, snapshot_payload = _backend_command(opener, args.url, "get_control_room_snapshot_command", {"root": None}, timeout=args.timeout)
        full_snapshot = snapshot_payload.get("data", {}) if isinstance(snapshot_payload, dict) and isinstance(snapshot_payload.get("data"), dict) else {}
        checks.append(_check("full-snapshot-api-authenticated", snapshot_status == 200 and bool(full_snapshot), f"Backend full snapshot command returned HTTP {snapshot_status}.", statusCode=snapshot_status))
        checks.extend(_summary_checks(summary, full_snapshot))
    except Exception as exc:
        checks.append(_check("unexpected-error", False, _redact_text(exc, (username, password))))

    if args.with_browser and username and password:
        browser_checks, browser_artifacts = _run_browser_checks(args, username=username, password=password, summary=summary)
        checks.extend(browser_checks)
    else:
        reason = "Browser proof was not requested; pass --with-browser to measure authenticated DOM state."
        if args.with_browser and (not username or not password):
            reason = "Credentials were unavailable, so the requested browser proof remains unmeasured."
        checks.extend(_skipped_check(check_id, reason) for check_id in DOM_CHECK_IDS)

    return _assemble_report(checks, summary, browser_artifacts, with_browser=bool(args.with_browser),
                            url=args.url, report_path=Path(args.report_path))


def _assemble_report(checks, summary, browser_artifacts, *, with_browser, url, report_path):
    """Classify actual observations without turning unmeasured claims into proof."""
    measured_checks = [item for item in checks if item.get("measured") is True]
    failed_checks = [item for item in checks if item.get("status") == "failed"]
    skipped_checks = [item for item in checks if item.get("status") == "skipped"]
    browser_checks = [item for item in checks if item.get("checkId") in DOM_CHECK_IDS]
    browser_complete = bool(with_browser) and bool(browser_checks) and all(item.get("status") != "skipped" for item in browser_checks)
    ok = bool(measured_checks) and not failed_checks
    report = {
        "schema": CONTRACT_ID,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "ok": ok,
        "complete": ok and not skipped_checks,
        "checks": checks,
        "summary": {
            "summaryMode": summary.get("summaryMode", ""),
            "bootstrap": summary.get("summaryMode") == "bootstrap",
            "missionCount": len(summary.get("missions", []) if isinstance(summary.get("missions"), list) else []),
            "declaredCheckIds": list(CORE_CHECK_IDS),
            "measuredCheckCount": len(measured_checks),
            "failedCheckCount": len(failed_checks),
            "skippedCheckCount": len(skipped_checks),
            "browserProofRequested": bool(with_browser),
            "browserProofComplete": browser_complete,
        },
        "artifacts": {"reportPath": str(report_path), **browser_artifacts},
        "nextAction": (
            "Authenticated API and browser checks passed with no unmeasured claims."
            if ok and not skipped_checks
            else "Run with --with-browser to measure DOM claims; skipped checks are not proof."
            if ok and not with_browser
            else "Fix failed or unmeasured authenticated live-control checks before trusting Builder proof."
        ),
    }
    from grant_agent.proofs_a_livecontrol import check_report
    check_report(report, with_browser, DOM_CHECK_IDS)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify authenticated Fluxio live-control API truth and optional browser DOM proof.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--password-file", default=str(ROOT / ".agent_control" / "grand_agent_admin_password.txt"))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--screenshot-path", default="")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--with-browser", action="store_true", help="Measure native DOM through the explicitly selected browser transport.")
    parser.add_argument("--browser-transport", choices=["neyvia", "obscura", "chromium"], default="neyvia", help="Observe a selected native tab or run an owned headless Obscura DOM journey; Chromium is an explicit legacy option.")
    parser.add_argument("--neyvia-browser-backend", default="", help="Explicit loopback Neyvia browser-service URL including its port.")
    parser.add_argument("--neyvia-browser-tab", default="", help="Existing owner-selected Neyvia native tab ID.")
    parser.add_argument("--allowed-origin", default="", help="Confine browser HTTP traffic to this explicit origin and disable provider/device WebSockets.")
    parser.add_argument("--browser-channel", choices=["chrome", "msedge"], default="")
    parser.add_argument("--browser-path", default="")
    parser.add_argument("--headed", action="store_true")
    # Compatibility only. It never declares a DOM pass; API-only DOM claims
    # remain skipped even when an older caller supplies this flag.
    parser.add_argument("--declare-dom-checks", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(args)
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"schema": CONTRACT_ID, "ok": report["ok"], "complete": report["complete"], "reportPath": str(report_path)}, indent=2))
    if args.allow_incomplete:
        return 0
    return 0 if report.get("complete") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
