"""Missing observable -> Luna-written candidate lens -> grouped keep/reject -> retire (plan 24).

Used by scripts/vision_stream.py (and runnable alone for one observable):
  python scripts/vision_evolve.py --run D:/NeyviaRuns/VISION/<run> --type overlap --name text-touches-icon \
      --description "..." [--measure "..."]

Authoring sees only FIT-group examples. The keep decision reads only CHECK groups.
FINAL groups are reported in the receipt and never read by a decision.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeout
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from vision_lens_eval import labelled_rows, evaluate, decide, summary, accuracy  # noqa: E402
from laya_glance_eval import _scene  # noqa: E402

RECEIPTS = ROOT / 'scripts/evidence/VISION-lenses'


# --- missing observables from looks -----------------------------------------

def _tokens(name):
    stop = {'the', 'a', 'of', 'to', 'and', 'or', 'in', 'on', 'at', 'by', 'is', 'with', 'from', 'text', 'line'}
    return {t for t in re.split(r'[^a-z0-9]+', name.lower()) if t and t not in stop}


def cluster_missing(looks):
    """Group the observables model looks named, per defect type, by shared name tokens."""
    mentions = []
    for row in looks:
        for m in row['answer']['missing']:
            mentions.append({'type': m['type'], 'name': m['name'], 'description': m['description'], 'measure': m['measure'],
                             'look': row.get('receiptSha256', '')[:16]})
    clusters = []
    for m in mentions:
        tok = _tokens(m['name']) or {m['name']}
        best = None
        for c in clusters:
            if c['type'] != m['type']:
                continue
            j = len(tok & c['tokens']) / max(len(tok | c['tokens']), 1)
            if j >= 0.34 and (best is None or j > best[0]):
                best = (j, c)
        if best:
            best[1]['mentions'].append(m)
            best[1]['tokens'] |= tok
        else:
            clusters.append({'type': m['type'], 'tokens': set(tok), 'mentions': [m]})
    out = []
    for c in clusters:
        names = Counter(m['name'] for m in c['mentions'])
        looks_n = len({m['look'] for m in c['mentions']})
        descs = [m['description'] for m in c['mentions'] if m['description']][:4]
        measures = [m['measure'] for m in c['mentions'] if m['measure']][:4]
        out.append({'type': c['type'], 'name': names.most_common(1)[0][0], 'names': dict(names), 'looks': looks_n,
                    'descriptions': descs, 'measures': measures})
    return sorted(out, key=lambda c: -c['looks'])


# --- examples for the author (fit groups only) ------------------------------

def _crop(image, box, out, margin=(220, 90)):
    from PIL import Image
    im = Image.open(image).convert('RGB')
    w, h = im.size
    x0 = max(0, int(box['x'] - margin[0])); y0 = max(0, int(box['y'] - margin[1]))
    x1 = min(w, int(box['x'] + box['w'] + margin[0])); y1 = min(h, int(box['y'] + box['h'] + margin[1]))
    if x1 - x0 < 8 or y1 - y0 < 8:  # region from another screen size: fall back to the bottom band
        x0, y0, x1, y1 = 0, max(0, h - 160), w, h
    im.crop((x0, y0, x1, y1)).save(out)
    return {'x': x0, 'y': y0, 'w': x1 - x0, 'h': y1 - y0}


def examples_for(defect, rows, judged, run, *, positives=3, negatives=1):
    """Fit-group rows only: positives the pixel glance missed (with a located quote), plus
    negatives of the same kind of surface. Returns (examples json, image paths)."""
    from grant_agent.laya_glance import transcribe, locate_quote, quotes
    crops = Path(run) / 'crops'
    crops.mkdir(parents=True, exist_ok=True)
    fired = {j['image']: set(j['fired']) for j in judged}
    pos, neg = [], []
    for r in rows:
        if r['split'] != 'fit':
            continue
        if r['labels'].get(defect) and defect not in fired.get(r['image'], set()):
            pos.append(r)
        elif not r['labels'].get(defect):
            neg.append(r)
    pos.sort(key=lambda r: hashlib.sha256(r['image'].encode()).hexdigest())
    neg.sort(key=lambda r: hashlib.sha256(r['image'].encode()).hexdigest())
    examples, images = [], []

    def add(r, label):
        scene = transcribe(_scene(r['image']))
        ev = (r.get('evidence') or {}).get(defect, '')
        node = None
        for q in quotes(ev):
            node = locate_quote(scene, q)
            if node:
                break
        by_id = {n['id']: n for n in scene['nodes']}
        if node:
            box = by_id[node]['attributes']['bounds']
        else:
            box = {'x': 0, 'y': scene['viewport']['height'] - 60, 'w': scene['viewport']['width'], 'h': 60} if label else None
        if box is None:
            return False
        out = crops / (hashlib.sha256((r['image'] + defect).encode()).hexdigest()[:16] + '.png')
        region = _crop(r['image'], box, out)
        near = [{'id': n['id'], 'text': n['attributes'].get('text', '')[:60], 'bounds': n['attributes'].get('bounds')}
                for n in scene['nodes'] if n['kind'] == 'text' and (b := n['attributes'].get('bounds'))
                and region['x'] <= b['x'] + b['w'] and b['x'] <= region['x'] + region['w']
                and region['y'] <= b['y'] + b['h'] and b['y'] <= region['y'] + region['h']][:14]
        examples.append({'image': len(images) + 1, 'label': 'defect' if label else 'no defect', 'type': defect,
                         'labelNote': ev or 'labelled clean for this type', 'screenshotSize': scene['viewport'],
                         'cropOffsetInScreenshot': region, 'ocrNodesInCrop': near})
        images.append(str(out))
        return True

    for r in pos:
        if len(images) >= positives:
            break
        add(r, True)
    target = len(images) + negatives
    # Negatives cropped at the same place as the first positive (same layout, no defect).
    for r in neg:
        if len(images) >= target:
            break
        if examples:
            first = examples[0]['cropOffsetInScreenshot']
            out = crops / (hashlib.sha256((r['image'] + defect + 'neg').encode()).hexdigest()[:16] + '.png')
            region = _crop(r['image'], {'x': first['x'] + 220, 'y': first['y'] + 90, 'w': max(first['w'] - 440, 1), 'h': max(first['h'] - 180, 1)}, out)
            examples.append({'image': len(images) + 1, 'label': 'no defect', 'type': defect, 'labelNote': 'labelled clean for this type',
                             'screenshotSize': {'width': None}, 'cropOffsetInScreenshot': region, 'ocrNodesInCrop': []})
            images.append(str(out))
    return examples, images, {'fitPositivesMissed': len(pos), 'fitNegatives': len(neg)}


# --- smoke run in a separate process ----------------------------------------

def _smoke(args):
    entry, images = args
    from grant_agent.scene_core.lenses import run_lens, load_program
    import numpy as np
    from PIL import Image
    fn = load_program(entry)
    out = []
    for image in images:
        raw = _scene(image)
        rgb = np.asarray(Image.open(image).convert('RGB'))
        facts, added, ms = run_lens(entry, rgb, raw, fn)
        out.append({'image': image, 'facts': sum(len(v) for v in facts.values()), 'added': len(added), 'ms': round(ms, 1),
                    'true': sum(1 for v in facts.values() for x in v.values() if x is True) +
                            sum(1 for a in added for k, x in a['measurements'].items() if x is True)})
    return out


def smoke(entry, images, timeout=120):
    pool = ProcessPoolExecutor(1)
    try:
        return pool.submit(_smoke, (entry, images)).result(timeout=timeout)
    except FutureTimeout:
        raise TimeoutError(f'lens smoke run exceeded {timeout} s on {len(images)} images')
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def fit_feedback(report, entry):
    """Precision/recall of the candidate on FIT groups only (the author may iterate on these)."""
    p = entry['branch']['predicate']
    m = report['splits']['fit']['types'][p]
    fps = [r for r in report['rows'] if r['split'] == 'fit' and p in r['fired'] and not r['labels'].get(p)]
    fns = [r for r in report['rows'] if r['split'] == 'fit' and r['labels'].get(p) and p not in r['fired']]
    lens_hits = lambda r: [b['text'] for b in r['bugs'] if b['type'] == p][:3]
    lines = [f'On labelled fit screenshots the predicate {p} now has precision {m["precision"]} and recall {m["recall"]} '
             f'(tp {m["tp"]}, fp {m["fp"]}, fn {m["fn"]}, tn {m["tn"]}).']
    for r in fps[:4]:
        lines.append(f'False alarm on {Path(r["image"]).name}: fired on {lens_hits(r)}')
    for r in fns[:4]:
        lines.append(f'Missed on {Path(r["image"]).name}: label note "{(r.get("evidence") or {}).get(p, "")[:120]}"')
    return '\n'.join(lines), m


def failure_crops(report, entry, run, rows):
    """Images of the candidate's own mistakes on FIT groups: 2 false alarms (cropped on the node
    it fired on) and 2 misses (cropped on the labelled quote), for the author's next attempt."""
    from grant_agent.laya_glance import transcribe, locate_quote, quotes
    p = entry['branch']['predicate']
    crops = Path(run) / 'crops'
    crops.mkdir(parents=True, exist_ok=True)
    by_image = {r['image']: r for r in rows}
    fps = [r for r in report['rows'] if r['split'] == 'fit' and p in r['fired'] and not r['labels'].get(p)]
    fns = [r for r in report['rows'] if r['split'] == 'fit' and r['labels'].get(p) and p not in r['fired']]
    key = lambda r: hashlib.sha256((r['image'] + entry['id']).encode()).hexdigest()
    fps.sort(key=key); fns.sort(key=key)
    examples, images = [], []
    for kind, part in (('false alarm (no defect here)', fps[:2]), ('missed defect', fns[:2])):
        for r in part:
            scene = transcribe(_scene(r['image']))
            by_id = {n['id']: n for n in scene['nodes']}
            box = None
            if kind.startswith('false'):
                hit = next((b for b in r['bugs'] if b['type'] == p and b['node'] in by_id), None)
                box = by_id[hit['node']]['attributes'].get('bounds') if hit else None
            else:
                for q in quotes((by_image[r['image']].get('evidence') or {}).get(p, '')):
                    nid = locate_quote(scene, q)
                    if nid:
                        box = by_id[nid]['attributes'].get('bounds'); break
            if not box:
                continue
            out = crops / (hashlib.sha256((r['image'] + entry['id'] + kind).encode()).hexdigest()[:16] + '.png')
            region = _crop(r['image'], box, out)
            examples.append({'image': len(images) + 1, 'label': kind, 'type': p,
                             'labelNote': (by_image[r['image']].get('evidence') or {}).get(p, '') or 'labelled clean for this type',
                             'cropOffsetInScreenshot': region, 'nodeBoundsInScreenshot': box})
            images.append(str(out))
    return examples, images


