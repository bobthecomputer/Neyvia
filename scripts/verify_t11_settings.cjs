/* Real authenticated backend journeys; no pytest, provider substitution or public service. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const net = require('node:net');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const {DatabaseSync} = require('node:sqlite');
const project = path.resolve(__dirname, '..');
const python = 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'neyvia-T11-'));
const root = path.join(scratch, 'state');
const base = 'http://127.0.0.1:48251';
const checks = [];
let child, cookie = '', diagnostics = '', sink, localSink, sinkHits = 0;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function record(name, detail) { checks.push({name, ok:true, detail}); console.log('PASS '+name); }
async function request(route, method='GET', body, authenticated=true) {
  const response = await fetch(base+route, {method, headers:{...(authenticated && cookie ? {Cookie:cookie} : {}), ...(body ? {'Content-Type':'application/json'} : {})},
    ...(body ? {body:JSON.stringify(body)} : {}), signal:AbortSignal.timeout(30000)});
  if (response.headers.get('set-cookie')) cookie = response.headers.get('set-cookie').split(';')[0];
  return {status:response.status, body:await response.json()};
}
async function call(tool, args={}) {
  const result = await request('/api/ui/tools/call','POST',{tool,arguments:args});
  assert.equal(result.status,200,JSON.stringify(result)); return result.body.data.result ?? result.body.data;
}
async function native(tool,args={}) {
  return request('/api/backend','POST',{command:'call_native_tool_command',payload:{tool,arguments:args}});
}
async function state() {
  const result=await request('/api/ui/settings'); assert.equal(result.status,200,JSON.stringify(result)); return result.body.data;
}
async function save(patch, expectedRevision) {
  return request('/api/ui/settings','POST',{patch,expectedRevision:expectedRevision ?? (await state()).revision});
}
async function free(port) {
  await new Promise((resolve,reject)=>{const probe=net.createServer();probe.once('error',reject);probe.listen(port,'127.0.0.1',()=>probe.close(resolve));});
}
async function start() {
  await free(48251);
  child=spawn(python,['scripts/run_web_backend.py','--host','127.0.0.1','--port','48251','--root',root,'--static-root',path.join(scratch,'static'),'--skip-runtime-auto-update'],
    {cwd:project,windowsHide:true,env:{...process.env,NO_PROXY:'*',no_proxy:'*',CODEX_HOME:path.join(scratch,'codex'),CLAUDE_CONFIG_DIR:path.join(scratch,'claude'),OPENCODE_DATA_DIR:path.join(scratch,'opencode'),
      NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0',NEYVIA_TOOL_AUTO_UPDATE:'0',FLUXIO_RUNTIME_AUTO_UPDATE:'0',
      NEYVIA_SIDEBAR_ALLOWED_ROOTS:JSON.stringify([scratch])}});
  child.stdout.on('data',()=>{}); child.stderr.on('data',data=>{diagnostics=(diagnostics+data).slice(-5000);});
  for(let i=0;i<120;i++) {
    if(child.exitCode!==null) throw Error('Backend exited: '+diagnostics);
    try { if((await request('/api/health','GET',undefined,false)).status===200) {
      assert.equal((await request('/api/auth/local-session','POST',{})).status,200); return;
    }} catch {}
    await sleep(500);
  }
  throw Error('Backend startup timeout: '+diagnostics);
}
async function stop() { if(child && child.exitCode===null) {child.kill();await new Promise(resolve=>child.once('exit',resolve));} }
function listen(server,port,host) {return new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,host,resolve);});}
async function runBridge(command,payload={}) {
  const code="import json,sys;from pathlib import Path;from grant_agent.desktop_bridge import dispatch_desktop_command;print(json.dumps(dispatch_desktop_command(Path(sys.argv[1]),sys.argv[2],json.loads(sys.argv[3]))))";
  const bridge=spawn(python,['-c',code,root,command,JSON.stringify(payload)],{cwd:project,windowsHide:true,
    env:{...process.env,PYTHONPATH:path.join(project,'src'),NEYVIA_CONNECTED_SERVICE_PORT:'48251'}});
  let out='',err='';bridge.stdout.on('data',x=>out+=x);bridge.stderr.on('data',x=>err+=x);
  const exit=await new Promise(resolve=>bridge.once('exit',resolve));assert.equal(exit,0,err);return JSON.parse(out);
}
async function main() {
  fs.mkdirSync(root,{recursive:true});
  const validator=spawn(python,['-c',
    'import json,sys;from pathlib import Path;from grant_agent.manual_contracts import validate_grounding;from grant_agent.native_tools import NativeToolRegistry;data=json.loads(Path("config/settings.manual.contract.json").read_text());validate_grounding(data,NativeToolRegistry(Path(sys.argv[1])));print(json.dumps({"grounded":True,"tools":len(data["schemas"]),"procedures":len(data["chapters"]["overview"]["procedures"])}))',path.join(scratch,'manual-validation')],
    {cwd:project,windowsHide:true,env:{...process.env,PYTHONPATH:path.join(project,'src')}});
  let validation='',validationError='';validator.stdout.on('data',data=>validation+=data);validator.stderr.on('data',data=>validationError+=data);
  assert.equal(await new Promise(resolve=>validator.once('exit',resolve)),0,validationError);record('plan-08 Settings manual contract grounded against live tool registry',JSON.parse(validation));
  await start();
  assert.equal((await request('/api/ui/settings','GET',undefined,false)).status,401);record('unauthenticated settings refused');
  let current=await state();assert.equal(current.settings.localOnly,false);assert.equal(current.settings.initiative,'suggest');record('canonical defaults',current.settings);
  const patch={density:'grove',theme:'morning',initiative:'act-and-tell',projectInitiative:{[root]:'silent'},
    cleanup:{noFolderDays:9,projectDays:35,autoArchive:false},nightShift:{paused:true,maxConcurrent:2,maxTaskSeconds:12,maxTaskTokens:900,perHarness:{codex:1}}};
  const saved=await save(patch);assert.equal(saved.status,200,JSON.stringify(saved));current=saved.body.data;
  assert.equal(current.settings.theme,'morning');assert.equal(current.settings.cleanup.noFolderDays,9);assert.equal(current.settings.nightShift.maxTaskTokens,900);
  assert.ok(current.events.some(e=>e.action==='view.layout'));assert.ok(current.events.some(e=>e.action==='view.theme' && e.payload.theme==='light'));
  record('save emits canonical state and existing view bus actions',current.events);
  const conflict=await save({theme:'sunset'},0);assert.equal(conflict.status,409);assert.equal((await state()).settings.theme,'morning');record('stale revision refuses without write');
  const revision=current.revision;
  for(const patch of [{localOnly:'yes'},{theme:'bogus'},{cleanup:{autoArchive:'yes'}},{nightShift:{maxTaskTokens:-1}},{initiative:'full-access'},{bogus:1}]) {
    const bad=await save(patch,revision);assert.equal(bad.status,400,JSON.stringify(bad));assert.equal((await state()).revision,revision);
  } record('invalid writes leave every policy unchanged');
  const race=await Promise.all([save({theme:'sunset'},revision),save({theme:'night-green'},revision)]);assert.deepEqual(race.map(x=>x.status).sort(),[200,409]);record('concurrent saves serialize and reject stale writer');
  current=await state();
  const proposal=await call('neyvia.settings.propose',{patch:{theme:'forest'},expectedRevision:current.revision});assert.equal(proposal.status,'approval_required');
  assert.equal((await state()).settings.theme,current.settings.theme);
  const approval=await request('/api/ui/approve','POST',{id:proposal.approvalId});assert.equal(approval.status,200);assert.equal((await state()).settings.theme,'forest');
  const approvedRevision=(await state()).revision;await request('/api/ui/approve','POST',{id:proposal.approvalId});assert.equal((await state()).revision,approvedRevision);
  const approvals=await request('/api/ui/approvals');assert.ok(!approvals.body.data.requests.some(row=>row.id===proposal.approvalId));
  record('model proposal waits for owner; approval applies once');
  const staleProposal=await call('neyvia.settings.propose',{patch:{density:'workshop'},expectedRevision:approvedRevision});await save({density:'calm'});
  assert.equal((await request('/api/ui/approve','POST',{id:staleProposal.approvalId})).status,409);record('stale proposal approval refuses');
  const setup=await request('/api/ui/settings/setup','POST',{});assert.equal(setup.status,200);assert.equal(setup.body.data.events[0].action,'setup.open');record('setup re-entry emits resumable event');
  const resources=await request('/api/nightshift/resources');assert.equal(resources.status,200);assert.equal(resources.body.data.maxTaskTokens,900);record('Night Shift consumes saved live resource policy',resources.body.data);
  await call('neyvia.view.layout',{level:'workshop'});assert.equal((await state()).settings.density,'workshop');
  await call('neyvia.view.theme',{theme:'night'});assert.equal((await state()).settings.theme,'night-green');record('existing view tools update canonical Settings');
  const budget=await request('/api/nightshift/resources','POST',{maxTaskTokens:901});assert.equal(budget.status,200,JSON.stringify(budget));assert.equal((await state()).settings.nightShift.maxTaskTokens,901);record('existing budget control updates canonical revision');
  // Disposable real conversation, aged in its durable store; no provider/mock run.
  const created=await request('/api/backend','POST',{command:'create_neyvia_conversation_command',payload:{title:'T11 stale housekeeping fixture',titleMode:'off',metadata:{workspacePath:root}}});
  assert.equal(created.status,200,JSON.stringify(created));const conversation=created.body.data.conversationId;
  const conversations=new DatabaseSync(path.join(root,'.agent_control','crashproof.sqlite3'));
  const old='2026-08-01T00:00:00Z';conversations.prepare('UPDATE conversations SET created_at=?,updated_at=?,last_meaningful_activity_at=? WHERE conversation_id=?').run(old,old,old,conversation);conversations.close();
  let observed=false;
  for(let i=0;i<60;i++){
    const listed=await request('/api/backend','POST',{command:'connected_sessions_list_command',payload:{app:'neyvia'}});
    if(listed.body.data?.sessions?.some(row=>row.title==='T11 stale housekeeping fixture')){observed=true;break;}
    await sleep(500);
  }
  assert.ok(observed,'Native broker did not observe the durable fixture before maintenance');
  async function snapshot(){return (await request('/api/ui/state')).body.data;}
  async function waitCleanup(predicate){for(let i=0;i<200;i++){const data=await snapshot();if(predicate(data))return data;await sleep(100);}throw Error('Automatic housekeeping did not reach expected state');}
  await save({initiative:'suggest',projectInitiative:{},cleanup:{autoArchive:true,noFolderDays:1}});
  let housekeeping=await waitCleanup(data=>data.cleanupLastRun?.candidates?.length>0);
  assert.equal(housekeeping.cleanupLastRun.archived.length,0);record('Suggest observes stale real conversation and proposes instead of archiving',housekeeping.cleanupLastRun);
  const busDb=new DatabaseSync(path.join(root,'.agent_control','ui_commands.sqlite3'));
  // Advance only the disposable maintenance throttle; trigger the real timer with save.
  busDb.prepare("UPDATE state SET value='0' WHERE key='cleanupAutomaticAt'").run();
  await save({initiative:'silent',projectInitiative:{[root]:'suggest'}});housekeeping=await waitCleanup(data=>data.cleanupAutomaticAt>0);
  assert.equal(housekeeping.cleanupLastRun.archived.length,0);record('per-project Suggest overrides global Silent');
  busDb.prepare("UPDATE state SET value='0' WHERE key='cleanupAutomaticAt'").run();
  const eventFloor=Number(busDb.prepare('SELECT COALESCE(MAX(id),0) AS id FROM events').get().id);
  await save({projectInitiative:{}});housekeeping=await waitCleanup(data=>data.cleanupLastArchive?.archived?.length>0);
  assert.equal(busDb.prepare("SELECT COUNT(*) AS n FROM events WHERE id>? AND action='notify'").get(eventFloor).n,0);
  const fixtureId=housekeeping.cleanupLastArchive.archived[0];assert.equal(housekeeping.sessions[fixtureId].archived,true);record('Silent automatically archives reversibly with durable receipt',housekeeping.cleanupLastArchive);
  const undone=await call('neyvia.sidebar.tidy',{undoLast:true});assert.ok(undone.restored.includes(fixtureId));assert.equal((await snapshot()).sessions[fixtureId].archived,false);record('automatic archive has real undo');
  await save({initiative:'act-and-tell',cleanup:{autoArchive:false}});busDb.close();
  const childRun=native('terminal.exec',{command:'Start-Sleep -Seconds 4; Write-Output "T11 child finished"',shell:'powershell',cwd:root,timeoutMs:10000});
  for(let i=0;i<30;i++){if((await state()).network.activeChildren>0)break;await sleep(50);}
  assert.ok((await state()).network.activeChildren>0,'Disposable child never started');
  const childConflict=await save({localOnly:true});assert.equal(childConflict.status,409,JSON.stringify(childConflict));assert.equal((await state()).settings.localOnly,false);
  const childResult=await childRun;assert.equal(childResult.body.data.ok,true,JSON.stringify(childResult));record('activation refuses live owned child; child completes normally');
  const external=Object.entries(os.networkInterfaces()).filter(([name])=>/ethernet|wi-?fi|wlan/i.test(name)).flatMap(([,rows])=>rows).find(row=>row.family==='IPv4'&&!row.internal);
  assert.ok(external,'No physical IPv4 address for local nonloopback sink proof');
  sink=http.createServer((req,res)=>{sinkHits++;res.setHeader('Content-Type','text/plain');res.end('T11 live nonloopback sink');});await listen(sink,48253,external.address);
  localSink=http.createServer((req,res)=>{res.setHeader('Content-Type','text/plain');res.end('T11 live loopback service');});await listen(localSink,48254,'127.0.0.1');
  const url=`http://${external.address}:48253/proof`;
  const online=await native('web.fetch',{url,refresh:true});assert.equal(online.status,200,JSON.stringify(online));assert.equal(online.body.data.ok,true);assert.equal(sinkHits,1);record('online native web.fetch reaches real nonloopback sink');
  for(let i=0;i<40;i++){const on=await save({localOnly:true});if(on.status===200)break;assert.equal(on.status,409);if(i===39)throw Error(JSON.stringify({on,network:(await state()).network}));await sleep(250);}
  assert.equal((await state()).network.policy,'loopback-only');
  const denied=await native('web.fetch',{url,refresh:true});assert.equal(denied.body.data.ok,false,JSON.stringify(denied));assert.match(JSON.stringify(denied),/local.only/i);assert.equal(sinkHits,1);record('native fetch blocked; external sink receives zero further requests');
  const local=await native('web.fetch',{url:'http://127.0.0.1:48254/proof',refresh:true});assert.equal(local.body.data.ok,true,JSON.stringify(local));record('real loopback fetch remains operable');
  const diagnostic=await call('neyvia.settings.network_check');assert.equal(diagnostic.ok,true);assert.equal(diagnostic.checks.length,9);assert.ok(diagnostic.checks.every(row=>row.blocked));record('real TCP/connect_ex/IPv6/UDP/DNS/HTTP/HTTPS/child/Windows-async attempts denied',diagnostic);
  const bridge=await runBridge('settings_get_command');assert.equal(bridge.settings.localOnly,true);record('fresh desktop worker forwards to persistent owner service');
  const beforeRestart=await state();await stop();cookie='';await start();current=await state();assert.equal(current.revision,beforeRestart.revision);assert.deepEqual(current.settings,beforeRestart.settings);assert.equal(current.network.localOnly,true);
  record('restart retains preferences and restores network enforcement before startup');
  const deniedAgain=await native('web.fetch',{url,refresh:true});assert.equal(deniedAgain.body.data.ok,false);assert.equal(sinkHits,1);record('restart still blocks nonloopback sink');
  const after=await save({localOnly:false});assert.equal(after.status,200);const restored=await native('web.fetch',{url,refresh:true});assert.equal(restored.body.data.ok,true);assert.equal(sinkHits,2);record('disable restores real network operation');
  const offlineDiagnostic=await call('neyvia.settings.get');assert.equal(offlineDiagnostic.network.policy,'online');
  const refusedDiagnostic=await request('/api/ui/tools/call','POST',{tool:'neyvia.settings.network_check',arguments:{}});assert.equal(refusedDiagnostic.body.data.ok,false);assert.match(refusedDiagnostic.body.data.error,/Enable local-only/);record('network diagnostic refuses online probing');
}
(async()=>{let failure;try{await main();}catch(error){failure=error;console.error(error.stack);console.error(diagnostics);}finally{
  await stop();for(const server of [sink,localSink])if(server)await new Promise(resolve=>server.close(resolve));
  const files=['src/grant_agent/neyvia_settings.py','src/grant_agent/local_network_policy.py','src/grant_agent/web_backend.py','src/grant_agent/neyvia_ui_api.py','src/grant_agent/desktop_bridge.py','src/grant_agent/neyvia_workspace_tools.py','src/grant_agent/neyvia_sidebar_cleanup.py','src/grant_agent/neyvia_view_tools.py','src/grant_agent/nightshift.py','src/grant_agent/nightshift_resources.py','scripts/run_web_backend.py','scripts/verify_t11_settings.cjs','plugins/neyvia/mcp/neyvia_mcp.py','config/settings.manual.contract.json'];
  const receipt={track:'T11',at:new Date().toISOString(),ok:!failure,scratch,ports:[48251,48253,48254,48259],checks,
    sourceHashes:Object.fromEntries(files.map(file=>[file,crypto.createHash('sha256').update(fs.readFileSync(path.join(project,file))).digest('hex')])),
    registrations:{
      settings_get_command:{http:'GET /api/ui/settings',tool:'neyvia.settings.get'},
      settings_update_command:{http:'POST /api/ui/settings',tool:'neyvia.settings.propose (owner applies through /api/ui/approve)'},
      settings_setup_command:{http:'POST /api/ui/settings/setup',tool:'neyvia.settings.setup',event:'setup.open'},
      settings_network_check_command:{http:'POST /api/backend or /api/ui/tools/call',tool:'neyvia.settings.network_check'},
      shared:['FluxioWebBackend.dispatch','desktop_bridge.ALLOWED_DESKTOP_COMMANDS + forward_connected_command','existing generic Tauri call_desktop_backend_command (Python worker path exercised; native Tauri build not exercised)','neyvia_workspace_tools.DEFINITIONS/tool_specs/WorkspaceTools.call','plugins/neyvia/mcp/neyvia_mcp.py PORTED'],
      manual:'config/settings.manual.contract.json is grounded source; Claude must copy to manuals/settings.manual.json and register only after the file exists'
    },
    boundary:'Real authenticated backend HTTP/native-tool/desktop/restart/network journeys, with one disposable native conversation aged in SQLite and its maintenance throttle advanced for initiative/undo proof. Rendered Settings UI and whole-PC firewall behavior are outside this receipt.',
    missing:['Claude rendered Settings/manual journey','T10 aggregate nightly budgets and quiet hours','NAS snapshot pending explicit isolation'],...(failure?{error:failure.message}:{})};
  fs.mkdirSync(path.join(project,'scripts/evidence'),{recursive:true});fs.writeFileSync(path.join(project,'scripts/evidence/T11.json'),JSON.stringify(receipt,null,2)+'\n');
  console.log('Receipt scripts/evidence/T11.json; retained scratch '+scratch);if(failure)process.exitCode=1;
}})();
