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
  console.log('SEMANTIC_HTTP_VERIFIED: authenticated scoped HTTP read, unauthenticated denial, bounded semantic records, and unknown identity handling');
} finally { child.kill(); rmSync(root, {recursive: true, force: true}); }
