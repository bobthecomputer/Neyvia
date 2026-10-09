"""VISION2: rebuild the shipped UI calibration (config/laya_glance_calibration.json) for the current transcriber.

The predicate fix (and the second-pass default, if on) changes ``transcriber_version()``, which orphans the
shipped per-predicate counts (load_calibration then returns None and nothing is admitted). The counts are
rebuilt from the 495 labelled episodes as judged by scripts/vision2_ocr_decision.py under the setting that
is now the default, exactly as scripts/vision_promote.py defines them (image-level tp/fp/tn/fn per type over
fit + check + final).

Usage: python scripts/vision2_calibration.py [--decision scripts/evidence/VISION2-ocr-decision.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--decision', default=str(ROOT / 'scripts/evidence/VISION2-ocr-decision.json'))
    a = ap.parse_args()
    from grant_agent import laya_glance_image
    from grant_agent.laya_glance import TYPES, transcriber_version, SHIPPED_CALIBRATION
    from laya_glance_eval import metrics
    d = json.loads(Path(a.decision).read_text(encoding='utf-8'))
    key = 'on' if laya_glance_image.SECOND_PASS_ENABLED else 'off'
    old = [r for r in d['rows'] if r['split'] in ('fit', 'check', 'final')]
    m = metrics([{**r, 'fired': r[key]} for r in old], TYPES)
    counts = {t: {k: m[t][k] for k in ('tp', 'fp', 'tn', 'fn')} for t in TYPES}
    prev = json.loads(SHIPPED_CALIBRATION.read_text(encoding='utf-8'))
    shipped = {'schema': 'neyvia.laya-glance-calibration.v1', 'transcriber': transcriber_version(), 'level': 0.95, 'counts': counts,
               'sources': len(old), 'lenses': prev.get('lenses', []), 'previousTranscriber': prev.get('transcriber'),
               'secondPass': laya_glance_image.SECOND_PASS_ENABLED,
               'meaning': 'Per-predicate image-level outcomes of the pixel glance on labelled captures (episodes); '
                          'precision/NPV bounds are k/(n+1). Rebuilt by scripts/vision2_calibration.py (VISION2 predicate fix).'}
    SHIPPED_CALIBRATION.write_text(json.dumps(shipped, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'transcriber': shipped['transcriber'], 'previous': shipped['previousTranscriber'], 'secondPass': key,
                      'internal-id': counts['internal-id'], 'encoded-path': counts['encoded-path']}, indent=1))


if __name__ == '__main__':
    main()
