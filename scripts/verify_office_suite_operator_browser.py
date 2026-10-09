"""Browser proof for the LibreOffice/Pandoc Office Suite operator workspace."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROOF_DIR = ROOT / ".agent_control" / "capability_os" / "qa"
PASSWORD_FILE = ROOT / ".agent_control" / "grand_agent_admin_password.txt"
BASE = "http://127.0.0.1:1420"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    stamp = time.strftime("%Y%m%d-%H%M%S")
    debug_shot = PROOF_DIR / f"grok-office-suite-browser-debug-{stamp}.png"
    panel_shot = PROOF_DIR / f"grok-office-suite-browser-panel-{stamp}.png"
    receipt_path = PROOF_DIR / f"grok-office-suite-browser-proof-{stamp}.json"

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

        describe_lo = context.request.post(
            f"{BASE}/api/backend",
            data=json.dumps(
                {
                    "command": "describe_tool_suite_command",
                    "payload": {"toolId": "tool.libreoffice"},
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        describe_pandoc = context.request.post(
            f"{BASE}/api/backend",
            data=json.dumps(
                {
                    "command": "describe_tool_suite_command",
                    "payload": {"toolId": "tool.pandoc"},
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        if not describe_lo.ok or not describe_pandoc.ok:
            raise RuntimeError("describe_tool_suite_command failed for office tools")
        lo_payload = describe_lo.json()
        pandoc_payload = describe_pandoc.json()
        if not lo_payload.get("ok") or not pandoc_payload.get("ok"):
            raise RuntimeError("describe_tool_suite_command returned ok=false")
        lo_data = lo_payload.get("data") or {}
        pandoc_data = pandoc_payload.get("data") or {}

        page.goto(f"{BASE}/control", wait_until="domcontentloaded", timeout=120000)

        lab = page.locator('button:has-text("Lab")')
        office_button = page.locator('[data-neyvia-lab-action="office-suite"]')
        loading = page.locator("text=Loading live control shell")
        for attempt in range(90):
            page.wait_for_timeout(2000)
            print(
                f"wait {attempt}: lab={lab.count()} office={office_button.count()} "
                f"loading={loading.count()} buttons={page.locator('button').count()}"
            )
            if office_button.count() > 0:
                break
            if loading.count() == 0 and lab.count() > 0 and page.locator("button").count() > 8:
                break
            if attempt in {10, 20, 40}:
                page.screenshot(path=str(debug_shot), full_page=True)

        page.screenshot(path=str(debug_shot), full_page=True)

        if office_button.count() == 0 and lab.count() > 0:
            lab.first.click()
            page.wait_for_timeout(2000)

        if office_button.count() == 0:
            raise RuntimeError(
                "Office Suite Lab entry not found. "
                f"Debug screenshot: {debug_shot}"
            )

        office_button.first.click()
        panel = page.locator('[data-neyvia-office-suite="true"]')
        panel.wait_for(state="visible", timeout=30000)
        page.wait_for_timeout(1200)

        availability = page.locator('[data-office-availability="true"]')
        availability.wait_for(state="visible", timeout=10000)
        proof_empty = page.locator('[data-office-proof="empty"]').count() > 0
        agent_ready_lo = bool(lo_data.get("agentReady") is True)
        agent_ready_pandoc = bool(pandoc_data.get("agentReady") is True)
        live_convert_proven = False
        convert_status = None
        convert_note = "UI opened; no live convert attempted in this proof."

        # Optional honest convert only when Pandoc is agent-ready and a workspace source exists.
        source = ROOT / "README.md"
        if agent_ready_pandoc and source.is_file():
            page.locator('[data-office-tool="tool.pandoc"]').click()
            page.wait_for_timeout(1500)
            page.locator('[data-office-field="operationId"]').select_option("document.convert")
            page.wait_for_timeout(800)
            out = (
                ROOT
                / ".agent_control"
                / "capability_os"
                / "outputs"
                / f"grok-office-suite-proof-{stamp}.html"
            )
            if out.exists():
                out.unlink()
            # Fill required fields after operation settle; re-assert approve last.
            for _attempt in range(3):
                if page.locator('[data-office-field="path"]').count():
                    page.locator('[data-office-field="path"]').fill(str(source))
                if page.locator('[data-office-field="outputFormat"]').count():
                    page.locator('[data-office-field="outputFormat"]').fill("html")
                if page.locator('[data-office-field="outputPath"]').count():
                    page.locator('[data-office-field="outputPath"]').fill(str(out))
                if page.locator('[data-office-field="inputFormat"]').count():
                    page.locator('[data-office-field="inputFormat"]').fill("markdown")
                page.locator('[data-office-approve="true"]').check()
                page.wait_for_timeout(250)
                path_value = page.locator('[data-office-field="path"]').input_value()
                if str(source) in path_value and page.locator('[data-office-approve="true"]').is_checked():
                    break
            execute = page.locator('[data-office-action="execute"]')
            if execute.is_disabled():
                convert_note = "Execute stayed disabled after approve/fill — inputs not accepted."
            else:
                execute.click()
                page.locator('[data-office-proof="true"]').wait_for(
                    state="visible", timeout=120000
                )
                page.wait_for_timeout(500)
                proof = page.locator('[data-office-proof="true"]')
                convert_status = proof.get_attribute("data-office-outcome")
                live_convert_proven = convert_status == "verified"
                convert_note = (
                    f"Live execute_tool_suite_command outcome={convert_status}; "
                    f"outputExists={out.exists()}"
                )
        elif not agent_ready_lo and not agent_ready_pandoc:
            convert_note = (
                "Honest unavailable proof: neither LibreOffice nor Pandoc "
                "reported agentReady from describe_tool_suite_command."
            )

        page.screenshot(path=str(panel_shot), full_page=True)

        proof = {
            "schema": "neyvia.office_suite.browser_proof.v1",
            "stamp": stamp,
            "panelVisible": panel.count() > 0,
            "availabilityVisible": availability.count() > 0,
            "proofEmptyBeforeExecute": proof_empty,
            "describe": {
                "libreoffice": {
                    "agentReady": agent_ready_lo,
                    "state": lo_data.get("state"),
                    "operationCount": len(lo_data.get("operations") or []),
                    "selectedVersion": lo_data.get("selectedVersion"),
                },
                "pandoc": {
                    "agentReady": agent_ready_pandoc,
                    "state": pandoc_data.get("state"),
                    "operationCount": len(pandoc_data.get("operations") or []),
                    "selectedVersion": pandoc_data.get("selectedVersion"),
                },
            },
            "liveConvertProven": live_convert_proven,
            "convertOutcome": convert_status,
            "convertNote": convert_note,
            "screenshots": {
                "debug": str(debug_shot.relative_to(ROOT)).replace("\\", "/"),
                "panel": str(panel_shot.relative_to(ROOT)).replace("\\", "/"),
            },
            "hashes": {
                "debugScreenshotSha256": sha256_file(debug_shot),
                "panelScreenshotSha256": sha256_file(panel_shot),
            },
        }
        receipt_path.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(proof, indent=2))
        print(f"PROOF_JSON={receipt_path}")
        print(f"PROOF_JSON_SHA256={sha256_file(receipt_path)}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
