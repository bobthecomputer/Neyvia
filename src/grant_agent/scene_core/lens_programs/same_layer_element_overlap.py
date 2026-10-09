import numpy as np

def measure(rgb, nodes, viewport):
    image = np.asarray(rgb)
    height, width = image.shape[:2]
    facts = {}
    normalized = []
    for node in nodes:
        box = node.get("bounds", {})
        x0 = max(0, min(width, int(box.get("x", 0))))
        y0 = max(0, min(height, int(box.get("y", 0))))
        x1 = max(x0, min(width, int(np.ceil(box.get("x", 0) + box.get("w", 0)))))
        y1 = max(y0, min(height, int(np.ceil(box.get("y", 0) + box.get("h", 0)))))
        normalized.append((node, x0, y0, x1, y1))
        facts[node.get("id", "")] = {"inkUnderNeighbor": False}
    for index, (node, x0, y0, x1, y1) in enumerate(normalized):
        if node.get("kind") != "text" or x1 <= x0 or y1 <= y0:
            continue
        own = image[y0:y1, x0:x1].astype(np.int16)
        if own.size == 0:
            continue
        edge = np.concatenate((image[max(0, y0-5):y0, x0:x1], image[y1:min(height, y1+5), x0:x1]), axis=0)
        if edge.size:
            background = np.median(edge.reshape(-1, 3), axis=0)
        else:
            background = np.median(own.reshape(-1, 3), axis=0)
        ink = np.max(np.abs(own - background), axis=2) > 24
        if not np.any(ink):
            continue
        for other, ax0, ay0, ax1, ay1 in normalized:
            if other is node or other.get("kind") == "text":
                continue
            ix0, iy0 = max(x0, ax0), max(y0, ay0)
            ix1, iy1 = min(x1, ax1), min(y1, ay1)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            region = image[iy0:iy1, ix0:ix1].astype(np.int16)
            local_ink = np.max(np.abs(region - background), axis=2) > 24
            if np.count_nonzero(local_ink) >= 3:
                facts[node.get("id", "")]["inkUnderNeighbor"] = True
                break
    return {"facts": facts, "nodes": []}