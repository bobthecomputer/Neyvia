import numpy as np


def measure(rgb, nodes, viewport):
    height, width = rgb.shape[:2]
    facts = {}
    for node in nodes:
        if node.get("kind") != "text":
            continue
        bounds = node.get("bounds", {})
        x = float(bounds.get("x", 0))
        y = float(bounds.get("y", 0))
        w = float(bounds.get("w", 0))
        h = float(bounds.get("h", 0))
        label = node.get("text", "").strip().lower()
        row_mid = y + h * 0.5

        # OCR line must itself reach the viewport edge; nearby toolbar labels alone
        # are not evidence of clipping. Allow a small raster/OCR boundary tolerance.
        near_right = x + w >= width - 3
        toolbar_row = row_mid >= height * 0.94
        cut = False
        if near_right and toolbar_row and width >= 8 and h > 0:
            left = max(0, int(width - 8))
            top = max(0, int(y - 2))
            bottom = min(height, int(y + h + 2))
            strip = rgb[top:bottom, left:width, :].astype(np.int16)
            if strip.size:
                # Require ink or a high-contrast partial glyph at the physical edge.
                edge = strip[:, -1, :]
                gray = edge.mean(axis=1)
                ink_rows = np.count_nonzero((gray < 155) | (gray > 230))
                chroma = np.max(np.ptp(edge, axis=1))
                local_delta = np.max(np.abs(strip[:, -1, :].astype(np.int16) - strip[:, -2, :].astype(np.int16)))
                cut = bool(ink_rows >= 2 and (chroma > 18 or local_delta > 24))
        facts[node["id"]] = {"rightEdgeControlCut": bool(cut)}
    return {"facts": facts, "nodes": []}
