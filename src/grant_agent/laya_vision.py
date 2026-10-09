"""Evolving vision (plan 24): the model look, look memory, and lens authoring.

1. ``look``     -- the "one model look" escalation, actually executed. One call to a
                   vision model (gpt-6-luna through ``codex exec``, Paul's existing
                   subscription; ``autopilot_model.decide``) with the screenshot, the
                   Scene, the definitions, the lens list and the question. It answers
                   with a verdict, per-type labels, a CL description of what it saw in
                   terms of existing lens ids, and the observables no lens covers.
2. ``remember`` -- every look is written as episodes at once (plan 21): one ``ui-look``
                   screenshot episode (frozen CLIP input) and node lessons for quoted
                   text-intrinsic defects. ``recall`` answers the next near-identical
                   screenshot locally, inside a radius calibrated on labelled episodes.
3. ``author_lens`` -- a cheap code model (Luna) writes a lens program for a missing
                   observable; ``lenses.validate_source`` and a smoke run gate it, and
                   the caller's held-out evaluation decides keep / reject (receipts).

Model calls are capped per run (``LookLog``) and every call is logged with tokens.
Nothing here trains. Model answers are untrusted data; they never execute.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time

from .laya_glance import TYPES, LESSON_TYPES, locate_quote, learn_node, node_text

REPO = Path(__file__).resolve().parents[2]
LOOK_DOMAIN = 'ui-look'
HOLD = Path('C:/Users/user/Projects/plans/logs/codex-budget.hold')
MODEL = 'gpt-6-luna'


class BudgetExhausted(RuntimeError):
    pass


class LookLog:
    """Per-run cap and append-only log of every model call (looks and lens authoring)."""

    def __init__(self, path, *, cap_looks=200, cap_authoring=40):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cap = {'look': cap_looks, 'author': cap_authoring}
        self.counts = {'look': 0, 'author': 0}
        if self.path.exists():
            for line in self.path.read_text(encoding='utf-8').splitlines():
                row = json.loads(line)
                if row.get('kind') in self.counts and row.get('status') != 'refused':
                    self.counts[row['kind']] += 1

    def reserve(self, kind):
        if HOLD.exists():
            raise BudgetExhausted('Codex budget hold is active (plans/logs/codex-budget.hold)')
        if self.counts[kind] >= self.cap[kind]:
            raise BudgetExhausted(f'{kind} cap {self.cap[kind]} reached for this run')
        self.counts[kind] += 1

    def write(self, row):
        with self.path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), **row}, ensure_ascii=False) + '\n')


# --- the model look ----------------------------------------------------------

RUBRIC = Path('D:/NeyviaRuns/laya-labels/RUBRIC.md')


def _definitions():
    from .laya_glance import _vocabulary
    return {r['id']: r.get('means', '') for r in _vocabulary()}


def _rubric():
    """The labelling rubric's type definitions (the same words the ground truth used)."""
    try:
        text = RUBRIC.read_text(encoding='utf-8')
        return text.split('## Types', 1)[1].split('## Output', 1)[0].strip()
    except (OSError, IndexError):
        return '\n'.join(f'- **{t}**: {m}' for t, m in _definitions().items())


def look_schema(types):
    return {
        'type': 'object', 'additionalProperties': False,
        'required': ['verdict', 'types', 'defects', 'seen', 'missing'],
        'properties': {
            'verdict': {'type': 'string', 'enum': ['broken', 'fine', 'unsure']},
            'types': {'type': 'object', 'additionalProperties': False, 'required': list(types),
                      'properties': {t: {'type': 'integer', 'enum': [0, 1]} for t in types}},
            'defects': {'type': 'array', 'maxItems': 12, 'items': {
                'type': 'object', 'additionalProperties': False,
                'required': ['type', 'where', 'box', 'lens', 'observable', 'description'],
                'properties': {
                    'type': {'type': 'string', 'enum': list(types)},
                    'where': {'type': 'string'},
                    'box': {'type': 'object', 'additionalProperties': False, 'required': ['x', 'y', 'w', 'h'],
                            'properties': {k: {'type': 'number'} for k in ('x', 'y', 'w', 'h')}},
                    'lens': {'type': 'string'},
                    'observable': {'type': 'string'},
                    'description': {'type': 'string'}}}},
            'seen': {'type': 'array', 'maxItems': 16, 'items': {
                'type': 'object', 'additionalProperties': False, 'required': ['lens', 'node', 'value'],
                'properties': {'lens': {'type': 'string'}, 'node': {'type': 'string'}, 'value': {'type': 'string'}}}},
            'missing': {'type': 'array', 'maxItems': 6, 'items': {
                'type': 'object', 'additionalProperties': False, 'required': ['name', 'type', 'description', 'measure'],
                'properties': {'name': {'type': 'string'}, 'type': {'type': 'string', 'enum': list(types)},
                               'description': {'type': 'string'}, 'measure': {'type': 'string'}}}},
        }}


