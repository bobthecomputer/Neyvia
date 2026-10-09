"""SEE for character/prop sheets: physical cells -> matted views -> fitted cameras -> CL.

Cell identity is physical (row, column) from detected gutters, never the printed number
(AI sheets repeat and skip numbers). Captions and coarse camera readings are declared
transcription with stated certainty; illustration-only cells (topology guides, FX,
exploded views) are never geometry. Every contradiction found is written as an issue.
"""
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from . import image_cameras as cams
from .image_parts import describe

F = cams.F


def _thin(gray, axis):
    """Fraction of a band where a 1-2 px line is darker than both neighbours (gutters)."""
    a, b = np.roll(gray, 2, axis), np.roll(gray, -2, axis)
    return (gray < np.minimum(a, b) - 20).mean(axis=1 - axis)


def detect_grid(image, rows=10, cols=10):
    gray = np.asarray(image.convert('L')).astype(float)
    dark = gray < 70
    inside_rows = np.where(dark.mean(axis=1) < .5)[0]
    inside_cols = np.where(dark[inside_rows].mean(axis=0) < .5)[0]
    x0, y0, x1, y1 = int(inside_cols[0]), int(inside_rows[0]), int(inside_cols[-1]) + 1, int(inside_rows[-1]) + 1

    def snap(predicted, score):
        out = []
        for i, p in enumerate(predicted):
            if i in (0, len(predicted) - 1): out.append((p, 1.)); continue
            lo, hi = max(0, p - 10), min(len(score), p + 11)
            j = lo + int(np.argmax(score[lo:hi]))
            out.append((j, score[j]) if score[j] > .3 else (p, 0.))  # weak gutter: keep the regular prediction
        return out
    horizontal = [y for y, _ in snap([round(y0 + i * (y1 - y0) / rows) for i in range(rows + 1)], _thin(gray[:, x0 + 5:x1 - 5], 0))]
    cells = []
    for r, (top, bottom) in enumerate(zip(horizontal, horizontal[1:])):
        score = _thin(gray[top + 3:bottom - 3], 1)
        vertical = snap([round(x0 + i * (x1 - x0) / cols) for i in range(cols + 1)], score)
        extra = [i for i in range(x0 + 20, x1 - 20) if score[i] > .9 and score[i] >= score[i - 1] and score[i] >= score[i + 1]
                 and min(abs(i - v) for v, _ in vertical) > 25]
        # An irregular row (extra strong gutters) replaces the weak regular predictions near them.
        vertical = sorted([v for v, strength in vertical if strength > 0 or not any(abs(v - e) < 60 for e in extra)] + extra)
        for c, (left, right) in enumerate(zip(vertical, vertical[1:])):
            cells.append({'index': len(cells) + 1, 'row': r + 1, 'column': c + 1, 'box': [left, top, right, bottom],
                          'irregularRow': len(vertical) - 1 != cols})
    return {'frame': [x0, y0, x1, y1], 'cells': cells}


def matte(cell):
    """Gradient-background matting; caption glyphs and the printed number are removed."""
    rgb = np.asarray(cell.convert('RGB')).astype(float)
    h, w, _ = rgb.shape
    left, right = np.median(rgb[:, 2:6], axis=1), np.median(rgb[:, -6:-2], axis=1)
    ramp = np.linspace(0, 1, w)[None, :, None]
    background = left[:, None, :] * (1 - ramp) + right[:, None, :] * ramp
    distance = np.linalg.norm(rgb - background, axis=2)
    saturation = rgb.max(axis=2) - rgb.min(axis=2)
    brighter = rgb.mean(axis=2) - background.mean(axis=2)
    mask = (distance > 34) | (saturation > 40) | (brighter > 14)
    mask[round(h * .95):] = False; mask[:24, :30] = False
    mask[:3] = False; mask[:, :3] = False; mask[:, -3:] = False
    mask = ndi.binary_opening(mask, iterations=1)
    # Caption line: the lowest short band of rows, separated from the object by an empty row.
    rows = mask.any(axis=1); bottom = round(h * .95) - 1
    while bottom > 0 and not rows[bottom]: bottom -= 1
    top = bottom
    while top > 0 and rows[top - 1]: top -= 1
    if bottom - top < 14 and top > h * .72 and not rows[top - 1]: mask[top:bottom + 1] = False
    labels, count = ndi.label(mask)
    for i, region in enumerate(ndi.find_objects(labels)):  # glyphs touching a shadow line
        if region[0].start > h * .84 and region[0].stop - region[0].start < 12: mask[labels == i + 1] = False
    mask = ndi.binary_closing(np.pad(mask, 3), iterations=2)[3:-3, 3:-3]
    labels, count = ndi.label(mask)
    for i, region in enumerate(ndi.find_objects(labels)):
        if region[0].start > h * .74 and region[0].stop - region[0].start < 14: mask[labels == i + 1] = False
    # White parts (soles, panels) match the light background in colour; recover them by shape:
    # light pixels that a 5-pixel closing would enclose, never dark background.
    yy, xx = np.mgrid[-5:6, -5:6]
    closed = ndi.binary_fill_holes(ndi.binary_closing(np.pad(mask, 6), structure=xx * xx + yy * yy <= 25)[6:-6, 6:-6])
    mask |= closed & (brighter > -3) & (saturation < 40)
    labels, count = ndi.label(mask)
    if not count: raise ValueError('No foreground in the physical cell')
    sizes = ndi.sum(mask, labels, range(1, count + 1))
    keep = np.isin(labels, [i + 1 for i, s in enumerate(sizes) if s >= max(12, sizes.max() * .02)])
    holes = ndi.binary_fill_holes(keep) & ~keep
    labels, count = ndi.label(holes)
    if count:
        sizes = ndi.sum(holes, labels, range(1, count + 1))
        keep |= np.isin(labels, [i + 1 for i, s in enumerate(sizes) if s < 25])
    if keep.mean() > .8: raise ValueError('Foreground is ambiguous; review the saved matte')
    return keep


