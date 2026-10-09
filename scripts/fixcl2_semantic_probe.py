"""Exercise semantic native owner mutations and CL effect predicates in scratch."""
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


SOURCE_FILES = (
    'src/grant_agent/cl/semantic_effects.py', 'src/grant_agent/cl/frontier_effects.py',
    'src/grant_agent/cl/codecs.py', 'src/grant_agent/native_tools.py',
    'src/grant_agent/semantic_tools.py', 'src/grant_agent/verified_operations.py',
    'src/grant_agent/proof_capsules.py', 'src/grant_agent/recovery_objects.py',
    'src/grant_agent/living_applications.py', 'src/grant_agent/semantic_missions.py',
    'manuals/tools-depth.manual.json', 'manuals/cl/tools-depth.cl',
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port != 48829:
        parser.error('Semantic proof uses only assigned port 48829')
    root = REPO / '.agent_control' / 'proofs' / ('FIXCL2-semantic-' + str(time.time_ns()))
    root.mkdir(parents=True)
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_WATCHDOG_AUTOSTART='0',
                      NEYVIA_COORDINATOR_AUTOSTART='0', NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{args.port}')
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.neyvia_manuals import unwrap
    from grant_agent.cl.protocol import Protocol
    from grant_agent.cl import semantic_effects as effects

    prepare_broker_fixture(root)
    gateway = NeyviaToolGateway(root, allow_mutations=True, action_scope='FIXCL2-semantic', permission_mode='workspace')
    protocol = Protocol(gateway)
    proof = {'schema': 'neyvia.FIXCL2.semantic.v1', 'root': str(root), 'port': args.port,
             'auditCells': ['AUD4.json#/transcripts/manual_validation_tools-depth'],
             'checks': {}, 'actions': [],
             'boundary': 'Native semantic records and persisted effects only; proof claims remain unproven'}
    proof['sourceHashesAtStart'] = {name: digest(REPO / name) for name in SOURCE_FILES}
    fixture = root / 'semantic-source.txt'
    fixture.write_bytes(b'FIXCL2 bounded semantic artifact bytes\n')
    sha = digest(fixture)

    def call(name, arguments):
        prior = effects.snapshot_for(protocol, name, arguments)
        assert effects.checks_for(protocol, name, arguments), name
        raw = gateway.call_native(name, arguments, action_id='fixcl2-semantic-' + str(len(proof['actions']) + 1))
        try:
            result = unwrap(protocol.action_output(name, raw))
        except RuntimeError as exc:
            raise AssertionError((name, str(exc), raw)) from exc
        passed = effects.checks_for(protocol, name, arguments)[0]['check'](arguments, result, prior)
        proof['checks'][name + ':effect'] = passed
        proof['actions'].append({'tool': name, 'ok': result.get('ok') is not False,
                                 'subject': result.get('recoveryId') or result.get('proofId') or
                                            result.get('changeId') or result.get('missionId') or
                                            result.get('applicationId') or result.get('policyId')})
        if not passed:
            raise AssertionError((name, result))
        return result, prior

    recovery_args = {'failedOperation': {'tool': 'fixture.operation', 'sourceSha256': sha, 'status': 'failed'},
                     'recoveryId': 'fixcl2-semantic-recovery', 'confirmedSteps': [{'id': 'source-hashed'}],
                     'uncertainEffects': [{'id': 'external-effect-unknown'}],
                     'retrySafety': 'requires_reconciliation',
                     'availableRecoveryPaths': [{'kind': 'inspect'}], 'requiredAuthority': ['operator']}
    recovery, prior = call('semantic.recovery.create', recovery_args)
    proof['checks']['recovery_wrong_identity_refused'] = not effects.checks_for(
        protocol, 'semantic.recovery.create', recovery_args)[0]['check'](
            recovery_args, {**recovery, 'recoveryId': 'wrong'}, prior)
    read = unwrap(protocol.action_output('semantic.recovery.read', gateway.call_native(
        'semantic.recovery.read', {'recoveryId': recovery['recoveryId']}, action_id='fixcl2-semantic-read')))
    proof['checks']['recovery_owner_read_exact'] = read.get('recovery') == recovery['recovery']
    cl_recovery_id = 'fixcl2-semantic-cl-recovery'
    cl_lines = ('G effect: semantic.recovery.read(recoveryId=' + json.dumps(cl_recovery_id)
                + ')["recovery"]["recoveryId"] == ' + json.dumps(cl_recovery_id) + '\n'
                + 'semantic.recovery.create(failedOperation=' + json.dumps(recovery_args['failedOperation'])
                + ',recoveryId=' + json.dumps(cl_recovery_id) + ')\n'
                + 'done()')
    cl_recovery = Protocol(gateway).run(cl_lines, action_id='fixcl2-semantic-cl-recovery')
    proof['checks']['recovery_cl_create_and_done'] = cl_recovery.get('ok') is True and cl_recovery.get('status') == 'ok'
    proof['actions'].append({'tool': 'neyvia.cl', 'case': 'semantic.recovery.create',
                             'ok': cl_recovery.get('ok'), 'status': cl_recovery.get('status'),
                             'text': cl_recovery.get('text', '')[-700:]})

    proof_args = {'claim': 'The disposable source has the recorded bytes', 'build': {'commit': 'fixture'},
                  'environment': {'scope': 'disposable'}, 'startingState': {'sha256': sha},
                  'journey': [{'step': 'read fixture'}], 'actions': [{'tool': 'workspace.read'}],
                  'artifacts': [{'path': str(fixture), 'sha256': sha}],
                  'result': {'status': 'reported'}, 'reproduction': {'path': str(fixture)},
                  'capsuleId': 'fixcl2-semantic-proof'}
    capsule, prior = call('semantic.proof.create', proof_args)
    proof['checks']['proof_creation_does_not_prove_claim'] = capsule['proof'].get('verification', {}).get('claimProven') is not True
    verified = unwrap(protocol.action_output('semantic.proof.verify', gateway.call_native(
        'semantic.proof.verify', {'proofId': capsule['proofId']}, action_id='fixcl2-semantic-verify')))
    proof['checks']['proof_verify_integrity_only'] = (verified['verification']['artifactsVerified'] is True and
        verified['verification']['claimProven'] is False and
        verified['verification']['semanticClaimStatus'] == 'artifact_integrity_only')

    change_args = {'intended_behavior': 'Preserve semantic fixture bytes',
                   'source_modifications': [{'path': str(fixture), 'sha256': sha}],
                   'generated_artifacts': [{'path': str(fixture), 'sha256': sha}],
                   'rollback_boundary': {'kind': 'disposable-root'}}
    change, prior = call('semantic.changeset.create', change_args)
    fixture.write_bytes(b'altered bytes after observed effect\n')
    proof['checks']['changeset_source_drift_refused'] = not effects.checks_for(
        protocol, 'semantic.changeset.create', change_args)[0]['check'](change_args, change, prior)
    fixture.write_bytes(b'FIXCL2 bounded semantic artifact bytes\n')
    proof['checks']['source_restored'] = digest(fixture) == sha

    mission_args = {'missionId': 'fixcl2-semantic-mission', 'desiredOutcome': 'Persist a pending mission',
                    'acceptanceGates': ['Review the fixture artifact'],
                    'conversationId': 'fixcl2-conversation', 'turnId': 'fixcl2-turn'}
    mission, prior = call('semantic.mission.create', mission_args)
    proof['checks']['mission_not_self_completed'] = mission['mission']['status'] == 'planned' and all(
        gate['status'] == 'pending' for gate in mission['mission']['acceptanceGates'])
    mission_path = Path(mission['artifactPath'])
    saved_mission = mission_path.read_bytes()
    try:
        mission_path.write_bytes(b'corrupt disposable mission record')
        proof['checks']['mission_corrupt_record_refused'] = not effects.checks_for(
            protocol, 'semantic.mission.create', mission_args)[0]['check'](mission_args, mission, prior)
    finally:
        mission_path.write_bytes(saved_mission)

    application_args = {'applicationId': 'fixcl2-semantic-app',
                        'source': {'path': str(fixture), 'sha256': sha},
                        'buildRecipe': {'command': 'none-disposable'},
                        'health': {'status': 'unproven'}, 'rollback': {'kind': 'disposable'}}
    application, prior = call('semantic.application.register', application_args)
    app_read = unwrap(protocol.action_output('semantic.application.read', gateway.call_native(
        'semantic.application.read', {'applicationId': application['applicationId']},
        action_id='fixcl2-semantic-app-read')))
    proof['checks']['application_owner_read_exact'] = app_read.get('application') == application['application']

    policy_path = root / '.agent_control' / 'autonomy' / 'fixcl2-semantic-policy.json'
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(json.dumps({'schema': 'neyvia.supervised_autonomy.v1',
        'objective': 'Disposable local policy transition', 'operatorAuthority': True,
        'permittedActions': ['fixture.noop'], 'evidenceThreshold': 1,
        'budget': 2.0, 'budgetUsed': 0.0, 'revoked': False, 'history': []}), encoding='utf-8')
    admission_args = {'policyId': 'fixcl2-semantic-policy', 'action': 'fixture.noop',
                      'cost': 0.25, 'evidenceCount': 1}
    decision, prior = call('semantic.autonomy.admit', admission_args)
    proof['checks']['autonomy_admission_never_executes'] = decision['decision']['executed'] is False
    revocation_args = {'policyId': 'fixcl2-semantic-policy', 'reason': 'fixture closed'}
    revoked, prior = call('semantic.autonomy.revoke', revocation_args)
    proof['checks']['autonomy_revoked_persisted'] = revoked['policy']['revoked'] is True
    proof['sourceHashesAtEnd'] = {name: digest(REPO / name) for name in SOURCE_FILES}
    proof['sourceUnchanged'] = proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
    proof['checks']['source_unchanged'] = proof['sourceUnchanged']

    output = REPO / 'scripts/evidence/FIXCL2-semantic.json'
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'receipt': str(output), 'passed': all(proof['checks'].values()), 'checks': proof['checks']}))
    return 0 if all(proof['checks'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
