import numpy as np
from scipy import ndimage

def measure(rgb, nodes, viewport):
    facts = {"object": {"detachedPieceGapPx": 0.0}}
    if rgb is None or rgb.ndim != 3 or rgb.shape[2] < 3:
        return {"facts": facts}

    image = rgb[:, :, :3].astype(np.int16)
    red, green, blue = image[:, :, 0], image[:, :, 1], image[:, :, 2]
    orange = (red > green) & (green > blue) & ((red - blue) >= 28) & (red > 45)
    if not orange.any():
        return {"facts": facts}

    # Bridge tiny shading breaks so a ridged or back-face-damaged surface is less
    # likely to appear as many separate pieces.
    closed = ndimage.binary_closing(orange, structure=np.ones((3, 3), dtype=bool))
    labels, count = ndimage.label(closed)
    if count < 2:
        return {"facts": facts}

    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    main_label = int(np.argmax(sizes))
    main_size = int(sizes[main_label])
    if main_size < 30:
        return {"facts": facts}

    main = labels == main_label
    # Distance transform is computed once for the whole image, including distant
    # pieces. Compactness and area gates reject thin limbs, handles, and shading.
    distance = ndimage.distance_transform_edt(~main)
    best = 0.0
    max_piece = max(24, int(main_size * 0.12))
    for component in range(1, count + 1):
        if component == main_label:
            continue
        size = int(sizes[component])
        if size < 16 or size > max_piece:
            continue
        ys, xs = np.nonzero(labels == component)
        if xs.size == 0:
            continue
        box_w = int(xs.max() - xs.min() + 1)
        box_h = int(ys.max() - ys.min() + 1)
        if box_w < 4 or box_h < 4:
            continue
        occupancy = size / float(box_w * box_h)
        aspect = max(box_w, box_h) / float(min(box_w, box_h))
        if occupancy < 0.22 or aspect > 3.5:
            continue
        gap = float(distance[ys, xs].min())
        if gap >= 5.0:
            best = max(best, gap)

    facts["object"]["detachedPieceGapPx"] = best
    return {"facts": facts}