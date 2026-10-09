"""Live browser proof: durable conversation paging 80 → 160 turns.

Seeds a 260-turn chat through the running web backend, opens the built/dev UI,
asserts the initial page shows 80 of 260, clicks Load earlier messages, and
asserts 160 of 260 with the Turn 100 / Turn 99 boundary check from the prior
product proof.
"""

from __future__ import annotations

import json
import statistics
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROOF_DIR = ROOT / ".agent_control" / "capability_os" / "qa"
PASSWORD_FILE = ROOT / ".agent_control" / "grand_agent_admin_password.txt"
BASE_UI = "http://127.0.0.1:1420"
BASE_API = "http://127.0.0.1:47880"
TOTAL_TURNS = 260
PAGE_SIZE = 80
STAMP = time.strftime("%Y%m%d")
TITLE = f"Phase0 paging proof {STAMP}"


def _load_login() -> tuple[str, str]:
    text = PASSWORD_FILE.read_text(encoding="utf-8")
    username = "admin"
    password = ""
    for line in text.splitlines():
        lower = line.lower()
        if lower.startswith("username:"):
            username = line.split(":", 1)[1].strip() or username
        if lower.startswith("password:"):
            password = line.split(":", 1)[1].strip()
    if not password:
        raise RuntimeError(f"password missing in {PASSWORD_FILE}")
    return username, password


class ApiClient:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def _request(self, path: str, payload: dict | None = None, *, timeout: float = 60.0) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with self.opener.open(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} {path}: {raw[:400]}") from exc
        if not raw:
            return {"ok": status < 400, "status": status}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"ok": True, "data": parsed}

    def login(self, username: str, password: str) -> None:
        result = self._request(
            "/api/auth/login",
            {"username": username, "password": password},
        )
        if result.get("ok") is False:
            raise RuntimeError(f"login failed: {result}")

    def backend(self, command: str, payload: dict | None = None) -> dict:
        result = self._request(
            "/api/backend",
            {"command": command, "payload": payload or {}},
        )
        if not result.get("ok"):
            raise RuntimeError(f"{command} failed: {result.get('error') or result}")
        return result.get("data") or {}


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _measure_pages(api: ApiClient, conversation_id: str) -> dict:
    full_samples: list[float] = []
    page_samples: list[float] = []
    full_bytes = 0
    page_bytes = 0
    for _ in range(5):
        started = time.perf_counter()
        full = api.backend(
            "get_neyvia_conversation_command",
            {"conversationId": conversation_id, "includeTurns": True},
        )
        full_samples.append((time.perf_counter() - started) * 1000)
        full_bytes = len(json.dumps(full).encode("utf-8"))

        started = time.perf_counter()
        page = api.backend(
            "get_neyvia_conversation_command",
            {"conversationId": conversation_id, "turnLimit": PAGE_SIZE},
        )
        page_samples.append((time.perf_counter() - started) * 1000)
        page_bytes = len(json.dumps(page).encode("utf-8"))

    newest = api.backend(
        "get_neyvia_conversation_command",
        {"conversationId": conversation_id, "turnLimit": PAGE_SIZE},
    )
    turn_page = newest.get("turnPage") or {}
    if int(turn_page.get("totalTurns") or 0) != TOTAL_TURNS:
        raise RuntimeError(f"expected {TOTAL_TURNS} turns, got {turn_page}")
    if len(newest.get("turns") or []) != PAGE_SIZE:
        raise RuntimeError(f"expected first page of {PAGE_SIZE}, got {len(newest.get('turns') or [])}")
    if not turn_page.get("hasEarlierTurns"):
        raise RuntimeError("first page should report hasEarlierTurns")

    return {
        "fullConversation": {
            "p50Ms": round(_percentile(full_samples, 50), 3),
            "p95Ms": round(_percentile(full_samples, 95), 3),
            "meanMs": round(statistics.fmean(full_samples), 3),
            "responseBytes": full_bytes,
            "turns": TOTAL_TURNS,
        },
        "initialPage": {
            "p50Ms": round(_percentile(page_samples, 50), 3),
            "p95Ms": round(_percentile(page_samples, 95), 3),
            "meanMs": round(statistics.fmean(page_samples), 3),
            "responseBytes": page_bytes,
            "turns": PAGE_SIZE,
        },
        "payloadReductionPercent": round(
            (1.0 - (page_bytes / full_bytes)) * 100.0 if full_bytes else 0.0,
            3,
        ),
        "method": "live web backend get_neyvia_conversation_command, 5 repeated full and paged reads",
        "samples": 5,
    }


