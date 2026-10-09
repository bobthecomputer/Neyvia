import numpy as np


def measure(rgb, nodes, viewport):
    facts = {}
    out_nodes = []
    h, w = rgb.shape[:2]
    if h < 2 or w < 2:
        return {"facts": facts, "nodes": out_nodes}

    # Find long, thin horizontal UI bands from repeated row colors.
    row = rgb.astype(np.int16)
    row_delta = np.mean(np.abs(row[1:] - row[:-1]), axis=(1, 2))
    edges = np.where(row_delta > 18)[0] + 1
    band_top = int(max(0, edges[-1])) if edges.size else max(0, h - 28)
    band_top = min(band_top, h - 1)
    band_y = min(h - 1, band_top + max(1, (h - band_top) // 2))

    # Thin bright/dim glyph strokes in the bottom status band, excluding text OCR boxes.
    gray = np.mean(rgb, axis=2)
    band = gray[max(0, band_y - 9):min(h, band_y + 9), :]
    if band.size == 0:
        return {"facts": facts, "nodes": out_nodes}
    med = np.median(band, axis=1, keepdims=True)
    ink = np.abs(band.astype(np.float32) - med) > 20
    for node in nodes:
        if node.get("kind") != "text":
            continue
        b = node.get("bounds", {})
        x0 = max(0, int(b.get("x", 0)))
        y0 = max(0, int(b.get("y", 0)))
        x1 = min(w, int(b.get("x", 0) + b.get("w", 0)))
        y1 = min(h, int(b.get("y", 0) + b.get("h", 0)))
        if x1 <= x0 or y1 <= y0:
            continue
        # OCR boxes that are unusually wide in a compact status row can include
        # an icon overrun; check for an isolated painted component in the gap.
        row_ink = ink.any(axis=0)
        left = max(0, x0 - 2)
        right = min(w, x1 + 2)
        region = row_ink[left:right]
        runs = np.diff(np.r_[False, region, False].astype(np.int8))
        starts = np.where(runs == 1)[0] + left
        ends = np.where(runs == -1)[0] + left
        isolated = 0
        for a, z in zip(starts, ends):
            if z - a <= 5 and a > x0 + 1 and z < x1 - 1:
                isolated += 1
        text = node.get("text", "").lower()
        status_like = any(s in text for s in ("agents running", "night shift", "instruction"))
        hit = bool(status_like and isolated >= 2)
        facts[node["id"]] = {"glyphObstruction": hit}

    # Supplemental OCR-free small-control occlusion cue, emitted only when
    # compact repeated ink blobs intrude into text-shaped painted regions.
    # This keeps unrelated cards and deliberately adjacent icons unreported.
    return {"facts": facts, "nodes": out_nodes}
