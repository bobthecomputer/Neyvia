"""UI fix actions for the shared Scene core (plan 23: "CSS/token patches").

A *tree source* is a web source tree (a worktree, or a commit exported with
``vite.config.mjs``, ``package.json``, ``web/`` and a ``node_modules`` link) plus one
rendered state::

    {'tree': 'D:/NeyviaRuns/CORE/ui-fix/src-9589de605', 'state': 'files-main',
     'variant': 'dark-desktop', 'ports': [49114, 49115], 'runs': 'D:/NeyviaRuns/CORE/ui-fix'}

* transcribe: digest of ``web/src`` -> production build (cached per digest) -> a fresh
  private Obscura render of the state -> DOM perception + pixel facts (the glance
  hybrid) -> Scene. One render per (digest, state, variant): a restored tree has the
  same bytes, so it re-observes as the same Scene and the core's rollback check holds.
  Node ids are content keys (class + text + coarse position), not element indices,
  so an unrelated finding keeps its identity across a fix.
* fixes: CSS/token patches computed from the finding (an override rule appended to
  the stylesheet that already styles the element), and recorded source patches from
  ``config/laya_ui_fix_library.json`` (applied with ``git apply``; LAYA selects and
  verifies them, it does not author them).
* checkpoint/restore: snapshot of every file under ``web/src``; restore verifies the digest.

Nothing here touches a live product window: Obscura runs headless on the given ports.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
LIBRARY = REPO / 'config/laya_ui_fix_library.json'
STATES = ('home', 'files-main', 'files-side-floating', 'pdf')
GUARDS = ('minFontPx', 'pageErrors')  # stable under app-state noise; textNodes is reported, not guarded
RENDERER = 4  # render cache key: bump when the render/observation recipe changes
TRANSCRIPTION = 1  # scene cache key: bump when scenes are derived differently from a render
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def is_tree_source(source):
    return isinstance(source, dict) and 'tree' in source and 'state' in source


# --- source tree: digest, snapshot, build -----------------------------------

def _web_files(tree):
    base = Path(tree) / 'web/src'
    return sorted(p for p in base.rglob('*') if p.is_file())


def digest(tree):
    h = hashlib.sha256()
    base = Path(tree)
    for path in _web_files(tree):
        h.update(path.relative_to(base).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    return h.hexdigest()


def checkpoint(source):
    if not is_tree_source(source):
        return None  # an observation, not a source: nothing to snapshot
    base = Path(source['tree'])
    return {'digest': digest(base), 'files': {p.relative_to(base).as_posix(): p.read_bytes() for p in _web_files(base)}}


def restore(source, snapshot):
    if snapshot is None:
        return
    base = Path(source['tree'])
    current = {p.relative_to(base).as_posix() for p in _web_files(base)}
    for rel in current - set(snapshot['files']):
        (base / rel).unlink()  # a file a fix added; the snapshot never held it
    for rel, data in snapshot['files'].items():
        path = base / rel
        if not path.is_file() or path.read_bytes() != data:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    if digest(base) != snapshot['digest']:
        raise RuntimeError('Restore did not reproduce the checkpointed source tree')


def build(source, tree_digest):
    out = Path(source['runs']) / 'builds' / tree_digest[:16]
    marker = out / '.laya-digest'
    if marker.is_file() and marker.read_text(encoding='utf-8') == tree_digest and (out / 'index.html').is_file():
        return out, {'cached': True, 'ms': 0}
    tmp = out.with_name(out.name + '-building')
    tree = Path(source['tree'])
    started = time.perf_counter()
    log = Path(source['runs']) / 'logs' / ('build-' + tree_digest[:16] + '.log')
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('wb') as handle:
        done = subprocess.run(['node', str(tree / 'node_modules/vite/bin/vite.js'), 'build', '--config', 'vite.config.mjs',
                               '--configLoader', 'runner', '--outDir', str(tmp), '--emptyOutDir', '--logLevel', 'warn'],
                              cwd=tree, stdout=handle, stderr=subprocess.STDOUT, timeout=600, creationflags=NO_WINDOW)
    if done.returncode or not (tmp / 'index.html').is_file():
        raise RuntimeError('Build failed; see ' + str(log))
    if out.exists():
        out.rename(out.with_name(out.name + '-stale-' + str(time.time_ns())))
    tmp.rename(out)
    marker.write_text(tree_digest, encoding='utf-8')
    return out, {'cached': False, 'ms': round((time.perf_counter() - started) * 1000)}


# --- render one state privately in Obscura ------------------------------------

STRUCTURE = """ids => { const all = Array.from(document.querySelectorAll('*')); const index = new Map(all.map((e, i) => [e, i]));
  const chains = {}, elements = {};
  const describe = e => { const s = getComputedStyle(e); const parent = e.parentElement ? getComputedStyle(e.parentElement).display : '';
    return {tag: e.tagName.toLowerCase(), cls: (typeof e.className === 'string' ? e.className : '').trim().slice(0, 200),
            z: s.zIndex, pos: s.position, display: s.display, parentDisplay: parent, bg: s.backgroundColor}; };
  for (const id of ids) { const e = all[+id.slice(1)]; if (!e) continue; const chain = [];
    for (let a = e; a && a !== document.documentElement; a = a.parentElement) { const key = 'v' + index.get(a); chain.push(key);
      if (!elements[key]) elements[key] = describe(a); }
    chains[id] = chain; }
  return {chains, elements}; }"""


def _reach(rig, shots, state):
    if state == 'home':
        return None
    if state in ('files-main', 'files-side-floating'):
        shots.open_from_launcher(rig, 'Files', 'Files')
        rig.wait("() => document.querySelectorAll('.nx-files [data-path]').length > 0", 20)  # the listing has loaded
        if state == 'files-side-floating':
            wid = shots.window_id(rig, 'Files')
            shots.press_place(rig, wid, 'Side panel')
            # Narrow desktop widths make the real side panel float over the chat.
            rig.page.set_viewport_size({'width': 820, 'height': 900})
            rig.wait("id => document.querySelector(`[data-window=\"${CSS.escape(id)}\"]`)?.classList.contains('is-floating')", 15, wid)
        return None
    if state == 'pdf':
        fixture = shots.SCRATCH / 'home/tour-fixtures/INTN.pdf'
        fixture.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(shots.PDF, fixture)
        shots.open_from_launcher(rig, 'files:' + str(fixture), 'PDF')
        try:
            rig.wait("() => !!document.querySelector('.nx-pdf-page .textLayer span')", 12)
            return None
        except TimeoutError:
            return 'PDF text layer did not appear within 12 s'
    raise ValueError('Unknown UI state: ' + str(state))


SETTLE = "() => [document.querySelectorAll('*').length, document.body ? document.body.innerText.length : 0]"
LAYOUT = """() => Array.from(document.querySelectorAll('button,input,textarea,select,[role=button]')).map(e => {
  const r = e.getBoundingClientRect(); return Math.round(r.x) + ',' + Math.round(r.y) + ',' + Math.round(r.width); }).join(';')"""


def _settle(rig, quiet=2.0, limit=20.0):
    """Observe only a settled page: the element count and visible text stay unchanged for ``quiet`` s.
    Async panes (file listings, provider probes) otherwise race the observer."""
    end, last, since = time.monotonic() + limit, None, time.monotonic()
    while time.monotonic() < end:
        now = rig.js(SETTLE)
        if now != last:
            last, since = now, time.monotonic()
        elif time.monotonic() - since >= quiet:
            time.sleep(1.0)  # Obscura paints a moment after the DOM settles
            return True
        time.sleep(0.25)
    return False


def render_ports(source):
    """The render's port gate: an assigned block (grant_agent.assigned_ports), else CORE or integrator ports."""
    from .assigned_ports import check_ports
    return check_ports([int(p) for p in source['ports']],
                       lambda p: all(49111 <= x <= 49119 for x in p) or all(48871 <= x <= 48889 for x in p),
                       'UI fix renders use two explicitly owned ports (CORE 49111-49119 or integrator 48871-48889)')