LOOK_SCHEMA = look_schema(TYPES)


def scene_digest(scene, limit=70):
    """Compact Scene view for the prompt: text nodes with ids, boxes and notable facts."""
    rows = []
    notable = ('contrastRatio', 'spacedEllipsis', 'crossesSurfaceEdge', 'overlap', 'viewportCut', 'offScreenControl',
               'uniform', 'expectedContent')
    for n in scene['nodes']:
        m = n.get('measurements', {})
        b = n.get('attributes', {}).get('bounds') or {}
        facts = {k: m[k] for k in notable if k in m and m[k] not in (None, False, [], '')}
        facts.update({k: v for k, v in m.items() if k not in notable and k not in ('source', 'lens') and v not in (None, False, [], '')
                      and not isinstance(v, (dict,))})
        rows.append((bool(facts) or n['kind'] != 'text', {'id': n['id'], 'kind': n['kind'],
                     'text': str(n.get('attributes', {}).get('text') or '')[:80],
                     'box': [round(b.get(k, 0)) for k in ('x', 'y', 'w', 'h')] if b else None, 'facts': facts}))
    rows.sort(key=lambda r: not r[0])
    return [r for _, r in rows[:limit]]


def question_for(verdict):
    adm = verdict.get('admission') or {}
    fired = adm.get('fired') or sorted({b['type'] for b in verdict.get('bugs', [])})
    weak = adm.get('uncalibratedNegatives') or []
    if fired:
        return ('Pixel lenses raised ' + ', '.join(fired) + ' but their calibrated precision is below 0.95. '
                'Confirm or reject each, and label every type.')
    return ('Pixel lenses found no defect, but they cannot certify a clean screen for: ' + ', '.join(weak or TYPES) +
            '. Is any defect of these types visible? Label every type.')


def _ui_prompt(scene, verdict, question, lens_cl):
    defs = _definitions()
    view = scene.get('viewport') or {}
    return '\n'.join([
        'You are LAYA\'s one model look at a screenshot of the Neyvia desktop app. LAYA measured the screenshot with '
        'small programs called lenses; their facts are below, but lenses miss many defects and raise false alarms. '
        'Scan the whole image yourself first (edges, status bar, chips, panels, icons next to text), then compare.',
        '', 'Defect types (label 1 only if visible in this screenshot):', _rubric(),
        '', 'Short definitions LAYA\'s predicates use:', *[f'- {t}: {defs.get(t, "")}' for t in TYPES],
        '', 'Lenses (existing eyes; cite their ids in "seen" and "defects.lens"):', lens_cl,
        '', f'Screenshot size: {view.get("width")}x{view.get("height")} px. Scene nodes (id, kind, text, box [x,y,w,h], facts):',
        json.dumps(scene_digest(scene), ensure_ascii=False),
        '', 'Question: ' + question,
        '', 'Answer rules:',
        '- verdict: broken if any type is 1, fine if none, unsure only if the image is unreadable.',
        '- types: 0/1 for every type.',
        '- defects: each visible defect with the quoted visible text nearest to it ("where"), its box in screenshot pixels, '
        'the lens id that measures it if one does ("lens"), else lens "none" and a short kebab-case name of the observable '
        'that would show it ("observable").',
        '- seen: up to 16 lens facts you confirm or refute (lens id, node id, what you see).',
        '- missing: observables no lens covers that would have let LAYA answer without you. Name each in kebab-case, '
        'say which type it serves, describe it, and say how pixels could measure it (geometry, colours, edges).',
    ])


