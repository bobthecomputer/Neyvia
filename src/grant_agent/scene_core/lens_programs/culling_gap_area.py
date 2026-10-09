import numpy as np
from scipy import ndimage


def measure(rgb, nodes, viewport):
    facts = {"object": {"cullingGapRatio": 0.0}}
    obj = next((node for node in nodes if node.get("kind") == "object"), None)
    if obj is None:
        return {"facts": facts}
    bounds = obj.get("bounds")
    if not bounds:
        return {"facts": facts}

    height, width = rgb.shape[:2]
    x = max(0, int(bounds.get("x", 0)))
    y = max(0, int(bounds.get("y", 0)))
    right = min(width, x + int(bounds.get("w", 0)))
    bottom = min(height, y + int(bounds.get("h", 0)))
    if right <= x or bottom <= y:
        return {"facts": facts}

    crop = rgb[y:bottom, x:right]
    red = crop[:, :, 0].astype(np.int16)
    green = crop[:, :, 1].astype(np.int16)
    blue = crop[:, :, 2].astype(np.int16)
    orange = (red > green) & (green > blue) & ((red - blue) / np.maximum(red, 1) > 0.35)
    subject_area = int(orange.sum())
    if subject_area < 80 or min(crop.shape[:2]) < 18:
        return {"facts": facts}

    # Close small silhouette breaks, then fill only sizeable enclosed regions.
    # Requiring neutral floor/background colours suppresses orange shading and facets.
    structure = np.ones((5, 5), dtype=bool)
    closed = ndimage.binary_closing(orange, structure=structure, iterations=2)
    enclosed = ndimage.binary_fill_holes(closed) & ~orange
    chroma = np.maximum(np.maximum(red, green), blue) - np.minimum(np.minimum(red, green), blue)
    neutral = chroma < 24
    visible_gap = enclosed & neutral
    labels, count = ndimage.label(visible_gap)
    if count:
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        # Ignore pinholes and small openings; these occur naturally at handles and rims.
        largest = int(sizes.max())
        if largest >= max(24, int(subject_area * 0.035)):
            facts["object"]["cullingGapRatio"] = round(largest / subject_area, 4)
    return {"facts": facts}
