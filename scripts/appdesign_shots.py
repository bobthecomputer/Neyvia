"""App design pass: every app in every theme, rendered in Neyvia's Obscura engine (layout only).

python scripts/appdesign_shots.py --set before [--only terminal,pdf] [--themes dark,light] [--narrow]

Reuses the placement proof rig (scripts/placement_shots.py) on ports 48921-48922: the production
build in web/dist over this worktree, an isolated HOME, apps opened through the launcher the way
Paul opens them. Each app is shot beside the chat at 1440x900 in Forest, Morning, Sunset and Night
Green; --narrow also shoots App Factory, App preview and CiteCraft in the side panel and as a peek.
Output: docs/evidence/appdesign/<set>/<app>-<theme>[-side|-peek].png and receipt.json.

Obscura paints no iframes, WebGL or web fonts: those parts are verified in a real browser by the
lead (the design manual's app-identity judge names them).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import placement_shots as shots  # noqa: E402

ROOT = HERE.parent
THEMES = {"dark": "forest", "light": "morning", "sunset": "sunset", "night": "night"}
NARROW = ("app-factory", "app-preview", "research")


SETTINGS_THEME = {"dark": "forest", "light": "morning", "sunset": "sunset", "night": "night-green"}
SET_THEME = """async theme => {
  const call = async (command, payload) => { const r = await fetch('/api/backend', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command, payload }) }); const j = await r.json(); return j.data ?? j; };
  const current = await call('settings_get_command', {});
  const look = { font: 'neyvia', textSize: 'm', background: { kind: 'theme', preset: '', color: '', image: '', dim: 0, blur: 0 } };
  await call('settings_update_command', { patch: { theme, look }, expectedRevision: current.revision });
  return current.revision;
}"""


def session(rig, theme, viewport):
    """A fresh page in `theme`: the theme lives in Settings (the backend), which wins over local storage."""
    rig.session(viewport)
    rig.page.evaluate(SET_THEME, SETTINGS_THEME[theme])
    rig.page.evaluate("t => { localStorage.setItem('nx.os.theme', JSON.stringify(t)); localStorage.removeItem('nx.os.look'); }", theme)
    rig.page.reload(wait_until="load")
    rig.wait("() => !!document.querySelector('.nx-root')", 40)
    rig.wait("t => document.querySelector('.nx')?.dataset.nxTheme === t", 20, theme)
    time.sleep(1.2)
    rig.page.evaluate("() => document.querySelector('.nx-onboarding [aria-label=\"Close\"], .nx-onb-skip')?.click()")


def check(receipt, label, ok, **extra):
    receipt["checks"].append({"label": label, "ok": bool(ok), **extra})
    print(("PASS " if ok else "FAIL ") + label)


TYPE_INTO = """([selector, text]) => { const el = document.querySelector(selector); if (!el) return false;
  let proto = Object.getPrototypeOf(el), d = null;
  while (proto && !(d = Object.getOwnPropertyDescriptor(proto, 'value'))) proto = Object.getPrototypeOf(proto);
  if (d && d.set) d.set.call(el, text); else el.value = text;
  el.dispatchEvent(new Event('input', { bubbles: true })); return true; }"""
WIN = "document.querySelector(`[data-window='${CSS.escape(id)}']`)"
CLASSES = "id => " + WIN + "?.className || ''"
# Every class a window wears while it moves (an observer, so a slow round trip can't miss a short glide).
WATCH = "id => { window.__seen = []; const el = " + WIN + "; window.__obs?.disconnect(); window.__obs = new MutationObserver(() => window.__seen.push(el.className)); window.__obs.observe(el, { attributes: true, attributeFilter: ['class'] }); return true; }"
SEEN = "() => (window.__seen || []).join(' | ')"


def extras(rig, receipt, themes):
    """App Factory's live sketch and frames, the motion between placements, and the 3D page alone."""
    for theme in [t for t in themes if t in ("dark", "light")]:
        session(rig, theme, shots.DESKTOP)
        name = THEMES[theme]
        shots.open_from_launcher(rig, "App Factory", "App Factory")
        wid = shots.window_id(rig, "App Factory")
        shots.press_place(rig, wid, "Full screen")
        time.sleep(1.0)
        rig.shot(f"app-factory-{name}-full-sample")
        sample = rig.js("() => document.querySelector('.af-sketch h1')?.textContent || ''")
        check(receipt, f"App Factory ({name}): an empty factory shows a sample app in its frame", sample == "Pocket Field Notes", sample=sample)
        rig.js(TYPE_INTO, [".af-form input[placeholder='Pocket Field Notes']", "Tide Log"])
        rig.js(TYPE_INTO, [".af-form textarea", "Write down each tide and what the beach looked like, then find a day again."])
        time.sleep(0.8)
        typed = rig.js("() => ({ title: document.querySelector('.af-sketch h1')?.textContent, noun: document.querySelector('.af-sk-workhead h2')?.textContent, badge: document.querySelector('.af-badge')?.textContent })")
        check(receipt, f"App Factory ({name}): the sketch follows the brief as it is typed", typed.get("title") == "Tide Log" and typed.get("badge") == "Sketch of your brief", typed=typed)
        rig.shot(f"app-factory-{name}-full-typing")
        for frame in ("Browser", "iPhone", "Android"):
            rig.js("label => [...document.querySelectorAll('.af-seg button')].find(b => b.textContent === label)?.click()", frame)
            time.sleep(0.9)
            kind = rig.js("() => document.querySelector('.af-device, .af-window')?.className || ''")
            check(receipt, f"App Factory ({name}): shows the app in the {frame} frame", frame.lower() in kind or (frame == "Browser" and "is-browser" in kind), kind=kind)
            rig.shot(f"app-factory-{name}-full-{frame.lower()}")
        rig.js("""() => { const s = document.querySelector('.af-form select'); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, 'neyvia'); s.dispatchEvent(new Event('change', { bubbles: true })); }""")
        time.sleep(0.8)
        kind = rig.js("() => document.querySelector('.af-device, .af-window')?.className || ''")
        check(receipt, f"App Factory ({name}): a Neyvia local app target puts it back in a browser frame", "is-browser" in kind, kind=kind)
        frame_key = "() => document.querySelector('.af-window, .af-device')?.getBoundingClientRect().width || 0"
        width_full = rig.js(frame_key)
        frame_restore = rig.js("id => { const b = [...document.querySelector(`[data-window='${CSS.escape(id)}']`).querySelectorAll('.nx-place button')].find(x => (x.getAttribute('aria-label') || '').startsWith('Exit full')); b?.click(); return !!b; }", wid)
        time.sleep(0.9)
        shots.press_place(rig, wid, "Side panel")
        time.sleep(1.0)
        compact = rig.js("() => { const tabs = document.querySelector('.af-tabs'); const canvas = document.querySelector('.af-canvas').getBoundingClientRect(); const brief = document.querySelector('.af-brief').getBoundingClientRect(); return { tabs: tabs ? getComputedStyle(tabs).display : null, stacked: brief.top >= canvas.bottom - 1, frame: document.querySelector('.af-window, .af-device')?.getBoundingClientRect().width || 0 }; }")
        check(receipt, f"App Factory ({name}): in the side panel it stacks with the app first and Brief/Build tabs", compact.get("tabs") == "flex" and compact.get("stacked") and 0 < compact.get("frame", 0) < width_full, compact=compact, restored=frame_restore)
        rig.shot(f"app-factory-{name}-side-typing")
        # Motion: the window folds into its bubble and unfolds back out, never a jump.
        rig.js(WATCH, wid)
        rig.js("id => [...document.querySelector(`[data-window='${CSS.escape(id)}']`).querySelectorAll('.nx-place button')].find(b => (b.getAttribute('aria-label') || '').startsWith('Collapse'))?.click()", wid)
        time.sleep(0.15)
        during = rig.js(SEEN)
        time.sleep(0.6)
        after = rig.js(CLASSES, wid)
        check(receipt, f"Motion ({name}): collapsing folds the window into its bubble, then hides it", "is-folding" in during and "is-hidden" in after, during=during, after=after)
        rig.js(WATCH, wid)
        rig.js("id => { const b = document.querySelector(`[data-bubble-for='${CSS.escape(id)}']`); b.focus(); b.dispatchEvent(new KeyboardEvent('keydown', { key: 'r', bubbles: true })); }", wid)
        time.sleep(0.15)
        during = rig.js(SEEN)
        time.sleep(0.6)
        after = rig.js(CLASSES, wid)
        check(receipt, f"Motion ({name}): R unfolds it from the bubble back into its place", "is-unfolding" in during and "is-hidden" not in after and "is-unfolding" not in after, during=during, after=after)
        rig.js(WATCH, wid)
        rig.js("id => [...document.querySelector(`[data-window='${CSS.escape(id)}']`).querySelectorAll('.nx-place button')].find(b => (b.getAttribute('aria-label') || '').startsWith('Full screen'))?.click()", wid)
        time.sleep(0.6)
        during = rig.js(SEEN)
        check(receipt, f"Motion ({name}): a move glides on the spring (is-moving)", "is-moving" in during, during=during)
        time.sleep(0.6)
        rig.js("id => document.querySelector(`[data-window='${CSS.escape(id)}'] .nx-stage-head > button[aria-label^='Close']`)?.click()", wid)
        leaving = rig.js("() => [...document.querySelectorAll('.nx-surface')].map(s => s.className).join(' | ')")
        check(receipt, f"Motion ({name}): closing fades the window out instead of cutting", "is-leaving" in leaving, leaving=leaving)
        time.sleep(0.6)
        gone = rig.js("() => document.querySelectorAll('.nx-surface').length")
        check(receipt, f"Motion ({name}): the faded window is gone after the fade", gone == 0, gone=gone)
        # The 3D page on its own: Obscura has no WebGL, so this is the honest fallback.
        origin = f"http://127.0.0.1:{shots.BACKEND}"
        rig.page.goto(origin + f"/api/gamedev/browser?look={'light' if theme == 'light' else 'dark'}", wait_until="load")
        time.sleep(2.5)
        state = rig.js("() => ({ fallback: !document.getElementById('fallback')?.hidden, title: document.getElementById('fallback-title')?.textContent, status: document.getElementById('status-text')?.textContent, look: document.body.dataset.look })")
        check(receipt, f"3D page ({name}): without WebGL it says why, plainly, and keeps the scene for agents", state.get("fallback") and "3D" in (state.get("title") or ""), state=state)
        rig.shot(f"3d-page-{name}-no-webgl")


