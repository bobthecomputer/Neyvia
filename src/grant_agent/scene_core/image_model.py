"""LAYA inverse graphics adapter: sheet pixels -> CL observation -> CL shape program ->
native Blender mesh -> same-camera renders -> predicates.

The shared core owns judge, retention, rollback and episodes. This adapter only
observes and proposes the next program edit from a fixed ladder. No external mesh
generator, learned head, paid model or unrestricted program interpreter is used.
"""
import hashlib
import json
from pathlib import Path
import uuid

import numpy as np
from PIL import Image

from . import Adapter
from .gamedev import call
from ..neyvia_gamedev import service_for

MANUAL = Path(__file__).resolve().parents[3] / 'manuals/cl/laya-3d.cl'
# Each edit is one proposal; the core keeps it only if findings strictly shrink.
LADDER = [('visual-hull', {'hull': True, 'tolerance': 1, 'resolution': 64}),
          ('tight-silhouette', {'tolerance': 0}),
          ('finer-hull', {'resolution': 96}),
          ('smooth-surface', {'smooth': 1}),
          ('smoother-surface', {'smooth': 2}),
          ('project-texture', {'texture': True})]
GUARDS = {'outline_iou_mean': 'min', 'colour_error_mean': 'max'}


def vocabulary():
    return [r for line in MANUAL.read_text(encoding='utf-8').splitlines() if line.startswith('-- @predicate ')
            for r in [json.loads(line[14:])] if 'laya3d' in r.get('domains', [])]


def native(source):
    return {**source, 'domain': 'blender'}


def _session(source):
    owner = service_for(source['root'])
    session = next(r for r in owner.sessions()['sessions'] if r['sessionId'] == source['sessionId'])
    return owner, session


def program(observation, options):
    """CL shape program text from the observation and the current option set."""
    name = observation['id']
    used = [v for v in observation['views'] if not v.get('excluded')]
    if not options.get('hull'):
        # Naive baseline: the anchor view's box, with depth equal to its shorter side.
        operations = [('primitive', {'name': name, 'kind': 'box', 'location': [0, 0, 0],
                                     'scale': observation['baselineHalfExtents'], 'colour': observation['colour']})]
    else:
        operations = [('visual_hull', {'name': name, 'bounds': observation['bounds'], 'resolution': options['resolution'],
                                       'tolerance': options['tolerance'], 'quorum': options.get('quorum', 0), 'colour': observation['colour'],
                                       'views': [{'view': v['view'], 'camera': v['camera'], 'maskHex': v['maskHex']} for v in used]})]
        if options.get('smooth'):
            operations.append(('smooth', {'target': name, 'pitch': .75, 'factor': .5, 'iterations': 4 * int(options['smooth'])}))
        if options.get('mirror'):
            operations.append(('mirror', {'target': name, 'axis': 0}))
        if options.get('texture'):
            operations.append(('project_texture', {'target': name, 'views': [{'view': v['view'], 'path': v['texture'], 'camera': v['camera']} for v in used]}))
    return 'CL 1.1\nL shape-program v1 -- LAYA inverse graphics; fitted cameras are measurements, masks are observed data\n' + \
        '\n'.join('shape.' + op + '(' + json.dumps(args, separators=(',', ':')) + ')' for op, args in operations) + '\n'


def prepare(source):
    if '_observation' in source: return
    owner, session = _session(source)
    if source.get('modelPath'):
        path = owner.safe_path(source['modelPath'], project=session['projectPath'])
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved.get('schema') != 'neyvia.shape-model.v2': raise ValueError('Expected a persisted LAYA shape model')
        for view in saved['observation']['views']:
            if hashlib.sha256(Path(view['path']).read_bytes()).hexdigest() != view['sha256']:
                raise ValueError('Persisted source view changed')
        source.update(_directory=str(path.parent), _observation=saved['observation'], _options=saved['options'],
                      _program=saved['program'], _ladder=saved['ladder'])
        if source.get('_allowBuild'): call(native(source), 'shape_program', {'program': source['_program']})
        return
    if not source.get('_allowBuild'):
        raise ValueError('Build with scene.improve(domain="laya3d") first; transcribe observes a live modelPath without rebuilding')
    from .image_sheets import see_sheet
    sheet = owner.safe_path(source['sheet'], project=session['projectPath'])
    directory = owner.safe_path('laya3d/' + source['spec']['object'] + '-' + uuid.uuid4().hex[:8], project=session['projectPath'])
    source['_observation'] = see_sheet(sheet, directory / 'eyes', source['spec'])
    source.update(_directory=str(directory), _options={}, _ladder=0)
    source['_program'] = program(source['_observation'], source['_options'])
    call(native(source), 'shape_program', {'program': source['_program']})
    (directory / 'initial.cl').write_text(source['_program'], encoding='utf-8')
    persist(source)


def persist(source):
    path = Path(source['_directory']) / 'model.json'
    path.write_text(json.dumps({'schema': 'neyvia.shape-model.v2', 'program': source['_program'], 'options': source['_options'],
                                'ladder': source['_ladder'], 'observation': source['_observation']}, indent=1), encoding='utf-8')
    return str(path)


