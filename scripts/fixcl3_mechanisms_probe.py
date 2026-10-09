"""Real frozen candidate competition and durable transcript compaction witnesses."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import time
from fixcl_verify import REPO, environment, guards


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48821, 48830):
        parser.error('Assigned explicit port required')
    root = REPO / '.agent_control/proofs' / ('FIXCL3-mechanisms-' + str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root); environment(root, args.port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    from grant_agent.neyvia_gateway import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.cl.lab_context_effects import SUPPORTED, snapshot_for
    from grant_agent.ui_command_bus import bus_for
    from grant_agent.workspace_intelligence import WorkspaceIntelligence
    from grant_agent.improvement_lab import ImprovementLab
    from grant_agent.context_engine import DurableContextEngine
    proof = {'schema': 'neyvia.FIXCL3.mechanisms.v1', 'root': str(root), 'port': args.port,
        'boundary': 'Actual frozen local artifact comparison and lossless durable transcript compaction; no provider/model quality inference.',
        'checks': {}, 'transcripts': {}, 'witnesses': []}
    paths = [REPO / p for p in ('src/grant_agent/cl/lab_context_effects.py', 'src/grant_agent/cl/record_effects.py',
        'src/grant_agent/improvement_tools.py', 'src/grant_agent/improvement_lab.py', 'src/grant_agent/context_engine.py',
        'src/grant_agent/cl/integration.py',
        'manuals/local-mechanisms.manual.json', 'manuals/cl/local-mechanisms.cl', 'scripts/fixcl3_mechanisms_probe.py')]
    hashes = lambda: {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    proof['sourceHashesAtStart'] = hashes()
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace', action_scope='fixture-context')
    WorkspaceIntelligence(root, 'fixture-context').configure_collaboration({'evaluation': True},
        expected_revision=0, operator_identity='FIXCL3-disposable-owner')
    source = root / 'source'; source.mkdir()
    (source / 'score.json').write_text('{"score":3}', encoding='utf-8')
    original = (source / 'score.json').read_bytes()
    engine = DurableContextEngine(root, 'fixture-context', max_context_tokens=1000, reserve_tokens=1000)
    engine.append('system', 'Never lose this exact instruction', kind='instruction', pinned=True)
    blob = engine.append('tool', 'original archived tool bytes ' * 600, kind='tool_output', reported_tokens=5000)
    for i in range(20):
        engine.append('user', 'historical-unique-' + str(i) + ' ' + 'content ' * 150, reported_tokens=500)
    cases = [
        ('lab.instrument', {'identity': 'limit', 'spec': {'kind': 'json_numeric', 'key': 'score', 'max': 5}}),
        ('lab.competition', {'workId': 'fixture-context', 'identity': 'frozen', 'source': 'source',
            'candidates': ['baseline', 'candidate'], 'instruments': ['limit']}),
        ('lab.compare', {'workId': 'fixture-context', 'identity': 'frozen', 'targets': {'baseline': 'score.json', 'candidate': 'score.json'}}),
        ('context.compact', {'sessionId': 'fixture-context', 'focus': 'Preserve exact evidence', 'targetRatio': .25, 'maxContextTokens': 1000}),
    ]
    if {name for name, _ in cases} != SUPPORTED:
        raise ValueError('Each admitted adapter requires an actual positive CL witness')
    lab = ImprovementLab(root)
    for index, (name, payload) in enumerate(cases):
        if name == 'lab.compare':
            from grant_agent.experiment_studio import ExperimentStudio
            identity = hashlib.sha256(b'frozen:candidate').hexdigest()[:32]
            manifest = ExperimentStudio(root).inspect(identity)
            if manifest.get('status') == 'not_found':
                proof['transcripts'][name] = {'ok': False, 'status': 'blocked', 'reason': 'Positive competition prerequisite was refused; no candidate exists'}
                proof['checks'][name + '-CLDone'] = False
                continue
            snapshot = manifest['snapshot']
            from pathlib import Path
            # An actual separate candidate edit, preserving the source/baseline.
            (Path(snapshot) / 'score.json').write_text('{"score":99}', encoding='utf-8')
        protocol = Protocol(gateway)
        before = snapshot_for(protocol, name, payload)
        action_id = 'FIXCL3-mechanisms-' + str(index)
        inputs = ','.join(k + '=' + json.dumps(v) for k, v in payload.items() if k != 'sessionId')
        lines = 'G local: time.now()["unixSeconds"] > 0\nrun local-mechanisms.verify-' + name.replace('.', '-') + '(' + inputs + ')\ndone()'
        result = protocol.run(lines, action_id=action_id)
        print(json.dumps({'tool': name, 'ok': result.get('ok'), 'status': result.get('status'),
                          'error': result.get('error')}), flush=True)
        proof['transcripts'][name] = result
        proof['checks'][name + '-CLDone'] = result.get('ok') is True
        uses = [event['payload'] for event in bus_for(root).since(0) if event['action'] == 'cl.manual.use']
        admitted = [row for row in uses if row.get('tool') == name and row.get('manual') == 'local-mechanisms' and
            row.get('status') == 'admitted' and row.get('actionIdentity', '').startswith(action_id + ':') and row.get('effectChecks')]
        proof['checks'][name + '-manualReceipt'] = len(admitted) == 1
        proof['checks'][name + '-freshCompletion'] = protocol.run('done()', action_id=action_id).get('ok') is True
        if not result.get('ok'):
            continue
        if name == 'context.compact':
            with engine._connection() as db:
                row = dict(db.execute('SELECT * FROM context_events WHERE active=0 ORDER BY sequence LIMIT 1').fetchone())
                db.execute('UPDATE context_events SET content=? WHERE event_id=?', ('lost historical content', row['event_id']))
            drift = protocol.run('done()', action_id=action_id)
            with engine._connection() as db:
                db.execute('UPDATE context_events SET content=? WHERE event_id=?', (row['content'], row['event_id']))
            from pathlib import Path
            original_blob = Path(blob.artifact_path).read_bytes()
            Path(blob.artifact_path).write_bytes(b'changed archived original tool bytes')
            proof['checks']['context.compact-archivedBlobDriftRefused'] = protocol.run('done()', action_id=action_id).get('ok') is False
            Path(blob.artifact_path).write_bytes(original_blob)
            drift_subject = str(engine.db_path) + '#' + row['event_id']
        else:
            if name == 'lab.instrument':
                path = lab.base / 'instrument-limit.json'
            elif name == 'lab.competition':
                from grant_agent.experiment_studio import ExperimentStudio
                from pathlib import Path
                identity = hashlib.sha256(b'frozen:baseline').hexdigest()[:32]
                path = Path(ExperimentStudio(root).inspect(identity)['snapshot']) / 'score.json'
            else:
                path = next(p for p in lab.base.glob('receipt-*.json') if str(p) not in before['files'])
            clean = path.read_bytes(); path.write_bytes(b'independently changed artifact')
            drift = protocol.run('done()', action_id=action_id)
            path.write_bytes(clean); drift_subject = str(path)
        proof['checks'][name + '-freshDriftRefused'] = drift.get('ok') is False
        proof['transcripts'][name + '-drift'] = drift
        proof['witnesses'].append({'tool': name, 'actionIdentity': action_id, 'positiveCL': result,
            'manualReceipt': admitted, 'freshDriftRefused': drift.get('ok') is False, 'driftSubject': drift_subject})
    receipts = [json.loads(p.read_bytes()) for p in lab.base.glob('receipt-*.json')]
    compared = next((r for r in receipts if r.get('kind') == 'competition'), {})
    rows = compared.get('candidates', [])
    proof['checks']['positiveBaselineAndNegativeCandidateRetained'] = len(rows) == 2 and rows[0]['eligible'] is True and rows[1]['eligible'] is False and compared['promoted'] is False
    proof['checks']['sourceUnchangedByCandidateEdit'] = (source / 'score.json').read_bytes() == original
    history = engine.search('historical-unique-0', limit=50)
    proof['checks']['archivedOriginalRetrievable'] = any(r['content'].startswith('historical-unique-0 ') and r['active'] is False for r in history)
    proof['checks']['exactInstructionProtected'] = any(r.content == 'Never lose this exact instruction' and r.active and r.pinned for r in engine._events())
    omitted = Protocol(gateway).run('G local: time.now()["unixSeconds"] > 0\nrun local-mechanisms.verify-lab-compare(workId="fixture-context",identity="frozen",targets={"baseline":"score.json"})\ndone()', action_id='FIXCL3-mechanisms-omitted')
    proof['transcripts']['omitted-candidate'] = omitted
    proof['checks']['omittedCandidateRefused'] = omitted.get('ok') is False
    empty_gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace', action_scope='empty-context')
    empty = Protocol(empty_gateway).run('G local: time.now()["unixSeconds"] > 0\nrun local-mechanisms.verify-context-compact(focus="",targetRatio=0.25,maxContextTokens=1000)\ndone()', action_id='FIXCL3-mechanisms-empty')
    proof['transcripts']['empty-context'] = empty
    proof['checks']['emptyContextNotCreditedAsCompaction'] = empty.get('ok') is False
    proof['sourceHashesAtEnd'] = hashes()
    proof['checks']['sourceUnchanged'] = proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
    proof['ok'] = all(proof['checks'].values())
    output = REPO / 'scripts/evidence/FIXCL3-mechanisms.json'
    output.write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'ok': proof['ok'], 'witnesses': len(proof['witnesses']), 'failed': [k for k,v in proof['checks'].items() if not v], 'receipt': str(output)}))
    return 0 if proof['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
