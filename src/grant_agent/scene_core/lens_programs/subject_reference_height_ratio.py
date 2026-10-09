import numpy as np


def measure(rgb, nodes, viewport):
    object_bounds = None
    reference_bounds = None
    for node in nodes:
        bounds = node.get("bounds")
        if node.get("kind") == "object":
            object_bounds = bounds
        elif node.get("kind") == "reference":
            reference_bounds = bounds

    view = viewport.get("view", "front")
    expected_height = float(viewport.get("expectedHeightM", 0) or 0)
    reference_height = float(viewport.get("referenceHeightM", 1.8) or 1.8)
    height_ratio = 0.0
    if object_bounds and reference_bounds and view == "front":
        object_px = max(0.0, float(object_bounds.get("h", 0)))
        reference_px = max(0.0, float(reference_bounds.get("h", 0)))
        if reference_px > 0 and expected_height > 0 and reference_height > 0:
            height_ratio = (object_px / reference_px) / (expected_height / reference_height)
    elif object_bounds and view in ("close", "close-high"):
        frame_height = float(viewport.get("height", rgb.shape[0]) or rgb.shape[0])
        object_px = max(0.0, float(object_bounds.get("h", 0)))
        if frame_height > 0:
            height_ratio = object_px / frame_height
    return {"facts": {"object": {"subjectHeightRatio": float(height_ratio)}}}
