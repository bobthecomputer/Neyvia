// Real authenticated user/model/desktop state path; starts bounded Luna runs.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const repo = path.resolve(import.meta.dirname, '..');
const root = path.join(repo, '.agent_control/t13/runtime');
const base = 'http://127.0.0.1:48421';
const version3 = process.argv.includes('--v3');
const version2 = process.argv.includes('--v2')||version3;
const observe = process.argv.includes('--observe');
const output = path.join(repo, `.agent_control/t13/http-proof${version3?'-v3':version2?'-v2':''}.json`);
const proof = {schema:'neyvia.T13.http-journey.v1',at:new Date().toISOString(),root,base,checks:[],runs:{},
  browser:{chrome:'Browser is not available: chrome',iab:'Browser is not available: iab',rendered:false}};
let cookie='';
function save(){fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(proof,null,2));}
function record(name,data=true){proof.checks.push({name,data});save();console.log(name);}
async function request(route,body,raw=false){
  const response=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{'content-type':'application/json',cookie},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data=await response.json();
  if(raw)return {status:response.status,data};
  assert.ok(response.ok,JSON.stringify(data));assert.notEqual(data.ok,false,JSON.stringify(data));
  return data.data ?? data;
}
const command=(command,payload={},raw=false)=>request('/api/backend',{command,payload},raw);
const tool=async(name,args={})=>{const receipt=await request('/api/ui/tools/call',{tool:'neyvia.'+name,arguments:args});assert.notEqual(receipt.ok,false,JSON.stringify(receipt));return receipt.result??receipt;};
async function main(){
  const denied=await request('/api/ui/evolver',undefined,true);assert.equal(denied.status,401);record('unauthenticated observer refused');
  const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
  assert.ok(login.ok);cookie=login.headers.getSetCookie().map(row=>row.split(';')[0]).join(';');
  const catalog=await request('/api/ui/tools');
  for(const op of ['state','lineage','receipt','genome','run','job'])assert.ok(catalog.tools.some(row=>row.name==='neyvia.evolver.'+op));
  record('six real model tools discoverable');
  const wrong=await request('/api/ui/evolver',{operation:'state',_expectedStateRoot:repo},true);assert.equal(wrong.status,409);record('wrong workspace refused');
  const edit=await command('evolver_run_command',{domain:'manual_compression',requestId:'t13-illegal-judge',judges:[]},true);assert.equal(edit.status,400);record('judge editing refused at application boundary');
  const invalid=await command('evolver_run_command',{domain:'manual_compression',requestId:'t13-illegal-budget',maxTrials:99},true);assert.equal(invalid.status,400);record('unbounded trial request refused');
  const manual=await tool('manual.validate',{id:'hill-climb'});record('executable hill-climb manual validated',manual);
  const journey=await tool('manual.run',{id:'hill-climb',chapter:'evolver',procedure:'inspect'});assert.equal(journey.status,'completed');record('model executed manual observer procedure',journey);
  for(const domain of (version3?['manual_compression_v2','cl_skill_v3']:version2?['manual_compression_v2','cl_skill_v2']:['manual_compression','cl_skill'])){
    const requestId=observe ? (domain==='cl_skill_v3'?'t13-live-cl_skill_v3-trial1':domain==='cl_skill_v2'?'t13-live-cl_skill_v2-trial2':'t13-live-'+domain+'-v1-retry') : 't13-live-'+domain+'-v1'+(process.argv.includes('--retry')?'-retry':'');
    const args={domain,requestId,maxTrials:1};
    const started=observe ? await tool('evolver.job',{requestId}) : await command('evolver_run_command',args);assert.equal(started.ok,true);record((observe?'observed ':'started ')+domain,{requestId,state:started.job.state});
    const replay=await command('evolver_run_command',args);assert.equal(replay.replayed,true);assert.equal(replay.job.pid,started.job.pid);record('retry did not duplicate '+domain);
    const collision=await command('evolver_run_command',{...args,maxTrials:2},true);assert.equal(collision.status,400);record('request identity collision refused '+domain);
    const deadline=Date.now()+1500000;
    let job;
    while(Date.now()<deadline){job=(await tool('evolver.job',{requestId})).job;if(['completed','failed'].includes(job.state))break;await new Promise(resolve=>setTimeout(resolve,2000));}
    assert.ok(job&&['completed','failed'].includes(job.state),'Job did not finish');
    proof.runs[domain]=job;save();assert.equal(job.state,'completed',job.error);
    const userState=await request('/api/ui/evolver?domain='+domain);
    const modelState=await tool('evolver.state',{domain});
    assert.equal(userState.domains[0].incumbent,modelState.domains[0].incumbent);assert.equal(userState.domains[0].trials,modelState.domains[0].trials);
    assert.ok(modelState.domains[0].frozen_lock.ok);record('user and model share locked state '+domain,{incumbent:userState.domains[0].incumbent,trials:userState.domains[0].trials});
    const lineage=await tool('evolver.lineage',{domain});assert.ok(lineage.lineage.length>=2);record('durable lineage '+domain,{count:lineage.lineage.length});
    const genome=await tool('evolver.genome',{domain,genome:lineage.incumbent});assert.ok(genome.genome.text.length>0);record('actual incumbent document readable '+domain,{id:genome.id,characters:genome.genome.text.length});
    const receipt=await tool('evolver.receipt',{domain,trial:modelState.domains[0].trials});assert.ok(receipt.receipt.stages.length>=1);record('actual paired receipt '+domain,{state:receipt.receipt.state,promoted:receipt.receipt.promoted,panels:receipt.receipt.stages.map(row=>row.panel)});
  }
  const lab=await request('/api/ui/lab');assert.ok(lab.evolver.domains.length>=2);record('Hill-climb Lab reads both real domains');
  const python='C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
  const desktop=spawnSync(python,['-c','import json; from pathlib import Path; from grant_agent.desktop_bridge import dispatch_desktop_command; state=dispatch_desktop_command(Path('+JSON.stringify(root)+'), "evolver_state_command", {}); print(json.dumps({"domains":[{key:row[key] for key in ("id","incumbent","trials","evaluations")} for row in state["domains"]]}))'],
    {cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src'),NEYVIA_UI_BACKEND_URL:base,NEYVIA_CONNECTED_SERVICE_PORT:'48421'},encoding:'utf8',windowsHide:true});
  assert.equal(desktop.status,0,desktop.error?.message??desktop.stderr);const state=JSON.parse(desktop.stdout);assert.deepEqual(state.domains,lab.evolver.domains.map(row=>Object.fromEntries(['id','incumbent','trials','evaluations'].map(key=>[key,row[key]]))));record('fresh desktop IPC reads same persisted domain state');
  proof.finishedAt=new Date().toISOString();save();console.log('T13 real HTTP journey complete');
}
main().catch(error=>{proof.error=String(error.stack??error);save();console.error(proof.error);process.exitCode=1;});