def _measure(expected, actual_path):
    target = Image.open(expected['path']).convert('RGBA'); rendered = Image.open(actual_path).convert('RGBA')
    t, r = np.asarray(target).astype(float), np.asarray(rendered).astype(float)
    a, b = t[:, :, 3] > 128, r[:, :, 3] > 128
    both = a & b
    # Regional colour: 8-pixel blocks, so drifted AI detail is not scored as wrong colour.
    def blocks(rgb, mask):
        weight = mask.reshape(16, 8, 16, 8).sum(axis=(1, 3))
        total = (rgb * mask[..., None]).reshape(16, 8, 16, 8, 3).sum(axis=(1, 3))
        return total / np.maximum(weight, 1)[..., None], weight >= 16
    ct, wt = blocks(t[:, :, :3], a); cr, wr = blocks(r[:, :, :3], b)
    shared = wt & wr
    colour = float(np.abs(ct - cr).mean(axis=2)[shared].mean() / 255) if shared.any() else 1.
    from .image_parts import components
    parts = len(components(b)) if b.any() else 0
    def extent(mask):
        yy, xx = np.nonzero(mask)
        return np.array([xx.max() - xx.min() + 1, yy.max() - yy.min() + 1]) if mask.any() else np.zeros(2)
    # Extent error relative to the object's size: a one-pixel slip on a thin prop is ~1%, not 15%.
    want, got = extent(a), extent(b)
    proportion = float(np.abs(want - got).max() / max(want.max(), 1))
    return {'outlineIoU': round(float(both.sum() / max((a | b).sum(), 1)), 6),
            'partMatch': round(min(expected['parts'], parts) / max(expected['parts'], parts, 1), 6),
            'proportionError': round(proportion, 6),
            'colourError': round(colour, 6)}


def transcribe(source):
    prepare(source)
    views = source['_observation']['views']; directory = Path(source['_directory'])
    digest = hashlib.sha256(source['_program'].encode()).hexdigest()
    # Content-addressed renders: the same live program must yield the identical Scene.
    rendered = call(native(source), 'canonical', {'path': str(directory / 'renders' / digest[:16]), 'collection': 'LAYA shape program',
                                                  'framing': {'center': [0, 0, 0], 'size': 2.56}, 'views': [v['view'] for v in views],
                                                  'sourceColour': True, 'replace': True, 'allowBlank': True,
                                                  'cameras': {v['view']: v['camera'] for v in views}})
    if rendered['programSha256'] != digest:
        raise ValueError('This live session contains another model; resume the modelPath with scene.improve')
    nodes = []
    for expected, actual in zip(views, rendered['views']):
        nodes.append({'id': expected['view'], 'kind': 'reference-view' if expected.get('excluded') else 'view-measurement',
                      'certainty': 'observed', 'attributes': {'role': expected['role'], 'cell': expected['cell']['index'],
                                                              'sourceParts': expected['parts']},
                      'measurements': _measure(expected, actual['path']), 'relations': {}})
    judged = [n['measurements'] for n in nodes if n['kind'] == 'view-measurement']
    # Predicates read the model node: per-view numbers are evidence; bands over the
    # worst and mean view make a continuous improvement a strict finding reduction.
    nodes.append({'id': 'model', 'kind': 'shape-model', 'certainty': 'observed',
                  'attributes': {'views': len(judged), 'options': source['_options']}, 'relations': {},
                  'measurements': {'outlineIoUMin': min(m['outlineIoU'] for m in judged),
                                   'outlineIoUMean': round(float(np.mean([m['outlineIoU'] for m in judged])), 6),
                                   'colourErrorMean': round(float(np.mean([m['colourError'] for m in judged])), 6),
                                   'extentErrorMean': round(float(np.mean([m['proportionError'] for m in judged])), 6),
                                   'partMatchMin': min(m['partMatch'] for m in judged)}})
    metrics = {'outline_iou_min': min(m['outlineIoU'] for m in judged),
               'outline_iou_mean': round(float(np.mean([m['outlineIoU'] for m in judged])), 6),
               'colour_error_mean': round(float(np.mean([m['colourError'] for m in judged])), 6),
               'colour_error_max': max(m['colourError'] for m in judged)}
    return {'schema': 'neyvia.scene.v1', 'domain': 'laya3d', 'surface': 'native-render', 'nodes': nodes, 'metrics': metrics,
            'truncated': False,
            'provenance': {'sourceSha256': source['_observation']['sourceSha256'], 'programSha256': digest,
                           'renderPixelSha256': [hashlib.sha256(np.asarray(Image.open(v['path']).convert('RGBA')).tobytes()).hexdigest() for v in rendered['views']], 'options': source['_options'],
                           'projection': source['_observation']['projection']},
            'unknown': ['Unseen surfaces and concavities are not recoverable from silhouettes alone.']}


def checkpoint(source):
    return {'program': source['_program'], 'options': dict(source['_options'])}


def restore(source, saved):
    call(native(source), 'shape_program', {'program': saved['program']})
    source['_program'], source['_options'] = saved['program'], saved['options']
    persist(source)


def next_edit(source):
    ladder = source['_ladder']
    while ladder < len(LADDER):
        name, change = LADDER[ladder]
        return ladder, name, change
    return None


def refit(source, finding):
    edit = next_edit(source)
    if edit is None: raise ValueError('The program edit ladder is exhausted')
    index, name, change = edit
    source['_ladder'] = index + 1  # Advances even if the core reverts this edit.
    source['_options'] = {**source['_options'], **change}
    source['_program'] = program(source['_observation'], source['_options'])
    (Path(source['_directory']) / f'candidate-{index}-{name}.cl').write_text(source['_program'], encoding='utf-8')
    result = call(native(source), 'shape_program', {'program': source['_program']})
    persist(source)
    return {'edit': name, **result}


def make_adapter():
    return Adapter(transcribe=transcribe, vocabulary=vocabulary, fixes={'shape.refit': refit},
                   checkpoint=checkpoint, restore=restore)
