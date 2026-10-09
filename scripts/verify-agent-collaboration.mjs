import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const repo = process.cwd();
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-collaboration-'));
const child = spawn(resolveNeyviaPython(repo).python, ['-u', '-c', String.raw`
import json,sys
from pathlib import Path
from http.server import ThreadingHTTPServer
from grant_agent.web_backend import FluxioWebBackend,make_handler
from grant_agent.workspace_intelligence import WorkspaceIntelligence
from grant_agent.innovation_tools import InnovationToolRuntime
from grant_agent.neyvia_agent import NeyviaAgentConfig,_role_instructions
from grant_agent.agent_questions import request_question
r=Path(sys.argv[1]); b=FluxioWebBackend(r,r)
b.sessions['fixture-token']={'username':'fixture-operator','role':'admin'}
for identity in ['task-a','task-b']:b.neyvia_mcp.conversations.create_conversation(conversation_id=identity,title=identity)
question=request_question(r,'runtime-a','Which direction?',conversation_id='task-a')
(r/'question.json').write_text(json.dumps(question))
store=WorkspaceIntelligence(r,'task-a')
directions=[{'id':'queue','title':'Work queue','approach':'Put the next useful action first.','tradeoff':'Less freeform exploration.'}, {'id':'canvas','title':'Artifact canvas','approach':'Organize around visible work products.','tradeoff':'More spatial navigation.'}]
store.propose_brief('Improve the active workspace',directions=directions,assumptions=['Single operator'],open_questions=['Which experience matters most?'])
checks={}
try:InnovationToolRuntime(r).call('intelligence.brief',{'workId':'task-a','arguments':{'understanding':'spoof','operator_identity':'forged'}})
except PermissionError:checks['modelCannotSupplyOperator']=True
try:store.configure_collaboration({'evaluation':'false'},expected_revision=0,operator_identity='fixture')
except ValueError:checks['strictBoolean']=True
try:store.propose_brief('duplicate directions',expected_revision=1,directions=[directions[0],directions[0]])
except ValueError:checks['duplicateDirectionRejected']=True
(r/'core-checks.json').write_text(json.dumps(checks))
s=ThreadingHTTPServer(('127.0.0.1',0),make_handler(b))
print(json.dumps({'port':s.server_address[1]}),flush=True);s.serve_forever()
`, root], { env: { ...process.env, PYTHONPATH: path.join(repo, 'src') }, stdio: ['ignore', 'pipe', 'pipe'] });
let errors = '';
child.stderr.on('data', data => { errors += data; });
const closed = new Promise(resolve => child.once('exit', resolve));
try {
  const ready = await new Promise((resolve, reject) => {
    let buffer = '';
    const timer = setTimeout(() => reject(Error('HTTP startup timeout: ' + errors.slice(-1000))), 30000);
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('exit', () => { clearTimeout(timer); reject(Error('HTTP host exited: ' + errors.slice(-1000))); });
    child.stdout.on('data', data => {
      buffer += data;
      if (buffer.includes('\n')) { clearTimeout(timer); resolve(JSON.parse(buffer.split('\n')[0])); }
    });
  });
  async function invoke(command, payload = {}, authenticated = true) {
    const response = await fetch(`http://127.0.0.1:${ready.port}/api/backend`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...(authenticated ? { Cookie: 'grand_agent_session=fixture-token' } : {}) },
      body: JSON.stringify({ command, payload: { conversationId: 'task-a', _operatorIdentity: 'spoofed', ...payload } }),
    });
    return { status: response.status, body: await response.json() };
  }
  assert.equal((await invoke('get_agent_collaboration_command', {}, false)).status, 401);
  const initial = (await invoke('get_agent_collaboration_command')).body.data;
  assert.equal(initial.preferences.evaluation, false);
  assert.equal(initial.preferences.rehearsal, false);
  assert.equal(initial.preferences.learning, false);
  const question=JSON.parse(readFileSync(path.join(root,'question.json'),'utf8'));
  assert.equal((await invoke('answer_agent_question_command',{conversationId:'task-b',questionId:question.questionId,answer:'wrong task'})).body.ok,false);
  assert.equal((await invoke('answer_agent_question_command',{questionId:question.questionId,answer:'Artifact canvas'})).body.ok,true);
  const saved = await invoke('save_agent_collaboration_command', { expectedRevision: 0, preferences: { clarification: 'thorough', directions: 'varied', learning: true } });
  assert.equal(saved.body.ok, true, JSON.stringify(saved));
  assert.equal(saved.body.data.revision, 1);
  const conflict = await invoke('save_agent_collaboration_command', { expectedRevision: 0, preferences: { learning: false } });
  assert.equal(conflict.body.ok, false);
  const selected = await invoke('review_agent_brief_command', { expectedRevision: 1, directionId: 'canvas', correction: 'Keep the existing start screen.' });
  assert.equal(selected.body.ok, true, JSON.stringify(selected));
  assert.equal(selected.body.data.brief.selection.source, 'fixture-operator');
  assert.equal(selected.body.data.brief.corrections[0].source, 'fixture-operator');
  assert.equal(selected.body.data.brief.authorityGranted, false);
  assert.equal((await invoke('review_agent_brief_command', { expectedRevision: 1, directionId: 'queue' })).body.ok, false);
  assert.equal((await invoke('review_agent_brief_command', { expectedRevision: 2, directionId: 'missing' })).body.ok, false);
  const other = (await invoke('get_agent_collaboration_command', { conversationId: 'task-b' })).body.data;
  assert.equal(other.brief, null);
  assert.equal(other.preferences.learning, false);
  assert.equal((await invoke('get_agent_collaboration_command', { conversationId: 'not-a-conversation' })).body.ok, false);
  const reloaded = (await invoke('get_agent_collaboration_command')).body.data;
  assert.equal(reloaded.brief.selection.id, 'canvas');
  assert.equal(reloaded.preferences.directions, 'varied');
  const core = JSON.parse(readFileSync(path.join(root, 'core-checks.json'), 'utf8'));
  assert.deepEqual(core, { modelCannotSupplyOperator: true, strictBoolean: true, duplicateDirectionRejected: true });
  const receipt = { status: 'verified', boundary: 'production store and authenticated HTTP behavior; no model or rendered-UI claim', checks: ['authentication', 'opt-in defaults', 'preference persistence', 'revision conflict', 'operator identity', 'direction selection', 'correction persistence', 'stale answer rejected', 'unknown direction rejected', 'task isolation', 'unknown task rejected', 'model authority rejection', 'strict values', 'unique directions'] };
  mkdirSync(path.join(repo, 'proof/system-improvement'), { recursive: true });
  writeFileSync(path.join(repo, 'proof/system-improvement/collaboration-checks.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
} finally {
  child.kill(); await closed;
  if (path.dirname(path.resolve(root)) !== path.resolve(tmpdir()) || !path.basename(root).startsWith('neyvia-collaboration-')) throw Error('Unexpected temporary cleanup path');
  rmSync(root, { recursive: true, force: true });
}
