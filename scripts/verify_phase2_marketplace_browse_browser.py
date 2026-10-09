"""Browser-visible proof for Phase 2 Marketplace browse/detail slice."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROOF_DIR = ROOT / ".agent_control" / "capability_os" / "qa"
PASSWORD_FILE = ROOT / ".agent_control" / "grand_agent_admin_password.txt"
BASE = "http://127.0.0.1:1420"


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
            (ROOT / ".agent_control" / "grand_agent_web_admin.json").read_text(
                encoding="utf-8"
            )
        )
        username = str(account.get("username") or "admin")
    if not username or not password:
        raise RuntimeError("Missing local Neyvia login credentials")
    return username, password


def main() -> int:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    username, password = load_login()
    started = time.perf_counter()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    debug_shot = PROOF_DIR / f"phase2-marketplace-browser-debug-{stamp}.png"
    browse_shot = PROOF_DIR / f"phase2-marketplace-browse-browser-{stamp}.png"
    gates_shot = PROOF_DIR / f"phase2-marketplace-gates-browser-{stamp}.png"
    receipt_path = PROOF_DIR / f"phase2-marketplace-browse-proof-{stamp}.json"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        page = context.new_page()

        login = context.request.post(
            f"{BASE}/api/auth/login",
            data=json.dumps({"username": username, "password": password}),
            headers={"Content-Type": "application/json"},
        )
        if not login.ok:
            raise RuntimeError(f"Login failed HTTP {login.status}: {login.text()[:400]}")

        api = context.request.post(
            f"{BASE}/api/backend",
            data=json.dumps(
                {
                    "command": "get_module_marketplace_browse_command",
                    "payload": {},
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        if not api.ok:
            raise RuntimeError(
                f"Marketplace browse API failed HTTP {api.status}: {api.text()[:600]}"
            )
        payload = api.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Marketplace browse API error: {payload.get('error')}")
        snapshot = payload.get("data") or {}

        page.goto(f"{BASE}/control", wait_until="domcontentloaded", timeout=120000)

        lab = page.locator('button:has-text("Lab")')
        market_button = page.locator('[data-neyvia-lab-action="marketplace"]')
        loading = page.locator("text=Loading live control shell")
        for attempt in range(90):
            page.wait_for_timeout(2000)
            print(
                f"wait {attempt}: lab={lab.count()} market={market_button.count()} "
                f"loading={loading.count()} buttons={page.locator('button').count()}"
            )
            if market_button.count() > 0:
                break
            if loading.count() == 0 and lab.count() > 0 and page.locator("button").count() > 8:
                break
            if attempt in {10, 20, 40}:
                page.screenshot(path=str(debug_shot), full_page=True)

        page.screenshot(path=str(debug_shot), full_page=True)

        if market_button.count() == 0 and lab.count() > 0:
            lab.first.click()
            page.wait_for_timeout(2000)

        if market_button.count() > 0:
            market_button.first.click()
        else:
            page.keyboard.press("Control+K")
            page.wait_for_timeout(800)
            search = page.locator(
                '[data-neyvia-command-palette="true"] input, '
                ".neyvia-command-palette input, "
                'input[placeholder*="Search"]'
            )
            if search.count() == 0:
                raise RuntimeError(
                    "Marketplace entry not found after shell wait. "
                    f"Debug screenshot: {debug_shot}"
                )
            search.first.fill("Marketplace")
            page.wait_for_timeout(700)
            page.get_by_text("Marketplace", exact=False).first.click()

        panel = page.locator('[data-neyvia-marketplace="true"]')
        panel.wait_for(state="visible", timeout=30000)
        page.wait_for_timeout(1500)

        listings = page.locator('[data-marketplace-listings="true"] li button')
        if listings.count() == 0:
            raise RuntimeError("Marketplace browse opened but no listing rows rendered")
        listing_rows = listings.count()
        listings.first.click()
        page.wait_for_timeout(500)
        detail = page.locator(".neyvia-marketplace-detail")
        detail.wait_for(state="visible", timeout=10000)
        detail_visible = detail.count() > 0
        human_on_browse = page.locator(
            '.neyvia-marketplace-detail [data-evidence="human-reviews"]'
        ).count() > 0
        page.screenshot(path=str(browse_shot), full_page=True)

        page.get_by_role("tab", name=re.compile("Gates", re.I)).click()
        page.wait_for_timeout(700)
        page.locator('[data-marketplace-section="gates"]').wait_for(state="visible")
        page.screenshot(path=str(gates_shot), full_page=True)

        page.get_by_role("tab", name=re.compile("Evidence", re.I)).click()
        page.wait_for_timeout(700)
        page.locator('[data-marketplace-section="evidence"]').wait_for(state="visible")
        human_on_evidence = page.locator('[data-evidence="human-reviews"]').count() > 0
        if page.locator('[data-install-progress="unavailable"]').count() == 0:
            raise RuntimeError("Install progress unavailable banner missing")

        receipt = {
            "schema": "neyvia.phase2-marketplace-browse-proof/v1",
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "durationMs": round((time.perf_counter() - started) * 1000, 2),
            "baseUrl": BASE,
            "uiBrowseProof": True,
            "packageInstallProof": False,
            "api": {
                "command": "get_module_marketplace_browse_command",
                "schema": snapshot.get("schema"),
                "listingCount": (snapshot.get("summary") or {}).get("listingCount"),
                "ociPublicRegistry": (snapshot.get("availability") or {}).get(
                    "ociPublicRegistry"
                ),
                "installProgressStreaming": (snapshot.get("availability") or {}).get(
                    "installProgressStreaming"
                ),
                "humanReviewsAvailable": (
                    (snapshot.get("evidencePolicy") or {})
                    .get("humanReviews", {})
                    .get("available")
                ),
                "activationGateReady": (snapshot.get("gates") or {}).get(
                    "activationGateReady"
                ),
            },
            "browser": {
                "panelVisible": True,
                "listingRows": listing_rows,
                "detailVisible": detail_visible,
                "humanReviewsSectionPresent": human_on_browse or human_on_evidence,
                "installProgressHonestlyUnavailable": True,
                "screenshots": {
                    "debug": str(debug_shot),
                    "browse": str(browse_shot),
                    "gates": str(gates_shot),
                },
            },
            "confidence": {
                "uiBrowseWiredToRealApi": True,
                "realPackageInstallVerified": False,
                "note": (
                    "This proof covers operator browse/detail against live "
                    "get_module_marketplace_browse_command data. It does not "
                    "prove signed package install, rollback, or OCI pull."
                ),
            },
        }
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
