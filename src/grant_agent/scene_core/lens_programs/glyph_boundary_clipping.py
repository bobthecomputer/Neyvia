import numpy as np


def measure(rgb, nodes, viewport):
    image = np.asarray(rgb)
    height, width = image.shape[:2]
    facts = {}
    for node in nodes:
        if node.get("kind") != "text":
            continue
        box = node.get("bounds", {})
        x = int(round(float(box.get("x", 0))))
        y = int(round(float(box.get("y", 0))))
        w = int(round(float(box.get("w", 0))))
        h = int(round(float(box.get("h", 0))))
        if w < 3 or h < 3:
            continue
        left = max(0, x)
        top = max(0, y)
        right = min(width, x + w)
        bottom = min(height, y + h)
        if right <= left or bottom <= top:
            continue
        patch = image[top:bottom, left:right].astype(np.int16)
        # Identify foreground ink as pixels substantially different from the
        # median perimeter color, then check for ink touching either text-box edge.
        perimeter = np.concatenate((patch[0], patch[-1], patch[:, 0], patch[:, -1]), axis=0)
        bg = np.median(perimeter, axis=0)
        delta = np.max(np.abs(patch - bg), axis=2)
        ink = delta > 42
        if not ink.any():
            continue
        rows, cols = np.where(ink)
        edge_band = max(1, min(3, w // 30))
        left_touch = bool(np.any(cols < edge_band))
        right_touch = bool(np.any(cols >= (right - left) - edge_band))
        # OCR bounds commonly end at the last recognized glyph. A cut is more
        # likely when the glyph boundary has substantial ink across the edge.
        right_edge_ink = ink[:, -1]
        left_edge_ink = ink[:, 0]
        right_fraction = float(np.mean(right_edge_ink))
        left_fraction = float(np.mean(left_edge_ink))
        # Detached ellipsis is represented by terminal dots with visible space;
        # suppress ordinary three-dot text endings.
        text = str(node.get("text", ""))
        detached_ellipsis = text.rstrip().endswith(("...", "…"))
        right_clip = right_touch and right_fraction >= 0.08 and not detached_ellipsis
        left_clip = left_touch and left_fraction >= 0.08
        facts[node["id"]] = {
            "glyphEdgeTouch": bool(left_touch or right_touch),
            "glyphEdgeInkFraction": round(max(left_fraction, right_fraction), 3),
            "glyphBoundaryCut": bool(left_clip or right_clip),
        }
    return {"facts": facts, "nodes": []}
