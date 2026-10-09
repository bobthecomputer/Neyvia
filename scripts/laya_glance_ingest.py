"""Write every labelled capture and every located defect as LAYA episodes.

No training. Each write is one append to plan 21's episode store and takes
effect on the next glance:
  * one ``ui-glance`` episode per labelled screenshot (495: the tour captures
    reviewed in D:/NeyviaRuns/ui-review plus the ui-fix / ui-fix2 before and
    after captures), with per-type labels; this also updates the per-predicate
    calibration counts that admit pixel verdicts at 0.95;
  * node lessons (``scene:ui-node:<type>``) for text-intrinsic defects: a quoted
    defect the rules missed becomes 'broken' on that text, a false alarm on an
    image labelled clean for that type becomes 'fine'.
The 194 detailed review bullets and 154 fixed-after screenshots imported by
scripts/laya_glance_corpus.py stay as they are (image-level episodes).

Usage: python scripts/laya_glance_ingest.py [--root .] [--workers 8]
Then: config/laya_glance_calibration.json is refreshed from the store.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from laya_glance_eval import load_labels, surface_group, _judge, _scene  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=ROOT)
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    from grant_agent.laya_glance import (TYPES, LESSON_TYPES, learn, learn_node, transcribe, locate_quote, quotes,
                                         node_text, _calibration_path, transcriber_version, SHIPPED_CALIBRATION)
    from grant_agent.laya_instant import store
    labels = load_labels()
    with ProcessPoolExecutor(a.workers) as pool:
        judged = list(pool.map(_judge, [r['image'] for r in labels], chunksize=4))
    local = store(str(a.root))
    writes, times = Counter(), []
    votes, example = defaultdict(Counter), {}
    for lab, j in zip(labels, judged):
        types = {t: int(lab['labels'].get(t, 0)) for t in TYPES}
        label = 'broken' if any(types.values()) else 'fine'
        notes = '; '.join(f'{t}: {lab["evidence"].get(t, "")}' for t in TYPES if types[t])
        reason = (notes or 'No defect of the nine types visible') + ' (labelled against D:/NeyviaRuns/ui-review)'
        source = 'LAYAG-label:' + str(Path(lab['image']).relative_to('D:/NeyviaRuns')).replace('\\', '/')
        started = time.perf_counter()
        result = learn(a.root, lab['image'], label, reason, source, surface=surface_group(lab['image']), types=types,
                       fired=set(j['fired']))
        times.append((time.perf_counter() - started) * 1000)
        writes['screenshots' if result.get('learned') else 'screenshotsAlreadyIngested'] += 1
        scene = transcribe(_scene(lab['image']))
        by_id = {n['id']: n for n in scene['nodes']}
        for b in j['bugs']:
            if b['type'] in LESSON_TYPES and not types[b['type']] and b['node'] in by_id and node_text(by_id[b['node']]):
                key = (b['type'], node_text(by_id[b['node']]))
                votes[key]['fine'] += 1
                example[key] = (scene, b['node'], lab['image'])
        for t in LESSON_TYPES:
            if types[t] and t not in j['fired']:
                for q in quotes(lab['evidence'].get(t, '')):
                    nid = locate_quote(scene, q)
                    if nid and node_text(by_id[nid]):
                        key = (t, node_text(by_id[nid]))
                        votes[key]['broken'] += 1
                        example[key] = (scene, nid, lab['image'])
    lesson_ms = []
    for (t, text), c in sorted(votes.items()):
        label = 'broken' if c['broken'] > c['fine'] else 'fine'
        scene, nid, image = example[(t, text)]
        started = time.perf_counter()
        result = learn_node(a.root, scene, nid, t, label, f'Located in labelled capture {Path(image).name} ({dict(c)})',
                            'LAYAG-node:' + t + ':' + hashlib.sha256(text.encode()).hexdigest()[:16])
        lesson_ms.append((time.perf_counter() - started) * 1000)
        writes['lessons-' + label + ('' if result.get('learned') else '-already')] += 1
    cal = json.loads(_calibration_path(a.root).read_text(encoding='utf-8'))
    shipped = {'schema': 'neyvia.laya-glance-calibration.v1', 'transcriber': cal['transcriber'], 'level': cal['level'],
               'counts': cal['counts'], 'sources': len(cal['sources']),
               'meaning': 'Per-predicate image-level outcomes of the pixel glance on labelled captures (episodes); '
                          'precision/NPV bounds are k/(n+1). Rebuilt by scripts/laya_glance_ingest.py.'}
    SHIPPED_CALIBRATION.write_text(json.dumps(shipped, indent=1) + '\n', encoding='utf-8')
    local.refresh()
    domains = Counter(r['domain'] for r in local.rows if r.get('kind', 'learn') == 'learn')
    summary = {'schema': 'neyvia.layag-ingest.v2', 'labelledScreenshots': len(labels), 'writes': dict(writes),
               'writeMsMedian': round(statistics.median(times), 1), 'lessonWriteMsMedian': round(statistics.median(lesson_ms), 1) if lesson_ms else None,
               'episodesByDomain': {k: v for k, v in sorted(domains.items()) if k == 'ui-glance' or k.startswith('scene:ui')},
               'calibration': {t: {**cal['counts'][t]} for t in TYPES}, 'transcriber': transcriber_version(),
               'reviewBulletsImportedEarlier': 'scripts/laya_glance_corpus.py: 194 detailed P1/P2/P3 bullets + 154 fixed-after screenshots',
               'training': 'none: appends only', 'store': str((a.root / '.neyvia/laya').resolve())}
    (ROOT / 'scripts/evidence/LAYAG-ingest-episodes.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
