"""Grouped evaluation of LAYA lens sets on every labelled screenshot episode (plan 24).

Splits (surface groups, fixed by name hash before any lens exists):
  final  -- LAYAG's final holdout (laya_glance_eval.final_holdout); reported only, never used
            to choose, keep or retire a lens;
  check  -- ~40% of the remaining groups ('vision-check:' hash); the keep/retire decision;
  fit    -- the rest; the only groups whose examples a lens author (Luna) may see.
Practice episodes (injected defects, perfect labels) are their own group family and are
reported separately; they may feed calibration but not the check decision.

Usage: python scripts/vision_lens_eval.py [--lenses all-active|none|id,id] [--workers 6]
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from laya_glance_eval import load_labels, surface_group, final_holdout, _scene, metrics  # noqa: E402

BUDGET = {'lensMedianMs': 120.0, 'lensP95Ms': 400.0}
PRECISION_FLOOR = 0.90
# Minimum evidence (added 7 Oct after the first final-group report showed an encoded-path lens kept on
# 2 check positives halving final precision; disclosed in VISION receipts): a keep needs at least this
# many check-group positives of the predicate and a net gain of at least this many check screenshots.
MIN_CHECK_POSITIVES = 5
MIN_NET_GAIN = 2


def check_groups(groups):
    return {g for g in groups if int(hashlib.sha256(('vision-check:' + g).encode()).hexdigest()[:8], 16) % 10 < 4}


def labelled_rows(practice=None):
    labels = load_labels()
    groups = sorted({surface_group(r['image']) for r in labels})
    final = final_holdout(groups)
    check = check_groups(set(groups) - final)
    rows = []
    for r in labels:
        g = surface_group(r['image'])
        rows.append({**r, 'group': g, 'split': 'final' if g in final else 'check' if g in check else 'fit'})
    for p in practice or []:
        rows.append({**p, 'split': 'practice'})
    return rows


def _judge_with(args):
    image, lens_entries, raw_scene = args
    from grant_agent.laya_glance import glance
    from grant_agent.scene_core.lenses import override
    import copy
    scene = copy.deepcopy(raw_scene) if raw_scene is not None else _scene(image)
    with override(lens_entries):
        started = time.perf_counter()
        v = glance(scene, calibration={}, lessons={}, record=False)
        ms = (time.perf_counter() - started) * 1000
    lens_ms = (v.get('sceneMetrics') or {}).get('lensMs', {})
    return {'image': image, 'fired': sorted({b['type'] for b in v['bugs']}),
            'bugs': [{'type': b['type'], 'node': b['node'], 'text': (b['evidence'] or {}).get('attributes.text')} for b in v['bugs']],
            'lensMs': lens_ms, 'lensErrors': (v.get('sceneMetrics') or {}).get('lensErrors', {}), 'glanceMs': ms}


def judge_all(rows, lens_entries, workers=6):
    jobs = [(r['image'], lens_entries, r.get('scene')) for r in rows]
    if workers <= 1:
        return [_judge_with(j) for j in jobs]
    with ProcessPoolExecutor(workers) as pool:
        return list(pool.map(_judge_with, jobs, chunksize=4))


def evaluate(lens_entries, rows=None, workers=None):
    from grant_agent.laya_glance import TYPES
    rows = rows or labelled_rows()
    workers = workers or int(__import__("os").environ.get("VISION_WORKERS", "6"))
    judged = judge_all(rows, lens_entries, workers)
    merged = [{**r, **j} for r, j in zip(rows, judged)]
    report = {'lenses': [e['id'] for e in lens_entries], 'splits': {}}
    for split in ('fit', 'check', 'final', 'practice'):
        part = [r for r in merged if r['split'] == split]
        if part:
            report['splits'][split] = {'images': len(part), 'groups': len({r.get('group') for r in part}), 'types': metrics(part, TYPES)}
    cost = {}
    for e in lens_entries:
        values = [r['lensMs'][e['id']] for r in merged if e['id'] in r['lensMs']]
        errors = sum(1 for r in merged if e['id'] in r['lensErrors'])
        if values:
            v = sorted(values)
            cost[e['id']] = {'medianMs': round(statistics.median(v), 2), 'p95Ms': round(v[int(.95 * (len(v) - 1))], 2),
                             'errors': errors, 'images': len(values)}
        else:
            cost[e['id']] = {'medianMs': None, 'p95Ms': None, 'errors': errors, 'images': 0}
    report['cost'] = cost
    report['rows'] = [{k: r[k] for k in ('image', 'group', 'split', 'fired', 'labels', 'bugs')} for r in merged]
    return report


def accuracy(m):
    n = m['tp'] + m['fp'] + m['tn'] + m['fn']
    return (m['tp'] + m['tn']) / n if n else None


def decide(candidate_id, with_report, without_report, predicate):
    """Keep only if check-group accuracy for the lens's predicate strictly improves, its
    precision stays >= floor (or >= baseline when baseline is below the floor), no other
    predicate's check accuracy drops, and the lens fits the glance budget."""
    a = with_report['splits']['check']['types']
    b = without_report['splits']['check']['types']
    acc_with, acc_without = accuracy(a[predicate]), accuracy(b[predicate])
    p_with = a[predicate]['precision'] or 0.0
    p_base = b[predicate]['precision'] if b[predicate]['precision'] is not None else 1.0
    floor = min(PRECISION_FLOOR, p_base)
    others = {t: (accuracy(b[t]), accuracy(a[t])) for t in a if t != predicate and accuracy(a[t]) is not None
              and accuracy(a[t]) < accuracy(b[t]) - 1e-9}
    cost = with_report['cost'].get(candidate_id, {})
    within = cost.get('medianMs') is not None and cost['medianMs'] <= BUDGET['lensMedianMs'] and cost['p95Ms'] <= BUDGET['lensP95Ms'] and not cost.get('errors')
    reasons = []
    n = sum(a[predicate][k] for k in ('tp', 'fp', 'tn', 'fn'))
    gain = round((acc_with - acc_without) * n)
    if a[predicate]['positives'] < MIN_CHECK_POSITIVES or gain < MIN_NET_GAIN:
        reasons.append(f'insufficient check evidence for {predicate}: {a[predicate]["positives"]} positives (min {MIN_CHECK_POSITIVES}), '
                       f'net gain {gain} screenshots (min {MIN_NET_GAIN})')
    if not acc_with > acc_without:
        reasons.append(f'check accuracy for {predicate} did not improve ({acc_without:.3f} -> {acc_with:.3f})')
    if p_with < floor:
        reasons.append(f'check precision for {predicate} {p_with:.3f} below floor {floor:.2f}')
    if others:
        reasons.append('other predicates regressed: ' + ', '.join(others))
    if not within:
        reasons.append(f'cost {cost} outside budget {BUDGET}')
    return {'keep': not reasons, 'reasons': reasons or ['improves held-out check accuracy within budget'],
            'predicate': predicate, 'checkAccuracy': {'without': round(acc_without, 4), 'with': round(acc_with, 4)},
            'checkPrecision': {'without': b[predicate]['precision'], 'with': a[predicate]['precision']},
            'checkRecall': {'without': b[predicate]['recall'], 'with': a[predicate]['recall']},
            'checkPositives': a[predicate]['positives'], 'checkNetGain': gain,
            'cost': cost, 'budget': BUDGET}


def summary(report):
    out = {}
    for split, data in report['splits'].items():
        out[split] = {t: (v['precision'], v['recall'], v['positives']) for t, v in data['types'].items()}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lenses', default='all-active')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    from grant_agent.scene_core.lenses import load
    reg = [e for e in load()['lenses']]
    if a.lenses == 'all-active':
        chosen = [e for e in reg if e['status'] == 'active']
    elif a.lenses == 'none':
        chosen = []
    else:
        ids = a.lenses.split(',')
        chosen = [e for e in reg if e['id'] in ids]
    rows = labelled_rows()
    print(json.dumps({s: dict(Counter(r['split'] for r in rows))[s] for s in ('fit', 'check', 'final')}))
    print('groups', {s: sorted({r['group'] for r in rows if r['split'] == s}) for s in ('check', 'final')})
    rep = evaluate(chosen, rows, a.workers)
    print(json.dumps({'lenses': rep['lenses'], 'cost': rep['cost'], 'summary': summary(rep)}, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
