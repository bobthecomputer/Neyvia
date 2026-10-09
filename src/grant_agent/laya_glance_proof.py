"""Before/after proof for the three P22 bugs, from pixels alone, plus cold latency.

The black PDF page, the see-through floating panels and the clipped composer
chips must be caught on the 'before' captures and absent on the 'after' ones.
Every image is transcribed cold in this process (no scene or OCR cache), so the
reported milliseconds are one real glance each: OCR + pixel facts + judge.

Contract thresholds (laya-glance.cl check pixel-before-after): no 'after'
capture is flagged for its fixed defect; the black PDF page is caught on every
'before' capture; see-through panels and clipped chips on at least 3/4 of them
(pixel boundary: a phone peek sheet whose foreign text lies wholly inside the
sheet shows no crossing; a chip row hidden under a panel is not visible).

Usage: python scripts/laya_glance_proof.py
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
MINIMUM = {'black-pdf-page': 1.0, 'see-through-panels': 0.75, 'clipped-chips': 0.75}
FIX = Path('D:/NeyviaRuns/ui-fix/pairs')
FIX2 = Path('D:/NeyviaRuns/ui-fix2')
ASK = re.compile(r'Ask\s+Ne\w*\s+to', re.I)


def chip_row(scene_nodes):
    """The composer chip row sits just under the 'Ask Neyvia to...' placeholder."""
    ask = next((n for n in scene_nodes if ASK.search(n['attributes'].get('text') or '')), None)
    if not ask:
        return None
    b = ask['attributes']['bounds']
    return (b['x'] - 30, b['y'] + 15, b['x'] + 420, b['y'] + 70)


def in_box(bounds, box):
    return bool(box and bounds and box[0] <= bounds['x'] <= box[2] and box[1] <= bounds['y'] <= box[3])

CASES = {
    'black-pdf-page': {
        'type': 'blank-render', 'node': lambda b: True,
        'pairs': [(FIX2 / 'before/pdf-full-dark-desktop.png', FIX2 / 'final3/pdf-full-dark-desktop.png'),
                  (FIX2 / 'before/pdf-main-dark-desktop.png', FIX2 / 'final3/pdf-main-dark-desktop.png'),
                  (FIX2 / 'before-l/pdf-full-light-desktop.png', FIX2 / 'final3/pdf-full-light-desktop.png'),
                  (FIX2 / 'before-l/pdf-main-light-desktop.png', FIX2 / 'final3/pdf-main-light-desktop.png')]},
    'see-through-panels': {
        'type': 'see-through', 'node': lambda b: True,
        'pairs': [(FIX / f'shell-before-{n}.png', FIX / f'shell-after-{n}.png') for n in (
            'dark-files-side-floating', 'dark-files-bubble-peek', 'dark-files-bubble-peek-phone',
            'dark-terminal-side-floating', 'dark-terminal-bubble-peek', 'dark-terminal-bubble-peek-phone',
            'light-files-side-floating', 'light-files-bubble-peek')]},
    'clipped-chips': {
        'type': 'clipped-text', 'node': lambda b: in_box(b.get('bounds'), b.get('chipRow')),
        'pairs': [(FIX / f'shell-before-{n}.png', FIX / f'shell-after-{n}.png') for n in (
            'dark-files-main', 'dark-laya-main', 'dark-laya-side', 'dark-terminal-side',
            'dark-files-side-floating', 'light-laya-main', 'light-laya-side', 'light-terminal-main')]},
}


def look(path):
    from grant_agent.laya_glance import glance, _transcribe
    started = time.perf_counter()
    v = glance(screenshot=str(path), calibration={}, lessons={}, record=False)
    ms = (time.perf_counter() - started) * 1000
    row = chip_row(_transcribe({'image': str(path)})['nodes'])
    bugs = [{'type': b['type'], 'node': b['node'], 'text': (b['evidence'] or {}).get('attributes.text'),
             'bounds': (b['evidence'] or {}).get('attributes.bounds'), 'chipRow': row} for b in v['bugs']]
    return bugs, ms, {**v['sceneMetrics'], 'composerVisible': row is not None}


def run():
    missing = [str(p) for c in CASES.values() for pair in c['pairs'] for p in pair if not Path(p).exists()]
    if missing:
        return {'schema': 'neyvia.layag-proof.v1', 'passed': False, 'reason': 'recorded captures missing', 'missing': missing[:5]}
    report = {'schema': 'neyvia.layag-proof.v1', 'cases': {}, 'boundary': 'Pixels only (OCR + measured facts); rules only, no lessons or calibration.'}
    times = []
    for name, case in CASES.items():
        rows = []
        for before, after in case['pairs']:
            row = {'before': str(before), 'after': str(after)}
            for side, path in (('before', before), ('after', after)):
                bugs, ms, metrics = look(path)
                times.append(ms)
                hits = [b for b in bugs if b['type'] == case['type'] and case['node'](b)]
                row[side + 'Caught'] = bool(hits)
                row[side + 'Evidence'] = [h['text'] for h in hits][:3]
                row[side + 'Ms'] = round(ms, 1)
                row[side + 'OtherTypes'] = sorted({b['type'] for b in bugs} - {case['type']})
                if name == 'clipped-chips':
                    row[side + 'ComposerVisible'] = metrics['composerVisible']
            row['ok'] = row['beforeCaught'] and not row['afterCaught']
            rows.append(row)
        report['cases'][name] = {'type': case['type'], 'pairs': rows, 'passed': sum(r['ok'] for r in rows), 'of': len(rows)}
    report['latencyMs'] = {'glances': len(times), 'median': round(statistics.median(times), 1),
                           'p95': round(sorted(times)[int(.95 * (len(times) - 1))], 1), 'max': round(max(times), 1),
                           'note': 'cold per image in one process: PNG decode + Windows OCR + pixel facts + shared judge'}
    clean_after = all(not r['afterCaught'] for c in report['cases'].values() for r in c['pairs'])
    enough = all(sum(r['beforeCaught'] for r in report['cases'][n]['pairs']) >= MINIMUM[n] * report['cases'][n]['of'] for n in MINIMUM)
    report.update(passed=clean_after and enough, cleanAfter=clean_after, minimumBeforeRate=MINIMUM)
    return report
