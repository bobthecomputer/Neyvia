"""Onboarding (track ONB) screenshots, rendered in Neyvia's Obscura engine.

python scripts/onb_shots.py --ports 49241,49242 --dist D:/NeyviaRuns/29-ONB/dist --out D:/NeyviaRuns/29-ONB/shots \
    [--themes dark,light] [--sizes 1440,390] [--only welcome,unique,downloads,connections,done,help] [--mock-components]

Reuses the placement rig (scripts/placement_shots.py): one backend over this worktree with an isolated HOME and
one Obscura, ports taken from the track's block (49241-49249). The page is the production build in --dist.

--mock-components answers components_*_command inside the page (fetch wrapper) with the row shape INST documents
in plans/logs/29-INST-progress.md ("INST API"), built from config/components.json, until INST's backend is merged.
The receipt says so. Installing flips the row to "current" after a short delay, so the switch is really pressed.

Obscura paints no iframes, WebGL or web fonts: fonts here are the fallback stack.
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
SIZES = {"1440": {"width": 1440, "height": 900}, "390": {"width": 390, "height": 844}}

MOCK = """(manifest) => {
  const rows = manifest.components.map(c => ({ ...c, state: c.required || c.group === 'core' ? 'current' : 'not-installed', installedVersion: c.required || c.group === 'core' ? '0.2.2' : '', bundledVersion: '0.2.2', installedAt: '', detail: '', optedIn: false, appVersion: '0.2.2' }));
  const by = Object.fromEntries(rows.map(r => [r.id, r]));
  by['laya-weights'].state = 'check-only'; by['laya-weights'].installedVersion = 'laya-1b-2026.09';
  by['dictation'].state = 'check-only'; by['dictation'].installedVersion = 'phonon-2.1';
  by['gamedev-bridges'].state = 'check-only'; by['gamedev-bridges'].installedVersion = '0.4.0';
  by['app-updater'].state = 'current'; by['app-updater'].installedVersion = '0.2.2';
  const scenario = (new URLSearchParams(location.search).get('mock') || localStorage.getItem('onb.mock') || 'fresh');
  if (scenario === 'nocodex') { by['claude-mod'].state = 'unavailable'; by['claude-mod'].detail = 'Claude Code is not installed on this PC.'; }
  if (scenario === 'on') { by['claude-mod'].state = 'current'; by['claude-mod'].installedVersion = '0.2.2'; by['codex-skills'].state = 'update-available'; by['codex-skills'].installedVersion = '0.2.1'; }
  if (scenario === 'adopt') { by['codex-skills'].unmanaged = ['neyvia-pdf', 'neyvia-lab']; }
  const realFetch = window.fetch.bind(window);
  window.fetch = async (url, init) => {
    try {
      if (String(url).endsWith('/api/backend') && init && init.body) {
        const body = JSON.parse(init.body);
        if (String(body.command).startsWith('components_')) {
          const id = body.payload && body.payload.component;
          const reply = data => new Response(JSON.stringify({ ok: true, data }), { status: 200, headers: { 'Content-Type': 'application/json' } });
          if (body.command === 'components_status_command') return reply({ ok: true, appVersion: '0.2.2', compat: { neyviaApi: '1', sdkAbi: '1' }, components: rows });
          if (body.command === 'components_install_command') { await new Promise(r => setTimeout(r, 1400)); by[id].state = 'current'; by[id].installedVersion = '0.2.2'; return reply({ ok: true, status: 'installed', state: by[id] }); }
          if (body.command === 'components_remove_command') { await new Promise(r => setTimeout(r, 600)); by[id].state = 'not-installed'; by[id].installedVersion = ''; return reply({ ok: true, status: 'removed', state: by[id] }); }
          if (body.command === 'components_update_command') { await new Promise(r => setTimeout(r, 900)); by[id].state = 'current'; by[id].installedVersion = '0.2.2'; return reply({ ok: true, status: 'updated', state: by[id] }); }
        }
      }
    } catch (e) { /* fall through to the real service */ }
    return realFetch(url, init);
  };
}"""

def patient_await_http(url, process, headers=None):
    """The backend can take a few minutes to answer on this PC when RAM is tight."""
    import urllib.request
    for _ in range(1500):
        if process.poll() is not None:
            raise RuntimeError(f"Process exited before {url}: {process.returncode}")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=1.0) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(url)


shots.await_http = patient_await_http
KEYS = shots.KEY
TYPE = shots.TYPE


def check(receipt, label, ok, **extra):
    receipt["checks"].append({"label": label, "ok": bool(ok), **extra})
    print(("PASS " if ok else "FAIL ") + label, flush=True)


def open_setup(rig, query="Setup and tour"):
    """Open setup the way a person does: Ctrl+Space, type, pick the result."""
    rig.js("() => { const s = document.querySelector('.nx-launcher'); if (s) document.activeElement?.blur(); }")
    rig.js(KEYS, [" ", "Space", True, False, False, None])
    rig.wait("() => !!document.querySelector('.nx-launcher input')", 10)
    rig.js("() => document.querySelector('.nx-launcher input').focus()")
    rig.js(TYPE, query)
    try:
        rig.wait("() => !!document.querySelector('.nx-result:not(.is-disabled)')", 15)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.6)
    clicked = rig.js("""q => { const o = [...document.querySelectorAll('.nx-result:not(.is-disabled)')].find(o => o.querySelector('.nx-result-title')?.textContent.trim() === q);
      if (!o) return false; o.click(); return true; }""", query)
    if not clicked:
        rig.js(KEYS, ["Enter", "Enter", False, False, False, ".nx-launcher input"])
    rig.wait("() => !!document.querySelector('.nx-onb')", 15)
    # The service can be slow to answer on this PC: wait for the step itself, not the dialog frame.
    rig.wait("() => !!document.querySelector('.nx-onb-scroll, .nx-tour-screen')", 240)
    time.sleep(0.8)


def go_step(rig, index):
    rig.js("i => document.querySelectorAll('.nx-onb-rail-step')[i]?.click()", index)
    time.sleep(0.9)


def snap(rig, receipt, name, out_dir):
    path = out_dir / f"{name}.png"
    time.sleep(0.8)
    rig.page.screenshot(path=str(path), full_page=False)
    receipt["shots"].append(str(path))
    return path


def run(args):
    ports = [int(p) for p in args.ports.split(",")]
    shots.BACKEND, shots.ENGINE = ports
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shots.OUT = out
    shots.SCRATCH = Path(args.state)
    shots.BUILD = Path(args.dist)
    receipt = {"checks": [], "errors": [], "shots": [], "mockComponents": bool(args.mock_components), "sizes": args.sizes, "themes": args.themes}
    manifest = json.loads((ROOT / "config/components.json").read_text(encoding="utf-8")) if (ROOT / "config/components.json").exists() else None
    if args.mock_components and manifest is None:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    only = set(args.only.split(",")) if args.only else None
    rig = shots.Rig(receipt)
    try:
        rig.start()
        for theme in args.themes.split(","):
            shots.THEME = theme
            for size in args.sizes.split(","):
                tag = f"{theme}-{size}"
                rig.session(SIZES[size])
                if args.mock_components:
                    rig.page.evaluate(f"({MOCK})({json.dumps(manifest)})")
                try:
                    rig.page.emulate_media(reduced_motion="reduce")
                except Exception as exc:  # noqa: BLE001
                    receipt["errors"].append(f"emulate_media: {exc}")
                open_setup(rig)
                steps = ["welcome", "unique", "downloads", "connections", "done"]
                for index, name in enumerate(steps):
                    if only and name not in only:
                        continue
                    go_step(rig, index)
                    if name == "unique":
                        # Each chapter's finished frame (reduced motion shows the last frame of a chapter).
                        count = rig.js("() => document.querySelectorAll('.nx-tour-seg').length")
                        for c in range(count):
                            rig.js("c => document.querySelectorAll('.nx-tour-seg')[c]?.click()", c)
                            try:
                                rig.wait("() => !!document.querySelector('.nx-tour-canvas .nx-tour-os, .nx-tour-canvas .nx-tour-stage, .nx-tour-canvas .nx-tour-feature')", 30)
                            except Exception as exc:  # noqa: BLE001
                                receipt["errors"].append(f"unique {c + 1}: scene never mounted ({exc})")
                            time.sleep(1.5)
                            title = rig.js("() => document.querySelector('.nx-tour-caption h3')?.textContent || ''")
                            snap(rig, receipt, f"{tag}-unique-{c + 1}", out)
                            check(receipt, f"{tag} unique chapter {c + 1} shows a caption ({title})", bool(title))
                    elif name == "downloads":
                        snap(rig, receipt, f"{tag}-downloads-top", out)
                        rig.js("() => document.querySelector('[data-component=\"claude-mod\"]')?.scrollIntoView({ block: 'center' })")
                        snap(rig, receipt, f"{tag}-downloads-mods", out)
                        # Press the Claude Code switch for real.
                        before = rig.js("() => document.querySelector('[data-component=\"claude-mod\"] input')?.checked")
                        rig.js("() => document.querySelector('[data-component=\"claude-mod\"] input')?.click()")
                        time.sleep(0.5)
                        snap(rig, receipt, f"{tag}-downloads-installing", out)
                        time.sleep(2.0)
                        after = rig.js("() => document.querySelector('[data-component=\"claude-mod\"] input')?.checked")
                        check(receipt, f"{tag} Claude Code switch turns on after the install answers", before is False and after is True, before=before, after=after)
                        snap(rig, receipt, f"{tag}-downloads-on", out)
                        rig.js("() => { const s = document.querySelector('.nx-onb-scroll'); if (s) s.scrollTop = 99999; }")
                        rig.js("() => document.querySelector('.nx-onb-chips')?.scrollIntoView({ block: 'start' })")
                        rig.js("() => document.querySelector('.nx-onb-chip')?.click()")
                        time.sleep(0.6)
                        snap(rig, receipt, f"{tag}-downloads-packs", out)
                    else:
                        if name in ("connections", "done"):
                            try:
                                rig.wait("() => (!!document.querySelector('.nx-cn-line') && !/Looking at this one/.test(document.querySelector('.nx-onb-slot')?.innerText || '')) || !!document.querySelector('.nx-onb-summary .is-ok, .nx-onb-error')", 240)
                            except Exception as exc:  # noqa: BLE001
                                receipt["errors"].append(f"{name}: agents never listed ({exc})")
                        snap(rig, receipt, f"{tag}-{name}", out)
                # Help: the tour of what makes Neyvia different, tour-only.
                if not only or "help" in only:
                    rig.js(KEYS, ["Escape", "Escape", False, False, False, None])
                    time.sleep(0.8)
                    open_setup(rig, "What makes Neyvia different")
                    snap(rig, receipt, f"{tag}-help", out)
                    check(receipt, f"{tag} help tour opens as tour-only", bool(rig.js("() => !!document.querySelector('.nx-onb.is-tour-only')")))
        receipt["errors"] = receipt["errors"] + []
    except Exception:  # noqa: BLE001
        receipt["errors"].append(traceback.format_exc())
        raise
    finally:
        rig.stop()
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print("receipt", out / "receipt.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ports", required=True)
    parser.add_argument("--dist", default=r"D:\NeyviaRuns\29-ONB\dist")
    parser.add_argument("--out", default=r"D:\NeyviaRuns\29-ONB\shots")
    parser.add_argument("--state", default=r"D:\NeyviaRuns\29-ONB\state")
    parser.add_argument("--themes", default="dark,light")
    parser.add_argument("--sizes", default="1440,390")
    parser.add_argument("--only", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--mock-components", action="store_true")
    run(parser.parse_args())
