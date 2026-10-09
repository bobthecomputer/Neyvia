// Real owner HTTP -> installed CLI quota views -> persisted state -> Night Shift.
// Does not read credentials. The account's live quota is never replaced by a fixture.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const repo = path.resolve(import.meta.dirname, '..');
const root = path.join(repo, '.agent_control/t21/runtime');
const base = 'http://127.0.0.1:48311';
const python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const receipt = {schema:'neyvia.T21.live-limits.v1',startedAt:new Date().toISOString(),checks:{},
  groundTruth:{suppliedAt:'2026-10-02',claudeFiveHour:0,claudeWeekly:47,
    fiveHourReset:'2026-10-03T01:50:00Z',weeklyReset:'2026-10-03T18:00:00Z'},
  limitations:['No browser surfaces available through Chrome or IAB; rendered dashboard journey not proven.',
    'OpenCode installed CLI has session stats but no subscription quota interface.',
    'Codex account reports only weekly; omitted 5-hour window is not fabricated.'],registrations:{
    connected_limits_command:['connected_sessions/api.py CONNECTED_COMMANDS and OWNER_COMMANDS','web_backend connected dispatch',
      'desktop_bridge imported CONNECTED_COMMANDS + persistent forward','Tauri call_desktop_backend_command generic IPC','NxAgentDashboard callNx'],
    'neyvia.agents.limits':['neyvia_agents_tools DEFINITIONS/call','neyvia_workspace_tools dispatch','native_tools registry',
      'plugins/neyvia/mcp/neyvia_mcp.py PORTED','manuals/agents.manual.json']}};
let cookie='';
const delay = ms => new Promise(resolve=>setTimeout(resolve,ms));
async function post(route,body,raw=false) {
  const response = await fetch(base+route,{method:'POST',headers:{'content-type':'application/json',cookie},body:JSON.stringify(body)});
  const value = await response.json();
  if(raw)return {status:response.status,body:value};
  assert.equal(response.ok,true,JSON.stringify(value));
  assert.notEqual(value.ok,false,JSON.stringify(value));
  return value.data ?? value.result ?? value;
}
const command=(command,payload={},raw=false)=>post('/api/backend',{command,payload},raw);
const tool=async(tool,arguments_={})=>{const receipt=await post('/api/ui/tools/call',{tool,arguments:arguments_});
  assert.notEqual(receipt.ok,false,JSON.stringify(receipt));return receipt.result ?? receipt;};
