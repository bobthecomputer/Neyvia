import numpy as np


def measure(rgb, nodes, viewport):
    height, width = rgb.shape[:2]
    facts = {}
    extra_nodes = []
    for node in nodes:
        text = node.get("text", "")
        bounds = node.get("bounds", {})
        x = float(bounds.get("x", 0))
        y = float(bounds.get("y", 0))
        w = float(bounds.get("w", 0))
        h = float(bounds.get("h", 0))
        right_gap = width - (x + w)
        near_right = 0 <= right_gap <= max(4.0, h * 0.8)
        status_control = (
            y >= height * 0.94
            and h >= 5
            and h <= 24
            and text.strip().lower() in {"grove", "voice"}
        )
        # A right-edge label is suspicious only when it is a short control-like
        # label in the bottom status strip and nearly touches the viewport edge.
        edge_label_cut = bool(status_control and near_right)
        facts[node["id"]] = {"edgeLabelTruncated": edge_label_cut}
    return {"facts": facts, "nodes": extra_nodes}