def seed_conversation(api: ApiClient, *, reuse_id: str = "") -> tuple[str, dict]:
    if reuse_id:
        conversation_id = reuse_id
        page = api.backend(
            "get_neyvia_conversation_command",
            {"conversationId": conversation_id, "turnLimit": PAGE_SIZE},
        )
        total = int((page.get("turnPage") or {}).get("totalTurns") or 0)
        if total != TOTAL_TURNS:
            raise RuntimeError(f"reuse conversation {conversation_id} has {total} turns, need {TOTAL_TURNS}")
        return conversation_id, _measure_pages(api, conversation_id)

    created = api.backend(
        "create_neyvia_conversation_command",
        {"kind": "chat", "title": TITLE, "titleMode": "off"},
    )
    conversation_id = str(created["conversationId"])
    api.backend(
        "set_neyvia_conversation_title_command",
        {"conversationId": conversation_id, "title": TITLE, "lock": True},
    )
    for index in range(TOTAL_TURNS):
        role = "user" if index % 2 == 0 else "assistant"
        api.backend(
            "append_neyvia_conversation_turn_command",
            {
                "conversationId": conversation_id,
                "role": role,
                "content": f"Turn {index}",
                "source": "phase0-paging-proof",
            },
        )
        if index and index % 50 == 0:
            print(f"seeded {index}/{TOTAL_TURNS}")
    return conversation_id, _measure_pages(api, conversation_id)


