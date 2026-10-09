"""Theme proof: every theme on the main surfaces, at 1440 and 390, rendered in Neyvia's Obscura engine.

python scripts/theme_shots.py --ports 49251,49252 [--themes terminal,paper,ember] [--views home,thread] [--viewports 1440,390] [--out D:/NeyviaRuns/29-THEME/shots/cp2]

Serves a fixtures build (web/vite.themeshots.config.mjs, import.meta.env.DEV true so ?fixtures=1 works) from
--dist with a tiny static server on the first port, starts the admitted Obscura engine on the second and drives
it over CDP. Nothing is ever shown on screen. Writes <out>/<view>-<theme>-<width>[-<scheme>].png and receipt.json
(rendered theme per shot, console errors). `--dark-os` / `--light-os` emulate prefers-color-scheme where it matters.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DPR = 2  # Obscura draws small monospace text with capitals as lowercase glyphs at 1x; at 2x it is right
INJECT = False  # --inject-css: layer the current nxThemes.css and nxMotion.css over the built bundle (CSS iteration without a rebuild)
UA = "NeyviaAgent/1.0 (Automation; Obscura)"
THEMES = ["dark", "light", "sunset", "night", "terminal", "paper", "ember"]
VIEWPORTS = {"1440": {"width": 1440, "height": 900}, "390": {"width": 390, "height": 844}}

KEY = """([key, code, ctrl]) => {
  const el = document.activeElement || document.body;
  const init = { key, code, ctrlKey: ctrl, bubbles: true, cancelable: true };
  el.dispatchEvent(new KeyboardEvent('keydown', init)); el.dispatchEvent(new KeyboardEvent('keyup', init));
}"""
TYPE = """text => {
  const el = document.activeElement;
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, text);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):  # single page app: unknown paths serve index.html
        path = self.translate_path(self.path.split("?")[0])
        if not os.path.exists(path) or os.path.isdir(path) and not os.path.exists(os.path.join(path, "index.html")):
            self.path = "/index.html"
        return super().do_GET()


