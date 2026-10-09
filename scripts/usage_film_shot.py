"""Trailer captures of the Usage pane, full screen (no sidebar, so no chat titles), Forest dark, 1920x1080 at device scale 2.

python scripts/usage_film_shot.py --dist D:/NeyviaRuns/29-USAGE/dist --out D:/NeyviaRuns/29-USAGE/shots [--mode real|mock|both]

real  Only real numbers: the Claude Code plan-window store the mod filled (scripts/evidence/MODREAL-plan-limits-store.json, copied
      unchanged into a scratch root so the live store is never touched), the real Codex window, and the real token history
      under ~/.claude, ~/.codex and OpenCode's database. Files: film-real-*.png.
mock  INJECTED data for the film, for when not every provider is connected: the real history plus OpenCode (Go plan, OpenAI login,
      MiniMax plan), DeepSeek and Anthropic keys, an OpenRouter key row, and Claude Code at 41 % / 63 %. The numbers are invented
      but sized like this PC's real ones and priced with the real price table through the product's own report code, so the
      contract check passes. The injected data lives only in this script; it never ships in the product. Files: film-mock-*.png.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import random
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from usage_shots import Quiet  # noqa: E402

FULL = ".nx-stage { position: fixed !important; inset: 0 !important; z-index: 99999 !important; width: auto !important; height: auto !important; max-width: none !important; }"

# agent, provider, model, billing, mean input tokens per weekday, cache share, output share of input, cache-write share of input
INJECTED = [
    ("opencode", "opencode-go", "deepseek-v4-pro", "plan", 62_000_000, 0.92, 0.009, 0.0),
    ("opencode", "opencode-go", "kimi-k3", "plan", 36_000_000, 0.88, 0.011, 0.0),
    ("opencode", "opencode-go", "glm-5.2", "plan", 21_000_000, 0.90, 0.010, 0.0),
    ("opencode", "minimax-coding-plan", "MiniMax-M2.5", "plan", 26_000_000, 0.93, 0.012, 0.05),
    ("opencode", "openai", "gpt-5.5", "plan", 44_000_000, 0.95, 0.006, 0.0),
    ("opencode", "openrouter", "~anthropic/claude-fable-latest", "api", 6_500_000, 0.80, 0.015, 0.06),
    ("neyvia-agent", "deepseek", "deepseek-v4.1-flash", "api", 19_000_000, 0.72, 0.012, 0.0),
    ("neyvia-agent", "anthropic", "claude-sonnet-5-5", "api", 9_500_000, 0.85, 0.014, 0.07),
    ("neyvia-agent", "opencode-go", "deepseek-v4.1-flash", "plan", 31_000_000, 0.9, 0.01, 0.0),
]


def mock_report(real_totals, range_name):
    from grant_agent import usage_report as u
    rng = random.Random(8)
    totals = {key: list(value) for key, value in real_totals.items()}
    today = datetime.now().astimezone().date()
    for back in range(u.WINDOW_DAYS):
        day = today - timedelta(days=back)
        weekday = 1.0 if day.weekday() < 5 else 0.45
        for agent, provider, model, billing, mean, cache, out, write in INJECTED:
            inp = int(mean * weekday * rng.uniform(0.6, 1.4))
            cell = totals.setdefault((day.isoformat(), provider, agent, model, billing), [0, 0, 0, 0, 0])
            cell[0] += inp
            cell[1] += int(inp * cache)
            cell[2] += int(inp * out)
            cell[3] += int(inp * write)
    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    plans = [
        {"app": "claude-code", "window": "five_hour", "label": "5-hour", "usedPercent": 41.0, "resetsAt": (now + timedelta(hours=2, minutes=10)).isoformat(timespec="seconds"), "source": "claude-mod", "status": "allowed", "stale": False, "availability": "ready", "at": stamp, "resetPassed": False},
        {"app": "claude-code", "window": "seven_day", "label": "Weekly", "usedPercent": 63.0, "resetsAt": (now + timedelta(days=2, hours=7)).isoformat(timespec="seconds"), "source": "claude-mod", "status": "allowed", "stale": False, "availability": "ready", "at": stamp, "resetPassed": False},
        {"app": "codex", "window": "weekly", "label": "Weekly", "usedPercent": 54.0, "resetsAt": "2026-10-14T03:29:06Z", "source": "codex-rollout", "status": None, "stale": False, "availability": None, "at": stamp, "resetPassed": False},
    ]
    return u.assemble(totals, plans, [], range_name, {"active": False, "done": 1, "total": 1}, time.time())


def capture(report_for, out, prefix, dist, port):
    from playwright.sync_api import sync_playwright
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=dist))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{port}"
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=2, locale="en-GB")
        ctx.add_init_script("localStorage.setItem('nx.os.theme', JSON.stringify('dark'))")
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)[:300]))

        def answer(route, _request=None):
            url = route.request.url
            want = "day" if "range=day" in url else "month" if "range=month" in url else "week"
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "data": report_for(want)}))

        page.route("**/api/ui/usage*", answer)
        page.goto(origin + "/control?preview-control=1&fixtures=1&bus=mock&busscript=0&ui=next", wait_until="load")
        page.wait_for_function("() => window.__nxOs", timeout=60000)
        page.evaluate("() => window.__nxOs.showPane('usage', '')")
        page.wait_for_selector(".nx-us-tiles", timeout=30000)
        page.add_style_tag(content=FULL)
        time.sleep(1.2)
        page.screenshot(path=str(out / f"{prefix}-1.png"))
        page.click(".nx-seg button:has-text('With cache reads')")
        time.sleep(1.0)
        page.screenshot(path=str(out / f"{prefix}-2-with-cache-reads.png"))
        page.click(".nx-seg button:has-text('New tokens')")
        page.evaluate("() => document.querySelector('.nx-us').scrollTo(0, 99999)")
        time.sleep(0.8)
        page.screenshot(path=str(out / f"{prefix}-3-lower.png"))
        browser.close()
    server.shutdown()
    return errors


def main():
    from grant_agent import usage_report as u
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", default="both", choices=["real", "mock", "both"])
    parser.add_argument("--scratch", default=r"D:\NeyviaRuns\29-USAGE\film-root")
    parser.add_argument("--port", type=int, default=49272)
    args = parser.parse_args()
    scratch = Path(args.scratch)
    (scratch / ".neyvia").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "scripts" / "evidence" / "MODREAL-plan-limits-store.json", scratch / ".neyvia" / "plan-limits.json")
    u.report(scratch, "week")
    while u._state["thread"].is_alive():
        time.sleep(1)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    if args.mode in ("real", "both"):
        reports = {name: u.report(scratch, name) for name in ("day", "week", "month")}
        (out / "film-real-report.json").write_text(json.dumps(reports["week"], indent=1), encoding="utf-8")
        result["real"] = capture(lambda name: reports[name], out, "film-real", args.dist, args.port)
        result["realPlans"] = [(p["app"], p["window"], p["usedPercent"], p["stale"]) for p in reports["week"]["plans"]]
        result["realCost"] = {k: reports["week"]["cost"][k] for k in ("apiEquivalentTotalUsd", "billedTotalUsd", "pricedShare")}
    if args.mode in ("mock", "both"):
        real_totals = dict(u._state["totals"])
        reports = {name: mock_report(real_totals, name) for name in ("day", "week", "month")}
        (out / "film-mock-report.json").write_text(json.dumps(reports["week"], indent=1), encoding="utf-8")
        result["mock"] = capture(lambda name: reports[name], out, "film-mock", args.dist, args.port)
        result["mockCost"] = {k: reports["week"]["cost"][k] for k in ("apiEquivalentTotalUsd", "billedTotalUsd", "pricedShare")}
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
