"""Fit explicit candidate representations from executable manuals and real receipts.

Preserves untouched benchmark labels and independent calibration/held-out splits.
No library copies, no downloads, no model-provider calls, no new test files.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import argparse
import os
os.environ['OPENBLAS_NUM_THREADS'] = '2'
os.environ['OMP_NUM_THREADS'] = '2'

REPO = Path(__file__).resolve().parents[1]
RUN = Path('D:/NeyviaRuns/laya-train')
sys.path.insert(0, str(REPO / 'src'))
from grant_agent import laya_curriculum as learner
from grant_agent.cl.manuals import cl_to_manual


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.parent == learner.ARTIFACTS:
        original = path.read_bytes()
        history = RUN / 'model-history' / (path.stem + '-' + hashlib.sha256(original).hexdigest()[:12] + '.json')
        history.parent.mkdir(parents=True, exist_ok=True)
        if not history.exists():
            history.write_bytes(original)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')


def manuals():
    rows, hashes, counts, layers = [], {}, Counter(), {}
    index = json.loads((REPO / 'config/neyvia_manuals.json').read_text(encoding='utf-8'))
    descriptions = {r['id']: r.get('description', '') for r in index['manuals']}
    for path in sorted((REPO / 'manuals/cl').glob('*.cl')):
        source = path.read_text(encoding='utf-8')
        if '@manual ' not in source:
            # CL skills carry the same A/C/P syntax but no JSON manual envelope.
            layer = path.stem
            for i, line in enumerate(source.splitlines()):
                if line.startswith(('A ', 'C ', 'P ')):
                    kind = {'A': 'actions', 'C': 'checks', 'P': 'procedures'}[line[0]]
                    rows.append({'id': f'{layer}:line:{i+1}', 'label': layer, 'kind': kind,
                                 'group': layer, 'text': line, 'source': path.relative_to(REPO).as_posix()})
                    counts[kind] += 1
        else:
            data = cl_to_manual(source)
            layer = 'cua' if data['id'] == 'computer-use' else data['id']
            layers[layer] = descriptions.get(data['id'], layer)
            rows.append({'id': layer + ':overview', 'label': layer, 'group': layer, 'kind': 'overview',
                         'text': layer + ' ' + layers[layer], 'source': path.relative_to(REPO).as_posix()})
            for chapter_id, chapter in data['chapters'].items():
                for kind in ('actions', 'checks', 'procedures'):
                    for name, item in chapter.get(kind, {}).items():
                        # Learn descriptions, action identities and check contracts.
                        text = ' '.join(str(item.get(k, '')) for k in ('goal', 'effect', 'pre', 'tool'))
                        rows.append({'id': f'{layer}:{chapter_id}:{kind}:{name}', 'label': layer,
                                     'kind': kind, 'group': chapter_id, 'name': name,
                                     'tool': item.get('tool', ''),
                                     'text': name.replace('-', ' ') + ' ' + text,
                                     'source': path.relative_to(REPO).as_posix()})
                        counts[kind] += 1
        hashes[path.relative_to(REPO).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    # Cross-cutting proof manuals quote application tools. Their declarations
    # teach the tool's owning layer, not a competing proof-layer route.
    for row in rows:
        owner = row.get('tool', '').removeprefix('neyvia.').split('.')[0]
        if owner in layers:
            row['label'] = owner
    routing_rows = [r for r in rows if not r['label'].startswith(('proofs', 'local-'))]
    model = learner.fit(routing_rows)
    learner.fit_head(model, routing_rows)
    model['manualHashes'] = hashes
    model['layers'] = layers
    benchmark = json.loads((REPO / 'config/cl_benchmark_1.1_tasks.json').read_text())
    def cases(section):
        return [{'id': f'{section}:{r["id"]}', 'group': str(r['id']), 'text': r['text'],
                 'label': 'cua' if r.get('layer') == 'computer-use' else r.get('layer')}
                for r in benchmark.get(section, []) if r.get('text') and r.get('layer') in layers]
    calibration, held = cases('dev'), cases('tasks')
    learner.calibrate(model, calibration)
    save(learner.ARTIFACTS / 'manual-router.json', model)
    report = learner.evaluate(model, held)
    real_panel = json.loads((REPO / 'scripts/evidence/MS-runs/manuals/panel.json').read_text(encoding='utf-8'))
    actual = []
    for row in real_panel['tasks']:
        receipts = REPO / 'scripts/evidence/MS-runs/manuals' / (row['manual'] + '-reviewed-paired.json')
        if not receipts.is_file():
            receipts = receipts.with_name(row['manual'] + '-paired.json')
        evidence = json.loads(receipts.read_text(encoding='utf-8')) if receipts.exists() else []
        if any(r.get('task') == row['id'] and r.get('transportPassed') for r in evidence):
            actual.append({'id': row['id'], 'group': row['id'], 'text': row['task'], 'label': row['manual'],
                           'receipt': receipts.relative_to(REPO).as_posix()})
    real_report = learner.evaluate(model, actual)
    save(RUN / 'manual-real-heldout.json', real_report)
    save(RUN / 'manual-real-cases.json', actual)
    save(RUN / 'manual-heldout.json', report)
    save(RUN / 'manual-curriculum.json', rows)
    return {'learned': len(rows), 'coverage': dict(counts), 'manuals': len(hashes),
            'calibration': model['calibration'], 'heldoutSource': 'Frozen CL 1.1 benchmark tasks, not live-run success',
            'unsupportedBenchmarkTaxonomy': len(benchmark['tasks']) - len(held),
            'realHeldout': {k: v for k, v in real_report.items() if k != 'answers'},
            **{k: v for k, v in report.items() if k != 'answers'}}


def receipts():
    rows, seen = [], set()
    # Real archived native tool outcomes only. Ignore self-authored aggregate reports.
    paths = list((REPO / '.agent_control/tool_receipts').glob('*.json'))
    tracked = subprocess.check_output(['git', 'ls-files', 'scripts/evidence/*receipt*.json'], cwd=REPO, text=True)
    paths += [REPO / path for path in tracked.splitlines()]
    for path in sorted(paths):
        if path.stat().st_size > 2_000_000:
            continue
        try:
            row = json.loads(path.read_bytes())
        except (ValueError, OSError):
            continue
        if not isinstance(row, dict) or row.get('schema') != 'fluxio.native_tool_receipt.v1' or not isinstance(row.get('ok'), bool):
            continue
        if not row.get('proofs'):
            continue
        result = row.get('result', {})
        # Do not feed the target top-level ok/status/proofs to the predictor.
        text = learner.receipt_text(result)
        identity = learner.digest([row.get('tool'), result])
        if identity in seen:
            continue
        seen.add(identity)
        rows.append({'id': identity, 'group': row.get('tool', 'unknown'), 'text': text,
                     'label': 'success' if row['ok'] else 'failure', 'source': str(path.relative_to(REPO))})
    # Tool families are isolated, so repeated operations cannot cross splits.
    split = lambda row: int(hashlib.sha256(row['group'].encode()).hexdigest()[:8], 16) % 5
    train = [r for r in rows if split(r) > 1]
    cal = [r for r in rows if split(r) == 1]
    held = [r for r in rows if split(r) == 0]
    model = learner.fit(train)
    learner.calibrate(model, cal)
    # No one-class training corpus is allowed to issue completion judgements.
    if len({r['label'] for r in train}) < 2:
        model['calibration'].update(threshold=None, confidenceLowerBound=0, reason='missing-failed-run-labels')
    report = learner.evaluate(model, held)
    save(learner.ARTIFACTS / 'receipt-outcome.json', model)
    save(RUN / 'receipt-heldout.json', report)
    save(RUN / 'receipt-curriculum.json', rows)
    return {'learned': len(train), 'realReceipts': len(rows), 'labels': dict(Counter(r['label'] for r in rows)),
            'calibration': model['calibration'], **{k: v for k, v in report.items() if k != 'answers'}}


def components():
    notes = learner.load('component-notes')['patterns']
    allowed = {'MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'ISC'}
    if any(r['license'] not in allowed for r in notes):
        raise ValueError('Unapproved source license')
    model = learner.fit(notes)
    old_path = learner.ARTIFACTS / 'components.json'
    old = {r['id']: r for r in learner.load('components')['rows']} if old_path.exists() else {}
    for row in model['rows']:
        previous = old.get(row['id'], {})
        if previous.get('source') == row['source'] and previous.get('renderRepresentation'):
            row['renderRepresentation'] = previous['renderRepresentation']
    save(old_path, model)
    return {'learned': len(notes), 'cases': 0, 'accuracy': None, 'answerRate': 0,
            'reason': 'Representations and source notes; no independent relevance/novelty labels'}


def personal():
    origin = Path('C:/Users/user/Projects/nx-c13-taste/proof')
    rows, source_hashes = [], {}
    for path in sorted((origin / 'votes-export').rglob('*.json')):
        data = json.loads(path.read_bytes())
        rel = path.relative_to(origin).as_posix()
        source_hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        if 'rounds' in data:
            for index, item in enumerate(data['rounds']):
                rows.append({'id': rel + ':' + str(index), 'group': item['round'], 'label': 'context',
                             'kind': 'qualitative-feedback', 'text': ' '.join(item.get('reasons', [])),
                             'note': item, 'source': rel})
        else:
            quality = 'better' in data
            rows.append({'id': rel, 'group': data.get('run', rel), 'label': 'quality' if quality else 'identity',
                         'kind': 'quality-preference' if quality else 'identity-only', 'text': json.dumps(data),
                         'note': {k: v for k, v in data.items() if k != 'voter'}, 'source': rel})
    for index, row in enumerate(json.loads((origin / 'r11/learning/personal-cases.json').read_bytes())):
        rows.append({'id': 'bound-pair:' + row['id'], 'label': 'context' if row.get('excludedFromTraining') else 'quality',
                     'group': row['group'], 'kind': 'unbound-comment' if row.get('excludedFromTraining') else 'bound-pixel-pair',
                     'text': row['reason'], 'note': row['reason'], 'source': 'r11/learning/personal-cases.json'})
    model = learner.fit(rows)
    model['sourceHashes'] = source_hashes
    save(learner.ARTIFACTS / 'personal.json', model)
    return {'learned': len(rows), 'labelKinds': dict(Counter(r['kind'] for r in rows)),
            'cases': 0, 'accuracy': None, 'answerRate': 0, 'conditioning': 'few-shot-only',
            'reason': 'All exported labels retained; identity labels never converted to quality supervision'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manual-only', action='store_true')
    args = parser.parse_args()
    previous = RUN / 'capability-metrics.json'
    summary = json.loads(previous.read_text(encoding='utf-8')) if args.manual_only and previous.exists() else {}
    for name, operation in [('components', components), ('personal', personal), ('manuals', manuals), ('outcomes', receipts)]:
        if args.manual_only and name != 'manuals':
            continue
        summary[name] = operation()
        print(name, json.dumps(summary[name]), flush=True)
    save(RUN / 'capability-metrics.json', summary)
    save(REPO / 'scripts/evidence/LAYAT-capability-metrics.json', summary)
    print(json.dumps(summary, indent=2))
