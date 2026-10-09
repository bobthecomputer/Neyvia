"""Usage pane proof: headless Playwright Chromium on a fixtures Vite build, the endpoint answered with this PC's real report.

python scripts/usage_shots.py --dist D:/NeyviaRuns/29-USAGE/dist --out D:/NeyviaRuns/29-USAGE/shots [--themes dark,light] [--port 49271]

The /api/ui/usage reply is the real grant_agent.usage_report output (no chat titles in it: only model names and counts).
Only real numbers here; the injected film mock lives in usage_film_shot.py.
Nothing is shown on screen (headless). Writes <out>/<variant>-<theme>-<width>.png and receipt.json.
"""
from __future__ import annotations

import argparse
import copy
import functools
import http.server
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
THEMES = ["dark", "light", "sunset", "night", "terminal", "paper", "ember"]
VIEWPORTS = {"1920": {"width": 1920, "height": 1080}, "390": {"width": 390, "height": 844}}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.translate_path(self.path.split("?")[0])
        if not os.path.exists(path) or os.path.isdir(path) and not os.path.exists(os.path.join(path, "index.html")):
            self.path = "/index.html"
        return super().do_GET()


def real_reports(root):
    from grant_agent import usage_report as u
    u.report(root, "week")
    while u._state["thread"].is_alive():
        time.sleep(1)
    return {name: u.report(root, name) for name in ("day", "week", "month")}


def empty(report):
    out = copy.deepcopy(report)
    out.update(plans=[], rows=[], totals={"input": 0, "cached": 0, "output": 0, "cacheShare": None})
    out["byDay"] = [{"day": d["day"], "agents": {}} for d in out["byDay"]]
    out["savings"].update(cacheShare=None, cachedTokens=0, apiEquivalentSavedUsd=None, billedSavedUsd=None)
    out["cost"].update(apiEquivalentTotalUsd=None, apiEquivalentParts=None, billedTotalUsd=None, apiRows=0, pricedShare=None, unpricedModels=[])
    return out


def scanning(report):
    out = empty(report)
    out["scan"] = {"active": True, "done": 312, "total": 1143, "builtAt": None}
    return out


def main():
    from playwright.sync_api import sync_playwright
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", default=r"C:\Users\user\Projects\Neyvia")
    parser.add_argument("--themes", default=",".join(THEMES))
    parser.add_argument("--variants", default="real,empty,scanning,month,day")
    parser.add_argument("--viewports", default="1920,390")
    parser.add_argument("--port", type=int, default=49271)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    reports = real_reports(args.root)
    (out / "real-report.json").write_text(json.dumps(reports["week"], indent=1), encoding="utf-8")
    sets = {"real": reports["week"], "empty": empty(reports["week"]), "scanning": scanning(reports["week"]), "month": reports["month"], "day": reports["day"]}
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), functools.partial(Quiet, directory=args.dist))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{args.port}"
    receipt = {"shots": [], "errors": []}

    def answer(route, variant):
        url = route.request.url
        want = "day" if "range=day" in url else "month" if "range=month" in url else "week"
        report = reports[want] if variant == "real" else sets[variant]
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "data": report}))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for variant in args.variants.split(","):
            for theme in args.themes.split(","):
                for width in args.viewports.split(","):
                    if variant in ("empty", "scanning", "month", "day") and theme not in ("dark", "light"):
                        continue
                    if width == "390" and theme not in ("dark", "light", "terminal", "paper"):
                        continue
                    ctx = browser.new_context(viewport=VIEWPORTS[width], device_scale_factor=2)
                    page = ctx.new_page()
                    page.on("pageerror", lambda e: receipt["errors"].append(str(e)[:300]))
                    page.route("**/api/ui/usage*", lambda route, _request=None, variant=variant: answer(route, variant))
                    ctx.add_init_script("localStorage.setItem('nx.os.theme', JSON.stringify(" + json.dumps(theme) + "))")
                    page.goto(origin + "/control?preview-control=1&fixtures=1&bus=mock&busscript=0&ui=next", wait_until="load")
                    page.wait_for_function("() => window.__nxOs", timeout=60000)
                    page.evaluate("() => window.__nxOs.showPane('usage', '')")
                    page.wait_for_selector(".nx-us-head", timeout=30000)
                    if variant != "scanning":
                        page.wait_for_selector(".nx-us-tiles", timeout=30000)
                    if variant in ("month", "day"):
                        page.click(f".nx-seg button:has-text('{variant.capitalize()}')")
                    time.sleep(1.2)
                    seen = page.evaluate("() => [document.querySelector('.nx-root')?.getAttribute('data-nx-theme'), document.documentElement.scrollWidth <= window.innerWidth + 1, (document.querySelector('.nx-us')?.scrollWidth ?? 0) <= (document.querySelector('.nx-us')?.clientWidth ?? 0) + 1]")
                    name = f"{variant}-{theme}-{width}.png"
                    page.screenshot(path=str(out / name))
                    full_h = page.evaluate("() => document.querySelector('.nx-us')?.scrollHeight || 0")
                    if full_h and full_h > VIEWPORTS[width]["height"] - 80 and variant == "real":
                        page.set_viewport_size({"width": VIEWPORTS[width]["width"], "height": min(full_h + 140, 3200)})
                        time.sleep(0.8)
                        page.screenshot(path=str(out / f"full-{name}"))
                    receipt["shots"].append({"file": name, "renderedTheme": seen[0], "pageNoHScroll": seen[1], "paneNoHScroll": seen[2]})
                    ctx.close()
        browser.close()
    server.shutdown()
    (out / "receipt.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    mismatch = [s["file"] for s in receipt["shots"] if s["renderedTheme"] != s["file"].split("-")[1]]
    hscroll = [s["file"] for s in receipt["shots"] if not (s["pageNoHScroll"] and s["paneNoHScroll"])]
    print(json.dumps({"shots": len(receipt["shots"]), "errors": receipt["errors"][:5], "themeMismatch": mismatch[:10], "horizontalScroll": hscroll[:10]}, indent=1))


if __name__ == "__main__":
    main()
