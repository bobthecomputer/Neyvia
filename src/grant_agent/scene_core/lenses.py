"""Lens registry: LAYA's eyes as a growing set of small measuring programs (plan 24).

A lens measures ONE observable and emits it as Scene facts (so it reaches CL through
the Scene's ``E node`` lines and the shared predicate language). Every lens has

  id          [a-z][a-z0-9-]{1,63}
  inputType   screenshot | dom | render | mesh
  emits       {fact: {type, cl}}  -- output schema; ``cl`` says in words what it measures
  cost        measured median/p95 ms (program lenses) or the shared transcriber cost
  provenance  who wrote it, when, from which request, with which receipt
  status      active | candidate | rejected | retired (+ the decision receipt)

Built-in lenses describe the facts the existing observers already measure
(laya_glance_image.py pixels, perception_scene.js DOM, Blender native mesh facts).
Program lenses are model-written Python kept in ``lens_programs/``. They run only when
their file hash equals the registry pin, after an AST allow-list check, with a
restricted import hook and builtins. A program lens may add one ``branch`` (a bounded
predicate condition, never code) that is OR-ed into one predicate of its domain.

Registry: config/laya_lenses.json. Nothing here trains anything.
"""
from __future__ import annotations

import ast
import builtins as _builtins
import os
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import time

REPO = Path(__file__).resolve().parents[3]
REGISTRY = REPO / 'config/laya_lenses.json'


def registry_path():
    """config/laya_lenses.json, or a run-local registry (NEYVIA_LAYA_LENSES) for experiments."""
    return Path(os.environ.get('NEYVIA_LAYA_LENSES') or REGISTRY)
PROGRAMS = Path(__file__).resolve().parent / 'lens_programs'
INPUT_TYPES = ('screenshot', 'dom', 'render', 'mesh')
STATUSES = ('active', 'candidate', 'rejected', 'retired')
SCHEMA = 'neyvia.laya.lenses.v1'
ID = re.compile(r'[a-z][a-z0-9-]{1,63}')
FACT = re.compile(r'[a-z][A-Za-z0-9]{1,47}')
ALLOWED_IMPORTS = {'numpy', 'math', 'scipy', 'scipy.ndimage', 'collections', 'itertools', 'functools',
                   'statistics', 're', 'heapq', 'bisect'}
FORBIDDEN_NAMES = {'open', 'exec', 'eval', 'compile', '__import__', 'globals', 'locals', 'vars', 'input',
                   'breakpoint', 'getattr', 'setattr', 'delattr', 'memoryview', 'exit', 'quit', 'help',
                   'dir', 'classmethod', 'staticmethod', 'property', 'super', 'object', 'type'}
FORBIDDEN_ATTRS = {'load', 'loads', 'save', 'savez', 'savez_compressed', 'savetxt', 'loadtxt', 'fromfile',
                   'tofile', 'memmap', 'ctypeslib', 'lib', 'distutils', 'testing', 'f2py', 'genfromtxt',
                   'DataSource', 'system', 'popen', 'dump', 'dumps', 'frombuffer', 'ctypes', 'os', 'sys', 'io',
                   'datasets', 'misc', 'fromregex', 'fromstring', 'compat', 'show_config', 'loadmat', 'savemat'}
SAFE_BUILTINS = {name: getattr(_builtins, name) for name in (
    'abs', 'all', 'any', 'bool', 'dict', 'enumerate', 'filter', 'float', 'frozenset', 'int', 'isinstance',
    'len', 'list', 'map', 'max', 'min', 'range', 'reversed', 'round', 'set', 'slice', 'sorted', 'str', 'sum',
    'tuple', 'zip', 'divmod', 'pow', 'hash', 'iter', 'next', 'ValueError', 'IndexError', 'KeyError',
    'ZeroDivisionError', 'Exception', 'TypeError', 'ArithmeticError', 'True', 'False', 'None', 'print')}
MAX_NEW_NODES = 200

_OVERRIDE = None  # evaluation: an explicit lens set (list of entries) instead of the registry


# --- built-in lenses (descriptions of existing observers) ------------------

