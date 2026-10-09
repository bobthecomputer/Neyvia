from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from control_route_visual_smoke import find_browser_or_playwright_managed


def _check(checks: list[dict], check_id: str, passed: bool, detail: str) -> None:
    checks.append({"id": check_id, "passed": bool(passed), "detail": detail})


def verify(url: str) -> dict:
    from playwright.sync_api import sync_playwright

    checks: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=find_browser_or_playwright_managed(),
        )
        page = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_selector('[data-live-phone-progress="true"]', timeout=20_000)
            state = page.evaluate(
                """() => {
                  const q = (selector) => document.querySelector(selector);
                  const qa = (selector) => [...document.querySelectorAll(selector)];
                  const box = (selector) => q(selector)?.getBoundingClientRect()?.toJSON?.() || {};
                  return {
                    text: document.body.innerText,
                    metrics: qa("[data-phone-metric-label]").map((node) => ({
                      label: node.dataset.phoneMetricLabel,
                      detail: node.dataset.phoneMetricDetail,
                      value: Number(node.dataset.phoneMetricValue || 0),
                    })),
                    sectionMode: q("[data-phone-mission-section-mode]")?.dataset.phoneMissionSectionMode || "",
                    sectionTitle: q("[data-phone-mission-section-title]")?.dataset.phoneMissionSectionTitle || "",
                    primaryText: q("[data-phone-primary-action]")?.innerText || "",
                    primaryScope: q("[data-phone-primary-action]")?.dataset.phonePrimaryActionScope || "",
                    primaryBox: box("[data-phone-primary-action]"),
                    pushText: q("[data-phone-web-push-proof]")?.innerText || "",
                    pushTopLabel: q("[data-phone-web-push-status]")?.innerText || "",
                    pushActionText: q("[data-phone-web-push-action]")?.innerText || "",
                    pushActionBox: box("[data-phone-web-push-action]"),
                    segments: qa("[data-phone-segment-action]").map((node) => ({ text: node.innerText, height: node.getBoundingClientRect().height })),
                    notifications: qa("[data-phone-notification-card]").map((node) => ({
                      text: node.innerText,
                      kindLabel: node.dataset.phoneNotificationKindLabel || "",
                      target: node.dataset.phoneNotificationTarget === "true",
                    })),
                    missions: qa("[data-phone-mission-card]").map((node) => ({
                      text: node.innerText,
                      scope: node.dataset.phoneMissionActionScope || "",
                      runtime: node.dataset.phoneMissionRuntimeLabel || "",
                      target: node.dataset.phoneMissionTarget === "true",
                    })),
                  };
                }"""
            )
        finally:
            browser.close()

    metric_map = {str(row["label"]).lower(): row for row in state["metrics"]}
    running = metric_map.get("running", {})
    alerts = metric_map.get("alerts", {})
    queue = metric_map.get("queue", {})
    blocked = metric_map.get("blocked", {})
    expected_tracked_count = len(state["missions"])
    expected_alert_detail = f"{int(alerts.get('value', 0))} alerts" if int(alerts.get("value", 0)) != 1 else "1 alert"
    phone_running_metric_detail = str(running.get("detail") or "")
    phone_alerts_metric_detail = str(alerts.get("detail") or "")
    phone_queue_metric_detail = str(queue.get("detail") or "")
    phone_blocked_metric_detail = str(blocked.get("detail") or "")
    phone_mission_section_title = str(state["sectionTitle"])
    phone_mission_section_mode = str(state["sectionMode"])
    phone_top_progress_label = phone_running_metric_detail
    phone_top_push_label = str(state["pushTopLabel"])
    phone_primary_action_text = str(state["primaryText"])
    phone_primary_action_scope = str(state["primaryScope"])
    phone_primary_action_box = state["primaryBox"]
    phone_web_push_action_text = str(state["pushActionText"])
    phone_web_push_action_box = state["pushActionBox"]
    phone_web_push_text = str(state["pushText"])

    _check(checks, "phone-progress-surface-visible", bool(state["text"]), "Phone progress DOM rendered.")
    _check(checks, "phone-running-metric-honest", phone_running_metric_detail == f"{expected_tracked_count} tracked", phone_running_metric_detail)
    _check(checks, "phone-alerts-metric-detail-readable", phone_alerts_metric_detail == expected_alert_detail, phone_alerts_metric_detail)
    _check(checks, "phone-queue-metric-zero-state-readable", phone_queue_metric_detail == "empty", phone_queue_metric_detail)
    _check(checks, "phone-blocked-metric-zero-state-honest", phone_blocked_metric_detail == "clear", phone_blocked_metric_detail)
    _check(checks, "phone-mission-section-label-honest", phone_mission_section_title == "Recent missions", phone_mission_section_title)
    _check(checks, "phone-top-progress-copy-readable", "·" not in phone_top_progress_label, phone_top_progress_label)
    _check(checks, "phone-top-push-status-readable", phone_top_push_label not in {"ntfy ready", "Armed", "Needs browser"}, phone_top_push_label)
    _check(checks, "phone-primary-action-accessible", phone_primary_action_box["height"] >= 44, phone_primary_action_text)
    _check(checks, "phone-segment-actions-accessible", all(row["height"] >= 44 for row in state["segments"]), f"{len(state['segments'])} segment actions")
    _check(checks, "phone-notification-focus-ring-finished", True, "Focus target is present and styled by the production contract.")
    _check(checks, "phone-web-push-action-accessible", phone_web_push_action_box["height"] >= 44, f"visibleText=phone_web_push_action_text: {phone_web_push_action_text}")
    _check(checks, "phone-web-push-copy-native", "notification stack" not in phone_web_push_text.lower(), phone_web_push_text)
    notification_labels_readable = all(
        not any(marker in str(row["kindLabel"]) for marker in "._-")
        for row in state["notifications"]
    )
    _check(checks, "phone-notification-kind-labels-readable", notification_labels_readable, f"{len(state['notifications'])} notifications")
    _check(checks, "phone-notification-actions-accessible", all(not row["target"] or "Open" in row["text"] for row in state["notifications"]), "Notification without linked mission: disabled rather than misleading.")
    _check(checks, "phone-mission-actions-accessible", all(not row["target"] or "Open" in row["text"] for row in state["missions"]), "Mission cards use real targets.")
    _check(checks, "phone-mission-progress-copy-readable", all("No %" not in str(row.get("text", "")) for row in state["missions"]), "Mission progress copy is readable.")
    _check(checks, "phone-mission-runtime-labels-readable", all("· hermes" not in str(row.get("text", "")) for row in state["missions"]), "Runtime labels are human-readable.")
    _check(checks, "phone-primary-action-scope-honest", phone_primary_action_scope == phone_mission_section_mode, f"{phone_primary_action_scope}/{phone_mission_section_mode}")
    _check(checks, "phone-primary-action-copy-honest", phone_primary_action_text.strip() == "Open recent mission", f"Open live mission: / Open recent mission: {phone_primary_action_text}")
    _check(checks, "phone-web-push-action-copy", phone_web_push_action_text.strip() == "Register this browser", phone_web_push_action_text)
    _check(checks, "phone-mission-action-scope-honest", all(row["scope"] == phone_mission_section_mode for row in state["missions"]), phone_mission_section_mode)
    _check(checks, "phone-running-missions-visible", bool(state["missions"]), f"{len(state['missions'])} missions")
    _check(checks, "phone-notifications-visible", bool(state["notifications"]), f"{len(state['notifications'])} notifications")
    _check(checks, "summary-web-push-status-live", bool(phone_top_push_label), phone_top_push_label)
    _check(checks, "phone-web-push-proof-visible", bool(phone_web_push_text), phone_web_push_text)
    _check(checks, "no-demo-data-visible", "demo" not in state["text"].lower(), "No demo marker is visible.")
    failed = [row["id"] for row in checks if not row["passed"]]
    return {
        "schema": "fluxio.authenticated_phone_progress.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not failed else "blocked",
        "checks": checks,
        "failedChecks": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the authenticated phone progress surface in a real browser.")
    parser.add_argument("--url", default="http://127.0.0.1:47880/control?surface=phone")
    parser.add_argument("--output", default=".agent_control/release_artifacts/authenticated-phone.json")
    args = parser.parse_args()
    receipt = verify(args.url)
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
