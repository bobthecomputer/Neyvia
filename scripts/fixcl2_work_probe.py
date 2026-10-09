"""Disposable real CL work actions with durable-state and refusal receipts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from fixcl_verify import environment, guards  # noqa: E402


SOURCE_PATHS = (
    'src/grant_agent/cl/frontier_effects.py', 'src/grant_agent/cl/work_effects.py',
    'src/grant_agent/cl/effects.py', 'src/grant_agent/cl/codecs.py',
    'src/grant_agent/cl/protocol.py', 'src/grant_agent/cl/host.py',
    'src/grant_agent/creative_tools.py', 'src/grant_agent/adaptive_work.py',
    'src/grant_agent/operation_adapters.py', 'src/grant_agent/native_tools.py',
    'manuals/adaptive-work.manual.json', 'manuals/cl/adaptive-work.cl',
    'config/neyvia_manuals.json', 'scripts/fixcl2_work_probe.py',
)


def hashes():
    return {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in SOURCE_PATHS}


def row(result):
    return {'ok': result.get('ok'), 'status': result.get('status'),
            'detail': (result.get('results') or [{}])[-1].get('cl', '')[-300:],
            'checks': [check for item in result.get('results', []) for check in item.get('checks', [])],
            'manualUse': [item.get('manualUse') for item in result.get('results', []) if item.get('manualUse')],
            'failure': next((item.get('result', {}).get('error') or item.get('error')
                             for item in result.get('results', []) if not item.get('ok')), None)}


def run(root: Path, port: int):
    if port not in range(48821, 48830):
        raise ValueError('Use an explicit assigned FIXCL2 port')
    root.mkdir(parents=True, exist_ok=False)
    guards(root)
    environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    start = hashes()
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.cl.manuals import cl_to_manual
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace')
    identity = 'fixture-work'
    path = root / '.agent_control' / 'adaptive_work' / (identity + '.json')
    events = path.with_suffix('.events.jsonl')
    results = {}
    absent = root / '.agent_control' / 'adaptive_work' / 'absent-work.json'
    results['read-initializer-refusal'] = row(Protocol(gateway).run(
        'G local: work.state(workId="absent-work")["state"]["revision"] == 0\ndone()',
        action_id='fixcl2-work-read-initializer'))
    results['read-initializer-refusal']['fileAbsent'] = not absent.exists()
    cases = (
        ('focus', 'work.focus(workId="fixture-work",text=" Resolve the selected workspace audit ")'),
        ('problem', 'work.problem(workId="fixture-work",text=" Missing effect observer ",blocker="Owner receipt needed")'),
        ('constraint', 'work.constraint(workId="fixture-work",text=" Stay inside this disposable workspace ")'),
    )
    states = {}
    for label, action in cases:
        results[label] = row(Protocol(gateway).run(
            'G local: time.now()["unixSeconds"] > 0\n' + action + '\ndone()',
            action_id='fixcl2-work-' + label))
        states[label] = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    problem_id = states['problem']['problems'][-1]['id'] if states['problem'] else ''
    update = ('work.update_problem(workId="fixture-work",problemId=' + json.dumps(problem_id) +
              ',status="blocked",need="test")')
    results['update'] = row(Protocol(gateway).run(
        'G local: time.now()["unixSeconds"] > 0\n' + update + '\ndone()',
        action_id='fixcl2-work-update'))
    states['update'] = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    if not path.exists():
        return {'schema': 'neyvia.FIXCL2.work.v1', 'root': str(root), 'port': port,
                'sourceHashesAtStart': start, 'sourceHashesAtEnd': hashes(),
                'results': results, 'checks': {'four_actions_bound': False}}
    stable_bytes = path.read_bytes()
    stable_events = events.read_bytes()
    results['unknown-problem'] = row(Protocol(gateway).run(
        'G local: time.now()["unixSeconds"] > 0\n'
        'work.update_problem(workId="fixture-work",problemId="missing-problem",status="resolved",need="reflect")\ndone()',
        action_id='fixcl2-work-missing'))
    results['unknown-problem']['stateUnchanged'] = path.read_bytes() == stable_bytes and events.read_bytes() == stable_events
    corrupt = root / '.agent_control' / 'adaptive_work' / 'corrupt-work.json'
    corrupt.write_bytes(b'{broken fixture bytes\n')
    results['corrupt-state'] = row(Protocol(gateway).run(
        'G local: time.now()["unixSeconds"] > 0\n'
        'work.focus(workId="corrupt-work",text="must refuse")\ndone()',
        action_id='fixcl2-work-corrupt'))
    results['corrupt-state']['stateUnchanged'] = corrupt.read_bytes() == b'{broken fixture bytes\n'
    after = hashes()
    accepted = all(results[name]['ok'] is True and
                   any(check.get('name') == 'effect-work-' + ('update-problem' if name == 'update' else name)
                       and check.get('passed') is True for check in results[name]['checks']) and
                   any(use.get('manual') == 'adaptive-work' and use.get('status') == 'admitted'
                       for use in results[name]['manualUse'])
                   for name in ('focus', 'problem', 'constraint', 'update'))
    return {'schema': 'neyvia.FIXCL2.work.v1', 'root': str(root), 'port': port,
            'sourceHashesAtStart': start, 'sourceHashesAtEnd': after,
            'results': results,
            'finalState': states['update'],
            'eventCount': len(stable_events.splitlines()),
            'remainingLocalFrontierAtThisLayer': [
                {'actions': ['neyvia.session.new'], 'reason': 'Provider broker request and runtime acknowledgement are required; an overlay alone cannot prove launch.'},
                {'actions': ['neyvia.session.cluster'], 'reason': 'Applying or undoing project assignments needs a selected broker inventory, exact prior assignments, and an executable procedure.'},
                {'actions': ['neyvia.sidebar.tidy'], 'reason': 'Confirmed cleanup and undoLast require fresh broker stale/archive safety and conservation across every selected chat.'},
                {'actions': ['neyvia.sidebar.preview', 'neyvia.sidebar.confirm', 'neyvia.sidebar.undo'],
                 'reason': 'Subject-bound UI-bus predicates exist but this layer has no current executable sidebar procedure or real CL receipt.'},
                {'actions': ['work.state'], 'reason': 'The nominal read creates initial JSON state; it is classified as mutation and refused as a G observer.'},
            ],
            'checks': {
                'four_actions_bound': accepted,
                'exact_revisions': [states[name]['revision'] if states[name] else None
                                    for name in ('focus', 'problem', 'constraint', 'update')] == [1, 2, 3, 4],
                'focus_and_constraint_conserved': states['update']['focus'] == states['focus']['focus']
                    and states['update']['constraints'] == states['constraint']['constraints'],
                'unknown_problem_refused': results['unknown-problem']['ok'] is False
                    and results['unknown-problem']['stateUnchanged'],
                'corrupt_state_refused': results['corrupt-state']['ok'] is False
                    and results['corrupt-state']['stateUnchanged'],
                'read_initializer_refused': results['read-initializer-refusal']['ok'] is False
                    and results['read-initializer-refusal']['fileAbsent'],
                'manual_roundtrip': cl_to_manual((REPO / 'manuals/cl/adaptive-work.cl').read_text(encoding='utf-8'))
                    == json.loads((REPO / 'manuals/adaptive-work.manual.json').read_text(encoding='utf-8')),
                'source_unchanged': start == after,
            }}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = REPO / '.agent_control' / 'proofs' / ('FIXCL2-work-' + str(time.time_ns()))
    receipt = run(root, args.port)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'checks': receipt['checks'], 'output': str(args.output)}))
    sys.exit(0 if all(receipt['checks'].values()) else 1)
