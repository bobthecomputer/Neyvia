import numpy as np
from scipy import ndimage


def measure(rgb, nodes, viewport):
    image = np.asarray(rgb)
    red = image[:, :, 0].astype(np.int16)
    green = image[:, :, 1].astype(np.int16)
    blue = image[:, :, 2].astype(np.int16)
    orange = (red > green) & (green > blue) & ((red - blue) > 25)

    bounds = None
    for node in nodes:
        if node.get("kind") == "object":
            bounds = node.get("bounds")
            break
    if not bounds:
        return {"facts": {"object": {"interiorGapRatio": 0.0}}}

    x0 = max(0, int(bounds["x"]))
    y0 = max(0, int(bounds["y"]))
    x1 = min(image.shape[1], x0 + int(bounds["w"]))
    y1 = min(image.shape[0], y0 + int(bounds["h"]))
    mask = orange[y0:y1, x0:x1]
    if mask.size == 0 or not mask.any():
        return {"facts": {"object": {"interiorGapRatio": 0.0}}}

    # Bridge only pixel-scale breaks, then count background regions enclosed by
    # the resulting subject surface. Open spaces between parts remain connected
    # to the crop boundary and are excluded.
    closed = ndimage.binary_closing(mask, structure=np.ones((3, 3), dtype=bool))
    filled = ndimage.binary_fill_holes(closed)
    holes = filled & ~closed
    labels, count = ndimage.label(holes)
    if count:
        sizes = np.bincount(labels.ravel())
        keep = sizes >= 4
        keep[0] = False
        hole_area = int(keep[labels].sum())
    else:
        hole_area = 0
    surface_area = int(filled.sum())
    ratio = float(hole_area / surface_area) if surface_area else 0.0
    return {"facts": {"object": {"interiorGapRatio": ratio}}}