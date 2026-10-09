"""Measure the UI glance on labelled screenshots, grouped by app surface.

Ground truth: D:/NeyviaRuns/laya-labels/batch-*.labels.json (per image, per type,
labelled against Paul's review in D:/NeyviaRuns/ui-review, vision-confirmed per
capture; copied into scripts/evidence/LAYAG-labels.json). Surfaces are grouped so
one app never appears on both sides; the FINAL holdout groups are fixed by hash
before any metric is read and are never used to tune predicates or calibration.

Usage: python scripts/laya_glance_eval.py [--final] [--workers 4]
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
LABELS = Path('D:/NeyviaRuns/laya-labels')
CACHE = Path('D:/NeyviaRuns/laya-glance/scenes')
PLACEMENTS = ('bubble-peek-isolated', 'side-floating', 'bubble-peek', 'side-left', 'dragging', 'bubble', 'main', 'full', 'side', 'failure')
ALIASES = {'citecraft': 'research', 'preview': 'app-preview'}


def surface_group(path):
    """App surface of a capture: the grouping unit for held-out evaluation."""
    stem = Path(path).stem
    stem = re.sub(r'^(shell|app|lab|laya)-(before|after)-(dark|light)-', '', stem)
    stem = re.sub(r'-(dark|light)-(desktop|phone)(-after-setup)?$', '', stem)
    stem = re.sub(r'-(adopted-service|tour)$', '', stem)
    stem = re.sub(r'-phone$', '', stem)
    for p in PLACEMENTS:
        if stem.endswith('-' + p):
            stem = stem[:-len(p) - 1]
            break
    return ALIASES.get(stem, stem)


def final_holdout(groups):
    """Fixed before measurement: ~30% of surface groups by name hash."""
    return {g for g in groups if int(hashlib.sha256(('layag-final:' + g).encode()).hexdigest()[:8], 16) % 10 < 3}


def load_labels():
    rows = []
    for f in sorted(LABELS.glob('batch-*.labels.json')):
        for r in json.loads(f.read_text(encoding='utf-8')):
            rows.append({'image': r['image'], 'labels': {k: int(v) for k, v in r['labels'].items()},
                         'evidence': r.get('evidence', {}), 'uncertain': r.get('uncertain', []), 'batch': f.stem})
    return rows


def _scene(path):
    from grant_agent.laya_glance import pixel_version
    from grant_agent.laya_glance_image import transcribe_image
    raw = Path(path).read_bytes()
    key = hashlib.sha256(raw).hexdigest()[:24] + '-' + pixel_version()
    cached = CACHE / (key + '.json')
    if cached.exists():
        return json.loads(cached.read_text(encoding='utf-8'))
    scene = transcribe_image(path, ocr_cache=CACHE.parent / 'ocr')
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(scene), encoding='utf-8')
    return scene


def _judge(path):
    from grant_agent.laya_glance import glance
    scene = _scene(path)
    started = time.perf_counter()
    verdict = glance(scene, calibration={}, lessons={}, record=False)
    return {'image': path, 'fired': sorted({b['type'] for b in verdict['bugs']}),
            'bugs': [{'type': b['type'], 'node': b['node'], 'text': (b['evidence'] or {}).get('attributes.text')} for b in verdict['bugs']],
            'judgeMs': (time.perf_counter() - started) * 1000, 'metrics': scene['metrics'], 'nodes': len(scene['nodes'])}


def metrics(rows, types):
    out = {}
    for t in types:
        c = Counter()
        for r in rows:
            f, y = t in r['fired'], bool(r['labels'].get(t))
            c['tp' if f and y else 'fp' if f else 'fn' if y else 'tn'] += 1
        p = c['tp'] / (c['tp'] + c['fp']) if c['tp'] + c['fp'] else None
        rc = c['tp'] / (c['tp'] + c['fn']) if c['tp'] + c['fn'] else None
        out[t] = {**{k: c[k] for k in ('tp', 'fp', 'tn', 'fn')}, 'precision': None if p is None else round(p, 3),
                  'recall': None if rc is None else round(rc, 3), 'positives': c['tp'] + c['fn']}
    return out


def episodes_run(dev, fin, types):
    """Instant learning on the dev groups only: every disagreement becomes a node
    lesson (false alarm -> 'fine', a quoted missed defect -> 'broken'), written
    to a fresh episode store; the final groups are then judged with those lessons."""
    from grant_agent.laya_glance import glance, transcribe, learn_node, locate_quote, quotes, node_text, _node_lessons, LESSON_TYPES
    types = [t for t in types if t in LESSON_TYPES]
    from grant_agent.laya_instant import store
    root = ROOT / '.agent_control/layag-eval-store' / str(time.time_ns())
    root.mkdir(parents=True, exist_ok=True)
    votes = defaultdict(Counter)
    example = {}
    for r in dev:
        scene = transcribe(_scene(r['image']))
        by_id = {n['id']: n for n in scene['nodes']}
        for b in r['bugs']:
            if b['type'] in types and not r['labels'].get(b['type']) and b['node'] in by_id and node_text(by_id[b['node']]):
                key = (b['type'], node_text(by_id[b['node']]))
                votes[key]['fine'] += 1
                example[key] = (scene, b['node'], r['image'])
        for t in types:
            if r['labels'].get(t) and t not in r['fired']:
                for q in quotes((r.get('evidence') or {}).get(t, '')):
                    nid = locate_quote(scene, q)
                    if nid and node_text(by_id[nid]):
                        key = (t, node_text(by_id[nid]))
                        votes[key]['broken'] += 1
                        example[key] = (scene, nid, r['image'])
    written, times = Counter(), []
    local = store(str(root))
    for (t, text), c in sorted(votes.items()):
        label = 'broken' if c['broken'] > c['fine'] else 'fine'
        scene, nid, image = example[(t, text)]
        started = time.perf_counter()
        learn_node(root, scene, nid, t, label, f'Dev label disagreement ({dict(c)}) on {Path(image).name}',
                   'layag-eval-dev:' + t + ':' + hashlib.sha256(text.encode()).hexdigest()[:16])
        times.append((time.perf_counter() - started) * 1000)
        written[label] += 1
    lessons = _node_lessons(root)
    fin2, judge_ms = [], []
    for r in fin:
        started = time.perf_counter()
        v = glance(_scene(r['image']), calibration={}, lessons=lessons, record=False)
        judge_ms.append((time.perf_counter() - started) * 1000)
        fin2.append({**r, 'fired': sorted({b['type'] for b in v['bugs']})})
    return ({'store': str(root), 'lessons': dict(written), 'writeMsMedian': round(statistics.median(times), 2) if times else None,
             'judgeWithLessonsMsMedian': round(statistics.median(judge_ms), 2), 'source': 'dev groups only'}, fin2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--final', action='store_true', help='also report the final held-out groups')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--show', default='', help='print fired/label disagreements for one type (dev only)')
    ap.add_argument('--episodes', action='store_true', help='write dev-derived node lessons, then re-judge the final groups with them')
    a = ap.parse_args()
    from grant_agent.laya_glance import TYPES, calibration_from_counts, transcriber_version
    from grant_agent.scene_core import admit_approximate
    from grant_agent.laya_glance import _vocabulary
    labels = load_labels()
    groups = sorted({surface_group(r['image']) for r in labels})
    final = final_holdout(groups)
    started = time.perf_counter()
    with ProcessPoolExecutor(a.workers) as pool:
        judged = list(pool.map(_judge, [r['image'] for r in labels], chunksize=4))
    wall = time.perf_counter() - started
    rows = []
    for lab, j in zip(labels, judged):
        rows.append({**lab, **j, 'group': surface_group(lab['image']), 'split': 'final' if surface_group(lab['image']) in final else 'dev'})
    dev = [r for r in rows if r['split'] == 'dev']
    fin = [r for r in rows if r['split'] == 'final']
    report = {'schema': 'neyvia.layag-eval.v1', 'transcriber': transcriber_version(), 'images': len(rows),
              'groups': {'dev': sorted(set(groups) - final), 'final': sorted(final)},
              'counts': {'dev': len(dev), 'final': len(fin)},
              'dev': metrics(dev, TYPES)}
    if a.show:
        for r in dev:
            f, y = a.show in r["fired"], bool(r["labels"].get(a.show))
            if f != y:
                hits = [b['text'] for b in r['bugs'] if b['type'] == a.show]
                print('FP' if f else 'FN', Path(r['image']).parent.name + '/' + Path(r['image']).name, hits[:3], (r['evidence'] or {}).get(a.show, '')[:120])
    # Calibration from dev only, then admission on the final groups.
    counts = {t: report['dev'][t] for t in TYPES}
    cal = calibration_from_counts({t: {k: counts[t][k] for k in ('tp', 'fp', 'tn', 'fn')} for t in TYPES})
    report['calibrationFromDev'] = {t: {'precisionLower': round(cal[t]['precisionLower'], 3), 'npvLower': round(cal[t]['npvLower'], 3)} for t in TYPES}
    rules = _vocabulary()
    if a.final:
        report['final'] = metrics(fin, TYPES)
        answered = correct = 0
        for r in fin:
            adm = admit_approximate([{'predicate': t} for t in r['fired']], rules, cal, 0.95)
            truth = any(r['labels'].get(t) for t in TYPES)
            if adm['admitted']:
                answered += 1
                correct += int(bool(r['fired']) == truth)
        report['finalAdmission'] = {'level': 0.95, 'answerRate': round(answered / len(fin), 3) if fin else None,
                                    'accuracyAdmitted': round(correct / answered, 3) if answered else None,
                                    'answered': answered, 'images': len(fin)}
    if a.episodes and a.final:
        report['episodes'], fin2 = episodes_run(dev, fin, TYPES)
        report['finalWithEpisodes'] = metrics(fin2, TYPES)
    ocr = [r['metrics']['ocrMs'] for r in rows]
    pix = [r['metrics']['pixelMs'] for r in rows]
    jm = [r['judgeMs'] for r in rows]
    tot = [r['metrics']['totalMs'] + r['judgeMs'] for r in rows]
    q = lambda v, p: round(sorted(v)[int(p * (len(v) - 1))], 1)
    report['latencyMs'] = {'ocrMedian': q(ocr, .5), 'pixelMedian': q(pix, .5), 'judgeMedian': round(statistics.median(jm), 2),
                           'glanceMedian': q(tot, .5), 'glanceP95': q(tot, .95), 'note': 'single process; cached scenes report their original timings'}
    report['wallSeconds'] = round(wall, 1)
    report['rows'] = [{k: r[k] for k in ('image', 'group', 'split', 'fired', 'labels', 'bugs')} for r in rows]
    out = ROOT / 'scripts/evidence/LAYAG-eval.json'
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
    show = {k: v for k, v in report.items() if k != 'rows'}
    print(json.dumps(show, indent=1))


if __name__ == '__main__':
    main()