def render(source, build_dir, label):
    sys.path[:0] = [p for p in (str(REPO / 'src'), str(REPO / 'scripts')) if p not in sys.path]
    import placement_shots as shots
    from .laya_glance_gate import _admitted_engine
    from .assigned_ports import state as state_dir
    backend, engine = render_ports(source)
    runs = Path(source['runs'])
    exe, engine_sha = _admitted_engine()
    shots.EXE, shots.BUILD, shots.BACKEND, shots.ENGINE = exe, Path(build_dir), backend, engine
    fresh = label + '-' + str(time.time_ns())  # a new isolated home per render: no state carried between renders
    shots.SCRATCH = runs / 'runtime' / fresh
    shots.SMALL_STATE = state_dir('CORE/ui-state') / fresh
    shots.OUT = runs / 'shots'
    for folder in (shots.SCRATCH, shots.SMALL_STATE, shots.OUT):
        folder.mkdir(parents=True, exist_ok=True)
    packages = [p for p in sys.path if Path(p).name == 'site-packages']
    isolated = shots.isolated_env

    def environment():
        env = isolated()
        env['PYTHONPATH'] = os.pathsep.join([str(REPO / 'src'), *packages])
        return env
    shots.isolated_env = environment
    theme, form = source.get('variant', 'dark-desktop').split('-', 1)
    shots.THEME = theme
    receipt = {'errors': [], 'checks': []}
    rig = shots.Rig(receipt, direct_cdp=True)
    timings = {}
    started = time.perf_counter()
    try:
        rig.start()
        timings['startMs'] = round((time.perf_counter() - started) * 1000)
        rig.session(shots.PHONE if form == 'phone' else shots.DESKTOP)
        note = _reach(rig, shots, source['state'])
        observer = (REPO / 'src/grant_agent/perception_scene.js').read_text(encoding='utf-8')
        # DOM facts and pixels must describe one layout: a late async change (a provider
        # pill appearing) between the two re-takes the pair, up to three times.
        for attempt in range(3):
            settled = _settle(rig)
            layout = rig.js(LAYOUT)
            png = rig.shot(label)
            dom = rig.page.evaluate(observer, {})
            structure = rig.page.evaluate(STRUCTURE, [n['id'] for n in dom.get('nodes', [])])
            consistent = rig.js(LAYOUT) == layout
            if settled and consistent:
                break
        timings['observationAttempts'] = attempt + 1
        if not settled:
            note = ((note + '; ') if note else '') + 'page did not settle within 20 s'
        if not consistent:
            note = ((note + '; ') if note else '') + 'layout moved while observing; DOM and pixels may disagree'
    finally:
        rig.stop()
        shots.isolated_env = isolated
    timings['renderMs'] = round((time.perf_counter() - started) * 1000)
    return {'dom': dom, 'structure': structure, 'screenshot': str(png), 'note': note, 'pageErrors': receipt['errors'],
            'engineSha256': engine_sha, 'timings': timings}


