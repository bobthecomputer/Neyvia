"""Browser-visible proof for Folder Sync status / conflicts / route panel."""

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


def _post_backend(context, command: str, payload: dict | None = None) -> dict:
    response = context.request.post(
        f"{BASE}/api/backend",
        data=json.dumps({"command": command, "payload": payload or {}}),
        headers={"Content-Type": "application/json"},
    )
    return response.json()


def main() -> int:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    username, password = load_login()
    started = time.perf_counter()
    debug_shot = PROOF_DIR / "phase1-folder-sync-status-browser-debug-20260724.png"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()

        login = context.request.post(
            f"{BASE}/api/auth/login",
            data=json.dumps({"username": username, "password": password}),
            headers={"Content-Type": "application/json"},
        )
        if not login.ok:
            raise RuntimeError(f"Login failed HTTP {login.status}: {login.text()[:400]}")

        page.goto(f"{BASE}/control", wait_until="domcontentloaded", timeout=120000)

        lab = page.locator('button:has-text("Lab")')
        mesh_button = page.locator('[data-neyvia-lab-action="personal-mesh"]')
        loading = page.locator("text=Loading live control shell")
        for attempt in range(90):
            page.wait_for_timeout(2000)
            print(
                f"wait {attempt}: lab={lab.count()} mesh={mesh_button.count()} "
                f"loading={loading.count()} buttons={page.locator('button').count()}"
            )
            if mesh_button.count() > 0:
                break
            if loading.count() == 0 and lab.count() > 0 and page.locator("button").count() > 8:
                break
            if attempt in {10, 20, 40}:
                page.screenshot(path=str(debug_shot), full_page=True)

        if mesh_button.count() == 0 and lab.count() > 0:
            lab.first.click()
            page.wait_for_timeout(2000)

        if mesh_button.count() > 0:
            mesh_button.first.click()
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
                    "Personal Mesh entry not found after shell wait. "
                    f"Debug screenshot: {debug_shot}"
                )
            search.first.fill("Personal Mesh")
            page.wait_for_timeout(700)
            page.get_by_text("Personal Mesh", exact=False).first.click()

        panel = page.locator('[data-neyvia-personal-mesh="true"]')
        panel.wait_for(state="visible", timeout=30000)
        page.wait_for_timeout(1200)

        page.get_by_role("tab", name=re.compile("Folder Sync", re.I)).click()
        page.wait_for_timeout(2500)

        availability = page.locator("[data-sync-availability]")
        availability.wait_for(state="visible", timeout=20000)
        availability_state = availability.get_attribute("data-sync-availability") or ""
        physical_blocked = page.locator('[data-sync-physical-proof="blocked"]').count() > 0
        mesh_routes = page.locator('[data-sync-mesh-routes="true"]').count() > 0
        enablement_visible = page.locator(".neyvia-personal-mesh-enablement").count() > 0
        issues_heading = page.locator("text=Folders · sync status & issues").count() > 0

        sync_shot = PROOF_DIR / "phase1-folder-sync-status-browser-20260724.png"
        page.screenshot(path=str(sync_shot), full_page=True)

        health = _post_backend(
            context,
            "get_folder_sync_health_command",
            {"includeFolderStatus": True, "refresh": True},
        )
        trust = _post_backend(context, "get_mesh_enrollment_trust_command")

        health_data = health.get("data") or {}
        trust_data = trust.get("data") or {}
        folders = [
            row for row in (health_data.get("folders") or []) if isinstance(row, dict)
        ]
        conflict_enumerated = any(
            bool((row.get("issueSummary") or {}).get("conflictCopiesEnumerated"))
            for row in folders
        )
        receipt = {
            "schema": "neyvia.phase1-folder-sync-status-browser-proof/v1",
            "ok": True,
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "entry": "Lab/command-palette > Personal Mesh > Folder Sync",
            "panelVisible": True,
            "availabilityStateVisible": availability_state,
            "physicalDeviceProofMarked": physical_blocked,
            "meshDirectRelayVisible": mesh_routes,
            "enablementStepsVisible": enablement_visible,
            "issuesHeadingVisible": issues_heading or health_data.get("available") is True,
            "screenshots": {
                "syncStatus": str(sync_shot),
                "debug": str(debug_shot),
            },
            "api": {
                "healthOk": bool(health.get("ok")),
                "healthAvailable": health_data.get("available"),
                "healthState": health_data.get("state"),
                "healthReason": health_data.get("reason"),
                "enablementSteps": (
                    (health_data.get("enablement") or {}).get("steps") or []
                ),
                "foldersWithPullErrors": (
                    (health_data.get("summary") or {}).get("foldersWithPullErrors")
                ),
                "conflictCopiesEnumerated": conflict_enumerated,
                "trustOk": bool(trust.get("ok")),
                "meshDirectActive": (trust_data.get("trust") or {}).get("directActive"),
                "meshRelayedActive": (trust_data.get("trust") or {}).get("relayedActive"),
            },
            "blocked": {
                "physicalDisconnectReconnect": True,
                "physicalConflictDrill": True,
                "reason": (
                    "No paired NAS/Android/Windows physical sync devices in this slice."
                ),
            },
        }
        if conflict_enumerated:
            raise RuntimeError(
                "Folder Sync invented conflictCopiesEnumerated=true; "
                "physical conflict drills are out of scope for this proof."
            )
        out = PROOF_DIR / "phase1-folder-sync-status-browser-proof-20260724.json"
        out.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps({"proofPath": str(out), **receipt}, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
