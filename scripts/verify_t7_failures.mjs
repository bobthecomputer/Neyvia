// Focused production failure paths against the owned disposable T7 backend.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,renameSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {randomUUID,randomBytes} from 'node:crypto';
import {resolve} from 'node:path';
const base='http://127.0.0.1:48211',file='scripts/evidence/T7.json',evidence=JSON.parse(readFileSync(file,'utf8'));
const auth=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
const cookie=auth.headers.get('set-cookie').split(';')[0];
async function call(path,body,credentials=cookie){const r=await fetch(base+path,{method:body===undefined?'GET':'POST',headers:{Cookie:credentials,...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)})});return{status:r.status,body:await r.json()}}
function record(name,data={}){evidence.checks.push({name,pass:true,...data});console.log('PASS '+name)}
// Reversibly hide only this task's model receipt, then restore it even on failure.
const receipt=resolve('.agent_control/t7/embedding-model/receipt.json'),held=receipt+'.unavailable-probe';
renameSync(receipt,held);
try{const r=await call('/api/ui/sidebar',{command:'sidebar_preview_command',ids:[]});assert.equal(r.status,200);assert.equal(r.body.ok,false);assert.equal(r.body.data.status,'model_unavailable');record('Real HTTP missing-model refusal without fallback or moves',{response:r.body});}
finally{renameSync(held,receipt)}
// Disposable account, random password kept only in memory and hashed by the backend.
const username='t7viewer'+randomUUID().slice(0,8),password=randomBytes(24).toString('base64url');
const created=await call('/api/backend',{command:'accounts_update_command',payload:{op:'create',username,password}});assert.equal(created.status,200,JSON.stringify(created.body));
try {
 const login=await fetch(base+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});assert.equal(login.status,200);const viewerCookie=login.headers.get('set-cookie').split(';')[0];
 for(const [path,body] of [['/api/ui/sidebar',undefined],['/api/ui/sidebar',{command:'sidebar_preview_command',ids:[]}],['/api/backend',{command:'sidebar_state_command',payload:{ids:[]}}]]){
  const r=await call(path,body,viewerCookie);assert.equal(r.status,403,JSON.stringify(r));
 }
 record('Real secondary account denied sidebar GET, POST and named desktop route');
}finally{await call('/api/backend',{command:'accounts_update_command',payload:{op:'remove',username}})}
// A controlled durable undo record exercises absence versus explicit null.
const identity='t7-presence-fixture-'+randomUUID(),undoId='t7-undo-'+randomUUID();
const seed="import sys,json;from pathlib import Path;from grant_agent.ui_command_bus import bus_for;b=bus_for(Path(sys.argv[1]));i=sys.argv[2];u=sys.argv[3];b.update('sessions',{i:{'project':'subject:presence-fixture','title':'Controlled presence fixture'}});b.put('sidebar:undo:'+u,{'moves':{i:{'before':{'present':False,'value':None},'after':'subject:presence-fixture'}}});print('{}')";
const python='C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
let child=spawnSync(python,['-c',seed,evidence.root,identity,undoId],{encoding:'utf8',windowsHide:true,env:{...process.env,PYTHONPATH:resolve('src'),NEYVIA_UI_STATE_ROOT:evidence.root}});assert.equal(child.status,0,child.stderr);
const restored=await call('/api/ui/sidebar',{command:'sidebar_undo_command',undoId});assert.deepEqual(restored.body.data.restored,[identity]);
child=spawnSync(python,['-c',"import sys,json;from pathlib import Path;from grant_agent.ui_command_bus import bus_for;print(json.dumps(bus_for(Path(sys.argv[1])).get('sessions',{})[sys.argv[2]]))",evidence.root,identity],{encoding:'utf8',windowsHide:true,env:{...process.env,PYTHONPATH:resolve('src'),NEYVIA_UI_STATE_ROOT:evidence.root}});assert.equal(child.status,0,child.stderr);assert.equal(Object.hasOwn(JSON.parse(child.stdout),'project'),false);
record('Controlled undo restores absence of override exactly, rather than writing null',{controlled:true});
writeFileSync(file,JSON.stringify(evidence,null,2)+'\n');
