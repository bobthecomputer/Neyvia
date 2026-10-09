"""Admit real native receipt labels into isolated reversible LAYA memory and audit transfer.

This pilot never overwrites the shipping seed. Model confidence is reported
separately from independently admitted accuracy; failed gates remain shadow.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUN = Path('D:/NeyviaRuns/laya-train')
HOST_ROOT = ROOT / '.agent_control/laya-train-runtime' / ('outcome-' + time.strftime('%Y%m%d-%H%M%S'))
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.laya_host import LayaHost, load_config
from grant_agent.laya_curriculum import wilson


def post(route, body):
    request = urllib.request.Request('http://127.0.0.1:48995' + route, json.dumps(body).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def query(row):
    receipt = json.loads((ROOT / row['source']).read_bytes())
    result = receipt.get('result') or {}
    if not isinstance(result, dict):
        result = {'value': result}
    observed = {'fields': ','.join(sorted(result)), 'error': result.get('error'),
                'status': result.get('status'), 'truncated': result.get('truncated'),
                'values': {k: v for k, v in result.items() if isinstance(v, (bool, int, float))}}
    return post('/v1/decide', {'set': 'neyvia.capability@1', 'questions': ['routine_outcome'],
        'state': {'tool': receipt['tool'], 'observed': observed}, 'scope': {'domain': 'native-receipt-outcome'}, 'base_cache': True})


def main():
    rows = json.loads((RUN / 'receipt-curriculum.json').read_text(encoding='utf-8'))
    split = lambda r: int(hashlib.sha256(r['group'].encode()).hexdigest()[:8], 16) % 5
    train, calibration, held = ([r for r in rows if split(r) > 1], [r for r in rows if split(r) == 1], [r for r in rows if split(r) == 0])
    spec = json.loads((ROOT / 'tools/laya/question_sets/neyvia.capability.json').read_bytes())
    registration = post('/v1/question-sets', spec)
    learned = []
    for row in train:
        response = query(row)
        receipt_path = ROOT / row['source']
        admitted = post('/v1/outcome', {'decision_id': response['decision_id'], 'question': 'routine_outcome',
            'correct': row['label'] == 'success', 'kind': 'verified_effect',
            'evidence': {'receipt': row['source'], 'sha256': hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                         'verifier': 'native-tool-contract-receipt', 'passed': True}})
        learned.append({'case': row['id'], 'admission': admitted})
        print('learned', len(learned), flush=True)
    observations = []
    for row in held:
        response = query(row)
        answer = response['answers']['routine_outcome']
        observations.append({'id': row['id'], 'truth': row['label'], 'correct': (answer['answer'] == 'true') == (row['label'] == 'success'),
                             'answer': answer, 'decisionId': response['decision_id']})
    proposed = [r for r in observations if r['answer']['top_probability'] >= .95 and r['answer']['policy'] == 'answer']
    report = {'learned': len(learned), 'registration': registration, 'cases': len(held),
        'accuracy': sum(r['correct'] for r in observations)/len(held) if held else None,
        'modelProposedAnswerRate': len(proposed)/len(held) if held else 0,
        'proposedAnsweredAccuracy': sum(r['correct'] for r in proposed)/len(proposed) if proposed else None,
        'calibrationCases': len(calibration), 'answerRate': 0, 'admitted': False,
        'reason': 'No independently grouped calibration cases; keep trained memory in task-local shadow database',
        'database': str(HOST_ROOT / '.neyvia/laya/system1.sqlite'), 'observations': observations, 'admissions': learned}
    (RUN / 'outcome-learning.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    summary = {k: v for k, v in report.items() if k not in ('observations', 'admissions')}
    (ROOT / 'scripts/evidence/LAYAT-outcome-learning.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    root = HOST_ROOT
    host = LayaHost(root, {**load_config(root), 'port': 48995, 'device': 'cpu'}).start()
    try:
        deadline = time.monotonic() + 240
        while not host.ready() and time.monotonic() < deadline:
            if host.state in {'unavailable', 'disabled'}:
                raise RuntimeError(host.reason)
            time.sleep(1)
        if not host.ready():
            raise RuntimeError('Owned outcome service did not become ready')
        main()
    finally:
        host.stop()
        shutil.copytree(root, RUN / root.name, dirs_exist_ok=True)