def _builtin_entries():
    """The eyes LAYA already had on 6 Oct, written down as lenses with provenance."""
    from_image = 'src/grant_agent/laya_glance_image.py'
    image_sha = _sha(REPO / from_image)
    pixels = {'author': 'LAYAG (Codex track, plan 23)', 'at': '2026-10-05', 'program': from_image, 'programSha256': image_sha,
              'note': 'Built into the pixel transcriber; one shared cost (OCR + pixel facts).'}
    dom = {'author': 'LAYAG (Codex track, plan 23)', 'at': '2026-10-05', 'program': 'src/grant_agent/perception_scene.js',
           'programSha256': _sha(REPO / 'src/grant_agent/perception_scene.js')}
    mesh = {'author': 'LAYA3D (Codex track, plan 23)', 'at': '2026-10-06', 'program': 'scripts/gamedev/blender/neyvia_bridge',
            'note': 'Native Blender bridge transcribe facts.'}
    shared = {'scope': 'shared', 'note': 'OCR ~170 ms + all pixel facts ~245 ms (LAYAG-eval medians)'}
    rows = [
        ('ocr-lines', 'screenshot', {'text': ('str', 'the words of one visible text line'),
                                     'bounds': ('box', 'where that line is painted')}, ['*'], pixels),
        ('ink-contrast', 'screenshot', {'contrastRatio': ('number', 'contrast between a text line\'s ink and its painted surround')},
         ['unreadable-contrast'], pixels),
        ('detached-ellipsis', 'screenshot', {'spacedEllipsis': ('bool', 'a text fragment is followed by a detached ellipsis'),
                                             'ellipsisGap': ('number', 'pixels between the fragment and the ellipsis')},
         ['clipped-text'], pixels),
        ('surface-edge-crossing', 'screenshot', {'crossesSurfaceEdge': ('list', 'a long panel boundary runs straight through a text line')},
         ['see-through'], pixels),
        ('text-box-overlap', 'screenshot', {'overlap': ('list', 'two OCR text boxes are painted on top of each other')},
         ['overlap'], pixels),
        ('viewport-edge-cut', 'screenshot', {'viewportCut': ('bool', 'glyph ink of a text line touches the viewport edge'),
                                             'offScreenControl': ('bool', 'a control or its label is cut by the viewport edge')},
         ['off-screen-control'], pixels),
        ('page-uniformity', 'screenshot', {'uniform': ('bool', 'a fully visible page-shaped rectangle is flat (no text, no vertical detail)'),
                                           'expectedContent': ('bool', 'the rectangle is a page that must show content')},
         ['blank-render'], pixels),
        ('dom-style-facts', 'dom', {'backgroundAlpha': ('number', 'opacity of a surface background'),
                                    'behindText': ('list', 'text painted underneath a surface'),
                                    'clippedText': ('bool', 'glyph rects outside their clip box'),
                                    'contrastRatio': ('number', 'computed foreground/background contrast'),
                                    'offScreenControl': ('bool', 'a control box outside the viewport')},
         ['see-through', 'clipped-text', 'unreadable-contrast', 'off-screen-control', 'overlap'], dom),
        ('mesh-topology', 'mesh', {'flippedNormals': ('number', 'faces whose normal points into the solid'),
                                   'nonManifoldEdges': ('number', 'edges shared by other than two faces'),
                                   'smallComponentVertices': ('number', 'vertices in small detached parts (floaters)'),
                                   'scaleError': ('number', 'relative error of the object scale against its unit')},
         ['flipped-normals', 'non-manifold', 'floaters', 'unapplied-scale'], mesh),
    ]
    out = []
    for lens_id, kind, emits, predicates, prov in rows:
        out.append({'id': lens_id, 'inputType': kind, 'status': 'active', 'builtin': True,
                    'emits': {k: {'type': t, 'cl': c} for k, (t, c) in emits.items()}, 'predicates': predicates,
                    'cost': shared if kind == 'screenshot' else {'scope': 'observer'}, 'provenance': prov,
                    'decision': {'status': 'active', 'reason': 'existing observer before plan 24 (baseline eyes)'}})
    return out


