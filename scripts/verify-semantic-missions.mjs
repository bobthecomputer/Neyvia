import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-semantic-missions-'));
try {
  const result = spawnSync(python, ['-c', String.raw`
import sys
from pathlib import Path
from grant_agent.semantic_missions import CollaborativeWorkspace, Mission, MissionGate, mission_from_message
from grant_agent.neyvia_conversations import NeyviaConversationStore
root=Path(sys.argv[1]); ledger=root/'workspace.jsonl'
workspace=CollaborativeWorkspace('workspace-fixture',storage_path=ledger)
decision=workspace.ingest_message('We will preserve the previous release and use the exact candidate hash.',conversation_id='conv-1',turn_id='turn-1')
assert decision.object_type=='decision' and decision.provenance.source_id=='turn-1'
approval=workspace.ingest_message('Approved for the exact candidate hash only.',conversation_id='conv-1',turn_id='turn-2')
assert approval.object_type=='approval' and approval.content['approved'] is True
artifact=workspace.ingest_message('Receipt sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',conversation_id='conv-1',turn_id='turn-3')
assert artifact.object_type=='artifact_reference' and artifact.content['references']
reopened=CollaborativeWorkspace('workspace-fixture',storage_path=ledger)
assert len(reopened.objects)==3 and reopened.snapshot()['objectCount']==3
mission=Mission('mission-fixture','Deploy the exact candidate safely',[MissionGate('gate-health','Service reports healthy'),MissionGate('gate-proof','Artifact receipt is preserved')],authority={'workspace':'fixture','allowedActions':['deploy']},exact_routes=[{'capability':'deploy','model':'luna','harness':'native'}],continuation_state={'next':'verify health'})
try:
    mission.mark_completed(); raise AssertionError('unproven mission completed')
except ValueError: pass
try:
    mission.verify_gate('gate-health',{'verified':True,'summary':'looks good'}); raise AssertionError('narrative evidence accepted')
except ValueError: pass
mission.verify_gate('gate-health',{'verified':True,'proofId':'proof-health-1','artifactHash':'a'*64},source=decision.provenance)
mission.verify_gate('gate-proof',{'verified':True,'receiptId':'receipt-1','sha256':'b'*64},source=artifact.provenance)
mission.mark_completed()
assert mission.status=='completed' and mission.proven_complete
serialized=mission.to_dict(); assert serialized['schema'].startswith('neyvia.semantic-mission') and serialized['provenanceHash']
derived=mission_from_message('Continue the release mission',conversation_id='conv-2',turn_id='turn-9',acceptance_gates=['A proof capsule exists'])
assert derived.continuation_state['sourceTurnId']=='turn-9' and derived.status=='planned'
store=NeyviaConversationStore(root/'store')
conversation=store.create_conversation(workspace_id='workspace-fixture',title='Semantic fixture')
turn=store.append_turn(conversation['conversationId'],role='user',content='Use the exact candidate route.',metadata={'semanticType':'decision'})
mission_record=store.create_semantic_mission(conversation['conversationId'],desired_outcome='Preserve and verify candidate',acceptance_gates=['A proof receipt exists'],exact_routes=[{'capability':'deploy','model':'luna'}],authority={'allowedActions':['deploy']})
semantic_object=store.ingest_semantic_turn(conversation['conversationId'],turn['turnId'])
assert semantic_object['objectType']=='decision' and mission_record['status']=='planned'
projection=store.get_conversation(conversation['conversationId'])['semantic']
assert projection['mission']['missionId']==mission_record['missionId'] and projection['objects'][0]['objectType']=='decision'
prepared=store.create_conversation(workspace_id='workspace-fixture',title='Prepared workflow',metadata={'desiredOutcome':'Ship the prepared workflow','acceptanceGates':['A proof receipt exists'],'exactRoutes':[{'model':'luna'}]})
prepared_turn=store.append_turn(prepared['conversationId'],role='user',content='Use the prepared route.',metadata={'semanticType':'decision'})
prepared_projection=store.get_conversation(prepared['conversationId'])['semantic']
assert prepared_projection['mission']['desiredOutcome']=='Ship the prepared workflow'
assert prepared_projection['objects'][0]['objectType']=='decision'
assert store.ingest_semantic_turn(prepared['conversationId'],prepared_turn['turnId'])['objectId']==prepared_projection['objects'][0]['objectId']
print('SEMANTIC_MISSIONS_VERIFIED: durable provenance, message conversion, persistence, explicit proof gates, and unproven-completion refusal')
`, root], {cwd: repo, env: {...process.env, PYTHONPATH: path.join(repo, 'src')}, encoding: 'utf8', timeout: 30000});
  assert.equal(result.status, 0, result.stderr || result.stdout || result.error?.message);
  console.log(result.stdout.trim());
} finally { rmSync(root, {recursive: true, force: true}); }
