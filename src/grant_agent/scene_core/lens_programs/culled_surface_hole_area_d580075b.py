import numpy as np
from scipy import ndimage


def measure(rgb, nodes, viewport):
    facts = {}
    height, width = rgb.shape[:2]
    for node in nodes:
        if node.get("kind") != "object":
            continue
        bounds = node.get("bounds")
        ratio = 0.0
        if bounds:
            x0 = max(0, int(bounds["x"]))
            y0 = max(0, int(bounds["y"]))
            x1 = min(width, x0 + max(0, int(bounds["w"])))
            y1 = min(height, y0 + max(0, int(bounds["h"])))
            crop = rgb[y0:y1, x0:x1].astype(np.int16)
            if crop.size:
                red, green, blue = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
                orange = (red > green) & (green > blue) & ((red - blue) > 28) & ((red - blue) > 0.20 * np.maximum(red, 1))
                if np.any(orange):
                    # Fill the subject silhouette, then look for neutral pixels in its interior.
                    # Restrict to sizable connected orange regions so small handles and floaters do not dominate.
                    labels, count = ndimage.label(orange)
                    sizes = np.bincount(labels.ravel())
                    keep = (labels > 0) & (sizes[labels] >= 12)
                    silhouette = ndimage.binary_fill_holes(ndimage.binary_closing(keep, structure=np.ones((3, 3), dtype=bool)))
                    area = int(np.count_nonzero(silhouette))
                    if area >= 160:
                        neutral = ((np.max(crop, axis=2) - np.min(crop, axis=2)) < 20) | (np.max(crop, axis=2) < 42)
                        interior = ndimage.binary_erosion(silhouette, structure=np.ones((3, 3), dtype=bool), iterations=2)
                        gaps = interior & neutral & ~orange
                        # Suppress tiny specks and narrow seams; retain broad, irregular culling patches.
                        gap_labels, gap_count = ndimage.label(gaps)
                        if gap_count:
                            gap_sizes = np.bincount(gap_labels.ravel())
                            substantial = (gap_labels > 0) & (gap_sizes[gap_labels] >= 12)
                            ratio = float(np.count_nonzero(substantial) / area)
        facts[node["id"]] = {"interiorNeutralPatchRatio": ratio}
    return {"facts": facts}