_prompt = _ui_prompt  # backward-compatible name

UI_SPEC = {'domain': 'ui', 'types': TYPES, 'lensInput': 'screenshot', 'prompt': _ui_prompt, 'question': question_for}


def look_cl(answer, *, screenshot_sha, model, receipt_sha, question):
    lines = ['CL 1.1', f'L look v1 -- untrusted model observation; {model} via codex exec; receipt {receipt_sha[:16]}',
             'S look ' + json.dumps({'verdict': answer['verdict'], 'screenshotSha256': screenshot_sha, 'question': question,
                                     'types': answer['types']}, ensure_ascii=False, sort_keys=True)]
    lines += ['E saw ' + json.dumps(s, ensure_ascii=False, sort_keys=True) for s in answer['seen']]
    lines += ['E defect ' + json.dumps(d, ensure_ascii=False, sort_keys=True) for d in answer['defects']]
    lines += ['E missing ' + json.dumps(m, ensure_ascii=False, sort_keys=True) for m in answer['missing']]
    return '\n'.join(lines)


def kebab(name):
    return re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')[:63] or 'unnamed'


def look(screenshot, scene, verdict, *, root, log, model=MODEL, question=None, timeout=300, spec=None):
    """Execute the one model look. Returns {answer, cl, missing, receipt, tokens, ms}."""
    from .autopilot_model import decide, AutopilotModelError
    from .scene_core.lenses import entries, registry_cl
    spec = spec or UI_SPEC
    log.reserve('look')
    question = question or spec['question'](verdict)
    shot = Path(screenshot)
    sha = hashlib.sha256(shot.read_bytes()).hexdigest()
    started = time.perf_counter()
    try:
        result = decide(spec['prompt'](scene, verdict, question, registry_cl(spec['lensInput'])), look_schema(spec['types']), root,
                        model=model, timeout=timeout, images=[shot], reasoning_effort='low')
    except AutopilotModelError as exc:
        log.write({'kind': 'look', 'status': 'failed', 'model': model, 'screenshotSha256': sha, 'error': str(exc)[:300],
                   'receipt': getattr(exc, 'receipt_path', None) or (exc.args[1] if len(exc.args) > 1 else None)})
        raise
    ms = (time.perf_counter() - started) * 1000
    answer = result['answer']
    known = {e['id'] for e in entries() if e['inputType'] == spec['lensInput']}
    for d in answer['defects']:
        if d['lens'] not in known:
            d['observable'] = kebab(d['observable'] or d['lens'])
            d['lens'] = 'none'
        else:
            d['observable'] = ''
    answer['seen'] = [s for s in answer['seen'] if s['lens'] in known]
    for m in answer['missing']:
        m['name'] = kebab(m['name'])
    # A defect without a lens names a missing observable even if the model forgot to list it.
    named = {m['name'] for m in answer['missing']}
    for d in answer['defects']:
        if d['lens'] == 'none' and d['observable'] not in named:
            answer['missing'].append({'name': d['observable'], 'type': d['type'], 'description': d['description'], 'measure': ''})
            named.add(d['observable'])
    receipt = Path(result['receiptPath'])
    receipt_sha = hashlib.sha256(receipt.read_bytes()).hexdigest()
    cl = look_cl(answer, screenshot_sha=sha, model=model, receipt_sha=receipt_sha, question=question)
    row = {'kind': 'look', 'status': 'completed', 'model': model, 'screenshot': str(shot), 'screenshotSha256': sha,
           'tokens': result.get('tokens'), 'ms': round(ms), 'receipt': str(receipt), 'verdict': answer['verdict'],
           'types': answer['types'], 'missing': [m['name'] for m in answer['missing']]}
    log.write(row)
    return {'answer': answer, 'cl': cl, 'receipt': str(receipt), 'receiptSha256': receipt_sha, 'tokens': result.get('tokens'),
            'ms': ms, 'screenshotSha256': sha, 'question': question}


# --- every look becomes episodes ---------------------------------------------

