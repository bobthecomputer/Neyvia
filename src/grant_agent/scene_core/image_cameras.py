"""LAYA eyes for concept-art sheets: fit one weak-perspective camera per view.

Silhouette consistency is the only signal: each view's camera is refined so the
visual hull of all views reprojects onto every mask. A declared coarse camera
(the transcription's reading of "3/4 front-left, slightly above") bounds the search
to +/-25 degrees, because a few silhouettes of a thin prop admit degenerate
solutions (a tilted slab explains any oblique view). No mesh is generated here;
the fitted cameras are written into the CL shape program that Blender executes.
"""
import importlib.util
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

_SPEC = importlib.util.spec_from_file_location(
    'laya_hull_math', Path(__file__).resolve().parents[3] / 'scripts/gamedev/blender/neyvia_bridge/hull_math.py')
hm = importlib.util.module_from_spec(_SPEC); _SPEC.loader.exec_module(hm)
F = hm.FRAME
ANCHOR_SCALE = 50.  # pixels per world unit: the 128-pixel frame spans 2.56 units
UPRIGHT = .05       # weight of the axis-aligned compactness prior
BOUND = 25.
ANCHOR_WEIGHT = float(__import__('os').environ.get('LAYA_ANCHOR_WEIGHT', '1'))         # degrees a fitted camera may move from its declared reading


def readings(declared, key):
    """A declared reading may list alternatives (e.g. muzzle left or right); fits stay near one."""
    value = (declared or {}).get(key)
    return None if value is None else [float(v) for v in (value if isinstance(value, (list, tuple)) else [value])]


def outside(declared, camera):
    bound = float((declared or {}).get('within', BOUND))
    for key in ('yaw', 'elevation', 'roll'):
        options = readings(declared, key)
        if options and min(abs((camera[key] - o + 180) % 360 - 180) for o in options) > bound: return True
    return False


def surface(occupied):
    pad = np.pad(occupied, 1)
    inner = pad[1:-1, 1:-1, 1:-1].copy()
    for axis in range(3):
        for shift in (-1, 1):
            inner &= np.roll(pad, shift, axis)[1:-1, 1:-1, 1:-1]
    return occupied & ~inner


def render(points, camera, step, size=F, factor=1.):
    """Silhouette of voxel cubes: centres splatted, then grown by half the voxel footprint."""
    scaled = {**camera, 'scale': camera['scale'] * factor, 'offset': [o * factor for o in camera.get('offset', (0, 0))]}
    u, v, _ = hm.project(points, scaled)
    u, v = u - F / 2 + size / 2, v - F / 2 + size / 2
    x, y = np.floor(u).astype(int), np.floor(v).astype(int)
    ok = (x >= 0) & (x < size) & (y >= 0) & (y < size)
    image = np.zeros((size, size), bool); image[y[ok], x[ok]] = True
    radius = step * scaled['scale'] * .5
    if radius >= .75:
        r = int(np.ceil(radius)); yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        image = ndi.binary_dilation(image, structure=(xx * xx + yy * yy) <= radius * radius + .25)
    return ndi.binary_closing(np.pad(image, 2), iterations=1)[2:-2, 2:-2]


def moments(mask):
    y, x = np.nonzero(mask); centre = np.array([x.mean(), y.mean()])
    w, v = np.linalg.eigh(np.cov(np.stack([x - centre[0], y - centre[1]])))
    return centre, np.degrees(np.arctan2(-v[1, 1], v[0, 1])), np.sqrt(np.maximum(w[::-1], 1e-9))


def place(points, camera, centre):
    u, v, _ = hm.project(points, {**camera, 'offset': [0, 0]})
    return {**camera, 'offset': [float(centre[0] - u.mean()), float(centre[1] - v.mean())]}