def _sha(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


# --- registry ---------------------------------------------------------------

def load(path=None):
    path = Path(path or registry_path())
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'schema': SCHEMA, 'lenses': []}
    if data.get('schema') != SCHEMA:
        raise ValueError('Unknown lens registry schema')
    return data


def save(data, path=None):
    path = Path(path or registry_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    data['updatedAt'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')


def entries(path=None, *, include_builtin=True):
    rows = list(_builtin_entries()) if include_builtin else []
    return rows + [validate_entry(e) for e in load(path)['lenses']]


def active(input_type, domain_predicates=None):
    """Active program lenses for one input type (or the evaluation override)."""
    rows = _OVERRIDE if _OVERRIDE is not None else [e for e in load()['lenses'] if e['status'] == 'active']
    return [e for e in rows if e['inputType'] == input_type and not e.get('builtin')]


@contextmanager
def override(lens_entries):
    """Evaluate with an explicit lens set (candidates included); restores afterwards."""
    global _OVERRIDE
    old, _OVERRIDE = _OVERRIDE, [validate_entry(e) for e in lens_entries]
    try:
        yield
    finally:
        _OVERRIDE = old


def identity(input_type='screenshot'):
    """Hash of the active program lenses (ids, pinned code, branches). Empty when none:
    the baseline transcriber identity is unchanged until a lens is adopted."""
    rows = active(input_type)
    if not rows:
        return ''
    body = json.dumps([[e['id'], e['programSha256'], e.get('branch')] for e in sorted(rows, key=lambda e: e['id'])], sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def validate_entry(e):
    if not ID.fullmatch(str(e.get('id', ''))) or e.get('inputType') not in INPUT_TYPES or e.get('status') not in STATUSES:
        raise ValueError('Lens needs an id, an input type and a status: %r' % e.get('id'))
    if not isinstance(e.get('emits'), dict) or not e['emits'] or not all(FACT.fullmatch(k) for k in e['emits']):
        raise ValueError('Lens %s needs a fact output schema: fact names are camelCase [a-z][A-Za-z0-9]{1,47}, got %s'
                         % (e['id'], sorted(e.get('emits') or {})))
    if not e.get('builtin'):
        if not e.get('program') or not e.get('programSha256') or not isinstance(e.get('provenance'), dict):
            raise ValueError('Program lens %s needs a pinned program and provenance' % e['id'])
        if e.get('branch') is not None:
            validate_branch(e['branch'], set(e['emits']))
    return e


OPS = {'eq', 'lt', 'le', 'gt', 'ge', 'nonempty', 'matches'}


def validate_branch(branch, emitted):
    """A branch is data: {predicate, condition} in the shared bounded predicate language.
    It must read at least one fact this lens emits."""
    if not isinstance(branch, dict) or not ID.fullmatch(str(branch.get('predicate', ''))):
        raise ValueError('Lens branch needs a predicate id')
    used = set()

    def walk(c, depth=0):
        if depth > 4 or not isinstance(c, dict):
            raise ValueError('Lens branch condition is too deep or malformed')
        if 'all' in c or 'any' in c:
            key = 'all' if 'all' in c else 'any'
            if set(c) != {key} or not isinstance(c[key], list) or not 1 <= len(c[key]) <= 6:
                raise ValueError('Lens branch combinator malformed')
            for sub in c[key]:
                walk(sub, depth + 1)
            return
        if set(c) - {'field', 'op', 'value'} or c.get('op') not in OPS or not re.fullmatch(r'(measurements|attributes)\.[A-Za-z0-9_.]{1,80}|kind|id', str(c.get('field', ''))):
            raise ValueError('Lens branch leaf malformed (fields: kind, id, measurements.<fact>, attributes.<name>): %r' % c)
        if c['op'] == 'matches' and len(str(c.get('value', ''))) > 300:
            raise ValueError('Lens branch regex too long')
        if '.' in c['field']:
            used.add(c['field'].split('.', 1)[1].split('.')[0])
    walk(branch['condition'])
    if not used & emitted:
        raise ValueError('Lens branch must read a fact the lens emits')
    return branch


def with_branches(rules, input_type='screenshot'):
    """OR each active lens branch into its predicate (vocabulary stays CL data)."""
    extra = {}
    for e in active(input_type):
        if e.get('branch'):
            extra.setdefault(e['branch']['predicate'], []).append(e['branch']['condition'])
    if not extra:
        return rules
    out = []
    for r in rules:
        if r['id'] in extra:
            # A predicate declared without eyes ("awaitsLens") is defined by its lens branches alone;
            # otherwise the branches are OR-ed into the authored condition.
            base = [] if r.get('awaitsLens') else [r['condition']]
            r = {**r, 'condition': {'any': [*base, *extra[r['id']]]},
                 'lenses': [e['id'] for e in active(input_type) if (e.get('branch') or {}).get('predicate') == r['id']]}
        out.append(r)
    return out


# --- program lenses: validation and restricted execution -------------------

def validate_source(source):
    """AST allow-list for model-written lens code. Raises ValueError with the reason."""
    if len(source) > 20000:
        raise ValueError('Lens program longer than 20000 characters')
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
            for name in names:
                if name not in ALLOWED_IMPORTS:
                    raise ValueError('Import not allowed in a lens: ' + name)
            if isinstance(node, ast.ImportFrom) and node.level:
                raise ValueError('Relative imports not allowed in a lens')
        elif isinstance(node, ast.Name) and (node.id in FORBIDDEN_NAMES or node.id.startswith('__')):
            raise ValueError('Name not allowed in a lens: ' + node.id)
        elif isinstance(node, ast.Attribute) and (node.attr.startswith('_') or node.attr in FORBIDDEN_ATTRS):
            raise ValueError('Attribute not allowed in a lens: ' + node.attr)
        elif isinstance(node, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await, ast.ClassDef)):
            raise ValueError('Statement not allowed in a lens: ' + type(node).__name__)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and '__' in node.value:
            raise ValueError('Dunder strings not allowed in a lens')
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if 'measure' not in names:
        raise ValueError('A lens defines measure(rgb, nodes, viewport)')
    return tree


def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    # Lens source may import only ALLOWED_IMPORTS (checked on the AST). At run time numpy and
    # scipy resolve their own lazy submodules through the caller's import hook, so their
    # subpackages and modules already loaded in this process are let through.
    import sys
    top = name.split('.', 1)[0]
    if level and globals and str(globals.get('__name__', '')).split('.', 1)[0] in ('numpy', 'scipy'):
        return __import__(name, globals, locals, fromlist, level)
    if level or not (name in ALLOWED_IMPORTS or top in ('numpy', 'scipy') or name in sys.modules):
        raise ImportError('Import not allowed in a lens: ' + name)
    return __import__(name, globals, locals, fromlist, level)


_LOADED = {}


def load_program(entry):
    path = Path(entry['program'])
    path = path if path.is_absolute() else REPO / path
    source = path.read_text(encoding='utf-8')
    digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
    if digest != entry['programSha256']:
        raise ValueError('Lens program %s differs from its registry pin' % entry['id'])
    if digest in _LOADED:
        return _LOADED[digest]
    validate_source(source)
    namespace = {'__builtins__': {**SAFE_BUILTINS, '__import__': _restricted_import}, '__name__': 'lens_' + entry['id'].replace('-', '_')}
    exec(compile(source, str(path), 'exec'), namespace)  # validated, pinned, restricted (see module doc)
    fn = namespace['measure']
    _LOADED[digest] = fn
    return fn


def _clean_value(v):
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v if not isinstance(v, str) else v[:200]
    if isinstance(v, (int, float)):
        f = float(v)
        if f != f or f in (float('inf'), float('-inf')):
            return None
        return round(f, 4) if isinstance(v, float) or not float(v).is_integer() else int(v)
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return _clean_value(v.item())
    except ImportError:
        pass
    if isinstance(v, (list, tuple)):
        return [_clean_value(x) for x in list(v)[:20]]
    raise ValueError('Lens facts must be scalars or short lists')


def lens_nodes(scene):
    """The compact node view a lens receives: id, kind, text, bounds (pixels)."""
    return [{'id': n['id'], 'kind': n['kind'], 'text': str(n.get('attributes', {}).get('text') or ''),
             'bounds': n.get('attributes', {}).get('bounds')} for n in scene['nodes']]


def run_lens(entry, rgb, scene, fn=None):
    """Run one program lens; returns (facts {node:{fact:value}}, new nodes, ms)."""
    fn = fn or load_program(entry)
    started = time.perf_counter()
    out = fn(rgb, lens_nodes(scene), dict(scene.get('viewport') or {}))
    ms = (time.perf_counter() - started) * 1000
    if out is None:
        out = {}
    if not isinstance(out, dict):
        raise ValueError('Lens must return a dict')
    emitted = set(entry['emits'])
    ids = {n['id'] for n in scene['nodes']}
    facts = {}
    raw_facts = out.get('facts', {k: v for k, v in out.items() if k != 'nodes'})
    for node_id, values in (raw_facts or {}).items():
        if str(node_id) not in ids or not isinstance(values, dict):
            continue
        clean = {k: _clean_value(v) for k, v in values.items() if k in emitted}
        if clean:
            facts[str(node_id)] = clean
    added = []
    for i, n in enumerate((out.get('nodes') or [])[:MAX_NEW_NODES]):
        if not isinstance(n, dict):
            continue
        b = n.get('bounds') or {}
        try:
            bounds = {k: round(float(b[k]), 1) for k in ('x', 'y', 'w', 'h')}
        except (KeyError, TypeError, ValueError):
            continue
        values = {k: _clean_value(v) for k, v in (n.get('facts') or {}).items() if k in emitted}
        added.append({'id': f"{entry['id']}:{i}", 'kind': str(n.get('kind') or 'region')[:32],
                      'attributes': {'text': str(n.get('text') or '')[:200], 'bounds': bounds},
                      'measurements': {'source': 'pixels', 'lens': entry['id'], **values},
                      'relations': {}, 'certainty': 'observed'})
    return facts, added, ms


def apply(scene, rgb=None, *, input_type='screenshot', strict=False):
    """Run every active program lens on a pixel scene; merge facts. Idempotent per lens set."""
    lens_rows = active(input_type)
    metrics = scene.setdefault('metrics', {})
    tag = identity(input_type) if _OVERRIDE is None else hashlib.sha256(
        json.dumps(sorted([e['id'], e['programSha256']] for e in lens_rows)).encode()).hexdigest()[:16]
    if not lens_rows or metrics.get('lensSet') == tag:
        return scene
    if rgb is None:
        import numpy as np
        from PIL import Image
        rgb = np.asarray(Image.open(scene['provenance']['screenshotPath']).convert('RGB'))
    by_id = {n['id']: n for n in scene['nodes']}
    timings, errors = {}, {}
    for e in lens_rows:
        try:
            facts, added, ms = run_lens(e, rgb, scene)
        except Exception as exc:  # a failing lens leaves its facts unknown, never fabricates them
            if strict:
                raise
            errors[e['id']] = type(exc).__name__ + ': ' + str(exc)[:200]
            continue
        timings[e['id']] = round(ms, 2)
        for node_id, values in facts.items():
            by_id[node_id]['measurements'].update(values)
        scene['nodes'].extend(a for a in added if a['id'] not in by_id)
        by_id.update({a['id']: a for a in added})
    metrics['lensMs'] = timings
    metrics['lensSet'] = tag
    if errors:
        metrics['lensErrors'] = errors
    return scene


def registry_cl(input_type=None):
    """The lens list in CL, for model looks and manuals."""
    lines = ['CL 1.1', 'L lenses v1 -- LAYA eyes: one observable per lens']
    for e in entries():
        if e['status'] != 'active' or (input_type and e['inputType'] != input_type):
            continue
        lines.append('E lens ' + json.dumps({'id': e['id'], 'input': e['inputType'],
                                             'emits': {k: v['cl'] for k, v in e['emits'].items()},
                                             'predicates': e.get('predicates', [])}, ensure_ascii=False, sort_keys=True))
    return '\n'.join(lines)
