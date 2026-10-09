import numpy as np


def measure(rgb, nodes, viewport):
    facts = {}
    text_nodes = [n for n in nodes if n.get("kind") == "text" and n.get("bounds") and n.get("text", "").strip()]
    boxes = []
    for n in text_nodes:
        b = n["bounds"]
        x1, y1 = float(b["x"]), float(b["y"])
        x2, y2 = x1 + float(b["w"]), y1 + float(b["h"])
        boxes.append((x1, y1, x2, y2))
    for i, n in enumerate(text_nodes):
        x1, y1, x2, y2 = boxes[i]
        area = max(1.0, (x2 - x1) * (y2 - y1))
        visible_foreign_text = False
        for j, other in enumerate(text_nodes):
            if i == j or n["text"].strip().lower() == other["text"].strip().lower():
                continue
            a1, b1, a2, b2 = boxes[j]
            iw = max(0.0, min(x2, a2) - max(x1, a1))
            ih = max(0.0, min(y2, b2) - max(y1, b1))
            inter = iw * ih
            other_area = max(1.0, (a2 - a1) * (b2 - b1))
            smaller_area = min(area, other_area)
            height_ratio = max(y2 - y1, b2 - b1) / max(1.0, min(y2 - y1, b2 - b1))
            if inter / smaller_area >= 0.22 and height_ratio >= 1.25:
                visible_foreign_text = True
                break
        facts[n["id"]] = {"foreignTextVisible": visible_foreign_text}
    return {"facts": facts, "nodes": []}