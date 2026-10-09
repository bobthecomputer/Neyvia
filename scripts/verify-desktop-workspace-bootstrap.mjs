import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const registry=path.join(root,'.agent_control/workspaces.json');
const before=readFileSync(registry);
const expected=JSON.parse(before);
const started=Date.now();
const proc=spawnSync(resolveNeyviaPython(root).python,['-m','grant_agent.desktop_bridge','--root',root],{
  cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src')},encoding:'utf8',timeout:12000,maxBuffer:8*1024*1024,
  input:JSON.stringify({command:'get_control_room_summary_command',payload:{payload:{root:null,summaryMode:'bootstrap'}}}),
});
assert.equal(proc.status,0,proc.stderr||String(proc.error));
const result=JSON.parse(proc.stdout);
assert.equal(result.ok,true,result.error);
assert.equal(result.data.summaryMode,'bootstrap');
assert.deepEqual(result.data.workspaces.map(w=>w.workspace_id).sort(),expected.map(w=>w.workspace_id).sort());
assert.deepEqual(readFileSync(registry),before,'Reading startup state must preserve registrations');
const frontend=readFileSync(path.join(root,'web/src/neyvia/NeyviaShell.jsx'),'utf8');
const routing=frontend.slice(frontend.indexOf('const DESKTOP_PYTHON_BACKEND_COMMANDS'),frontend.indexOf('function createBackendRequestId'));
assert(routing.includes('"get_control_room_summary_command"'),'Desktop must use the backend that honors bootstrap mode');
const receipt={ok:true,transport:'desktop bridge',summaryMode:result.data.summaryMode,elapsedMs:Date.now()-started,
  workspaces:result.data.workspaces.map(({workspace_id,name,root_path})=>({workspace_id,name,root_path})),registryUnchanged:true,
  registrySha256:createHash('sha256').update(before).digest('hex')};
const proof=path.join(root,'proof/workspace-registration-20260927');mkdirSync(proof,{recursive:true});
writeFileSync(path.join(proof,'bootstrap-check.json'),JSON.stringify(receipt,null,2));
console.log(JSON.stringify(receipt));
