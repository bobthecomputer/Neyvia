"""Verify and execute the frozen C1 panel without changing its manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'scripts/C1-comparison-run.json'


def verify(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 'neyvia.c1.computer-use-comparison.v1':
        raise ValueError('Unexpected comparison schema')
    tasks = data['tasks']
    frozen = {'tasks': tasks, 'fixtures': data['fixtures'],
              'repetitionsPerTask': data['protocol']['repetitionsPerTask'],
              'timeBudgetSecondsPerAttempt': data['protocol']['timeBudgetSecondsPerAttempt']}
    digest = hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(',', ':'),
                                       ensure_ascii=False).encode('utf-8')).hexdigest()
    if digest != data['taskFreeze']['sha256']:
        raise ValueError('Frozen task hash mismatch; issue a new comparison version')
    ids = [row['id'] for row in tasks]
    apps = [row['app'] for row in tasks]
    if len(tasks) < 15 or len(set(ids)) != len(tasks) or len(set(apps)) != len(tasks):
        raise ValueError('Expected 15 or more different app tasks with unique IDs')
    for row in tasks:
        if not row.get('fixture') or not row.get('instruction') or not row.get('postcondition'):
            raise ValueError('Incomplete frozen task: ' + row['id'])
    if data['environment']['allowedTcpPortsInclusive'] != [48701, 48709]:
        raise ValueError('C1 comparison port boundary changed')
    arms = data['protocol']['arms']
    if arms != ['neyvia', 'claude_computer_use', 'openai_computer_use']:
        raise ValueError('Comparison arms changed')
    if set(data['runs']) != set(arms):
        raise ValueError('Missing comparison arm record')
    for arm in arms:
        row = data['runs'][arm]
        if row['status'].startswith('pending') and row['attemptReceipt'] is not None:
            raise ValueError('Pending arm advertises an attempt receipt: ' + arm)
    return {'ok': True, 'status': data['status'], 'taskCount': len(tasks),
            'distinctApps': len(set(apps)), 'frozenPanelSha256': digest,
            'armStatuses': {arm: data['runs'][arm]['status'] for arm in arms},
            'modelsCalled': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--child', type=Path, help='Internal isolated Neyvia fixture attempt')
    parser.add_argument('--receipt', type=Path, default=ROOT / 'scripts/evidence/C1CMP.json')
    parser.add_argument('--arm', choices=['neyvia', 'openai_computer_use', 'claude_computer_use'])
    parser.add_argument('--series', choices=['baseline', 'repaired', 'paired'], default='baseline',
        help='Fresh five-repetition panel after repairs; original failures stay in the receipt')
    args = parser.parse_args()
    try:
        preflight = verify(args.manifest)
        if args.prepare or args.run or args.child:
            from c1_comparison_execution import execute
            execute(args, preflight)
        else:
            print(json.dumps(preflight, sort_keys=True))
    except (KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}), file=sys.stderr)
        sys.exit(1)