class Problem:
    def __init__(self, views, resolution=40):
        self.views = views
        anchor = views[0]
        y, x = np.nonzero(anchor['mask'])
        yaw, elevation = hm.LABELLED[anchor['role']] if anchor['role'] in hm.LABELLED else (0, 0)
        declared = anchor.get('declared') or {}
        anchor['camera'] = {'yaw': (readings(declared, 'yaw') or [yaw])[0], 'elevation': (readings(declared, 'elevation') or [elevation])[0],
                            'roll': (readings(declared, 'roll') or [0.])[0], 'scale': ANCHOR_SCALE,
                            'offset': [(x.max() + x.min() + 1) / 2 - F / 2, (y.max() + y.min() + 1) / 2 - F / 2]}
        half = np.array([(x.max() - x.min() + 1), (y.max() - y.min() + 1)]) / ANCHOR_SCALE / 2
        depth = float(anchor.get('depth', half.max()))
        corners = np.array([[sx * half[0], sy * half[1], sz * depth] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])
        # The anchor's image-plane box swept through its depth, expressed in world axes.
        world = corners @ hm.rotation(anchor['camera'])
        self.bounds = (world.min(0), world.max(0))
        self.points, self.shape, self.step = hm.grid(self.bounds, resolution)
        for view in views:
            view['small'] = view['mask'].reshape(F // 2, 2, F // 2, 2).max(axis=(1, 3))

    def hull(self, active, tolerance=1):
        return hm.carve(self.points, [{'mask': v['mask'], 'camera': v['camera']} for v in active], tolerance)

    def objective(self, active, scored=None):
        occupied = self.hull(active)
        if not occupied.any(): return 0.
        points = self.points[surface(occupied.reshape(self.shape)).ravel()]
        scores = [hm.iou(render(points, v['camera'], self.step, F // 2, .5), v['small']) for v in (scored or active)]
        weights = [ANCHOR_WEIGHT if v is self.views[0] else 1. for v in (scored or active)]  # the anchor is the trusted reading
        fit = float(np.average(scores, weights=weights))
        index = np.argwhere(occupied.reshape(self.shape))
        return fit + UPRIGHT * float(occupied.sum() / np.prod(index.max(0) - index.min(0) + 1))

    def descend(self, active, view, scales=(10, 5, 2.5), scored=None):
        best = self.objective(active, scored)
        declared = view.get('declared') or {}
        for delta in scales:
            improved = True
            while improved:
                improved = False
                for key, d in (('yaw', delta), ('yaw', -delta), ('elevation', delta), ('elevation', -delta),
                               ('roll', delta), ('roll', -delta), ('scale', .005 * delta), ('scale', -.005 * delta),
                               ('du', delta / 2.5), ('du', -delta / 2.5), ('dv', delta / 2.5), ('dv', -delta / 2.5)):
                    old = view['camera']; trial = {**old, 'offset': list(old['offset'])}
                    if key == 'scale': trial['scale'] *= 1 + d
                    elif key in ('du', 'dv'): trial['offset'][key == 'dv'] += d
                    else: trial[key] += d
                    if outside(declared, trial): continue
                    view['camera'] = trial
                    score = self.objective(active, scored)
                    if score > best + 1e-4: best = score; improved = True
                    else: view['camera'] = old
        return best

    def starts(self, view, active):
        declared = view.get('declared') or {}
        if readings(declared, 'yaw') is not None:
            seeds = [(y + dy, e + de) for y in readings(declared, 'yaw') for e in (readings(declared, 'elevation') or [0.])
                     for dy in (-15, 0, 15) for de in (-10, 0, 10)]
        else:
            seeds = ([hm.LABELLED[view['role']]] if view['role'] in hm.LABELLED else []) + \
                    [(y, e) for y in range(0, 360, 45) for e in (0, 25, 50)]
        points = self.points[self.hull(active)]
        centre, angle, spread = moments(view['mask'])
        for yaw, elevation in seeds:
            base = {'yaw': float(yaw), 'elevation': float(elevation), 'roll': 0., 'scale': 1.}
            u, v, _ = hm.project(points, base)
            w, vec = np.linalg.eigh(np.cov(np.stack([u, -v])))
            axis = np.degrees(np.arctan2(vec[1, 1], vec[0, 1]))
            rolls = (angle - axis, angle - axis + 180, 0.)
            if readings(declared, 'roll') is not None:
                rolls = readings(declared, 'roll') + [r for r in (angle - axis, angle - axis + 180, angle - axis - 180)
                                                      if not outside({'roll': readings(declared, 'roll')}, {'yaw': 0, 'elevation': 0, 'roll': r})]
            for roll in rolls:
                yield place(points, {**base, 'roll': float(roll), 'scale': float(spread[0] / np.sqrt(max(w[1], 1e-9)))}, centre)


def solve(views, resolution=40):
    """Greedy add + joint polish. views[0] is the anchor (fixed scale, labelled camera)."""
    problem = Problem(views, resolution)
    active = [views[0]]
    for view in views[1:]:
        candidates = []
        for camera in problem.starts(view, active):
            view['camera'] = camera
            candidates.append((problem.objective(active + [view]), camera))
        candidates.sort(key=lambda t: -t[0])
        best = None
        for _, camera in candidates[:3]:
            view['camera'] = camera
            score = problem.descend(active + [view], view, scales=(10, 5))
            if best is None or score > best[0]: best = (score, view['camera'])
        view['camera'] = best[1]
        active.append(view)
    for view in views[1:]:
        problem.descend(views, view, scales=(5, 2.5))
    return problem


def held_out(problem, index):
    """Leave one view out of the hull, refit only its camera, and score its silhouette."""
    views = problem.views; target = views[index]
    others = [v for i, v in enumerate(views) if i != index]
    occupied = problem.hull(others)
    if not occupied.any(): return 0.
    saved = target['camera']
    points = problem.points[surface(occupied.reshape(problem.shape)).ravel()]
    best = (hm.iou(render(points, saved, problem.step), target['mask']), saved)
    for delta in (5, 2.5):
        improved = True
        while improved:
            improved = False
            for key, d in (('yaw', delta), ('yaw', -delta), ('elevation', delta), ('elevation', -delta), ('roll', delta), ('roll', -delta),
                           ('scale', .005 * delta), ('scale', -.005 * delta), ('du', delta / 2.5), ('du', -delta / 2.5), ('dv', delta / 2.5), ('dv', -delta / 2.5)):
                trial = {**best[1], 'offset': list(best[1]['offset'])}
                if key == 'scale': trial['scale'] *= 1 + d
                elif key in ('du', 'dv'): trial['offset'][key == 'dv'] += d
                else: trial[key] += d
                score = hm.iou(render(points, trial, problem.step), target['mask'])
                if score > best[0] + 1e-4: best = (score, trial); improved = True
    return float(best[0])
