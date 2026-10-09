"""VISION2 (plan 27 §7): should the OCR second pass be on by default? Measured, with a rule fixed in advance.

Judges every labelled capture twice -- second pass off and on (NEYVIA_LAYA_OCR_SECOND_PASS, read at import
in each worker process) -- with the active lens set, exactly as scripts/vision_lens_eval.py judges them:
  * the 495 plan-24 episodes in their fit / check / final splits (final = the OLD held-out, contaminated for
    the lens types decided while it was read; reported, not used to decide);
  * the NEW held-out split (scripts/vision2_new_split.py, blind labels in
    scripts/evidence/VISION2-new-split-labels.json): 'unseen-surface' and 'unseen-capture', and both together.

Decision rule (written and committed BEFORE the new split was judged by any version of the glance):
  ON by default only if, on the NEW split (both kinds together),
    R1 recall gain: summed true positives over encoded-path + internal-id + raw-error is strictly higher with
       the second pass, and no one of those three loses recall;
    R2 no precision collapse: for every type, precision with the second pass is >= precision without minus
       0.05, and never below 0.90 where it was >= 0.90 without (types with no firing on either side pass);
    R3 latency: median added second-pass time <= 250 ms and p95 <= 1500 ms per screenshot (cold, fresh scenes
       of the new split; the first OCR call per worker includes engine creation).
  Otherwise it stays opt-in. The same numbers are reported for the old splits.

Admission (what an answer costs): with calibration counts from the 495 episodes judged the same way, the
share of new-split screenshots the glance answers at the 0.95 level, and the accuracy of those answers.

Usage: python scripts/vision2_ocr_decision.py [--workers 4] [--out scripts/evidence/VISION2-ocr-decision.json]
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from laya_glance_eval import metrics, _scene  # noqa: E402
from vision_lens_eval import labelled_rows  # noqa: E402

NEW_LABELS = ROOT / 'scripts/evidence/VISION2-new-split-labels.json'
TEXT_TYPES = ('encoded-path', 'internal-id', 'raw-error')
RULE = {'precisionDrop': 0.05, 'precisionFloor': 0.90, 'medianMs': 250.0, 'p95Ms': 1500.0}


def _judge(args):
    image, lens_entries = args
    from grant_agent.laya_glance import glance
    from grant_agent.scene_core.lenses import override
    scene = _scene(image)
    with override(lens_entries):
        v = glance(scene, calibration={}, lessons={}, record=False)
    m = scene.get('metrics', {})
    return {'image': image, 'fired': sorted({b['type'] for b in v['bugs']}),
            'bugs': [{'type': b['type'], 'text': (b['evidence'] or {}).get('attributes.text')} for b in v['bugs']],
            'secondPassMs': m.get('secondPassMs'), 'totalMs': m.get('totalMs'), 'crops': m.get('secondPassCrops')}


def judge(rows, lens_entries, second, workers):
    os.environ['NEYVIA_LAYA_OCR_SECOND_PASS'] = '1' if second else '0'  # explicit both ways (default is on since VISION2)
    with ProcessPoolExecutor(workers) as pool:  # fresh workers: the flag is read at import
        return list(pool.map(_judge, [(r['image'], lens_entries) for r in rows], chunksize=4))


def q(values, p):
    v = sorted(x for x in values if x is not None)
    return round(v[int(p * (len(v) - 1))], 1) if v else None


def admission(rows, fired_key, cal):
    from grant_agent.laya_glance import TYPES, _vocabulary
    from grant_agent.scene_core import admit_approximate
    rules = _vocabulary()
    answered = correct = 0
    for r in rows:
        adm = admit_approximate([{'predicate': t} for t in r[fired_key]], rules, cal, 0.95)
        if adm['admitted']:
            answered += 1
            correct += int(bool(r[fired_key]) == any(r['labels'].get(t) for t in TYPES))
    return {'answerRate': round(answered / len(rows), 3), 'accuracyAdmitted': round(correct / answered, 3) if answered else None,
            'answered': answered, 'images': len(rows)}


def decide(off, on, types):
    reasons, ok = [], True
    tp_off = sum(off[t]['tp'] for t in TEXT_TYPES)
    tp_on = sum(on[t]['tp'] for t in TEXT_TYPES)
    lost = [t for t in TEXT_TYPES if on[t]['tp'] < off[t]['tp']]
    r1 = tp_on > tp_off and not lost
    reasons.append(f'R1 text-type true positives {tp_off} -> {tp_on}' + (f'; recall lost on {lost}' if lost else ''))
    bad = []
    for t in types:
        p0, p1 = off[t]['precision'], on[t]['precision']
        if p1 is None:
            continue
        base = p0 if p0 is not None else 1.0
        if p1 < base - RULE['precisionDrop'] or (base >= RULE['precisionFloor'] and p1 < RULE['precisionFloor']):
            bad.append(f'{t} {p0}->{p1}')
    r2 = not bad
    reasons.append('R2 precision ' + ('held on every type' if r2 else 'dropped: ' + ', '.join(bad)))
    return r1, r2, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--out', default=str(ROOT / 'scripts/evidence/VISION2-ocr-decision.json'))
    a = ap.parse_args()
    from grant_agent.laya_glance import TYPES, calibration_from_counts
    from grant_agent.scene_core.lenses import load
    lenses = [e for e in load()['lenses'] if e['status'] == 'active']
    old = labelled_rows()
    new = [{**r, 'split': 'new-' + r['kind']} for r in json.loads(NEW_LABELS.read_text(encoding='utf-8'))['rows']]
    rows = old + new
    out = {'schema': 'neyvia.vision2.ocr-decision.v1', 'lenses': [e['id'] for e in lenses], 'rule': RULE,
           'images': {'old': len(old), 'new': len(new)}}
    started = time.perf_counter()
    judged = {}
    for second in (False, True):
        judged[second] = judge(rows, lenses, second, a.workers)
    out['wallSeconds'] = round(time.perf_counter() - started, 1)
    for r, j0, j1 in zip(rows, judged[False], judged[True]):
        r['off'], r['on'] = j0['fired'], j1['fired']
        r['bugsOff'], r['bugsOn'] = j0['bugs'], j1['bugs']
        r['secondPassMs'], r['crops'], r['totalMsOn'], r['totalMsOff'] = j1['secondPassMs'], j1['crops'], j1['totalMs'], j0['totalMs']
    splits = {}
    for name, part in (('fit', [r for r in rows if r['split'] == 'fit']), ('check', [r for r in rows if r['split'] == 'check']),
                       ('old-final', [r for r in rows if r['split'] == 'final']),
                       ('new-unseen-surface', [r for r in rows if r['split'] == 'new-unseen-surface']),
                       ('new-unseen-capture', [r for r in rows if r['split'] == 'new-unseen-capture']),
                       ('new', new)):
        off = metrics([{**r, 'fired': r['off']} for r in part], TYPES)
        on = metrics([{**r, 'fired': r['on']} for r in part], TYPES)
        splits[name] = {'images': len(part), 'surfaces': len({r.get('surface', r.get('group')) for r in part}),
                        'off': off, 'on': on}
    out['splits'] = splits
    # Calibration from the 495 episodes under each setting, then admission on the new split.
    cal = {}
    for key in ('off', 'on'):
        m = metrics([{**r, 'fired': r[key]} for r in old], TYPES)
        cal[key] = calibration_from_counts({t: {k: m[t][k] for k in ('tp', 'fp', 'tn', 'fn')} for t in TYPES})
    out['admissionNew'] = {key: admission(new, key, cal[key]) for key in ('off', 'on')}
    sp = [r['secondPassMs'] for r in new]
    out['latencyNew'] = {'secondPassMedianMs': q(sp, .5), 'secondPassP95Ms': q(sp, .95), 'cropsMean': round(statistics.mean(r['crops'] or 0 for r in new), 2),
                         'transcribeMedianOffMs': q([r['totalMsOff'] for r in new], .5),
                         'note': 'secondPassMs is the added time, measured inside the transcription of fresh scenes (first transcription '
                                 'of these captures; crop OCR not memoised yet); cold workers include OCR engine creation. The "on" '
                                 'transcription reuses the first-pass OCR memo of the "off" run, so whole-transcription times are not compared.'}
    r1, r2, reasons = decide(splits['new']['off'], splits['new']['on'], TYPES)
    r3 = (out['latencyNew']['secondPassMedianMs'] or 0) <= RULE['medianMs'] and (out['latencyNew']['secondPassP95Ms'] or 0) <= RULE['p95Ms']
    reasons.append(f"R3 latency median {out['latencyNew']['secondPassMedianMs']} ms, p95 {out['latencyNew']['secondPassP95Ms']} ms")
    out['decision'] = {'onByDefault': bool(r1 and r2 and r3), 'R1': r1, 'R2': r2, 'R3': r3, 'reasons': reasons}
    out['rows'] = [{k: r.get(k) for k in ('image', 'split', 'surface', 'labels', 'off', 'on', 'bugsOff', 'bugsOn', 'secondPassMs')} for r in rows]
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
    show = {k: v for k, v in out.items() if k not in ('rows', 'splits')}
    show['summary'] = {s: {t: [d['off'][t]['precision'], d['off'][t]['recall'], '->', d['on'][t]['precision'], d['on'][t]['recall'], d['on'][t]['positives']]
                           for t in TYPES} for s, d in splits.items()}
    print(json.dumps(show, indent=1))


if __name__ == '__main__':
    main()
