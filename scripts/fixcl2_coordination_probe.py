"""Actual local workflow recorder journey through the CL host, with byte drift."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from fixcl_verify import REPO, bind_fixture_broker, environment, guards


def run(port):
    if port != 48828:
        raise ValueError('This FIXCL2 coordination probe owns port 48828 only')
    root = REPO / '.agent_control' / 'proofs' / ('FIXCL2-coordination-' + str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root)
    environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.cl import coordination_effects
    from grant_agent.neyvia_manuals import unwrap
    bound_paths = [REPO / item for item in (
        'src/grant_agent/cl/coordination_effects.py', 'src/grant_agent/cl/frontier_effects.py',
        'src/grant_agent/cl/effects.py', 'src/grant_agent/cl/protocol.py',
        'src/grant_agent/cl/host.py', 'src/grant_agent/workflow_manuals.py',
        'manuals/research.manual.json', 'manuals/cl/research.cl',
        'scripts/fixcl2_coordination_probe.py')]
    source_hashes = lambda: {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in bound_paths}
    source_start = source_hashes()
    prepare_broker_fixture(root)
    bind_fixture_broker(root)
    gateway = NeyviaToolGateway(root, allow_mutations=True, action_scope='FIXCL2-coordination', permission_mode='workspace')
    clock = unwrap(gateway.native.call('neyvia.time.now', {}))
    observed_success = isinstance(clock.get('unixSeconds'), (int, float)) and clock['unixSeconds'] > 0
    measurement = {'success': observed_success, 'unixSeconds': clock.get('unixSeconds'),
                   'subject': 'native time.now returned a positive Unix timestamp'}
    path = root / 'clock-measurement.json'
    path.write_text(json.dumps(measurement, sort_keys=True), encoding='utf-8')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {'events': [
        {'stage': 'question', 'data': {'question': 'Does the local native clock return a positive Unix timestamp?'}},
        {'stage': 'prior-art', 'data': {'sources': [
            {'source': 'Python wall clock', 'finding': 'Unix seconds advance from a fixed epoch'},
            {'source': 'Neyvia native time tool', 'finding': 'Exposes unixSeconds in its local result'}]}},
        {'stage': 'claim', 'data': {'prediction': 'The observed local timestamp will be positive',
                                    'falsifier': 'The observed timestamp is missing or nonpositive'}},
        {'stage': 'test', 'data': {'receipt': 'clock'}},
        {'stage': 'result', 'data': {'supported': observed_success,
                                     'limitations': ['One local clock read does not establish time synchronization']}}]}
    args = {'manual': 'research', 'report': report, 'evidence': {'clock': {'path': path.name, 'sha256': digest}},
            'outcomeQuality': 0.5, 'tokens': 1}
    host = Protocol(gateway)
    before = coordination_effects.snapshot_for(host, 'neyvia.workflow.record', args)
    native = unwrap(gateway.native.call('neyvia.workflow.record', args))
    effect = coordination_effects.checks_for(host, 'neyvia.workflow.record', args)
    native_pass = len(effect) == 1 and effect[0]['check'](args, native, before)
    forged = dict(native, sha256='0' * 64)
    forged_refused = not effect[0]['check'](args, forged, before)
    stale_args = dict(args, evidence={'clock': {'path': path.name, 'sha256': '0' * 64}})
    stale_refused = False
    try:
        coordination_effects.snapshot_for(host, 'neyvia.workflow.record', stale_args)
    except ValueError:
        stale_refused = True
    cl_args = {**args, 'tokens': 2}
    cl_target = coordination_effects.snapshot_for(host, 'neyvia.workflow.record', cl_args)
    source = ('G: time.now()["unixSeconds"] > 0\nrun research.verify-and-record(' +
              'report=' + json.dumps(report, separators=(',', ':')) +
              ',evidence=' + json.dumps(args['evidence'], separators=(',', ':')) +
              ',outcomeQuality=0.5,tokens=2)\ndone()')
    cl_host = Protocol(gateway)
    passed = cl_host.run(source, action_id='workflow-record')
    saved = Path(native['receipt'])
    initial_done = cl_host.completion()
    path.write_text(json.dumps({**measurement, 'success': False}, sort_keys=True), encoding='utf-8')
    stale_done = cl_host.completion()
    checks = {
        'realClockMeasurement': observed_success,
        'nativeEffectReadback': native_pass,
        'forgedResultRefused': forged_refused,
        'staleSourceRefusedBeforeDispatch': stale_refused,
        'clProcedureAccepted': passed.get('ok') is True,
        'savedReceiptExactBytes': saved.is_file() and hashlib.sha256(saved.read_bytes()).hexdigest() == native['sha256'],
        'initialCompletion': initial_done.get('status') == 'completed',
        'clCreatedDistinctReceipt': not cl_target['before'].get('exists') and
            Path(cl_target['target']).is_file() and
            hashlib.sha256(Path(cl_target['target']).read_bytes()).hexdigest() == cl_target['digest'],
        'sourceDriftRevokesCompletion': stale_done.get('status') == 'incomplete',
        'pureIntentClassifiedRead': coordination_effects.readonly('neyvia.intent.checklist', {}) is True,
        'pureWorkflowDetailsClassifiedRead': coordination_effects.readonly('neyvia.workflow.details', {}) is True,
        'timeBudgetRetainedFrontier': coordination_effects.readonly('neyvia.time.budget', {}) is None,
    }
    source_end = source_hashes()
    checks['sourceUnchanged'] = source_start == source_end
    return {'schema': 'neyvia.FIXCL2.coordination.v1', 'root': str(root), 'port': port,
            'checks': checks, 'passCount': sum(checks.values()), 'total': len(checks),
            'sourceHashesAtStart': source_start, 'sourceHashesAtEnd': source_end,
            'native': {'sha256': native['sha256'], 'receipt': native['receipt'], 'effectCheck': effect[0]['name']},
            'cl': {'ok': passed.get('ok'), 'status': passed.get('status'), 'text': passed.get('text'),
                   'manuals': [row.get('manualUse', {}).get('manual') for row in passed.get('results', []) if row.get('manualUse')]},
            'initialCompletion': initial_done.get('status'), 'afterSourceDrift': stale_done.get('status')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.port)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"coordination {result['passCount']}/{result['total']} {args.output}")
    if result['passCount'] != result['total']:
        print(json.dumps(result['checks'], indent=2))
        sys.exit(1)


if __name__ == '__main__':
    main()