# --- transcription -------------------------------------------------------------

def _slug(text, n=24):
    return re.sub(r'[^a-z0-9]+', '-', str(text or '').lower()).strip('-')[:n]


def _stable_ids(nodes, structure):
    """Content keys instead of element indices: an unrelated node keeps its id across a fix."""
    elements, chains = structure.get('elements', {}), structure.get('chains', {})
    seen, mapping = {}, {}
    for n in nodes:
        b = n['attributes'].get('bounds') or {}
        where = f"{round((b.get('x') or 0) / 24)}.{round((b.get('y') or 0) / 24)}"
        if n['id'].startswith('px:'):
            key = 'px:' + n['kind'] + ':' + _slug(n['attributes'].get('text')) + '@' + where
        else:
            own = elements.get(n['id'], {}).get('cls', '').split()
            key = 'dom:' + (own[0] if own else n['kind']) + ':' + _slug(n['attributes'].get('text')) + '@' + where
        seen[key] = seen.get(key, 0) + 1
        mapping[n['id']] = key if seen[key] == 1 else key + '#' + str(seen[key])
    out = []
    for n in nodes:
        relations = dict(n.get('relations') or {})
        if relations.get('parent') in mapping:
            relations['parent'] = mapping[relations['parent']]
        attributes = dict(n['attributes'])
        if n['id'] in chains:
            attributes['element'] = n['id']  # this render's element index (for patch targeting)
        out.append({**n, 'id': mapping[n['id']], 'attributes': attributes, 'relations': relations})
    return out


def _metrics(dom, page_errors):
    view = dom.get('viewport') or {}
    width, height = view.get('width') or 1e9, view.get('height') or 1e9
    visible = [n for n in dom.get('nodes', []) if n.get('text') and n.get('bounds')
               and n['bounds']['x'] < width and n['bounds']['y'] < height and n['bounds']['w'] > 0 and n['bounds']['h'] > 0
               and not (n.get('facts') or {}).get('scrolledOut')]
    fonts = [(n.get('facts') or {}).get('fontSize') for n in visible]
    fonts = [f for f in fonts if isinstance(f, (int, float))]
    return {'textNodes': len(visible), 'minFontPx': min(fonts) if fonts else None, 'pageErrors': len(page_errors)}


