"""Prove Neyvia's details library (plan 17 A2) on the running design lab.

Usage: python scripts/prove_details.py --url http://a2-details.localhost:1761 [--out proof/a2-details]
       python scripts/prove_details.py --request .agent_control/details/request.json

Opens each details specimen in headless Chrome (the same driver as the design-craft
runner), saves light/dark x desktop/phone screenshots and drives every detail the way a
person would: rolls numbers both ways, starts and finishes a task, asks and keeps/deletes
in place, copies (with a working and a refused clipboard), loads quickly and slowly,
ticks a task, and repeats a roll with reduced motion. Then the same details where Neyvia
uses them (checklist, status strip, chat copy, chat loading, Arrange scenes; dev fixtures and
the mock bus, no account) and the framework-free kit generated apps get (kit/demo.html). Writes report.json; exit 1 if any
probe failed. The design manual's `details` chapter runs this through terminal.exec.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.chromium_review import chromium_review_page  # noqa: E402

SPECIMENS = ("details-numbers", "details-actions", "details-states")
VIEWPORTS = {"desktop": (1280, 900), "phone": (390, 844)}

CLICK = """(label) => { const b = [...document.querySelectorAll('button')].find(x => (x.getAttribute('aria-label') || x.textContent).trim() === label);
  if (!b) return false; b.click(); return true; }"""
WHEEL = """() => [...document.querySelectorAll('.nx-dl-figure .nx-roll-strip')].map(s => ({ p: Number(s.style.getPropertyValue('--nx-roll-p')),
  y: new DOMMatrix(getComputedStyle(s).transform).m42, h: parseFloat(getComputedStyle(s).lineHeight) }))"""


def call(page, fn: str, *args):
    return page.evaluate(f"({fn})({', '.join(json.dumps(a) for a in args)})")


def probe_numbers(page, checks):
    call(page, CLICK, "Add 27")  # 98 -> 125: a new hundreds wheel, tens 9->2 and ones 8->5 roll forward
    page.wait_for_timeout(90)
    mid = page.evaluate(WHEEL)
    page.wait_for_timeout(700)
    end = page.evaluate(WHEEL)
    said = page.evaluate("document.querySelector('.nx-dl-figure .nx-visually-hidden').textContent")
    moving = any(abs(m["y"] + m["p"] * m["h"]) > 1 for m in mid[1:])
    checks["roll-reads-whole-number"] = said == "125"
    checks["roll-animates"] = moving
    checks["roll-rests-in-middle-band"] = all(10 <= c["p"] < 20 for c in end)
    checks["roll-lands"] = all(abs(c["y"] + c["p"] * c["h"]) < 0.5 for c in end)
    before = page.evaluate(WHEEL)
    call(page, CLICK, "Take 1")  # 125 -> 124: the ones wheel steps back one face, not forward nine
    page.wait_for_timeout(30)
    after = page.evaluate(WHEEL)
    checks["roll-short-way-down"] = after[-1]["p"] == before[-1]["p"] - 1
    page.wait_for_timeout(600)
    # Meter: estimated task creeps, stays under 90 %, then fills on Finish.
    call(page, CLICK, "Start a task")
    page.wait_for_timeout(1600)
    meter = "() => { const m = document.querySelector('[aria-label=\"Task progress\"]'); return { text: m.getAttribute('aria-valuetext'), now: m.getAttribute('aria-valuenow'), scale: new DOMMatrix(getComputedStyle(m.firstChild).transform).a }; }"
    running = page.evaluate(meter)
    checks["meter-creeps"] = running["text"] == "In progress" and 0.15 < running["scale"] < 0.9
    call(page, CLICK, "Finish")
    page.wait_for_timeout(600)
    finished = page.evaluate(meter)
    checks["meter-finishes"] = finished["now"] == "100" and finished["scale"] > 0.99
    return {"mid": mid, "end": end, "meterRunning": running, "meterFinished": finished}


def probe_actions(page, checks):
    open_state = page.evaluate("() => ({ group: document.querySelector('.nx-confirm')?.getAttribute('aria-label'), focus: document.activeElement?.textContent })")
    checks["confirm-focuses-keep"] = open_state == {"group": "Delete Focus?", "focus": "Keep"}
    page.evaluate("document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))")
    page.wait_for_timeout(120)
    kept = page.evaluate("() => ({ open: Boolean(document.querySelector('.nx-confirm')), focus: document.activeElement?.getAttribute('aria-label') })")
    checks["confirm-escape-keeps-and-refocuses"] = kept == {"open": False, "focus": "Delete Focus"}
    call(page, CLICK, "Delete Two chats")
    page.wait_for_timeout(120)
    call(page, CLICK, "Delete")
    page.wait_for_timeout(200)
    gone = page.evaluate("() => ({ chips: [...document.querySelectorAll('.nx-dl-chip > span:first-child')].map(x => x.textContent), said: (globalThis.__nxAnnounced || []).map(x => x.text) })")
    checks["confirm-deletes-and-announces"] = gone["chips"] == ["Reading", "Focus"] and "Two chats deleted" in gone["said"]
    # Copy: a working clipboard, then a refused one.
    page.evaluate("navigator.clipboard.writeText = async text => { window.__copied = text; }")
    call(page, CLICK, "Copy path")
    page.wait_for_timeout(260)
    done = page.evaluate("() => { const b = document.querySelector('[aria-label=\"Copy path\"]'); return { cls: b.className, title: b.title, copied: window.__copied, clip: getComputedStyle(b.querySelector('.nx-copybtn-check')).clipPath }; }")
    checks["copy-shows-done"] = "is-done" in done["cls"] and done["title"] == "Copied" and done["copied"] == "C:\\Users\\user\\Projects\\Neyvia"
    page.evaluate("navigator.clipboard.writeText = async () => { throw new Error('denied'); }")
    call(page, CLICK, "Copy")
    page.wait_for_timeout(120)
    failed = page.evaluate("() => { const b = [...document.querySelectorAll('.nx-copybtn')].find(x => x.querySelector('.nx-copybtn-label')); return { cls: b.className, label: b.querySelector('.nx-copybtn-label').textContent }; }")
    checks["copy-says-when-it-failed"] = "is-failed" in failed["cls"] and failed["label"] == "Copy failed"
    page.wait_for_timeout(1700)
    checks["copy-resets"] = "is-idle" in page.evaluate("document.querySelector('[aria-label=\"Copy path\"]').className")
    return {"open": open_state, "kept": kept, "gone": gone, "copy": done, "copyFailed": failed}


def probe_states(page, checks):
    skeleton = "Boolean(document.querySelector('.nx-dl-skeleton'))"
    call(page, CLICK, "Load quickly")
    page.wait_for_timeout(100)
    quick_mid = page.evaluate(skeleton)
    page.wait_for_timeout(400)
    checks["calm-skips-short-wait"] = quick_mid is False and page.evaluate(skeleton) is False
    call(page, CLICK, "Load slowly")
    page.wait_for_timeout(120)
    early = page.evaluate(skeleton)
    page.wait_for_timeout(400)
    shown = page.evaluate(skeleton)
    page.wait_for_timeout(1700)
    checks["calm-shows-long-wait"] = early is False and shown is True and page.evaluate(skeleton) is False
    page.evaluate("document.querySelectorAll('.nx-dl-tasks input')[1].click()")
    page.wait_for_timeout(110)
    size = "parseFloat(getComputedStyle(document.querySelectorAll('.nx-strike')[1]).backgroundSize)"
    mid = page.evaluate(size)
    page.wait_for_timeout(500)
    checks["strike-draws"] = 0 < mid < 100 and page.evaluate(size) == 100
    call(page, CLICK, "Clear the search")
    page.wait_for_timeout(100)
    checks["empty-action-works"] = page.evaluate("document.body.textContent.includes('Showing every chat.')")
    return {"strikeMid": mid}


def probe_reduced(page, checks):
    page._send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
    page.wait_for_timeout(100)
    call(page, CLICK, "Add 1")
    page.wait_for_timeout(40)
    wheel = page.evaluate(WHEEL)
    checks["reduced-motion-cuts"] = all(abs(c["y"] + c["p"] * c["h"]) < 0.5 or 10 <= c["p"] < 20 for c in wheel)
    return {"wheel": wheel}


SHELL = "/control?preview-control=1&fixtures=1&bus=mock&busscript=0&chat=s-claude-live"


def probe_shell(page, checks, out: Path, theme: str):
    """The details where Neyvia uses them: checklist, status strip, chat copy, chat loading, Arrange scenes."""
    page.evaluate(f"document.querySelector('.nx-root')?.setAttribute('data-nx-theme', {json.dumps(theme)})")
    found: dict[str, object] = {}
    # 1. Checklist: the count rolls, done steps are struck.
    found["checklist"] = page.evaluate("() => ({ roll: Boolean(document.querySelector('.nx-checklist-count .nx-roll')), text: document.querySelector('.nx-checklist-count').textContent })")
    page.evaluate("document.querySelector('.nx-checklist-head').click()")
    page.wait_for_timeout(400)
    struck = page.evaluate("[...document.querySelectorAll('.nx-checklist-item .nx-strike.is-on')].map(x => x.textContent)")
    checks[f"shell-checklist-{theme}"] = found["checklist"]["roll"] and found["checklist"]["text"] == "1 of 3" and struck == ["Read the plan"]
    # 2. Status strip: Night Shift count rolls and its meter fills; Usage gets a real progressbar.
    page.evaluate("""__nxBus.emit('nightshift.task.updated', { id: 'N1', status: 'done', title: 'Index the notes' });
      __nxBus.emit('nightshift.task.updated', { id: 'N2', status: 'running', title: 'Check the links' });
      __nxBus.emit('indicator.updated', { key: 'usage', label: 'Codex', used: 41, limit: 100, unit: '%' });""")
    page.wait_for_timeout(700)
    strip = ("() => { const m = [...document.querySelectorAll('.nx-strip .nx-meter')]; return { meters: m.map(x => ({ role: x.getAttribute('role'), "
             "now: x.getAttribute('aria-valuenow'), scale: Math.round(new DOMMatrix(getComputedStyle(x.firstChild).transform).a * 100) / 100, cls: x.className })), "
             "text: document.querySelector('.nx-strip').textContent }; }")
    before = page.evaluate(strip)
    page.evaluate("__nxBus.emit('nightshift.task.updated', { id: 'N2', status: 'done', title: 'Check the links' })")
    page.wait_for_timeout(700)
    after = page.evaluate(strip)
    found["strip"] = {"before": before, "after": after}
    checks[f"shell-strip-{theme}"] = bool(
        "Night Shift 1/2" in before["text"] and "Night Shift 2/2" in after["text"]
        and before["meters"] and before["meters"][0]["scale"] == 0.5 and after["meters"][0]["scale"] == 1
        and any(m["role"] == "progressbar" and m["now"] == "41" for m in after["meters"]))
    page.screenshot(path=str(out / f"shell-checklist-strip-{theme}.png"))
    # 3. Chat copy: the tool output copy shows its check.
    page.evaluate("navigator.clipboard.writeText = async text => { window.__copied = text; }")
    page.evaluate("[...document.querySelectorAll('.nx-copy')][0].click()")
    page.wait_for_timeout(260)
    copied = page.evaluate("() => { const b = document.querySelector('.nx-copy'); return { cls: b.className, copied: typeof window.__copied === 'string' }; }")
    found["copy"] = copied
    checks[f"shell-copy-{theme}"] = "is-done" in copied["cls"] and "nx-copybtn" in copied["cls"] and copied["copied"]
    # 4. Calm loading: switching to a chat that loads in ~120 ms never shows the skeleton.
    # The skeleton may show only when the wait passed 240 ms; record both and check they agree.
    page.evaluate("""window.__sk = null; window.__busy = null; window.__busyAt = null; const t0 = performance.now();
      const watch = new MutationObserver(() => {
        if (window.__sk == null && document.querySelector('.nx-thread-skeleton')) window.__sk = performance.now() - t0;
        if (window.__busyAt == null && document.querySelector('.nx-thread-state[aria-busy]')) window.__busyAt = performance.now() - t0;
        if (window.__busyAt != null && window.__busy == null && !document.querySelector('.nx-thread-state[aria-busy]')) window.__busy = performance.now() - t0;
      });
      watch.observe(document.body, { subtree: true, childList: true });
      [...document.querySelectorAll('button')].find(b => b.textContent.startsWith('Improve step-5'))?.click();""")
    page.wait_for_timeout(1500)
    calm = page.evaluate("() => ({ loadingAt: window.__busyAt, skeletonAt: window.__sk, loadedAt: window.__busy, ready: Boolean(document.querySelector('.nx-thread-col')) })")
    found["calm"] = calm
    # Times are from the click (observer callbacks run late, after long tasks, so "loading started"
    # is only known to be after the click). The skeleton may never show within 240 ms of the click;
    # whether it shows later depends on how long the chat takes to render. The lab specimen proves
    # the exact timing on both sides (150 ms: never; 1.8 s: after 240 ms).
    found["calmMs"] = {"loadedAfterClick": calm["loadedAt"] and round(calm["loadedAt"]), "skeletonAfterClick": calm["skeletonAt"] and round(calm["skeletonAt"])}
    checks[f"shell-calm-loading-{theme}"] = calm["ready"] and (calm["skeletonAt"] is None or calm["skeletonAt"] >= 240)
    # 5. Arrange: save a scene, then Delete asks in place; Escape keeps it, Delete removes it.
    page.evaluate("[...document.querySelectorAll('.nx-strip button')].find(b => b.textContent.includes('Arrange')).click()")
    page.wait_for_timeout(300)
    page.evaluate("[...document.querySelectorAll('button')].find(b => b.textContent.includes('Save as scene')).click()")
    page.wait_for_timeout(150)
    page.evaluate("""(() => { const input = document.querySelector('input[aria-label="Scene name"]');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'Proof scene');
      input.dispatchEvent(new Event('input', { bubbles: true })); input.form.requestSubmit(); })()""")
    page.wait_for_timeout(200)
    x = "document.querySelector('[aria-label=\"Delete scene Proof scene\"]')"
    page.evaluate(f"{x}.focus(); {x}.click()")
    page.wait_for_timeout(250)
    asked = page.evaluate("() => ({ group: document.querySelector('.nx-confirm')?.getAttribute('aria-label'), focus: document.activeElement?.textContent })")
    page.screenshot(path=str(out / f"shell-arrange-confirm-{theme}.png"))
    page.evaluate("document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))")
    page.wait_for_timeout(150)
    kept = page.evaluate("() => ({ open: Boolean(document.querySelector('.nx-confirm')), focus: document.activeElement?.getAttribute('aria-label') })")
    page.evaluate(f"{x}.click()")
    page.wait_for_timeout(200)
    page.evaluate("[...document.querySelectorAll('.nx-confirm button')].find(b => b.textContent === 'Delete').click()")
    page.wait_for_timeout(250)
    gone = page.evaluate(f"() => ({{ chip: Boolean({x}), said: (globalThis.__nxAnnounced || []).map(x => x.text) }})")
    found["arrange"] = {"asked": asked, "kept": kept, "gone": gone}
    checks[f"shell-arrange-confirm-{theme}"] = (asked == {"group": "Delete Proof scene?", "focus": "Keep"}
        and kept == {"open": False, "focus": "Delete scene Proof scene"} and not gone["chip"] and "Scene Proof scene deleted" in gone["said"])
    page.evaluate("[...document.querySelectorAll('.nx-strip button')].find(b => b.textContent.includes('Done arranging'))?.click()")
    return found


def run_shell(base_url: str, out: Path, checks: dict, data: dict) -> None:
    for viewport, (width, height) in VIEWPORTS.items():
        for theme in ("dark", "light"):
            if viewport == "phone" and theme == "dark":
                continue
            with chromium_review_page(width=width, height=height) as page:
                page.goto(base_url.rstrip("/") + SHELL)
                page.wait_for_selector(".nx-checklist", timeout=60000)
                page.wait_for_timeout(600)
                label = theme if viewport == "desktop" else f"{theme}-phone"
                try:
                    if viewport == "phone":  # the phone shows the chat with its checklist
                        page.evaluate(f"document.querySelector('.nx-root')?.setAttribute('data-nx-theme', {json.dumps(theme)})")
                        page.wait_for_timeout(200)
                        page.screenshot(path=str(out / f"shell-phone-{theme}.png"))
                        checks[f"shell-phone-no-overflow-{theme}"] = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1
                    else:
                        data[f"shell:{label}"] = probe_shell(page, checks, out, theme)
                except Exception as error:  # a broken probe is a failed check, with its reason
                    checks[f"shell-{label}-ran"] = False
                    data[f"shell:{label}"] = {"error": str(error)}


KIT = "/src/neyvia/next/details/kit/demo.html"
KIT_WHEEL = """() => [...document.querySelectorAll('#count .nxd-roll-strip')].map(s => ({ p: Number(s.style.getPropertyValue('--nxd-roll-p')),
  y: new DOMMatrix(getComputedStyle(s).transform).m42, h: parseFloat(getComputedStyle(s).lineHeight) }))"""


def probe_kit(page, checks):
    """The framework-free kit a generated web app gets: same behaviours, plain DOM."""
    found = {}
    page.evaluate("[...document.querySelectorAll('[data-add=\"27\"]')][0].click()")
    page.wait_for_timeout(90)
    mid = page.evaluate(KIT_WHEEL)
    page.wait_for_timeout(700)
    end = page.evaluate(KIT_WHEEL)
    text = page.evaluate("document.querySelector('#count').textContent")
    found["roll"] = {"mid": mid, "end": end, "text": text}
    checks["kit-roll"] = (text == "125" and any(abs(m["y"] + m["p"] * m["h"]) > 1 for m in mid[1:])
                          and all(10 <= c["p"] < 20 and abs(c["y"] + c["p"] * c["h"]) < 0.5 for c in end))
    meter = page.evaluate("() => { const m = document.querySelector('#meter'); return { now: m.getAttribute('aria-valuenow'), role: m.getAttribute('role') }; }")
    checks["kit-meter"] = meter == {"now": "50", "role": "progressbar"}
    page.evaluate("document.querySelectorAll('#tasks input')[1].click()")
    page.wait_for_timeout(500)
    checks["kit-strike"] = page.evaluate("document.querySelectorAll('#tasks .nxd-strike.is-on').length") == 2
    page.evaluate("document.querySelector('#delete').click()")
    page.wait_for_timeout(150)
    asked = page.evaluate("() => ({ group: document.querySelector('.nxd-confirm')?.getAttribute('aria-label'), focus: document.activeElement?.textContent })")
    page.evaluate("document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))")
    page.wait_for_timeout(100)
    kept = page.evaluate("() => ({ open: Boolean(document.querySelector('.nxd-confirm')), focus: document.activeElement?.id })")
    page.evaluate("document.querySelector('#delete').click()")
    page.wait_for_timeout(100)
    page.evaluate("[...document.querySelectorAll('.nxd-confirm button')].find(b => b.textContent === 'Delete').click()")
    page.wait_for_timeout(200)
    gone = page.evaluate("() => ({ chip: Boolean(document.querySelector('.chip')), said: document.querySelector('.nxd-sr[role=status]')?.textContent })")
    found["confirm"] = {"asked": asked, "kept": kept, "gone": gone}
    checks["kit-confirm"] = asked == {"group": "Delete Old draft?", "focus": "Keep"} and kept == {"open": False, "focus": "delete"} and gone == {"chip": False, "said": "Old draft deleted"}
    page.evaluate("navigator.clipboard.writeText = async text => { window.__copied = text; }")
    page.evaluate("document.querySelector('#copy').click()")
    page.wait_for_timeout(260)
    copy = page.evaluate("() => ({ state: document.querySelector('#copy').dataset.state, label: document.querySelector('#copy .nxd-copy-label').textContent, copied: window.__copied })")
    checks["kit-copy"] = copy == {"state": "done", "label": "Copied", "copied": "npm run build"}
    skeleton = "Boolean(document.querySelector('#result .skeleton'))"
    page.evaluate("document.querySelector('[data-load=\"150\"]').click()")
    page.wait_for_timeout(100)
    quick = page.evaluate(skeleton)
    page.wait_for_timeout(300)
    page.evaluate("document.querySelector('[data-load=\"1800\"]').click()")
    page.wait_for_timeout(120)
    early = page.evaluate(skeleton)
    page.wait_for_timeout(400)
    shown = page.evaluate(skeleton)
    page.wait_for_timeout(1700)
    after = page.evaluate("document.querySelector('#result').textContent")
    checks["kit-calm-loading"] = quick is False and early is False and shown is True and after.startswith("Loaded in 1.8 s")
    found["copy"] = copy
    return found


def run_kit(base_url: str, out: Path, checks: dict, data: dict) -> None:
    for viewport, (width, height) in VIEWPORTS.items():
        for theme in ("light", "dark"):
            with chromium_review_page(width=width, height=height) as page:
                page.emulate_media(color_scheme=theme)
                page.goto(base_url.rstrip("/") + KIT)
                page.wait_for_selector("#count.nxd-roll")
                page.wait_for_timeout(300)
                checks[f"kit-no-overflow-{viewport}-{theme}"] = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1
                page.screenshot(path=str(out / f"kit-{viewport}-{theme}.png"), full_page=True)
                if viewport == "desktop" and theme == "dark":
                    try:
                        data["kit"] = probe_kit(page, checks)
                    except Exception as error:
                        checks["kit-ran"] = False
                        data["kit"] = {"error": str(error)}


def run_lab(base: str, out: Path, checks: dict, data: dict, shots: list) -> None:
    for viewport, (width, height) in VIEWPORTS.items():
        with chromium_review_page(width=width, height=height) as page:
            for theme in ("light", "dark"):
                for only in SPECIMENS:
                    page.goto(f"{base}?theme={theme}&only={only}")
                    page.wait_for_selector(f"[data-specimen='{only}']")
                    page.wait_for_timeout(500)
                    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                    checks[f"no-overflow-{only}-{viewport}-{theme}"] = overflow <= 1
                    path = out / f"{only}-{viewport}-{theme}.png"
                    page.screenshot(path=str(path), full_page=True)
                    shots.append(str(path))
    with chromium_review_page(width=1280, height=900) as page:
        for only, probe in (("details-numbers", probe_numbers), ("details-actions", probe_actions), ("details-states", probe_states), ("details-numbers", probe_reduced)):
            page.goto(f"{base}?theme=dark&only={only}")
            page.wait_for_selector(f"[data-specimen='{only}']")
            page.wait_for_timeout(400)
            try:
                data[f"{only}:{probe.__name__}"] = probe(page, checks)
            except Exception as error:  # a broken probe is a failed check, with its reason
                checks[f"{probe.__name__}-ran"] = False
                data[f"{only}:{probe.__name__}"] = {"error": str(error)}


PARTS = ("lab", "shell", "kit")


def part_of(name: str) -> str:
    """Which part wrote a check, data key or screenshot (so one part can be re-run alone)."""
    return "shell" if name.startswith("shell") else "kit" if name.startswith("kit") else "lab"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="dev UI origin serving /design-lab.html and /control")
    parser.add_argument("--request", type=Path, help="JSON {url, out?} written by the design manual's prove-details procedure")
    parser.add_argument("--out", type=Path, default=Path("proof/a2-details"))
    parser.add_argument("--part", choices=("all",) + PARTS, default="all",
                        help="run one part (each fits a 2-minute terminal call); the others' results in report.json are kept")
    args = parser.parse_args(argv)
    if args.request:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        args.url = args.url or request.get("url")
        args.out = Path(request["out"]) if request.get("out") else args.out
    if not args.url:
        parser.error("pass --url or a --request file with a url")
    args.out.mkdir(parents=True, exist_ok=True)
    base = args.url.rstrip("/") + "/design-lab.html"
    parts = PARTS if args.part == "all" else (args.part,)
    report_path = args.out / "report.json"
    previous = json.loads(report_path.read_text(encoding="utf-8")) if args.part != "all" and report_path.exists() else {}
    checks: dict[str, bool] = {k: v for k, v in previous.get("checks", {}).items() if part_of(k) not in parts}
    data: dict[str, object] = {k: v for k, v in previous.get("data", {}).items() if part_of(k) not in parts}
    shots = [p for p in previous.get("screenshots", []) if part_of(Path(p).name) not in parts]
    if "lab" in parts:
        run_lab(base, args.out, checks, data, shots)
    if "shell" in parts:
        run_shell(args.url, args.out, checks, data)
    if "kit" in parts:
        run_kit(args.url, args.out, checks, data)
    failed = sorted(name for name, ok in checks.items() if not ok)
    report = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "url": base, "status": "ok" if not failed else "fail",
              "checks": checks, "failed": failed, "screenshots": shots, "data": data}
    (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"R details {report['status']} checks:{len(checks) - len(failed)}/{len(checks)}" + "".join(f" -{name}" for name in failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