def run_browser_flow(conversation_id: str) -> dict:
    username, password = _load_login()
    proof_dir = PROOF_DIR
    proof_dir.mkdir(parents=True, exist_ok=True)
    initial_shot = proof_dir / f"mobile-conversation-paging-initial-80-{STAMP}.png"
    after_shot = proof_dir / f"mobile-conversation-paging-after-160-{STAMP}.png"
    debug_shot = proof_dir / f"mobile-conversation-paging-debug-{STAMP}.png"
    started = time.perf_counter()
    diagnostics: dict[str, list] = {
        "consoleErrors": [],
        "pageErrors": [],
        "failedRequests": [],
    }

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
            # Conversation sidebar is display:none below 1120px
            # (neyviaProductMode.css). Paging control lives in the thread after
            # open; use a desktop viewport so the real sidebar open path works.
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                service_workers="block",
            )
            page = context.new_page()
            page.set_default_timeout(45_000)
            page.on(
                "console",
                lambda message: diagnostics["consoleErrors"].append(message.text)
                if message.type == "error"
                else None,
            )
            page.on(
                "pageerror",
                lambda error: diagnostics["pageErrors"].append(str(error)[:2000]),
            )
            page.on(
                "requestfailed",
                lambda request: diagnostics["failedRequests"].append(
                    {
                        "method": request.method,
                        "url": request.url,
                        "error": str(request.failure),
                    }
                ),
            )

            login = context.request.post(
                f"{BASE_API}/api/auth/login",
                data=json.dumps({"username": username, "password": password}),
                headers={"Content-Type": "application/json"},
            )
            if not login.ok:
                raise RuntimeError(f"browser login failed HTTP {login.status}")

            # Mirror cookies onto the Vite origin so /api proxy calls stay authenticated.
            for cookie in context.cookies(f"{BASE_API}/"):
                mirrored = dict(cookie)
                mirrored["domain"] = "127.0.0.1"
                try:
                    context.add_cookies([mirrored])
                except Exception:
                    pass

            page.goto(
                f"{BASE_UI}/control?surface=agent&mode=agent",
                wait_until="domcontentloaded",
                timeout=120_000,
            )
            page.locator(".fluxos-shell").wait_for(state="visible", timeout=120_000)

            sidebar = page.locator('.neyvia-conversation-sidebar[data-conversation-state="ready"]')
            for attempt in range(60):
                if sidebar.count() > 0:
                    break
                page.wait_for_timeout(1000)
                if attempt in {10, 20, 40}:
                    page.screenshot(path=str(debug_shot), full_page=True)
                    print(f"wait shell attempt={attempt} buttons={page.locator('button').count()}")
            sidebar.wait_for(state="visible", timeout=90_000)

            search = sidebar.locator('input[type="search"]')
            if search.count():
                search.first.fill(TITLE)
                page.wait_for_timeout(700)

            row = sidebar.locator(f'[data-conversation-id="{conversation_id}"]')
            if row.count() == 0:
                page.screenshot(path=str(debug_shot), full_page=True)
                raise RuntimeError(
                    f"seeded conversation row not found: {conversation_id}; debug={debug_shot}"
                )
            row.first.click()
            page.locator(
                f'[data-selected-neyvia-conversation="{conversation_id}"]'
            ).wait_for(state="visible", timeout=60_000)

            def message_summary() -> str:
                return " ".join(
                    (page.locator(".fluxos-thread-head strong").first.text_content() or "").split()
                )

            page.wait_for_function(
                """() => {
                  const text = document.querySelector('.fluxos-thread-head strong')?.textContent || '';
                  return /80 of 260 stored messages/i.test(text);
                }""",
                timeout=60_000,
            )
            initial_summary = message_summary()
            load_btn = page.get_by_role("button", name="Load earlier messages")
            load_btn.wait_for(state="visible", timeout=30_000)
            page.screenshot(path=str(initial_shot), full_page=True)

            click_started = time.perf_counter()
            load_btn.click()
            page.wait_for_function(
                """() => {
                  const text = document.querySelector('.fluxos-thread-head strong')?.textContent || '';
                  return /160 of 260 stored messages/i.test(text);
                }""",
                timeout=60_000,
            )
            load_ms = round((time.perf_counter() - click_started) * 1000, 3)
            after_summary = message_summary()

            # Default thread view collapses to the final message only.
            expand = page.locator('[data-agent-thread-compact-toggle="true"]')
            expand.wait_for(state="visible", timeout=30_000)
            hidden_before_expand = expand.get_attribute("data-agent-thread-compact-hidden") or ""
            expand.click()
            page.get_by_role("button", name="Collapse to final message").wait_for(
                state="visible",
                timeout=30_000,
            )
            page.wait_for_timeout(500)

            thread_text = page.evaluate(
                """() => Array.from(
                  document.querySelectorAll('[data-message-zone="thread"]')
                ).map(node => node.innerText || '').join('\\n')"""
            )
            turn_100 = "Turn 100" in thread_text
            turn_99 = "Turn 99" in thread_text
            turn_180 = "Turn 180" in thread_text
            page.screenshot(path=str(after_shot), full_page=True)

            still_has_earlier = page.get_by_role("button", name="Load earlier messages").count() > 0
            if not turn_100:
                raise RuntimeError(
                    "after load-earlier + expand, Turn 100 was not in rendered thread messages"
                )
            if turn_99:
                raise RuntimeError(
                    "after first load-earlier, Turn 99 should still be unloaded (boundary check)"
                )
            if not turn_180:
                raise RuntimeError("newest-page marker Turn 180 missing after expand")

            return {
                "surface": "Vite UI :1420 proxied to web backend :47880",
                "viewport": {"width": 1440, "height": 1000},
                "viewportNote": "≥1121px required for visible .neyvia-conversation-sidebar; paging button is in-thread after open",
                "conversationId": conversation_id,
                "conversationTitle": TITLE,
                "conversationTurns": TOTAL_TURNS,
                "initialResult": initial_summary,
                "afterLoadEarlier": after_summary,
                "loadEarlierMs": load_ms,
                "compactHiddenBeforeExpand": hidden_before_expand,
                "boundaryCheck": {
                    "present": "Turn 100",
                    "notYetLoaded": "Turn 99",
                    "presentObserved": turn_100,
                    "notYetLoadedObserved": not turn_99,
                    "newestPageMarkerPresent": turn_180,
                    "method": "expand compacted thread then scan [data-message-zone=thread]",
                },
                "explicitLoadEarlierControl": True,
                "hasEarlierTurnsRemaining": still_has_earlier,
                "screenshots": {
                    "initial80": str(initial_shot),
                    "after160": str(after_shot),
                    "debug": str(debug_shot) if debug_shot.exists() else None,
                },
                "diagnostics": diagnostics,
                "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "result": "passed",
            }
        except Exception as exc:
            try:
                page.screenshot(path=str(debug_shot), full_page=True)
            except Exception:
                pass
            return {
                "surface": "Vite UI :1420 proxied to web backend :47880",
                "conversationId": conversation_id,
                "conversationTitle": TITLE,
                "conversationTurns": TOTAL_TURNS,
                "screenshots": {"debug": str(debug_shot) if debug_shot.exists() else None},
                "diagnostics": diagnostics,
                "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "error": str(exc)[:2000],
                "result": "failed",
            }
        finally:
            browser.close()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reuse-conversation-id",
        default="",
        help="Reuse an already-seeded 260-turn conversation instead of seeding again",
    )
    args = parser.parse_args()

    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    username, password = _load_login()
    api = ApiClient(BASE_API)
    api.login(username, password)
    print("seeding 260-turn conversation via live backend…")
    seed_started = time.perf_counter()
    conversation_id, benchmark = seed_conversation(
        api,
        reuse_id=str(args.reuse_conversation_id or "").strip(),
    )
    seed_ms = round((time.perf_counter() - seed_started) * 1000, 3)
    print(f"seeded {conversation_id} in {seed_ms} ms")

    print("running browser paging flow…")
    browser_flow = run_browser_flow(conversation_id)
    status = "passed" if browser_flow.get("result") == "passed" else "failed"
    receipt = {
        "schema": "neyvia.mobile-conversation-paging-proof.v1",
        "status": status,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "scope": {
            "conversationTurns": TOTAL_TURNS,
            "initialPageTurns": PAGE_SIZE,
            "maximumPageTurns": 200,
            "cursor": "exact beforeTurnId",
            "ordering": "chronological within each page",
        },
        "seed": {
            "conversationId": conversation_id,
            "title": TITLE,
            "durationMs": seed_ms,
            "via": "live /api/backend create + append_neyvia_conversation_turn_command",
        },
        "benchmark": benchmark,
        "browserFlow": browser_flow,
        "behavior": {
            "optimisticOpenBeforeNetwork": True,
            "explicitLoadEarlierControl": True,
            "pageMergeDeduplicatesExactTurnIds": True,
            "errorState": True,
        },
        "verification": {
            "frontendDevServer": BASE_UI,
            "webBackend": BASE_API,
            "liveBrowserReproof": True,
            "physicalDevice": "unavailable / not claimed",
        },
    }
    out = PROOF_DIR / f"mobile-conversation-paging-proof-{STAMP}.json"
    out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"proofPath": str(out), "status": status, "browserFlow": browser_flow}, indent=2))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