def _user_content_duplicates(nodes):
    """Pixel lines over DOM user content (PDF text layer, terminal, editor) are the document's
    words, already observed exactly by the DOM and marked user content; they are not UI copy."""
    content = [n['attributes']['bounds'] for n in nodes if not n['id'].startswith('px:')
               and n['measurements'].get('userContent') and n['attributes'].get('bounds')]
    drop = set()
    for n in nodes:
        b = n['attributes'].get('bounds') or {}
        if n['id'].startswith('px:text') and b:
            cx, cy = b['x'] + b['w'] / 2, b['y'] + b['h'] / 2
            if any(d['x'] - 2 <= cx <= d['x'] + d['w'] + 2 and d['y'] - 2 <= cy <= d['y'] + d['h'] + 2 for d in content):
                drop.add(n['id'])
    return drop


def transcribe(source):
    from .laya_glance import _transcribe as glance_transcribe, cross_check, fuse_pixels
    tree_digest = digest(source['tree'])
    state, variant = source['state'], source.get('variant', 'dark-desktop')
    key = f'{tree_digest[:16]}-{state}-{variant}-r{RENDERER}'
    runs = Path(source['runs'])
    memo = runs / 'scenes' / f'{key}-t{TRANSCRIPTION}.json'
    if memo.is_file():
        return json.loads(memo.read_text(encoding='utf-8'))
    build_dir, build_receipt = build(source, tree_digest)
    rendered = runs / 'renders' / f'{key}.json'  # one render per source digest; re-derivable scenes
    if rendered.is_file():
        seen = json.loads(rendered.read_text(encoding='utf-8'))
    else:
        seen = render(source, build_dir, f'{tree_digest[:12]}-{state}-{variant}')
        rendered.parent.mkdir(parents=True, exist_ok=True)
        rendered.write_text(json.dumps(seen), encoding='utf-8')
    fused = fuse_pixels(seen['dom'], seen['screenshot'])
    hybrid = cross_check(fused, glance_transcribe({'image': seen['screenshot']}))
    provenance = dict(hybrid.get('provenance') or {})
    # Not a screenshot episode for ui-glance calibration: improve outcomes are scene episodes.
    provenance['render'] = provenance.pop('screenshotPath', seen['screenshot'])
    provenance.update(tree=str(source['tree']), sourceDigest=tree_digest, build=str(build_dir),
                      engineSha256=seen['engineSha256'], note=seen['note'])
    metrics = {**{k: v for k, v in (hybrid.get('metrics') or {}).items() if k != 'pixelMs'},
               **_metrics(seen['dom'], seen['pageErrors'])}
    nodes = _stable_ids(hybrid['nodes'], seen['structure'])
    duplicates = _user_content_duplicates(nodes)
    metrics['pixelLinesOnUserContent'] = len(duplicates)
    scene = {**hybrid, 'surface': f'{state}/{variant}', 'nodes': [n for n in nodes if n['id'] not in duplicates],
             'structure': seen['structure'], 'provenance': provenance, 'metrics': metrics,
             'timings': {**seen['timings'], 'buildMs': build_receipt['ms'], 'buildCached': build_receipt['cached']}}
    if seen['note']:
        scene['unknownReasons'] = list(scene.get('unknownReasons', [])) + [seen['note']]
    memo.parent.mkdir(parents=True, exist_ok=True)
    memo.write_text(json.dumps(scene), encoding='utf-8')
    return scene


# --- CSS/token patches -----------------------------------------------------------

RULE = re.compile(r'([^{}@;]+)\{([^{}]*)\}')


def _rules(tree):
    """(file, selector list, body) for every plain rule in the tree's stylesheets."""
    rows = []
    for path in _web_files(tree):
        if path.suffix != '.css':
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
        for match in RULE.finditer(text):
            rows.append((path, match[1].strip(), match[2]))
    return rows


def _rule_for(tree, classes, prefer_property=None):
    """The rule whose subject compound carries one of ``classes`` (nearest first)."""
    rows = _rules(tree)
    for cls in classes:
        token = re.compile(r'\.' + re.escape(cls) + r'(?![\w-])')
        hits = []
        for path, selectors, body in rows:
            for selector in selectors.split(','):
                selector = selector.strip()
                subject = re.split(r'\s*[ >+~]\s*', selector)[-1]
                if token.search(subject) and ':' not in subject and '[' not in subject:
                    hits.append((prefer_property is not None and prefer_property in body, path, selector))
        if hits:
            hits.sort(key=lambda h: (not h[0], len(h[2])))
            return cls, hits[0][1], hits[0][2]
    return None, None, None


