import numpy as np
from scipy import ndimage


def measure(rgb, nodes, viewport):
    facts = {}
    if rgb is None or rgb.ndim != 3 or rgb.shape[2] < 3:
        return {"facts": {"object": facts}}
    image = rgb[:, :, :3]
    height, width = image.shape[:2]
    obj = next((node for node in nodes if node.get("kind") == "object"), None)
    if obj is None or not obj.get("bounds"):
        return {"facts": {"object": facts}}
    box = obj["bounds"]
    x0 = max(0, int(box["x"]))
    y0 = max(0, int(box["y"]))
    x1 = min(width, int(box["x"] + box["w"]))
    y1 = min(height, int(box["y"] + box["h"]))
    if x1 <= x0 or y1 <= y0:
        return {"facts": {"object": facts}}
    crop = image[y0:y1, x0:x1].astype(np.int16)
    red, green, blue = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    orange = (red > green) & (green > blue) & ((red - blue) > 24) & (red > 65)
    if not orange.any():
        facts["culledHoleEvidence"] = 0.0
        facts["culledHoleCount"] = 0
        return {"facts": {"object": facts}}

    # Use only background-like pixels as candidate holes; nearby orange shading is not a gap.
    background = (blue > red * 0.82) | ((red - blue) < 18)
    background &= (red < 145) & (green < 155) & (blue < 175)
    silhouette = ndimage.binary_closing(orange, structure=np.ones((3, 3), dtype=bool), iterations=1)
    silhouette = ndimage.binary_fill_holes(silhouette)
    candidates = silhouette & background
    labels, count = ndimage.label(candidates, structure=np.ones((3, 3), dtype=bool))
    if count == 0:
        facts["culledHoleEvidence"] = 0.0
        facts["culledHoleCount"] = 0
        return {"facts": {"object": facts}}

    sizes = np.bincount(labels.ravel())
    ys, xs = np.indices(candidates.shape)
    # Require holes to be distinctly interior and large enough to be more than raster noise.
    interior = (xs > 2) & (xs < candidates.shape[1] - 3) & (ys > 2) & (ys < candidates.shape[0] - 3)
    accepted = np.zeros(count + 1, dtype=bool)
    for label_id in range(1, count + 1):
        region = labels == label_id
        area = int(sizes[label_id])
        if area < max(18, int(orange.sum() * 0.004)):
            continue
        if not np.any(region & interior):
            continue
        # Cull exterior-connected candidate regions and broad gaps that reach a crop edge.
        expanded = ndimage.binary_dilation(region, structure=np.ones((3, 3), dtype=bool), iterations=1)
        if np.any(expanded[0]) or np.any(expanded[-1]) or np.any(expanded[:, 0]) or np.any(expanded[:, -1]):
            continue
        accepted[label_id] = True
    area = int(np.sum(accepted[labels]))
    facts["culledHoleEvidence"] = float(area / max(1, int(orange.sum())))
    facts["culledHoleCount"] = int(np.count_nonzero(accepted))
    return {"facts": {"object": facts}}
