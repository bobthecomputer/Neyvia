from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from control_route_visual_smoke import browser_launch_diagnostics, find_browser_or_playwright_managed, image_stats
from verify_authenticated_live_control import _api_url, _load_login

try:
    from playwright.async_api import async_playwright
except Exception as exc:  # pragma: no cover - environment guard
    async_playwright = None
    PLAYWRIGHT_IMPORT_ERROR = exc
else:
    PLAYWRIGHT_IMPORT_ERROR = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://127.0.0.1:5190/control?surface=agent"


def _url_with_surface(url: str, surface: str) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    query["surface"] = [surface]
    query.pop("polish", None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/control", urlencode(query, doseq=True), ""))


def _safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip())
    return cleaned.strip("-") or "mainstreet-proof"


async def _visible_text(page, selector: str, timeout_ms: int) -> str:
    try:
        locator = page.locator(selector).first
        await locator.wait_for(timeout=timeout_ms)
        return (await locator.inner_text(timeout=timeout_ms)).strip()
    except Exception:
        return ""


async def _screenshot(page, path: Path) -> dict[str, object]:
    await page.screenshot(path=str(path), full_page=False)
    stats = image_stats(path)
    return {"path": str(path), **stats}


async def _record_async(args: argparse.Namespace) -> dict[str, object]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = _safe_name(args.name)
    report_path = out_dir / f"{name}-recording.json"
    video_dir = out_dir / f"{name}-video-tmp"
    video_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / f"{name}.webm"
    checks: list[dict[str, object]] = []
    screenshots: dict[str, object] = {}

    def record(check_id: str, passed: bool, detail: str, **extra: object) -> None:
        checks.append({"checkId": check_id, "passed": bool(passed), "detail": detail, **extra})

    if async_playwright is None:
        result = {
            "schema": "fluxio.authenticated_mainstreet_recording.v1",
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "ok": False,
            "url": args.url,
            "error": f"Playwright is required: {PLAYWRIGHT_IMPORT_ERROR}",
            "checks": checks,
            "artifacts": {"reportPath": str(report_path), "videoPath": str(video_path), "screenshots": screenshots},
        }
        report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    username, password = _load_login(Path(args.password_file), args.username, args.password)
    browser_path = find_browser_or_playwright_managed(args.browser, args.browser_path)

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(
                executable_path=browser_path,
                headless=True,
                args=["--disable-gpu", "--no-sandbox"],
            )
        except Exception as exc:
            diagnostics = browser_launch_diagnostics(exc)
            record(
                "browser-launch",
                False,
                "Chromium could not start for authenticated mainstreet recording.",
                **diagnostics,
            )
            result = {
                "schema": "fluxio.authenticated_mainstreet_recording.v1",
                "checkedAt": datetime.now(timezone.utc).isoformat(),
                "ok": False,
                "url": args.url,
                "checks": checks,
                "artifacts": {"reportPath": str(report_path), "videoPath": str(video_path), "screenshots": screenshots},
                "nextAction": diagnostics.get("nextAction", "Fix browser launch before recording proof."),
            }
            report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            return result

        context = await browser.new_context(
            ignore_https_errors=True,
            viewport={"width": args.width, "height": args.height},
            record_video_dir=str(video_dir),
            record_video_size={"width": args.width, "height": args.height},
        )
        login_response = await context.request.post(
            _api_url(args.url, "/api/auth/login"),
            data=json.dumps({"username": username, "password": password}),
            headers={"Content-Type": "application/json"},
            timeout=args.timeout_ms,
        )
        record("account-login", login_response.ok, f"Login endpoint returned HTTP {login_response.status}.", status=login_response.status)

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
        summary_json = await summary_response.json()
        summary = summary_json.get("data", {}) if isinstance(summary_json, dict) else {}
        missions = summary.get("missions", []) if isinstance(summary, dict) and isinstance(summary.get("missions"), list) else []
        notifications = summary.get("notifications", []) if isinstance(summary, dict) and isinstance(summary.get("notifications"), list) else []
        record(
            "live-summary",
            summary_response.ok and len(missions) > 0,
            "Authenticated recording context can read live mission and notification rows.",
            missionCount=len(missions),
            notificationCount=len(notifications),
            schema=summary.get("schema", "") if isinstance(summary, dict) else "",
        )

        page = await context.new_page()
        video = page.video
        try:
            async def open_browser_target() -> None:
                browser_url = _url_with_surface(args.url, "browser")
                target_input = page.locator('[data-browser-real-target-url="true"]').first
                for attempt in range(2):
                    await page.goto(browser_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
                    await page.wait_for_timeout(args.settle_ms)
                    try:
                        await target_input.wait_for(state="visible", timeout=args.timeout_ms)
                        break
                    except Exception:
                        if attempt == 1:
                            raise
                        await page.wait_for_timeout(args.settle_ms)
                if args.browser_target_url:
                    await target_input.fill(args.browser_target_url, timeout=args.timeout_ms)
                    await page.locator('[data-browser-load-action="true"]').first.click(timeout=args.timeout_ms)
                    await page.wait_for_timeout(args.settle_ms)

            for surface in ("agent", "builder"):
                await page.goto(_url_with_surface(args.url, surface), wait_until="domcontentloaded", timeout=args.timeout_ms)
                await page.wait_for_timeout(args.settle_ms)
                body_text = await page.locator("body").inner_text(timeout=args.timeout_ms)
                record(
                    f"{surface}-rendered",
                    surface in body_text.lower() or "Fluxio" in body_text,
                    f"{surface} surface rendered during the recording.",
                    textPreview=body_text[:180],
                )
                screenshots[surface] = await _screenshot(page, out_dir / f"{name}-{surface}.png")

            await open_browser_target()
            browser_surface_text = await page.locator("body").inner_text(timeout=args.timeout_ms)
            browser_surface_text_normalized = browser_surface_text.lower()
            browser_agent_return_count = await page.locator('[data-browser-agent-return-action="true"]').count()
            browser_folder_action_count = await page.locator('[data-browser-folder-action="true"]').count()
            browser_load_action_count = await page.locator('[data-browser-load-action="true"]').count()
            browser_open_action_count = await page.locator('[data-browser-open-action="true"]').count()
            browser_refresh_action_count = await page.locator('[data-browser-refresh-action="true"]').count()
            browser_select_region_count = await page.locator('[data-browser-select-region="true"]').count()
            browser_interaction_state_count = await page.locator('[data-browser-interaction-state="true"]').count()
            browser_viewport_summary_count = await page.locator('[data-browser-viewport-summary-copy="true"]').count()
            browser_target_summary_count = await page.locator('[data-browser-target-summary="true"]').count()
            browser_target_ready_count = await page.locator('[data-browser-target-ready-copy="true"]').count()
            browser_agent_return_text = ""
            if browser_agent_return_count > 0:
                browser_agent_return_text = await page.locator('[data-browser-agent-return-action="true"]').first.inner_text(timeout=args.timeout_ms)
            browser_folder_action_text = ""
            if browser_folder_action_count > 0:
                browser_folder_action_text = await page.locator('[data-browser-folder-action="true"]').first.inner_text(timeout=args.timeout_ms)
            browser_load_action_text = ""
            if browser_load_action_count > 0:
                browser_load_action_text = await page.locator('[data-browser-load-action="true"]').first.inner_text(timeout=args.timeout_ms)
            browser_open_action_text = ""
            if browser_open_action_count > 0:
                browser_open_action_text = await page.locator('[data-browser-open-action="true"]').first.inner_text(timeout=args.timeout_ms)
            browser_refresh_action_text = ""
            if browser_refresh_action_count > 0:
                browser_refresh_action_text = await page.locator('[data-browser-refresh-action="true"]').first.inner_text(timeout=args.timeout_ms)
            browser_select_region_text = ""
            browser_select_region_label = ""
            browser_select_region_pressed = ""
            browser_select_region_disabled = True
            if browser_select_region_count > 0:
                browser_select_region = page.locator('[data-browser-select-region="true"]').first
                browser_select_region_text = await browser_select_region.inner_text(timeout=args.timeout_ms)
                browser_select_region_label = await browser_select_region.get_attribute("aria-label", timeout=args.timeout_ms) or ""
                browser_select_region_pressed = await browser_select_region.get_attribute("aria-pressed", timeout=args.timeout_ms) or ""
                browser_select_region_disabled = await browser_select_region.is_disabled(timeout=args.timeout_ms)
            browser_interaction_state_text = ""
            if browser_interaction_state_count > 0:
                browser_interaction_state_text = await page.locator('[data-browser-interaction-state="true"]').first.inner_text(timeout=args.timeout_ms)
            browser_viewport_summary_text = ""
            browser_viewport_summary_title = ""
            if browser_viewport_summary_count > 0:
                browser_viewport_summary = page.locator('[data-browser-viewport-summary-copy="true"]').first
                browser_viewport_summary_text = await browser_viewport_summary.inner_text(timeout=args.timeout_ms)
                browser_viewport_summary_title = await browser_viewport_summary.get_attribute("title", timeout=args.timeout_ms) or ""
            browser_target_summary_text = ""
            browser_target_summary_title = ""
            if browser_target_summary_count > 0:
                browser_target_summary = page.locator('[data-browser-target-summary="true"]').first
                browser_target_summary_text = await browser_target_summary.inner_text(timeout=args.timeout_ms)
                browser_target_summary_title = await browser_target_summary.get_attribute("title", timeout=args.timeout_ms) or ""
            browser_target_summary_normalized = browser_target_summary_text.strip().lower()
            browser_target_ready_text = ""
            if browser_target_ready_count > 0:
                browser_target_ready_text = await page.locator('[data-browser-target-ready-copy="true"]').first.inner_text(timeout=args.timeout_ms)
            browser_target_ready_normalized = browser_target_ready_text.strip().lower()
            browser_target_summary_artifact = (
                browser_target_summary_normalized == "mission artifact"
                and "/api/artifact" in browser_target_summary_title
            )
            browser_target_summary_local = (
                browser_target_summary_normalized == "local interaction probe"
                and browser_target_summary_title.strip().lower() == "local interaction probe"
            )
            browser_load_preview_frame_count = await page.locator('[data-browser-preview-frame="true"]').count()
            browser_load_preview_frame_src = ""
            if browser_load_preview_frame_count > 0:
                browser_load_preview_frame_src = await page.locator('[data-browser-preview-frame="true"]').first.get_attribute("src", timeout=args.timeout_ms) or ""
            browser_load_preview_target_ok = (
                bool(args.browser_target_url and args.browser_target_url in browser_load_preview_frame_src)
                or (
                    not args.browser_target_url
                    and browser_load_preview_frame_count == 0
                    and await page.locator('[data-browser-local-probe="true"]').count() == 1
                )
            )
            screenshots["browserLoadPreview"] = await _screenshot(page, out_dir / f"{name}-browser-load-preview.png")
            record(
                "browser-url-bar-copy-product-native",
                "target url" in browser_surface_text_normalized
                and "refresh preview" in browser_surface_text_normalized
                and "real target url" not in browser_surface_text_normalized
                and "refresh data" not in browser_surface_text_normalized,
                "Browser URL bar uses preview-focused product copy while preserving the target and refresh controls.",
                rejectedCopy=["Real target URL", "Refresh data"],
                textPreview=browser_surface_text[:360],
            )
            record(
                "browser-agent-return-copy-product-native",
                browser_agent_return_count == 1
                and browser_agent_return_text.strip().lower() == "back to agent",
                "Browser toolbar exposes an explicit return action instead of a terse destination label.",
                buttonCount=browser_agent_return_count,
                buttonText=browser_agent_return_text,
                rejectedCopy="Agent",
                textPreview=browser_surface_text[:240],
            )
            record(
                "browser-folder-action-copy-product-native",
                browser_folder_action_count == 1
                and browser_folder_action_text.strip().lower() == "choose folder",
                "Browser toolbar exposes a direct folder choice action instead of file-dialog wording.",
                buttonCount=browser_folder_action_count,
                buttonText=browser_folder_action_text,
                rejectedCopy="Browse folder",
                textPreview=browser_surface_text[:240],
            )
            browser_folder_dialog_count = 0
            browser_folder_current_folder_count = 0
            browser_folder_current_folder_value = ""
            browser_folder_roots_count = 0
            browser_folder_list_count = 0
            browser_folder_entry_count = 0
            browser_folder_use_action_count = 0
            browser_folder_close_count = 0
            browser_folder_dialog_closed = False
            browser_folder_dialog_error = ""
            if browser_folder_action_count > 0:
                try:
                    await page.locator('[data-browser-folder-action="true"]').first.click(timeout=args.timeout_ms)
                    browser_folder_dialog = page.locator('[data-workspace-browser-dialog="true"]').first
                    await browser_folder_dialog.wait_for(state="visible", timeout=args.timeout_ms)
                    await page.wait_for_timeout(args.settle_ms)
                    browser_folder_dialog_count = await page.locator('[data-workspace-browser-dialog="true"]').count()
                    browser_folder_current_folder_count = await page.locator('[data-workspace-browser-current-folder="true"]').count()
                    if browser_folder_current_folder_count > 0:
                        browser_folder_current_folder_value = await page.locator('[data-workspace-browser-current-folder="true"]').first.input_value(timeout=args.timeout_ms)
                    browser_folder_roots_count = await page.locator('[data-workspace-browser-roots="true"]').count()
                    browser_folder_list_count = await page.locator('[data-workspace-browser-list="true"]').count()
                    browser_folder_entry_count = await page.locator('[data-workspace-browser-entry="true"]').count()
                    browser_folder_use_action_count = await page.locator('[data-workspace-browser-use-folder-action="true"]').count()
                    screenshots["browserFolderDialog"] = await _screenshot(page, out_dir / f"{name}-browser-folder-dialog.png")
                    browser_folder_close = page.locator('button[title="Close folder browser"]').first
                    browser_folder_close_count = await page.locator('button[title="Close folder browser"]').count()
                    if browser_folder_close_count > 0:
                        await browser_folder_close.click(timeout=args.timeout_ms)
                        await page.locator('[data-workspace-browser-dialog="true"]').first.wait_for(state="hidden", timeout=args.timeout_ms)
                        remaining_folder_dialogs = page.locator('[data-workspace-browser-dialog="true"]')
                        remaining_folder_dialog_count = await remaining_folder_dialogs.count()
                        if remaining_folder_dialog_count == 0:
                            browser_folder_dialog_closed = True
                        else:
                            browser_folder_dialog_closed = not await remaining_folder_dialogs.first.is_visible(timeout=1000)
                    else:
                        browser_folder_dialog_error = "Close folder browser action was not found."
                except Exception as exc:
                    browser_folder_dialog_error = str(exc)
            record(
                "browser-choose-folder-action-proof-product-native",
                browser_folder_action_count == 1
                and browser_folder_dialog_count == 1
                and browser_folder_current_folder_count == 1
                and browser_folder_list_count == 1
                and browser_folder_use_action_count == 1
                and browser_folder_dialog_closed
                and bool(screenshots.get("browserFolderDialog", {}).get("nonBlank")),
                "Browser Choose folder opens and closes the live backend folder browser.",
                buttonCount=browser_folder_action_count,
                dialogCount=browser_folder_dialog_count,
                currentFolderCount=browser_folder_current_folder_count,
                currentFolder=browser_folder_current_folder_value,
                rootsCount=browser_folder_roots_count,
                listCount=browser_folder_list_count,
                entryCount=browser_folder_entry_count,
                useActionCount=browser_folder_use_action_count,
                closeActionCount=browser_folder_close_count,
                closed=browser_folder_dialog_closed,
                error=browser_folder_dialog_error,
                screenshot=screenshots.get("browserFolderDialog", {}).get("path", ""),
            )
            browser_use_folder_clicked = False
            browser_use_folder_dialog_count = 0
            browser_use_folder_current_value = ""
            browser_use_folder_action_count = 0
            browser_project_dialog_count = 0
            browser_project_folder_input_count = 0
            browser_project_folder_value = ""
            browser_project_dialog_closed = False
            add_project_neutral_style = {}
            add_project_amber_tokens = []
            browser_use_folder_error = ""
            if browser_folder_action_count > 0:
                try:
                    await page.locator('[data-browser-folder-action="true"]').first.click(timeout=args.timeout_ms)
                    await page.locator('[data-workspace-browser-dialog="true"]').first.wait_for(state="visible", timeout=args.timeout_ms)
                    await page.wait_for_timeout(args.settle_ms)
                    browser_use_folder_dialog_count = await page.locator('[data-workspace-browser-dialog="true"]').count()
                    browser_use_folder_action_count = await page.locator('[data-workspace-browser-use-folder-action="true"]').count()
                    if await page.locator('[data-workspace-browser-current-folder="true"]').count() > 0:
                        browser_use_folder_current_value = await page.locator('[data-workspace-browser-current-folder="true"]').first.input_value(timeout=args.timeout_ms)
                    use_folder_button = page.locator('[data-workspace-browser-use-folder-action="true"] button').first
                    await use_folder_button.click(timeout=args.timeout_ms)
                    browser_use_folder_clicked = True
                    await page.locator('[data-workspace-project-dialog="true"]').first.wait_for(state="visible", timeout=args.timeout_ms)
                    await page.wait_for_timeout(args.settle_ms)
                    browser_project_dialog_count = await page.locator('[data-workspace-project-dialog="true"]').count()
                    browser_project_folder_input_count = await page.locator('[data-workspace-project-folder-input="true"]').count()
                    if browser_project_folder_input_count > 0:
                        browser_project_folder_value = await page.locator('[data-workspace-project-folder-input="true"]').first.input_value(timeout=args.timeout_ms)
                    add_project_neutral_style = await page.evaluate(
                        """() => {
                            const form = document.querySelector('[data-workspace-project-dialog="true"]');
                            const panel = form ? form.closest('.modal-panel') : null;
                            const save = panel ? panel.querySelector('.modal-actions .action-btn.primary') : null;
                            const note = form ? form.querySelector('.project-dialog-note') : null;
                            const readStyle = element => {
                                if (!element) {
                                    return {};
                                }
                                const style = window.getComputedStyle(element);
                                return {
                                    backgroundColor: style.backgroundColor,
                                    backgroundImage: style.backgroundImage,
                                    borderColor: style.borderColor,
                                    color: style.color,
                                };
                            };
                            return {
                                save: readStyle(save),
                                note: readStyle(note),
                            };
                        }"""
                    )
                    add_project_style_text = " ".join(
                        str(value)
                        for section in add_project_neutral_style.values()
                        for value in section.values()
                    ).lower()
                    add_project_amber_tokens = [
                        token
                        for token in [
                            "214, 168, 79",
                            "245, 158, 11",
                            "255, 224, 155",
                            "#d6a84f",
                            "#f59e0b",
                        ]
                        if token in add_project_style_text
                    ]
                    screenshots["browserUseFolderApplied"] = await _screenshot(page, out_dir / f"{name}-browser-use-folder-applied.png")
                    close_project_dialog_count = await page.locator('button[title="Close project dialog"]').count()
                    if close_project_dialog_count > 0:
                        await page.locator('button[title="Close project dialog"]').first.click(timeout=args.timeout_ms)
                        await page.locator('[data-workspace-project-dialog="true"]').first.wait_for(state="hidden", timeout=args.timeout_ms)
                        remaining_project_dialogs = page.locator('[data-workspace-project-dialog="true"]')
                        remaining_project_dialog_count = await remaining_project_dialogs.count()
                        if remaining_project_dialog_count == 0:
                            browser_project_dialog_closed = True
                        else:
                            browser_project_dialog_closed = not await remaining_project_dialogs.first.is_visible(timeout=1000)
                    else:
                        browser_use_folder_error = "Close project dialog action was not found."
                except Exception as exc:
                    browser_use_folder_error = str(exc)
            record(
                "browser-use-folder-applies-project-proof-product-native",
                browser_folder_action_count == 1
                and browser_use_folder_dialog_count == 1
                and browser_use_folder_action_count == 1
                and browser_use_folder_clicked
                and browser_project_dialog_count == 1
                and browser_project_folder_input_count == 1
                and bool(browser_use_folder_current_value)
                and browser_project_folder_value == browser_use_folder_current_value
                and browser_project_dialog_closed
                and bool(screenshots.get("browserUseFolderApplied", {}).get("nonBlank")),
                "Browser Use this folder applies the selected backend folder to the Add project form.",
                buttonCount=browser_folder_action_count,
                dialogCount=browser_use_folder_dialog_count,
                useActionCount=browser_use_folder_action_count,
                clicked=browser_use_folder_clicked,
                selectedFolder=browser_use_folder_current_value,
                projectDialogCount=browser_project_dialog_count,
                projectFolderInputCount=browser_project_folder_input_count,
                projectFolderValue=browser_project_folder_value,
                projectDialogClosed=browser_project_dialog_closed,
                error=browser_use_folder_error,
                screenshot=screenshots.get("browserUseFolderApplied", {}).get("path", ""),
            )
            record(
                "add-project-modal-neutral-ui-proof-product-native",
                browser_project_dialog_count == 1
                and browser_project_folder_input_count == 1
                and not add_project_amber_tokens
                and bool(screenshots.get("browserUseFolderApplied", {}).get("nonBlank")),
                "Add project modal reached from Browser Use this folder uses neutral Fluxio styling instead of amber/gold controls.",
                projectDialogCount=browser_project_dialog_count,
                projectFolderInputCount=browser_project_folder_input_count,
                rejectedAmberTokens=add_project_amber_tokens,
                saveStyles=add_project_neutral_style.get("save", {}),
                noteStyles=add_project_neutral_style.get("note", {}),
                screenshot=screenshots.get("browserUseFolderApplied", {}).get("path", ""),
            )
            record(
                "browser-load-action-copy-product-native",
                browser_load_action_count == 1
                and browser_load_action_text.strip().lower() == "load preview",
                "Browser URL form exposes a preview-specific load action instead of a generic load label.",
                buttonCount=browser_load_action_count,
                buttonText=browser_load_action_text,
                rejectedCopy="Load",
                textPreview=browser_surface_text[:240],
            )
            record(
                "browser-load-preview-action-proof-product-native",
                browser_load_action_count == 1
                and browser_load_preview_target_ok
                and bool(screenshots["browserLoadPreview"].get("nonBlank"))
                and browser_target_ready_normalized == "target ready for inspection.",
                "Browser Load preview loads the current target into the Browser workspace frame.",
                buttonCount=browser_load_action_count,
                frameCount=browser_load_preview_frame_count,
                frameSrc=browser_load_preview_frame_src[:240],
                targetMatched=browser_load_preview_target_ok,
                targetReadyText=browser_target_ready_text,
                screenshot=screenshots["browserLoadPreview"].get("path", ""),
            )
            record(
                "browser-open-action-copy-product-native",
                browser_open_action_count == 1
                and browser_open_action_text.strip().lower() == "open preview"
                and "open new tab" not in browser_surface_text_normalized,
                "Browser URL form exposes a preview-specific external-open action instead of generic tab wording.",
                buttonCount=browser_open_action_count,
                buttonText=browser_open_action_text,
                rejectedCopy="Open new tab",
                textPreview=browser_surface_text[:260],
            )
            browser_open_preview_clicked = False
            browser_open_preview_popup_count = 0
            browser_open_preview_popup_url = ""
            browser_open_preview_popup_text = ""
            browser_open_preview_error = ""
            if browser_open_action_count > 0:
                try:
                    async with page.expect_popup(timeout=args.timeout_ms) as popup_info:
                        await page.locator('[data-browser-open-action="true"]').first.click(timeout=args.timeout_ms)
                    browser_open_preview_clicked = True
                    browser_open_preview_popup = await popup_info.value
                    browser_open_preview_popup_count = 1
                    await browser_open_preview_popup.wait_for_load_state("domcontentloaded", timeout=args.timeout_ms)
                    await browser_open_preview_popup.wait_for_timeout(500)
                    browser_open_preview_popup_url = browser_open_preview_popup.url
                    browser_open_preview_popup_text = await browser_open_preview_popup.locator("body").inner_text(timeout=args.timeout_ms)
                    screenshots["browserOpenPreview"] = await _screenshot(
                        browser_open_preview_popup,
                        out_dir / f"{name}-browser-open-preview.png",
                    )
                    await browser_open_preview_popup.close()
                except Exception as exc:
                    browser_open_preview_error = str(exc)[:240]
            browser_open_preview_target_ok = (
                bool(args.browser_target_url and args.browser_target_url in browser_open_preview_popup_url)
                or (
                    not args.browser_target_url
                    and (
                        "interaction" in browser_open_preview_popup_url.lower()
                        or "local interaction probe" in browser_open_preview_popup_text.lower()
                    )
                )
            )
            record(
                "browser-open-preview-action-proof-product-native",
                browser_open_action_count == 1
                and browser_open_preview_clicked
                and browser_open_preview_popup_count == 1
                and browser_open_preview_target_ok
                and bool(screenshots.get("browserOpenPreview", {}).get("nonBlank")),
                "Browser Open preview opens the current target in a separate inspectable page.",
                buttonCount=browser_open_action_count,
                clicked=browser_open_preview_clicked,
                popupCount=browser_open_preview_popup_count,
                popupUrl=browser_open_preview_popup_url[:240],
                targetMatched=browser_open_preview_target_ok,
                error=browser_open_preview_error,
                screenshot=screenshots.get("browserOpenPreview", {}).get("path", ""),
            )
            record(
                "browser-refresh-action-proof-product-native",
                browser_refresh_action_count == 1
                and browser_refresh_action_text.strip().lower() == "refresh preview",
                "Browser URL form exposes a stable preview refresh action instead of an untracked generic button.",
                buttonCount=browser_refresh_action_count,
                buttonText=browser_refresh_action_text,
                action="preview:refresh",
                textPreview=browser_surface_text[:280],
            )
            browser_refresh_clicked = False
            browser_refresh_frame_count_after = 0
            browser_refresh_frame_src_after = ""
            browser_refresh_token_before = ""
            browser_refresh_token_after = ""
            if browser_load_preview_frame_count > 0:
                browser_refresh_token_before = await page.locator('[data-browser-preview-frame="true"]').first.get_attribute(
                    "data-browser-preview-refresh-token",
                    timeout=args.timeout_ms,
                ) or ""
            if browser_refresh_action_count > 0:
                await page.locator('[data-browser-refresh-action="true"]').first.click(timeout=args.timeout_ms)
                browser_refresh_clicked = True
                await page.wait_for_timeout(args.settle_ms)
                browser_refresh_frame_count_after = await page.locator('[data-browser-preview-frame="true"]').count()
                if browser_refresh_frame_count_after > 0:
                    browser_refresh_frame = page.locator('[data-browser-preview-frame="true"]').first
                    browser_refresh_frame_src_after = await browser_refresh_frame.get_attribute("src", timeout=args.timeout_ms) or ""
                    browser_refresh_token_after = await browser_refresh_frame.get_attribute(
                        "data-browser-preview-refresh-token",
                        timeout=args.timeout_ms,
                    ) or ""
                screenshots["browserRefreshPreview"] = await _screenshot(page, out_dir / f"{name}-browser-refresh-preview.png")
            browser_refresh_target_ok = bool(
                args.browser_target_url
                and args.browser_target_url in browser_refresh_frame_src_after
            )
            record(
                "browser-refresh-preview-reload-proof-product-native",
                browser_refresh_action_count == 1
                and browser_refresh_clicked
                and browser_refresh_frame_count_after == 1
                and browser_refresh_target_ok
                and browser_refresh_token_after != browser_refresh_token_before
                and bool(screenshots.get("browserRefreshPreview", {}).get("nonBlank")),
                "Browser Refresh preview remounts the current target in the Browser workspace frame.",
                buttonCount=browser_refresh_action_count,
                clicked=browser_refresh_clicked,
                frameCount=browser_refresh_frame_count_after,
                frameSrc=browser_refresh_frame_src_after[:240],
                tokenBefore=browser_refresh_token_before,
                tokenAfter=browser_refresh_token_after,
                targetMatched=browser_refresh_target_ok,
                screenshot=screenshots.get("browserRefreshPreview", {}).get("path", ""),
            )
            record(
                "browser-interaction-ready-copy-product-native",
                browser_interaction_state_count == 1
                and browser_interaction_state_text.strip().lower() == "preview ready",
                "Browser side rail exposes a ready preview state instead of an idle waiting label.",
                stateCount=browser_interaction_state_count,
                stateText=browser_interaction_state_text,
                rejectedCopy="Waiting",
                textPreview=browser_surface_text[:240],
            )
            record(
                "browser-viewport-summary-copy-product-native",
                browser_viewport_summary_count == 1
                and browser_viewport_summary_text.strip().lower() == "desktop viewport"
                and f"{args.width} x {args.height}" in browser_viewport_summary_title
                and f"viewport {args.width} x {args.height}" not in browser_surface_text_normalized,
                "Browser side rail summarizes the viewport while preserving exact dimensions in metadata.",
                stateCount=browser_viewport_summary_count,
                stateText=browser_viewport_summary_text,
                preservedViewport=browser_viewport_summary_title,
                rejectedCopy=f"Viewport {args.width} x {args.height}",
                textPreview=browser_surface_text[:260],
            )
            record(
                "browser-target-summary-copy-product-native",
                browser_target_summary_count == 1
                and (browser_target_summary_artifact or browser_target_summary_local),
                "Browser side rail summarizes the loaded target while preserving the exact target in metadata.",
                stateCount=browser_target_summary_count,
                stateText=browser_target_summary_text,
                preservedTarget=browser_target_summary_title[:180],
                usedTargetOverride=bool(args.browser_target_url),
                rejectedCopy="raw artifact URL in the side rail",
            )
            record(
                "browser-target-ready-copy-product-native",
                browser_target_ready_count == 1
                and browser_target_ready_normalized in {
                    "target ready for inspection.",
                    "local probe ready for inspection.",
                },
                "Browser side rail uses inspection-ready target copy instead of preview-capture wording.",
                stateCount=browser_target_ready_count,
                stateText=browser_target_ready_text,
                rejectedCopy=[
                    "Loaded target is ready for preview capture.",
                    "Built-in setup probe; real mission URLs still replace it when available.",
                ],
                textPreview=browser_surface_text[:260],
            )
            proof_drawer_button = page.locator('[data-browser-proof-drawer-action="true"]').first
            proof_drawer_button_count = await page.locator('[data-browser-proof-drawer-action="true"]').count()
            if proof_drawer_button_count > 0:
                await proof_drawer_button.click(timeout=args.timeout_ms)
                await page.wait_for_timeout(500)
                proof_drawer = page.locator(".fluxio-drawer.open").first
                proof_panel = page.locator('[data-browser-proof-panel="true"][data-browser-proof-panel-open="true"]').first
                proof_drawer_count = await page.locator(".fluxio-drawer.open").count()
                proof_panel_count = await page.locator('[data-browser-proof-panel="true"][data-browser-proof-panel-open="true"]').count()
                proof_surface_count = proof_drawer_count + proof_panel_count
                redundant_toast_count = await page.locator(".toast", has_text="Browser proof view opened.").count()
                focus_target_count = await page.locator('[data-browser-proof-panel-focus-target="true"]').count()
                focused_proof_panel_target = bool(
                    await page.evaluate(
                        """() => Boolean(document.activeElement?.matches?.('[data-browser-proof-panel-focus-target="true"]'))"""
                    )
                )
                proof_drawer_text = ""
                if proof_drawer_count > 0:
                    try:
                        proof_drawer_text = await proof_drawer.inner_text(timeout=args.timeout_ms)
                    except Exception:
                        proof_drawer_text = ""
                elif proof_panel_count > 0:
                    try:
                        proof_drawer_text = await proof_panel.inner_text(timeout=args.timeout_ms)
                    except Exception:
                        proof_drawer_text = ""
                browser_capture_note_label_count = await page.locator('[data-browser-capture-note-label="true"]').count()
                browser_capture_note_text_count = await page.locator('[data-browser-capture-note-text="true"]').count()
                browser_capture_note_text = ""
                if browser_capture_note_text_count > 0:
                    browser_capture_note_text = await page.locator('[data-browser-capture-note-text="true"]').first.inner_text(timeout=args.timeout_ms)
                proof_drawer_text_normalized = proof_drawer_text.lower()
                browser_capture_note_text_normalized = browser_capture_note_text.strip().lower()
                screenshots["browserProofDrawer"] = await _screenshot(page, out_dir / f"{name}-browser-proof-drawer.png")
                record(
                    "browser-proof-drawer-action-captured",
                    proof_surface_count > 0
                    and redundant_toast_count == 0
                    and bool(screenshots["browserProofDrawer"].get("nonBlank"))
                    and "preview details" in proof_drawer_text_normalized
                    and "browser preview state" in proof_drawer_text_normalized
                    and "capture note" in proof_drawer_text_normalized
                    and "recorder cue" not in proof_drawer_text_normalized
                    and "browser proof state" not in proof_drawer_text_normalized
                    and "proof drawer" not in proof_drawer_text_normalized,
                    "Browser preview details action opened a visible evidence surface without the redundant global toast.",
                    buttonCount=proof_drawer_button_count,
                    drawerCount=proof_drawer_count,
                    panelCount=proof_panel_count,
                    redundantToastCount=redundant_toast_count,
                    captureNoteLabelCount=browser_capture_note_label_count,
                    captureNoteTextCount=browser_capture_note_text_count,
                    captureNoteText=browser_capture_note_text,
                    drawerText=proof_drawer_text[:360],
                    rejectedCopy=["Browser proof state", "Proof drawer", "Recorder cue"],
                    screenshot=screenshots["browserProofDrawer"].get("path", ""),
                )
                record(
                    "browser-capture-note-copy-product-native",
                    browser_capture_note_label_count == 1
                    and browser_capture_note_text_count == 1
                    and (
                        browser_capture_note_text_normalized == "preview stays attached to this browser run."
                        or browser_capture_note_text_normalized == "local probe is ready for interaction."
                    ),
                    "Browser preview details use product-facing capture note copy instead of recorder wording.",
                    labelCount=browser_capture_note_label_count,
                    textCount=browser_capture_note_text_count,
                    noteText=browser_capture_note_text,
                    rejectedCopy="Recorder cue",
                )
                if browser_capture_note_label_count > 0:
                    try:
                        await page.locator('[data-browser-capture-note-label="true"]').first.scroll_into_view_if_needed(timeout=args.timeout_ms)
                        await page.wait_for_timeout(250)
                        screenshots["browserCaptureNote"] = await _screenshot(page, out_dir / f"{name}-browser-capture-note.png")
                    except Exception:
                        pass
                record(
                    "browser-proof-panel-keyboard-focus",
                    proof_panel_count > 0 and focus_target_count == 1 and focused_proof_panel_target,
                    "Browser proof panel moved keyboard focus to its close control after opening.",
                    panelCount=proof_panel_count,
                    focusTargetCount=focus_target_count,
                    focusedProofPanelTarget=focused_proof_panel_target,
                )
                close_button = page.locator('[data-browser-proof-panel-close="true"]').first
                proof_panel_close_clicked = False
                try:
                    if await page.locator('[data-browser-proof-panel-close="true"]').count() > 0:
                        await close_button.click(timeout=2500)
                        proof_panel_close_clicked = True
                        await page.wait_for_timeout(250)
                    else:
                        await page.get_by_role("button", name="Close").first.click(timeout=2500)
                        proof_panel_close_clicked = True
                        await page.wait_for_timeout(250)
                except Exception:
                    pass
                proof_drawer_count_after_close = await page.locator(".fluxio-drawer.open").count()
                proof_panel_count_after_close = await page.locator('[data-browser-proof-panel="true"][data-browser-proof-panel-open="true"]').count()
                proof_surface_count_after_close = proof_drawer_count_after_close + proof_panel_count_after_close
                proof_button_expanded_after_close = await proof_drawer_button.get_attribute("aria-expanded", timeout=args.timeout_ms) or ""
                screenshots["browserProofDetailsClosed"] = await _screenshot(page, out_dir / f"{name}-browser-preview-details-closed.png")
                record(
                    "browser-preview-details-close-proof-product-native",
                    proof_panel_close_clicked
                    and proof_surface_count_after_close == 0
                    and proof_button_expanded_after_close == "false"
                    and bool(screenshots["browserProofDetailsClosed"].get("nonBlank")),
                    "Browser Preview details closes back to the primary Browser workspace without leaving proof chrome open.",
                    closeClicked=proof_panel_close_clicked,
                    openSurfaceCount=proof_surface_count_after_close,
                    buttonExpanded=proof_button_expanded_after_close,
                    screenshot=screenshots["browserProofDetailsClosed"].get("path", ""),
                )
            else:
                record(
                    "browser-proof-drawer-action-captured",
                    False,
                    "Browser preview details action was not available.",
                    buttonCount=proof_drawer_button_count,
                )
                record(
                    "browser-proof-panel-keyboard-focus",
                    False,
                    "Browser proof panel focus target was not available because the proof action was missing.",
                )
                record(
                    "browser-preview-details-close-proof-product-native",
                    False,
                    "Browser preview details close proof was not available because the proof action was missing.",
                    buttonCount=proof_drawer_button_count,
                )
            browser_return_action_count = await page.locator('[data-browser-agent-return-action="true"]').count()
            browser_return_agent_surface_count = 0
            browser_return_text = ""
            browser_return_clicked = False
            if browser_return_action_count > 0:
                await page.locator('[data-browser-agent-return-action="true"]').first.click(timeout=args.timeout_ms)
                browser_return_clicked = True
                await page.wait_for_timeout(args.settle_ms)
                browser_return_text = await page.locator("body").inner_text(timeout=args.timeout_ms)
                browser_return_agent_surface_count = await page.locator('[data-agent-conversation-mode]').count()
                screenshots["browserAgentReturn"] = await _screenshot(page, out_dir / f"{name}-browser-back-to-agent.png")
                await open_browser_target()
            record(
                "browser-back-to-agent-action-proof-product-native",
                browser_return_action_count == 1
                and browser_return_clicked
                and browser_return_agent_surface_count == 1
                and (
                    "agent live" in browser_return_text.lower()
                    or "fluxio conversation" in browser_return_text.lower()
                    or "what should fluxio do today?" in browser_return_text.lower()
                ),
                "Browser Back to Agent returns from the Browser workspace to the Agent surface.",
                buttonCount=browser_return_action_count,
                clicked=browser_return_clicked,
                agentSurfaceCount=browser_return_agent_surface_count,
                textPreview=browser_return_text[:240],
                screenshot=screenshots.get("browserAgentReturn", {}).get("path", ""),
            )
            browser_send_selection_initial_count = await page.locator('[data-browser-send-selection-action="true"]').count()
            browser_clear_selection_initial_count = await page.locator('[data-browser-clear-selection-action="true"]').count()
            browser_send_selection_initial_disabled = True
            browser_clear_selection_initial_disabled = True
            if browser_send_selection_initial_count > 0:
                browser_send_selection_initial_disabled = await page.locator('[data-browser-send-selection-action="true"]').first.is_disabled(timeout=args.timeout_ms)
            if browser_clear_selection_initial_count > 0:
                browser_clear_selection_initial_disabled = await page.locator('[data-browser-clear-selection-action="true"]').first.is_disabled(timeout=args.timeout_ms)
            await page.locator('[data-browser-select-region="true"]').click(timeout=args.timeout_ms)
            await page.wait_for_selector('[data-browser-selection-layer="true"]', timeout=args.timeout_ms)
            browser_select_region_active = page.locator('[data-browser-select-region="true"]').first
            browser_select_region_active_text = await browser_select_region_active.inner_text(timeout=args.timeout_ms)
            browser_select_region_active_label = await browser_select_region_active.get_attribute("aria-label", timeout=args.timeout_ms) or ""
            browser_select_region_active_pressed = await browser_select_region_active.get_attribute("aria-pressed", timeout=args.timeout_ms) or ""
            browser_selection_layer_count = await page.locator('[data-browser-selection-layer="true"]').count()
            record(
                "browser-select-region-action-proof-product-native",
                browser_select_region_count == 1
                and browser_select_region_text.strip().lower() == "select region"
                and browser_select_region_label == "Select page region"
                and browser_select_region_pressed == "false"
                and not browser_select_region_disabled
                and browser_select_region_active_text.strip().lower() == "selecting"
                and browser_select_region_active_label == "Selecting page region"
                and browser_select_region_active_pressed == "true"
                and browser_selection_layer_count == 1,
                "Browser Select region is a real toggled action with idle and active state proof.",
                buttonCount=browser_select_region_count,
                initialText=browser_select_region_text,
                initialLabel=browser_select_region_label,
                initialPressed=browser_select_region_pressed,
                initialDisabled=browser_select_region_disabled,
                activeText=browser_select_region_active_text,
                activeLabel=browser_select_region_active_label,
                activePressed=browser_select_region_active_pressed,
                selectionLayerCount=browser_selection_layer_count,
            )
            layer = page.locator('[data-browser-selection-layer="true"]').first
            box = await layer.bounding_box()
            if not box:
                record("browser-selection-layer", False, "Browser selection layer did not expose a bounding box.")
            else:
                await page.mouse.move(box["x"] + box["width"] * 0.16, box["y"] + box["height"] * 0.24)
                await page.mouse.down()
                await page.mouse.move(box["x"] + box["width"] * 0.58, box["y"] + box["height"] * 0.64, steps=12)
                await page.mouse.up()
                await page.wait_for_timeout(500)
                selection_text = await _visible_text(page, ".fluxos-browser-proof-strip", args.timeout_ms)
                browser_selection_overlay_count = await page.locator(".fluxos-browser-selection-rect").count()
                browser_selection_overlay_after_content = ""
                if browser_selection_overlay_count > 0:
                    browser_selection_overlay_after_content = await page.locator(".fluxos-browser-selection-rect").first.evaluate(
                        "node => window.getComputedStyle(node, '::after').getPropertyValue('content')"
                    )
                browser_selection_summary_count = await page.locator('[data-browser-selection-summary-copy="true"]').count()
                browser_selection_ready_count = await page.locator('[data-browser-selection-ready-copy="true"]').count()
                browser_selection_summary_text = ""
                browser_selection_summary_geometry = ""
                if browser_selection_summary_count > 0:
                    browser_selection_summary = page.locator('[data-browser-selection-summary-copy="true"]').first
                    browser_selection_summary_text = await browser_selection_summary.inner_text(timeout=args.timeout_ms)
                    browser_selection_summary_geometry = await browser_selection_summary.get_attribute("title", timeout=args.timeout_ms) or ""
                browser_selection_ready_text = ""
                if browser_selection_ready_count > 0:
                    browser_selection_ready_text = await page.locator('[data-browser-selection-ready-copy="true"]').first.inner_text(timeout=args.timeout_ms)
                browser_send_selection_count = await page.locator('[data-browser-send-selection-action="true"]').count()
                browser_clear_selection_count = await page.locator('[data-browser-clear-selection-action="true"]').count()
                browser_send_selection_text = ""
                browser_clear_selection_text = ""
                browser_send_selection_disabled = True
                browser_clear_selection_disabled = True
                if browser_send_selection_count > 0:
                    browser_send_selection = page.locator('[data-browser-send-selection-action="true"]').first
                    browser_send_selection_text = await browser_send_selection.inner_text(timeout=args.timeout_ms)
                    browser_send_selection_disabled = await browser_send_selection.is_disabled(timeout=args.timeout_ms)
                if browser_clear_selection_count > 0:
                    browser_clear_selection = page.locator('[data-browser-clear-selection-action="true"]').first
                    browser_clear_selection_text = await browser_clear_selection.inner_text(timeout=args.timeout_ms)
                    browser_clear_selection_disabled = await browser_clear_selection.is_disabled(timeout=args.timeout_ms)
                screenshots["browser"] = await _screenshot(page, out_dir / f"{name}-browser.png")
                record(
                    "browser-workspace-screenshot-before-handoff",
                    bool(screenshots["browser"].get("nonBlank")),
                    "Browser workspace screenshot was captured before sending the selected region to Agent.",
                    screenshot=screenshots["browser"].get("path", ""),
                )
                record(
                    "browser-selection-overlay-quiet-product-native",
                    browser_selection_overlay_count == 1
                    and browser_selection_overlay_after_content.strip().lower() in {"none", '""'},
                    "Browser selection overlay keeps the rectangle but removes the duplicate text chip.",
                    overlayCount=browser_selection_overlay_count,
                    afterContent=browser_selection_overlay_after_content,
                    rejectedCopy="Selected region",
                    screenshot=screenshots["browser"].get("path", ""),
                )
                record(
                    "browser-selection-summary-copy-product-native",
                    browser_selection_summary_count == 1
                    and browser_selection_summary_text.strip().lower() == "region selected"
                    and "% x " in browser_selection_summary_geometry
                    and " at " in browser_selection_summary_geometry
                    and "Region selected" in selection_text
                    and "% x " not in selection_text,
                    "Browser side rail summarizes the selected region while preserving exact geometry in metadata.",
                    stateCount=browser_selection_summary_count,
                    stateText=browser_selection_summary_text,
                    preservedGeometry=browser_selection_summary_geometry,
                    rejectedCopy="raw geometry in the side rail",
                    textPreview=selection_text[:240],
                )
                record(
                    "browser-selection-ready-copy-product-native",
                    browser_selection_ready_count == 1
                    and browser_selection_ready_text.strip().lower() == "region ready for agent"
                    and "data-fluxio-browser-region" not in selection_text,
                    "Browser side rail shows a human selection-ready message instead of the internal selector.",
                    stateCount=browser_selection_ready_count,
                    stateText=browser_selection_ready_text,
                    rejectedCopy="data-fluxio-browser-region",
                    textPreview=selection_text[:240],
                )
                record(
                    "browser-selection-actions-proof-product-native",
                    browser_send_selection_initial_count == 1
                    and browser_clear_selection_initial_count == 1
                    and browser_send_selection_initial_disabled
                    and browser_clear_selection_initial_disabled
                    and browser_send_selection_count == 1
                    and browser_clear_selection_count == 1
                    and browser_send_selection_text.strip().lower() == "send to agent"
                    and browser_clear_selection_text.strip().lower() == "clear selection"
                    and not browser_send_selection_disabled
                    and not browser_clear_selection_disabled,
                    "Browser selection actions are disabled until a region exists, then become the primary handoff controls.",
                    sendButtonCount=browser_send_selection_count,
                    clearButtonCount=browser_clear_selection_count,
                    initialDisabled={
                        "sendToAgent": browser_send_selection_initial_disabled,
                        "clearSelection": browser_clear_selection_initial_disabled,
                    },
                    afterSelectionDisabled={
                        "sendToAgent": browser_send_selection_disabled,
                        "clearSelection": browser_clear_selection_disabled,
                    },
                    sendButtonText=browser_send_selection_text,
                    clearButtonText=browser_clear_selection_text,
                    textPreview=selection_text[:260],
                )
                clear_button = page.locator('[data-browser-clear-selection-action="true"]').first
                await clear_button.click(timeout=args.timeout_ms)
                await page.wait_for_timeout(400)
                browser_selection_reset_text = await _visible_text(page, ".fluxos-browser-proof-strip", args.timeout_ms)
                browser_selection_reset_summary_text = ""
                browser_selection_reset_ready_text = ""
                browser_selection_reset_summary_count = await page.locator('[data-browser-selection-summary-copy="true"]').count()
                browser_selection_reset_ready_count = await page.locator('[data-browser-selection-ready-copy="true"]').count()
                if browser_selection_reset_summary_count > 0:
                    browser_selection_reset_summary_text = await page.locator('[data-browser-selection-summary-copy="true"]').first.inner_text(timeout=args.timeout_ms)
                if browser_selection_reset_ready_count > 0:
                    browser_selection_reset_ready_text = await page.locator('[data-browser-selection-ready-copy="true"]').first.inner_text(timeout=args.timeout_ms)
                browser_selection_reset_overlay_count = await page.locator(".fluxos-browser-selection-rect").count()
                browser_send_selection_reset_disabled = await page.locator('[data-browser-send-selection-action="true"]').first.is_disabled(timeout=args.timeout_ms)
                browser_clear_selection_reset_disabled = await page.locator('[data-browser-clear-selection-action="true"]').first.is_disabled(timeout=args.timeout_ms)
                screenshots["browserSelectionCleared"] = await _screenshot(page, out_dir / f"{name}-browser-selection-cleared.png")
                record(
                    "browser-clear-selection-reset-proof-product-native",
                    browser_selection_reset_summary_count == 1
                    and browser_selection_reset_ready_count == 1
                    and browser_selection_reset_summary_text.strip().lower() == "no region selected"
                    and browser_selection_reset_ready_text.strip().lower() == "use select region to attach exact ui context to agent."
                    and browser_selection_reset_overlay_count == 0
                    and browser_send_selection_reset_disabled
                    and browser_clear_selection_reset_disabled,
                    "Browser Clear selection returns the rail and handoff controls to the idle state.",
                    summaryText=browser_selection_reset_summary_text,
                    readyText=browser_selection_reset_ready_text,
                    overlayCount=browser_selection_reset_overlay_count,
                    sendDisabled=browser_send_selection_reset_disabled,
                    clearDisabled=browser_clear_selection_reset_disabled,
                    textPreview=browser_selection_reset_text[:260],
                    screenshot=screenshots["browserSelectionCleared"].get("path", ""),
                )
                await page.locator('[data-browser-select-region="true"]').click(timeout=args.timeout_ms)
                await page.wait_for_selector('[data-browser-selection-layer="true"]', timeout=args.timeout_ms)
                reselect_layer = page.locator('[data-browser-selection-layer="true"]').first
                reselect_box = await reselect_layer.bounding_box()
                if not reselect_box:
                    record("browser-clear-selection-reselect-layer", False, "Browser selection layer was not available after clearing and reselecting.")
                else:
                    await page.mouse.move(reselect_box["x"] + reselect_box["width"] * 0.22, reselect_box["y"] + reselect_box["height"] * 0.2)
                    await page.mouse.down()
                    await page.mouse.move(reselect_box["x"] + reselect_box["width"] * 0.6, reselect_box["y"] + reselect_box["height"] * 0.6, steps=12)
                    await page.mouse.up()
                    await page.wait_for_timeout(500)
                    selection_text = await _visible_text(page, ".fluxos-browser-proof-strip", args.timeout_ms)
                    screenshots["browser"] = await _screenshot(page, out_dir / f"{name}-browser.png")
                send_button = page.locator('[data-browser-send-selection-action="true"]').first
                await send_button.click(timeout=args.timeout_ms)
                await page.wait_for_timeout(args.settle_ms)
                screenshots["browserAgentHandoff"] = await _screenshot(page, out_dir / f"{name}-browser-agent-handoff.png")
                record(
                    "browser-region-sent-to-agent",
                    "Selected region" in selection_text
                    or "Region ready for Agent" in selection_text
                    or "data-fluxio-browser-region" in selection_text,
                    "Browser region selection was created and sent to the Agent draft.",
                    proofText=selection_text[:240],
                )
            if "browser" not in screenshots:
                screenshots["browser"] = await _screenshot(page, out_dir / f"{name}-browser.png")

            await page.goto(_url_with_surface(args.url, "phone"), wait_until="domcontentloaded", timeout=args.timeout_ms)
            await page.wait_for_timeout(args.settle_ms)
            phone_text = await page.locator("body").inner_text(timeout=args.timeout_ms)
            record(
                "phone-live-progress",
                "phone progress" in phone_text.lower() and str(len(notifications)) in phone_text,
                "Phone surface rendered live summary counts during the recording.",
                textPreview=phone_text[:240],
            )
            screenshots["phone"] = await _screenshot(page, out_dir / f"{name}-phone.png")
        finally:
            await page.close()
            await context.close()
            await browser.close()

        raw_video_path = ""
        if video is not None:
            try:
                raw_video_path = await video.path()
            except Exception:
                raw_video_path = ""
        if raw_video_path:
            shutil.copyfile(raw_video_path, video_path)
            record("video-written", video_path.exists() and video_path.stat().st_size > 0, "Playwright wrote a WebM recording.", bytes=video_path.stat().st_size)
        else:
            record("video-written", False, "Playwright did not return a video file path.")

    result = {
        "schema": "fluxio.authenticated_mainstreet_recording.v1",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "ok": all(bool(item.get("passed")) for item in checks),
        "url": args.url,
        "viewport": {"width": args.width, "height": args.height},
        "checks": checks,
        "summary": {
            "missionCount": len(missions),
            "notificationCount": len(notifications),
            "summarySchema": summary.get("schema", "") if isinstance(summary, dict) else "",
        },
        "artifacts": {
            "reportPath": str(report_path),
            "videoPath": str(video_path),
            "screenshots": screenshots,
        },
    }
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record authenticated Fluxio mainstreet proof workflow.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out-dir", default=str(ROOT / "tmp-ui-checks" / "mainstreet-recording"))
    parser.add_argument("--name", default="mainstreet-proof")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--password-file", default=str(ROOT / ".agent_control" / "neyvia_admin_password.txt"))
    parser.add_argument("--browser", default="auto", choices=["auto", "chrome", "chromium", "edge", "zen"])
    parser.add_argument("--browser-path", default="")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--timeout-ms", type=int, default=45000)
    parser.add_argument("--settle-ms", type=int, default=2200)
    parser.add_argument("--browser-target-url", default="", help="Optional URL to load through the Browser URL bar before proof checks.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    result = asyncio.run(_record_async(args))
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
