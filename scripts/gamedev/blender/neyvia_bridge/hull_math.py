"""One weak-perspective camera and silhouette-carving definition (numpy only, no bpy).

Shared by LAYA's planner (scene_core.image_sheets) and Blender's shape program so the
fitted cameras that build a hull are exactly the cameras that render the comparison.

World: X right, Y away from the front viewer, Z up. A camera is
{yaw, elevation, roll} in degrees plus scale (pixels per world unit) and offset
[du, dv] (pixels from the 128-pixel frame centre). yaw orbits the camera from the
front (-Y) toward +X, elevation raises it toward +Z, roll turns the image
counter-clockwise. Projection is orthographic: an explicit assumption for concept
art that was drawn with a mild perspective.
"""
import numpy as np

FRAME = 128
BASE = np.array([[1., 0, 0], [0, 0, 1], [0, -1, 0]])
LABELLED = {'front': (0, 0), 'back': (180, 0), 'side': (90, 0), 'left': (-90, 0), 'right': (90, 0),
            'top': (0, 90), 'bottom': (0, -90)}


def rotation(camera):
    yaw, elevation, roll = (np.radians(float(camera.get(k, 0))) for k in ('yaw', 'elevation', 'roll'))
    c, s = np.cos(-yaw), np.sin(-yaw)
    world = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    c, s = np.cos(elevation), np.sin(elevation)
    tilt = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    c, s = np.cos(roll), np.sin(roll)
    turn = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    return turn @ tilt @ BASE @ world


def project(points, camera):
    """World points (N,3) -> pixel (u, v) in the 128 frame, plus camera depth."""
    local = np.asarray(points, float) @ rotation(camera).T
    scale = float(camera['scale']); du, dv = camera.get('offset', (0, 0))
    return FRAME / 2 + scale * local[:, 0] + du, FRAME / 2 - scale * local[:, 1] + dv, local[:, 2]


def blender_camera(camera, distance=20.):
    """World matrix rows (4x4 nested lists) and ortho scale for a native camera."""
    r = rotation(camera); scale = float(camera['scale']); du, dv = camera.get('offset', (0, 0))
    location = r.T @ np.array([-du / scale, dv / scale, distance])
    matrix = np.eye(4); matrix[:3, :3] = r.T; matrix[:3, 3] = location
    return matrix.tolist(), FRAME / scale


def decode(mask_hex):
    bits = int(mask_hex, 16).to_bytes(FRAME * FRAME // 8, 'little')
    return np.unpackbits(np.frombuffer(bits, np.uint8), bitorder='little').reshape(FRAME, FRAME).astype(bool)


def encode(mask):
    return hex(int.from_bytes(np.packbits(np.asarray(mask, bool).ravel(), bitorder='little').tobytes(), 'little'))


def grid(bounds, resolution):
    low, high = np.asarray(bounds[0], float), np.asarray(bounds[1], float)
    step = (high - low).max() / resolution
    shape = np.maximum(1, np.ceil((high - low) / step).astype(int))
    axes = [low[i] + (np.arange(shape[i]) + .5) * step for i in range(3)]
    return np.stack(np.meshgrid(*axes, indexing='ij'), -1).reshape(-1, 3), tuple(shape), step


def dilate(mask, radius):
    if radius <= 0: return mask
    out = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius: continue
            out |= np.roll(np.roll(mask, dy, 0), dx, 1)
    return out


def carve(points, views, tolerance=1, quorum=0):
    """Visual hull: keep points inside every (tolerance-dilated) mask, or all but `quorum` of them.

    quorum=1 is the robust k-of-n hull: one drifted AI view cannot remove what the others agree on.
    """
    misses = np.zeros(len(points), np.int16)
    for view in views:
        mask = dilate(view['mask'] if 'mask' in view else decode(view['maskHex']), int(view.get('tolerance', tolerance)))
        u, v, _ = project(points, view['camera'])
        x, y = np.floor(u).astype(int), np.floor(v).astype(int)
        valid = (x >= 0) & (x < FRAME) & (y >= 0) & (y < FRAME)
        hit = np.zeros(len(points), bool); hit[valid] = mask[y[valid], x[valid]]
        misses += ~hit
    return misses <= min(int(quorum), max(0, len(views) - 2))


def splat(points, camera, radius=1):
    u, v, _ = project(points, camera)
    x, y = np.floor(u).astype(int), np.floor(v).astype(int)
    valid = (x >= 0) & (x < FRAME) & (y >= 0) & (y < FRAME)
    image = np.zeros((FRAME, FRAME), bool); image[y[valid], x[valid]] = True
    return dilate(image, radius)


def iou(a, b):
    return float((a & b).sum() / max((a | b).sum(), 1))
