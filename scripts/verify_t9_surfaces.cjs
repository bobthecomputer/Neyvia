/* Reopen the saved negative journey on the owned backend at 48233.
 * Reads/controls production state; no model invocation and no UI rendering claim.
 */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const repo=path.resolve(__dirname,'..'),base='http://127.0.0.1:48233';
const source=JSON.parse(fs.readFileSync(path.join(repo,'scripts/evidence/T9-conductor-failure.json'),'utf8'));
const job=source.jobs.at(-1),id=job.id;
const receipt={schema:'neyvia.T9.surface-proof.v1',at:new Date().toISOString(),checks:{},commands:[],root:source.root};
let cookie='';
async function post(route,value,raw=false){
 const r=await fetch(base+route,{method:'POST',headers:{'content-type':'application/json',cookie},body:JSON.stringify(value)});
 const j=await r.json();if(raw)return {status:r.status,body:j};assert(r.ok&&j.ok!==false,JSON.stringify(j));return j.data||j;
}
const cmd=(command,payload,raw)=>post('/api/backend',{command,payload},raw);
async function main(){try{
 const auth=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
 assert.equal(auth.status,200);cookie=auth.headers.getSetCookie().map(s=>s.split(';')[0]).join(';');
 const ui=await post('/api/ui/conductor',{operation:'get',id});assert.equal(ui.job.id,id);assert.equal(ui.job.status,'failed');
 const bot=await post('/api/ui/tools/call',{tool:'neyvia.conductor.get',arguments:{id}});
 assert.equal((bot.result||bot).job.id,id);receipt.checks.httpAndBotSameDurableState=true;
 const observer=await post('/api/ui/tools/call',{tool:'neyvia.manual.observe',arguments:{id:'conductor',state:'jobs'}});
 assert.equal(observer.ok,true);receipt.checks.executableManualObserver=true;
 for(const manual of ['conductor','agents']){
  const v=await post('/api/ui/tools/call',{tool:'neyvia.manual.validate',arguments:{id:manual}});assert.equal(v.ok,true);
 }
 receipt.checks.manualsGrounded=true;
 const ipc=spawnSync('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe',
  ['-m','grant_agent.desktop_bridge','--root',source.root],{cwd:repo,windowsHide:true,encoding:'utf8',timeout:45000,
   input:JSON.stringify({command:'conductor_get_command',payload:{id}}),
   env:{...process.env,PYTHONPATH:path.join(repo,'src'),PYTHONDONTWRITEBYTECODE:'1',NEYVIA_CONNECTED_SERVICE_PORT:'48233'}});
 assert.equal(ipc.status,0,ipc.stderr);const desktop=JSON.parse(ipc.stdout);assert.equal(desktop.data.job.id,id);
 assert.equal(desktop.data.job.status,'failed');receipt.checks.desktopPersistentForwarding=true;
 const refusal=await cmd('conductor_control_command',{id,action:'resume'},true);
 assert.equal(refusal.status,409);assert.equal(refusal.body.code,'run_not_active');receipt.checks.failedResumeCoded409=true;
 const conflict=await cmd('conductor_plan_command',{...job.request.intent,requestId:'t9-negative-'+path.basename(source.root).replace('proof-',''),goal:'different'},true);
 assert.equal(conflict.status,409);assert.equal(conflict.body.code,'request_id_conflict');receipt.checks.conflictCoded409=true;
 const invalid=await cmd('conductor_list_command',{limit:101},true);assert.equal(invalid.status,400);receipt.checks.invalidPageCoded400=true;
 const missing=await cmd('conductor_get_command',{id:'harness-job-missing-t9'},true);assert.equal(missing.status,404);receipt.checks.missingJobCoded404=true;
 const dashboard=await cmd('connected_agents_dashboard_command',{limit:1,offset:0});
 assert.equal(dashboard.sessions.length,1);assert.equal(dashboard.limit,1);assert(dashboard.total>1);assert.equal(dashboard.nextOffset,1);
 receipt.checks.dashboardPagingRegistered=true;receipt.dashboard={total:dashboard.total,nextOffset:dashboard.nextOffset,sources:dashboard.sources};
 const retry=await cmd('conductor_plan_command',{...job.request.intent,requestId:'t9-negative-'+path.basename(source.root).replace('proof-','')});
 assert.equal(retry.job.id,id);assert.equal(retry.job.status,'failed');assert.equal(retry.replayed,true);receipt.checks.failedPlanReplayAttachesOnly=true;
 receipt.commands=['conductor_plan_command','conductor_get_command','conductor_list_command','conductor_control_command','connected_session_answer_command','connected_session_stop_command','connected_agents_dashboard_command'];
 receipt.passed=Object.values(receipt.checks).every(Boolean);
}catch(e){receipt.passed=false;receipt.error=e.stack;process.exitCode=1;console.error(e.stack);}
finally{fs.writeFileSync(path.join(repo,'scripts/evidence/T9-surfaces.json'),JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify(receipt));}}
main();
