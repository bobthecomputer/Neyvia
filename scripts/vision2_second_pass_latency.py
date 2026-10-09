"""VISION2: second-pass latency in ONE warm process (no crop memo), next to the pre-registered measurement.

The decision run (scripts/vision2_ocr_decision.py) measures the added time inside 4 parallel cold workers
while other tracks share the machine. This probe re-measures only time, no labels: one process, OCR engine
warmed on a first image, first-pass OCR read from the memo, every second-pass crop recognised fresh.

Usage: python scripts/vision2_second_pass_latency.py [--n 60]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=60)
    ap.add_argument('--out', default=str(ROOT / 'scripts/evidence/VISION2-second-pass-latency.json'))
    a = ap.parse_args()
    import numpy as np
    from PIL import Image
    from grant_agent import laya_glance_image as L
    images = [r['image'] for r in json.loads((ROOT / 'scripts/evidence/VISION2-new-split.json').read_text(encoding='utf-8'))['images']][:a.n]
    L._recognize(Image.new('RGBA', (64, 16), (255, 255, 255, 255)))  # engine creation outside the timings
    rows = []
    for path in images:
        image = Image.open(path).convert('RGB')
        rgb = np.asarray(image)
        h, w = rgb.shape[:2]
        scale = 2.0 if w < 800 else 1.5
        big = image.resize((int(w * scale), int(h * scale)), Image.BICUBIC).convert('RGBA')
        t0 = time.perf_counter()
        ocr = L._recognize(big)
        first = (time.perf_counter() - t0) * 1000
        lines = []
        for text, words in ocr:
            words = [(t, x / scale, y / scale, ww / scale, hh / scale) for t, x, y, ww, hh in words]
            lines.append((text, L._box(words), words))
        _, m = L._second_pass(image, rgb, lines, None)
        rows.append({'image': path, 'firstPassOcrMs': round(first, 1), 'secondPassMs': m['secondPassMs'], 'crops': m['secondPassCrops']})
    sp = sorted(r['secondPassMs'] for r in rows)
    fp = sorted(r['firstPassOcrMs'] for r in rows)
    q = lambda v, p: round(v[int(p * (len(v) - 1))], 1)
    out = {'schema': 'neyvia.vision2.second-pass-latency.v1', 'images': len(rows), 'process': 'one warm process, no crop memo',
           'secondPassMedianMs': q(sp, .5), 'secondPassP95Ms': q(sp, .95), 'firstPassOcrMedianMs': q(fp, .5),
           'cropsMean': round(statistics.mean(r['crops'] for r in rows), 2), 'rows': rows}
    Path(a.out).write_text(json.dumps(out, indent=1), encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, indent=1))


if __name__ == '__main__':
    main()