def _fit_score(m):
    return ((m['precision'] or 0) >= 0.9, accuracy(m) or 0)


# --- the whole loop for one observable --------------------------------------

def practice_examples(defect, practice, run, start, limit=1):
    """Practice positives with their EXACT injected region (LAYA made them), plus the same place
    before injection (which may still carry real defects of other kinds)."""
    crops = Path(run) / 'crops'
    crops.mkdir(parents=True, exist_ok=True)
    eps = sorted((e for e in (practice or {}).get('episodes', []) if e['type'] == defect),
                 key=lambda e: hashlib.sha256(e['image'].encode()).hexdigest())[:limit]
    examples, images = [], []
    for e in eps:
        for side, path in (('defect (injected by LAYA; exact region)', e['image']), ('same place before injection', e['base'])):
            out = crops / (hashlib.sha256((path + defect + side).encode()).hexdigest()[:16] + '.png')
            region = _crop(path, e['region'], out)
            examples.append({'image': start + len(images) + 1, 'label': side, 'type': defect, 'injection': e['kind'],
                             'injectedRegionInScreenshot': e['region'], 'cropOffsetInScreenshot': region})
            images.append(str(out))
    return examples, images


def attempt(observable, *, run, log, rows, baseline, active_entries, max_calls=4, practice=None):
    """Author -> validate -> smoke -> evaluate (fit feedback, up to max_calls) -> decide on check.
    Returns the decision receipt (and writes it)."""
    from grant_agent.laya_vision import author_lens
    from grant_agent.scene_core.lenses import validate_source, validate_entry
    defect = observable['type']
    examples, images, pool = examples_for(defect, rows, baseline['rows'], run, positives=2 if practice else 3)
    if practice:
        px, pi = practice_examples(defect, practice, run, len(images))
        examples, images = (examples + px)[:4], (images + pi)[:4]
    programs = Path(run) / 'lens_programs'
    programs.mkdir(parents=True, exist_ok=True)
    history, feedback, best = [], None, None
    call_examples, call_images = examples, images
    for call in range(max_calls):
        try:
            entry, source, receipt = author_lens(observable, call_examples, call_images, root=run, log=log, feedback=feedback)
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
            fit_images = [r['image'] for r in rows if r['split'] == 'fit'][:6]
            step['smoke'] = smoke(entry, fit_images)
        except Exception as exc:
            feedback = f'{type(exc).__name__}: {str(exc)[:600]}'
            step['rejectedBeforeEvaluation'] = feedback
            continue
        report = evaluate(active_entries + [entry], rows)
        text, fit_m = fit_feedback(report, entry)
        step['fit'] = fit_m
        step['cost'] = report['cost'].get(entry['id'])
        if best is None or _fit_score(fit_m) > _fit_score(best[2]['splits']['fit']['types'][entry['branch']['predicate']]):
            best = (entry, source, report)
        base_fit = baseline['splits']['fit']['types'][entry['branch']['predicate']]
        if (fit_m['precision'] or 0) >= 0.9 and (accuracy(fit_m) or 0) > (accuracy(base_fit) or 0) and step['cost'] and \
                (step['cost']['medianMs'] or 1e9) <= 120:
            break
        feedback = (text + f'\nLens cost: {step["cost"]}. Raise precision first; then recall. The attached images are now '
                    'crops of YOUR program\'s mistakes on labelled screenshots (described in the examples). Edit your '
                    'previous program rather than starting over:\n```python\n' + source[:12000] + '\n```')
        fx, fi = failure_crops(report, entry, run, rows)
        if fi:
            call_examples, call_images = fx, fi
    receipt = {'schema': 'neyvia.laya.lens-decision.v1', 'observable': observable, 'examples': examples, 'examplePool': pool,
               'history': history, 'at': time.strftime('%Y-%m-%dT%H:%M:%S')}
    if best is None:
        receipt['decision'] = {'keep': False, 'reasons': ['no candidate lens survived validation and smoke run']}
        return receipt, None
    entry, source, report = best
    decision = decide(entry['id'], report, baseline, entry['branch']['predicate'])
    receipt.update(lens=entry, decision=decision,
                   finalReportOnly={'with': report['splits']['final']['types'][entry['branch']['predicate']],
                                    'without': baseline['splits']['final']['types'][entry['branch']['predicate']]},
                   fitWith=report['splits']['fit']['types'][entry['branch']['predicate']],
                   fitWithout=baseline['splits']['fit']['types'][entry['branch']['predicate']])
    entry['status'] = 'active' if decision['keep'] else 'rejected'
    entry['decision'] = {'status': entry['status'], 'reasons': decision['reasons'], 'checkAccuracy': decision['checkAccuracy'],
                         'cost': decision['cost'], 'at': receipt['at']}
    entry['cost'] = decision['cost']
    return receipt, (entry, report)