def remember(root, screenshot, scene, result, *, surface='', domain=LOOK_DOMAIN, lessons=True):
    """Write the look as episodes immediately: the screenshot verdict (CLIP input) and node
    lessons for quoted text-intrinsic defects. Source = the look receipt (forgettable)."""
    from .laya_instant import store
    answer = result['answer']
    raw = Path(screenshot).read_bytes()
    frozen = Path(root) / '.neyvia/laya/glance-images' / (hashlib.sha256(raw).hexdigest() + Path(screenshot).suffix)
    frozen.parent.mkdir(parents=True, exist_ok=True)
    if not frozen.exists():
        frozen.write_bytes(raw)
    source = 'model-look:' + result['receiptSha256'][:24]
    written = {'look': store(str(root)).learn(domain, {'image': str(frozen.resolve())}, answer['verdict'], source,
                                              evidence={'kind': 'model-look', 'types': answer['types'], 'surface': surface,
                                                        'cl': result['cl'], 'receipt': result['receipt']})}
    lessons = []
    for d in answer['defects'] if lessons else []:
        if d['type'] not in LESSON_TYPES or not d['where'].strip():
            continue
        node = locate_quote(scene, d['where'])
        if not node:
            continue
        n = next(x for x in scene['nodes'] if x['id'] == node)
        if not node_text(n):
            continue
        lessons.append(learn_node(root, scene, node, d['type'], 'broken', 'Model look: ' + d['description'][:300],
                                  source + ':' + d['type'] + ':' + hashlib.sha256(node_text(n).encode()).hexdigest()[:12]))
    written['lessons'] = lessons
    return written


def recall(root, screenshot, *, radius, domain=LOOK_DOMAIN):
    """Answer locally from an earlier look on a near-identical screenshot (cosine >= radius
    on the frozen CLIP embedding). Returns the stored look or None."""
    import numpy as np
    from .laya_instant import store, latest_episodes, encode
    local = store(str(root))
    local.refresh()
    rows = [r for r in latest_episodes(local.rows) if r['domain'] == domain]
    if not rows:
        return None
    vector, identity = encode({'image': str(Path(screenshot).resolve())}, domain)
    rows = [r for r in rows if r['encoder'] == identity]
    if not rows:
        return None
    matrix = np.asarray([r['vector'] for r in rows], dtype=np.float32)
    sims = matrix @ (vector / max(float(np.linalg.norm(vector)), 1e-9)) / np.maximum(np.linalg.norm(matrix, axis=1), 1e-9)
    i = int(np.argmax(sims))
    if sims[i] < radius:
        return None
    r = rows[i]
    return {'verdict': r['label'], 'types': r['evidence'].get('types', {}), 'similarity': round(float(sims[i]), 4),
            'episodeId': r['id'], 'source': r['source']}


# --- lens authoring by a cheap code model ------------------------------------

def author_schema(types):
    return {
        'type': 'object', 'additionalProperties': False,
        'required': ['id', 'program', 'emits', 'branch', 'rationale'],
        'properties': {
            'id': {'type': 'string'},
            'program': {'type': 'string'},
            'emits': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': {
                'type': 'object', 'additionalProperties': False, 'required': ['fact', 'type', 'cl'],
                'properties': {'fact': {'type': 'string'}, 'type': {'type': 'string', 'enum': ['bool', 'number', 'list', 'str']},
                               'cl': {'type': 'string'}}}},
            'branch': {'type': 'object', 'additionalProperties': False, 'required': ['predicate', 'condition_json'],
                       'properties': {'predicate': {'type': 'string', 'enum': list(types)}, 'condition_json': {'type': 'string'}}},
            'rationale': {'type': 'string'},
        }}


AUTHOR_SCHEMA = author_schema(TYPES)

