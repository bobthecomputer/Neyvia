import numpy as np
from scipy import ndimage


def measure(rgb, nodes, viewport):
    image = np.asarray(rgb)
    red = image[:, :, 0].astype(np.int16)
    green = image[:, :, 1].astype(np.int16)
    blue = image[:, :, 2].astype(np.int16)
    high = np.maximum(np.maximum(red, green), blue)
    low = np.minimum(np.minimum(red, green), blue)
    orange = (red > green) & (green > blue) & ((red - blue) >= 24) & ((high - low) >= 35)
    labels, count = ndimage.label(orange, structure=np.ones((3, 3), dtype=bool))
    result = 0
    if count > 1:
        areas = np.bincount(labels.ravel())
        main_label = int(np.argmax(areas[1:]) + 1)
        main_area = int(areas[main_label])
        main = labels == main_label
        distance = ndimage.distance_transform_edt(~main)
        minimum_area = max(28, int(main_area * 0.008))
        for label in range(1, count + 1):
            if label == main_label:
                continue
            area = int(areas[label])
            if area < minimum_area:
                continue
            separation = float(np.min(distance[labels == label]))
            if separation >= 6.0:
                result += 1
    return {"facts": {"object": {"detachedPieceCountMeasured": result}}}