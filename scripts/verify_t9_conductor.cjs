/* Real owner HTTP -> detached worker -> installed Codex CLI model runs.
 * Restarts only the child backend this script starts, never its worker tree.
 */
const {spawn, spawnSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const repo = path.resolve(__dirname, '..');
const python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const suffix = Date.now().toString(36);
const root = path.join(repo, '.agent_control/t9/proof-' + suffix);
const folder = path.join(root, 'workspace');
fs.mkdirSync(folder, {recursive:true});
const port = 48232, base = `http://127.0.0.1:${port}`;
const negativeOnly = process.argv.includes('--negative-only');
const receipt = {schema:'neyvia.T9.conductor-proof.v1', startedAt:new Date().toISOString(), root, folder,
  model:'gpt-6-luna', transport:'installed Codex CLI app-server stdio', checks:{}, jobs:[], restarts:[]};
let server, cookie='', id;
const delay = ms => new Promise(r=>setTimeout(r,ms));
async function wait(check, timeout=180000) {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline) {const v=await check();if(v)return v;await delay(500);}
  throw Error('Timed out waiting for observed production state');
}
async function boot() {
  const log=fs.openSync(path.join(root,'backend-'+receipt.restarts.length+'.log'),'a');
  server=spawn(python,['scripts/run_web_backend.py','--host','127.0.0.1','--port',String(port),'--root',root,'--skip-runtime-auto-update'],
    {cwd:repo,windowsHide:true,stdio:['ignore',log,log],env:{...process.env,NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0',
     NEYVIA_CONNECTED_SERVICE_PORT:String(port),NEYVIA_WEB_PORT:String(port),PYTHONDONTWRITEBYTECODE:'1'}});
  fs.closeSync(log);
  await wait(async()=>{if(server.exitCode!==null)throw Error('Backend exited '+server.exitCode);try{return (await fetch(base+'/api/health')).ok;}catch{return false;}},60000);
  const auth=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
  assert.equal(auth.status,200);cookie=auth.headers.getSetCookie().map(s=>s.split(';')[0]).join(';');
}
async function post(route,payload,raw=false) {
  const r=await fetch(base+route,{method:'POST',headers:{'content-type':'application/json',cookie},body:JSON.stringify(payload)});
  const j=await r.json();if(raw)return {status:r.status,body:j};
  if(!r.ok||j.ok===false)throw Error(JSON.stringify({status:r.status,...j}));return j.data||j;
}
const command=(command,payload={},raw=false)=>post('/api/backend',{command,payload},raw);
const get=async()=> (await command('conductor_get_command',{id})).job;
async function stopServer() {if(!server||server.exitCode!==null)return;server.kill();await new Promise(r=>server.once('exit',r));await delay(400);}
async function main() {
 let job;
 try {
  await boot();
  const unauth=await fetch(base+'/api/backend',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({command:'conductor_plan_command',payload:{}})});
  assert.equal(unauth.status,401);receipt.checks.loginRequired=true;
  const options=await command('connected_provider_options_command',{app:'codex'});
  assert(options.models.some(m=>m.id==='gpt-6-luna'));receipt.checks.lunaAdvertised=true;
  for(const name of ['planner','executor','verifier','classifier']) {
   await post('/api/ui/runtime',{action:'profile',name,route:{app:'codex',model:'gpt-6-luna',effort:'low',permissionMode:name==='planner'||name==='classifier'?'ask':'full'}});
  }
  if (!negativeOnly) {
  const goal='Build a small Node sum tool. Implement tally.cjs exporting sum(numbers), accepting only arrays of finite numbers and throwing TypeError otherwise. Add verify.cjs with real node:assert checks for negatives, zero, fractions and invalid inputs. At the beginning of implementation wait 12 seconds using a Node timer, then append exactly one line "build" to runs.txt (one implementation attempt only). Do not commit. No downloads or installs. Verify by running node verify.cjs.';
  const acceptanceChecks=['node verify.cjs exits with code 0 and checks negatives, zero, fractions and invalid inputs','runs.txt contains exactly one line build'];
  const input={requestId:'t9-real-'+suffix,goal,folder,acceptanceChecks,maxRuntimeSeconds:600};
  job=(await command('conductor_plan_command',input)).job;id=job.id;
  job=await wait(async()=>{const j=await get();if(j.status==='failed')throw Error(j.error);return j.conductor?.phase==='ready'&&j;},180000);
  assert(job.conductor.tasks.length>=2);assert.equal(job.conductor.tasks.at(-1).routingProfile,'verifier');
  assert(job.conductor.receipts.every(r=>r.route.model==='gpt-6-luna'&&r.state==='completed'));
  assert.equal(fs.existsSync(path.join(folder,'runs.txt')),false);receipt.checks.plannedBeforeExecution=true;
  receipt.plan=job;
  const replay=(await command('conductor_plan_command',input)).job;
  assert.equal(replay.id,id);assert.equal(replay.pid,job.pid);receipt.checks.idempotentPlan=true;
  const conflict=await command('conductor_plan_command',{...input,goal:'Different intent'},true);
  assert(conflict.status>=400||conflict.body.ok===false);receipt.checks.conflictingIdRefused=true;
  // Changing settings must not redirect any approved task.
  await post('/api/ui/runtime',{action:'profile',name:'executor',route:{app:'codex',model:'gpt-6-luna',effort:'medium',permissionMode:'full'}});
  await command('conductor_control_command',{id,action:'start'});
  job=await wait(async()=>{const j=await get();return j.conductor?.tasks.some(t=>t.status==='running')&&j;},30000);
  const active=job.conductor.tasks.find(t=>t.status==='running');
  assert.equal(active.route.effort,'low');receipt.checks.routesFrozen=true;
  const before={backendPid:server.pid,workerPid:job.pid,jobId:id,runId:active.runId};
  await stopServer();await boot();
  job=await get();
  assert.equal(job.pid,before.workerPid);assert.equal(job.id,before.jobId);
  assert(job.conductor.tasks.some(t=>t.runId===before.runId));
  receipt.restarts.push({before,after:{backendPid:server.pid,workerPid:job.pid,jobId:job.id,runIds:job.conductor.tasks.map(t=>t.runId).filter(Boolean)}});
  receipt.checks.reattachedAfterBackendRestart=true;
  await command('conductor_control_command',{id,action:'pause'});
  job=await wait(async()=>{const j=await get();if(j.status==='failed')throw Error(j.error);return j.conductor?.phase==='paused'&&j;},180000);
  const completed=job.conductor.tasks.filter(t=>t.status==='completed').map(t=>t.runId);
  assert(completed.length>0);assert(job.conductor.tasks.some(t=>t.status==='waiting'));receipt.checks.pauseHoldsDependents=true;
  await command('conductor_control_command',{id,action:'resume'});
  job=await wait(async()=>{const j=await get();if(j.status==='failed')throw Error(j.error);return j.status==='completed'&&j;},180000);
  assert(completed.every(run=>job.conductor.tasks.some(t=>t.runId===run&&t.status==='completed')));
  const verify=spawnSync(process.execPath,['verify.cjs'],{cwd:folder,encoding:'utf8',windowsHide:true});
  assert.equal(verify.status,0,verify.stderr);assert.equal(fs.readFileSync(path.join(folder,'runs.txt'),'utf8').trim(),'build');
  assert.equal(new Set(job.conductor.receipts.map(r=>r.runId)).size,job.conductor.receipts.length);
  assert.equal(job.conductor.tasks.at(-1).verification.passed,true);
  assert(job.conductor.receipts.every(r=>r.route.model==='gpt-6-luna'&&r.state==='completed'));
  receipt.checks.realFilesAndVerification=true;receipt.checks.noDuplicateAttempts=true;receipt.checks.resumePendingOnly=true;
  receipt.checks.actualTokenReceipts=job.conductor.receipts.every(r=>r.usage?.reportedByTransport&&r.usage?.totalTokens>0);
  receipt.jobs.push(job);receipt.localVerification={exitCode:verify.status,stdout:verify.stdout};
  const listed=await command('conductor_list_command',{limit:1,offset:0});assert.equal(listed.jobs[0].id,id);receipt.checks.pagedJobs=true;
  const manual=await post('/api/ui/tools/call',{tool:'neyvia.manual.validate',arguments:{id:'conductor'}});receipt.manual=manual;
  assert.equal(manual.ok,true);receipt.checks.groundedExecutableManual=true;
  const bot=await post('/api/ui/tools/call',{tool:'neyvia.conductor.get',arguments:{id}});
  const botData=bot.result||bot;assert.equal(botData.job.id,id);receipt.checks.sameBotState=true;
  }
  // Important failure path: approval crosses the restarted web/worker boundary,
  // then an independently observed bad file must fail the whole goal.
  await post('/api/ui/runtime',{action:'profile',name:'classifier',route:null});
  await post('/api/ui/runtime',{action:'profile',name:'executor',route:{app:'codex',model:'gpt-6-luna',effort:'low',permissionMode:'ask'}});
  const failureFolder=path.join(root,'failure-workspace');fs.mkdirSync(failureFolder);
  const negative=(await command('conductor_plan_command',{requestId:'t9-negative-'+suffix,folder:failureFolder,
   goal:'Create status.txt containing exactly healthy. Use apply_patch to create the file; request approval if required. Do not run shell commands or edit other files. Keep this as one executor task.',
   acceptanceChecks:['status.txt contains exactly healthy'],maxRuntimeSeconds:300})).job;
  id=negative.id;
  await wait(async()=>{const j=await get();if(j.status==='failed')throw Error(j.error);return j.conductor?.phase==='ready'&&j;});
  await command('conductor_control_command',{id,action:'start'});
  await wait(async()=>{const j=await get();return j.conductor?.tasks.some(t=>t.status==='running')&&j;},30000);
  await command('conductor_control_command',{id,action:'pause'});
  const approvals=new Set();
  job=await wait(async()=>{
   const j=await get();if(j.status==='failed')throw Error(j.error);
   const active=j.conductor?.activeRun,pending=active?.pendingRequest;
   if(pending&&!approvals.has(pending.requestId)) {
    assert.equal(pending.kind,'approval');assert(['item/fileChange/requestApproval','item/permissions/requestApproval'].includes(pending.method));
    await command('connected_session_answer_command',{runId:active.runId,requestId:pending.requestId,response:{decision:'approve'}});
    approvals.add(pending.requestId);
   }
   return j.conductor?.phase==='paused'&&j;
  });
  receipt.approvals=[...approvals];receipt.checks.workerApprovalRelay=approvals.size>0;
  assert.equal(fs.readFileSync(path.join(failureFolder,'status.txt'),'utf8').trim(),'healthy');
  fs.writeFileSync(path.join(failureFolder,'status.txt'),'broken\n');
  await command('conductor_control_command',{id,action:'resume'});
  job=await wait(async()=>{const j=await get();return ['failed','completed'].includes(j.status)&&j;});
  assert.equal(job.status,'failed');assert(job.error.includes('Final verifier did not prove'));receipt.checks.falseAcceptanceRefused=true;
  const failedRunIds=job.conductor.receipts.map(r=>r.runId);
  const denied=await command('conductor_control_command',{id,action:'resume'},true);
  assert(denied.status>=400||denied.body.ok===false);assert.deepEqual((await get()).conductor.receipts.map(r=>r.runId),failedRunIds);
  receipt.checks.failedJobNeverReplayed=true;receipt.jobs.push(job);
  receipt.passed=Object.values(receipt.checks).every(Boolean);
 } catch(e) {receipt.passed=false;receipt.error=e.stack;console.error(e.stack);process.exitCode=1;}
 finally {
  if(id){try{const j=await get();if(j.status==='running')await command('conductor_control_command',{id,action:'stop'});}catch{}}
  await stopServer();receipt.finishedAt=new Date().toISOString();
  fs.mkdirSync(path.join(repo,'scripts/evidence'),{recursive:true});fs.writeFileSync(path.join(repo,negativeOnly?'scripts/evidence/T9-conductor-failure.json':'scripts/evidence/T9-conductor.json'),JSON.stringify(receipt,null,2)+'\n');
  console.log(JSON.stringify({passed:receipt.passed,checks:receipt.checks,receipt:negativeOnly?'scripts/evidence/T9-conductor-failure.json':'scripts/evidence/T9-conductor.json'}));
 }
}
main();