NARROW_PROBE = {
    "app-factory": "() => { const t = document.querySelector('.af-tabs'); const c = document.querySelector('.af-canvas')?.getBoundingClientRect(); const b = document.querySelector('.af-brief')?.getBoundingClientRect(); return !!(t && c && b) && getComputedStyle(t).display === 'flex' && b.top >= c.bottom - 1; }",
    "research": "() => { const g = document.querySelector('.neyvia-citecraft-grid'); const l = document.querySelector('.neyvia-research-ledger'); return !!(g && l) && getComputedStyle(g).display === 'flex' && getComputedStyle(l).gridTemplateColumns.split(' ').length === 1; }",
    "app-preview": "() => { const f = document.querySelector('.neyvia-app-preview .af-window, .neyvia-app-preview .af-device'); const s = document.querySelector('.neyvia-app-preview-stage'); return !!(f && s) && f.getBoundingClientRect().width <= s.getBoundingClientRect().width + 1; }",
}


def narrow_check(rig, receipt, app, name, where):
    ok = rig.js(NARROW_PROBE[app])
    check(receipt, f"{app} ({name}): adapts in the {where}", ok)


def files_go(rig, place_label, names):
    """Pick a place in Files' place menu, then double-click down through folder names."""
    rig.wait("() => document.querySelectorAll('.nx-files-placepick option').length > 0", 15)
    rig.js("""label => { const s = document.querySelector('.nx-files-placepick'); const o = [...s.options].find(o => o.textContent.trim() === label);
      if (!o) return false; Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, o.value); s.dispatchEvent(new Event('change', { bubbles: true })); return true; }""", place_label)
    time.sleep(1.0)
    for name in names:
        find = "n => [...document.querySelectorAll('[data-path]')].find(e => e.dataset.path.split(/[\\\\/]/).pop() === n)"
        rig.wait(f"n => !!({find})(n)", 15, name)
        rig.js(f"n => ({find})(n).dispatchEvent(new MouseEvent('dblclick', {{ bubbles: true }}))", name)
        time.sleep(1.0)