def await_http(url, headers=None, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(url)


class Rig:
    def __init__(self, dist, out, ports, exe, scratch):
        self.dist, self.out, self.exe, self.scratch = Path(dist), Path(out), Path(exe), Path(scratch)
        self.static_port, self.engine_port = ports
        self.errors, self.checks = [], []
        self.engine = self.server = self.playwright = self.browser = self.context = self.page = None

    def start(self):
        handler = functools.partial(Quiet, directory=str(self.dist))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", self.static_port), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        token = secrets.token_urlsafe(36)
        self.scratch.mkdir(parents=True, exist_ok=True)
        log = (self.scratch / "engine.log").open("ab")
        env = {**os.environ, "OBSCURA_CDP_TOKEN": token, "OBSCURA_ROTATE_PROFILE": "0", "OBSCURA_NAV_TIMEOUT_MS": "40000", "OBSCURA_SCRIPT_DEADLINE_MS": "30000"}
        self.engine = subprocess.Popen([str(self.exe), "serve", "--host", "127.0.0.1", "--port", str(self.engine_port), "--user-agent", UA,
                                        "--max-connections", "8", "--allow-private-network"], stdout=log, stderr=log, env=env,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        await_http(f"http://127.0.0.1:{self.engine_port}/json/version", {"Authorization": "Bearer " + token})
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.engine_port}", headers={"Authorization": "Bearer " + token}, timeout=30000)

    def session(self, theme, viewport, query="preview-control=1&fixtures=1&bus=mock&busscript=0&ui=next", scheme=None, extra=None, reduced=False):
        if self.context:
            self.context.close()
        kwargs = {"user_agent": UA, "viewport": viewport, "device_scale_factor": DPR}
        if scheme:
            kwargs["color_scheme"] = scheme
        if reduced:
            kwargs["reduced_motion"] = "reduce"
        self.context = self.browser.new_context(**kwargs)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)[:300]))
        origin = f"http://127.0.0.1:{self.static_port}"
        self.context.add_init_script("try { localStorage.clear(); localStorage.setItem('nx.os.theme', JSON.stringify(" + json.dumps(theme) + ")); localStorage.setItem('nx.os.density', JSON.stringify('workshop')); } catch (e) {}")
        for key, value in (extra or {}).items():
            self.context.add_init_script("try { localStorage.setItem(" + json.dumps(key) + ", JSON.stringify(" + json.dumps(value) + ")); } catch (e) {}")
        self.page.goto(f"{origin}/control?{query}", wait_until="load")
        self.wait("() => !!document.querySelector('.nx-root')", 60)
        self.wait("t => document.querySelector('.nx-root')?.getAttribute('data-nx-theme') === t", 30, theme)
        if INJECT:
            self.page.evaluate("css => { const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s); }", chr(10).join((ROOT / "web/src/neyvia/next" / name).read_text(encoding="utf-8") for name in ("nxOs.css", "providerMark.css", "nxThemes.css", "nxMotion.css")))
        time.sleep(1.5)
        self.js("() => document.querySelector('.nx-onboarding [aria-label=\"Close\"], .nx-onb-skip')?.click()")

    def js(self, expression, arg=None):
        return self.page.evaluate(expression, arg) if arg is not None else self.page.evaluate(expression)

    def wait(self, expression, timeout=20, arg=None):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                if self.js(expression, arg):
                    return True
            except Exception:
                pass
            time.sleep(0.25)
        raise TimeoutError(expression)

    def shot(self, name, theme):
        actual = self.js("() => document.querySelector('.nx-root')?.getAttribute('data-nx-theme')")
        self.checks.append({"name": name, "theme": theme, "rendered": actual, "ok": actual == theme})
        time.sleep(1.0)
        path = self.out / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=False)
        return path

    def stop(self):
        for closer in (lambda: self.context and self.context.close(), lambda: self.browser and self.browser.close(), lambda: self.playwright and self.playwright.stop(), lambda: self.server and self.server.shutdown()):
            try:
                closer()
            except Exception as exc:
                self.errors.append(f"close: {exc}")
        if self.engine and self.engine.poll() is None:
            self.engine.terminate()
            try:
                self.engine.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.engine.kill()


# ---- views: each leaves the shell on one main surface -------------------------------------

BASE = "preview-control=1&fixtures=1&bus=mock&busscript=0&ui=next"
# view -> (extra query, action after load). Panes and apps open through the product's own store actions (window.__nxOs).
VIEWS = {
    "home": ("", None),
    "thread": ("chat=s-claude-live", None),
    "approval": ("chat=s-codex-approve", None),
    "question": ("chat=s-claude-question", None),
    "settings": ("", "() => window.__nxOs.showPane('settings', '')"),
    "runtime": ("", "() => window.__nxOs.showPane('runtime', '')"),
    "notes": ("", "() => window.__nxOs.openApp('notes', 'documents')"),
    "files": ("", "() => window.__nxOs.openApp('files', 'documents')"),
    "agents": ("", "() => window.__nxOs.setDashboard(true)"),
    "help": ("", "() => window.__nxOs.setHelp(true)"),
    "launcher": ("", "KEYS"),
}

