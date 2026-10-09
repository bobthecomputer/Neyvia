"""LAYA glance for the P22 release gate: changed web sources -> rendered states -> verdict rows.

The gate appends a request JSON path; one JSON object goes to stdout:
{"commit", "observations": [{surface, variant, verdict, admitted, screenshotSha256, reason, ...}]}.
Rendering uses only the admitted headless Obscura engine through placement_shots.Rig on the
assigned ports. Only an admitted, defect-free glance yields "looks fine"; every other outcome
(including render or observer failure) is reported as "looks broken" or "uncertain".
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADMISSION = Path(os.environ.get('NEYVIA_LAYA_ENGINE_ADMISSION',
                                r'D:\NeyviaRuns\engines\obscura-c2h\4028d3ec7e4a-d25dbe93fae7\ADMISSION.json'))
PORTS = (49087, 49088)
VARIANTS = ('dark-desktop', 'light-desktop', 'dark-phone', 'light-phone')
HOME = 'home'

# Shell-level files render as the home shell (no app opened) — an intentional mapping.
SHELL_WORDS = ('shell', 'home', 'sidebar', 'composer', 'launcher', 'tokens', 'themes', 'theme', 'os', 'stage',
               'thread', 'look', 'backdrop', 'canopy', 'switcher', 'toasts', 'indicators', 'primitives', 'motion',
               'placement', 'bubbles', 'newchat', 'dashboard', 'avatar', 'main', 'index', 'app', 'store', 'tree',
               'growingtree', 'spring', 'morph', 'announce', 'arrange', 'dockdrag', 'panes', 'tidy', 'update',
               'onboarding', 'signin', 'phone', 'checklist', 'toolshared', 'appskins', 'appskin', 'nx')
SUFFIXES = ('test', 'app', 'pane', 'panel', 'page', 'toolbar', 'parts', 'model', 'api', 'store', 'surfaces',
            'welcome', 'learned', 'pip', 'fixture', 'contracts', 'hooks', 'observe', 'settings', 'screens')
ALIASES = {'library': 'library', 'memory': 'memory', 'pdf': 'pdf', 'terminal': 'terminal', 'laya': 'laya',
           'gamedev': 'godot', 'scrollstudy': 'scroll-generator', 'mobilestudio': 'mobile-studio',
           'notes': 'notes', 'files': 'files', 'browser': 'browser', 'awareness': 'awareness'}


def _norm(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())


def map_surface(path, apps):
    """Return ([app ids], mapping note) for one changed web path."""
    name = Path(path).name.lower()
    stem = name.split('.', 1)[0]
    stem = _norm(stem[2:] if stem.startswith('nx') and len(stem) > 2 else stem)
    keys = {}
    for field in (0, 2):  # ids win over window titles
        for app in apps:
            key = _norm(app[field])
            if len(key) >= 3:
                keys.setdefault(key, app[0])
    keys.update(ALIASES)
    candidates = [stem]
    current = stem
    changed = True
    while changed:
        changed = False
        for suffix in SUFFIXES:
            if current.endswith(suffix) and len(current) > len(suffix):
                current = current[:-len(suffix)]
                candidates.append(current)
                changed = True
    for candidate in candidates:
        if candidate in keys:
            return [keys[candidate]], f'mapping: {Path(path).name} -> app {keys[candidate]}'
    for candidate in candidates:
        if candidate in SHELL_WORDS or any(candidate.startswith(word) for word in ('shell', 'sidebar', 'composer', 'launcher', 'home')):
            return [HOME], f'mapping: {Path(path).name} is a shell surface, rendered home shell'
    return [HOME], f'mapping: {Path(path).name} unmapped, rendered home shell'


def _admitted_engine():
    admission = json.loads(ADMISSION.read_text(encoding='utf-8'))
    for key in ('engineBinary', 'workerBinary'):
        row = admission[key]
        actual = hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()
        if actual != row['sha256']:
            raise ValueError(f'Admitted Obscura {key} differs from its admission record')
    return Path(admission['engineBinary']['path']), admission['engineBinary']['sha256']


def _advisory(v):
    """Pixel findings not yet trusted at 0.95 are reported, never counted."""
    rows = v.get('advisory') or []
    if not rows:
        return ''
    kinds = sorted({f['predicate'] for f in rows})
    return '; pixel advisory (below calibrated 0.95): ' + ', '.join(kinds)


def _reason(v, nodes):
    if v.get('admitted') and not v.get('bugs'):
        return f'No defect predicate matched across {nodes} observed nodes'
    if v.get('admitted'):
        parts = []
        for bug in v['bugs'][:4]:
            text = (bug.get('evidence') or {}).get('attributes.text')
            label = f" on '{str(text)[:40]}'" if text else ''
            source = ' [pixels]' if str(bug['node']).startswith('px:') else ''
            parts.append(f"{bug['type']}{label} (node {bug['node']}){source}")
        more = f'; +{len(v["bugs"]) - 4} more' if len(v['bugs']) > 4 else ''
        return '; '.join(parts) + more + _advisory(v)
    texts = v.get('unknownTexts') or {}
    unknown = '; '.join(f"{p} on {', '.join(repr(t) for t in texts.get(p, [])[:3]) or 'unnamed nodes'}"
                        for p in v.get('unknown', [])[:8]) or 'none listed'
    extra = ''.join('; ' + r for r in v.get('unknownReasons', []))
    return f'Not admitted: unknown facts: {unknown}{extra}{_advisory(v)}; one model look required'


def _row(surface, variant, state, note):
    row = {'surface': surface, 'variant': variant, 'verdict': state['verdict'], 'admitted': state['admitted'],
           'screenshotSha256': state.get('screenshotSha256'), 'reason': f"{state['reason']} [{note}]",
           'state': state['key'], 'bugs': state.get('bugs', []), 'screenshot': state.get('screenshot'), 'ms': state.get('ms')}
    return row


def request_ports(request):
    """Use the caller's allocation across the gate and legacy hook interfaces."""
    from .assigned_ports import assigned_block, check_ports
    def normalize(value):
        if isinstance(value, str):
            value = value.replace(',', ' ').split()
        if isinstance(value, dict):
            value = [value['backend'], value['engine']]
        ports = tuple(int(port) for port in value)
        blocks = (range(48871, 48890), range(49081, 49090), range(49111, 49120))
        if len(ports) != 2:
            raise ValueError('Glance needs two distinct assigned ports in one owned block')
        return tuple(check_ports(ports, lambda p: len(set(p)) == 2 and
                                any(all(port in block for port in p) for block in blocks),
                                'Glance needs two distinct assigned ports in one owned block'))
    declared = request.get('assignedPorts')
    legacy = request.get('ports')
    if declared is not None:
        ports = normalize(declared)
        if legacy is not None and normalize(legacy) != ports:
            raise ValueError('Conflicting caller port allocations')
        return ports
    configured = legacy if legacy is not None else os.environ.get('NEYVIA_LAYA_GLANCE_PORTS')
    if configured is None:
        block = assigned_block()
        configured = block.pair(0) if block is not None else PORTS
    return normalize(configured)


