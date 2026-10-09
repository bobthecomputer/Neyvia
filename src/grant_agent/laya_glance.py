"""UI adapter for the shared Scene core.

Two transcription sources feed ONE vocabulary (manuals/cl/laya-glance.cl):
  * the perception layer (DOM/accessibility graph plus computed style facts),
    optionally fused with the screenshot's pixels for facts CSS cannot settle;
  * a plain screenshot, read by local OCR plus pixel measurement
    (``laya_glance_image``).

Instant learning (plan 21): labelled screenshots are episodes. Per-type
calibration counts are updated on every labelled write, so the very next glance
uses them. Node-level corrections ("this finding is fine", "this node is
clipped") are episodes too and change the next answer immediately. No training.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time

REPO = Path(__file__).resolve().parents[2]
DOMAIN = 'ui-glance'
NODE_DOMAIN = 'scene:ui-node'
TYPES = ('see-through', 'clipped-text', 'raw-error', 'encoded-path', 'internal-id',
         'blank-render', 'overlap', 'unreadable-contrast', 'off-screen-control')
LEVEL = 0.95


def _is_scene_nodes(rows):
    return bool(rows) and all(isinstance(r, dict) and 'measurements' in r and 'kind' in r for r in rows)


def _lensed(scene):
    """Plan 24: run the registered program lenses on a pixel scene (no-op without any)."""
    if isinstance(scene, dict) and scene.get('measured') == 'approximate' and (scene.get('provenance') or {}).get('screenshotPath'):
        from .scene_core.lenses import apply
        apply(scene)
    return scene


def _transcribe(observation):
    from .laya_ui_fix import is_tree_source
    if is_tree_source(observation):  # a web source tree + state: build, render privately, observe
        from .laya_ui_fix import transcribe as tree_scene
        return tree_scene(observation)
    if isinstance(observation, dict) and observation.get('image') and not observation.get('nodes'):
        from .laya_glance_image import transcribe_image
        scene = transcribe_image(observation['image'])
        if observation.get('surface'):
            scene['surface'] = observation['surface']
        return _lensed(scene)
    value = observation
    while isinstance(value, dict) and 'state' in value and 'nodes' not in value:
        value = value['state']
    value = value.get('scene', value)
    if value.get('domain') == 'ui' and value.get('schema') == 'neyvia.scene.v1':
        return value
    if _is_scene_nodes(value.get('nodes')):
        return _lensed(value)  # already Scene-shaped (pixel transcription or a fused DOM scene)
    model = isinstance(value.get('text'), list)
    rows = value.get('nodes', value.get('elements', []))
    if model:
        rows = [{'id': f'{kind}-{i}', 'role': kind, 'text': r.get('text', r.get('description', '')),
                 'bounds': r.get('bounds'), 'certainty': r.get('certainty', 'uncertain')}
                for kind in ('text', 'layout', 'objects') for i, r in enumerate(value.get(kind, []))]
    nodes = []
    for i, r in enumerate(rows):
        facts = dict(r.get('facts', {}))
        if not model:
            facts.setdefault('source', 'dom')
        nodes.append({'id': str(r.get('id', i)), 'kind': r.get('role', 'unknown'),
                      'attributes': {'text': r.get('text', r.get('name', '')), 'bounds': r.get('bounds')},
                      'measurements': facts, 'relations': {'parent': r.get('parent')},
                      'certainty': r.get('certainty', 'observed')})
    scene = {'surface': value.get('surface', value.get('title', 'screenshot' if model else 'ui')),
             'layer': value.get('layer', 'image' if model else 'app'), 'nodes': nodes,
             'viewport': value.get('viewport'), 'truncated': bool(value.get('truncated')),
             'modelTranscription': model or value.get('modelTranscription', False),
             'provenance': value.get('source', value.get('provenance', {})) or {}, 'metrics': value.get('metrics', {})}
    if value.get('measured'):
        scene['measured'] = value['measured']
    return scene


def _vocabulary():
    path = REPO / 'manuals/cl/laya-glance.cl'
    rules = [json.loads(line.removeprefix('-- @bug ')) for line in path.read_text(encoding='utf-8').splitlines()
             if line.startswith('-- @bug ')]

    def condition(v):
        if 'field' in v:
            field = v['field']
            return {**v, 'field': field.replace('facts.', 'measurements.', 1) if field.startswith('facts.') else 'attributes.' + field}
        return {k: [condition(c) for c in values] for k, values in v.items()}
    from .laya_ui_fix import library_actions
    from .scene_core.lenses import with_branches

    def fix(r):
        # Named fix patterns in preference order (CL @bug "actions"), then recorded library
        # patches for this predicate. With none registered, the fix stays a review proposal.
        actions = list(r.get('actions', [])) + library_actions(r['type'])
        return {'action': actions[0] if r.get('actions') else 'ui.review-fix',
                'alternatives': actions[1:] if r.get('actions') else actions,
                'arguments': {'pattern': r['type'], 'instruction': r['fix']}}
    return with_branches([{'id': r['type'], 'condition': condition(r['predicate']), 'severity': 'error', 'means': r.get('means', ''),
             'evidence': ['attributes.text', 'attributes.bounds', 'measurements'], 'fix': fix(r)} for r in rules])


def ui_adapter():
    from .scene_core import Adapter

    def pixels(scene):
        path = scene.get('provenance', {}).get('screenshotPath')
        return (DOMAIN, {'image': str(Path(path).resolve())}) if path else None
    from . import laya_ui_fix
    # Fixes act only on tree sources (a web source tree + rendered state); a perception
    # scene or screenshot has nothing to edit, so improve proposes for those.
    return Adapter(transcribe=_transcribe, vocabulary=_vocabulary, episode_input=pixels,
                   fixes=laya_ui_fix.fixes(), checkpoint=laya_ui_fix.checkpoint, restore=laya_ui_fix.restore)


def transcribe(observation, *, surface=None):
    from .scene_core import transcribe as shared
    scene = shared('ui', observation)
    if surface:
        scene = shared('ui', {**scene, 'surface': surface})
    return scene


# --- screenshot fusion for DOM scenes --------------------------------------

def fuse_pixels(raw, screenshot):
    """Fill DOM facts CSS cannot settle with measurements of the painted pixels.

    Only contrast is fused. Pixel contrast never exceeds the painted truth
    (anti-aliasing lowers it), so >=4.5 proves a pass and <1.8 proves a failure;
    anything between stays unknown.
    """
    import numpy as np
    from PIL import Image
    from .laya_glance_image import _contrast, _Pixels
    scene = _transcribe(raw)
    rgb = np.asarray(Image.open(screenshot).convert('RGB'))
    px = _Pixels(rgb)
    view = scene.get('viewport') or {}
    sx = px.w / float(view.get('width') or px.w)
    sy = px.h / float(view.get('height') or px.h)
    fused = 0
    for node in scene['nodes']:
        m = node['measurements']
        b = node['attributes'].get('bounds') or {}
        if m.get('source') != 'dom' or m.get('contrastRatio') is not None or not node['attributes'].get('text') or not b:
            continue
        # Narrow the element box to where its glyphs are (fields and buttons are
        # wider than their text), using the collector's alignment and padding.
        text = str(node['attributes']['text'])
        font = m.get('fontSize') or min(b['h'] * 0.6, 16)
        width = m.get('naturalTextWidth') or min(len(text) * 0.56 * font, b['w'])
        width = min(width, b['w'])
        left = b['x'] + (m.get('paddingLeft') or 0)
        right = b['x'] + b['w'] - (m.get('paddingRight') or 0)
        align = m.get('textAlign') or 'start'
        if align in ('center', '-webkit-center'):
            left = (left + right - width) / 2
        elif align in ('right', 'end'):
            left = right - width
        x0, x1 = left * sx, (left + width) * sx
        mid = b['y'] + b['h'] / 2
        y0, y1 = (mid - font * 0.7) * sy, (mid + font * 0.7) * sy
        X0, Y0, X1, Y1 = px.clamp_box(x0, y0, x1, y1)
        if X1 - X0 < 3 or Y1 - Y0 < 3:
            continue
        region = px.rgb[Y0:Y1, X0:X1]
        bg = px.background(x0, y0, x1, y1)
        dist = px.distance(region, bg).reshape(-1)
        ink = dist > 40
        # Element boxes can be wider than their glyphs; only text-dense boxes
        # give a trustworthy ink colour. Sparse ones stay unknown.
        if dist.max() <= 0 or ink.mean() < 0.04:
            continue
        fg = region.reshape(-1, 3)[dist >= max(np.quantile(dist, 0.9), 0.7 * dist.max())].mean(axis=0)
        ratio = _contrast(fg, bg)
        if ratio >= 4.5 or ratio < 1.8:
            m['contrastRatio'] = round(ratio, 2)
            m['contrastSource'] = 'pixels'
            fused += 1
    scene.setdefault('metrics', {})['pixelFusedFacts'] = fused
    scene.setdefault('provenance', {})['screenshotPath'] = str(Path(screenshot).resolve())
    return scene


# --- calibration and instant node corrections ------------------------------

def _calibration_path(root):
    return Path(root) / '.neyvia/laya/calibration/ui-glance.json'


def pixel_version():
    """Identity of the pixel transcriber alone (scene caches key on this)."""
    from . import laya_glance_image
    digest = hashlib.sha256(Path(laya_glance_image.__file__).read_bytes()).hexdigest()[:16]
    return digest + ('-ocr2' if laya_glance_image.SECOND_PASS_ENABLED else '')


def transcriber_version():
    """Pixel transcriber plus vocabulary: calibration counts are valid only for both.

    Only what decides firing is bound (each predicate's type and condition, plus adopted lenses);
    fix actions, wording and means do not change which screenshots fire, so editing them must not
    orphan the shipped calibration (it did when @bug lines gained fix actions on track/laya-core)."""
    bugs = ''.join(json.dumps([r['type'], r['predicate']], sort_keys=True)
                   for r in (json.loads(l[len('-- @bug '):]) for l in (REPO / 'manuals/cl/laya-glance.cl').read_text(encoding='utf-8').splitlines()
                             if l.startswith('-- @bug ')))
    from .scene_core.lenses import identity
    return hashlib.sha256((pixel_version() + bugs + identity('screenshot')).encode()).hexdigest()[:16]


def conformal_lower(k, n):
    """Finite-sample conservative rate: k/(n+1). 19/19 correct -> 0.95."""
    return k / (n + 1) if n else 0.0


def calibration_from_counts(counts):
    out = {}
    for t, c in counts.items():
        tp, fp, tn, fn = c.get('tp', 0), c.get('fp', 0), c.get('tn', 0), c.get('fn', 0)
        out[t] = {**c, 'precisionLower': conformal_lower(tp, tp + fp), 'npvLower': conformal_lower(tn, tn + fn)}
    return out


SHIPPED_CALIBRATION = REPO / 'config/laya_glance_calibration.json'


def load_calibration(root):
    """Per-predicate counts from labelled episodes in this root's store, else the
    shipped snapshot (config/laya_glance_calibration.json) built from the same
    episodes. Counts bound to another transcriber/vocabulary are ignored."""
    version = transcriber_version()
    for path in ([_calibration_path(root)] if root else []) + [SHIPPED_CALIBRATION]:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('transcriber') == version:
            return calibration_from_counts(data['counts'])
        # facts changed meaning (new transcriber, vocabulary or adopted lens): these counts no
        # longer calibrate them; a stale local file falls back to the shipped snapshot (plan 24).
    return None


def node_text(node):
    return re.sub(r'[^a-z0-9]+', ' ', str(node['attributes'].get('text', '')).lower()).strip()[:200]


def node_domain(predicate):
    return NODE_DOMAIN + ':' + predicate


def node_key(node, predicate):
    """The lesson input is the node's visible words only (the predicate is the
    domain), so similarity is not inflated by shared JSON keys."""
    return node_text(node)


LESSON_RADIUS = 0.8  # cosine similarity of hashed word/bigram vectors (OCR-noise tolerant)
# Text-keyed lessons only for defects intrinsic to the words or the element.
# See-through, off-screen and blank renders depend on the surrounding layout:
# the same hero text is fine on home and wrong under a translucent panel.
LESSON_TYPES = ('clipped-text', 'raw-error', 'encoded-path', 'internal-id', 'overlap', 'unreadable-contrast')


def _node_lessons(root):
    """Latest explicit node lessons, grouped by predicate, with frozen vectors."""
    if not root:
        return {}
    import numpy as np
    from .laya_instant import store, latest_episodes
    local = store(str(root))
    local.refresh()
    lessons = {}
    for row in latest_episodes(local.rows):
        if row['domain'].startswith(NODE_DOMAIN + ':') and row['split'] != 'holdout':
            lessons.setdefault(row['domain'].rsplit(':', 1)[1], []).append(row)
    return {p: (rows, np.asarray([r['vector'] for r in rows], dtype=np.float32)) for p, rows in lessons.items()}


def learn_node(root, scene, node_id, predicate, label, reason, source, *, user='', layer='corrective', split=None):
    """Instant node lesson: 'broken' adds the finding to similar nodes, 'fine'
    suppresses it. Effective on the next glance; no training."""
    if label not in {'broken', 'fine'} or predicate not in LESSON_TYPES or not reason.strip():
        raise ValueError('A broken/fine label, a text-intrinsic predicate (%s) and a reason are required' % ', '.join(LESSON_TYPES))
    node = next(n for n in scene['nodes'] if n['id'] == node_id)
    if not node_text(node):
        raise ValueError('Node lessons need visible text')
    from .laya_instant import store
    return store(str(root)).learn(node_domain(predicate), node_key(node, predicate), label, source, user=user, layer=layer,
                                  split=split, evidence={'reason': reason, 'sceneSha256': scene.get('sha256'), 'node': node_id,
                                                         'text': node['attributes'].get('text')})


def _nearest_lesson(lessons, predicate, node):
    entry = lessons.get(predicate)
    if not entry or not node_text(node):
        return None
    import numpy as np
    from .laya_instant import encode
    rows, matrix = entry
    vector, _ = encode(node_key(node, predicate), node_domain(predicate))
    sims = matrix @ vector
    i = int(np.argmax(sims))
    if sims[i] < LESSON_RADIUS:
        return None
    # Newest lesson among equally near ones wins (a correction supersedes).
    best = max((k for k in range(len(rows)) if sims[k] >= sims[i] - 1e-6), key=lambda k: rows[k]['id'])
    return rows[best], float(sims[best])


def _apply_lessons(result, scene, lessons):
    if not lessons:
        return result
    by_id = {n['id']: n for n in scene['nodes']}
    kept, learned = [], []
    for f in result['findings']:
        node = by_id.get(f['node'])
        hit = _nearest_lesson(lessons, f['predicate'], node) if node else None
        if hit and hit[0]['label'] == 'fine':
            learned.append({'predicate': f['predicate'], 'node': f['node'], 'lesson': hit[0]['id'], 'similarity': round(hit[1], 3), 'effect': 'suppressed'})
            continue
        kept.append(f)
    seen = {(f['predicate'], f['node']) for f in kept}
    for predicate in lessons:
        for node in scene['nodes']:
            if (predicate, node['id']) in seen or node['kind'] != 'text':
                continue
            hit = _nearest_lesson(lessons, predicate, node)
            if hit and hit[0]['label'] == 'broken':
                kept.append({'predicate': predicate, 'node': node['id'], 'severity': 'error', 'learned': True,
                             'evidence': {'attributes.text': node['attributes'].get('text'), 'lesson': hit[0]['id'],
                                          'similarity': round(hit[1], 3), 'reason': hit[0].get('evidence', {}).get('reason')},
                             'fix': {'action': 'ui.review-fix', 'arguments': {'pattern': predicate}}})
                seen.add((predicate, node['id']))
                learned.append({'predicate': predicate, 'node': node['id'], 'lesson': hit[0]['id'], 'similarity': round(hit[1], 3), 'effect': 'added'})
    return {**result, 'findings': kept, 'lessons': learned}


def quotes(text):
    """Quoted UI strings in a review finding or label note ('PT-5. ...', "Ho ...")."""
    found = re.findall(r"[‘'\"“]([^'\"’”]{2,80})[’'\"”]", text or '')
    return [q for q in found if re.search(r'[A-Za-z]{2}', q)]


def locate_quote(scene, quote):
    """Text node that shows a quoted string (token overlap; OCR-noise tolerant)."""
    want = [t for t in re.findall(r'[a-z0-9]+', quote.lower()) if len(t) >= 2]
    if not want:
        return None
    best, score = None, 0.0
    for node in scene['nodes']:
        if node['kind'] != 'text':
            continue
        have = set(re.findall(r'[a-z0-9]+', node_text(node)))
        hit = sum(t in have for t in want) / len(want)
        if hit > score:
            best, score = node, hit
    return best['id'] if best is not None and score >= (1.0 if len(want) == 1 else 0.6) else None


# --- the glance --------------------------------------------------------------

def cross_check(raw, pixel_scene, *, min_coverage=0.85):
    """Merge a pixel transcription into a DOM scene (hybrid observation).

    Every OCR line with real words should sit on a DOM text node; if too many do
    not, the DOM observation is incomplete (unhydrated page, closed shadow root,
    canvas text) and cannot certify a clean screen. Pixel text nodes are added
    with ``px:`` ids so pixel-only defects are still seen.
    """
    nodes = raw['nodes']
    view = raw.get('viewport') or {}
    pv = pixel_scene.get('viewport') or {}
    sx = (view.get('width') or pv.get('width') or 1) / float(pv.get('width') or 1)
    sy = (view.get('height') or pv.get('height') or 1) / float(pv.get('height') or 1)
    boxes = [n['attributes'].get('bounds') for n in nodes if n['attributes'].get('text') and n['attributes'].get('bounds')]
    lines = [n for n in pixel_scene['nodes'] if n['kind'] == 'text' and len(re.findall(r'[A-Za-z]', n['attributes']['text'])) >= 3]
    covered = 0
    for n in lines:
        b = n['attributes']['bounds']
        cx, cy = (b['x'] + b['w'] / 2) * sx, (b['y'] + b['h'] / 2) * sy
        covered += any(d['x'] - 4 <= cx <= d['x'] + d['w'] + 4 and d['y'] - 4 <= cy <= d['y'] + d['h'] + 4 for d in boxes)
    coverage = covered / len(lines) if lines else 1.0
    merged = {**raw, 'nodes': nodes + [{**n, 'id': 'px:' + n['id']} for n in pixel_scene['nodes']]}
    merged['metrics'] = {**(raw.get('metrics') or {}), 'domCoverageOfPixelText': round(coverage, 3),
                         'pixelLines': len(lines), 'pixelMs': pixel_scene['metrics'].get('totalMs')}
    if coverage < min_coverage:
        merged['truncated'] = True
        merged['unknownReasons'] = list(raw.get('unknownReasons', [])) + [
            f'DOM observation covers {coverage:.0%} of visible text lines; a clean verdict needs >= {min_coverage:.0%}']
    return merged


def glance(scene=None, *, root=None, screenshot=None, fuzzy=False, calibration=None, user='', lessons=None, record=True,
           hybrid=True):
    """Judge one UI observation.

    * screenshot only: the pixels are transcribed (OCR + measured facts) and the
      verdict is admitted through per-predicate calibration (approximate facts);
    * DOM scene: exact predicates; a clean answer needs complete coverage;
    * DOM scene + screenshot: pixel facts fill contrast, and (``hybrid``) the
      pixel transcription is merged in, so the screenshot cross-checks the DOM.
      Pixel-only findings count as defects only where calibration trusts that
      predicate at 0.95; otherwise they make the verdict uncertain.
    Returns the judge verdict plus ``bugs`` [{type,node,evidence,fix}],
    ``broken`` (True/False/None), unknown nodes and timing.
    """
    from .scene_core import judge, vocabulary
    started = time.perf_counter()
    if scene is None:
        if not screenshot:
            raise ValueError('Supply a scene or a screenshot')
        raw = _transcribe({'image': screenshot})
    elif screenshot:
        raw = fuse_pixels(scene, screenshot)
        if hybrid:
            raw = cross_check(raw, _transcribe({'image': screenshot}))
    else:
        raw = scene
    scene = transcribe(raw)
    rules = vocabulary('ui')
    if fuzzy:
        rules = rules + [{'id': 'fuzzy-quality', 'condition': {}, 'fuzzy': True, 'severity': 'warning',
                          'evidence': ['attributes', 'measurements'], 'fix': {'action': 'ui.review-fix', 'arguments': {'pattern': 'fuzzy-quality'}}}]
    mixed = any(n['id'].startswith('px:') for n in scene['nodes'])
    if calibration is None and (scene.get('measured') == 'approximate' or mixed):
        calibration = load_calibration(root or REPO)
    result = judge(scene, rules, root=root, user=user, record=record and scene.get('measured') != 'approximate' and not mixed,
                   calibration=calibration, level=LEVEL)
    if lessons is None:
        lessons = _node_lessons(root or REPO)
    result = _apply_lessons(result, scene, lessons)
    if scene.get('measured') == 'approximate':
        from .scene_core import admit_approximate
        result.update(admit_approximate(result['findings'], rules, calibration, LEVEL))
    elif mixed:
        cal = calibration or {}
        is_px = lambda f: f['node'].startswith('px:')
        exact = [f for f in result['findings'] if not is_px(f)]
        trusted = [f for f in result['findings'] if is_px(f) and cal.get(f['predicate'], {}).get('precisionLower', 0) >= LEVEL]
        advisory = [f for f in result['findings'] if is_px(f) and f not in trusted]
        # Pixel predicates are evaluated on pixel nodes too; only the DOM's own
        # unknowns block a clean answer.
        dom_unknown = sorted({p for p, ids in result.get('unknownNodes', {}).items() if any(not i.startswith('px:') for i in ids)})
        complete = not dom_unknown and not scene.get('truncated')
        admitted = bool(exact or trusted) or (complete and not advisory)
        reasons = list(raw.get('unknownReasons', []))
        if advisory and not (exact or trusted):
            reasons.append('pixel finding(s) below calibrated 0.95 precision: ' + ', '.join(sorted({f['predicate'] for f in advisory})))
        result.update(findings=exact + trusted, advisory=advisory, admitted=admitted, complete=complete, unknown=dom_unknown,
                      confidence=1.0 if admitted else 0.0,
                      confidenceKind=('calibrated-episodes' if trusted and not exact else 'observed-predicate') if admitted else 'uncalibrated',
                      escalation=None if admitted else {'kind': 'one-model-look', 'maxCalls': 1, 'maxScreenshots': 1, 'tour': False},
                      unknownReasons=reasons)
    bugs = [{'type': f['predicate'], 'node': f['node'], 'evidence': f['evidence'], 'fix': f['fix']} for f in result['findings']]
    by_id = {n['id']: n for n in scene['nodes']}
    unknown_texts = {p: [str(by_id[i]['attributes'].get('text') or i)[:40] for i in ids if i in by_id and not (mixed and i.startswith('px:'))]
                     for p, ids in result.get('unknownNodes', {}).items()}
    return {**result, 'bugs': bugs, 'broken': bool(bugs) if result['admitted'] else None, 'unknownTexts': unknown_texts,
            'transcriptionMs': scene.get('transcriptionMs'), 'sceneMetrics': scene.get('metrics', {}),
            'glanceMs': (time.perf_counter() - started) * 1000, 'layer': scene.get('layer')}


def learn(root, screenshot, label, reason, source, *, surface='', split=None, types=None, fired=None):
    """Write one labelled screenshot episode. ``types`` (dict type->0/1) also
    updates per-type calibration counts immediately (instant admission).
    ``fired`` (predicates the pixel glance raised) skips re-transcription."""
    if label not in {'broken', 'fine'} or not reason.strip():
        raise ValueError('A broken/fine label and a reason are required')
    from .laya_instant import store
    raw = Path(screenshot).read_bytes()
    frozen = Path(root) / '.neyvia/laya/glance-images' / (hashlib.sha256(raw).hexdigest() + '.png')
    frozen.parent.mkdir(parents=True, exist_ok=True)
    if not frozen.exists():
        frozen.write_bytes(raw)
    result = store(str(root)).learn(DOMAIN, {'image': str(frozen.resolve())}, label, source,
                                    evidence={'reason': reason, 'surface': surface, 'sourceScreenshot': str(screenshot),
                                              **({'types': types} if types else {})}, split=split)
    if types and split != 'holdout':
        if fired is None:
            verdict = glance(screenshot=str(frozen), root=root, calibration={}, lessons={}, record=False)
            fired = {f['type'] for f in verdict['bugs']}
        result['calibration'] = update_calibration(root, source, set(fired), types)
    return result


def update_calibration(root, source, fired, types):
    """Idempotent per source: replace this screenshot's contribution, then save."""
    path = _calibration_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    version = transcriber_version()
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if data.get('transcriber') != version:
        data = {'transcriber': version, 'level': LEVEL, 'sources': {}}
    data['sources'][source] = {t: [int(t in fired), int(bool(types.get(t)))] for t in TYPES if t in types}
    counts = {t: {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0} for t in TYPES}
    for rows in data['sources'].values():
        for t, (f, y) in rows.items():
            counts[t]['tp' if f and y else 'fp' if f else 'fn' if y else 'tn'] += 1
    data['counts'] = counts
    data['updatedAt'] = time.time()
    path.write_text(json.dumps(data, indent=1), encoding='utf-8')
    return {t: {k: counts[t][k] for k in ('tp', 'fp', 'tn', 'fn')} for t in TYPES}
