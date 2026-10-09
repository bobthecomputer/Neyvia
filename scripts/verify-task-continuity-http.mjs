import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-semantic-http-'));
const child = spawn(python, ['-u', '-c', String.raw`
import json,sys
from pathlib import Path
from http.server import ThreadingHTTPServer
from grant_agent.neyvia_conversations import NeyviaConversationStore
from grant_agent.verified_operations import VerifiedOperationStore
from grant_agent.web_backend import FluxioWebBackend,make_handler
root=Path(sys.argv[1]); store=NeyviaConversationStore(root)
conversation=store.create_conversation(workspace_id='fixture',title='HTTP semantic fixture')
turn=store.append_turn(conversation['conversationId'],role='user',content='Use this exact route.',metadata={'semanticType':'decision'})
store.create_semantic_mission(conversation['conversationId'],desired_outcome='Verify fixture',acceptance_gates=['Receipt exists'],exact_routes=[{'model':'luna'}])
store.ingest_semantic_turn(conversation['conversationId'],turn['turnId'])
VerifiedOperationStore(root,conversation['conversationId']).execute('op-http-fixture','fixture.tool',authority={'granted':True},effect=lambda: {'ok':True},verify=lambda c: {'verified':True})
backend=FluxioWebBackend(root,root); backend.sessions['fixture-token']={'username':'fixture','displayName':'Fixture','role':'admin'}
backend.sessions['other-token']={'username':'other','displayName':'Other','role':'admin'}
from grant_agent.contextual_learning import ContextualLearningStore
(root/'before.txt').write_text('Long draft')
(root/'after.txt').write_text('Short draft')
learning=ContextualLearningStore(root/'.agent_control'/'contextual_learning'/f"{conversation['conversationId']}.json",scope_root=root)
learning.record_correction('landing-page',before_path='before.txt',after_path='after.txt',correction='Prefer concise copy in this example')
from grant_agent.experimental_quality import ExperimentalQuality
quality=ExperimentalQuality(root,conversation['conversationId'])
quality.define_instrument('latency',{'kind':'json_numeric','key':'latency','max':20})
quality.define_holdout('baseline',{'instruments':['latency']})
quality.challenge('baseline',{'condition':'Evaluate a slower connection','spec':{'instruments':['latency']}})
server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(backend)); print(json.dumps({'port':server.server_address[1],'conversationId':conversation['conversationId']}),flush=True); server.serve_forever()
`, root], {cwd: repo, env: {...process.env, PYTHONPATH: path.join(repo, 'src')}, stdio: ['ignore','pipe','pipe']});
try {
  const ready = await new Promise((resolve, reject) => {
    let buf = '';
    child.stdout.on('data', chunk => { buf += chunk; const line = buf.split(/\r?\n/)[0]; if (line) resolve(JSON.parse(line)); });
    child.stderr.on('data', chunk => { if (!buf) reject(new Error(String(chunk))); });
    child.on('error', reject);
  });
  const base = `http://127.0.0.1:${ready.port}`;
  const denied = await fetch(`${base}/api/neyvia/semantic?conversationId=${encodeURIComponent(ready.conversationId)}`);
  assert.equal(denied.status, 401);
  const response = await fetch(`${base}/api/neyvia/semantic?conversationId=${encodeURIComponent(ready.conversationId)}&limit=10`, {headers:{Cookie:'grand_agent_session=fixture-token'}});
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.ok, true);
  assert.equal(body.data.identity.conversationId, ready.conversationId);
  assert.equal(body.data.workspace.objects[0].objectType, 'decision');
  assert.equal(body.data.mission.status, 'planned');
  assert.equal(body.data.operations[0].operationId, 'op-http-fixture');
  const missing = await fetch(`${base}/api/neyvia/semantic?conversationId=missing`, {headers:{Cookie:'grand_agent_session=fixture-token'}});
  assert.equal(missing.status, 404);
  const invoke = async (command, payload, token = 'fixture-token') => {
    const response = await fetch(`${base}/api/backend`, {method:'POST', headers:{'Content-Type':'application/json', ...(token ? {Cookie:`grand_agent_session=${token}`} : {})}, body:JSON.stringify({command,payload})});
    return {status:response.status, body:await response.json()};
  };
  assert.equal((await invoke('get_task_continuity_command', {deviceId:'phone'}, '')).status, 401);
  const initial = await invoke('get_task_continuity_command', {deviceId:'computer'});
  assert.equal(initial.body.data.revision, 0);
  const saved = await invoke('save_task_continuity_command', {deviceId:'computer',conversationId:ready.conversationId,draft:'Keep this draft →',expectedRevision:0});
  assert.equal(saved.body.data.status, 'saved');
  const phone = await invoke('get_task_continuity_command', {deviceId:'phone'});
  assert.equal(phone.body.data.sharedLatest.draft, 'Keep this draft →');
  const conflict = await invoke('save_task_continuity_command', {deviceId:'phone',conversationId:ready.conversationId,draft:'stale draft',expectedRevision:0});
  assert.equal(conflict.body.data.status, 'conflict');
  const isolated = await invoke('get_task_continuity_command', {deviceId:'phone',_continuityOwner:'fixture'}, 'other-token');
  assert.equal(isolated.body.data.revision, 0);
  const invalid = await invoke('save_task_continuity_command', {deviceId:'phone',conversationId:'missing',expectedRevision:1});
  assert.equal(invalid.body.ok, false);
  assert.equal((await invoke('get_task_continuity_command', {deviceId:'phone'})).body.data.revision, 1);
  const learning = await invoke('get_workspace_intelligence_command', {conversationId:ready.conversationId});
  assert.equal(learning.body.ok, true);
  const group=learning.body.data.preferences.find(group=>group.context==='landing-page');
  const correctionId=group.rows[0].correctionId;
  assert.equal(group.rows[0].status, 'provisional');
  assert.equal((await invoke('review_contextual_correction_command', {conversationId:ready.conversationId,correctionId,approve:true}, '')).status,401);
  assert.equal((await invoke('review_contextual_correction_command', {conversationId:ready.conversationId,correctionId,approve:true})).body.data.status,'accepted');
  const reviewed=await invoke('get_workspace_intelligence_command', {conversationId:ready.conversationId});
  assert.equal(reviewed.body.data.preferences.find(group=>group.context==='landing-page').rows[0].trustedOperator,true);
  const challenge=reviewed.body.data.challenges.rows[0];
  assert.equal(challenge.status,'pending_operator_promotion');
  assert.equal((await invoke('review_quality_challenge_command',{conversationId:ready.conversationId,challengeId:challenge.id,approve:true},'')).status,401);
  const promotion=await invoke('review_quality_challenge_command',{conversationId:ready.conversationId,challengeId:challenge.id,approve:true});
  assert.equal(promotion.body.data.status,'approved');
  assert.equal(promotion.body.data.promotedHoldoutId,challenge.id);
  console.log('TASK_CONTINUITY_HTTP_VERIFIED: authentication, two-device resume, stale-write denial, unknown-task denial, and server-owned account isolation');
} finally { child.kill(); rmSync(root, {recursive: true, force: true}); }
