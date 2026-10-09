import numpy as np
from scipy import ndimage

def measure(rgb, nodes, viewport):
    facts = {"object": {}}
    obj = next((n for n in nodes if n.get("kind") == "object"), None)
    if obj is None:
        return {"facts": facts}
    bounds = obj.get("bounds")
    if not bounds:
        facts["object"]["interiorVoidRatio"] = 0.0
        return {"facts": facts}
    x, y, w, h = (int(bounds[k]) for k in ("x", "y", "w", "h"))
    height, width = rgb.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 <= x0 or y1 <= y0:
        facts["object"]["interiorVoidRatio"] = 0.0
        return {"facts": facts}
    crop = rgb[y0:y1, x0:x1]
    r = crop[:, :, 0].astype(np.int16)
    g = crop[:, :, 1].astype(np.int16)
    b = crop[:, :, 2].astype(np.int16)
    chroma = crop.max(axis=2).astype(np.int16) - crop.min(axis=2).astype(np.int16)
    orange = (r > g + 8) & (g > b + 3) & (chroma > 35)
    if not orange.any():
        facts["object"]["interiorVoidRatio"] = 0.0
        return {"facts": facts}
    # Bridge small raster gaps so open seams can be assessed as interior voids.
    closed = ndimage.binary_closing(orange, structure=np.ones((5, 5), dtype=bool))
    filled = ndimage.binary_fill_holes(closed)
    interior = filled & ~closed
    # Count only neutral pixels consistent with the visible floor/background, not orange shading.
    neutral = (chroma < 42) & (r - b < 35)
    eligible = interior & neutral
    area = int(filled.sum())
    ratio = float(eligible.sum()) / max(1, area)
    facts["object"]["interiorVoidRatio"] = round(ratio, 5)
    return {"facts": facts}
