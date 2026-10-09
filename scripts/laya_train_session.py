"""Scoped LAYA experiments; writes live artifacts on D:, never the source model tree.

Run with system Python. The existing frozen model uses its installed runtime.
This is an experiment runner, not a replacement for CL acceptance contracts.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import shutil
import time

REPO = Path(__file__).resolve().parents[1]
RUN = Path('D:/NeyviaRuns/laya-train')
sys.path.insert(0, str(REPO / 'src'))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + '\n', encoding='utf-8')


def regression(phase, resume=False):
    from grant_agent.laya_host import LayaHost, load_config
    gates = load(REPO / 'scripts/laya_regression_gate.py', 'laya_regression')
    gates.SCRATCH = RUN / phase / 'gates'
    port = 48991 if phase == 'before' else 48993
    report = json.loads((RUN / phase / 'regression.json').read_text()) if resume else {'phase': phase, 'started': time.time(), 'port': port}
    if resume:
        if report.get('G3', {}).get('correct', 0) < 138:
            raise RuntimeError('Cannot resume without a completed passing JevBench run')
        save(RUN / phase / 'interrupted-regression.json', report)
        report.pop('finished', None)
        report['resumedExistingSets'] = time.time()
    for name, operation in ([] if resume else [('G1', gates.g1_journey), ('G2', gates.g2_routes)]):
        try:
            report[name] = operation()
        except Exception as exc:
            report[name] = {'passed': False, 'error': str(exc)}
        save(RUN / phase / 'regression.json', report)
        print(name, json.dumps(report[name]), flush=True)
    root = REPO / '.agent_control/laya-train-runtime' / phase if resume else RUN / phase / 'host'
    host = LayaHost(root, {**load_config(root), 'port': port, 'device': 'cpu'}).start()
    try:
        report['serviceReady'] = gates.wait_ready(port)
        report['host'] = host.status()
        save(RUN / phase / 'regression.json', report)
        if not report['serviceReady']:
            return
        runner = load(gates.LAYA_PROJECT / 'scripts/run_jevbench.py', 'laya_jevbench')
        runner.ROOT = RUN
        output = RUN / phase / 'jevbench.json'
        sys.argv = [str(__file__), '--endpoint', f'http://127.0.0.1:{port}/ai/run',
                    '--name', 'LAYAT-' + phase, '--output', str(output), '--timeout', '180']
        if not resume:
            runner.main()
        report['G3'] = json.loads(output.read_text(encoding='utf-8'))
        report['G3']['passed'] = report['G3'].get('correct', 0) >= 138
        print('G3', report['G3'].get('correct'), flush=True)
        # Existing question sets, untouched data and observed predictions retained.
        from grant_agent import laya_hooks
        import urllib.request
        saved = RUN / phase / 'existing-sets.json'
        observations = json.loads(saved.read_text()) if resume and saved.exists() else []
        done = {(r['area'],r['id']) for r in observations}
        for area in ('page_done', 'taste_triage'):
            rows = [json.loads(line) for line in (REPO / 'tools/laya/corpora' / (area + '.jsonl')).read_text(encoding='utf-8').splitlines()]
            for row in rows:
                if row.get('split') == 'train':
                    continue
                if (area,row['id']) in done:
                    continue
                payload = {'set': laya_hooks.SET, 'questions': [area], 'state': row['state'],
                           'scope': laya_hooks.SCOPES[area], 'base_cache': False}
                request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/decide', json.dumps(payload).encode(), {'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=180) as response:
                    answer = json.load(response)['answers'][area]
                observations.append({'area': area, 'id': row['id'], 'label': row['label'], 'answer': answer})
                save(RUN / phase / 'existing-sets.json', observations)
        report['existingCases'] = len(observations)
    finally:
        host.stop()
        if resume:
            shutil.copytree(root, RUN / phase / 'resumed-host-checkpoint', dirs_exist_ok=True)
        report['finished'] = time.time()
        save(RUN / phase / 'regression.json', report)


def summarize():
    before, after = [json.loads((RUN / phase / 'regression.json').read_text(encoding='utf-8')) for phase in ('before','after')]
    if not before.get('finished') or not after.get('finished'):
        raise RuntimeError('Both regression runs must finish before admission')
    old, new = [json.loads((RUN / phase / 'existing-sets.json').read_text(encoding='utf-8')) for phase in ('before','after')]
    keys = lambda rows: {(r['area'],r['id']):r for r in rows}
    baseline, candidate = keys(old), keys(new)
    if baseline.keys() != candidate.keys():
        raise RuntimeError('Existing question-set case IDs changed')
    areas = {}
    for area in ('page_done','taste_triage'):
        selected = [key for key in baseline if key[0] == area]
        changed = [key[1] for key in selected if any(baseline[key]['answer'].get(field) != candidate[key]['answer'].get(field)
                    for field in ('answer','p','policy','source','confidence'))]
        correct = lambda rows: sum(str(rows[k]['answer']['answer']).lower() == str(rows[k]['label']).lower() for k in selected)
        areas[area] = {'cases':len(selected),'beforeCorrect':correct(baseline),'afterCorrect':correct(candidate),
                       'changedDecisionIds':changed,'identicalDecisionsAndProbabilities':not changed}
    report = {'G1':after['G1'], 'G2':after['G2'], 'JevBench':{'before':before['G3']['correct'],'after':after['G3']['correct'],'cases':231},
              'existingSets':areas,'rawEvidence':str(RUN),'scope':'CPU frozen model replay plus disposable G1/G2 artifacts; host shutdown race separately verified in CL'}
    report['passed'] = after['G1']['passed'] and after['G2']['passed'] and after['G3']['correct'] >= 138 and all(r['identicalDecisionsAndProbabilities'] for r in areas.values())
    save(REPO / 'scripts/evidence/LAYAT-regression.json', report)
    print(json.dumps(report), flush=True)
    if not report['passed']:
        raise RuntimeError('Regression gate failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['before', 'after', 'summary'])
    parser.add_argument('--resume-existing', action='store_true')
    args = parser.parse_args()
    RUN.mkdir(parents=True, exist_ok=True)
    os.environ['NEYVIA_TOOL_AUTO_UPDATE'] = '0'
    os.environ['FLUXIO_WATCHDOG_AUTOSTART'] = '0'
    if args.phase == 'summary':
        summarize()
    else:
        regression(args.phase, args.resume_existing)