# Text contrast measured in the rendered page: every element with its own text, its colour against the
# first opaque background found walking up (alpha blended), WCAG 4.5:1 (3:1 for large text). Gradients and
# images are not sampled, so this is the floor check; the theme tokens are checked exhaustively in the model test.
CONTRAST = r"""() => {
  const parse = c => { const m = /rgba?\(([^)]+)\)/.exec(c); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lin = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = c => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
  const mix = (top, base) => ({ r: top.r * top.a + base.r * (1 - top.a), g: top.g * top.a + base.g * (1 - top.a), b: top.b * top.a + base.b * (1 - top.a), a: 1 });
  const backdrop = el => { const stack = []; for (let n = el; n; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a > 0) { stack.push(c); if (c.a >= 1) break; } }
    let base = { r: 4, g: 4, b: 4, a: 1 }; const root = parse(getComputedStyle(document.querySelector('.nx-root')).backgroundColor); if (root) base = { ...root, a: 1 };
    for (const c of stack.reverse()) base = mix(c, base); return base; };
  const out = []; let checked = 0;
  for (const el of document.querySelectorAll('.nx-root *')) {
    if (!el.childNodes.length) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (!own) continue;
    const box = el.getBoundingClientRect(); if (box.width < 2 || box.height < 2) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none' || Number(cs.opacity) === 0) continue;
    const fg = parse(cs.color); if (!fg) continue;
    const bg = backdrop(el); const text = mix(fg, bg);
    const a = lum(text) + 0.05, b = lum(bg) + 0.05, ratio = Math.max(a, b) / Math.min(a, b);
    const px = parseFloat(cs.fontSize), large = px >= 24 || (px >= 18.66 && Number(cs.fontWeight) >= 700);
    checked += 1;
    if (ratio < (large ? 3 : 4.5)) out.push({ text: el.textContent.trim().slice(0, 40), ratio: Math.round(ratio * 100) / 100, cls: String(el.className).slice(0, 60) });
  }
  return { checked, fails: out.slice(0, 25), failCount: out.length };
}"""


def run_action(rig, action):
    if not action:
        return
    if action == "KEYS":
        rig.js(KEY, [" ", "Space", True])
        rig.wait("() => !!document.querySelector('.nx-launcher input')", 10)
    else:
        rig.js(action)
    time.sleep(1.4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ports", required=True)
    parser.add_argument("--themes", default=",".join(THEMES))
    parser.add_argument("--views", default="home,thread,approval,settings,launcher,notes")
    parser.add_argument("--viewports", default="1440,390")
    parser.add_argument("--out", default=r"D:\NeyviaRuns\29-THEME\shots\run")
    parser.add_argument("--dist", default=r"D:\NeyviaRuns\29-THEME\dist-shots")
    parser.add_argument("--inject-css", action="store_true")
    parser.add_argument("--dpr", type=int, default=2)
    args = parser.parse_args()
    global INJECT, DPR
    INJECT = args.inject_css
    DPR = args.dpr
    ports = [int(p) for p in args.ports.split(",")]
    if len(ports) != 2 or not all(49251 <= p <= 49259 for p in ports):
        raise SystemExit("two ports in 49251-49259")
    exe = os.environ.get("NEYVIA_OBSCURA_EXE")
    if not exe:
        from grant_agent.browser_obscura import managed_executable
        exe = str(managed_executable())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rig = Rig(args.dist, out, ports, exe, r"D:\NeyviaRuns\29-THEME\engine")
    receipt = {"themes": args.themes, "views": args.views, "engine": exe, "engineSha256": hashlib.sha256(Path(exe).read_bytes()).hexdigest(), "shots": []}
    rig.start()
    try:
        for width in args.viewports.split(","):
            for theme in args.themes.split(","):
                for view in args.views.split(","):
                    try:
                        query, action = VIEWS[view]
                        rig.session(theme, VIEWPORTS[width], "&".join(x for x in (BASE, query) if x))
                        run_action(rig, action)
                        audit = rig.js(CONTRAST)
                        path = rig.shot(f"{view}-{theme}-{width}", theme)
                        receipt["shots"].append(str(path))
                        receipt.setdefault("contrast", {})[path.name] = audit
                        print("shot", path.name, "contrast fails", audit["failCount"], "of", audit["checked"], flush=True)
                    except Exception as exc:  # keep going: one failing view must not hide the rest
                        rig.errors.append(f"{view}-{theme}-{width}: {exc!r}"[:300])
                        print("FAIL", view, theme, width, repr(exc)[:160], flush=True)
    finally:
        rig.stop()
    receipt["checks"], receipt["errors"] = rig.checks, rig.errors
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"{len(receipt['shots'])} shots, {len(rig.errors)} errors, {sum(not c['ok'] for c in rig.checks)} theme mismatches")


if __name__ == "__main__":
    main()
