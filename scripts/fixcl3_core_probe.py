"""Run the actual CL initializer and independent capsule hash verification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from fixcl_verify import REPO, environment, guards, bind_fixture_broker


def write_manual():
    from grant_agent.native_tools import NativeToolRegistry
    from grant_agent.cl.manuals import manual_to_cl, cl_to_manual
    registry = NativeToolRegistry(REPO / '.agent_control/fixcl3-core-schema')
    names = ['work.state', 'semantic.proof.verify']
    schemas = {name: registry.describe(name)['inputSchema'] for name in names}
    data = {'schema': 'neyvia.manual.v1', 'id': 'local-integrity', 'kind': 'environment',
            'schemas': schemas, 'chapters': {'overview': {
                'title': 'Initialize local work and verify exact proof artifact bytes',
                'state': {}, 'checks': {}, 'judge': {}, 'pitfalls': [], 'guidance': [],
                'frontier': ['Artifact integrity does not establish a capsule semantic claim.',
                             'work.state initializes absent stores and cannot be used as a pure goal observer.'],
                'actions': {}, 'procedures': {}}}}
    chapter = data['chapters']['overview']
    for name in names:
        key = name.rsplit('.', 1)[-1]
        chapter['actions'][key] = {'tool': name, 'schema': name, 'returns': {'type': 'object'},
            'pre': 'Selected safe workspace identity and intact source bytes',
            'effect': 'Exact owning state persists, freshly independently reread', 'reversible': False}
        chapter['procedures'][key] = {'goal': chapter['actions'][key]['effect'],
            'inputs': schemas[name], 'steps': [{'action': key, 'args': {
                field: {'$input': field} for field in schemas[name]['required']}, 'save': 'effect'}]}
    text = manual_to_cl(data)
    if cl_to_manual(text) != data:
        raise ValueError('Manual does not roundtrip')
    (REPO / 'manuals/local-integrity.manual.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
    (REPO / 'manuals/cl/local-integrity.cl').write_text(text, encoding='utf-8', newline='\n')


def run(port, output):
    root = REPO / '.agent_control/proofs' / ('FIXCL3-core-' + str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root); environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol, unwrap
    from grant_agent.cl import effects
    from grant_agent.ui_command_bus import bus_for
    prepare_broker_fixture(root); bind_fixture_broker(root)
    paths = [*sorted((REPO / 'src/grant_agent/cl').glob('*.py')),
             REPO / 'manuals/local-integrity.manual.json', REPO / 'manuals/cl/local-integrity.cl', Path(__file__)]
    hashes = lambda: {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    start = hashes()
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace')
    protocol = Protocol(gateway)
    source = 'G: time.now()["unixSeconds"] > 0\nrun local-integrity.state(workId="fresh")\ndone()'
    initialized = protocol.run(source, action_id='initialize-local-work')
    path = root / '.agent_control/adaptive_work/fresh.json'
    initial_done = protocol.completion()
    from grant_agent.adaptive_work import AdaptiveWorkStore
    AdaptiveWorkStore(root, 'fresh').change_focus('new focus')
    drift = protocol.completion()
    artifact = root / 'clock.json'
    clock = unwrap(gateway.native.call('neyvia.time.now', {}))
    artifact.write_text(json.dumps(clock), encoding='utf-8')
    created = unwrap(gateway.native.call('semantic.proof.create', {
        'capsuleId': 'local-proof', 'claim': 'A local clock response was persisted',
        'build': {}, 'environment': {'port': port}, 'startingState': {},
        'journey': [{'tool': 'neyvia.time.now'}], 'actions': [{'tool': 'neyvia.time.now'}],
        'artifacts': [{'path': 'clock.json', 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}],
        'result': {'status': 'passed', 'verified': True}, 'reproduction': {}}))
    args = {'proofId': created['proofId']}
    p = Protocol(gateway)
    source_verify = 'G: time.now()["unixSeconds"] > 0\nrun local-integrity.verify(proofId="local-proof")\ndone()'
    verified = p.run(source_verify, action_id='verify-proof-integrity')
    verified_done = p.completion()
    saved = json.loads(Path(created['artifactPath']).read_bytes())
    artifact.write_text('changed exact artifact bytes', encoding='utf-8')
    invalidated = p.completion()
    checks = {'initializerPositiveCL': initialized.get('ok') is True,
              'initializerFreshDone': initial_done.get('status') == 'completed',
              'initializerPersisted': path.is_file(), 'initializerDriftRefused': drift.get('status') == 'incomplete',
              'proofVerifierPositiveCL': verified.get('ok') is True,
              'proofVerifierFreshDone': verified_done.get('status') == 'completed',
              'artifactIntegrityVerified': saved['verification'].get('artifactsVerified') is True,
              'semanticClaimStillUnproven': saved['verification'].get('claimProven') is False,
              'artifactDriftRefused': invalidated.get('status') == 'incomplete',
              'sourceUnchanged': start == hashes()}
    proof = {'schema': 'neyvia.FIXCL3.core.v1', 'root': str(root), 'port': port,
             'sourceHashesAtStart': start, 'sourceHashesAtEnd': hashes(), 'checks': checks,
             'manualReceipts': [row['payload'] for row in bus_for(root).since(0) if row['action'] == 'cl.manual.use'],
             'transcripts': {'work.state': initialized, 'semantic.proof.verify': verified,
                             'initializedDone': initial_done, 'workDrift': drift,
                             'verifiedDone': verified_done, 'artifactDrift': invalidated},
             'ok': all(checks.values()), 'boundary': 'Real local initialization and artifact hashes; semantic proof claim remains unproven.'}
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'ok': proof['ok'], 'checks': checks}))
    return 0 if proof['ok'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int)
    parser.add_argument('--output', type=Path, default=REPO / 'scripts/evidence/FIXCL3-core.json')
    parser.add_argument('--write-manual', action='store_true')
    args = parser.parse_args()
    if args.write_manual:
        write_manual()
    else:
        if args.port not in range(48821, 48830): parser.error('Explicit assigned port required')
        raise SystemExit(run(args.port, args.output))
