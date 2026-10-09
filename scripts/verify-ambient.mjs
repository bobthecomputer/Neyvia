// Live API/bus journey and the production frontend reducer; no browser simulation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {initialOsState,reduceUiAction} from '../web/src/neyvia/next/nxOsStore.js';
const base=process.env.AMBIENT_BACKEND||'http://127.0.0.1:48186';
const url=new URL(base);assert.equal(url.hostname,'127.0.0.1');assert(/^4818[1-9]$/.test(url.port));
const root=path.resolve(process.env.AMBIENT_ROOT||'tmp/r-proof');
const auth=await fetch(base+'/api/auth/local-session',{method:'POST',body:'{}',headers:{'Content-Type':'application/json'}});assert(auth.ok);
const cookie=auth.headers.get('set-cookie').split(';')[0],calls=[];
let state=initialOsState({});
for(const on of [false,true]){
 const r=await fetch(base+'/api/ui/tools/call',{method:'POST',body:JSON.stringify({tool:'neyvia.view.ambient',arguments:{on}}),headers:{'Content-Type':'application/json',Cookie:cookie}});
 const receipt=await r.json();assert(r.ok,JSON.stringify(receipt));let v=receipt.data;while(v?.tool&&v.result)v=v.result;
 assert.equal(v.event.action,'view.ambient');assert.deepEqual(v.event.payload,{on});
 state=reduceUiAction(state,v.event.action,v.event.payload);assert.equal(state.ambient,on);calls.push(v);
}
const python='C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const probe=spawnSync(python,['-c',String.raw`
import json,sys
from pathlib import Path
sys.path.insert(0,'src')
from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent.ui_command_bus import UICommandBus
w=workspace_for(Path(sys.argv[1]));before=w.bus.since()
refused=[]
for args in [{},{'on':'false'},{'on':0},{'on':None}]:
 try:w.call('view.ambient',args);raise AssertionError('invalid ambient accepted')
 except ValueError as e:assert str(e)=='on must be true or false';refused.append(args)
assert w.bus.since()==before
print(json.dumps({'persisted':UICommandBus(Path(sys.argv[1])).get('ambient'),'invalidRefused':refused,'invalidEmittedNothing':True}))
`,root],{cwd:process.cwd(),encoding:'utf8',windowsHide:true});assert.equal(probe.status,0,probe.stderr);
const durable=JSON.parse(probe.stdout);assert.equal(durable.persisted,true);
const evidence={backend:base,calls,durable,frontendReducerApplied:true,renderedUiVerified:false,renderedLimit:'Chrome/Computer Use browser inventory is empty; no DOM or screenshot claim.',registrations:['neyvia_view_tools.DEFINITIONS','neyvia_workspace_tools.DEFINITIONS.extend(view)','WorkspaceTools.call view.*','NativeToolRegistry neyvia workspace specs','existing POST /api/ui/tools/call','WorkspaceTools.result -> UICommandBus.emit -> existing nxOsStore view.ambient reducer','manuals/neyvia.manual.json settings chapter']};
fs.mkdirSync('scripts/evidence',{recursive:true});fs.writeFileSync('scripts/evidence/ambient.json',JSON.stringify(evidence,null,2)+'\n');console.log('Ambient live API on/off, durable bus and malformed refusal passed; production reducer applied. Rendering unverified.');
