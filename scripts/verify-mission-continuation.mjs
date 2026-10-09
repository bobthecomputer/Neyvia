import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-mission-continuation-'));
try {
  const result = spawnSync(python, ['-c', String.raw`
import json,sys
from pathlib import Path
from grant_agent.neyvia_conversations import NeyviaConversationStore
from grant_agent.verified_operations import VerifiedOperationStore
root=Path(sys.argv[1]); store=NeyviaConversationStore(root)
c=store.create_conversation(workspace_id='w',kind='orchestration',title='Continuation',metadata={'desiredOutcome':'Ship safely','acceptanceGates':['Health is proven'],'routeSnapshot':[{'model':'luna'}]})
mission=store.get_conversation(c['conversationId'])['semantic']['mission']
narrative_refused=False
try: store.verify_semantic_mission_gate(c['conversationId'],mission['acceptanceGates'][0]['gateId'],{'verified':True,'summary':'looks good'})
except ValueError: narrative_refused=True
store.append_turn(c['conversationId'],role='assistant',content='Checkpoint saved',metadata={'missionCheckpoint':{'checkpointId':'cp-1','next':'capture proof'}})
reloaded=store.get_conversation(c['conversationId'])['semantic']['mission']
untrusted_refused=False
try: store.verify_semantic_mission_gate(c['conversationId'],reloaded['acceptanceGates'][0]['gateId'],{'verified':True,'proofId':'proof-1'},source_turn_id='turn-proof')
except ValueError: untrusted_refused=True
ops=VerifiedOperationStore(root,c['conversationId'])
ops.execute('proof-1','fixture.verify',authority={'granted':True},effect=lambda:{'ok':True},verify=lambda _:{'verified':True,'claim':'Health is proven'})
trusted=store.verify_semantic_mission_gate(c['conversationId'],reloaded['acceptanceGates'][0]['gateId'],{'verified':True,'proofId':'proof-1'},source_turn_id='turn-proof')
print(json.dumps({'narrativeRefused':narrative_refused,'untrustedRefused':untrusted_refused,'mission':trusted}))
`, root], {cwd: repo, env: {...process.env, PYTHONPATH: path.join(repo, 'src')}, encoding: 'utf8', timeout: 30000});
  assert.equal(result.status, 0, result.stderr || result.stdout || result.error?.message);
  const evidence = JSON.parse(result.stdout.trim());
  assert.equal(evidence.narrativeRefused, true);
  assert.equal(evidence.untrustedRefused, true);
  assert.equal(evidence.mission.status, 'planned');
  assert.equal(evidence.mission.continuationState.latestCheckpoint.checkpointId, 'cp-1');
  assert.deepEqual(evidence.mission.exactRoutes, [{model:'luna'}]);
  console.log('MISSION_CONTINUATION_VERIFIED: reload-safe route preservation, checkpoint provenance, narrative-proof refusal, and unproven mission status');
} finally { rmSync(root, {recursive: true, force: true}); }
