"""Production acceptance journeys and explicit disposable-state fault injection.

This is a CLI proof artifact, not a pytest suite. Native CAS writes, fresh reads
and real Codex providers supply all accepted effects and model answers.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import time
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from grant_agent.efficiency_cascade import Cascade
from grant_agent.transition_memory import TransitionStore, atomic_json, digest
from grant_agent.neyvia_agent import NeyviaToolGateway
from grant_agent.neyvia_manuals import unwrap


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve() / ('adverse-acceptance-'+uuid.uuid4().hex)
    root.mkdir(parents=True, exist_ok=True)
    output = Path(args.output)
    report = {'passed': False, 'root': str(root), 'checks': [], 'nativeCalls': [], 'decisions': []}

    def save():
        atomic_json(output, report)

    def check(condition, label):
        if not condition:
            raise AssertionError(label)
        report['checks'].append(label)
        save()

    gateway = NeyviaToolGateway(root, allow_mutations=True, action_scope='T14-acceptance',
                               permission_mode='workspace')

    def native(tool, arguments):
        row = unwrap(gateway.call_native(tool, arguments, action_id=uuid.uuid4().hex if tool == 'workspace.write' else ''))
        report['nativeCalls'].append({'tool': tool, 'arguments': arguments, 'result': row})
        save()
        return row

    file = root / 'journey.txt'
    file.write_text('initial', encoding='utf-8')

    def observe():
        row = native('workspace.read', {'path': 'journey.txt'})
        independently = file.read_bytes()
        check(row['sha256'] == hashlib.sha256(independently).hexdigest(), 'native observer SHA agrees with independent file bytes')
        return {'content': row['content'], 'sha256': row['sha256']}

    def execute(operation):
        check(operation['type'] == 'native-call' and operation['tool'] == 'workspace.write', 'replay executes an explicitly permitted native write')
        return native(operation['tool'], operation['arguments'])

    scope = {'workspace': str(root), 'application': 'native-file', 'tools': ['workspace.read', 'workspace.write']}
    store = TransitionStore(root)
    rows = []
    for content in ['cobalt', 'orchard']:
        before = observe()
        operation = {'type': 'native-call', 'tool': 'workspace.write', 'arguments': {'path': 'journey.txt', 'content': content, 'expectedSha256': before['sha256']}}
        actual = execute(operation)
        after = observe()
        check(after['content'] == content, 'CAS write effect independently verified '+content)
        receipt_path = root / ('successful-'+content+'.json')
        atomic_json(receipt_path, {'status': 'completed', 'source': 'real-native-CAS-journey', 'operation': operation,
                                  'effect': after, 'checks': [{'passed': actual.get('toolResult', actual).get('sha256') == after['sha256']}, {'passed': after['content'] == content}]})
        rows.append(store.learn({'type': 'write-file', 'content': content}, before, operation, after,
                                {'type': 'escalate', 'reason': 'hash-disagreement'}, {'receiptPath': str(receipt_path)}, scope))
    operation = {'type': 'sequence', 'steps': [{'operation': r['operation'], 'preconditions': r['preconditions'], 'effect': r['effect']} for r in rows]}
    composite_path = root / 'composite-success.json'
    atomic_json(composite_path, {'status': 'completed', 'source': 'actual-two-step-CAS-journey', 'operation': operation,
                                'effect': rows[-1]['effect'], 'checks': [{'passed': True, 'observedNativeReceiptCount': len(report['nativeCalls'])}]})
    composite = store.compose(rows, {'type': 'write-sequence', 'name': 'two-native-writes'}, {'receiptPath': str(composite_path)}, scope)
    # Reset only the disposable fixture, then replay through production native CAS.
    file.write_text('initial', encoding='utf-8')
    replay = store.replay(composite, execute, observe, scope, rows[0]['preconditions'])
    check(replay['status'] == 'completed' and file.read_text(encoding='utf-8') == 'orchard', 'positive composite learned from actual journey replays two real native effects')

    def rejected(fn, label):
        try:
            fn()
        except ValueError:
            check(True, label)
            return
        raise AssertionError(label)

    rejected(lambda: store.replay(rows[0], execute, observe, {**scope, 'application': 'other'}, rows[0]['preconditions']), 'changed scope denies replay')
    rejected(lambda: store.replay(rows[0], execute, observe, scope, rows[0]['preconditions']), 'fresh changed preconditions deny replay before write')
    expired = store.learn({'type': 'expiry'}, rows[0]['preconditions'], rows[0]['operation'], rows[0]['effect'],
                          {'type': 'escalate'}, rows[0]['provenance'], scope, ttl_seconds=.001)
    time.sleep(.005)
    check(store.lookup(expired['goal'], expired['preconditions'], scope)['status'] == 'missing', 'expired learned row is ineligible')
    provenance_file = Path(rows[0]['provenance']['receiptPath'])
    provenance_file.write_text(provenance_file.read_text(encoding='utf-8')+' ', encoding='utf-8')
    check(store.lookup(rows[0]['goal'], rows[0]['preconditions'], scope)['status'] == 'conflict', 'modified source receipt SHA rejects provenance and requires escalation')

    schema = {'type': 'object', 'properties': {'color': {'type': 'string'}}, 'required': ['color'], 'additionalProperties': False}
    expected = {'color': 'cobalt'}
    valid = lambda answer: answer == expected
    cascade = Cascade(root / 'routing')
    call_scope = {'application': 'acceptance-live-provider'}

    def decide(prompt, **kwargs):
        row = cascade.decide(prompt, schema, scope=call_scope, preconditions={'observedColor': 'cobalt'}, validate=valid, **kwargs)
        report['decisions'].append(row)
        save()
        return row

    uncertain = decide('Return the color cobalt as a structured color object.', system1=lambda *a, **kw: {'answer': expected, 'confidence': False})
    check(uncertain['route'] == 'big' and uncertain['modelCalls'][0]['model'] == 'gpt-6.1-sol', 'System One uncertainty escalates directly to real Sol and validates answer')
    invalid = decide('Give the color cobalt as the structured color object.', script=lambda: {'color': 'incorrect'})
    check(invalid['route'] == 'big', 'invalid deterministic answer rejected and real Sol resolves it')
    bypass_calls = []
    prompt = 'Exact UI value for ID 00002486 and date 2026-10-03 is color cobalt. Return the color object.'
    bypass = decide(prompt, script=lambda: expected, learn=False)
    cached = decide(prompt, system1=lambda *a, **kw: bypass_calls.append(True), learn=False)
    check(cached['route'] == 'cache' and not bypass_calls and not cached['modelCalls'], 'exact digits ID date UI values bypass approximate System One and use validated cache without provider calls')

    conflict_prompt = 'Return the color cobalt; resolve conflicting persisted observations using the original requested color.'
    goal = {'type': 'decision', 'promptSha256': digest(conflict_prompt), 'schemaSha256': digest(schema)}
    bound_scope = {**call_scope, 'workspace': str(cascade.root)}
    pre = {'observedColor': 'cobalt'}
    # Conflicting real native source observations are bound into explicit source receipts.
    # The accepted answer is subsequently obtained from a real provider, never injected.
    for color in ['cobalt', 'orchard']:
        observation = next(row['result'] for row in report['nativeCalls'] if row['tool'] == 'workspace.read' and row['result'].get('content') == color)
        answer = {'color': observation['content']}
        op = {'type': 'decision', 'answer': answer}
        receipt = cascade.root / ('conflicting-observed-'+color+'.json')
        atomic_json(receipt, {'status': 'completed', 'source': 'actual-native-observation-controlled-conflict', 'operation': op,
                             'effect': {'answer': answer}, 'checks': [{'passed': observation['sha256'] == hashlib.sha256(color.encode()).hexdigest()}]})
        cascade.transitions.learn(goal, pre, op, {'answer': answer}, {'type': 'escalate'}, {'receiptPath': str(receipt)}, bound_scope)
    conflict = decide(conflict_prompt)
    check(conflict['route'] == 'big' and any(s['status'] == 'conflict' for s in conflict['trace']), 'conflicting verified native observations force real Sol escalation')
    report['metrics'] = cascade.metrics()
    report['passed'] = True
    save()
    print(json.dumps({'passed': True, 'checks': len(report['checks']), 'realProviderCalls': sum(len(x['modelCalls']) for x in report['decisions'])}))


if __name__ == '__main__':
    main()
