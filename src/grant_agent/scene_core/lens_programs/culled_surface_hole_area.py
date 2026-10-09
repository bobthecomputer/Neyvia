import numpy as np
from scipy import ndimage


def measure(rgb, nodes, viewport):
    obj = next((node for node in nodes if node.get("kind") == "object"), None)
    bounds = obj.get("bounds") if obj else None
    if not bounds:
        return {"facts": {"object": {"culledSurfaceHoleArea": 0.0}}}

    h, w = rgb.shape[:2]
    x0 = max(0, int(bounds.get("x", 0)))
    y0 = max(0, int(bounds.get("y", 0)))
    x1 = min(w, x0 + int(bounds.get("w", 0)))
    y1 = min(h, y0 + int(bounds.get("h", 0)))
    if x1 <= x0 or y1 <= y0:
        return {"facts": {"object": {"culledSurfaceHoleArea": 0.0}}}

    crop = rgb[y0:y1, x0:x1].astype(np.int16)
    red, green, blue = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    orange = (red > green + 8) & (green > blue + 8) & ((red - blue) > 28)
    area = int(np.count_nonzero(orange))
    if area < 30:
        return {"facts": {"object": {"culledSurfaceHoleArea": 0.0}}}

    # Limit this test to a compact, substantial orange subject. Thin parts and
    # open spaces in articulated silhouettes are common and are poor hole evidence.
    oh, ow = orange.shape
    frac = area / float(oh * ow)
    if frac < 0.055:
        return {"facts": {"object": {"culledSurfaceHoleArea": 0.0}}}

    # Estimate the continuous outer silhouette with a small, scale-aware closing.
    # This fills small surface gaps while leaving large limb and handle openings open.
    radius = max(2, min(6, int(round(min(oh, ow) * 0.012))))
    yy, xx = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    disk = (xx * xx + yy * yy) <= radius * radius
    closed = ndimage.binary_closing(orange, structure=disk)
    filled = ndimage.binary_fill_holes(closed)
    interior = filled & ~orange
    labels, count = ndimage.label(interior)
    if count == 0:
        return {"facts": {"object": {"culledSurfaceHoleArea": 0.0}}}

    sizes = np.bincount(labels.ravel())
    # A genuine culled patch is a sizable enclosed patch. Ignore small raster
    # cavities, and require grey values close to the exposed floor rather than shading.
    min_size = max(18, int(area * 0.004))
    component_ok = sizes >= min_size
    component_ok[0] = False
    floor_like = ((np.abs(red - green) < 10) & (np.abs(green - blue) < 14) &
                  (green > 55) & (green < 155))
    holes = component_ok[labels] & floor_like

    # Ignore components dominated by boundary pixels; their shapes usually come
    # from adjacent thin parts or imperfect segmentation rather than surface holes.
    boundary = ndimage.binary_dilation(orange, structure=np.ones((3, 3), dtype=bool), iterations=1)
    candidate = holes & boundary
    candidate_area = int(np.count_nonzero(candidate))
    ratio = candidate_area / float(area)

    # In close views a correctly framed model should occupy a meaningful fraction
    # of the image; this guard avoids treating unrelated pixels as subject defects.
    expected_h = float(viewport.get("expectedHeightM") or 0.0)
    if viewport.get("view") in ("close", "close-high") and expected_h > 0:
        subject_fraction = float(np.count_nonzero(np.any(orange, axis=1))) / max(oh, 1)
        if subject_fraction < 0.18:
            return {"facts": {"object": {"culledSurfaceHoleArea": 0.0}}}

    return {"facts": {"object": {"culledSurfaceHoleArea": float(ratio)}}}
