"""VISION2: prove the faster _text_runs returns exactly what the previous implementation returned.

Reference = the implementation at 4d4269333 (float mean + binary_dilation 3x9), inlined below. Runs both
on every labelled capture (495 + the 163 new-split captures) and compares the run lists, plus timing.

Usage: python scripts/vision2_text_runs_identity.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]


def reference(rgb):
    import numpy as np
    from scipy import ndimage
    gray = rgb.astype(np.int16).mean(axis=2)
    edges = np.zeros(gray.shape, bool)
    edges[:, 1:] = np.abs(gray[:, 1:] - gray[:, :-1]) > 28
    joined = ndimage.binary_dilation(edges, structure=np.ones((3, 9), bool))
    labels, _ = ndimage.label(joined)
    runs = []
    for sl in ndimage.find_objects(labels):
        if sl is None:
            continue
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if 7 <= h <= 40 and w >= 24 and w >= 2.5 * h and edges[sl].mean() >= 0.06:
            runs.append((sl[1].start, sl[0].start, sl[1].stop, sl[0].stop))
    return runs


def main():
    import numpy as np
    from PIL import Image
    from grant_agent.laya_glance_image import _text_runs
    from laya_glance_eval import load_labels
    images = [r['image'] for r in load_labels()]
    images += [r['image'] for r in json.loads((ROOT / 'scripts/evidence/VISION2-new-split.json').read_text(encoding='utf-8'))['images']]
    same, t_ref, t_new, differ = 0, 0.0, 0.0, []
    for path in images:
        rgb = np.asarray(Image.open(path).convert('RGB'))
        t = time.perf_counter(); a = reference(rgb); t_ref += time.perf_counter() - t
        t = time.perf_counter(); b = _text_runs(rgb); t_new += time.perf_counter() - t
        if a == b:
            same += 1
        else:
            differ.append(path)
    out = {'schema': 'neyvia.vision2.text-runs-identity.v1', 'images': len(images), 'identical': same, 'differ': differ,
           'referenceMsPerImage': round(t_ref * 1000 / len(images), 1), 'newMsPerImage': round(t_new * 1000 / len(images), 1)}
    (ROOT / 'scripts/evidence/VISION2-text-runs-identity.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