def content(rig, receipt, themes):
    """Real content, shown the way each app should show it (Obscura still paints no xterm canvas or pdf.js)."""
    for theme in [t for t in themes if t in ("dark", "light")]:
        session(rig, theme, shots.DESKTOP)
        name = THEMES[theme]
        # Terminal: the header and the prompt line from the first frame.
        shots.open_from_launcher(rig, "Terminal", "Terminal")
        time.sleep(1.5)
        term = rig.js("() => ({ head: !!document.querySelector('.nx-tp-head'), path: document.querySelector('.nx-tp-path')?.textContent || '', prompt: document.querySelector('.nx-tp-ghost')?.textContent || '', rows: document.querySelector('.xterm-rows')?.textContent?.trim().length || 0 })")
        check(receipt, f"Terminal ({name}): a header names the folder and shell, and a prompt line shows before the shell's first output", term.get("head") and term.get("path") and (term.get("prompt").startswith("PS ") or term.get("rows", 0) > 0), term=term)
        rig.shot(f"terminal-{name}-content")
        shots.close_all(rig)
        # Notes: the welcome page, then a note from a starter.
        shots.open_from_launcher(rig, "Notes", "Notes")
        time.sleep(1.2)
        welcome = rig.js("() => ({ sheet: !!document.querySelector('.nx-notes-sheet'), starters: document.querySelectorAll('.nx-notes-starters button').length })")
        check(receipt, f"Notes ({name}): with no note open it shows an example page and one-click starters", welcome.get("sheet") and welcome.get("starters") == 4, welcome=welcome)
        rig.shot(f"notes-{name}-welcome")
        rig.js("() => [...document.querySelectorAll('.nx-notes-starters button')].find(b => b.textContent.includes('Meeting'))?.click()")
        rig.wait("() => !!document.querySelector('.nx-notes-text')", 15)
        time.sleep(1.2)
        # What was saved, as the note's own preview renders it (Obscura doesn't report a textarea's value).
        note = rig.js("() => document.querySelector('.nx-notes-preview')?.innerText?.trim() || document.querySelector('.nx-notes-text')?.value || ''")
        check(receipt, f"Notes ({name}): the Meeting starter makes a real note with its template", note.lstrip("# ").startswith("Meeting"), note=note[:60])
        rig.shot(f"notes-{name}-note")
        shots.close_all(rig)
        # Research: the example review, then loaded for real.
        shots.open_from_launcher(rig, "CiteCraft", "CiteCraft")
        time.sleep(1.2)
        rig.js("() => document.querySelector('[data-studio-action=\"load-example\"]')?.click()")
        time.sleep(1.0)
        cards = rig.js("() => document.querySelectorAll('.neyvia-research-list li:not(.neyvia-research-example)').length")
        check(receipt, f"Research ({name}): 'Start from the example review' fills the ledger with real, editable sources", cards == 2, cards=cards)
        rig.shot(f"research-{name}-content")
        rig.js("() => { localStorage.removeItem('neyvia.studio.citecraft.v1'); }")
        shots.close_all(rig)
        # Files: a folder of pictures as a grid of thumbnails.
        shots.open_from_launcher(rig, "Files", "Files")
        files_go(rig, "Workspace", ["docs", "evidence", "appdesign", "final"])
        rig.js("() => [...document.querySelectorAll('.nx-files-main .nx-iconbtn')].find(b => (b.getAttribute('aria-label') || '') === 'Show as a grid')?.click()")
        try:
            rig.wait("() => document.querySelectorAll('.nx-files-thumb.is-ready').length > 0", 12)
        except TimeoutError:
            pass
        time.sleep(1.0)
        grid = rig.js("() => ({ grid: !!document.querySelector('.nx-files-list.is-grid'), thumbs: document.querySelectorAll('.nx-files-thumb.is-ready').length, head: document.querySelector('.nx-files-head h2')?.textContent || '' })")
        check(receipt, f"Files ({name}): a folder of pictures shows as a grid with loaded thumbnails and a named header", grid.get("grid") and grid.get("thumbs", 0) > 0 and grid.get("head") == "final", grid=grid)
        rig.shot(f"files-{name}-grid")
        rig.js("() => [...document.querySelectorAll('.nx-files-main .nx-iconbtn')].find(b => (b.getAttribute('aria-label') || '') === 'Show as a list')?.click()")
        shots.close_all(rig)


