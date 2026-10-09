"""The same evolving-vision mechanism on 3D renders (plan 24 -> plans 23/26).

Domain ``render3d``: one rendered view of a 3D subject standing next to a 1.8 m reference
mannequin (scripts/vision_blender_practice.py). The baseline eye is one built-in lens,
``render-silhouette`` (object/reference masks by colour: coverage and boxes). The three
fault predicates live in manuals/cl/laya-vision.cl (``-- @render-predicate``); two of them
start with no eyes at all (``awaitsLens``) and get their conditions only from lenses that
model looks asked for and Luna wrote, kept on held-out subjects.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
MANUAL = REPO / 'manuals/cl/laya-vision.cl'
DOMAIN = 'render3d'
TYPES = ('flipped-normals', 'floaters', 'wrong-scale')
LOOK_DOMAIN = 'render-look'


def masks(rgb):
    """Built-in lens render-silhouette: subject (orange) and reference (blue-grey) by hue."""
    f = rgb.astype(np.float32)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    mx, mn = f.max(axis=2), f.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1)
    subject = (r > g) & (g > b) & (sat > 0.35) & (mx > 40)
    reference = (b > r + 12) & (b > g) & (sat > 0.18) & (mx > 50)
    return subject, reference


def _box(mask):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return {'x': float(xs.min()), 'y': float(ys.min()), 'w': float(xs.max() - xs.min() + 1), 'h': float(ys.max() - ys.min() + 1)}


def transcribe_render(source):
    from PIL import Image
    from .scene_core.lenses import apply
    path = Path(source['image'])
    raw = path.read_bytes()
    rgb = np.asarray(Image.open(path).convert('RGB'))
    h, w = rgb.shape[:2]
    subject, reference = masks(rgb)
    sbox, rbox = _box(subject), _box(reference)
    nodes = [{'id': 'object', 'kind': 'object', 'attributes': {'text': '', 'bounds': sbox},
              'measurements': {'source': 'pixels', 'coverage': round(float(subject.mean()), 5),
                               'visible': bool(subject.any())}, 'relations': {}, 'certainty': 'observed'},
             {'id': 'reference', 'kind': 'reference', 'attributes': {'text': '', 'bounds': rbox},
              'measurements': {'source': 'pixels', 'coverage': round(float(reference.mean()), 5)}, 'relations': {},
              'certainty': 'observed'}]
    scene = {'surface': source.get('subject', path.stem), 'layer': 'render', 'nodes': nodes,
             'viewport': {'width': w, 'height': h, 'view': source.get('view'), 'expectedHeightM': source.get('expectedHeightM'),
                          'referenceHeightM': source.get('referenceHeightM', 1.8)},
             'measured': 'approximate', 'truncated': False, 'modelTranscription': False,
             'provenance': {'screenshotPath': str(path.resolve()), 'renderSha256': hashlib.sha256(raw).hexdigest(),
                            'lens': 'render-silhouette'}, 'metrics': {}}
    apply(scene, rgb, input_type='render')
    return scene


def _rules():
    rules = []
    for line in MANUAL.read_text(encoding='utf-8').splitlines():
        if line.startswith('-- @render-predicate '):
            r = json.loads(line[len('-- @render-predicate '):])
            rules.append({'id': r['id'], 'condition': r['condition'], 'severity': 'error', 'means': r.get('means', ''),
                          'awaitsLens': bool(r.get('awaitsLens')), 'evidence': ['attributes.bounds', 'measurements'],
                          'fix': {'action': 'render.review-fix', 'arguments': {'pattern': r['id'], 'instruction': r.get('fix', '')}}})
    return rules


def vocabulary():
    from .scene_core.lenses import with_branches
    return with_branches(_rules(), 'render')


def ensure_registered():
    from .scene_core import Adapter, register, _ADAPTERS
    if DOMAIN not in _ADAPTERS:
        register(DOMAIN, Adapter(transcribe=transcribe_render, vocabulary=vocabulary))


def glance(source, *, calibration=None, level=0.95):
    from .scene_core import transcribe, judge, admit_approximate
    ensure_registered()
    scene = transcribe(DOMAIN, source)
    rules = vocabulary()
    result = judge(scene, rules, record=False, calibration=calibration or {}, level=level)
    result.update(admit_approximate(result['findings'], rules, calibration or {}, level))
    fired = sorted({f['predicate'] for f in result['findings']})
    return {**result, 'fired': fired, 'broken': bool(fired) if result['admitted'] else None, 'scene': scene}


# --- model look spec for renders ---------------------------------------------

DEFINITIONS = {
    'flipped-normals': 'Some faces of the subject point inward. The renderer culls back faces (as a game engine does), so '
                       'those faces vanish: holes, missing patches or see-through parts in a surface that should be closed.',
    'floaters': 'Small detached pieces of the subject float apart from its body (stray cubes or blobs not touching it).',
    'wrong-scale': 'The subject is the wrong size for what it is: compare it with the 1.8 m blue mannequin and its declared '
                   'real-world height (much too large or far too small).',
}


def _question(verdict):
    adm = verdict.get('admission') or {}
    fired = adm.get('fired') or verdict.get('fired') or []
    if fired:
        return 'Render lenses raised ' + ', '.join(fired) + ' below calibrated precision 0.95. Confirm or reject; label every type.'
    return 'Render lenses cannot certify this render as clean. Is any fault visible? Label every type.'


def _prompt(scene, verdict, question, lens_cl):
    view = scene.get('viewport') or {}
    nodes = [{'id': n['id'], 'kind': n['kind'], 'box': n['attributes'].get('bounds'),
              'facts': {k: v for k, v in n['measurements'].items() if k not in ('source',)}} for n in scene['nodes']]
    return '\n'.join([
        'You are LAYA\'s one model look at a render of a 3D asset. The orange object is the subject; the blue-grey figure is a '
        f'1.8 m reference mannequin; the floor is grey. The subject should be about {view.get("expectedHeightM")} m tall. '
        f'View: {view.get("view")} ("front" shows the stage with the mannequin; "close*" frames the subject at its declared size). '
        'Back faces are culled, as in a game engine.',
        '', 'Fault types (label 1 only if visible):', *[f'- {t}: {d}' for t, d in DEFINITIONS.items()],
        '', 'Lenses (LAYA\'s current eyes; cite ids in "seen"/"defects.lens"):', lens_cl,
        '', f'Render {view.get("width")}x{view.get("height")} px. Scene nodes:', json.dumps(nodes),
        '', 'Question: ' + question,
        '', 'Answer rules: verdict broken if any type is 1; types 0/1 for every type; defects with a short "where" '
        '(e.g. "left of the subject, in the air"), its box in render pixels, the lens id that measures it or "none" plus a '
        'kebab-case observable name; seen = lens facts you confirm or refute; missing = observables no lens covers that would '
        'let LAYA decide without you: kebab-case name, type, description, and how pixels could measure it.',
    ])


RENDER_CONTRACT = '''Write ONE Python lens program (a small measuring function) for LAYA's 3D render eyes.

Contract:
- Define `measure(rgb, nodes, viewport)`; nothing runs at import time except constants/imports.
  * rgb: numpy uint8 array HxWx3 of a Workbench render (640x480). Background dark navy (about 18,20,28 near the top),
    floor grey (about 107,107,107 lit), subject ORANGE (r>g>b, saturated), reference mannequin BLUE-GREY (b>r).
    Back faces are culled: inward-facing faces vanish and show floor/background through the subject.
  * nodes: [{"id":"object","kind":"object","bounds":{x,y,w,h}|None}, {"id":"reference","kind":"reference","bounds":...}]
    (bounds from colour masks: subject = r>g>b & saturation>0.35; reference = b>r+12).
  * viewport: {"width","height","view":"front"|"close"|"close-high","expectedHeightM","referenceHeightM":1.8}.
    In "front" both subject and reference stand on the same floor at similar depth; "close*" frames the subject's
    DECLARED height so a correct subject fills roughly 25-60% of the frame height.
- Return {"facts": {"object": {fact: value}}}. Facts are bool/number/short list. Fact names camelCase
  ([a-z][A-Za-z0-9]{1,47}) and listed in "emits".
- Allowed imports: numpy, math, scipy.ndimage, collections, itertools, functools, statistics, re. No files, os, sys,
  eval/exec, getattr, dunder names, classes, attributes starting with "_".
- Must run in < 60 ms. Vectorise with numpy/scipy.ndimage.
- Measure only. The predicate branch (JSON data) decides, e.g.
  {"all":[{"field":"kind","op":"eq","value":"object"},{"field":"measurements.<fact>","op":"gt","value":0}]}
  ops: eq lt le gt ge nonempty matches; combinators all/any; fields "kind", "measurements.<fact>".
- Prefer precision: thin legs, handles, gaps between parts and shading are NOT faults.
'''

SPEC = {'domain': 'render3d', 'types': TYPES, 'lensInput': 'render', 'prompt': _prompt, 'question': _question,
        'contract': RENDER_CONTRACT}
