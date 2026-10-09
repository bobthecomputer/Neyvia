"""G2 UI correction browser proof: modal contrast/scroll/CTA + mobile conversation picker."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROOF_DIR = ROOT / ".agent_control" / "capability_os" / "qa"
PASSWORD_FILE = ROOT / ".agent_control" / "grand_agent_admin_password.txt"
BASE_UI = "http://127.0.0.1:1420"
STAMP = time.strftime("%Y%m%d")


def load_login() -> tuple[str, str]:
    text = PASSWORD_FILE.read_text(encoding="utf-8")
    username = ""
    password = ""
    for line in text.splitlines():
        if not username:
            match = re.match(r"\s*Username:\s*(.+?)\s*$", line, flags=re.IGNORECASE)
            if match:
                username = match.group(1).strip()
        if not password:
            match = re.match(r"\s*Password:\s*(.+?)\s*$", line, flags=re.IGNORECASE)
            if match:
                password = match.group(1).strip()
    if not username:
        account = json.loads(
            (ROOT / ".agent_control" / "grand_agent_web_admin.json").read_text(encoding="utf-8")
        )
        username = str(account.get("username") or "admin")
    if not username or not password:
        raise RuntimeError("Missing local Neyvia login credentials")
    return username, password


def _luminance(rgb: tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        value = value / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _parse_rgb(value: str) -> tuple[float, float, float] | None:
    text = (value or "").strip()
    if not text.startswith("rgb"):
        return None
    inner = text[text.find("(") + 1 : text.rfind(")")]
    parts = [part.strip() for part in inner.split(",")]
    if len(parts) < 3:
        return None
    return float(parts[0]), float(parts[1]), float(parts[2])


def _contrast_ratio(fg: str, bg: str) -> float | None:
    foreground = _parse_rgb(fg)
    background = _parse_rgb(bg)
    if not foreground or not background:
        return None
    lighter = max(_luminance(foreground), _luminance(background))
    darker = min(_luminance(foreground), _luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def wait_for_shell(page) -> None:
    loading = page.locator("text=Loading live control shell")
    shell = page.locator('[data-neyvia-shell="true"], .fluxos-shell, .reference-shell').first
    for _ in range(60):
        if shell.count() and shell.is_visible():
            if loading.count() == 0:
                return
        page.wait_for_timeout(1000)
    page.wait_for_timeout(1500)


def main() -> int:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    username, password = load_login()
    checks: list[dict] = []
    screenshots: dict[str, str] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        login = context.request.post(
            f"{BASE_UI}/api/auth/login",
            data=json.dumps({"username": username, "password": password}),
            headers={"Content-Type": "application/json"},
        )
        if not login.ok:
            raise RuntimeError(f"Login failed HTTP {login.status}: {login.text()[:400]}")

        page.goto(f"{BASE_UI}/control?surface=agent", wait_until="domcontentloaded", timeout=120_000)
        wait_for_shell(page)

        # Prefer the agent-start Launch mission chip, then other launch controls.
        opened = False
        for selector in (
            '[data-agent-start-action="launch"]',
            '[data-builder-timeline-action="launch"]',
            'button:has-text("Launch mission")',
            'button:has-text("Launch")',
        ):
            loc = page.locator(selector).first
            try:
                loc.wait_for(state="visible", timeout=8_000)
                loc.click(timeout=5_000)
                opened = True
                break
            except Exception:
                continue
        if not opened:
            page.evaluate("() => window.dispatchEvent(new CustomEvent('neyvia:qa-open-mission-launcher'))")
            page.wait_for_timeout(500)

        launcher = page.locator('[data-mission-command-launcher="true"]').first
        try:
            launcher.wait_for(state="visible", timeout=20_000)
            modal_visible = True
        except Exception as exc:
            modal_visible = False
            debug = PROOF_DIR / f"g2-ui-mission-modal-debug-{STAMP}.png"
            page.screenshot(path=str(debug), full_page=False)
            screenshots["mission_modal_debug"] = str(debug.relative_to(ROOT)).replace("\\", "/")
            checks.append(
                {
                    "id": "mission-modal-visible",
                    "ok": False,
                    "detail": f"Mission launcher not visible: {exc}",
                }
            )

        if modal_visible:
            panel = page.locator('.modal-panel:has([data-mission-command-launcher="true"])').first
            metrics = page.evaluate(
                """() => {
                  const panel = document.querySelector('.modal-panel:has([data-mission-command-launcher="true"])');
                  const body = panel?.querySelector('.modal-body');
                  const primary = document.querySelector('[data-mission-launch-primary="true"]');
                  const primaryBtn = primary?.closest('button') || primary;
                  const title = panel?.querySelector('.section-title-block h2');
                  const summary = panel?.querySelector('.section-summary');
                  const cs = (el) => el ? getComputedStyle(el) : null;
                  const panelCs = cs(panel);
                  const bodyCs = cs(body);
                  const primaryCs = cs(primaryBtn);
                  const titleCs = cs(title);
                  const summaryCs = cs(summary);
                  return {
                    panelMaxHeight: panelCs?.maxHeight || '',
                    panelOverflow: panelCs?.overflow || '',
                    panelColor: panelCs?.color || '',
                    panelBg: panelCs?.backgroundColor || '',
                    bodyOverflowY: bodyCs?.overflowY || '',
                    bodyMaxHeight: body ? body.getBoundingClientRect().height : 0,
                    panelHeight: panel ? panel.getBoundingClientRect().height : 0,
                    viewportHeight: window.innerHeight,
                    primaryBg: primaryCs?.backgroundColor || '',
                    primaryColor: primaryCs?.color || '',
                    primaryFontWeight: primaryCs?.fontWeight || '',
                    primaryText: (primaryBtn?.textContent || '').trim(),
                    titleColor: titleCs?.color || '',
                    titleBg: panelCs?.backgroundColor || '',
                    summaryColor: summaryCs?.color || '',
                  };
                }"""
            )

            title_contrast = _contrast_ratio(metrics["titleColor"], metrics["panelBg"]) or 0.0
            primary_contrast = _contrast_ratio(metrics["primaryColor"], metrics["primaryBg"]) or 0.0
            summary_contrast = _contrast_ratio(metrics["summaryColor"], metrics["panelBg"]) or 0.0
            height_ok = metrics["panelHeight"] <= metrics["viewportHeight"] - 12
            scroll_ok = metrics["bodyOverflowY"] in {"auto", "scroll", "overlay"}
            primary_ok = (
                "launch mission" in metrics["primaryText"].lower()
                and primary_contrast >= 4.5
            )
            contrast_ok = title_contrast >= 4.5 and summary_contrast >= 3.0

            checks.extend(
                [
                    {"id": "mission-modal-visible", "ok": True, "detail": "Launcher visible"},
                    {
                        "id": "modal-height-constrained",
                        "ok": height_ok,
                        "detail": f"panelHeight={metrics['panelHeight']:.1f} viewport={metrics['viewportHeight']}",
                        "metrics": {
                            "panelHeight": metrics["panelHeight"],
                            "viewportHeight": metrics["viewportHeight"],
                            "panelMaxHeight": metrics["panelMaxHeight"],
                        },
                    },
                    {
                        "id": "modal-body-scrollable",
                        "ok": scroll_ok,
                        "detail": f"overflowY={metrics['bodyOverflowY']}",
                    },
                    {
                        "id": "modal-text-contrast",
                        "ok": contrast_ok,
                        "detail": f"titleContrast={title_contrast:.2f} summaryContrast={summary_contrast:.2f}",
                        "colors": {
                            "titleColor": metrics["titleColor"],
                            "summaryColor": metrics["summaryColor"],
                            "panelBg": metrics["panelBg"],
                        },
                    },
                    {
                        "id": "primary-action-obvious",
                        "ok": primary_ok,
                        "detail": f"text={metrics['primaryText']!r} contrast={primary_contrast:.2f} weight={metrics['primaryFontWeight']}",
                        "colors": {
                            "primaryBg": metrics["primaryBg"],
                            "primaryColor": metrics["primaryColor"],
                        },
                    },
                ]
            )

            shot = PROOF_DIR / f"g2-ui-mission-modal-{STAMP}.png"
            panel.screenshot(path=str(shot))
            screenshots["mission_modal"] = str(shot.relative_to(ROOT)).replace("\\", "/")
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)

        # Mobile conversation picker proof
        mobile = context.new_page()
        mobile.set_viewport_size({"width": 390, "height": 844})
        mobile.goto(f"{BASE_UI}/control?surface=agent", wait_until="domcontentloaded", timeout=120_000)
        wait_for_shell(mobile)

        for selector in (
            'button[aria-label="Open Neyvia Chat"]',
            'button[title="Neyvia Chat"]',
            'button[aria-label="Open Chat"]',
            'nav button[aria-label*="Chat"]',
        ):
            loc = mobile.locator(selector).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=5_000)
                break
        mobile.wait_for_timeout(1000)

        sidebar_hidden = mobile.evaluate(
            """() => {
              const sidebar = document.querySelector('.neyvia-conversation-sidebar:not(.is-sheet)');
              if (!sidebar) return true;
              const style = getComputedStyle(sidebar);
              return style.display === 'none' || style.visibility === 'hidden';
            }"""
        )
        trigger = mobile.locator('[data-mobile-conversation-picker-trigger="true"]').first
        trigger_visible = False
        try:
            trigger.wait_for(state="visible", timeout=12_000)
            trigger_visible = True
        except Exception:
            trigger_visible = trigger.count() > 0 and trigger.is_visible()

        checks.append(
            {
                "id": "mobile-sidebar-hidden",
                "ok": bool(sidebar_hidden),
                "detail": f"sidebarHidden={sidebar_hidden}",
            }
        )
        checks.append(
            {
                "id": "mobile-picker-trigger-visible",
                "ok": bool(trigger_visible),
                "detail": f"triggerVisible={trigger_visible}",
            }
        )

        if trigger_visible:
            trigger.click(timeout=5_000)
            picker = mobile.locator('[data-mobile-conversation-picker="true"]').first
            picker.wait_for(state="visible", timeout=8_000)
            sheet = mobile.locator('.neyvia-conversation-sidebar.is-sheet').first
            checks.append(
                {
                    "id": "mobile-picker-opens",
                    "ok": picker.is_visible() and sheet.is_visible(),
                    "detail": "Conversation sheet opened from mobile trigger",
                }
            )
            shot = PROOF_DIR / f"g2-ui-mobile-conversation-picker-{STAMP}.png"
            mobile.screenshot(path=str(shot), full_page=False)
            screenshots["mobile_picker"] = str(shot.relative_to(ROOT)).replace("\\", "/")
        else:
            checks.append(
                {
                    "id": "mobile-picker-opens",
                    "ok": False,
                    "detail": "Trigger not visible; picker could not be opened",
                }
            )
            shot = PROOF_DIR / f"g2-ui-mobile-conversation-picker-debug-{STAMP}.png"
            mobile.screenshot(path=str(shot), full_page=False)
            screenshots["mobile_picker_debug"] = str(shot.relative_to(ROOT)).replace("\\", "/")

        browser.close()

    passed = all(item.get("ok") for item in checks)
    proof = {
        "stamp": STAMP,
        "result": "PASSED" if passed else "FAILED",
        "checks": checks,
        "screenshots": screenshots,
        "baseUi": f"{BASE_UI}/control",
    }
    proof_path = PROOF_DIR / f"g2-ui-correction-proof-{STAMP}.json"
    proof_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps(proof, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