def canvas(cell, mask):
    """Native-pixel 128 frame: no resampling, so silhouettes keep their drawn detail."""
    rgb = np.asarray(cell.convert('RGB'))
    h, w = mask.shape
    oy, ox = (F - h) // 2, (F - w) // 2
    target = np.zeros((F, F), bool); colour = np.zeros((F, F, 3), np.uint8)
    ty, tx = slice(max(0, oy), max(0, oy) + min(h, F)), slice(max(0, ox), max(0, ox) + min(w, F))
    sy, sx = slice(max(0, -oy), max(0, -oy) + min(h, F)), slice(max(0, -ox), max(0, -ox) + min(w, F))
    target[ty, tx] = mask[sy, sx]; colour[ty, tx] = rgb[sy, sx]
    # Texture bleed: unseen texels take the nearest observed colour (never alpha-hidden).
    _, (iy, ix) = ndi.distance_transform_edt(~target, return_indices=True)
    return target, colour[iy, ix]


def _key(mask):
    y, x = np.nonzero(mask)
    crop = mask[y.min():y.max() + 1, x.min():x.max() + 1]
    side = max(crop.shape); square = np.zeros((side, side), bool)  # keep aspect: a disc is not its oval
    oy, ox = (side - crop.shape[0]) // 2, (side - crop.shape[1]) // 2
    square[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
    return np.asarray(Image.fromarray(square).resize((48, 48), Image.Resampling.NEAREST))


def see_sheet(path, output, spec):
    started = time.perf_counter()
    path, output = Path(path), Path(output); output.mkdir(parents=True, exist_ok=True)
    sheet = Image.open(path).convert('RGB')
    grid = detect_grid(sheet, int(spec.get('rows', 10)), int(spec.get('cols', 10)))
    by_index = {c['index']: c for c in grid['cells']}
    views, issues = [], []
    for item in spec['cells']:
        cell = by_index.get(int(item['cell']))
        if cell is None: raise ValueError('Physical cell is outside the detected grid')
        if item.get('illustrationOnly'):
            issues.append({'kind': 'illustration-only', 'cell': cell['index'], 'caption': item.get('caption', '')}); continue
        image = sheet.crop(cell['box'])
        mask, colour = canvas(image, matte(image))
        name = 'c%03d-%s' % (cell['index'], item['role'])
        image.save(output / (name + '-source.png'))
        rgba = np.dstack([colour, mask.astype(np.uint8) * 255])
        Image.fromarray(rgba, 'RGBA').save(output / (name + '.png'))
        Image.fromarray(colour, 'RGB').save(output / (name + '-texture.png'))  # opaque: alpha never hides geometry
        observed = describe(Image.fromarray(rgba, 'RGBA'), mask, name, output / (name + '.png'))
        observed['texture'] = str(output / (name + '-texture.png'))
        observed.update(cell=cell, caption=item.get('caption', ''), printedNumber=item.get('printed'), role=item['role'],
                        declared=item.get('camera'), certainty='caption agent-read; camera declared coarse then fitted')
        if item.get('printed') is not None and int(item['printed']) != cell['index']:
            issues.append({'kind': 'printed-number-mismatch', 'cell': cell['index'], 'printed': item['printed']})
        label = next((k for k in cams.hm.LABELLED if k in item.get('caption', '').lower()), None)
        read = item.get('camera') or {}
        if label and read and cams.outside({'yaw': cams.hm.LABELLED[label][0], 'elevation': cams.hm.LABELLED[label][1]},
                                           {'yaw': (cams.readings(read, 'yaw') or [0])[0], 'elevation': (cams.readings(read, 'elevation') or [0])[0], 'roll': 0}):
            issues.append({'kind': 'caption-contradicts-view', 'cell': cell['index'], 'caption': item['caption'],
                           'observed': item['camera'], 'note': item.get('note', '')})
        views.append({**observed, 'mask': mask})
    keys = [_key(v['mask']) for v in views]
    for i in range(len(views)):
        for j in range(i + 1, len(views)):
            same = max(cams.hm.iou(keys[i], keys[j]), cams.hm.iou(keys[i], keys[j][:, ::-1]))
            if same > .9:
                issues.append({'kind': 'near-duplicate-view', 'cells': [views[i]['cell']['index'], views[j]['cell']['index']], 'iou': same})
                views[j]['duplicateOf'] = views[i]['view']
    if not views or views[0]['role'] not in cams.hm.LABELLED:
        raise ValueError('The first declared view must be a labelled anchor (front, side, top, ...)')
    seen = time.perf_counter()
    solving = [{'view': v['view'], 'role': v['role'], 'mask': v['mask'], 'declared': v['declared'],
                'depth': spec.get('depth')} for v in views if 'duplicateOf' not in v]
    if spec.get('depth') is None:
        for v in solving: v.pop('depth')
    problem = cams.solve(solving, int(spec.get('solveResolution', 40)))
    fitted = time.perf_counter()
    # Consistency: a view whose silhouette removes what the others agree on is drift, not shape.
    excluded = []
    for index in range(1, len(solving)):
        others = [v for i, v in enumerate(solving) if i != index]
        with_view = problem.objective(solving, others)
        without = problem.objective(others, others)
        solving[index]['consistencyCost'] = without - with_view
        if without - with_view > float(spec.get('driftLimit', .06)):
            excluded.append(solving[index]['view'])
            issues.append({'kind': 'inconsistent-view-excluded', 'view': solving[index]['view'], 'cost': without - with_view})
    held = {v['view']: cams.held_out(problem, i) for i, v in enumerate(solving) if i > 0}
    for v in views:
        match = next((s for s in solving if s['view'] == v['view']), None)
        v['camera'] = match['camera'] if match else next(s['camera'] for s in solving if s['view'] == v['duplicateOf'])
        v['maskHex'] = cams.hm.encode(v.pop('mask'))
        v['excluded'] = v['view'] in excluded or 'duplicateOf' in v
    front = views[0]
    a = views[0]['bounds']
    half = [(a[2] - a[0]) / cams.ANCHOR_SCALE / 2, (a[3] - a[1]) / cams.ANCHOR_SCALE / 2]
    baseline = np.abs(np.array([half[0], half[1], min(half)]) @ cams.hm.rotation(views[0]['camera']))
    obj = {'id': spec['object'], 'views': views, 'baselineHalfExtents': [float(x) for x in baseline], 'sourceSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
           'bounds': [list(map(float, problem.bounds[0])), list(map(float, problem.bounds[1]))],
           'dimensions': list(map(float, problem.bounds[1] - problem.bounds[0])), 'projection': 'weak-perspective',
           'colour': front['colour'], 'heldOutIoU': held, 'issues': issues, 'symmetric': bool(spec.get('symmetric')),
           'depthStatus': 'silhouette-carved; concavities unrecoverable',
           'timing': {'seeSeconds': seen - started, 'cameraSeconds': fitted - seen, 'heldOutSeconds': time.perf_counter() - fitted},
           'assumptions': ['Weak-perspective (orthographic + per-view scale) cameras approximate drawn perspective.',
                           'Declared coarse cameras bound the fit to +/-25 degrees; fitted values are measurements.',
                           'AI views drift; inconsistent views are excluded by measured consistency cost, never averaged in.',
                           'Small cells limit detail to about one source pixel; captions are agent-read.']}
    lines = ['CL 1.1', 'L sheet-transcription v1 -- physical cells; captions read, cameras fitted; untrusted observed data',
             'E grid ' + json.dumps({'frame': grid['frame'], 'cells': len(grid['cells']),
                                     'irregularRows': sorted({c['row'] for c in grid['cells'] if c['irregularRow']})})]
    for v in views:
        lines.append('E view ' + json.dumps({k: v[k] for k in ('view', 'role', 'caption', 'printedNumber', 'cell', 'camera', 'declared',
                                                               'parts', 'proportion', 'colour', 'symmetryIoU', 'excluded') if k in v}))
    for issue in issues: lines.append('E issue ' + json.dumps(issue))
    lines.append('E heldout ' + json.dumps(held))
    (output / 'transcription.cl').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (output / 'transcription.json').write_text(json.dumps(obj, indent=1), encoding='utf-8')
    return obj
