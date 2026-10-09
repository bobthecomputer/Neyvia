"""Plan 24 on 3D renders: the same look -> missing observable -> Luna lens -> held-out keep loop.

Input: D:/NeyviaRuns/VISION/render-practice/renders.json (scripts/vision_blender_practice.py:
12 subjects x 3 views x {clean, flipped-normals, floaters, wrong-scale}, faults made by LAYA,
so every render is a perfect episode). Subjects are the held-out unit:
  final (3 subjects, reported only) | check (3, keep/retire decisions) | fit (6, author examples).
Renders arrive in a fixed hash order; each is answered by calibrated render lenses, by look
memory, or by one model look (gpt-6-luna via codex exec), which is written as an episode.

Usage: python scripts/vision_render_run.py --run D:/NeyviaRuns/VISION/render-1 [--window 24] [--cap 200]
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
RENDERS = Path('D:/NeyviaRuns/VISION/render-practice/renders.json')


def rows_with_splits(path=RENDERS):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    subjects = sorted({r['subject'] for r in data['renders']}, key=lambda s: hashlib.sha256(('vision-render:' + s).encode()).hexdigest())
    final, check = set(subjects[:3]), set(subjects[3:6])
    out = []
    for r in data['renders']:
        out.append({**r, 'group': r['subject'], 'split': 'final' if r['subject'] in final else 'check' if r['subject'] in check else 'fit'})
    return out


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


def evaluate(lens_entries, rows):
    from grant_agent.laya_vision_render import glance, TYPES
    from grant_agent.scene_core.lenses import override
    merged, timings, errors = [], {}, Counter()
    with override(lens_entries):
        for r in rows:
            v = glance(r)
            for k, ms in (v['scene'].get('metrics', {}).get('lensMs') or {}).items():
                timings.setdefault(k, []).append(ms)
            for k in (v['scene'].get('metrics', {}).get('lensErrors') or {}):
                errors[k] += 1
            merged.append({**r, 'fired': v['fired'], 'bugs': [{'type': f['predicate'], 'node': f['node'], 'text': ''} for f in v['findings']]})
    report = {'lenses': [e['id'] for e in lens_entries], 'splits': {}}
    for split in ('fit', 'check', 'final'):
        part = [r for r in merged if r['split'] == split]
        report['splits'][split] = {'images': len(part), 'groups': len({r['group'] for r in part}), 'types': metrics(part, TYPES)}
    report['cost'] = {}
    for e in lens_entries:
        v = sorted(timings.get(e['id'], []))
        report['cost'][e['id']] = {'medianMs': round(statistics.median(v), 2) if v else None,
                                   'p95Ms': round(v[int(.95 * (len(v) - 1))], 2) if v else None, 'errors': errors[e['id']], 'images': len(v)}
    report['rows'] = [{k: r[k] for k in ('image', 'group', 'split', 'fired', 'labels', 'bugs')} for r in merged]
    return report


def calibration(report):
    from grant_agent.laya_glance import calibration_from_counts
    from grant_agent.laya_vision_render import TYPES
    counts = {t: {k: sum(report['splits'][s]['types'][t][k] for s in ('fit', 'check')) for k in ('tp', 'fp', 'tn', 'fn')} for t in TYPES}
    return calibration_from_counts(counts), counts


def examples_for(defect, rows, report):
    fired = {r['image']: set(r['fired']) for r in report['rows']}
    pos = [r for r in rows if r['split'] == 'fit' and r['labels'][defect] and defect not in fired[r['image']]]
    neg = [r for r in rows if r['split'] == 'fit' and r['condition'] == 'clean']
    key = lambda r: hashlib.sha256(r['image'].encode()).hexdigest()
    pos.sort(key=key); neg.sort(key=key)
    picked = pos[:3] + neg[:1]
    ex = [{'image': i + 1, 'label': 'fault' if r['labels'][defect] else 'no fault', 'type': defect, 'view': r['view'],
           'expectedHeightM': r['expectedHeightM'], 'subject': r['subject'], 'detail': r.get('detail')} for i, r in enumerate(picked)]
    return ex, [r['image'] for r in picked], {'fitPositivesMissed': len(pos), 'fitNegatives': len(neg)}


def attempt(observable, *, run, log, rows, baseline, active_entries, max_calls=4):
    from grant_agent.laya_vision import author_lens
    from grant_agent.laya_vision_render import SPEC
    from grant_agent.scene_core.lenses import validate_source, validate_entry
    from vision_lens_eval import decide, accuracy
    defect = observable['type']
    examples, images, pool = examples_for(defect, rows, baseline)
    programs = Path(run) / 'lens_programs'
    programs.mkdir(parents=True, exist_ok=True)
    history, feedback, best = [], None, None
    for call in range(max_calls):
        try:
            entry, source, receipt = author_lens(observable, examples, images, root=run, log=log, feedback=feedback, spec=SPEC)
        except Exception as exc:
            history.append({'call': call, 'error': type(exc).__name__ + ': ' + str(exc)[:300]})
            if 'cap' in str(exc) or 'hold' in str(exc):
                break
            continue
        step = {'call': call, 'authorReceipt': receipt, 'lens': entry['id']}
        history.append(step)
        try:
            validate_source(source)
            path = programs / f"{entry['id']}-{call}-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:8]}.py"
            path.write_text(source, encoding='utf-8')
            entry.update(program=str(path), programSha256=hashlib.sha256(source.encode('utf-8')).hexdigest(), status='candidate')
            validate_entry(entry)
            report = evaluate(active_entries + [entry], rows)
        except Exception as exc:
            feedback = f'{type(exc).__name__}: {str(exc)[:600]}'
            step['rejectedBeforeEvaluation'] = feedback
            continue
        p = entry['branch']['predicate']
        fit_m = report['splits']['fit']['types'][p]
        step['fit'] = fit_m
        step['cost'] = report['cost'].get(entry['id'])
        if step['cost'] and step['cost']['errors']:
            feedback = f"The program raised errors on {step['cost']['errors']} renders."
            continue
        if best is None or (accuracy(fit_m) or 0) > (accuracy(best[2]['splits']['fit']['types'][p]) or 0):
            best = (entry, source, report)
        base_fit = baseline['splits']['fit']['types'][p]
        if (fit_m['precision'] or 0) >= 0.9 and (accuracy(fit_m) or 0) > (accuracy(base_fit) or 0):
            break
        fps = [Path(r['image']).name for r in report['rows'] if r['split'] == 'fit' and p in r['fired'] and not r['labels'][p]][:5]
        fns = [Path(r['image']).name for r in report['rows'] if r['split'] == 'fit' and r['labels'][p] and p not in r['fired']][:5]
        feedback = (f'On fit renders {p}: precision {fit_m["precision"]}, recall {fit_m["recall"]} (tp {fit_m["tp"]}, fp {fit_m["fp"]}, '
                    f'fn {fit_m["fn"]}). False alarms: {fps}. Missed: {fns}. Raise precision first, then recall. The attached '
                    'images are now renders where YOUR program was wrong (see examples). Edit your previous program:\n```python\n'
                    + source[:12000] + '\n```')
        by_name = {Path(r['image']).name: r for r in rows}
        fail = [(n, 'false alarm (no ' + p + ' here)') for n in fps[:2]] + [(n, 'missed ' + p) for n in fns[:2]]
        if fail:
            examples = [{'image': i + 1, 'label': why, 'type': p, 'view': by_name[n]['view'], 'subject': by_name[n]['subject'],
                         'expectedHeightM': by_name[n]['expectedHeightM'], 'detail': by_name[n].get('detail')} for i, (n, why) in enumerate(fail)]
            images = [by_name[n]['image'] for n, _ in fail]
    receipt = {'schema': 'neyvia.laya.lens-decision.v1', 'domain': 'render3d', 'observable': observable, 'examples': examples,
               'examplePool': pool, 'history': history, 'at': time.strftime('%Y-%m-%dT%H:%M:%S')}
    if best is None:
        receipt['decision'] = {'keep': False, 'reasons': ['no candidate lens survived validation and evaluation']}
        return receipt, None
    entry, source, report = best
    p = entry['branch']['predicate']
    decision = decide(entry['id'], report, baseline, p)
    receipt.update(lens=entry, decision=decision,
                   finalReportOnly={'with': report['splits']['final']['types'][p], 'without': baseline['splits']['final']['types'][p]},
                   fitWith=report['splits']['fit']['types'][p], fitWithout=baseline['splits']['fit']['types'][p])
    entry['status'] = 'active' if decision['keep'] else 'rejected'
    entry['decision'] = {'status': entry['status'], 'reasons': decision['reasons'], 'checkAccuracy': decision['checkAccuracy'],
                         'cost': decision['cost'], 'at': receipt['at']}
    entry['cost'] = decision['cost']
    return receipt, (entry, report)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--window', type=int, default=24)
    ap.add_argument('--cap', type=int, default=200)
    ap.add_argument('--min-looks', type=int, default=2)
    ap.add_argument('--stream', default=str(RENDERS), help='renders.json arriving in this run')
    ap.add_argument('--eval', nargs='*', default=None, help='stored labelled renders for decisions and calibration (default: the stream set)')
    ap.add_argument('--start-registry', default='', help='begin with the lens registry of an earlier run')
    a = ap.parse_args()
    run = Path(a.run)
    run.mkdir(parents=True, exist_ok=True)
    os.environ['NEYVIA_LAYA_LENSES'] = str(run / 'lenses.json')
    if not (run / 'lenses.json').exists():
        start = json.loads(Path(a.start_registry).read_text(encoding='utf-8')) if a.start_registry else {'schema': 'neyvia.laya.lenses.v1', 'lenses': []}
        (run / 'lenses.json').write_text(json.dumps(start, indent=1), encoding='utf-8')
    from grant_agent.laya_vision import LookLog, look, remember, recall, BudgetExhausted
    from grant_agent.laya_vision_render import glance, SPEC, TYPES, LOOK_DOMAIN
    from grant_agent.scene_core import lenses as L
    from vision_evolve import cluster_missing, write_receipt
    from vision_stream import window_stats, answer_record as _ui_answer  # noqa: F401
    stream_rows = rows_with_splits(a.stream)
    rows = [r for path in (a.eval or [a.stream]) for r in rows_with_splits(path)]  # stored labelled episodes
    order = sorted(range(len(stream_rows)), key=lambda i: hashlib.sha256(('vision-render-stream:' + stream_rows[i]['image']).encode()).hexdigest())
    state_path = run / 'state.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'next': 0, 'records': [], 'events': [], 'attempted': {}, 'windowsDone': 0}
    log = LookLog(run / 'model-calls.jsonl', cap_looks=a.cap)
    active = lambda: [e for e in L.load()['lenses'] if e['status'] == 'active']
    current = evaluate(active(), rows)
    cal, counts = calibration(current)
    state['events'].append({'event': 'calibrate', 'position': state['next'], 'lenses': [e['id'] for e in active()],
                            'precisionLower': {t: round(v['precisionLower'], 3) for t, v in cal.items()},
                            'npvLower': {t: round(v['npvLower'], 3) for t, v in cal.items()}})
    # Look memory radius: renders of different faults on one subject are near-identical in CLIP,
    # so memory is enabled only if dev renders show a radius with >= 0.95 per-type agreement.
    import numpy as np
    from grant_agent.taste_vision import embedding
    E = np.asarray([embedding(Path(r['image']), cache_root=Path('D:/NeyviaRuns/laya-train/vision/embeddings')) for r in rows], dtype=np.float32)
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    dev = [i for i, r in enumerate(rows) if r['split'] != 'final']
    S = E[dev] @ E[dev].T
    np.fill_diagonal(S, -1)
    Y = np.asarray([[rows[i]['labels'][t] for t in TYPES] for i in dev])
    nn, sim = S.argmax(1), S.max(1)
    radius, table = None, []
    for th in (0.95, 0.97, 0.98, 0.99, 0.995, 0.998):
        m = sim >= th
        n = int(m.sum()) * len(TYPES)
        k = int((Y[m] == Y[nn[m]]).sum())
        lower = k / (n + 1) if n else 0
        table.append({'radius': th, 'pairs': int(m.sum()), 'perTypeAgreementLower': round(lower, 4)})
        if radius is None and n and lower >= 0.95:
            radius = th
    state.update(radius=radius, radiusTable=table)
    looks_dir = run / 'looks'
    looks_dir.mkdir(exist_ok=True)
    looks_done = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(looks_dir.glob('*.json'))]
    while state['next'] < len(order):
        r = stream_rows[order[state['next']]]
        v = glance(r, calibration=cal)
        truth = {t: int(r['labels'][t]) for t in TYPES}
        rec = {'image': r['image'], 'group': r['group'], 'split': r['split'], 'truthBroken': any(truth.values()), 'truth': truth}
        if v['admitted']:
            rec.update(by='lenses', answerBroken=bool(v['fired']), answerTypes={t: int(t in v['fired']) for t in TYPES})
        else:
            hit = recall(run, r['image'], radius=radius, domain=LOOK_DOMAIN) if radius else None
            if hit:
                rec.update(by='memory', answerBroken=hit['verdict'] == 'broken', answerTypes=hit['types'], similarity=hit['similarity'])
            else:
                sha = hashlib.sha256(Path(r['image']).read_bytes()).hexdigest()
                cached = looks_dir / (sha[:24] + '.json')
                try:
                    if cached.exists():
                        result = json.loads(cached.read_text(encoding='utf-8'))
                    else:
                        result = look(r['image'], v['scene'], v, root=run, log=log, spec=SPEC)
                        result.update(image=r['image'], split=r['split'])
                        cached.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
                        remember(run, r['image'], v['scene'], result, surface=r['group'], domain=LOOK_DOMAIN, lessons=False)
                        looks_done.append(result)
                    ans = result['answer']
                    rec.update(by='look', answerBroken=None if ans['verdict'] == 'unsure' else ans['verdict'] == 'broken',
                               answerTypes=ans['types'], missing=[m['name'] for m in ans['missing']], tokens=result.get('tokens'))
                except BudgetExhausted as exc:
                    rec.update(by='unanswered', answerBroken=None, answerTypes=None, reason=str(exc))
        rec['verdictCorrect'] = None if rec['answerBroken'] is None else rec['answerBroken'] == rec['truthBroken']
        if rec.get('answerTypes') is not None:
            rec['typeAgreement'] = sum(int(rec['answerTypes'].get(t, 0)) == truth[t] for t in TYPES) / len(TYPES)
        state['records'].append(rec)
        state['next'] += 1
        print(f"{state['next']:4d} {rec['by']:8s} {rec['split']:6s} ok={rec['verdictCorrect']} {Path(r['image']).name}", flush=True)
        if state['next'] % a.window == 0 or state['next'] == len(order):
            state['windowsDone'] += 1
            clusters = cluster_missing(looks_done)
            fit_recall = {t: (v_['recall'] if v_['recall'] is not None else 1.0) for t, v_ in current['splits']['fit']['types'].items()}
            clusters.sort(key=lambda c: (fit_recall.get(c['type'], 1.0), -c['looks']))
            state['missingClusters'] = clusters[:10]
            adopted = {e['branch']['predicate'] for e in active()}
            for c in clusters:
                tries = state['attempted'].get(c['type'], 0)
                seen_looks = state.setdefault('looksAtAttempt', {}).get(c['type'], 0)
                if c['looks'] < a.min_looks or tries >= 3 or c['type'] in adopted or (tries and c['looks'] <= seen_looks):
                    continue
                state['looksAtAttempt'][c['type']] = c['looks']
                state['attempted'][c['type']] = tries + 1
                obs = {k: c[k] for k in ('type', 'name', 'names', 'descriptions', 'measures', 'looks')}
                receipt, kept = attempt(obs, run=run, log=log, rows=rows, baseline=current, active_entries=active())
                path = write_receipt(receipt, f"{run.name}-w{state['windowsDone']}-{c['type']}-{c['name']}"[:120])
                if kept:
                    entry, report = kept
                    entry['decision']['receipt'] = str(path)
                    reg = L.load(); reg['lenses'].append(entry); L.save(reg)
                    if entry['status'] == 'active':
                        current = evaluate(active(), rows)
                        if len(active()) >= 2:  # retire pass: ablation on CHECK subjects
                            from vision_lens_eval import accuracy
                            ablation = []
                            for e in active():
                                without = evaluate([x for x in active() if x['id'] != e['id']], rows)
                                p_ = e['branch']['predicate']
                                aw, ao = accuracy(current['splits']['check']['types'][p_]), accuracy(without['splits']['check']['types'][p_])
                                ablation.append({'lens': e['id'], 'predicate': p_, 'checkAccuracyWith': round(aw, 4),
                                                 'checkAccuracyWithout': round(ao, 4), 'contributes': aw > ao})
                            state['events'].append({'event': 'retire-pass', 'position': state['next'], 'ablation': ablation})
                            reg = L.load()
                            for row in ablation:
                                for e in reg['lenses']:
                                    if e['id'] == row['lens'] and e['status'] == 'active' and not row['contributes']:
                                        e['status'] = 'retired'
                                        e['decision'] = {**e.get('decision', {}), 'status': 'retired', 'retiredAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                                         'retireReason': 'ablation on check subjects: no accuracy contribution', 'ablation': row}
                            L.save(reg)
                            current = evaluate(active(), rows)
                        cal, counts = calibration(current)
                        state['events'].append({'event': 'calibrate', 'position': state['next'], 'lenses': [e['id'] for e in active()],
                                                'precisionLower': {t: round(v_['precisionLower'], 3) for t, v_ in cal.items()},
                                                'npvLower': {t: round(v_['npvLower'], 3) for t, v_ in cal.items()}})
                state['events'].append({'event': 'lens-decision', 'position': state['next'], 'observable': c['type'] + ':' + c['name'],
                                        'lens': kept[0]['id'] if kept else None, 'status': kept[0]['status'] if kept else 'no-candidate',
                                        'receipt': str(path), 'reasons': receipt['decision']['reasons']})
                break
            state['windows'] = window_stats(state['records'], a.window)
            print(json.dumps(state['windows'][-1]), flush=True)
        state_path.write_text(json.dumps(state, indent=1, default=str), encoding='utf-8')
    state['windows'] = window_stats(state['records'], a.window)
    state['finalReport'] = {s: current['splits'][s] for s in ('fit', 'check', 'final')}
    state_path.write_text(json.dumps(state, indent=1, default=str), encoding='utf-8')
    print(json.dumps({'windows': state['windows'], 'events': [e for e in state['events'] if e['event'] != 'calibrate']}, indent=1, default=str))


if __name__ == '__main__':
    main()
