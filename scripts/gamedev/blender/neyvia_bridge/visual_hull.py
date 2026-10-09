"""Bounded local inverse graphics: carve a voxel grid with fitted-camera silhouettes.

Cameras and masks come from LAYA's CL shape program; hull_math is the same camera
definition the planner used, so building and comparing cannot disagree.
"""
import numpy as np
import bpy

from .hull_math import grid, carve

# Outward quad corners per face direction, counter-clockwise seen from outside.
_FACES = {
    (1, 0, 0): ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)),
    (-1, 0, 0): ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)),
    (0, 1, 0): ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)),
    (0, -1, 0): ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),
    (0, 0, 1): ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)),
    (0, 0, -1): ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)),
}


def occupancy(args):
    resolution = int(args.get('resolution', 64))
    if not 24 <= resolution <= 128: raise ValueError('Visual hull resolution must be 24..128')
    low, high = (np.asarray(b, float) for b in args['bounds'])
    if low.shape != (3,) or high.shape != (3,) or not np.all(np.isfinite(low)) or np.any(high - low <= 0) or np.any(high - low > 20):
        raise ValueError('Invalid visual hull bounds')
    views = args['views']
    if not 1 <= len(views) <= 8: raise ValueError('Visual hull needs one to eight fitted views')
    points, shape, step = grid((low, high), resolution)
    inside = carve(points, views, int(args.get('tolerance', 0)), int(args.get('quorum', 0))).reshape(shape)
    if not inside.any(): raise ValueError('Fitted views have no common volume; review inconsistent views')
    return inside, low, step


def mesh_from(inside, low, step):
    padded = np.pad(inside, 1)
    lattice = np.array(inside.shape) + 1
    quads = []
    for (dx, dy, dz), corners in _FACES.items():
        neighbour = padded[1 + dx:padded.shape[0] - 1 + dx, 1 + dy:padded.shape[1] - 1 + dy, 1 + dz:padded.shape[2] - 1 + dz]
        cells = np.argwhere(inside & ~neighbour)
        quads.append(np.stack([cells + np.array(corner) for corner in corners], 1))
    quads = np.concatenate(quads, 0)
    keys = (quads[..., 0] * lattice[1] + quads[..., 1]) * lattice[2] + quads[..., 2]
    unique, inverse = np.unique(keys.ravel(), return_inverse=True)
    coords = np.stack([unique // (lattice[1] * lattice[2]), (unique // lattice[2]) % lattice[1], unique % lattice[2]], 1)
    vertices = low + coords * step
    return vertices, inverse.reshape(-1, 4)


def build(args):
    inside, low, step = occupancy(args)
    vertices, faces = mesh_from(inside, low, step)
    mesh = bpy.data.meshes.new(args['name'])
    mesh.vertices.add(len(vertices)); mesh.vertices.foreach_set('co', vertices.astype(np.float32).ravel())
    mesh.loops.add(faces.size); mesh.loops.foreach_set('vertex_index', faces.astype(np.int32).ravel())
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set('loop_start', (np.arange(len(faces)) * 4).astype(np.int32))
    mesh.polygons.foreach_set('loop_total', np.full(len(faces), 4, np.int32))
    mesh.update(); mesh.validate()
    obj = bpy.data.objects.new(args['name'], mesh); bpy.context.collection.objects.link(obj)
    obj['laya_hull_resolution'] = int(args.get('resolution', 64)); obj['laya_hull_step'] = float(step)
    obj['laya_camera_status'] = 'fitted-weak-perspective'
    return obj