def run(request_path, *, budget=150.0, run_root=None):
    started = time.perf_counter()
    deadline = started + budget
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    # The caller owns the sockets; a release gate must never inherit the
    # development track's default ports.
    ports = request_ports(request)
    from .proof_ports import configure_asyncio
    wakeup_ports = request.get('observerPorts', [48875,48876] if min(ports)<49000 else [49085,49086])
    if set(wakeup_ports) & set(ports):
        raise ValueError('Observer wake-up ports conflict with render servers')
    configure_asyncio(wakeup_ports)
    commit = request.get('commit')
    from .assigned_ports import state as state_dir
    surfaces = list(request.get('changedSurfaces') or [])
    variants = [v for v in (request.get('variants') or VARIANTS)]
    stamp = time.strftime('%Y%m%d-%H%M%S') + '-' + str(commit or 'nocommit')[:10]
    # Screenshots and receipts stay beside the request; small runtime databases use
    # ignored local state. Durable SQLite writes on the D output disk can starve startup.
    root = Path(run_root or Path(request_path).resolve().parent / ('laya-glance-' + stamp)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    receipt = {'schema': 'neyvia.laya-glance-gate.v1', 'commit': commit, 'request': str(request_path),
               'build': request.get('build'), 'ports': {'backend': ports[0], 'engine': ports[1]},
               'surfaces': {}, 'states': {}, 'errors': [], 'checks': [], 'timings': {}}
    states = {}

    sys.path[:0] = [str(REPO / 'src'), str(REPO / 'scripts')]
    import placement_shots as shots
    mapping = {}
    for surface in surfaces:
        apps, note = map_surface(surface, shots.APPS)
        mapping[surface] = (apps, note)
        receipt['surfaces'][surface] = {'apps': apps, 'mapping': note}
    wanted_apps = []
    for apps, _ in mapping.values():
        for app in apps:
            if app not in wanted_apps:
                wanted_apps.append(app)
    # Home first: each variant session starts there; apps follow, closed between states.
    wanted_apps.sort(key=lambda a: a != HOME)

    def fail_all(reason):
        for variant in variants:
            for app in wanted_apps:
                states.setdefault((app, variant), {'key': f'{app}/{variant}', 'verdict': 'uncertain', 'admitted': False,
                                                   'screenshotSha256': None, 'reason': reason})

    rig = None
    try:
        build = Path(request.get('build') or '')
        if not (build / 'index.html').is_file():
            raise FileNotFoundError(f'Build directory has no index.html: {build}')
        exe, engine_sha = _admitted_engine()
        receipt['engineAdmission'] = {'path': str(ADMISSION), 'engineSha256': engine_sha}
        observer = (REPO / 'src/grant_agent/perception_scene.js').read_text(encoding='utf-8')
        shots.EXE, shots.BUILD = exe, build
        shots.BACKEND, shots.ENGINE = ports
        shots.SCRATCH = root / 'runtime'
        shots.SMALL_STATE = state_dir('INTN/laya-glance-state') / stamp
        receipt['runtimeStateRoot'] = str(shots.SMALL_STATE)
        receipt['artifactRoot'] = str(root)
        shots.OUT = root / 'shots'
        for folder in (shots.SCRATCH, shots.SMALL_STATE, shots.OUT):
            folder.mkdir(parents=True, exist_ok=True)
        apps = {app_id: (query, title) for app_id, query, title in shots.APPS}
        if 'pdf' in wanted_apps:
            # A real document in this run's isolated Files home, opened through Files.
            fixture = shots.SCRATCH / 'home/tour-fixtures/INTN.pdf'
            fixture.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(shots.PDF, fixture)
            apps['pdf'] = ('files:' + str(fixture), 'PDF')
        isolated = shots.isolated_env
        package_paths = [p for p in sys.path if Path(p).name == 'site-packages']

        def render_env():
            env = isolated()
            env['PYTHONPATH'] = os.pathsep.join([str(REPO / 'src'), *package_paths])
            return env
        shots.isolated_env = render_env
        rig_receipt = {'errors': [], 'checks': []}
        rig = shots.Rig(rig_receipt, direct_cdp=True)
        t0 = time.perf_counter()
        rig.start()
        receipt['timings']['startMs'] = round((time.perf_counter() - t0) * 1000)
        receipt['rig'] = rig_receipt
        for variant in variants:
            theme, form = variant.split('-', 1)
            if time.perf_counter() > deadline:
                break
            t0 = time.perf_counter()
            try:
                shots.THEME = theme
                rig.session(shots.PHONE if form == 'phone' else shots.DESKTOP)
            except Exception as exc:
                for app in wanted_apps:
                    states[(app, variant)] = {'key': f'{app}/{variant}', 'verdict': 'uncertain', 'admitted': False,
                                              'screenshotSha256': None, 'reason': f'Session failed: {type(exc).__name__}: {str(exc)[:200]}'}
                continue
            receipt['timings'][f'session/{variant}'] = round((time.perf_counter() - t0) * 1000)
            for app in wanted_apps:
                if time.perf_counter() > deadline:
                    break
                states[(app, variant)] = _render_state(rig, shots, app, variant, apps, observer, rig_receipt)
    except Exception as exc:
        receipt['errors'].append(f'{type(exc).__name__}: {exc}')
        receipt['traceback'] = traceback.format_exc()
        fail_all(f'Render rig failed: {type(exc).__name__}: {str(exc)[:200]}')
    finally:
        if rig is not None:
            rig.stop()
    fail_all(f'Not rendered within the {budget:.0f} s LAYA budget')

    observations = []
    for surface in surfaces:
        app_ids, note = mapping[surface]
        for variant in variants:
            rows = [states[(app, variant)] for app in app_ids]
            # The weakest state decides: uncertain < looks broken < looks fine.
            order = {'uncertain': 0, 'looks broken': 1, 'looks fine': 2}
            worst = min(rows, key=lambda s: order[s['verdict']])
            observations.append(_row(surface, variant, worst, note))
    receipt['states'] = {f'{a}/{v}': s for (a, v), s in states.items()}
    receipt['observations'] = observations
    receipt['timings']['totalMs'] = round((time.perf_counter() - started) * 1000)
    receipt['root'] = str(root)
    (root / 'receipt.json').write_text(json.dumps(receipt, indent=2, default=str) + '\n', encoding='utf-8')
    return {'commit': commit, 'observations': observations, 'receipt': str(root / 'receipt.json'),
            'totalMs': receipt['timings']['totalMs']}


def _render_state(rig, shots, app, variant, apps, observer, rig_receipt):
    key = f'{app}/{variant}'
    started = time.perf_counter()
    state = {'key': key, 'verdict': 'uncertain', 'admitted': False, 'screenshotSha256': None}
    errors_before = len(rig_receipt['errors'])
    try:
        shots.close_all(rig)
        if app != HOME:
            query, title = apps[app]
            shots.open_from_launcher(rig, query, title)
            if app == 'pdf':
                try:
                    # The canvas mounts before its asynchronous page render. This
                    # known text fixture is ready only after the text layer follows
                    # the completed raster, avoiding a blank first-frame capture.
                    rig.wait("() => !!document.querySelector('.nx-pdf-page .textLayer span')", 8)
                except TimeoutError:
                    state['note'] = 'readiness: PDF fixture text layer did not finish within 8 s'
        raw = rig.page.evaluate(observer, {})
        nodes = len(raw.get('nodes', raw.get('elements', []))) if isinstance(raw, dict) else 0
        png = rig.shot(f'{app}-{variant}')
        theme_check = rig_receipt['checks'][-1] if rig_receipt['checks'] else {}
        state['screenshot'] = str(png)
        state['screenshotSha256'] = hashlib.sha256(Path(png).read_bytes()).hexdigest()
        (Path(png).with_suffix('.scene.json')).write_text(json.dumps(raw, default=str), encoding='utf-8')
        from grant_agent.laya_glance import glance
        verdict = glance(raw, screenshot=str(png), root=shots.SMALL_STATE)
        bugs = verdict.get('bugs') or []
        state['bugs'] = bugs
        state['glance'] = {k: verdict.get(k) for k in ('admitted', 'broken', 'complete', 'unknown', 'confidenceKind', 'escalation', 'ms', 'sceneSha256')}
        state['admitted'] = bool(verdict.get('admitted'))
        if theme_check and theme_check.get('ok') is False:
            state['admitted'] = False
            state['reason'] = f"Rendered theme {theme_check.get('actual')!r} differs from requested {theme_check.get('requested')!r}"
        else:
            state['verdict'] = ('looks broken' if bugs else 'looks fine') if state['admitted'] else 'uncertain'
            state['reason'] = _reason({**verdict, 'admitted': state['admitted']}, nodes)
        if state.get('note'):
            # An unsettled state is never certified fine, whatever the glance saw.
            state['reason'] += '; ' + state['note']
            if state['verdict'] == 'looks fine':
                state['verdict'], state['admitted'] = 'uncertain', False
        page_errors = rig_receipt['errors'][errors_before:]
        if page_errors:
            state['pageErrors'] = page_errors
            state['reason'] += f'; {len(page_errors)} page error(s): {page_errors[0][:120]}'
            if state['verdict'] == 'looks fine':
                state['verdict'], state['admitted'] = 'uncertain', False
                state['reason'] = 'Page raised errors while rendering: ' + state['reason']
    except Exception as exc:
        state['reason'] = f'Render or glance failed: {type(exc).__name__}: {str(exc)[:240]}'
        state['traceback'] = traceback.format_exc()[-1500:]
        try:
            png = rig.shot(f'{app}-{variant}-failure')
            state['screenshot'] = str(png)
            state['screenshotSha256'] = hashlib.sha256(Path(png).read_bytes()).hexdigest()
        except Exception:
            pass
    state['ms'] = round((time.perf_counter() - started) * 1000)
    return state
