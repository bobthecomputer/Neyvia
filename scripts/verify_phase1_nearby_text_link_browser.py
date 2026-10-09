"""Browser-visible Phase 1 proof: Nearby Send text/link + favorites + receipts."""

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


def backend(context, command: str, payload: dict | None = None) -> dict:
    response = context.request.post(
        f"{BASE}/api/backend",
        data=json.dumps({"command": command, "payload": payload or {}}),
        headers={"Content-Type": "application/json"},
    )
    body = response.json()
    if not response.ok or not body.get("ok"):
        raise RuntimeError(
            f"{command} failed: HTTP {response.status} {json.dumps(body)[:500]}"
        )
    return body.get("data") or {}


def open_personal_mesh(page) -> None:
    page.goto(f"{BASE}/control", wait_until="domcontentloaded", timeout=120000)
    mesh_button = page.locator('[data-neyvia-lab-action="personal-mesh"]')
    lab = page.locator('button:has-text("Lab")')
    loading = page.locator("text=Loading live control shell")
    for _ in range(90):
        page.wait_for_timeout(1500)
        if mesh_button.count() > 0:
            break
        if loading.count() == 0 and lab.count() > 0 and page.locator("button").count() > 8:
            break
    if mesh_button.count() == 0 and lab.count() > 0:
        lab.first.click()
        page.wait_for_timeout(1200)
    if mesh_button.count() > 0:
        mesh_button.first.click()
    else:
        page.keyboard.press("Control+K")
        page.wait_for_timeout(700)
        search = page.locator(
            '[data-neyvia-command-palette="true"] input, '
            ".neyvia-command-palette input, "
            'input[placeholder*="Search"]'
        )
        search.first.fill("Personal Mesh")
        page.wait_for_timeout(500)
        page.get_by_text("Personal Mesh", exact=False).first.click()
    page.locator('[data-neyvia-personal-mesh="true"]').wait_for(
        state="visible",
        timeout=30000,
    )


def main() -> int:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    username, password = load_login()
    started = time.perf_counter()
    text_body = f"phase1 text payload proof {time.time()}"
    link_body = "https://example.com/neyvia-phase1-nearby"

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

        open_personal_mesh(page)
        page.get_by_role("tab", name=re.compile("Nearby Send", re.I)).click()
        page.wait_for_timeout(800)

        sidecar = backend(
            context,
            "start_nearby_receiver_sidecar_command",
            {"host": "127.0.0.1", "port": 0},
        )
        endpoint = str(sidecar.get("endpoint") or "")
        favorite = backend(
            context,
            "upsert_nearby_favorite_command",
            {
                "device": {
                    "deviceId": "nearby_loopback_sidecar",
                    "alias": "Loopback sidecar",
                    "endpoint": endpoint,
                }
            },
        )
        plan = backend(
            context,
            "plan_nearby_send_command",
            {
                "payloads": [
                    {"kind": "text", "content": text_body},
                    {"kind": "link", "content": link_body},
                ],
                "favoriteDeviceId": favorite["device"]["deviceId"],
            },
        )
        send = backend(
            context,
            "send_nearby_files_command",
            {"plan": plan, "approved": True},
        )
        page.locator('[data-neyvia-mesh-action="refresh"]').click()
        page.wait_for_timeout(1200)
        page.get_by_role("tab", name=re.compile("Nearby Send", re.I)).click()
        page.wait_for_timeout(900)

        shot = PROOF_DIR / "phase1-nearby-text-link-browser-20260724.png"
        page.screenshot(path=str(shot), full_page=True)

        composer_visible = page.locator('[data-nearby-payload-composer="true"]').count() > 0
        favorites_visible = page.locator('[data-nearby-favorites="true"]').count() > 0
        physical_blocked = page.locator('[data-nearby-physical-proof="blocked"]').count() > 0
        text_rows = page.locator('[data-payload-kind="text"]').count()
        link_rows = page.locator('[data-payload-kind="link"]').count()
        remote_verified = page.locator('[data-remote-hash-verified="true"]').count()
        source_match = page.locator('[data-source-matches-destination="true"]').count()

        history = backend(
            context,
            "get_nearby_transfer_history_command",
            {"limit": 10},
        )
        favorites = backend(context, "get_nearby_favorites_command", {})
        backend(context, "stop_nearby_receiver_sidecar_command", {})

        send_summary = send.get("summary") or {}
        file_kinds = {
            str(row.get("payloadKind") or "")
            for row in send.get("files") or []
            if isinstance(row, dict)
        }
        receipt = {
            "schema": "neyvia.phase1-nearby-text-link-browser-proof/v1",
            "ok": bool(
                send.get("ok")
                and send_summary.get("remoteHashVerified", 0) >= 2
                and send_summary.get("textCount", 0) >= 1
                and send_summary.get("linkCount", 0) >= 1
                and composer_visible
                and favorites_visible
                and physical_blocked
                and text_rows >= 1
                and link_rows >= 1
                and remote_verified >= 1
            ),
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "physicalDeviceProof": {
                "available": False,
                "uiMarkedBlocked": physical_blocked,
                "reason": (history.get("physicalDeviceProof") or {}).get("reason"),
            },
            "ui": {
                "composerVisible": composer_visible,
                "favoritesVisible": favorites_visible,
                "textPayloadRowsVisible": text_rows,
                "linkPayloadRowsVisible": link_rows,
                "remoteHashVerifiedRowsVisible": remote_verified,
                "sourceMatchesDestinationRowsVisible": source_match,
                "screenshot": str(shot),
            },
            "liveTransfer": {
                "sidecarEndpoint": endpoint,
                "favoriteDeviceId": favorite.get("device", {}).get("deviceId"),
                "planId": plan.get("planId"),
                "receiptId": send.get("receiptId"),
                "ok": send.get("ok"),
                "payloadKinds": sorted(file_kinds),
                "remoteHashVerified": send_summary.get("remoteHashVerified"),
                "textCount": send_summary.get("textCount"),
                "linkCount": send_summary.get("linkCount"),
                "files": [
                    {
                        "fileName": row.get("fileName"),
                        "payloadKind": row.get("payloadKind"),
                        "sha256": row.get("sha256"),
                        "destinationSha256": row.get("destinationSha256"),
                        "sourceMatchesDestination": row.get(
                            "sourceMatchesDestination"
                        ),
                    }
                    for row in send.get("files") or []
                    if isinstance(row, dict)
                ],
            },
            "favorites": {
                "count": (favorites.get("summary") or {}).get("devices"),
                "autoAcceptFromFavorites": (
                    (favorites.get("policy") or {}).get("autoAcceptFromFavorites")
                ),
                "senderQuickTargetOnly": (
                    (favorites.get("policy") or {}).get("senderQuickTargetOnly")
                ),
            },
            "history": {
                "transfers": (history.get("summary") or {}).get("transfers"),
                "remoteHashVerifiedCount": (history.get("summary") or {}).get(
                    "remoteHashVerifiedCount"
                ),
                "sourceMatchesDestinationCount": (history.get("summary") or {}).get(
                    "sourceMatchesDestinationCount"
                ),
            },
        }
        out = PROOF_DIR / "phase1-nearby-text-link-browser-proof-20260724.json"
        out.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps({"proofPath": str(out), **receipt}, indent=2))
        browser.close()
        return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
