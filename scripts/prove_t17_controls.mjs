// Targeted production cancellation/control checks after the independent review.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const repo=process.cwd(),python='C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const proofPath=path.join(repo,'scripts/evidence/T17.json'),proof=JSON.parse(fs.readFileSync(proofPath));
const root=proof.root,base='http://127.0.0.1:48192',checks=[];
const env={...process.env,PYTHONPATH:path.join(repo,'src'),FLUXIO_WATCHDOG_AUTOSTART:'0',NEYVIA_WEB_PORT:'48192',NEYVIA_CONNECTED_SERVICE_PORT:'48192'};delete env.NEYVIA_UI_STATE_ROOT;delete env.NEYVIA_UI_BACKEND_URL;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));let cookie='';
function check(v,label){assert.ok(v,label);checks.push(label);}
async function http(payload){const r=await fetch(base+'/api/ui/autopilot',{method:'POST',body:JSON.stringify(payload),headers:{Cookie:cookie,'Content-Type':'application/json'},signal:AbortSignal.timeout(30000)});return (await r.json()).data;}
async function get(id){const r=await fetch(base+'/api/ui/autopilot?runId='+id,{headers:{Cookie:cookie}});return (await r.json()).data.run;}
const server=spawn(python,['scripts/run_web_backend.py','--host','127.0.0.1','--port','48192','--root',root,'--skip-runtime-auto-update'],{cwd:repo,env,windowsHide:true,stdio:'ignore'});
try{
 for(let i=0;i<100;i++){try{const r=await fetch(base+'/api/auth/local-session',{method:'POST',body:'{}',headers:{'Content-Type':'application/json'}});if(r.ok){cookie=r.headers.get('set-cookie').split(';')[0];break;}}catch{}await sleep(200);}check(cookie,'isolated owner backend ready on 48192');
 const human=structuredClone(proof.journeys[0].autopilot);human.runId=createHash('sha256').update('T17-authority-control').digest('hex').slice(0,32);human.status='stopped';human.needsPaul=['Controlled unresolved publication authority'];fs.writeFileSync(path.join(root,'.neyvia/autopilot',human.runId+'.json'),JSON.stringify(human));await http({operation:'resume',runId:human.runId});await sleep(300);check((await get(human.runId)).status==='waiting_approval','unresolved needsPaul prevents whole-run completion even when local items have checks');
 const before=fs.readFileSync(path.join(root,'alpha.txt'),'utf8');const started=await http({operation:'start',requestId:'T17-crossprocess-stop',text:'Replace alpha.txt with exactly "cancelled edit must not land". Also read beta.txt and confirm saffron meadow.',scopeTools:['workspace.read','workspace.write','runtime.environment']});
 let observed;for(let i=0;i<300;i++){observed=await get(started.run.runId);if(observed.models.length && observed.items[0]?.receipt?.status==='judge')break;await sleep(100);}check(observed.items[0]?.receipt?.status==='judge','actual live edit reaches saved-source judgement before cancellation');
 const stopRequest={jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'neyvia.autopilot.stop',arguments:{runId:started.run.runId}}};
 const ipc=spawnSync(python,['-m','grant_agent.neyvia_mcp_stdio','--root',root,'--permission-mode','read-only'],{cwd:repo,env,input:JSON.stringify(stopRequest)+'\n',encoding:'utf8',windowsHide:true,timeout:30000});check(ipc.status===0 && !JSON.parse(ipc.stdout.trim()).error,'separate read-only MCP process stops the persisted owner run');
 const immediate=await http({operation:'resume',runId:started.run.runId});check(immediate.ok===false && /still stopping/.test(immediate.error),'immediate resume cannot clear a stop while its worker remains active');
 await sleep(16000);const cancelled=await get(started.run.runId);check(cancelled.status==='stopped' && cancelled.items[0].receipt.runId===observed.items[0].receipt.runId && cancelled.models.length>=observed.models.length,'cross-process stop preserves newest child receipts and model totals');check(fs.readFileSync(path.join(root,'alpha.txt'),'utf8')===before,'cancelled CAS edit never changes actual source bytes');
 const deniedEnv={...env};delete deniedEnv.NEYVIA_WEB_PORT;delete deniedEnv.NEYVIA_CONNECTED_SERVICE_PORT;delete deniedEnv.NEYVIA_AUTOPILOT_SERVICE_PORT;
 const noPort=spawnSync(python,['-m','grant_agent.desktop_bridge','--root',root],{cwd:repo,env:deniedEnv,input:JSON.stringify({command:'autopilot_list_command',payload:{}}),encoding:'utf8',windowsHide:true});check(noPort.status===0 && noPort.stdout.includes('explicit isolated service port'),'desktop missing port fails before any default/public service call');
 const receipt={schema:'neyvia.T17.controls.v1',at:new Date().toISOString(),checks,controlledAuthorityState:human.runId,cancelled};fs.writeFileSync(path.join(repo,'scripts/evidence/T17-controls.json'),JSON.stringify(receipt,null,2)+'\n');proof.controls={receipt:'scripts/evidence/T17-controls.json',checks};
 for(const file of ['src/grant_agent/neyvia_autopilot.py','src/grant_agent/autopilot_model.py','src/grant_agent/neyvia_agent.py','src/grant_agent/neyvia_ui_api.py','src/grant_agent/desktop_bridge.py','src/grant_agent/neyvia_workspace_tools.py','src/grant_agent/neyvia_mcp_stdio.py','plugins/neyvia/mcp/neyvia_mcp.py','manuals/autopilot.manual.json','config/neyvia_manuals.json']){
  const hash=createHash('sha256').update(fs.readFileSync(path.join(repo,file))).digest('hex');if(proof.sources[file])assert.equal(hash,proof.sources[file],file+' final evidence source unchanged');else proof.sources[file]=hash;
 }
 fs.writeFileSync(proofPath,JSON.stringify(proof,null,2)+'\n');console.log(JSON.stringify({passed:true,checks:checks.length,receipt:'scripts/evidence/T17-controls.json'}));
}finally{if(server.exitCode===null)spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});}