async function until(read,timeout=60000) {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline){const value=await read();if(value)return value;await delay(1000);}
  throw Error('Timed out waiting for observed production state');
}
function record(name,value=true){receipt.checks[name]=value;console.log(name);}
const tasks=async()=> (await command('nightshift_tasks_command')).tasks;
async function main(){
  const unauth=await post('/api/backend',{command:'connected_limits_command',payload:{}},true);
  assert.equal(unauth.status,401);record('unauthenticatedReadRefused');
  const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
  assert.equal(login.status,200);cookie=login.headers.getSetCookie().map(s=>s.split(';')[0]).join(';');
  const invalid=await command('connected_limits_command',{refresh:'yes'},true);
  assert.equal(invalid.status,400);record('malformedRefreshRefused');
  const mismatch=await command('connected_limits_command',{_expectedStateRoot:repo},true);
  assert.equal(mismatch.status,409);record('wrongWorkspaceRefused');
  const live=await command('connected_limits_command',{refresh:true,wait:true});
  assert.equal(live.refreshing,false);assert.equal(live.refreshSeconds,180);
  assert.equal(live.providers.find(p=>p.app==='claude-code').status,'ready');
  assert.equal(live.providers.find(p=>p.app==='codex').status,'ready');
  assert.equal(live.providers.find(p=>p.app==='opencode').status,'unavailable');
  const claude=live.limits.filter(r=>r.app==='claude-code');
  assert.equal(claude.length,2);assert.ok(claude.every(r=>!r.stale&&r.source==='claude-usage'));
  assert.equal(claude.find(r=>r.window==='five_hour').resetsAt,receipt.groundTruth.fiveHourReset);
  assert.equal(claude.find(r=>r.window==='seven_day').resetsAt,receipt.groundTruth.weeklyReset);
  assert.ok(Math.abs(claude.find(r=>r.window==='seven_day').usedPercent-47)<=3);
  record('realCliReads',live);
  receipt.groundTruthComparison={fiveHourDelta:claude.find(r=>r.window==='five_hour').usedPercent,
    weeklyDelta:claude.find(r=>r.window==='seven_day').usedPercent-47,
    resetTimesMatch:true,desktopCurrentReadingConfirmed:false};
  const snapshot=spawnSync(python,['scripts/read_live_limits.py','--root',root,'--last-known'],{cwd:repo,windowsHide:true,encoding:'utf8'});
  assert.equal(snapshot.status,0,snapshot.stderr);const saved=JSON.parse(snapshot.stdout);
  assert.deepEqual(saved.limits.map(r=>[r.app,r.window,r.usedPercent,r.at]).sort(),live.limits.map(r=>[r.app,r.window,r.usedPercent,r.at]).sort());
  record('lastKnownLoadedInSeparateProcess',saved);
  const failure=spawnSync(process.execPath,['scripts/verify_t21_failures.mjs'],{cwd:repo,windowsHide:true,encoding:'utf8',timeout:60000});
  assert.equal(failure.status,0,failure.stderr);
  record('failurePath',JSON.parse(fs.readFileSync(path.join(repo,'.agent_control/t21/failure-receipt.json'),'utf8')));
  const dashboard=await command('connected_agents_dashboard_command',{limit:1});
  assert.ok(dashboard.limitProviders.length===3&&dashboard.limits.length>=3);
  record('dashboardProductionRead',{limits:dashboard.limits,providers:dashboard.limitProviders});
  const native=await tool('neyvia.agents.limits');
  assert.ok(native.providers?.length===3);record('nativeBotSameState',{limits:native.limits,providers:native.providers});
  const manual=await tool('neyvia.manual.validate',{id:'agents'});record('groundedManualValidation',manual);
  const manualRun=await tool('neyvia.manual.run',{id:'agents',chapter:'overview',procedure:'refresh-limits'});
  assert.equal(manualRun.status,'completed');record('manualRefreshExecuted',{runId:manualRun.runId,status:manualRun.status});
  const folder=path.join(root,'night-task');fs.mkdirSync(folder,{recursive:true});
  const tag=Date.now().toString(36),holdId='t21-live-hold-'+tag,unknownId='t21-unknown-'+tag,runId='t21-run-'+tag;
  const original=await command('nightshift_resources_command');
  try {
    const hold=claude.find(r=>r.window==='seven_day').usedPercent;
    await command('nightshift_resources_command',{holdAtPlanPercent:Math.floor(hold)});
    await command('nightshift_create_command',{id:holdId,harness:'claude-code',owner:'Claude',folder,prompt:'Reply T21 only.'});
    await command('nightshift_start_command',{ids:[holdId]});
    const held=await until(async()=>{const task=(await tasks()).find(t=>t.id===holdId);return task?.reason?.startsWith('Holding:')&&task;});
    assert.equal(held.status,'waiting');assert.equal(held.runId,null);
    record('realQuotaHoldsNightShift',{threshold:Math.floor(hold),observed:hold,status:held.status,reason:held.reason,runId:held.runId});
    await command('nightshift_stop_command',{id:holdId});
    await command('nightshift_resources_command',{holdAtPlanPercent:70});
    await command('nightshift_create_command',{id:unknownId,harness:'opencode',owner:'Codex',folder,prompt:'Reply T21 only.'});
    await command('nightshift_start_command',{ids:[unknownId]});
    const unknown=await until(async()=>{const task=(await tasks()).find(t=>t.id===unknownId);return task?.reason?.startsWith('Holding:')&&task;});
    assert.equal(unknown.status,'waiting');assert.equal(unknown.runId,null);
    record('unknownQuotaHeldAt70',{status:unknown.status,reason:unknown.reason,runId:unknown.runId});
    await command('nightshift_stop_command',{id:unknownId});
    await command('nightshift_create_command',{id:runId,harness:'codex',owner:'Codex',folder,model:'gpt-6-luna',effort:'low',
      prompt:'Reply exactly T21_LIMITS_REAL_RUN_OK. Do not use tools or alter files.'});
    await command('nightshift_start_command',{ids:[runId]});
    const finished=await until(async()=>{const task=(await tasks()).find(t=>t.id===runId);return ['done','blocked'].includes(task?.status)&&task;},150000);
    receipt.realNightShiftTask=finished;
    assert.equal(finished.status,'done',finished.reason);assert.ok(finished.evidence?.runId);
    const summary=await command('nightshift_summary_command');
    record('realCodexTaskUnder70',{taskId:finished.id,status:finished.status,evidence:finished.evidence,perHarness:summary.perHarness});
  } finally {
    await command('nightshift_resources_command',original);
  }
  // Observe the real 180-second timer without an on-demand refresh or AI turn.
  const before=await command('connected_limits_command');
  const beforeAt=before.limits.find(r=>r.app==='claude-code'&&r.window==='seven_day').at;
  console.log('Waiting for automatic 180-second CLI refresh');
  const automatic=await until(async()=>{const value=await command('connected_limits_command');
    const row=value.limits.find(r=>r.app==='claude-code'&&r.window==='seven_day');
    return !value.refreshing&&row?.at>beforeAt&&value;},240000);
  record('automaticRefreshWithoutModelTurn',{beforeAt,afterAt:automatic.limits.find(r=>r.app==='claude-code'&&r.window==='seven_day').at,
    refreshSeconds:automatic.refreshSeconds,limits:automatic.limits});
}
try{await main();receipt.completedAt=new Date().toISOString();receipt.passed=true;}
catch(error){receipt.passed=false;receipt.error=String(error.message);process.exitCode=1;console.error(receipt.error);}
finally{receipt.acceptance={complete:false,scopedChecksPassed:receipt.passed===true,missing:receipt.limitations};
  fs.mkdirSync(path.join(repo,'scripts/evidence'),{recursive:true});fs.writeFileSync(path.join(repo,'scripts/evidence/T21.json'),JSON.stringify(receipt,null,2)+'\n');}