def run(args):
    out = ROOT / "docs/evidence/appdesign" / args.set
    out.mkdir(parents=True, exist_ok=True)
    shots.OUT = out
    shots.BACKEND, shots.ENGINE = 48921, 48922
    shots.SCRATCH = ROOT.parent / "nx-appdesign-scratch" / args.set
    receipt = {"schema": "neyvia.appdesign-shots.v1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "set": args.set, "shots": [], "checks": [], "errors": []}
    only = [item for item in args.only.split(",") if item]
    apps = [app for app in shots.APPS if not only or app[0] in only]
    themes = [theme for theme in args.themes.split(",") if theme]
    rig = shots.Rig(receipt)
    try:
        rig.start()
        for theme in ([] if args.apps_off else themes):
            session(rig, theme, shots.DESKTOP)
            for app, query, title in ([] if args.apps_off else apps):
                try:
                    shots.open_from_launcher(rig, query, title)
                    wid = shots.window_id(rig, title)
                    time.sleep(args.settle)
                    name = f"{app}-{THEMES[theme]}"
                    rig.shot(name)
                    receipt["shots"].append({"file": f"{name}.png", "app": app, "theme": theme, "placement": "main"})
                    if args.narrow and app in NARROW:
                        shots.press_place(rig, wid, "Side panel")
                        time.sleep(0.8)
                        rig.shot(f"{name}-side")
                        narrow_check(rig, receipt, app, name, "side panel")
                        receipt["shots"].append({"file": f"{name}-side.png", "app": app, "theme": theme, "placement": "side"})
                        shots.press_place(rig, wid, "Collapse to a bubble")
                        rig.js("id => { const b = document.querySelector(`[data-bubble-for=\"${CSS.escape(id)}\"]`); b.focus(); b.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); }", wid)
                        time.sleep(0.9)
                        rig.js("on => { let s = document.getElementById('iso'); if (!s) { s = document.createElement('style'); s.id = 'iso'; document.head.append(s); } s.textContent = '.nx-os, .nx-strip, .nx-surface.is-main, .nx-surface.is-side { visibility: hidden !important; }'; }", True)
                        narrow_check(rig, receipt, app, name, "bubble peek")
                        rig.shot(f"{name}-peek")
                        rig.js("() => document.getElementById('iso')?.remove()")
                        receipt["shots"].append({"file": f"{name}-peek.png", "app": app, "theme": theme, "placement": "bubble-peek"})
                    shots.close_all(rig)
                except Exception as exc:  # one app failing must not hide the others
                    receipt["errors"].append(f"{app}/{theme}: {type(exc).__name__}: {exc}")
                    print("ERROR", app, theme, exc)
                    try:
                        rig.shot(f"failure-{app}-{THEMES[theme]}")
                        shots.close_all(rig)
                    except Exception:
                        pass
        if args.extras:
            extras(rig, receipt, themes)
        if args.content:
            content(rig, receipt, themes)
        receipt["ok"] = not receipt["errors"] and all(check["ok"] for check in receipt["checks"])
    except Exception as exc:
        receipt["ok"] = False
        receipt["failure"] = f"{type(exc).__name__}: {exc}"
        receipt["traceback"] = traceback.format_exc()
    finally:
        rig.stop()
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"ok": receipt.get("ok"), "failure": receipt.get("failure"), "shots": len(receipt["shots"]), "errors": receipt["errors"]}))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default="before")
    parser.add_argument("--only", default="")
    parser.add_argument("--themes", default="dark,light,sunset,night")
    parser.add_argument("--narrow", action="store_true")
    parser.add_argument("--settle", type=float, default=1.0)
    parser.add_argument("--extras", action="store_true", help="App Factory sketch and frames, motion checks, the 3D page alone")
    parser.add_argument("--apps-off", action="store_true", help="skip the per-app theme shots")
    parser.add_argument("--content", action="store_true", help="apps with real content: a note, a research review, a folder of pictures, the terminal prompt")
    result = run(parser.parse_args())
    raise SystemExit(0 if result.get("ok") else 1)