def retire_pass(active_entries, rows, current_report):
    """Ablation on CHECK groups: a lens whose removal does not lower check accuracy of its
    predicate (or that now breaks the budget) stops contributing and is retired."""
    out = []
    for e in active_entries:
        rest = [x for x in active_entries if x['id'] != e['id']]
        without = evaluate(rest, rows)
        p = e['branch']['predicate']
        a_with = accuracy(current_report['splits']['check']['types'][p])
        a_without = accuracy(without['splits']['check']['types'][p])
        contributes = a_with > a_without
        out.append({'lens': e['id'], 'predicate': p, 'checkAccuracyWith': round(a_with, 4), 'checkAccuracyWithout': round(a_without, 4),
                    'contributes': contributes, 'cost': current_report['cost'].get(e['id'])})
    return out


def write_receipt(receipt, name):
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    path = RECEIPTS / (name + '.json')
    path.write_text(json.dumps(receipt, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--type', required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--description', required=True)
    ap.add_argument('--measure', default='')
    ap.add_argument('--max-calls', type=int, default=3)
    a = ap.parse_args()
    from grant_agent.laya_vision import LookLog
    run = Path(a.run)
    run.mkdir(parents=True, exist_ok=True)
    log = LookLog(run / 'model-calls.jsonl')
    rows = labelled_rows()
    baseline = evaluate([], rows)
    obs = {'type': a.type, 'name': a.name, 'descriptions': [a.description], 'measures': [a.measure] if a.measure else [], 'looks': 0}
    receipt, kept = attempt(obs, run=run, log=log, rows=rows, baseline=baseline, active_entries=[], max_calls=a.max_calls)
    path = write_receipt(receipt, 'manual-' + a.name)
    print(json.dumps({'receipt': str(path), 'decision': receipt['decision'], 'history': receipt['history']}, indent=1, default=str))


if __name__ == '__main__':
    main()
