"""Real CL records with exact owner state, corrupt/stale refusal, and no model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from fixcl_verify import REPO, environment, guards


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48821, 48830):
        parser.error('Assigned explicit port required')
    root = REPO / '.agent_control/proofs' / ('FIXCL2-creative-' + str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root); environment(root, args.port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    from grant_agent.neyvia_gateway import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.situation_interface import SituationStore
    from grant_agent.behavioral_experiments import BehavioralExperimentLedger
    from grant_agent.workspace_intelligence import WorkspaceIntelligence

    paths = [*(REPO / 'src/grant_agent/cl').glob('*.py'),
             REPO / 'src/grant_agent/creative_tools.py', REPO / 'src/grant_agent/innovation_tools.py',
             REPO / 'src/grant_agent/contextual_learning.py', REPO / 'src/grant_agent/behavioral_experiments.py',
             REPO / 'src/grant_agent/situation_interface.py', REPO / 'src/grant_agent/situation_tools.py',
             REPO / 'src/grant_agent/workspace_intelligence.py', REPO / 'src/grant_agent/native_tools.py',
             REPO / 'manuals/cl/creative-records.cl', REPO / 'manuals/creative-records.manual.json',
             REPO / 'config/neyvia_manuals.json', Path(__file__)]
    hashes = lambda: {path.relative_to(REPO).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    start = hashes()
    proof = {'schema': 'neyvia.FIXCL2.creative.v1', 'root': str(root), 'port': args.port,
             'boundary': 'Persisted agent proposals and unverified caller reports only; no provider or causal quality claim.',
             'checks': {}, 'transcripts': {}, 'sourceHashesAtStart': start}
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace')
    identity = 'reported-fixture'
    j = json.dumps
    definition = {'experiment_id': 'trial', 'baseline_input': 'original representation',
                  'variant_input': 'revised representation', 'acceptance': {'kind': 'response_contains', 'text': 'target'},
                  'requested_route': {'runtime': 'reported', 'model': 'fixture'}, 'budget': {'maxCalls': 2}}
    report = {'experiment_id': 'trial', 'variant': 'baseline', 'response': 'reported response',
              'actual_route': {'runtime': 'reported', 'model': 'fixture'}}
    trial_path = root / '.agent_control/contextual_learning' / (identity + '-attention.json')
    # A real empty owner ledger is a disposable prerequisite, not model evidence.
    BehavioralExperimentLedger(trial_path)._save()
    goal = j('"experimentId": "trial"') + ' in workspace.read(path=' + j(str(trial_path)) + ')["content"]'

    def run(label, lines):
        protocol = Protocol(gateway)
        result = protocol.run(lines, action_id='FIXCL2-creative-' + label)
        proof['transcripts'][label] = result
        return protocol, result

    # Native evaluation preference defaults to denied, and cannot be granted by
    # model arguments. The fixture enables it via the existing trusted owner seam.
    _, denied = run('preference-denied', 'G local: time.now()["unixSeconds"] > 0\n'
                    'run creative-records.record-attention-create(workId=' + j(identity) + ',arguments=' + j(definition) + ')\ndone()')
    proof['checks']['evaluationPreferenceRequired'] = denied.get('ok') is False and json.loads(trial_path.read_bytes())['experiments'] == {}
    preferences = WorkspaceIntelligence(root, identity)
    preferences.configure_collaboration({'evaluation': True}, expected_revision=0, operator_identity='FIXCL2-disposable-owner')
    protocol, created = run('create', 'G local: ' + goal + '\nrun creative-records.record-attention-create(workId='
                            + j(identity) + ',arguments=' + j(definition) + ')\ndone()')
    proof['checks']['createCLDone'] = created.get('ok') is True
    before_report = json.loads(trial_path.read_bytes())
    protocol, observed = run('observe', 'G local: ' + goal + '\nrun creative-records.record-attention-observe(workId='
                             + j(identity) + ',arguments=' + j(report) + ')\ndone()')
    proof['checks']['observeCLDone'] = observed.get('ok') is True
    if not proof['checks']['createCLDone'] or not proof['checks']['observeCLDone']:
        proof['sourceHashesAtEnd'] = hashes()
        proof['ok'] = False
        output = REPO / 'scripts/evidence/FIXCL2-creative.json'
        output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
        print(json.dumps({'ok': False, 'checks': proof['checks'], 'create': created, 'observe': observed}))
        return 1
    state = json.loads(trial_path.read_bytes())
    row = state['experiments'].get('trial', {}).get('observations', [{}])[-1]
    proof['checks']['reportedEvidenceNeverPromoted'] = row.get('evidenceVerified') is False and row.get('response') == report['response']
    proof['checks']['definitionAndOtherRecordsConserved'] = state['experiments']['trial']['definition'] == before_report['experiments']['trial']['definition']
    _, duplicate = run('duplicate', 'G local: ' + goal + '\nrun creative-records.record-attention-create(workId='
                       + j(identity) + ',arguments=' + j(definition) + ')\ndone()')
    proof['checks']['duplicateExperimentRefused'] = duplicate.get('ok') is False and json.loads(trial_path.read_bytes()) == state
    missing = {**report, 'experiment_id': 'missing'}
    _, unknown = run('unknown', 'G local: ' + goal + '\nrun creative-records.record-attention-observe(workId='
                     + j(identity) + ',arguments=' + j(missing) + ')\ndone()')
    proof['checks']['unknownExperimentRefused'] = unknown.get('ok') is False and json.loads(trial_path.read_bytes()) == state
    clean = trial_path.read_bytes()
    corrupt = json.loads(clean); corrupt['experiments']['trial']['observations'][0]['response'] = 'changed'
    trial_path.write_text(json.dumps(corrupt), encoding='utf-8')
    proof['checks']['corruptedObservationBlocksDone'] = protocol.run('done()', action_id='FIXCL2-creative-observe').get('ok') is False
    trial_path.write_bytes(clean)
    task = {'workId': identity, 'task': 'Preserve the selected audit boundary', 'constraints': ['No external provider'],
            'acceptance': ['Exact proposal saved'], 'expectedRevision': 0}
    situation_goal = 'situation.recall(workId=' + j(identity) + ')["task"]["task"] == ' + j(task['task'])
    task_args = ','.join(key + '=' + j(value) for key, value in task.items())
    protocol, saved = run('situation', 'G local: ' + situation_goal + '\nrun creative-records.record-situation-define('
                         + task_args + ')\ndone()')
    proof['checks']['situationCLDone'] = saved.get('ok') is True
    situation = SituationStore(root, identity)
    original = situation.path.read_bytes()
    proof['checks']['proposalSourcePreserved'] = situation._read()['contract']['source'] == 'agent_proposal'
    _, stale = run('stale-revision', 'G local: ' + situation_goal + '\nrun creative-records.record-situation-define('
                    + task_args + ')\ndone()')
    proof['checks']['staleRevisionRefusedWithoutWrite'] = stale.get('ok') is False and situation.path.read_bytes() == original
    corrupt = json.loads(original); corrupt['contract']['task'] = 'corrupted task'
    situation.path.write_text(json.dumps(corrupt), encoding='utf-8')
    proof['checks']['corruptProposalBlocksDone'] = protocol.run('done()', action_id='FIXCL2-creative-situation').get('ok') is False
    situation.path.write_bytes(original)
    from grant_agent.ui_command_bus import bus_for
    uses = [event['payload'] for event in bus_for(root).since(0) if event['action'] == 'cl.manual.use']
    successful_identities = {label: 'FIXCL2-creative-' + label + ':' for label in ('create', 'observe', 'situation')}
    proof['manualUses'] = [{'ok': True, 'manualUse': use} for use in uses
                          if use.get('manual') == 'creative-records' and use.get('status') == 'admitted'
                          and any(use.get('actionIdentity', '').startswith(prefix) for prefix in successful_identities.values())]
    for label, tool in (('create', 'attention.create'), ('observe', 'attention.observe'), ('situation', 'situation.define')):
        proof['checks'][label + '-manualAdmission'] = any(use.get('tool') == tool and use.get('manual') == 'creative-records'
            and use.get('actionIdentity', '').startswith(successful_identities[label])
            and use.get('status') == 'admitted' and use.get('effectChecks') for use in uses)
    proof['sourceHashesAtEnd'] = hashes()
    proof['checks']['sourceUnchanged'] = start == proof['sourceHashesAtEnd']
    proof['ok'] = all(proof['checks'].values())
    output = REPO / 'scripts/evidence/FIXCL2-creative.json'
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'receipt': str(output), 'ok': proof['ok'], 'checks': proof['checks']}))
    return 0 if proof['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
