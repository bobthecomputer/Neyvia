import numpy as np
import re


def measure(rgb, nodes, viewport):
    h, w = rgb.shape[:2]
    facts = {}
    out = []
    control_re = re.compile(r"^(export|save|cancel|apply|submit|download|generate|publish|create|send|run|install|open|confirm)(?:\s+(?:file|image|project))?$", re.I)
    for node in nodes:
        node_id = node.get("id", "")
        facts[node_id] = {"panelBottomControlCut": False}
        if node.get("kind") != "text":
            continue
        b = node.get("bounds", {})
        x, y = float(b.get("x", 0)), float(b.get("y", 0))
        nw, nh = float(b.get("w", 0)), float(b.get("h", 0))
        text = str(node.get("text", "")).strip()
        # Only short, standalone control labels: prose mentioning a download is
        # not evidence that a button is being cut off.
        if not control_re.fullmatch(text) or nw <= 0 or nh <= 0 or len(text) > 24:
            continue
        if y + nh < h * 0.50:
            continue
        left, right = max(0, int(x)), min(w, int(x + nw))
        top, bottom = max(0, int(y)), min(h, int(y + nh))
        if right <= left or bottom <= top:
            continue
        # Look just below the label for a broad, horizontal panel boundary.
        x0, x1 = max(0, left - 40), min(w, right + 40)
        y0, y1 = max(bottom + 3, int(h * 0.52)), min(h - 3, bottom + 48)
        if x1 - x0 < 36 or y1 <= y0:
            continue
        band = rgb[:, x0:x1, :].astype(np.int16)
        row_delta = np.abs(np.diff(band, axis=0)).mean(axis=(1, 2))
        candidates = np.arange(y0, y1 + 1)
        scores = row_delta[candidates - 1]
        idx = int(np.argmax(scores))
        boundary = int(candidates[idx])
        if float(scores[idx]) < 13 or boundary >= h - 3:
            continue
        # A genuine fixed panel edge persists across most of the local span.
        local = rgb[max(0, boundary - 2):min(h, boundary + 3), x0:x1, :].astype(np.int16)
        adjacent = rgb[max(0, boundary - 9):boundary - 3, x0:x1, :].astype(np.int16)
        if local.size == 0 or adjacent.size == 0:
            continue
        edge_row = rgb[boundary, x0:x1, :].astype(np.int16)
        contrast_cols = np.abs(edge_row - rgb[boundary - 1, x0:x1, :].astype(np.int16)).mean(axis=1) > 12
        if float(contrast_cols.mean()) < 0.62:
            continue
        # Require a control-sized surface to extend to both sides of the edge,
        # with a visible change below it, consistent with panel clipping.
        bx0, bx1 = max(0, left - 10), min(w, right + 10)
        above = rgb[max(0, boundary - 16):boundary - 3, bx0:bx1, :].astype(np.int16)
        below = rgb[boundary + 3:min(h, boundary + 16), bx0:bx1, :].astype(np.int16)
        if above.size == 0 or below.size == 0:
            continue
        change = float(np.abs(above.mean(axis=(0, 1)) - below.mean(axis=(0, 1))).mean())
        edge_continuity = float(np.abs(rgb[boundary - 2, bx0:bx1, :].astype(np.int16) - rgb[boundary + 2, bx0:bx1, :].astype(np.int16)).mean())
        if change > 22 and edge_continuity < 24:
            facts[node_id]["panelBottomControlCut"] = True
    return {"facts": facts, "nodes": out}