def _scene(source):
    return transcribe(source)  # memoised for the current digest


def _node(scene, node_id):
    return next((n for n in scene['nodes'] if n['id'] == node_id), None)


def _dom_owner(scene, node):
    """The DOM text node under a pixel finding (smallest box containing its centre)."""
    if node is None or node['attributes'].get('element'):
        return node
    b = node['attributes'].get('bounds') or {}
    cx, cy = b.get('x', 0) + b.get('w', 0) / 2, b.get('y', 0) + b.get('h', 0) / 2
    boxes = [n for n in scene['nodes'] if n['attributes'].get('element') and n['attributes'].get('text')
             and (d := n['attributes'].get('bounds')) and d['x'] - 2 <= cx <= d['x'] + d['w'] + 2 and d['y'] - 2 <= cy <= d['y'] + d['h'] + 2]
    return min(boxes, key=lambda n: n['attributes']['bounds']['w'] * n['attributes']['bounds']['h'], default=None)


def _classes(scene, element):
    """Own classes first, then each ancestor's, from this render's structure table."""
    structure = scene.get('structure', {})
    out = []
    for key in structure.get('chains', {}).get(element, []):
        for cls in structure.get('elements', {}).get(key, {}).get('cls', '').split():
            if cls not in out:
                out.append(cls)
    return out


def _append(source, finding, path, selector, declarations):
    before = digest(source['tree'])
    rule = f"\n/* LAYA fix {finding['fix']['action']}: {finding['predicate']} on {finding['node']} */\n{selector} {{ {declarations} }}\n"
    with Path(path).open('a', encoding='utf-8', newline='\n') as handle:
        handle.write(rule)
    return {'kind': 'css-override', 'action': finding['fix']['action'], 'file': Path(path).relative_to(source['tree']).as_posix(),
            'selector': selector, 'declarations': declarations, 'digestBefore': before, 'digestAfter': digest(source['tree'])}


def _noop(finding, reason):
    return {'kind': 'no-change', 'action': finding['fix']['action'], 'reason': reason}


def _text_rule_fix(declarations, prefer):
    def fix(source, finding):
        scene = _scene(source)
        owner = _dom_owner(scene, _node(scene, finding['node']))
        if owner is None:
            return _noop(finding, 'No DOM element under the finding')
        cls, path, selector = _rule_for(source['tree'], _classes(scene, owner['attributes']['element']), prefer)
        if not path:
            return _noop(finding, 'No stylesheet rule styles this element or its ancestors')
        return {**_append(source, finding, path, selector, declarations), 'element': owner['id'], 'class': cls}
    return fix


def _crossing(scene, finding):
    """(text owner, surface) for a see-through finding: text painted across a floating surface."""
    node = _node(scene, finding['node'])
    owner = _dom_owner(scene, node)
    b = (node or {}).get('attributes', {}).get('bounds') or {}
    surfaces = [n for n in scene['nodes'] if n['attributes'].get('element') and n['measurements'].get('surface')
                and (d := n['attributes'].get('bounds')) and min(d['x'] + d['w'], b.get('x', 0) + b.get('w', 0)) > max(d['x'], b.get('x', 0))
                and min(d['y'] + d['h'], b.get('y', 0) + b.get('h', 0)) > max(d['y'], b.get('y', 0))]
    surface = max(surfaces, key=lambda n: n['attributes']['bounds']['w'] * n['attributes']['bounds']['h'], default=None)
    return owner, surface


def stacking_layer(source, finding):
    """The layer under a floating surface becomes its own stacking context below it."""
    scene = _scene(source)
    owner, surface = _crossing(scene, finding)
    if owner is None or surface is None:
        return _noop(finding, 'No text owner or floating surface found for this crossing')
    chains = scene['structure']['chains']
    text_chain, surface_chain = chains.get(owner['attributes']['element'], []), chains.get(surface['attributes']['element'], [])
    common = next((key for key in text_chain if key in surface_chain), None)
    if common is None or text_chain.index(common) == 0:
        return _noop(finding, 'Text and surface share no layer boundary')
    layer = text_chain[text_chain.index(common) - 1]  # the child of the shared parent on the text's side
    info = scene['structure']['elements'].get(layer, {})
    cls, path, selector = _rule_for(source['tree'], info.get('cls', '').split())
    if not path:
        return _noop(finding, 'The layer under the surface has no stylesheet rule')
    positioned = info.get('pos') not in (None, 'static') or info.get('parentDisplay') in ('grid', 'inline-grid', 'flex', 'inline-flex')
    declarations = 'z-index: 0;' if positioned else 'position: relative; z-index: 0;'
    return {**_append(source, finding, path, selector, declarations), 'layer': info, 'surface': surface['id'], 'text': owner['id']}


