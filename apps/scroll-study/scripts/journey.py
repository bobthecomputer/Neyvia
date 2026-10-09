"""User-path proof for the Scroll Study prototype.

Walks the feed like a person would (drags, taps, swipes, keys) in a phone viewport, light
and dark, saves one screenshot per card type and moment, then opens the same app inside
Neyvia's Mobile Studio phone frame. Reads app state only through window.scrollStudy (the
two-sided state API) to know what is on screen; answers through the UI.

    python apps/scroll-study/scripts/journey.py --vite http://127.0.0.1:1771 --out proof/a3-scroll-study
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WWW = ROOT / "www"


def app_url(vite: str) -> str:
    return vite.rstrip("/") + "/@fs/" + WWW.joinpath("index.html").as_posix()


def drag(page, x0, y0, x1, y1, steps=12):
    page.mouse.move(x0, y0)
    page.mouse.down()
    for k in range(1, steps + 1):
        page.mouse.move(x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps)
        time.sleep(0.012)
    page.mouse.up()


def state(page):
    return page.evaluate("window.scrollStudy.state()")


def next_card(page, how="drag"):
    w, h = page.viewport_size["width"], page.viewport_size["height"]
    if how == "drag":
        drag(page, w / 2, h * 0.75, w / 2, h * 0.3)
    else:
        page.keyboard.press("ArrowDown")
    page.wait_for_timeout(450)


def answer(page, rng, accuracy=0.8):
    """Answer the current graded card through the UI. Returns (type, right?)."""
    st = state(page)
    card = st["card"]
    kind = card["type"]
    sel = f'.ss-page[aria-hidden="false"]'
    right = rng.random() < accuracy
    w, h = page.viewport_size["width"], page.viewport_size["height"]
    if kind == "truefalse":
        truth = page.evaluate("window.scrollStudy.correct()")
        choice = truth if right else (not truth)
        # swipe the statement sideways, the way the thumb does it
        box = page.locator(f"{sel} [data-swipe]").bounding_box()
        y = box["y"] + box["height"] / 2
        drag(page, w / 2, y, w / 2 + (150 if choice else -150), y)
    elif kind == "mcq":
        options = page.locator(f"{sel} [data-option]")
        idx = page.evaluate("(() => { const c = window.scrollStudy.state().card; return null; })()")
        correct = page.evaluate("""(() => { const p = document.querySelector('.ss-page[aria-hidden="false"]');
            const id = p.querySelector('[data-card]').getAttribute('data-card');
            const card = window.SS_PACK.cards.find(c => c.id === id);
            return card.options.findIndex(o => o.correct); })()""")
        target = correct if right else next(k for k in range(options.count()) if k != correct)
        page.locator(f'{sel} [data-option="{target}"]').click()
    elif kind in ("flashcard", "why", "cloze"):
        page.locator(f"{sel} [data-reveal]").click()
        page.wait_for_timeout(250)
        box = page.locator(f"{sel} [data-swipe]").bounding_box()
        y = box["y"] + box["height"] / 2
        drag(page, w / 2, y, w / 2 + (150 if right else -150), y)
    elif kind == "order":
        n = page.locator(f"{sel} [data-item]").count()
        order = list(range(n)) if right else [1, 0] + list(range(2, n))
        for k in order:
            page.locator(f'{sel} [data-item="{k}"]').click()
    elif kind == "spot":
        wrong = page.evaluate("""(() => { const p = document.querySelector('.ss-page[aria-hidden="false"]');
            const id = p.querySelector('[data-card]').getAttribute('data-card');
            return window.SS_PACK.cards.find(c => c.id === id).wrong; })()""")
        page.locator(f'{sel} [data-line="{wrong if right else 0}"]').click()
    page.wait_for_timeout(350)
    return kind, state(page)["card"]["result"]


def walk(page, out: Path, tag: str, rng, shots: dict, limit=60):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(app_url(args.vite))
    page.wait_for_selector(".ss-page")
    page.wait_for_timeout(400)
    page.screenshot(path=str(out / f"{tag}-00-start.png"))
    trail = []
    for step in range(limit):
        next_card(page, "drag" if step % 3 else "key")
        st = state(page)
        card = st["card"]
        kind = card["type"]
        if kind in ("fact", "explainer", "recap"):
            page.wait_for_timeout(4300)  # honest exposure: stay until it counts as seen
            if kind not in shots:
                shots[kind] = 1
                page.screenshot(path=str(out / f"{tag}-{kind}.png"))
        elif kind == "worked":
            if "worked" not in shots:
                page.screenshot(path=str(out / f"{tag}-worked-step1.png"))
            for _ in range(6):
                if not page.locator('.ss-page[aria-hidden="false"] [data-next-step]:visible').count():
                    break
                w, h = page.viewport_size["width"], page.viewport_size["height"]
                drag(page, w * 0.8, h * 0.45, w * 0.2, h * 0.45)  # swipe left = next step
                page.wait_for_timeout(250)
            why = page.locator('.ss-page[aria-hidden="false"] [data-step-why]')
            if why.count():
                why.first.click()
            if "worked" not in shots:
                shots["worked"] = 1
                page.screenshot(path=str(out / f"{tag}-worked-done.png"))
        elif kind in ("reward",):
            page.wait_for_timeout(500)
            page.screenshot(path=str(out / f"{tag}-reward.png"))
        elif kind == "goal":
            page.wait_for_timeout(500)
            page.screenshot(path=str(out / f"{tag}-goal.png"))
            trail.append(("goal", st["done"]))
            page.locator('.ss-page[aria-hidden="false"] [data-finish]').click()
            page.wait_for_timeout(600)
            page.screenshot(path=str(out / f"{tag}-end.png"))
            break
        elif kind == "end":
            break
        else:
            if kind not in shots:
                page.screenshot(path=str(out / f"{tag}-{kind}-question.png"))
            k, result = answer(page, rng)
            key = f"{kind}-{result}"
            if key not in shots:
                shots[key] = 1
                page.screenshot(path=str(out / f"{tag}-{kind}-{result}.png"))
            shots[kind] = 1
        trail.append((card["id"], kind, state(page)["card"]["result"]))
    # menu -> live goal checks
    page.locator("#menu").click()
    page.locator('[data-menu="checks"]').click()
    page.wait_for_timeout(400)
    page.screenshot(path=str(out / f"{tag}-checks.png"))
    checks = page.evaluate("window.scrollStudy.checks()")
    page.keyboard.press("Escape")
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    return {"trail": trail, "checks": checks, "consoleErrors": errors, "horizontalOverflowPx": overflow, "final": state(page)}


def mobile_studio(browser, out: Path):
    """Neyvia UI on 127.0.0.1 (loopback local session), Mobile Studio opened by a bot call."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="dark")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    base = args.vite.rstrip("/")
    page.goto(base + "/control")
    page.request.post(base + "/api/auth/local-session", data="{}", headers={"Content-Type": "application/json"})
    project = str(ROOT)
    page.request.post(base + "/api/ui/tools/call", data=json.dumps({"tool": "neyvia.mobile.preview", "arguments": {"project": project, "device": "iphone-16", "dark": True}}),
                      headers={"Content-Type": "application/json"})
    page.goto(base + "/control")
    page.wait_for_timeout(6000)
    skip = page.get_by_role("button", name="Skip setup")
    if skip.count():
        skip.first.click()
        page.wait_for_timeout(800)
    page.request.post(base + "/api/ui/tools/call", data=json.dumps({"tool": "neyvia.app.open", "arguments": {"app": "mobile-studio"}}),
                      headers={"Content-Type": "application/json"})
    page.wait_for_selector('iframe[title="Your app on the phone"]', timeout=20000)
    frame = page.frame_locator('iframe[title="Your app on the phone"]')
    frame.locator(".ss-page").first.wait_for(timeout=20000)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(out / "studio-01-start.png"))
    box = page.locator('iframe[title="Your app on the phone"]').bounding_box()
    # drag inside the phone: the preview helper turns it into touch, the feed pages
    drag(page, box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.75, box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.3)
    page.wait_for_timeout(5000)
    drag(page, box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.75, box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.3)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(out / "studio-02-card.png"))
    inner = page.frames[-1]
    st = None
    for f in page.frames:
        try:
            st = f.evaluate("window.scrollStudy && window.scrollStudy.state()")
            if st:
                break
        except Exception:
            continue
    ctx.close()
    return {"state": st, "pageErrors": errors}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vite", default="http://127.0.0.1:1771")
    ap.add_argument("--out", default=str(ROOT.parents[1] / "proof" / "a3-scroll-study"))
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for scheme in ("dark", "light"):
            ctx = browser.new_context(viewport={"width": 393, "height": 852}, device_scale_factor=2, color_scheme=scheme, has_touch=False)
            page = ctx.new_page()
            report[scheme] = walk(page, out, scheme, random.Random(args.seed), {})
            ctx.close()
        ctx = browser.new_context(viewport={"width": 393, "height": 852}, color_scheme="dark", reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(app_url(args.vite))
        page.wait_for_selector(".ss-page")
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(200)
        report["reducedMotion"] = {"index": state(page)["index"], "transition": page.evaluate("getComputedStyle(document.getElementById('track')).transitionDuration")}
        ctx.close()
        try:
            report["mobileStudio"] = mobile_studio(browser, out)
        except Exception as error:  # report, don't hide
            report["mobileStudio"] = {"error": str(error)}
        browser.close()
    (out / "journey.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    for scheme in ("dark", "light"):
        r = report[scheme]
        print(scheme, "cards", len(r["trail"]), "errors", len(r["consoleErrors"]), "overflow", r["horizontalOverflowPx"],
              "checks", " ".join(c["id"] + ("ok" if c["ok"] else "FAIL") for c in r["checks"]))
    print("reduced", report["reducedMotion"])
    ms = report["mobileStudio"]
    print("studio", ms.get("error") or (ms.get("state") or {}).get("card"), ms.get("pageErrors"))
