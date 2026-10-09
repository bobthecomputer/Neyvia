import numpy as np


def measure(rgb, nodes, viewport):
    height, width = rgb.shape[:2]
    facts = {}
    measured_nodes = []
    for node in nodes:
        bounds = node.get("bounds", {})
        text = node.get("text", "")
        x = float(bounds.get("x", 0))
        y = float(bounds.get("y", 0))
        w = float(bounds.get("w", 0))
        h = float(bounds.get("h", 0))
        right_gap = width - (x + w)
        bottom_gap = height - (y + h)
        # Only flag substantial text lines that are geometrically cut by an edge;
        # a small gap alone is normal for right-aligned toolbar labels.
        right_cut = right_gap < -1.5 and x < width and w >= 28 and h >= 10
        bottom_cut = bottom_gap < -1.5 and y < height and h >= 10 and w >= 28
        left_cut = x < -1.5 and x + w > 0 and w >= 28 and h >= 10
        top_cut = y < -1.5 and y + h > 0 and h >= 10 and w >= 28
        key = "controlEdgeCut"
        node_facts = {key: bool((right_cut or bottom_cut or left_cut or top_cut) and text.strip())}
        facts[node.get("id", "")] = node_facts
        measured_nodes.append({"kind": node.get("kind", "text"), "text": text, "bounds": bounds, "facts": node_facts})
    return {"facts": facts, "nodes": measured_nodes}