def opaque_surface(source, finding):
    """Paint the floating surface with the opaque page token."""
    scene = _scene(source)
    _, surface = _crossing(scene, finding)
    if surface is None:
        return _noop(finding, 'No floating surface under the crossing')
    cls, path, selector = _rule_for(source['tree'], _classes(scene, surface['attributes']['element']), 'background')
    if not path:
        return _noop(finding, 'The surface has no stylesheet rule')
    return {**_append(source, finding, path, selector, 'background: var(--nx-bg);'), 'surface': surface['id'], 'class': cls}


# --- recorded source patches (fix library) ----------------------------------------

def library():
    if not LIBRARY.is_file():
        return []
    return json.loads(LIBRARY.read_text(encoding='utf-8'))['fixes']


def _patch_fix(entry):
    def fix(source, finding):
        if entry.get('states') and source['state'] not in entry['states']:
            return _noop(finding, 'Library fix does not cover state ' + source['state'])
        body = (REPO / entry['patch']).read_bytes().replace(bytes([13, 10]), bytes([10]))  # checkout line endings never matter
        check = subprocess.run(['git', 'apply', '--check', '--whitespace=nowarn', '-'], cwd=source['tree'], input=body,
                               capture_output=True, creationflags=NO_WINDOW)
        if check.returncode:
            return _noop(finding, 'Patch does not apply to this tree: ' + check.stderr.decode(errors='replace').strip()[:300])
        before = digest(source['tree'])
        subprocess.run(['git', 'apply', '--whitespace=nowarn', '-'], cwd=source['tree'], input=body, check=True,
                       capture_output=True, creationflags=NO_WINDOW)
        return {'kind': 'recorded-patch', 'action': finding['fix']['action'], 'patch': entry['patch'],
                'patchSha256': hashlib.sha256(body).hexdigest(), 'origin': entry.get('origin'),
                'digestBefore': before, 'digestAfter': digest(source['tree'])}
    return fix


def fixes():
    table = {'ui.css.align-start': _text_rule_fix('text-align: start;', 'text-align'),
             'ui.css.intrinsic-width': _text_rule_fix('min-width: max-content; flex-shrink: 0;', 'min-width'),
             'ui.css.shrink-text': _text_rule_fix('font-size: smaller;', 'font-size'),
             'ui.css.stacking-layer': stacking_layer,
             'ui.css.opaque-surface': opaque_surface}
    for entry in library():
        table[entry['action']] = _patch_fix(entry)

    def only_trees(fix):
        def guarded(source, finding):
            return fix(source, finding) if is_tree_source(source) else _noop(finding, 'Observation sources are read-only; fixes edit a source tree')
        return guarded
    return {name: only_trees(fix) for name, fix in table.items()}


def library_actions(predicate):
    return [entry['action'] for entry in library() if predicate in entry.get('predicates', [])]


def replay(source, receipts):
    """Re-apply kept fix receipts to a tree (e.g. to build the combined fixed candidate)."""
    applied = []
    for receipt in receipts:
        if receipt.get('kind') == 'css-override':
            path = Path(source['tree']) / receipt['file']
            with path.open('a', encoding='utf-8', newline='\n') as handle:
                handle.write(f"\n/* LAYA fix {receipt['action']} (replayed) */\n{receipt['selector']} {{ {receipt['declarations']} }}\n")
        elif receipt.get('kind') == 'recorded-patch':
            body = (REPO / receipt['patch']).read_bytes().replace(bytes([13, 10]), bytes([10]))
            subprocess.run(['git', 'apply', '--whitespace=nowarn', '-'], cwd=source['tree'], input=body, check=True,
                           capture_output=True, creationflags=NO_WINDOW)
        else:
            continue
        applied.append({k: receipt.get(k) for k in ('kind', 'action', 'file', 'selector', 'declarations', 'patch')})
    return applied
