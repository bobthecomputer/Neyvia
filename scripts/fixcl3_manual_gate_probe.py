"""Exercise approved canonical wrapper preservation and actual recursion refusals."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
import time
from fixcl_verify import REPO, guards, environment, bind_fixture_broker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48821, 48830):
        parser.error('Explicit assigned port required')
    root = REPO / '.agent_control/proofs' / ('FIXCL3-manual-gate-' + str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root); environment(root, args.port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    bind_fixture_broker(root)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.neyvia_manuals import unwrap, get_manual, checked_action_output
    registry = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace').native
    sources = [REPO / path for path in ('src/grant_agent/manual_contracts.py',
        'src/grant_agent/neyvia_manuals.py', 'src/grant_agent/cl/protocol.py',
        'manuals/manuals-next.manual.json', 'manuals/cl/manuals-next.cl', 'scripts/fixcl3_manual_gate_probe.py')]
    hashes = lambda: {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    start = hashes(); calls = {}
    def call(key, name, value):
        tool = 'neyvia.manual.' + name
        result = checked_action_output(registry, tool, registry.call(tool, value))
        calls[key] = result
        (root / 'partial-calls.json').write_text(json.dumps(calls, indent=2), encoding='utf-8')
        return unwrap(result) if result.get('ok') is not False else result
    validated = call('canonical-validation', 'validate', {'id': 'manuals-next'})
    original = call('original-version', 'versions', {'id': 'manuals-next'})
    patch = call('unrelated-patch', 'frontier', {'id': 'manuals-next', 'note': 'Scoped canonical-control conservation',
        'observed': {'fixture': True}, 'operations': [{'op': 'add', 'path': '/chapters/versions/guidance/-',
        'value': 'Disposable fixture: canonical wrappers remain exact.'}]})
    promotion = call('approved-promotion', 'patch.apply', {'id': 'manuals-next', 'patchId': patch['patchId'],
        'expectedSha256': original['sha256'], 'approved': True, 'reviewer': 'FIXCL3 scoped fixture',
        'evidence': ['Actual disposable unrelated guidance edit; exact wrappers conserved.']})
    current = call('promoted-version', 'versions', {'id': 'manuals-next'})
    data = get_manual('manuals-next')[2]
    chapter, row = next((key, value) for key, value in data['chapters'].items() if 'verified-run' in value['procedures'])
    step = deepcopy(row['procedures']['verified-run']['steps'][0]); step['save'] = 'introduced-recursion'
    bad = call('recursive-patch', 'frontier', {'id': 'manuals-next', 'note': 'Real recursion refusal fixture',
        'observed': {'fixture': True}, 'operations': [{'op': 'add',
        'path': '/chapters/' + chapter + '/procedures/verified-run/steps/-', 'value': step}]})
    refused = call('recursive-promotion', 'patch.apply', {'id': 'manuals-next', 'patchId': bad['patchId'],
        'expectedSha256': current['sha256'], 'approved': True, 'reviewer': 'FIXCL3 scoped fixture',
        'evidence': ['Expected actual refusal; no version mutation.']})
    retained = call('after-refusal-version', 'versions', {'id': 'manuals-next'})
    before_runs = list((root / '.neyvia/manual-runs').glob('*.json'))
    nested = call('native-nested-run', 'run', {'id': 'manuals-next', 'chapter': chapter,
        'procedure': 'verified-run', 'inputs': {'id': 'notes', 'procedure': 'read', 'inputs': {}}})
    checks = {'canonicalManualGrounded': validated.get('ok') is True,
        'unrelatedApprovedEditPromoted': promotion.get('ok') is True and current['sha256'] != original['sha256'],
        'newRecursionPromotionRefused': refused.get('ok') is False and 'Recursive manual execution' in str(refused),
        'versionUnchangedAfterRefusal': retained['sha256'] == current['sha256'],
        'nativeNestedExecutionRefused': nested.get('ok') is False and 'Recursive manual execution' in str(nested),
        'noNestedRunStateWritten': before_runs == list((root / '.neyvia/manual-runs').glob('*.json')),
        'sourcesUnchanged': start == hashes()}
    proof = {'ok': all(checks.values()), 'root': str(root), 'port': args.port, 'checks': checks, 'calls': calls,
        'sourceHashesAtStart': start, 'sourceHashesAtEnd': hashes(),
        'boundary': 'Exact canonical CL declarations survive approved unrelated edits; actual native nesting and introduced recursion are refused.'}
    (REPO / 'scripts/evidence/FIXCL3-manual-gate.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'ok': proof['ok'], 'checks': checks}))
    return 0 if proof['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
