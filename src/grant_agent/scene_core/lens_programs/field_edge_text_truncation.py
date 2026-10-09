import numpy as np


def measure(rgb, nodes, viewport):
    h, w = rgb.shape[:2]
    facts = {}
    regions = []
    lum = rgb.astype(np.float32).mean(axis=2)
    for node in nodes:
        if node.get("kind") != "text":
            continue
        b = node.get("bounds", {})
        x, y = float(b.get("x", 0)), float(b.get("y", 0))
        nw, nh = float(b.get("w", 0)), float(b.get("h", 0))
        text = node.get("text", "")
        right = x + nw
        # Require a text line to end extremely near the viewport boundary or a
        # strong, locally detected vertical boundary. This avoids treating
        # ordinary neighboring labels and complete tab labels as truncation.
        ix0 = max(0, int(round(x)))
        iy0 = max(0, int(round(y + nh * 0.15)))
        iy1 = min(h, max(iy0 + 1, int(round(y + nh * 0.9))))
        ir = min(w, max(ix0, int(round(right))))
        near_view_edge = (w - right) <= max(1.5, nh * 0.18)
        edge_strength = 0.0
        if iy1 > iy0 and 1 <= ir < w:
            left = lum[iy0:iy1, max(0, ir - 3):ir]
            right_strip = lum[iy0:iy1, ir:min(w, ir + 3)]
            if left.size and right_strip.size:
                edge_strength = float(abs(np.median(left) - np.median(right_strip)))
        # OCR lines explicitly ending at the viewport edge are useful only
        # when the final token is not punctuation/ellipsis and the ink reaches it.
        ink_touch = False
        if iy1 > iy0 and ix0 < w and ir > ix0:
            patch = lum[iy0:iy1, max(ix0, ir - 2):ir]
            if patch.size:
                ink_touch = float(np.min(patch)) < 150.0
        last = text.rstrip()[-1:] if text.strip() else ""
        suspicious_end = bool(last and last not in ".…,:;!?)]}»'7\u00a0")
        clipped = bool(near_view_edge and ink_touch and suspicious_end)
        facts[node["id"]] = {"fieldEdgeCut": clipped}
    return {"facts": facts, "nodes": regions}
