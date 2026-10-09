from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


def _clipped(value: object, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    base_url = str(args.base_url).rstrip("/")
    screenshot_path = Path(args.screenshot).resolve()
    receipt_path = Path(args.receipt).resolve()
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    deadline = time.monotonic() + max(10, int(args.timeout_seconds))
    diagnostics: dict[str, list[Any]] = {
        "consoleErrors": [],
        "pageErrors": [],
        "failedRequests": [],
    }

    def remaining_ms() -> int:
        remaining = int((deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            raise TimeoutError("detached conversation clickthrough exceeded its hard deadline")
        return max(1_000, remaining)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-default-apps",
                    "--disable-gpu",
                    "--no-first-run",
                ],
            )
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000},
                    service_workers="block",
                )
                try:
                    page = context.new_page()
                    page.set_default_timeout(min(15_000, remaining_ms()))
                    page.set_default_navigation_timeout(min(20_000, remaining_ms()))
                    page.on(
                        "console",
                        lambda message: diagnostics["consoleErrors"].append(_clipped(message.text))
                        if message.type == "error"
                        else None,
                    )
                    page.on("pageerror", lambda error: diagnostics["pageErrors"].append(_clipped(error, 2_000)))
                    page.on(
                        "requestfailed",
                        lambda request: diagnostics["failedRequests"].append(
                            {
                                "method": request.method,
                                "url": request.url,
                                "error": _clipped(request.failure),
                            }
                        ),
                    )

                    page.goto(f"{base_url}/control", wait_until="domcontentloaded", timeout=remaining_ms())
                    local_session_status = page.evaluate(
                        """
                        async () => {
                          const response = await fetch('/api/auth/local-session', { method: 'POST' });
                          return response.status;
                        }
                        """
                    )
                    if local_session_status != 200:
                        raise RuntimeError(f"local session failed: {local_session_status}")
                    page.goto(
                        f"{base_url}/control?surface=agent&mode=agent",
                        wait_until="domcontentloaded",
                        timeout=remaining_ms(),
                    )
                    page.locator(".fluxos-shell").wait_for(state="visible", timeout=remaining_ms())
                    sidebar = page.locator(
                        '.neyvia-conversation-sidebar[data-conversation-state="ready"]'
                    )
                    sidebar.wait_for(state="visible", timeout=remaining_ms())

                    chat_rows = sidebar.locator('[data-conversation-kind="chat"]')
                    row_count = chat_rows.count()
                    if not row_count:
                        raise RuntimeError("no durable chat conversation is available for the clickthrough")

                    selected_id = ""
                    selected_title = ""
                    stored_message_count = 0
                    for index in range(min(row_count, 30)):
                        remaining_ms()
                        row = chat_rows.nth(index)
                        conversation_id = row.get_attribute("data-conversation-id") or ""
                        row.click(timeout=min(10_000, remaining_ms()))
                        banner = page.locator(
                            f'[data-selected-neyvia-conversation="{conversation_id}"]'
                        )
                        banner.wait_for(state="visible", timeout=min(10_000, remaining_ms()))
                        message_summary = _clipped(
                            page.locator(".fluxos-thread-head strong").first.text_content()
                        )
                        count_text = message_summary.split(" ", 1)[0]
                        if count_text.isdigit() and int(count_text) > 0 and "stored message" in message_summary:
                            selected_id = conversation_id
                            selected_title = _clipped(banner.locator("strong").text_content())
                            stored_message_count = int(count_text)
                            break
                    if not selected_id:
                        raise RuntimeError(
                            "durable chat rows exist, but none contains a stored transcript"
                        )

                    selected_row = sidebar.locator(
                        f'[data-conversation-id="{selected_id}"]'
                    )
                    if selected_row.get_attribute("aria-current") != "true":
                        raise RuntimeError("the selected durable conversation row is not marked current")
                    if page.locator('[data-agent-composer-draft="true"]').count():
                        raise RuntimeError(
                            "the live composer remained available while browsing durable history"
                        )
                    visible_turn_count = page.locator('[data-message-zone="thread"]').count()
                    if not visible_turn_count:
                        raise RuntimeError(
                            "the selected durable transcript rendered no visible turns"
                        )

                    page.locator(
                        f'[data-selected-neyvia-conversation="{selected_id}"]:visible button',
                        has_text="Return to current work",
                    ).first.click(
                        timeout=min(10_000, remaining_ms())
                    )
                    page.locator("[data-selected-neyvia-conversation]").wait_for(
                        state="detached",
                        timeout=min(10_000, remaining_ms()),
                    )
                    page.locator('[data-agent-composer-draft="true"]').wait_for(
                        state="visible",
                        timeout=min(10_000, remaining_ms()),
                    )

                    harness_button = page.locator(
                        'nav[aria-label="Fluxio surfaces"] button',
                        has_text="Harnesses",
                    ).first
                    harness_button.wait_for(
                        state="visible",
                        timeout=min(10_000, remaining_ms()),
                    )
                    harness_button.click(timeout=min(10_000, remaining_ms()))
                    harness_surface = page.locator(
                        'section[data-harnesses-surface="true"]'
                    )
                    harness_surface.wait_for(
                        state="visible",
                        timeout=min(10_000, remaining_ms()),
                    )
                    harness_receipt = harness_surface.locator(
                        '[data-harness-receipt="true"]'
                    )
                    harness_receipt.wait_for(
                        state="visible",
                        timeout=min(10_000, remaining_ms()),
                    )
                    harness_chooser = harness_surface.locator(
                        'select[aria-label="Execution environment"]'
                    )
                    harness_chooser.wait_for(
                        state="visible",
                        timeout=min(10_000, remaining_ms()),
                    )
                    real_harness_option = harness_chooser.locator('option:not([value=""])')
                    real_harness_option.first.wait_for(
                        state="attached",
                        timeout=min(10_000, remaining_ms()),
                    )
                    harness_count = real_harness_option.count()
                    if not harness_count:
                        raise RuntimeError(
                            "the reconciled Harness surface rendered no real runtime choices"
                        )
                    page.screenshot(path=str(screenshot_path), full_page=True)
                finally:
                    context.close()
            finally:
                browser.close()

        if diagnostics["pageErrors"] or diagnostics["consoleErrors"]:
            raise RuntimeError(f"page diagnostics failed: {json.dumps(diagnostics)}")
        receipt = {
            "schema": "neyvia.conversation-fabric-headless-proof.v1",
            "status": "passed",
            "startedAt": started_at,
            "completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "baseUrl": base_url,
            "isolation": {
                "browser": "detached-playwright-chromium",
                "headless": True,
                "gpuDisabled": True,
                "codexEmbeddedBrowserUsed": False,
                "serviceWorkersBlocked": True,
            },
            "selectedConversation": {
                "conversationId": selected_id,
                "title": selected_title,
                "storedMessageCount": stored_message_count,
                "visibleTurnCount": visible_turn_count,
            },
            "assertions": {
                "exactRowMarkedCurrent": True,
                "durableTranscriptRendered": True,
                "historicalComposerHidden": True,
                "returnRestoredComposer": True,
                "harnessNavigationLoaded": True,
                "harnessReceiptVisible": True,
                "harnessRuntimeChoiceCount": harness_count,
            },
            "diagnostics": diagnostics,
            "screenshotPath": str(screenshot_path),
        }
        _write_receipt(receipt_path, receipt)
        return {"ok": True, "receiptPath": str(receipt_path), "screenshotPath": str(screenshot_path)}
    except Exception as exc:
        receipt = {
            "schema": "neyvia.conversation-fabric-headless-proof.v1",
            "status": "failed",
            "startedAt": started_at,
            "completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "baseUrl": base_url,
            "error": _clipped(exc, 2_000),
            "diagnostics": diagnostics,
        }
        _write_receipt(receipt_path, receipt)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the Neyvia durable conversation clickthrough in a detached headless browser."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:47880")
    parser.add_argument(
        "--screenshot",
        default=".agent_control/runtime_proof/neyvia-conversation-fabric-headless.png",
    )
    parser.add_argument(
        "--receipt",
        default=".agent_control/runtime_proof/neyvia-conversation-fabric-headless.json",
    )
    parser.add_argument("--timeout-seconds", type=int, default=45)
    args = parser.parse_args()
    try:
        result = run(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": _clipped(exc, 2_000)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
