import numpy as np
from scipy import ndimage


def measure(rgb, nodes, viewport):
    image = np.asarray(rgb, dtype=np.uint8)
    red = image[:, :, 0].astype(float)
    green = image[:, :, 1].astype(float)
    blue = image[:, :, 2].astype(float)
    high = np.maximum(np.maximum(red, green), blue)
    low = np.minimum(np.minimum(red, green), blue)
    saturation = np.divide(high - low, high, out=np.zeros_like(high), where=high > 0)
    orange = (red > green) & (green > blue) & (saturation > 0.35)
    labels, count = ndimage.label(orange, structure=np.ones((3, 3), dtype=bool))
    sizes = np.bincount(labels.ravel(), minlength=count + 1)
    if count == 0:
        return {"facts": {"object": {"detachedComponentCount": 0}}}
    main = int(np.argmax(sizes[1:]) + 1)
    main_mask = labels == main
    near_main = ndimage.binary_dilation(main_mask, iterations=2)
    total = int(sizes[1:].sum())
    detached = 0
    for component in range(1, count + 1):
        size = int(sizes[component])
        if component != main and size >= 6 and size <= max(6, int(total * 0.25)):
            component_mask = labels == component
            if not np.any(component_mask & near_main):
                detached += 1
    return {"facts": {"object": {"detachedComponentCount": detached}}}