LENS_CONTRACT = '''Write ONE Python lens program (a small measuring function) for LAYA.

Contract:
- Define `measure(rgb, nodes, viewport)` and nothing that runs at import time except constants/imports.
  * rgb: numpy uint8 array HxWx3 of the screenshot.
  * nodes: list of dicts {"id": str, "kind": "text"|"page"|"viewport-edge"|..., "text": str,
    "bounds": {"x","y","w","h"} in screenshot pixels} (text nodes are OCR lines; OCR often misses icons and cut glyphs).
  * viewport: {"width": W, "height": H}.
- Return {"facts": {node_id: {fact_name: value}}, "nodes": [{"kind": str, "text": str, "bounds": {...}, "facts": {...}}]}.
  Facts are bool/number/short list/short string. Fact names are camelCase ([a-z][A-Za-z0-9]{1,47}, no
  underscores) and must be the names listed in "emits". Use "nodes" only for regions no OCR node covers (max 200).
- Allowed imports: numpy, math, scipy.ndimage, collections, itertools, functools, statistics, re.
  No file, network, os, sys, eval/exec, getattr, dunder names, classes, or attributes starting with "_".
- Must run in < 60 ms on a 1440x900 image (vectorise with numpy; avoid per-pixel Python loops).
- Measure only; never decide the defect type in the program. The predicate branch (data, not code)
  decides, using the facts you emit.
- Prefer precision: the fact should be true on the defect and false on ordinary layouts
  (icons next to labels with normal spacing, chips, avatars, scrollbars, intended overlays).

Branch: a JSON condition in LAYA's predicate language, OR-ed into one existing predicate:
  {"all":[{"field":"measurements.source","op":"eq","value":"pixels"},{"field":"measurements.<fact>","op":"eq","value":true}]}
  ops: eq lt le gt ge nonempty matches; combinators all/any; fields "measurements.<fact>" or "attributes.text".
'''


def _author_prompt(observable, examples, existing_facts, feedback=None, contract=None):
    parts = [contract or LENS_CONTRACT, '', 'Missing observable to measure (named by model looks):',
             json.dumps(observable, ensure_ascii=False, indent=1),
             '', 'Existing fact names you must not reuse: ' + ', '.join(sorted(existing_facts)),
             '', 'Labelled examples (images attached in this order; positives show the defect, negatives do not):',
             json.dumps(examples, ensure_ascii=False, indent=1)]
    if feedback:
        parts += ['', 'Your previous program failed. Fix it. Feedback:', feedback]
    parts += ['', 'Return: id (kebab-case lens id), program (full Python source), emits (fact name, type, a one-line CL '
              'description of what it measures), branch (predicate + condition_json string), rationale (2 sentences).']
    return '\n'.join(parts)


def author_lens(observable, examples, images, *, root, log, feedback=None, model=MODEL, timeout=420, spec=None):
    """One Luna call that writes a candidate lens. Returns (entry-without-status, source, receipt)."""
    from .autopilot_model import decide, AutopilotModelError
    from .scene_core.lenses import entries
    spec = spec or UI_SPEC
    log.reserve('author')
    existing = {f for e in entries() for f in e['emits']} | {'source', 'lens', 'text', 'bounds'}
    started = time.perf_counter()
    try:
        result = decide(_author_prompt(observable, examples, existing, feedback, spec.get('contract')), author_schema(spec['types']), root, model=model,
                        timeout=timeout, images=[Path(p) for p in images][:4], reasoning_effort='medium')
    except AutopilotModelError as exc:
        log.write({'kind': 'author', 'status': 'failed', 'model': model, 'observable': observable.get('name'),
                   'error': str(exc)[:300]})
        raise
    answer = result['answer']
    log.write({'kind': 'author', 'status': 'completed', 'model': model, 'observable': observable.get('name'),
               'tokens': result.get('tokens'), 'ms': round((time.perf_counter() - started) * 1000),
               'receipt': result['receiptPath'], 'lens': answer.get('id')})
    try:
        condition = json.loads(answer['branch']['condition_json'])
    except json.JSONDecodeError:
        condition = None
    entry = {'id': kebab(answer['id']), 'inputType': spec['lensInput'],
             'emits': {e['fact']: {'type': e['type'], 'cl': e['cl'][:200]} for e in answer['emits']},
             'branch': {'predicate': answer['branch']['predicate'], 'condition': condition},
             'predicates': [answer['branch']['predicate']],
             'provenance': {'author': model + ' via codex exec (autopilot_model.decide)', 'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                            'receipt': result['receiptPath'], 'tokens': result.get('tokens'),
                            'requestedBy': observable, 'rationale': answer['rationale'][:600]}}
    return entry, answer['program'], result['receiptPath']
