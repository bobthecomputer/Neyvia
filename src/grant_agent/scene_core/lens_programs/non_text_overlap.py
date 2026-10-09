import numpy as np


def measure(rgb, nodes, viewport):
    image = np.asarray(rgb)
    height, width = image.shape[:2]
    facts = {}
    output_nodes = []
    text_nodes = [n for n in nodes if n.get("kind") == "text" and n.get("bounds")]
    gray = image.astype(np.int16).mean(axis=2)
    for node in text_nodes:
        box = node["bounds"]
        x0 = max(0, int(box["x"]))
        y0 = max(0, int(box["y"]))
        x1 = min(width, int(box["x"] + box["w"]))
        y1 = min(height, int(box["y"] + box["h"]))
        if x1 <= x0 or y1 <= y0:
            continue
        pad = 9
        ax0, ay0 = max(0, x0-pad), max(0, y0-pad)
        ax1, ay1 = min(width, x1+pad), min(height, y1+pad)
        patch = gray[ay0:ay1, ax0:ax1]
        local = patch[(patch > 18) & (patch < 245)]
        if local.size < 20:
            continue
        threshold = float(np.percentile(local, 75))
        ink = gray[y0:y1, x0:x1] >= threshold
        if ink.size == 0:
            continue
        outside = np.ones(patch.shape, dtype=bool)
        outside[y0-ay0:y1-ay0, x0-ax0:x1-ax0] = False
        surrounding = patch[outside]
        if surrounding.size < 30:
            continue
        # A covering object must create a substantial, sharply bounded region
        # that cuts through the OCR line, rather than a nearby button edge.
        rows, cols = np.where(ink)
        if cols.size < 8:
            continue
        hit = False
        for xx in range(x0+2, x1-2):
            col = gray[y0:y1, xx]
            dark = col < threshold
            if np.count_nonzero(dark) < 3:
                continue
            if np.count_nonzero(ink[:, xx-x0]) < 1:
                # Only consider OCR-reported ink interrupted inside its bounds.
                continue
            neighborhood = gray[max(0,y0-3):min(height,y1+3), max(0,xx-2):min(width,xx+3)]
            if neighborhood.size and float(np.ptp(neighborhood)) > 55:
                hit = True
                break
        if hit:
            facts[node["id"]] = {"paintOccludesGlyph": True}
    return {"facts": facts, "nodes": output_nodes}
