"""Placement proof: every app in every placement, rendered in Neyvia's own Obscura engine.

python scripts/placement_shots.py --ports <assigned-backend>,<assigned-engine> [--probe] [--only 3d-studio,notes]

Ports 48871-48889 only: one explicitly assigned backend and one Obscura CDP port per
run, so up to four runs (--tag) can go side by side; each writes receipt-<tag>.json. The backend
runs over this worktree with an isolated HOME, so no private chats or settings reach the shots.
Apps are opened and moved through the product's own controls: the launcher (Ctrl+Space), the
window's placement buttons, its keyboard shortcuts and a title-bar drag. Output:
D:/NeyviaRuns/tour, with exact receipt paths reported by the controller.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe")
EXE = Path(os.environ["NEYVIA_OBSCURA_EXE"]) if os.environ.get("NEYVIA_OBSCURA_EXE") else None
BACKEND = ENGINE = None
OUT = Path(r"D:\NeyviaRuns\tour\placement")
SCRATCH = Path(os.environ.get("PLACEMENT_SCRATCH", r"D:\NeyviaRuns\tour\placement-state"))
BUILD = ROOT / "web/dist"
THEME = "dark"
SMALL_STATE = None
UA = "NeyviaAgent/1.0 (Automation; Obscura)"
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}

# Every app and surface (docs/evidence/placement-matrix.md): (id, how it is opened, window title).
# A launcher search opens it the way Paul does (the result whose title matches is clicked); "files:"
# opens a file from Files with a double-click. Ready registry entries below
# supersede old fixture openers, so PDF now opens directly from the launcher.
PDF = ROOT / "scripts/evidence/C11g-artifacts/xournal.pdf"
APPS = [
    ("3d-studio", "3D Studio", "3D Studio"),
    ("browser", "Browser", "Browser"),
    ("cua-preview", "Preview: apps agents are using", "Preview"),
    ("preview", "App preview", "App preview"),
    ("files", "Files", "Files"),
    ("notes", "Notes", "Notes"),
    ("pdf", "files:" + str(PDF), "PDF"),
    ("terminal", "Terminal", "Terminal"),
    ("mobile-studio", "Mobile Studio", "Mobile Studio"),
    ("image-studio", "Image Playground", "Image Playground"),
    ("laya", "LAYA activity", "LAYA"),
    ("citecraft", "CiteCraft", "CiteCraft"),
    ("app-factory", "App Factory", "App Factory"),
    ("agent-view", "Agents at work", "Agents at work"),
    ("memory", "Memory", "Memory"),
]
REGISTRY = json.loads((ROOT / 'config/neyvia_apps.json').read_text(encoding='utf-8'))
REGISTRY_APPS = [app for suite in REGISTRY['suites'] for app in suite['apps']]
for registered in REGISTRY_APPS:
    if registered['status'] != 'ready':
        continue
    descriptor = (registered['id'], registered['name'], registered['name'])
    index = next((i for i, app in enumerate(APPS) if app[0] == registered['id']), None)
    if index is None:
        APPS.append(descriptor)
    else:
        APPS[index] = descriptor

# Include the production launcher's installed tool screens, not a second list.
_launcher = (ROOT / 'web/src/neyvia/next/nxShellLauncher.js').read_text(encoding='utf-8')
_tool_rows = _launcher.split('const TOOL_LAUNCH = [', 1)[1].split('\n];', 1)[0]
for _line in _tool_rows.splitlines():
    if not _line.strip() or _line.lstrip().startswith('//'):
        continue
    _row = re.match(r'\s*\[("(?:[^"\\]|\\.)*"),\s*("(?:[^"\\]|\\.)*")', _line)
    if not _row:
        raise ValueError('Tour cannot interpret a production launcher tool row')
    _app, _title = (json.loads(value) for value in _row.groups())
    if not any(app[0] == _app for app in APPS):
        APPS.append((_app, _title, _title))


def use_ports(backend, engine):
    global BACKEND, ENGINE
    declared = {int(p) for p in os.environ.get("NEYVIA_PLACEMENT_PORTS", "").split(",") if p}
    if len({backend, engine}) != 2 or not all(48871 <= port <= 48889 and port in declared for port in (backend, engine)):
        raise ValueError("Two distinct, explicitly assigned ports in 48871-48889 required")
    BACKEND, ENGINE = backend, engine


def free(port):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def await_http(url, process, headers=None):
    for _ in range(240):
        if process.poll() is not None:
            raise RuntimeError(f"Process exited before {url}: {process.returncode}")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=0.5) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(url)


def owned_listener(port, process):
    """Bind a ready Windows listener to the exact child this run started."""
    if process.poll() is not None:
        raise RuntimeError('Owned child exited before listener identity verification')
    command = f'(Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort {int(port)} -ErrorAction Stop).OwningProcess'
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    owners = {int(value) for value in result.stdout.split() if value.isdigit()}
    if result.returncode or owners != {process.pid}:
        raise RuntimeError(f'Port {port} is not owned by this run child PID {process.pid}')
    return {'port':port, 'pid':process.pid, 'verified':True}


def isolated_env():
    env = os.environ.copy()
    import site
    # APPDATA is isolated below; keep Python's user site-packages (pypdfium2, the PDF page renderer)
    # where they are installed, or the tour shows an import error a real user never sees.
    env.setdefault("PYTHONUSERBASE", site.getuserbase())
    for name in list(env):
        if any(word in name.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH_FILE")):
            env.pop(name, None)
    home = SCRATCH / "home"
    state = SCRATCH / "ui-state"
    # A fresh user's homes exist even when empty: a CODEX_HOME that points nowhere makes the
    # Codex app server exit at once, which is a harness artifact, not what a new user sees.
    for folder in (home, state, *(home / name for name in ("codex", "hermes", "claude", "xdg", "appdata", "localappdata"))):
        folder.mkdir(parents=True, exist_ok=True)
    env.update({
        "HOME": str(home), "USERPROFILE": str(home), "CODEX_HOME": str(home / "codex"), "HERMES_HOME": str(home / "hermes"),
        "CLAUDE_CONFIG_DIR": str(home / "claude"), "XDG_CONFIG_HOME": str(home / "xdg"), "APPDATA": str(home / "appdata"),
        "LOCALAPPDATA": str(home / "localappdata"), "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(ROOT / '.agent_control/INTN/bytecode' / ('tour-' + SMALL_STATE.name)) if SMALL_STATE else r"D:\NeyviaRuns\INTN\bytecode", "NEYVIA_PROVISIONING_ROOT": str((SMALL_STATE or SCRATCH) / "provisioning"),
        "NEYVIA_MOBILE_PROBE_DEVICES": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0", "NEYVIA_TOOL_AUTO_UPDATE": "0", "FLUXIO_RUNTIME_AUTO_UPDATE": "0",
        "FLUXIO_LOCAL_SESSION_BOOTSTRAP": "1", "SYNTELOS_ACCOUNT_USER": "placement-proof", "SYNTELOS_ACCOUNT_PASSWORD": secrets.token_urlsafe(32),
        "NEYVIA_UI_STATE_ROOT": str(SMALL_STATE or state), "FLUXIO_WEB_BACKEND_URL": f"http://127.0.0.1:{BACKEND}",
    })
    return env


class Rig:
    """Backend + Obscura + one Playwright page over CDP."""

    def __init__(self, receipt, *, connect_timeout=20000, direct_cdp=False):
        self.receipt = receipt
        self.processes = []
        self.playwright = self.browser = self.context = self.page = None
        self.connect_timeout, self.direct_cdp = connect_timeout, direct_cdp

    def start(self):
        if EXE is None or not EXE.is_file():
            raise ValueError('NEYVIA_OBSCURA_EXE must name the explicitly admitted engine')
        for port in (BACKEND, ENGINE):
            free(port)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        env = isolated_env()
        log = (SCRATCH / "backend.log").open("wb")
        backend = subprocess.Popen([str(PYTHON), "scripts/run_web_backend.py", "--host", "127.0.0.1", "--port", str(BACKEND),
                                    "--root", str(SMALL_STATE or SCRATCH).replace("\\", "/"), "--static-root", str(BUILD).replace("\\", "/"),
                                    "--skip-runtime-auto-update", "--skip-proof-self-check"],
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        self.processes.append(backend)
        await_http(f"http://127.0.0.1:{BACKEND}/api/health", backend)
        self.receipt.setdefault('listeners', []).append(owned_listener(BACKEND, backend))
        token = secrets.token_urlsafe(36)
        elog = (SCRATCH / "engine.log").open("ab")
        engine = subprocess.Popen([str(EXE), "serve", "--host", "127.0.0.1", "--port", str(ENGINE), "--user-agent", UA, "--max-connections", "8", "--allow-private-network"],
                                  stdout=elog, stderr=elog, creationflags=subprocess.CREATE_NO_WINDOW,
                                  env={**env, "OBSCURA_CDP_TOKEN": token, "OBSCURA_ROTATE_PROFILE": "0", "OBSCURA_NAV_TIMEOUT_MS": "30000", "OBSCURA_SCRIPT_DEADLINE_MS": "20000"})
        self.processes.append(engine)
        await_http(f"http://127.0.0.1:{ENGINE}/json/version", engine, {"Authorization": "Bearer " + token})
        self.receipt.setdefault('listeners', []).append(owned_listener(ENGINE, engine))
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        endpoint = f"ws://127.0.0.1:{ENGINE}/devtools/browser" if self.direct_cdp else f"http://127.0.0.1:{ENGINE}"
        self.browser = self.playwright.chromium.connect_over_cdp(endpoint, headers={"Authorization": "Bearer " + token}, timeout=self.connect_timeout)
        self.receipt["engine"] = {"exe": str(EXE), "sha256": hashlib.sha256(EXE.read_bytes()).hexdigest()}

    def session(self, viewport):
        if self.context:
            self.context.close()
        self.context = self.browser.new_context(user_agent=UA, viewport=viewport)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.receipt["errors"].append(str(error)[:300]))
        origin = f"http://127.0.0.1:{BACKEND}"
        # Use this context's cookie jar for the real local-session bootstrap.
        # A fetch evaluated in a document can be interrupted by cold navigation.
        status = self.context.request.post(origin + "/api/auth/local-session", data={}, timeout=30000).status
        self.receipt.setdefault("auth", []).append(status)
        if status != 200:
            raise RuntimeError(f"Local-session bootstrap failed: {status}")
        self.context.request.post(origin + '/api/backend', data={'command':'onboarding_save_command', 'payload':{'dismissed':True}}, timeout=30000)
        # Canonical Settings owns the look after hydration. Browser storage
        # alone can be superseded by that record during a cold mount.
        response = self.context.request.post(origin + '/api/backend', data={'command':'settings_get_command', 'payload':{}}, timeout=30000)
        value = response.json()
        prefs = value.get('data', value)
        if response.status != 200 or value.get('ok') is False or 'revision' not in prefs:
            raise RuntimeError('Tour could not read its isolated Settings revision')
        saved = self.context.request.post(origin + '/api/backend', data={'command':'settings_update_command', 'payload':{
            'patch':{'theme':{'dark':'forest','light':'morning','sunset':'sunset','night':'night-green'}[THEME], 'density':'workshop'},
            'expectedRevision':prefs['revision']}}, timeout=30000)
        if saved.status != 200 or saved.json().get('ok') is False:
            raise RuntimeError('Tour could not save its isolated theme')
        # Set origin storage before a single React mount; bootstrap uses the
        # context cookie jar so it cannot be interrupted by cold navigation.
        self.page.goto(origin + "/api/health", wait_until="load")
        self.page.evaluate("""theme => { localStorage.setItem('nx.os.theme', JSON.stringify(theme)); localStorage.removeItem('nx.os.layout'); localStorage.removeItem('nx.os.placements'); localStorage.setItem('nx.os.density', JSON.stringify('workshop')); }""", THEME)
        self.page.goto(origin + "/control", wait_until="load")
        self.wait("() => !!document.querySelector('.nx-root')", 40)
        self.wait("theme => document.querySelector('.nx-root')?.getAttribute('data-nx-theme') === theme", 30, THEME)
        time.sleep(1.5)
        # Setup was dismissed for this isolated user; close it if it still shows.
        self.page.evaluate("() => document.querySelector('.nx-onboarding [aria-label=\"Close\"], .nx-onb-skip')?.click()")

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

    def shot(self, name):
        path = OUT / f"{name}.png"
        actual = self.js("() => document.querySelector('.nx-root')?.getAttribute('data-nx-theme')")
        self.receipt['checks'].append({'name':f'{name}: rendered theme matches requested theme', 'ok':actual == THEME,
                                      'requested':THEME, 'actual':actual})
        time.sleep(1.0)  # Obscura paints a moment after the DOM changes
        self.page.screenshot(path=str(path), full_page=False)
        return path

    def stop(self):
        for closer in (lambda: self.context and self.context.close(), lambda: self.browser and self.browser.close(), lambda: self.playwright and self.playwright.stop()):
            try:
                closer()
            except Exception as exc:
                self.receipt["errors"].append(f"close: {exc}")
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()


# ---- the product's own controls, driven with real DOM events ---------------------------------

KEY = """([key, code, ctrl, alt, shift, target]) => {
  const el = target ? document.querySelector(target) : (document.activeElement || document.body);
  const init = { key, code, ctrlKey: ctrl, altKey: alt, shiftKey: shift, bubbles: true, cancelable: true };
  el.dispatchEvent(new KeyboardEvent('keydown', init)); el.dispatchEvent(new KeyboardEvent('keyup', init));
}"""

TYPE = """text => {
  const el = document.activeElement;
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, text);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}"""

CLICK = """selector => { const el = document.querySelector(selector); if (!el) return false; el.click(); return true; }"""


def open_from_launcher(rig, query, expect_title):
    if query.startswith("files:"):
        open_from_launcher(rig, "Files", "Files")
        slash = "const fwd = v => v.split(String.fromCharCode(92)).join('/');"
        target = query[6:].replace(chr(92), "/")
        rig.wait("() => document.querySelectorAll('.nx-files-placepick option').length > 0", 15)
        place = rig.js("t => { " + slash + """ const s = document.querySelector('.nx-files-placepick');
          const o = [...s.options].map(o => o.value).filter(v => t.toLowerCase().startsWith(fwd(v).toLowerCase())).sort((a, b) => b.length - a.length)[0];
          if (!o) return null; Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, o); s.dispatchEvent(new Event('change', { bubbles: true })); return fwd(o); }""", target)
        if not place:
            raise AssertionError("Files has no place containing " + target)
        for name in target[len(place):].strip("/").split("/"):
            find = "[...document.querySelectorAll('[data-path]')].find(e => fwd(e.dataset.path).endsWith('/' + n))"
            rig.wait("n => { " + slash + " return !!" + find + "; }", 15, name)
            rig.js("n => { " + slash + " " + find + ".dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); }", name)
            time.sleep(0.8)
        rig.wait("t => [...document.querySelectorAll('.nx-surface .nx-stage-title strong')].some(e => e.textContent.trim() === t)", 25, expect_title)
        # The document was opened from Files. Close that caller through its
        # actual control so the placement journey measures one app and chat.
        files_window = window_id(rig, 'Files')
        if files_window:
            rig.js("id => document.querySelector(`[data-window=\"${CSS.escape(id)}\"] .nx-stage-head > button[aria-label^=\"Close\"]`)?.click()", files_window)
            rig.wait("id => !document.querySelector(`[data-window=\"${CSS.escape(id)}\"]`)", 10, files_window)
        time.sleep(1.5)
        return
    if query.startswith("tool:"):
        status = rig.js("""([tool, source]) => fetch('/api/ui/tools/call', {method:'POST', credentials:'include', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({tool, arguments: {source}})}).then(async r => ({status: r.status, body: (await r.text()).slice(0, 600)}))""", [query[5:], str(PDF)])
        rig.receipt.setdefault("toolCalls", []).append({"tool": query[5:], "status": status})
        rig.wait("t => [...document.querySelectorAll('.nx-surface .nx-stage-title strong')].some(e => e.textContent.trim() === t)", 25, expect_title)
        time.sleep(1.2)
        return
    rig.js("() => { const s = document.querySelector('.nx-launcher'); if (s) document.activeElement?.blur(); }")
    rig.js(KEY, [" ", "Space", True, False, False, None])
    rig.wait("() => !!document.querySelector('.nx-launcher input')", 10)
    rig.js("() => document.querySelector('.nx-launcher input').focus()")
    rig.js(TYPE, query)
    time.sleep(0.6)
    clicked = rig.js("""q => { const option = [...document.querySelectorAll('.nx-result:not(.is-disabled)')].find(o => o.querySelector('.nx-result-title')?.textContent.trim() === q);
      if (!option) return false; option.click(); return true; }""", query)
    if not clicked:
        rig.js(KEY, ["Enter", "Enter", False, False, False, ".nx-launcher input"])
    rig.wait("t => [...document.querySelectorAll('.nx-surface .nx-stage-title strong')].some(e => e.textContent.trim() === t)", 25, expect_title)
    time.sleep(1.2)


def window_id(rig, title):
    return rig.js("t => [...document.querySelectorAll('.nx-surface')].find(s => s.querySelector('.nx-stage-title strong')?.textContent.trim() === t)?.dataset.window || null", title)


def press_place(rig, wid, label_start):
    ok = rig.js("""([id, label]) => {
      const frame = document.querySelector(`[data-window="${CSS.escape(id)}"]`);
      const button = [...frame.querySelectorAll('.nx-place button')].find(b => (b.getAttribute('aria-label') || '').startsWith(label));
      if (!button) return false; button.click(); return true; }""", [wid, label_start])
    if not ok:
        raise AssertionError(f"No placement button '{label_start}' on {wid}")
    time.sleep(0.7)


def placement_of(rig, wid):
    return rig.js("id => { const f = document.querySelector(`[data-window=\"${CSS.escape(id)}\"]`); if (!f) return null; const r = f.getBoundingClientRect(); return { placement: f.dataset.placement, hidden: f.classList.contains('is-hidden'), x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }; }", wid)


def close_all(rig):
    for _ in range(12):
        if not rig.js(CLICK, ".nx-surface .nx-stage-head > button[aria-label^='Close']"):
            # Bubbled windows are hidden; close them from the bubble with Delete.
            if not rig.js("() => { const b = document.querySelector('.nx-wbubble'); if (!b) return false; b.focus(); b.dispatchEvent(new KeyboardEvent('keydown', {key:'Delete', bubbles:true, cancelable:true})); return true; }"):
                break
        time.sleep(0.4)


def probe(rig):
    info = rig.js("() => ({ es: typeof EventSource, ro: typeof ResizeObserver, inert: 'inert' in HTMLElement.prototype, has: CSS.supports('selector(:has(a))'), cm: CSS.supports('color', 'color-mix(in srgb, red 50%, blue)'), w: innerWidth, h: innerHeight, bus: document.querySelector('.nx-strip')?.innerText?.slice(0, 200) })")
    rig.receipt["probe"] = info
    rig.shot("probe-home")
    print(json.dumps(info))


def run(args):
    OUT.mkdir(parents=True, exist_ok=True)
    receipt = {"schema": "neyvia.placement-shots.v1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ports": {"backend": BACKEND, "engine": ENGINE},
               "viewports": {"desktop": DESKTOP, "phone": PHONE}, "theme": THEME, "build": str(BUILD), "runtimeStateRoot":str(SMALL_STATE or SCRATCH), "shots": [], "checks": [], "errors": [],
               "registry":REGISTRY_APPS, "requestedApps":[a[0] for a in APPS if not args.only or a[0] in args.only.split(',')]}
    rig = Rig(receipt)
    try:
        rig.start()
        if getattr(args, 'listeners_only', False):
            receipt['scope'] = 'Owned listener identity only; no application journey or render proof'
            receipt['requestedApps'] = []
            receipt['checks'].append({'name':'backend and engine belong to exact owned child PIDs',
                                      'ok':len(receipt.get('listeners', [])) == 2})
            receipt['ok'] = receipt['checks'][0]['ok']
            return receipt
        rig.session(DESKTOP)
        if args.probe:
            probe(rig)
            return receipt
        from placement_journeys import run_journeys  # the shot list lives next to this file
        run_journeys(rig, receipt, args, sys.modules[__name__])
        receipt["ok"] = all(check["ok"] for check in receipt["checks"])
    except Exception as exc:
        receipt["ok"] = False
        receipt["failure"] = f"{type(exc).__name__}: {exc}"
        receipt["traceback"] = traceback.format_exc()
        try:
            rig.shot("failure")
        except Exception:
            pass
    finally:
        rig.stop()
        (OUT / ("probe.json" if args.probe else f"receipt-{args.tag}.json")).write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"ok": receipt.get("ok"), "failure": receipt.get("failure"), "shots": len(receipt["shots"]), "checks": len(receipt["checks"])}))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--listeners-only", action="store_true", help="Verify exact owned backend/engine PIDs without opening an application")
    parser.add_argument("--only", default="")
    parser.add_argument("--phone-only", action="store_true")
    parser.add_argument("--library-handoff", action="store_true", help="Also observe the Library's real unsent domain draft and saved layout")
    parser.add_argument("--ports", required=True)
    parser.add_argument("--tag", default="all")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--scratch", type=Path, default=SCRATCH)
    parser.add_argument("--build-dir", type=Path, default=BUILD)
    parser.add_argument("--theme", choices=("dark", "light", "sunset", "night"), default="dark")
    parser.add_argument("--local-small-state", action="store_true")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    parsed = parser.parse_args()
    OUT, SCRATCH, BUILD, THEME = parsed.output.resolve(), parsed.scratch.resolve(), parsed.build_dir.resolve(), parsed.theme
    for destination in (OUT, SCRATCH):
        if not destination.is_relative_to(Path(r'D:\NeyviaRuns').resolve()):
            parser.error('Render and scratch output must remain below D:/NeyviaRuns')
    if not (BUILD / "index.html").is_file():
        parser.error("Build directory must contain index.html")
    use_ports(*map(int, parsed.ports.split(",")))
    SCRATCH = SCRATCH / parsed.tag
    # The actual PDF fixture must be inside this run's isolated Files home.
    # Preserve its bytes, rather than depending on another checkout's places.
    if any(app[1].startswith('files:') for app in APPS):
        import shutil
        fixture = SCRATCH / 'home/tour-fixtures/INTN.pdf'
        fixture.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PDF, fixture)
        APPS = [(app, 'files:' + str(fixture) if query.startswith('files:') else query, title) for app, query, title in APPS]
    if parsed.local_small_state:
        if not parsed.tag.replace('-', '').isalnum(): parser.error('Invalid small-state label')
        SMALL_STATE = ROOT / '.agent_control/INTN/tour-state' / parsed.tag
        SMALL_STATE.mkdir(parents=True, exist_ok=True)
    result = run(parsed)
    raise SystemExit(0 if result.get("ok", True) else 1)
