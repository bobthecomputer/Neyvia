import numpy as np


def measure(rgb, nodes, viewport):
    facts = {}
    text_nodes = [node for node in nodes if node.get("kind") == "text" and node.get("bounds") and str(node.get("text", "")).strip()]
    if len(text_nodes) < 2:
        return {"facts": facts, "nodes": []}
    boxes = np.array([[float(node["bounds"]["x"]), float(node["bounds"]["y"]),
                       float(node["bounds"]["x"]) + float(node["bounds"]["w"]),
                       float(node["bounds"]["y"]) + float(node["bounds"]["h"])]
                      for node in text_nodes], dtype=float)
    widths = boxes[:, 2] - boxes[:, 0]
    heights = boxes[:, 3] - boxes[:, 1]
    left = np.maximum(boxes[:, None, 0], boxes[None, :, 0])
    top = np.maximum(boxes[:, None, 1], boxes[None, :, 1])
    right = np.minimum(boxes[:, None, 2], boxes[None, :, 2])
    bottom = np.minimum(boxes[:, None, 3], boxes[None, :, 3])
    overlap_w = np.maximum(0, right - left)
    overlap_h = np.maximum(0, bottom - top)
    area = overlap_w * overlap_h
    own_area = np.maximum(1, widths * heights)
    ratios = area / own_area[:, None]
    np.fill_diagonal(ratios, 0)
    lengths = np.array([len(str(node.get("text", "")).strip()) for node in text_nodes])
    heights_match = (heights[:, None] / np.maximum(1, heights[None, :]) >= 0.55) & (heights[:, None] / np.maximum(1, heights[None, :]) <= 1.8)
    substantial = (widths[:, None] >= 45) & (widths[None, :] >= 45) & (heights[:, None] >= 8) & (heights[None, :] >= 8)
    text_sized = (lengths[:, None] >= 5) & (lengths[None, :] >= 5)
    intrusion = np.any((ratios >= 0.38) & (ratios.T >= 0.38) & heights_match & substantial & text_sized, axis=1)
    for index, node in enumerate(text_nodes):
        facts[node["id"]] = {"substantialTextIntrusion": bool(intrusion[index])}
    return {"facts": facts, "nodes": []}
