"""Self-made practice for LAYA's eyes (plan 24 step 5): free, perfectly labelled episodes.

Real Neyvia pages are rendered in the admitted headless Obscura engine (no window, private
ports 49131/49132). On each page state LAYA injects ONE known defect through the DOM, takes
the screenshot, and reverts the injection (verified: no marker left). Because LAYA made the
defect, it knows the answer exactly, at region level:
  * the injected region on the injected screenshot is a positive for the injected type;
  * the same region on the base screenshot (before injection) is a negative.
Injections: overlap-text, overlap-icon, off-screen-control, see-through, clipped-text,
raw-error, encoded-path, internal-id, unreadable-contrast.

Usage: python scripts/vision_practice.py --out D:/NeyviaRuns/VISION/practice [--build DIR]
Output: <out>/practice.json + screenshots. ``region_counts`` turns episodes into
calibration counts for a lens set (used by scripts/vision_stream.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
PORTS = (49131, 49132)
DEFAULT_BUILD = Path('D:/NeyviaRuns/ui-fix2/build-final2')
APPS = ['home', 'files', 'notes', 'terminal', 'laya', 'app-factory', 'agent-view', 'memory', 'browser', 'image-studio', 'citecraft']
INJECTIONS = ['overlap-text', 'overlap-icon', 'off-screen-control', 'see-through', 'clipped-text', 'raw-error',
              'encoded-path', 'internal-id', 'unreadable-contrast']
TYPE_OF = {'overlap-text': 'overlap', 'overlap-icon': 'overlap', 'off-screen-control': 'off-screen-control',
           'see-through': 'see-through', 'clipped-text': 'clipped-text', 'raw-error': 'raw-error',
           'encoded-path': 'encoded-path', 'internal-id': 'internal-id', 'unreadable-contrast': 'unreadable-contrast'}

# One JS function per injection: (kind, seed, payload) -> {ok, region, detail}. Injected
# elements carry data-vp="1"; changed inline styles are saved in window.__vpUndo.
INJECT = r"""
([kind, seed, payload]) => {
  let s = seed >>> 0; const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  window.__vpUndo = window.__vpUndo || [];
  const vw = innerWidth, vh = innerHeight;
  const visible = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 6 && r.height > 6 && r.left >= 2 && r.top >= 2 && r.right <= vw - 2 && r.bottom <= vh - 2
      && cs.visibility !== 'hidden' && parseFloat(cs.opacity || '1') > 0.5; };
  const ownText = el => Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
  const labels = Array.from(document.querySelectorAll('.nx-root *')).filter(el => {
    const t = ownText(el); return t.length >= 4 && t.length <= 40 && /[A-Za-z]{3}/.test(t) && visible(el)
      && el.getBoundingClientRect().height < 40 && !el.closest('[data-vp]'); });
  if (!labels.length) return {ok: false, detail: 'no visible text label'};
  const pick = arr => arr[Math.floor(rnd() * arr.length)];
  const box = r => ({x: r.left, y: r.top, w: r.width, h: r.height});
  const union = (a, b) => { const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y);
    return {x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y}; };
  const styled = (el, props) => { window.__vpUndo.push([el, el.getAttribute('style')]); for (const [k, v] of Object.entries(props)) el.style.setProperty(k, v, 'important'); };
  const ghost = (from, text) => { const cs = getComputedStyle(from); const d = document.createElement('div'); d.dataset.vp = '1';
    d.textContent = text; Object.assign(d.style, {position: 'fixed', zIndex: 2147483000, font: cs.font, color: cs.color,
      whiteSpace: 'nowrap', pointerEvents: 'none', letterSpacing: cs.letterSpacing}); document.body.appendChild(d); return d; };
  const bgOf = el => { let e = el; while (e) { const c = getComputedStyle(e).backgroundColor; if (c && !/rgba\(0, 0, 0, 0\)|transparent/.test(c)) return c; e = e.parentElement; } return 'rgb(255,255,255)'; };
  if (kind === 'overlap-text') {
    const a = pick(labels); const ra = a.getBoundingClientRect();
    const others = labels.filter(l => l !== a);
    const text = others.length ? ownText(pick(others)) : 'Overlapping label';
    const d = ghost(a, text); d.style.left = (ra.left + ra.width * (0.25 + rnd() * 0.4)) + 'px'; d.style.top = (ra.top + ra.height * (rnd() * 0.3 - 0.15)) + 'px';
    return {ok: true, region: union(box(ra), box(d.getBoundingClientRect())), detail: {label: ownText(a), over: text}};
  }
  if (kind === 'overlap-icon') {
    // A status/moon/gear style glyph drawn into the end of a label (the "No agents running runs into
    // the Night Shift icon" family). Drawn with CSS so every engine paints it.
    const a = pick(labels); const ra = a.getBoundingClientRect(); const cs = getComputedStyle(a);
    const size = Math.max(12, Math.min(20, ra.height * 0.95));
    const wrap = document.createElement('div'); wrap.dataset.vp = '1';
    const shape = Math.floor(rnd() * 3);
    Object.assign(wrap.style, {position: 'fixed', zIndex: 2147483000, width: size + 'px', height: size + 'px', pointerEvents: 'none',
      left: (ra.right - size * (0.3 + rnd() * 0.5)) + 'px', top: (ra.top + (ra.height - size) / 2) + 'px', boxSizing: 'border-box',
      borderRadius: shape === 2 ? '3px' : '50%', border: `2px solid ${cs.color}`,
      boxShadow: shape === 0 ? `inset ${size * 0.28}px -${size * 0.12}px 0 0 ${cs.color}` : 'none'});
    if (shape === 1) { const dot = document.createElement('div'); Object.assign(dot.style, {position: 'absolute', left: '30%', top: '30%', width: '40%', height: '40%', borderRadius: '50%', background: cs.color}); wrap.appendChild(dot); }
    document.body.appendChild(wrap);
    return {ok: true, region: union(box(ra), box(wrap.getBoundingClientRect())), detail: {label: ownText(a), shape}};
  }
  if (kind === 'off-screen-control') {
    const buttons = Array.from(document.querySelectorAll('.nx-root button, .nx-root [role=button]')).filter(b => visible(b) && (b.innerText || '').trim().length >= 3 && b.getBoundingClientRect().width < 260);
    if (!buttons.length) return {ok: false, detail: 'no button'};
    const b = pick(buttons); const rb = b.getBoundingClientRect(); const c = b.cloneNode(true); c.dataset.vp = '1';
    const cs = getComputedStyle(b);
    Object.assign(c.style, {position: 'fixed', zIndex: 2147483000, width: rb.width + 'px', height: rb.height + 'px', margin: 0, background: cs.backgroundColor, color: cs.color, font: cs.font, border: cs.border, borderRadius: cs.borderRadius, padding: cs.padding, display: cs.display === 'inline' ? 'inline-block' : cs.display});
    const edge = rnd() < 0.6 ? 'right' : 'bottom';
    if (edge === 'right') { c.style.left = (vw - rb.width * (0.35 + rnd() * 0.3)) + 'px'; c.style.top = (60 + rnd() * (vh - 140)) + 'px'; }
    else { c.style.top = (vh - rb.height * (0.35 + rnd() * 0.3)) + 'px'; c.style.left = (80 + rnd() * (vw - 360)) + 'px'; }
    document.body.appendChild(c); const r = c.getBoundingClientRect();
    const reg = {x: r.left, y: r.top, w: Math.min(r.right, vw) - r.left, h: Math.min(r.bottom, vh) - r.top};
    return {ok: true, region: reg, detail: {button: (b.innerText || '').trim().slice(0, 40), edge}};
  }
  if (kind === 'see-through') {
    // A floating panel whose body is translucent: page text shows through, colliding with its own title.
    const a = pick(labels); const ra = a.getBoundingClientRect();
    const w = Math.min(vw - 40, 360 + rnd() * 200), h = Math.min(vh - 40, 220 + rnd() * 160);
    const x = Math.max(10, Math.min(vw - w - 10, ra.left - 40)), y = Math.max(10, Math.min(vh - h - 10, ra.top - 30));
    const p = document.createElement('div'); p.dataset.vp = '1';
    const surf = bgOf(document.querySelector('.nx-root')); const rgb = (surf.match(/\d+(\.\d+)?/g) || [255, 255, 255]).slice(0, 3).join(',');
    Object.assign(p.style, {position: 'fixed', zIndex: 2147483000, left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px',
      background: `rgba(${rgb},${0.35 + rnd() * 0.25})`, border: '1px solid rgba(127,127,127,.6)', borderRadius: '14px', boxShadow: '0 12px 40px rgba(0,0,0,.25)',
      font: getComputedStyle(a).font, color: getComputedStyle(a).color, padding: '14px 18px', pointerEvents: 'none'});
    p.innerHTML = '<div style="font-weight:600;font-size:15px">' + (payload || 'Panel') + '</div><div style="margin-top:10px;font-size:13px">Recent items</div>';
    document.body.appendChild(p);
    return {ok: true, region: box(p.getBoundingClientRect()), detail: {over: ownText(a), title: payload}};
  }
  if (kind === 'clipped-text') {
    const cands = labels.filter(l => ownText(l).length >= 6);
    if (!cands.length) return {ok: false, detail: 'no long label'};
    const a = pick(cands); const ra = a.getBoundingClientRect();
    styled(a, {'text-indent': (-0.35 - rnd() * 0.4) + 'em', overflow: 'hidden', 'white-space': 'nowrap', 'text-overflow': 'ellipsis',
      'max-width': Math.max(18, ra.width * (0.45 + rnd() * 0.2)) + 'px', display: 'inline-block'});
    a.dataset.vpStyled = '1';
    return {ok: true, region: box(a.getBoundingClientRect()), detail: {label: ownText(a)}};
  }
  if (kind === 'raw-error' || kind === 'encoded-path' || kind === 'internal-id') {
    // Replace the words of a real label (the product showing the wrong copy), not a sticker on top.
    const cands = labels.filter(l => l.getBoundingClientRect().width >= 60);
    const a = pick(cands.length ? cands : labels);
    const node = Array.from(a.childNodes).find(n => n.nodeType === 3 && n.textContent.trim());
    // A fresh element (not a mutated text node): every engine repaints new nodes.
    const span = document.createElement('span'); span.dataset.vp = '1'; span.textContent = payload;
    window.__vpText = window.__vpText || []; window.__vpText.push([span, node]);
    node.replaceWith(span); a.dataset.vpStyled = '1';
    styled(a, {'white-space': 'nowrap', 'max-width': 'none', overflow: 'visible'});
    return {ok: true, region: box(a.getBoundingClientRect()), detail: {replaced: (node.textContent || '').trim().slice(0, 40), text: payload}};
  }
  if (kind === 'unreadable-contrast') {
    const a = pick(labels.filter(l => ownText(l).length >= 6)); if (!a) return {ok: false, detail: 'no label'};
    const bg = bgOf(a); const m = (bg.match(/\d+(\.\d+)?/g) || [255, 255, 255]).slice(0, 3).map(Number);
    const lum = (m[0] + m[1] + m[2]) / 3; const shift = lum > 128 ? -18 : 18;
    styled(a, {color: `rgb(${m.map(v => Math.max(0, Math.min(255, v + shift))).join(',')})`});
    a.dataset.vpStyled = '1';
    return {ok: true, region: box(a.getBoundingClientRect()), detail: {label: ownText(a), background: bg}};
  }
  return {ok: false, detail: 'unknown kind'};
}
"""
REVERT = r"""
() => { for (const [span, node] of (window.__vpText || []).reverse()) { if (span.isConnected) span.replaceWith(node); } window.__vpText = [];
  document.querySelectorAll('[data-vp]').forEach(e => e.remove());
  for (const [el, style] of (window.__vpUndo || []).reverse()) { if (style === null) el.removeAttribute('style'); else el.setAttribute('style', style); delete el.dataset.vpStyled; }
  for (const [span, node] of (window.__vpText || []).reverse()) { if (span.isConnected) span.replaceWith(node); }
  window.__vpUndo = []; window.__vpText = []; return document.querySelectorAll('[data-vp],[data-vp-styled]').length; }
