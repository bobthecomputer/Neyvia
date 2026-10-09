import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = await mkdtemp(path.join(os.tmpdir(), 'neyvia-controller-state-'));
function run(operation, payload = {}) {
  return new Promise((resolve, reject) => {
    const source = [
      'import json,sys',
      'from pathlib import Path',
      'from grant_agent.web_backend import _save_conversation_state,_load_conversation_state',
      'request=json.load(sys.stdin)',
      'root=Path(request["root"])',
      'result=_save_conversation_state(root,request["payload"]) if request["operation"]=="save" else _load_conversation_state(root)',
      'print(json.dumps(result,ensure_ascii=True))',
    ].join('\n');
    const child = spawn(process.env.NEYVIA_PYTHON || 'python', ['-c', source], {
      cwd: repo, env: {...process.env, PYTHONPATH: path.join(repo, 'src')}, stdio: ['pipe','pipe','pipe'],
    });
    let output = '', error = '';
    child.stdout.on('data', bytes => { output += bytes; });
    child.stderr.on('data', bytes => { error += bytes; });
    child.on('error', reject);
    child.on('exit', code => code ? reject(new Error(error)) : resolve(JSON.parse(output)));
    child.stdin.end(JSON.stringify({root:fixture, operation, payload}));
  });
}
const session = (id, date = '2026-09-25T12:00:00Z') => ({id, title:id, createdAt:date, updatedAt:date,
  workspaceId:'pc-workspace',rootPath:'C:/proof/workspace', route:{runtimeId:'neyvia-agent', provider:'opencode-go',model:'deepseek-v4.1-flash',effort:'high'},systemPromptProfile:'custom'});
const turn = (id,title,pending,source) => ({id,title,role:'assistant',pending,source,createdAt:'2026-09-25T12:00:00Z'});
try {
  await run('save',{chatSessions:[session('pc')],chatSessionTranscripts:{pc:[turn('answer','Thinking...',true,'runtime-pending')]}});
  await Promise.all([
    run('save',{mergeExistingTranscripts:true,chatSessions:[session('phone')],chatSessionTranscripts:{phone:[turn('phone-answer','Phone task',false,'backend-runtime-reply')]}}),
    run('save',{mergeExistingTranscripts:true,chatSessions:[session('pc')],chatSessionTranscripts:{pc:[turn('answer','Hi',true,'runtime-stream')]}}),
  ]);
  let state = await run('load');
  assert.deepEqual(new Set(state.chatSessions.map(row=>row.id)),new Set(['pc','phone']));
  assert.equal(state.chatSessionTranscripts.pc[0].title,'Hi','A short first chunk must replace Thinking');
  assert.equal(state.chatSessions.find(row=>row.id==='phone').route.effort,'high');
  assert.equal(state.chatSessions.find(row=>row.id==='phone').systemPromptProfile,'custom');
  await run('save',{mergeExistingTranscripts:true,chatSessions:[session('pc')],chatSessionTranscripts:{pc:[{...turn('answer','Complete reply',false,'backend-runtime-reply'),reasoningSummary:'Summary',toolCalls:[{id:'t1',tool:'terminal.exec',status:'completed'}]}]}});
  await run('save',{mergeExistingTranscripts:true,chatSessions:[session('pc','2026-09-25T11:00:00Z')],chatSessionTranscripts:{pc:[turn('answer','Hi',true,'runtime-stream')]}});
  state = await run('load');
  assert.equal(state.chatSessionTranscripts.pc[0].title,'Complete reply');
  assert.equal(state.chatSessionTranscripts.pc[0].pending,false);
  assert.equal(state.chatSessionTranscripts.pc[0].toolCalls[0].tool,'terminal.exec');
  assert.equal(state.chatSessions.length,2);
  await run('save',{mergeExistingTranscripts:true,chatSessions:[{...session('pc'),rootPath:'',route:{model:'',provider:'',effort:''},systemPromptProfile:'auto'}]});
  state=await run('load');
  assert.equal(state.chatSessions.find(row=>row.id==='pc').systemPromptProfile,'custom','A passive copy with the same revision must not reset prompt settings');
  await run('save',{mergeExistingTranscripts:true,chatSessions:[{...session('pc','2026-09-25T12:01:00Z'),rootPath:'',route:{model:'',provider:'',effort:''}}]});
  state=await run('load');
  const retained=state.chatSessions.find(row=>row.id==='pc');
  assert.equal(retained.route.model,'deepseek-v4.1-flash');
  assert.equal(retained.rootPath,'C:/proof/workspace');
  console.log(JSON.stringify({ok:true,concurrentSessionsPreserved:true,finalReplyPreserved:true,routeAndPromptPreserved:true,toolTracePreserved:true}));
} finally {
  assert.ok(fixture.startsWith(path.join(os.tmpdir(),'neyvia-controller-state-')));
  await rm(fixture,{recursive:true,force:true});
}
