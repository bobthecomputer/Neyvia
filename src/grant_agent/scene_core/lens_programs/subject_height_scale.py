import numpy as np


def measure(rgb, nodes, viewport):
    facts = {}
    object_node = next((node for node in nodes if node.get("kind") == "object"), None)
    reference_node = next((node for node in nodes if node.get("kind") == "reference"), None)
    object_bounds = object_node.get("bounds") if object_node else None
    reference_bounds = reference_node.get("bounds") if reference_node else None
    view = str(viewport.get("view", "front")).lower()
    frame_height = float(viewport.get("height", rgb.shape[0]) or rgb.shape[0])
    expected_height = float(viewport.get("expectedHeightM", 0) or 0)
    reference_height = float(viewport.get("referenceHeightM", 1.8) or 1.8)
    close_view = "close" in view
    deviation = 1.0

    if close_view:
        if object_bounds is not None and frame_height > 0:
            fraction = float(object_bounds.get("h", 0) or 0) / frame_height
            if fraction > 0:
                # Close views are framed around the declared subject height; avoid
                # treating modest framing variation as a scale defect.
                if fraction < 0.25:
                    deviation = 0.25 / fraction
                elif fraction > 0.60:
                    deviation = fraction / 0.60
    elif (object_bounds is not None and reference_bounds is not None
          and expected_height > 0 and reference_height > 0):
        object_px = float(object_bounds.get("h", 0) or 0)
        reference_px = float(reference_bounds.get("h", 0) or 0)
        if object_px > 0 and reference_px > 0:
            observed = object_px / reference_px
            expected = expected_height / reference_height
            ratio = observed / expected
            if ratio > 0:
                deviation = max(ratio, 1.0 / ratio)

    facts["object"] = {"heightScaleDeviation": float(deviation)}
    return {"facts": facts}
