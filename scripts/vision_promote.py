"""Promote the lens decisions of finished plan 24 runs into the repository registry.

Every program lens a run decided (active, rejected or retired) is copied with its receipt into
config/laya_lenses.json; its code goes to src/grant_agent/scene_core/lens_programs/<id>.py and
stays pinned by the same sha256. Only ``active`` lenses ever run. Because an adopted screenshot
lens changes the UI transcriber identity, the shipped calibration
(config/laya_glance_calibration.json) is rebuilt from the same labelled captures with the new
lens set, exactly as scripts/laya_glance_ingest.py defines it.

Usage: python scripts/vision_promote.py --runs D:/NeyviaRuns/VISION/stream-1 D:/NeyviaRuns/VISION/render-1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
PROGRAMS = ROOT / 'src/grant_agent/scene_core/lens_programs'
REGISTRY = ROOT / 'config/laya_lenses.json'
RENDER_EVAL = ['D:/NeyviaRuns/VISION/render-practice/renders.json', 'D:/NeyviaRuns/VISION/render-practice-2/renders.json',
               'D:/NeyviaRuns/VISION/render-practice-4/renders.json', 'D:/NeyviaRuns/VISION/render-practice-5/renders.json']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', nargs='+', required=True)
    a = ap.parse_args()
    from grant_agent.scene_core.lenses import load, save, validate_entry, SCHEMA
    reg = load(REGISTRY) if REGISTRY.exists() else {'schema': SCHEMA, 'lenses': []}
    known = {e['id'] for e in reg['lenses']}
    PROGRAMS.mkdir(parents=True, exist_ok=True)
    promoted = []
    for run in a.runs:
        run_reg = json.loads((Path(run) / 'lenses.json').read_text(encoding='utf-8'))
        for e in run_reg['lenses']:
            same = next((x for x in reg['lenses'] if x['programSha256'] == e['programSha256']), None)
            if same:  # a later run that started from this registry carries the same lens: keep the newest decision
                if e.get('decision', {}).get('status') == 'retired' and same['status'] != 'retired':
                    same['status'] = 'retired'
                    same['decision'] = {**same.get('decision', {}), **e['decision']}
                continue
            lens_id = e['id'] if e['id'] not in known else e['id'] + '-' + e['programSha256'][:8]
            src = Path(e['program'])
            code = src.read_text(encoding='utf-8')
            if hashlib.sha256(code.encode('utf-8')).hexdigest() != e['programSha256']:
                raise ValueError('Run program differs from its pin: ' + str(src))
            dest = PROGRAMS / (lens_id.replace('-', '_') + '.py')
            dest.write_text(code, encoding='utf-8', newline='')
            entry = {**e, 'id': lens_id, 'program': dest.relative_to(ROOT).as_posix(),
                     'provenance': {**e['provenance'], 'run': str(run), 'runProgram': str(src)}}
            if hashlib.sha256(dest.read_bytes()).hexdigest() != entry['programSha256']:
                raise ValueError('Copied program changed bytes: ' + str(dest))
            validate_entry(entry)
            reg['lenses'].append(entry)
            known.add(lens_id)
            promoted.append({'id': lens_id, 'status': entry['status'], 'inputType': entry['inputType'], 'run': str(run)})
    reg['note'] = ('Program lenses written by gpt-6-luna for observables named by model looks (plan 24). Only status '
                   '"active" runs; rejected and retired entries are kept with their decision receipts.')
    save(reg, REGISTRY)
    os.environ['NEYVIA_LAYA_LENSES'] = str(REGISTRY)
    # Rebuild the shipped UI calibration for the new transcriber identity (all labelled captures).
    from grant_agent.laya_glance import TYPES, transcriber_version, SHIPPED_CALIBRATION
    from vision_lens_eval import labelled_rows, evaluate, accuracy
    rows = labelled_rows()
    # Lenses from several runs now act together: an ablation pass on CHECK groups retires any lens
    # that no longer contributes once the others are present (receipt kept on the entry).
    active_ui = [e for e in reg['lenses'] if e['status'] == 'active' and e['inputType'] == 'screenshot']
    retired = []
    if len(active_ui) >= 2:
        together = evaluate(active_ui, rows)
        for e in list(active_ui):
            rest = [x for x in active_ui if x['id'] != e['id']]
            without = evaluate(rest, rows)
            p_ = e['branch']['predicate']
            aw, ao = accuracy(together['splits']['check']['types'][p_]), accuracy(without['splits']['check']['types'][p_])
            row = {'lens': e['id'], 'predicate': p_, 'checkAccuracyWith': round(aw, 4), 'checkAccuracyWithout': round(ao, 4), 'contributes': aw > ao}
            if not row['contributes']:
                e['status'] = 'retired'
                e['decision'] = {**e.get('decision', {}), 'status': 'retired', 'retireReason': 'ablation at promotion: no check accuracy contribution alongside the other adopted lenses', 'ablation': row}
                active_ui = rest
                together = evaluate(active_ui, rows)
            retired.append(row)
        save(reg, REGISTRY)
    # Minimum-evidence rule (vision_lens_eval.MIN_CHECK_POSITIVES / MIN_NET_GAIN), applied to lenses kept before
    # it existed, from CHECK groups only. Disclosed: the rule was added after reading the first final report.
    from vision_lens_eval import MIN_CHECK_POSITIVES, MIN_NET_GAIN
    for e in [x for x in reg['lenses'] if x['status'] == 'active' and x['inputType'] == 'screenshot']:
        p_ = e['branch']['predicate']
        together = evaluate(active_ui, rows)
        without = evaluate([x for x in active_ui if x['id'] != e['id']], rows)
        m = together['splits']['check']['types'][p_]
        n = sum(m[k] for k in ('tp', 'fp', 'tn', 'fn'))
        gain = round((accuracy(m) - accuracy(without['splits']['check']['types'][p_])) * n)
        row = {'lens': e['id'], 'predicate': p_, 'checkPositives': m['positives'], 'checkNetGain': gain}
        if m['positives'] < MIN_CHECK_POSITIVES or gain < MIN_NET_GAIN:
            e['status'] = 'retired'
            e['decision'] = {**e.get('decision', {}), 'status': 'retired', 'evidence': row,
                             'retireReason': f'insufficient check evidence (positives >= {MIN_CHECK_POSITIVES} and net gain >= {MIN_NET_GAIN} required); '
                                             'rule added 7 Oct after the first final-group report (disclosed)'}
            active_ui = [x for x in active_ui if x['id'] != e['id']]
        retired.append({**row, 'evidenceRule': 'kept' if e['status'] == 'active' else 'retired'})
    save(reg, REGISTRY)
    # The same rule for render lenses, on CHECK subjects of every stored labelled render batch.
    import vision_render_run as R
    render_rows = [r for path in RENDER_EVAL for r in R.rows_with_splits(path)]
    active_r = [x for x in reg['lenses'] if x['status'] == 'active' and x['inputType'] == 'render']
    for e in list(active_r):
        p_ = e['branch']['predicate']
        together = R.evaluate(active_r, render_rows)
        without = R.evaluate([x for x in active_r if x['id'] != e['id']], render_rows)
        m = together['splits']['check']['types'][p_]
        n = sum(m[k] for k in ('tp', 'fp', 'tn', 'fn'))
        gain = round((accuracy(m) - accuracy(without['splits']['check']['types'][p_])) * n)
        row = {'lens': e['id'], 'predicate': p_, 'checkPositives': m['positives'], 'checkNetGain': gain, 'renders': len(render_rows)}
        if m['positives'] < MIN_CHECK_POSITIVES or gain < MIN_NET_GAIN:
            e['status'] = 'retired'
            e['decision'] = {**e.get('decision', {}), 'status': 'retired', 'evidence': row,
                             'retireReason': f'insufficient check evidence (positives >= {MIN_CHECK_POSITIVES} and net gain >= {MIN_NET_GAIN} required)'}
            active_r = [x for x in active_r if x['id'] != e['id']]
        retired.append({**row, 'evidenceRule': 'kept' if e['status'] == 'active' else 'retired'})
    save(reg, REGISTRY)
    report = evaluate(active_ui, rows)
    counts = {t: {k: sum(report['splits'][s]['types'][t][k] for s in ('fit', 'check', 'final')) for k in ('tp', 'fp', 'tn', 'fn')} for t in TYPES}
    old = json.loads(SHIPPED_CALIBRATION.read_text(encoding='utf-8'))
    shipped = {'schema': 'neyvia.laya-glance-calibration.v1', 'transcriber': transcriber_version(), 'level': 0.95, 'counts': counts,
               'sources': len(rows), 'lenses': [e['id'] for e in active_ui], 'previousTranscriber': old.get('transcriber'),
               'meaning': 'Per-predicate image-level outcomes of the pixel glance on labelled captures (episodes); '
                          'precision/NPV bounds are k/(n+1). Rebuilt by scripts/vision_promote.py with the adopted lenses.'}
    SHIPPED_CALIBRATION.write_text(json.dumps(shipped, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'promoted': promoted, 'ablation': retired, 'activeScreenshotLenses': [e['id'] for e in active_ui],
                      'transcriber': shipped['transcriber'], 'previous': shipped['previousTranscriber']}, indent=1))


if __name__ == '__main__':
    main()
