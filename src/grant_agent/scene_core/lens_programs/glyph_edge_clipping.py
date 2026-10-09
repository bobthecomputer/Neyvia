import numpy as np


def measure(rgb, nodes, viewport):
    h, w = rgb.shape[:2]
    facts = {}
    regions = []
    gray = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]).astype(np.uint8)

    for node in nodes:
        if node.get("kind") != "text":
            continue
        b = node.get("bounds", {})
        x0 = max(0, int(b.get("x", 0)))
        y0 = max(0, int(b.get("y", 0)))
        x1 = min(w, int(np.ceil(b.get("x", 0) + b.get("w", 0))))
        y1 = min(h, int(np.ceil(b.get("y", 0) + b.get("h", 0))))
        inkTouch = False
        nearEdge = False
        if x1 > x0 and y1 > y0:
            patch = gray[y0:y1, x0:x1]
            edge = max(1, min(3, patch.shape[1] // 8))
            med = float(np.median(patch))
            # Threshold relative to local background, robust to light and dark text.
            dark = patch < max(40, med - 28)
            light = patch > min(245, med + 28)
            ink = dark | light
            edge_ink = ink[:, -edge:]
            edge_density = float(np.mean(edge_ink))
            inner_density = float(np.mean(ink[:, max(0, patch.shape[1] - 2 * edge):max(1, patch.shape[1] - edge)])) if patch.shape[1] > edge else 0.0
            inkTouch = edge_density > 0.12 and inner_density > 0.04
            # OCR ending mid-word is a useful signal, but require image ink near its measured right bound.
            nearEdge = inkTouch and (x1 >= w - 2 or edge_density > inner_density * 1.4)
        clipped = bool(nearEdge and not str(node.get("text", "")).rstrip().endswith(("…", "...")))
        facts[node["id"]] = {"glyphEdgeClipping": clipped}

    return {"facts": facts, "nodes": regions}
