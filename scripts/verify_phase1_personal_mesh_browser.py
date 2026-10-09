"""Browser-visible proof for Phase 1 Personal Mesh operator panel."""

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
    debug_shot = PROOF_DIR / "phase1-personal-mesh-browser-debug-20260724.png"

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
        page.wait_for_timeout(1500)

        trust_shot = PROOF_DIR / "phase1-personal-mesh-trust-browser-20260724.png"
        page.screenshot(path=str(trust_shot), full_page=True)

        page.get_by_role("tab", name=re.compile("Nearby Send", re.I)).click()
        page.wait_for_timeout(800)

        # Live loopback hash-ACK transfer through the same backend the UI uses.
        proof_file = (
            ROOT / ".agent_control" / "nearby_send" / "phase1-browser-hash-ack.txt"
        )
        proof_file.parent.mkdir(parents=True, exist_ok=True)
        proof_file.write_text(
            f"browser hash ack proof {time.time()}",
            encoding="utf-8",
        )
        sidecar_start = context.request.post(
            f"{BASE}/api/backend",
            data=json.dumps(
                {
                    "command": "start_nearby_receiver_sidecar_command",
                    "payload": {"host": "127.0.0.1", "port": 0},
                }
            ),
            headers={"Content-Type": "application/json"},
        ).json()
        sidecar_data = sidecar_start.get("data") or {}
        endpoint = str(sidecar_data.get("endpoint") or "")
        plan_response = context.request.post(
            f"{BASE}/api/backend",
            data=json.dumps(
                {
                    "command": "plan_nearby_send_command",
                    "payload": {
                        "paths": [str(proof_file)],
                        "recipientEndpoint": endpoint,
                    },
                }
            ),
            headers={"Content-Type": "application/json"},
        ).json()
        send_response = context.request.post(
            f"{BASE}/api/backend",
            data=json.dumps(
                {
                    "command": "send_nearby_files_command",
                    "payload": {
                        "plan": (plan_response.get("data") or {}),
                        "approved": True,
                    },
                }
            ),
            headers={"Content-Type": "application/json"},
        ).json()
        send_data = send_response.get("data") or {}

        page.locator('[data-neyvia-mesh-action="refresh"]').click()
        page.wait_for_timeout(1200)
        page.get_by_role("tab", name=re.compile("Nearby Send", re.I)).click()
        page.wait_for_timeout(800)

        nearby_shot = PROOF_DIR / "phase1-personal-mesh-nearby-browser-20260724.png"
        page.screenshot(path=str(nearby_shot), full_page=True)
        history_visible = page.locator("text=Transfer history").count() > 0
        physical_blocked = page.locator("text=Physical device proof").count() > 0
        sidecar_card = page.locator('[data-nearby-sidecar]').count() > 0
        hash_summary = page.locator('[data-nearby-hash-summary="true"]').count() > 0
        remote_verified_ui = page.locator('[data-remote-hash-verified="true"]').count()
        source_match_ui = page.locator('[data-source-matches-destination="true"]').count()
        source_eq_dest_text = page.locator("text=source==dest SHA-256").count() > 0

        page.get_by_role("tab", name=re.compile("Folder Sync", re.I)).click()
        page.wait_for_timeout(800)
        sync_shot = PROOF_DIR / "phase1-personal-mesh-sync-browser-20260724.png"
        page.screenshot(path=str(sync_shot), full_page=True)

        enrollment = context.request.post(
            f"{BASE}/api/backend",
            data=json.dumps(
                {"command": "get_mesh_enrollment_trust_command", "payload": {}}
            ),
            headers={"Content-Type": "application/json"},
        ).json()
        history = context.request.post(
            f"{BASE}/api/backend",
            data=json.dumps(
                {
                    "command": "get_nearby_transfer_history_command",
                    "payload": {"limit": 10},
                }
            ),
            headers={"Content-Type": "application/json"},
        ).json()
        sidecar = context.request.post(
            f"{BASE}/api/backend",
            data=json.dumps(
                {
                    "command": "get_nearby_receiver_sidecar_status_command",
                    "payload": {},
                }
            ),
            headers={"Content-Type": "application/json"},
        ).json()
        context.request.post(
            f"{BASE}/api/backend",
            data=json.dumps(
                {"command": "stop_nearby_receiver_sidecar_command", "payload": {}}
            ),
            headers={"Content-Type": "application/json"},
        )

        history_data = history.get("data") or {}
        history_summary = history_data.get("summary") or {}
        file_rows = ((send_data.get("files") or [{}])[0]) if isinstance(send_data, dict) else {}
        receipt = {
            "schema": "neyvia.phase1-personal-mesh-browser-proof/v1",
            "ok": bool(
                send_response.get("ok")
                and send_data.get("summary", {}).get("remoteHashVerified", 0) >= 1
                and remote_verified_ui >= 1
            ),
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "entry": "Lab/command-palette > Personal Mesh",
            "panelVisible": True,
            "historySectionVisible": history_visible,
            "physicalDeviceProofMarked": physical_blocked,
            "sidecarCardVisible": sidecar_card,
            "hashSummaryVisible": hash_summary,
            "remoteHashVerifiedRowsVisible": remote_verified_ui,
            "sourceMatchesDestinationRowsVisible": source_match_ui,
            "sourceEqualsDestTextVisible": source_eq_dest_text,
            "liveTransfer": {
                "sidecarStartOk": bool(sidecar_start.get("ok")),
                "endpoint": endpoint,
                "planOk": bool(plan_response.get("ok")),
                "sendOk": bool(send_response.get("ok")),
                "remoteHashVerified": (send_data.get("summary") or {}).get(
                    "remoteHashVerified"
                ),
                "sourceSha256": file_rows.get("sha256"),
                "destinationSha256": file_rows.get("destinationSha256"),
                "sourceMatchesDestination": file_rows.get(
                    "sourceMatchesDestination"
                ),
                "receiptId": send_data.get("receiptId"),
            },
            "screenshots": {
                "trust": str(trust_shot),
                "nearby": str(nearby_shot),
                "sync": str(sync_shot),
                "debug": str(debug_shot),
            },
            "api": {
                "enrollmentOk": bool(enrollment.get("ok")),
                "enrollmentAvailable": (
                    ((enrollment.get("data") or {}).get("enrollment") or {}).get(
                        "available"
                    )
                ),
                "historyOk": bool(history.get("ok")),
                "historyTransfers": history_summary.get("transfers"),
                "remoteHashVerifiedCount": history_summary.get(
                    "remoteHashVerifiedCount"
                ),
                "sourceMatchesDestinationCount": history_summary.get(
                    "sourceMatchesDestinationCount"
                ),
                "sidecarOk": bool(sidecar.get("ok")),
                "sidecarImplemented": (
                    (sidecar.get("data") or {}).get("implemented")
                ),
                "sidecarRunning": ((sidecar.get("data") or {}).get("running")),
            },
        }
        out = PROOF_DIR / "phase1-personal-mesh-browser-proof-20260724.json"
        out.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps({"proofPath": str(out), **receipt}, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