"""
PAYLOADS = {
    'raw-error': ["TypeError: Cannot read properties of undefined (reading 'map')", 'Codex app-server stopped before confirming this request.',
                  'FileNotFoundError: settings.json could not be read: ENOENT', 'Unhandled rejection: exit code 1',
                  'Run cua-driver.exe --source local to continue'],
    'encoded-path': ['raw?path=D%3A%5CNeyviaRuns%5Ctour%5Cnotes', 'D:\\NeyviaRuns\\tour\\final-verified-theme',
                     'web/src/neyvia/next/nxApi.js', 'C:\\Users\\user\\AppData\\Local\\neyvia\\state.json'],
    'internal-id': ['codex_builtin_image_gen', 'Editor · browser-null', 'neyvia.evolver.run', 'source-a1, source-b2', 'T16-runtime-directory'],
    'see-through': ['Files', 'Notes', 'Agents at work', 'Memory', 'Research'],
}


def generate(out, build, variants, apps, per_state):
    import placement_shots as shots
    from grant_agent.laya_glance_gate import _admitted_engine
    out = Path(out)
    shots_dir = out / 'shots'
    shots_dir.mkdir(parents=True, exist_ok=True)
    exe, engine_sha = _admitted_engine()
    shots.EXE, shots.BUILD = exe, Path(build)
    shots.BACKEND, shots.ENGINE = PORTS
    shots.SCRATCH = out / 'runtime'
    shots.SMALL_STATE = ROOT / '.agent_control/VISION/practice-state' / time.strftime('%Y%m%d-%H%M%S')
    shots.OUT = shots_dir
    for folder in (shots.SCRATCH, shots.SMALL_STATE):
        folder.mkdir(parents=True, exist_ok=True)
    package_paths = [p for p in sys.path if Path(p).name == 'site-packages']
    isolated = shots.isolated_env

    def render_env():
        env = isolated()
        env['PYTHONPATH'] = os.pathsep.join([str(ROOT / 'src'), *package_paths])
        return env
    shots.isolated_env = render_env
    apps_map = {a: (q, t) for a, q, t in shots.APPS}
    receipt = {'errors': [], 'checks': []}
    rig = shots.Rig(receipt, direct_cdp=True)
    episodes, bases, failures = [], [], []
    rnd = random.Random(24)
    started = time.perf_counter()
    try:
        rig.start()
        for variant in variants:
            theme, form = variant.split('-', 1)
            shots.THEME = theme
            rig.session(shots.PHONE if form == 'phone' else shots.DESKTOP)
            for app in apps:
                try:
                    shots.close_all(rig)
                    if app != 'home':
                        q, t = apps_map[app]
                        shots.open_from_launcher(rig, q, t)
                    time.sleep(0.8)
                    base = rig.shot(f'{app}-{variant}-base')
                except Exception as exc:
                    failures.append({'state': f'{app}/{variant}', 'error': f'{type(exc).__name__}: {str(exc)[:200]}'})
                    continue
                bases.append({'image': str(base), 'page': app, 'variant': variant})
                kinds = list(INJECTIONS)
                rnd.shuffle(kinds)
                for kind in kinds[:per_state]:
                    seed = rnd.randrange(1, 2 ** 31)
                    payload = rnd.choice(PAYLOADS.get(kind, ['']))
                    try:
                        result = rig.js(INJECT, [kind, seed, payload])
                        if not result or not result.get('ok'):
                            failures.append({'state': f'{app}/{variant}', 'kind': kind, 'detail': (result or {}).get('detail')})
                            rig.js(REVERT)
                            continue
                        name = f'{app}-{variant}-{kind}-{seed}'
                        shot = rig.shot(name)
                        left = rig.js(REVERT)
                        if left:
                            raise RuntimeError(f'{left} practice markers survived the revert')
                        r = {k: round(float(v), 1) for k, v in result['region'].items()}
                        episodes.append({'image': str(shot), 'base': str(base), 'page': app, 'variant': variant, 'kind': kind,
                                         'type': TYPE_OF[kind], 'region': r, 'detail': result.get('detail'), 'seed': seed,
                                         'label': 'broken', 'labelSource': 'injected by LAYA (known answer, region level)',
                                         'group': 'practice:' + app})
                    except Exception as exc:
                        failures.append({'state': f'{app}/{variant}', 'kind': kind, 'error': f'{type(exc).__name__}: {str(exc)[:200]}'})
                        try:
                            rig.js(REVERT)
                        except Exception:
                            pass
                print(f'{app}/{variant}: {len(episodes)} episodes so far', flush=True)
    except Exception as exc:
        failures.append({'fatal': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()[-1500:]})
    finally:
        rig.stop()
    data = {'schema': 'neyvia.laya.practice.v1', 'build': str(build), 'engineSha256': engine_sha, 'ports': PORTS,
            'variants': variants, 'apps': apps, 'episodes': episodes, 'bases': bases, 'failures': failures,
            'rigErrors': receipt['errors'][:20], 'seconds': round(time.perf_counter() - started, 1),
            'labels': 'region level: injected region positive for its type on the injected screenshot, negative on the base'}
    (out / 'practice.json').write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    return data


# --- practice episodes -> region-level calibration counts ---------------------

def _fired_boxes(args):
    """One image, once: the pixel glance with a lens set -> [(type, node bounds)] of its findings."""
    image, lens_entries = args
    import copy
    from vision_lens_eval import _judge_with
    from laya_glance_eval import _scene
    from grant_agent.laya_glance import transcribe
    from grant_agent.scene_core.lenses import override
    j = _judge_with((image, lens_entries, None))
    with override(lens_entries):
        scene = transcribe(copy.deepcopy(_scene(image)))
    by_id = {n['id']: n for n in scene['nodes']}
    return image, [(b['type'], by_id[b['node']]['attributes'].get('bounds')) for b in j['bugs'] if b['node'] in by_id]


def _in_region(boxes, region, predicate, pad=6):
    x0, y0, x1, y1 = region['x'] - pad, region['y'] - pad, region['x'] + region['w'] + pad, region['y'] + region['h'] + pad
    for t, nb in boxes:
        if t == predicate and nb:
            cx, cy = nb['x'] + nb['w'] / 2, nb['y'] + nb['h'] / 2
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return True
    return False


def region_counts(practice, lens_entries, workers=None):
    """Each distinct screenshot is judged once (bases are shared by many episodes; judging them
    in parallel raced on the OCR/scene caches)."""
    from concurrent.futures import ProcessPoolExecutor
    workers = workers or int(os.environ.get("VISION_WORKERS", "6"))
    from grant_agent.laya_glance import TYPES
    from laya_glance_eval import _scene
    images = sorted({ep['image'] for ep in practice['episodes']} | {ep['base'] for ep in practice['episodes']})
    for image in images:  # fill the OCR/scene caches serially first (cheap when cached)
        _scene(image)
    with ProcessPoolExecutor(workers) as pool:
        boxes = dict(pool.map(_fired_boxes, [(i, lens_entries) for i in images], chunksize=4))
    counts = {t: {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0} for t in TYPES}
    for ep in practice['episodes']:
        t = ep['type']
        counts[t]['tp' if _in_region(boxes[ep['image']], ep['region'], t) else 'fn'] += 1
        counts[t]['fp' if _in_region(boxes[ep['base']], ep['region'], t) else 'tn'] += 1
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='D:/NeyviaRuns/VISION/practice')
    ap.add_argument('--build', default=str(DEFAULT_BUILD))
    ap.add_argument('--variants', default='dark-desktop,light-desktop')
    ap.add_argument('--apps', default=','.join(APPS))
    ap.add_argument('--per-state', type=int, default=9)
    ap.add_argument('--counts', action='store_true', help='print region counts for the current registry lenses')
    a = ap.parse_args()
    if a.counts:
        from grant_agent.scene_core.lenses import load
        data = json.loads((Path(a.out) / 'practice.json').read_text(encoding='utf-8'))
        print(json.dumps(region_counts(data, [e for e in load()['lenses'] if e['status'] == 'active']), indent=1))
        return
    data = generate(a.out, a.build, a.variants.split(','), a.apps.split(','), a.per_state)
    print(json.dumps({'episodes': len(data['episodes']), 'bases': len(data['bases']), 'failures': len(data['failures']),
                      'seconds': data['seconds']}, indent=1))


if __name__ == '__main__':
    main()
