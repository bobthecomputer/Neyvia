"""Plan 24 proof run: a stream of labelled screenshots arriving over time.

For each screenshot LAYA answers in the cheapest admissible way:
  1. lenses   -- pixel glance with the active lenses, admitted through calibration at 0.95;
  2. memory   -- an earlier model look on a near-identical screenshot (CLIP cosine >= radius,
                 radius calibrated on dev labels only);
  3. look     -- the one model look (gpt-6-luna via codex exec), written at once as
                 episodes (look memory + node lessons); its missing observables queue up.
After every window: the most-named missing observable becomes a Luna-written candidate lens
(fit-group examples), kept only if CHECK-group accuracy improves within the glance budget;
kept lenses re-calibrate admission; an ablation pass retires lenses that stop contributing.
Optional self-made practice episodes (scripts/vision_practice.py) join calibration at a
declared window.

Model looks are capped at 200 per run; every call is logged (model-calls.jsonl).
Resumable: state.json holds the position; looks are cached per screenshot hash.

Usage: python scripts/vision_stream.py --run D:/NeyviaRuns/VISION/stream-1 [--window 45] [--limit N]
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]


def load_state(run):
    p = run / 'state.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'next': 0, 'records': [], 'events': [], 'windowsDone': 0,
                                                                         'attempted': {}}


def save_state(run, state):
    tmp = run / 'state.json.tmp'
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    tmp.replace(run / 'state.json')


def calibration_for(report, practice_counts=None):
    """Per-type counts of the pixel glance on labelled DEV episodes (fit+check) [+ practice]."""
    from grant_agent.laya_glance import TYPES, calibration_from_counts
    counts = {t: {k: 0 for k in ('tp', 'fp', 'tn', 'fn')} for t in TYPES}
    for split in ('fit', 'check'):
        for t in TYPES:
            for k in counts[t]:
                counts[t][k] += report['splits'][split]['types'][t][k]
    for t, c in (practice_counts or {}).items():
        for k in counts[t]:
            counts[t][k] += c.get(k, 0)
    return calibration_from_counts(counts), counts


def recall_radius(rows, clip):
    """Smallest CLIP cosine at which an earlier labelled DEV screenshot's per-type labels agree
    with the new one at a conservative >= 0.95 (k/(n+1) over type decisions)."""
    import numpy as np
    from grant_agent.laya_glance import TYPES
    dev = [i for i, r in enumerate(rows) if r['split'] in ('fit', 'check')]
    E = clip[dev]
    S = E @ E.T
    np.fill_diagonal(S, -1)
    Y = np.asarray([[rows[i]['labels'].get(t, 0) for t in TYPES] for i in dev])
    nn, sim = S.argmax(1), S.max(1)
    table = []
    chosen = None
    for th in (0.95, 0.96, 0.97, 0.98, 0.985, 0.99, 0.993, 0.995, 0.997):
        m = sim >= th
        n = int(m.sum()) * len(TYPES)
        k = int((Y[m] == Y[nn[m]]).sum())
        lower = k / (n + 1) if n else 0
        table.append({'radius': th, 'pairs': int(m.sum()), 'perTypeAgreementLower': round(lower, 4),
                      'exactAgreement': round(float((Y[m] == Y[nn[m]]).all(1).mean()), 3) if m.any() else None})
        if chosen is None and lower >= 0.95:
            chosen = th
    return chosen or 0.997, table


def clip_matrix(rows, cache):
    import numpy as np
    from grant_agent.taste_vision import embedding
    if cache.exists():
        data = np.load(cache)
        if data.shape[0] == len(rows):
            return data
    E = np.asarray([embedding(Path(r['image']), cache_root=Path('D:/NeyviaRuns/laya-train/vision/embeddings')) for r in rows], dtype=np.float32)
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    np.save(cache, E)
    return E


def answer_record(r, by, types_answer, broken_answer, extra=None):
    from grant_agent.laya_glance import TYPES
    truth = {t: int(r['labels'].get(t, 0)) for t in TYPES}
    truth_broken = any(truth.values())
    rec = {'image': r['image'], 'group': r['group'], 'split': r['split'], 'by': by, 'truthBroken': truth_broken,
           'answerBroken': broken_answer, 'verdictCorrect': None if broken_answer is None else broken_answer == truth_broken,
           'answerTypes': types_answer, 'truth': truth}
    if types_answer is not None and by in ('look', 'memory'):
        rec['typeAgreement'] = sum(int(types_answer.get(t, 0)) == truth[t] for t in TYPES) / len(TYPES)
    if extra:
        rec.update(extra)
    return rec


def window_stats(records, size):
    out = []
    for i in range(0, len(records), size):
        w = records[i:i + size]
        c = Counter(r['by'] for r in w)
        answered = [r for r in w if r['verdictCorrect'] is not None]
        out.append({'window': i // size, 'images': len(w), 'lenses': c['lenses'], 'memory': c['memory'], 'look': c['look'],
                    'unanswered': c['unanswered'], 'lookRate': round(c['look'] / len(w), 3),
                    'localRate': round((c['lenses'] + c['memory']) / len(w), 3),
                    'verdictAccuracy': round(sum(r['verdictCorrect'] for r in answered) / len(answered), 3) if answered else None})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--window', type=int, default=45)
    ap.add_argument('--limit', type=int, default=0, help='stop after this many images (resume later)')
    ap.add_argument('--cap', type=int, default=200)
    ap.add_argument('--min-looks', type=int, default=3, help='looks naming an observable before a lens is written')
    ap.add_argument('--practice', default='', help='practice episodes json (scripts/vision_practice.py)')
    ap.add_argument('--practice-window', type=int, default=4)
    ap.add_argument('--practice-calibration', action='store_true',
                    help='also add practice region counts to admission calibration (stream-1 did; it mixes synthetic '
                         'region-level counts into image-level bounds, so it is off by default)')
    ap.add_argument('--replay-looks', default='', help='earlier run looks/ dir: an identical screenshot reuses that look')
    ap.add_argument('--no-authoring', action='store_true')
    a = ap.parse_args()
    run = Path(a.run)
    run.mkdir(parents=True, exist_ok=True)
    os.environ['NEYVIA_LAYA_LENSES'] = str(run / 'lenses.json')
    if not (run / 'lenses.json').exists():
        (run / 'lenses.json').write_text(json.dumps({'schema': 'neyvia.laya.lenses.v1', 'lenses': []}), encoding='utf-8')
    from grant_agent.laya_glance import glance, transcribe, _node_lessons
    from grant_agent.laya_vision import LookLog, look, remember, recall, BudgetExhausted
    from grant_agent.scene_core import lenses as L
    from vision_lens_eval import labelled_rows, evaluate, summary
    from vision_evolve import cluster_missing, attempt, retire_pass, write_receipt
    from laya_glance_eval import _scene

    rows = labelled_rows()
    order = sorted(range(len(rows)), key=lambda i: hashlib.sha256(('vision-stream:' + rows[i]['image']).encode()).hexdigest())
    clip = clip_matrix(rows, run / 'clip.npy')
    radius, radius_table = recall_radius(rows, clip)
    state = load_state(run)
    state.update(radius=radius, radiusTable=radius_table, window=a.window, order='sha256(vision-stream:image)')
    log = LookLog(run / 'model-calls.jsonl', cap_looks=a.cap)
    looks_dir = run / 'looks'
    looks_dir.mkdir(exist_ok=True)

    def active_entries():
        return [e for e in L.load()['lenses'] if e['status'] == 'active']

    practice_counts = None
    practice = json.loads(Path(a.practice).read_text(encoding='utf-8')) if a.practice and Path(a.practice).exists() else None

    def recalibrate(reason):
        nonlocal practice_counts
        report = evaluate(active_entries(), rows)
        if practice and state.get('practiceJoined') and a.practice_calibration:
            practice_counts = practice_calibration(practice, active_entries())
        cal, counts = calibration_for(report, practice_counts)
        state['events'].append({'at': time.strftime('%H:%M:%S'), 'position': state['next'], 'event': 'calibrate', 'reason': reason,
                                'lenses': [e['id'] for e in active_entries()],
                                'precisionLower': {t: round(v['precisionLower'], 3) for t, v in cal.items()},
                                'npvLower': {t: round(v['npvLower'], 3) for t, v in cal.items()},
                                'practice': bool(practice_counts)})
        return cal, report

    cal, current = recalibrate('start')
    looks_done = []
    for p in sorted(looks_dir.glob('*.json')):
        looks_done.append(json.loads(p.read_text(encoding='utf-8')))
    processed = 0
    while state['next'] < len(order):
        if a.limit and processed >= a.limit:
            break
        r = rows[order[state['next']]]
        raw = _scene(r['image'])
        lessons = _node_lessons(run)
        v = glance(raw, calibration=cal, lessons=lessons, record=False)
        if v['admitted']:
            types = {b['type']: 1 for b in v['bugs']}
            rec = answer_record(r, 'lenses', types, bool(v['bugs']), {'fired': sorted(types), 'lessons': len(v.get('lessons') or [])})
        else:
            hit = recall(run, r['image'], radius=radius)
            if hit:
                rec = answer_record(r, 'memory', hit['types'], hit['verdict'] == 'broken', {'similarity': hit['similarity']})
            else:
                sha = hashlib.sha256(Path(r['image']).read_bytes()).hexdigest()
                cached = looks_dir / (sha[:24] + '.json')
                replay = Path(a.replay_looks) / (sha[:24] + '.json') if a.replay_looks else None
                try:
                    if cached.exists():
                        result = json.loads(cached.read_text(encoding='utf-8'))
                    elif replay and replay.exists():
                        # The same screenshot was already looked at in an earlier run: reuse that answer (no new
                        # model call), still count it as a look this run needed, and write it as episodes now.
                        result = {**json.loads(replay.read_text(encoding='utf-8')), 'replayedFrom': str(replay)}
                        cached.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
                        remember(run, r['image'], transcribe(raw), result, surface=r['group'])
                        looks_done.append(result)
                    else:
                        scene = transcribe(raw)
                        result = look(r['image'], scene, v, root=run, log=log)
                        result['image'] = r['image']
                        result['split'] = r['split']
                        cached.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
                        remember(run, r['image'], scene, result, surface=r['group'])
                        looks_done.append(result)
                    ans = result['answer']
                    rec = answer_record(r, 'look', ans['types'], ans['verdict'] == 'broken' if ans['verdict'] != 'unsure' else None,
                                        {'missing': [m['name'] for m in ans['missing']], 'tokens': result.get('tokens'),
                                         'lookMs': round(result.get('ms', 0)), 'replayed': bool(result.get('replayedFrom'))})
                except BudgetExhausted as exc:
                    rec = answer_record(r, 'unanswered', None, None, {'reason': str(exc)})
                except Exception as exc:
                    rec = answer_record(r, 'unanswered', None, None, {'reason': type(exc).__name__ + ': ' + str(exc)[:200]})
        state['records'].append(rec)
        state['next'] += 1
        processed += 1
        print(f"{state['next']:4d} {rec['by']:10s} {rec['split']:6s} correct={rec['verdictCorrect']} {Path(r['image']).name}", flush=True)
        if state['next'] % a.window == 0 or state['next'] == len(order):
            state['windowsDone'] += 1
            changed = False
            if not a.no_authoring:
                clusters = cluster_missing(looks_done)
                # Plan 24: weakest types first (lowest FIT-group recall of the current eyes), then most-named.
                fit_recall = {t: (v['recall'] if v['recall'] is not None else 1.0) for t, v in current['splits']['fit']['types'].items()}
                clusters.sort(key=lambda c: (fit_recall.get(c['type'], 1.0), -c['looks']))
                state['missingClusters'] = clusters[:12]
                adopted_types = {e['branch']['predicate'] for e in active_entries()}
                for c in clusters:
                    key = c['type'] + ':' + c['name']
                    tries = state['attempted'].get(c['type'], 0)
                    # Up to three attempts per type, each needing new looks that name the observable.
                    seen_looks = state.setdefault('looksAtAttempt', {}).get(c['type'], 0)
                    if c['looks'] < a.min_looks or tries >= 3 or c['type'] in adopted_types or (tries and c['looks'] <= seen_looks):
                        continue
                    state['looksAtAttempt'][c['type']] = c['looks']
                    state['attempted'][c['type']] = tries + 1
                    obs = {'type': c['type'], 'name': c['name'], 'names': c['names'], 'descriptions': c['descriptions'],
                           'measures': c['measures'], 'looks': c['looks']}
                    receipt, kept = attempt(obs, run=run, log=log, rows=rows, baseline=current, active_entries=active_entries(),
                                            practice=practice if state.get('practiceJoined') else None)
                    name = f"{run.name}-w{state['windowsDone']}-{c['type']}-{c['name']}"[:120]
                    path = write_receipt(receipt, name)
                    reg = L.load()
                    if kept:
                        entry, report = kept
                        entry['decision']['receipt'] = str(path)
                        reg['lenses'].append(entry)
                        L.save(reg)
                        changed = entry['status'] == 'active'
                    state['events'].append({'at': time.strftime('%H:%M:%S'), 'position': state['next'], 'event': 'lens-decision',
                                            'observable': key, 'lens': (kept[0]['id'] if kept else None),
                                            'status': (kept[0]['status'] if kept else 'no-candidate'), 'receipt': str(path),
                                            'reasons': receipt['decision']['reasons']})
                    save_state(run, state)
                    break  # one authoring attempt per window
            if practice and not state.get('practiceJoined') and state['windowsDone'] >= a.practice_window:
                changed = True
                state['practiceJoined'] = True
                # Every practice screenshot is a perfect episode: written at once to the run's store.
                from grant_agent.laya_instant import store
                local, t0 = store(str(run)), time.perf_counter()
                with local.import_batch():  # one atomic write; per-row writes re-calibrate the store each time
                    for ep in practice['episodes']:
                        local.learn('ui-practice', {'image': ep['image']}, 'broken', 'practice:' + Path(ep['image']).name,
                                    evidence={'type': ep['type'], 'kind': ep['kind'], 'region': ep['region'], 'base': ep['base'],
                                              'labelSource': ep['labelSource']})
                state['events'].append({'event': 'practice-episodes-written', 'count': len(practice['episodes']),
                                        'seconds': round(time.perf_counter() - t0, 1)})
                state['events'].append({'at': time.strftime('%H:%M:%S'), 'position': state['next'], 'event': 'practice-joins',
                                        'episodes': len(practice['episodes'])})
            if changed:
                cal, current = recalibrate('lens adopted or practice joined')
                act = active_entries()
                if len(act) >= 2:
                    ablation = retire_pass(act, rows, current)
                    state['events'].append({'event': 'retire-pass', 'position': state['next'], 'ablation': ablation})
                    reg = L.load()
                    for row in ablation:
                        if not row['contributes']:
                            for e in reg['lenses']:
                                if e['id'] == row['lens'] and e['status'] == 'active':
                                    e['status'] = 'retired'
                                    e['decision'] = {**e.get('decision', {}), 'status': 'retired', 'retiredAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                                     'retireReason': 'ablation on check groups: no accuracy contribution', 'ablation': row}
                    L.save(reg)
                    cal, current = recalibrate('after retire pass')
            state['windows'] = window_stats(state['records'], a.window)
            print(json.dumps(state['windows'][-1]), flush=True)
        save_state(run, state)
    state['windows'] = window_stats(state['records'], a.window)
    state['finalSummary'] = summary(current)
    save_state(run, state)
    print(json.dumps({'windows': state['windows'], 'events': [e for e in state['events'] if e['event'] != 'calibrate']}, indent=1, default=str))


def practice_calibration(practice, lens_entries):
    """Region-level counts on practice episodes: an injected region is a perfect positive for its
    type, the same region before injection a perfect negative (scripts/vision_practice.py)."""
    from vision_practice import region_counts
    return region_counts(practice, lens_entries)


if __name__ == '__main__':
    main()
