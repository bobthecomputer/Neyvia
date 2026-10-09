"""Retained positive CL witnesses and fresh drift refusals for every local adapter."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from fixcl_verify import REPO, environment, guards


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48821, 48830):
        parser.error('Assigned explicit port required')
    root = REPO / '.agent_control/proofs' / ('FIXCL3-records-' + str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root); environment(root, args.port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    from grant_agent.neyvia_gateway import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.cl.record_effects import SUPPORTED, snapshot_for, checks_for
    from grant_agent.ui_command_bus import bus_for
    from grant_agent.workspace_intelligence import WorkspaceIntelligence
    from PIL import Image

    proof = {'schema': 'neyvia.FIXCL3.records.v1', 'root': str(root), 'port': args.port,
             'boundary': 'Fresh isolated artifact copies, deterministic compiled plans, frozen declared artifact criteria and unverified proposed records only.',
             'checks': {}, 'transcripts': {}, 'witnesses': [], 'frontier': {
                 'environment.create/run': 'Dependency installation/execution requires an installed uv runtime and independently observed process effect; no install performed.',
                 'intelligence.*': 'Question/obligation/handoff consistency needs dedicated owner witnesses.',
                 'lab.*': 'Full competitions, causal analysis, curriculum and rehearsal need dedicated fresh matched observation witnesses.',
                 'skill.live.iterate': 'Edits global user skill state and requires authorized isolated skill installation and native behavioral proof.',
                 'context.compact': 'Durable transcript compaction requires its own fresh SQLite event/receipt witness.'}}
    paths = [REPO / 'src/grant_agent/cl/record_effects.py', REPO / 'scripts/fixcl3_records_probe.py',
             REPO / 'manuals/local-records.manual.json', REPO / 'manuals/cl/local-records.cl',
             *[REPO / 'src/grant_agent' / name for name in ('creative_tools.py', 'innovation_tools.py', 'experimental_quality.py',
             'behavioral_experiments.py', 'experiment_studio.py', 'experience_learning.py', 'contextual_learning.py', 'orchestration_language.py')]]
    hashes = lambda: {path.relative_to(REPO).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    proof['sourceHashesAtStart'] = hashes()
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace')
    prefs = WorkspaceIntelligence(root, 'record-fixture')
    prefs.configure_collaboration({'learning': True, 'evaluation': True}, expected_revision=0, operator_identity='FIXCL3-disposable-owner')
    (root / 'source').mkdir()
    (root / 'source/original.txt').write_text('preserved fixture bytes\n', encoding='utf-8')
    (root / 'baseline.json').write_text('{"score": 3}', encoding='utf-8')
    (root / 'candidate.json').write_text('{"score": 4}', encoding='utf-8')
    Image.new('RGBA', (8, 8), (0, 32, 96, 255)).save(root / 'before.png')
    Image.new('RGBA', (8, 8), (96, 32, 0, 128)).save(root / 'after.png')
    work = 'record-fixture'
    cases = [
        ('behavior.create', {'workId': work, 'experimentId': 'trial', 'baselineInput': 'original', 'variantInput': 'variant',
            'acceptance': {'kind': 'response_contains', 'text': 'expected'}, 'requestedRoute': {'runtime': 'reported', 'model': 'fixture'}, 'budget': {'maxCalls': 2}}),
        ('behavior.observe', {'workId': work, 'experimentId': 'trial', 'variant': 'baseline', 'response': 'caller report',
            'actualRoute': {'runtime': 'reported', 'model': 'fixture'}, 'latencyMs': 5, 'cost': 0}),
        ('experiment.create', {'experimentId': 'isolated', 'source': 'source', 'launchRecipe': {}, 'resetRecipe': {}}),
        ('experiment.restore', {'experimentId': 'isolated', 'restoreId': 'restored'}),
        ('experience.note', {'workId': work, 'lesson': 'Preserve source bytes', 'conditions': 'Local fixture', 'invalidation': 'Source changes', 'evidence': ['source/original.txt']}),
        ('experience.compare', {'workId': work, 'baseline': 'before.png', 'candidate': 'after.png', 'preference': 'undecided', 'observations': {'alpha': 'candidate is translucent'}}),
        ('experience.trace', {'workId': work, 'traceId': 'fixture-trace', 'eventKind': 'state', 'payload': {'state': 'reported'}, 'references': []}),
        ('experience.investigate', {'workId': work, 'hypothesis': 'Declared score stays within limit', 'experiment': {'target': 'candidate.json'}, 'references': []}),
        ('quality.instrument', {'workId': work, 'arguments': {'i': 'score', 'spec': {'kind': 'json_numeric', 'key': 'score', 'max': 5}}}),
        ('quality.holdout', {'workId': work, 'arguments': {'i': 'held', 'spec': {'instruments': ['score']}}}),
        ('quality.measure', {'workId': work, 'arguments': {'instrument': 'score', 'target': 'candidate.json'}}),
        ('quality.compare', {'workId': work, 'arguments': {'instrument': 'score', 'baseline': 'baseline.json', 'candidate': 'candidate.json'}}),
        ('quality.examine', {'workId': work, 'arguments': {'holdout': 'held', 'targets': ['baseline.json', 'candidate.json']}}),
        ('quality.challenge', {'workId': work, 'arguments': {'holdout': 'held', 'proposal': {'spec': {'instruments': ['score']}}}}),
        ('taste.correction', {'workId': work, 'arguments': {'context': 'product-ui', 'before_path': 'before.png', 'after_path': 'after.png', 'correction': 'Explore alpha', 'agent_id': 'fixture'}}),
        ('orchestration.compile', {'source': 'NEYVIA/1\nGOAL text="Inspect disposable fixture"\nLANE local runtime=native model=none effort=low permissions=read\nSTEP inspect lane=local action=tool tool=workspace.read risk=read acceptance="bytes observed"\n', 'outputPath': 'compiled.json'}),
    ]
    if {name for name, _ in cases} != SUPPORTED:
        raise ValueError('Every admitted action requires an actual retained witness')
    for index, (name, payload) in enumerate(cases):
        protocol = Protocol(gateway)
        identity = 'FIXCL3-records-' + str(index)
        before = snapshot_for(protocol, name, payload)
        inputs = ','.join(k + '=' + json.dumps(v) for k, v in payload.items())
        lines = 'G local: time.now()["unixSeconds"] > 0\nrun local-records.record-' + name.replace('.', '-') + '(' + inputs + ')\ndone()'
        result = protocol.run(lines, action_id=identity)
        proof['transcripts'][name] = result
        proof['checks'][name + '-CLDone'] = result.get('ok') is True
        uses = [event['payload'] for event in bus_for(root).since(0) if event['action'] == 'cl.manual.use']
        admitted = [use for use in uses if use.get('tool') == name and use.get('manual') == 'local-records' and
                    use.get('status') == 'admitted' and use.get('actionIdentity', '').startswith(identity + ':') and use.get('effectChecks')]
        proof['checks'][name + '-manualReceipt'] = len(admitted) == 1
        # A positive CL completion rechecks its own host-bound fresh predicate.
        proof['checks'][name + '-freshCompletion'] = protocol.run('done()', action_id=identity).get('ok') is True
        if not result.get('ok'):
            continue
        if name.startswith('behavior.'):
            corrupt_path = root / '.agent_control/behavioral_experiments.json'
        elif name.startswith('experience.'):
            from grant_agent.experience_learning import ExperienceStore
            corrupt_path = next(p for p in ExperienceStore(root, work).base.glob('*.json') if str(p) not in before['files'])
        elif name.startswith('quality.'):
            from grant_agent.experimental_quality import ExperimentalQuality
            corrupt_path = next(p for p in ExperimentalQuality(root, work).base.glob('*.json') if str(p) not in before['files'])
        elif name == 'taste.correction':
            corrupt_path = root / 'before.png'
        elif name == 'experiment.create':
            corrupt_path = root / '.agent_control/experiments/isolated/source/original.txt'
        elif name == 'experiment.restore':
            corrupt_path = root / '.agent_control/experiment_restores/restored/original.txt'
        else:
            corrupt_path = root / 'compiled.json'
        clean = corrupt_path.read_bytes()
        corrupt_path.write_bytes(b'changed by independent fixture writer')
        drift = protocol.run('done()', action_id=identity)
        proof['transcripts'][name + '-drift'] = drift
        proof['checks'][name + '-freshDriftRefused'] = drift.get('ok') is False
        corrupt_path.write_bytes(clean)
        proof['witnesses'].append({'tool': name, 'actionIdentity': identity, 'positiveCL': result,
                                   'manualReceipt': admitted, 'freshDriftRefused': drift.get('ok') is False,
                                   'driftSubject': str(corrupt_path)})
    # Declared negative measurements are retained, rather than rewritten to pass.
    (root / 'candidate.json').write_text('{"score": 99}', encoding='utf-8')
    protocol = Protocol(gateway)
    negative = protocol.run('G local: time.now()["unixSeconds"] > 0\nrun local-records.record-quality-measure(workId="record-fixture",arguments={"instrument":"score","target":"candidate.json"})\ndone()', action_id='FIXCL3-records-negative-measure')
    proof['transcripts']['negative-measure'] = negative
    from grant_agent.experimental_quality import ExperimentalQuality
    measurements = [json.loads(p.read_bytes()) for p in ExperimentalQuality(root, work).base.glob('receipt-*.json')]
    proof['checks']['negativeMeasurementRetained'] = negative.get('ok') is True and any(row.get('value') == 99 and row.get('withinLimit') is False for row in measurements)
    # Duplicate snapshot creation cannot overwrite either the original or its snapshot.
    duplicate = Protocol(gateway).run('G local: time.now()["unixSeconds"] > 0\nrun local-records.record-experiment-create(experimentId="isolated",source="source",launchRecipe={},resetRecipe={})\ndone()', action_id='FIXCL3-records-duplicate')
    proof['transcripts']['duplicate'] = duplicate
    proof['checks']['duplicateSnapshotRefused'] = duplicate.get('ok') is False
    # Product runs route durable learning/quality records to a separate work
    # root. Exercise that actual gateway route, not only an unscoped local owner.
    work_root = root / 'durable-work'; work_root.mkdir()
    scoped = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace',
                              action_scope='scoped-fixture', action_root=work_root)
    scoped_protocol = Protocol(scoped)
    scoped_result = scoped_protocol.run('G local: time.now()["unixSeconds"] > 0\nrun local-records.record-experience-trace(workId="scoped-fixture",traceId="scoped-trace",eventKind="state",payload={"state":"reported"},references=[])\ndone()', action_id='FIXCL3-records-scoped-owner')
    proof['transcripts']['scoped-owner'] = scoped_result
    from grant_agent.experience_learning import ExperienceStore
    owner_store = ExperienceStore(work_root, 'scoped-fixture')
    owned_records = list(owner_store.base.glob('trace_*.json'))
    proof['checks']['scopedProductOwnerCLDone'] = scoped_result.get('ok') is True and len(owned_records) == 1
    if owned_records:
        clean = owned_records[0].read_bytes()
        owned_records[0].write_bytes(b'independently changed durable work record')
        proof['checks']['scopedProductOwnerDriftRefused'] = scoped_protocol.run('done()', action_id='FIXCL3-records-scoped-owner').get('ok') is False
        owned_records[0].write_bytes(clean)
    (work_root / 'score.json').write_text('{"score": 2}', encoding='utf-8')
    scoped_quality = Protocol(scoped).run('G local: time.now()["unixSeconds"] > 0\nrun local-records.record-quality-instrument(workId="scoped-fixture",arguments={"i":"scoped-score","spec":{"kind":"json_numeric","key":"score","max":3}})\ndone()', action_id='FIXCL3-records-scoped-quality-instrument')
    proof['transcripts']['scoped-quality-instrument'] = scoped_quality
    measured_quality = Protocol(scoped).run('G local: time.now()["unixSeconds"] > 0\nrun local-records.record-quality-measure(workId="scoped-fixture",arguments={"instrument":"scoped-score","target":"score.json"})\ndone()', action_id='FIXCL3-records-scoped-quality-measure')
    proof['transcripts']['scoped-quality-measure'] = measured_quality
    proof['checks']['scopedProductQualityOwnerCLDone'] = scoped_quality.get('ok') is True and measured_quality.get('ok') is True
    proof['sourceHashesAtEnd'] = hashes()
    proof['checks']['sourceUnchanged'] = proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
    proof['ok'] = all(proof['checks'].values())
    output = REPO / 'scripts/evidence/FIXCL3-records.json'
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'receipt': str(output), 'ok': proof['ok'], 'witnesses': len(proof['witnesses']), 'failed': [k for k, v in proof['checks'].items() if not v]}))
    return 0 if proof['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
