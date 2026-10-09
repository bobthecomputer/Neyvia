// Real backend/MCP/CLI acceptance journeys with independent file verification.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawn,spawnSync} from 'node:child_process';
import readline from 'node:readline';
import {randomUUID,createHash} from 'node:crypto';

const repo=process.cwd(), python='C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const evidence=path.join(repo,'scripts/evidence'), root=path.join(repo,'.agent_control','t17-proof',randomUUID());
const saved=path.join(evidence,'T17-runs');fs.mkdirSync(saved,{recursive:true});fs.mkdirSync(root,{recursive:true});
const base='http://127.0.0.1:48191',calls=[],checks=[],journeys=[];
const env={...process.env,PYTHONPATH:path.join(repo,'src'),FLUXIO_WATCHDOG_AUTOSTART:'0',NEYVIA_WEB_PORT:'48191',NEYVIA_CONNECTED_SERVICE_PORT:'48191'};
delete env.NEYVIA_UI_STATE_ROOT;delete env.NEYVIA_UI_BACKEND_URL;
function check(value,label){assert.ok(value,label);checks.push(label);}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function stop(child){if(child && child.exitCode===null)spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});}
function fixtures(folder){fs.mkdirSync(folder,{recursive:true});for(const [name,text] of Object.entries({'alpha.txt':'cobalt orchard 739\n','beta.txt':'saffron meadow 241\n','gamma.txt':'original project brief\n','delta.txt':'violet river 852\n'}))fs.writeFileSync(path.join(folder,name),text);}
fixtures(root);
function mcp(folder,mode='workspace'){
 const child=spawn(python,['-m','grant_agent.neyvia_mcp_stdio','--root',folder,'--permission-mode',mode,'--session-id','t17-proof'],{cwd:repo,env,windowsHide:true,stdio:['pipe','pipe','pipe']});
 const pending=new Map();let id=0,stderr='';child.stderr.on('data',c=>stderr+=c);
 readline.createInterface({input:child.stdout}).on('line',line=>{let a;try{a=JSON.parse(line);}catch{return;}const p=pending.get(a.id);if(p){pending.delete(a.id);clearTimeout(p.timer);a.error?p.reject(Error(a.error.message)):p.resolve(a.result);}});
 child.on('exit',code=>{for(const p of pending.values())p.reject(Error(`MCP exited ${code}: ${stderr}`));});
 return {child,async call(name,args={}){const n=++id;const result=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('MCP deadline '+name)),180000);pending.set(n,{resolve,reject,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id:n,method:'tools/call',params:{name:'neyvia.'+name,arguments:args}})+'\n');});calls.push({transport:'stdio',name,args,result});let v=result.structuredContent;while(v?.tool && v.result)v=v.result;return v;},close(){stop(child);}};
}
let backend,cookie='',api;
async function http(url,args){const response=await fetch(base+url,{method:args?'POST':'GET',headers:{'Content-Type':'application/json',...(cookie?{Cookie:cookie}:{})},...(args?{body:JSON.stringify(args)}:{}),signal:AbortSignal.timeout(180000)});const value=await response.json();calls.push({transport:'HTTP',url,args,status:response.status,value});if(response.headers.get('set-cookie'))cookie=response.headers.get('set-cookie').split(';')[0];return {status:response.status,...value};}
async function terminal(id){for(let i=0;i<240;i++){const v=(await http('/api/ui/autopilot?runId='+id)).data.run;if(['completed','blocked','waiting_approval','stopped'].includes(v.status))return v;await sleep(500);}throw Error('Autopilot deadline');}
function startServer(){const child=spawn(python,['scripts/run_web_backend.py','--host','127.0.0.1','--port','48191','--root',root,'--skip-runtime-auto-update'],{cwd:repo,env,windowsHide:true,stdio:['ignore','pipe','pipe']});const log=fs.createWriteStream(path.join(saved,'backend.log'),{flags:'a'});child.stdout.pipe(log);child.stderr.pipe(log);return child;}
async function ready(){for(let i=0;i<90;i++){try{const r=await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)});if(r.status!==502)return;}catch{}await sleep(300);}throw Error('Backend unavailable');}
const tasks=[
 {id:'read-search',text:'Read alpha.txt and verify cobalt orchard. Also read beta.txt and confirm saffron meadow. Finally find the text orchard across *.txt and report the matching file.',scope:['workspace.read','workspace.search','runtime.environment']},
 {id:'edit-confirm',text:'Replace alpha.txt with exactly "cobalt orchard release ready" (no trailing newline). Also replace beta.txt with exactly "saffron meadow release ready" (no trailing newline). Then read alpha.txt to confirm the exact replacement, and read beta.txt to confirm its exact replacement.',scope:['workspace.read','workspace.write','runtime.environment']},
 {id:'brief-runtime',text:'Replace gamma.txt with exactly "project brief approved" (no trailing newline). Also read delta.txt and confirm violet river. Finally inspect the real local runtime environment and report the selected workspace root.',scope:['workspace.read','workspace.write','runtime.environment']},
];
function verifyTask(task,folder){if(task.id==='edit-confirm'){assert.equal(fs.readFileSync(path.join(folder,'alpha.txt'),'utf8'),'cobalt orchard release ready');assert.equal(fs.readFileSync(path.join(folder,'beta.txt'),'utf8'),'saffron meadow release ready');}if(task.id==='brief-runtime')assert.equal(fs.readFileSync(path.join(folder,'gamma.txt'),'utf8'),'project brief approved');assert.match(fs.readFileSync(path.join(folder,'delta.txt'),'utf8'),/violet river/);}
async function baseline(task){
 if(process.argv.includes('--reuse-baselines')){
  const previous=JSON.parse(fs.readFileSync(path.join(evidence,'T17.json'),'utf8')).journeys.find(j=>j.task.id===task.id);
  assert.equal(previous.task.text,task.text);verifyTask(task,previous.normal.root);
  check(previous.normal.toolCalls>=3,'retained normal '+task.id+' has actual tool receipts and independently rechecked effects');
  return {...previous.normal,retainedFromPriorRun:true};
 }
 const folder=path.join(root,'normal',task.id);fixtures(folder);
 const nodeEntry=path.join(process.env.APPDATA,'npm/node_modules/@openai/codex/bin/codex.js');
 const args=[nodeEntry,'exec','--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check','--sandbox','read-only','--model','gpt-6-luna','--json','--cd',folder,'-c','project_doc_max_bytes=0','-c','model_reasoning_effort="low"','-c','web_search="disabled"','--enable','skip_host_skill_discovery'];
 for(const f of ['shell_tool','unified_exec','apps','plugins','skill_search','memories','multi_agent','multi_agent_v2','browser_use','browser_use_external','computer_use','in_app_browser','image_generation','goals','hooks','daemon_auto_start','sleep_tool','view_image'])args.push('--disable',f);
 args.push('-c','mcp_servers.neyvia.command='+JSON.stringify(python),'-c','mcp_servers.neyvia.args='+JSON.stringify(['-m','grant_agent.neyvia_mcp_stdio','--root',folder,'--permission-mode','workspace']),'-c','mcp_servers.neyvia.env.PYTHONPATH='+JSON.stringify(path.join(repo,'src')),'-c','mcp_servers.neyvia.tool_timeout_sec=180','-c','mcp_servers.neyvia.tools={"neyvia.native.call"={approval_mode="approve"}}','-');
 const child=spawn(process.execPath,args,{cwd:repo,env,windowsHide:true,stdio:['pipe','pipe','pipe']});
 const out=fs.createWriteStream(path.join(saved,'normal-'+task.id+'.jsonl')),err=fs.createWriteStream(path.join(saved,'normal-'+task.id+'.stderr.txt'));let stdout='';child.stdout.on('data',c=>stdout+=c);child.stdout.pipe(out);child.stderr.pipe(err);
 const started=Date.now();child.stdin.end('Use only the neyvia MCP tools for this task. Execute it normally, with direct workspace.read/workspace.write/workspace.search/runtime.environment calls through neyvia.native.call; search/describe tools as needed. Do not use autopilot or manual.run or compiled scripts. No shell, no check-ins, no outside access. CAS writes need the observed SHA-256 and a stable actionId. Read back every write before finishing. Complete every ask:\n'+task.text);
 const timer=setTimeout(()=>stop(child),180000);const code=await new Promise(r=>child.on('exit',r));clearTimeout(timer);
 const events=stdout.split('\n').filter(Boolean).map(l=>{try{return JSON.parse(l);}catch{return {};}});const usage=events.filter(x=>x.type==='turn.completed').at(-1)?.usage;
 check(code===0 && usage,'normal '+task.id+' real Luna CLI returns usage');verifyTask(task,folder);
 const toolEvents=events.filter(x=>x.type==='item.completed' && x.item?.type==='mcp_tool_call' && x.item.status==='completed');check(toolEvents.filter(x=>x.item.tool==='neyvia.native.call').length>=3,'normal '+task.id+' completes at least three actual native MCP calls');
 return {model:'gpt-6-luna',elapsedMs:Date.now()-started,tokens:{input:usage.input_tokens,cachedInput:usage.cached_input_tokens,output:usage.output_tokens,total:usage.input_tokens+usage.output_tokens},toolCalls:toolEvents.length,receipt:'scripts/evidence/T17-runs/normal-'+task.id+'.jsonl',root:folder};
}
try{
 api=mcp(root);
 const grounding=await api.call('manual.validate',{id:'autopilot'});check(grounding.manuals[0].grounded,'autopilot manual grounded against registered production tools');
 const warmups=[];
 for(const inputs of [{path:'alpha.txt',phrase:'cobalt orchard'},{path:'beta.txt',phrase:'saffron meadow'}]){
  for(let i=0;i<3;i++){const v=await api.call('manual.run',{id:'workspace',chapter:'files',procedure:'read-and-confirm',inputs});check(v.status==='completed','real compiler source readback succeeds');warmups.push(v.runId);}
  const script=await api.call('manual.compile',{id:'workspace',chapter:'files',procedure:'read-and-confirm',inputs,minRuns:3});check(script.zeroToken,'verified repeated read compiles to zero-token script');
 }
 // A compiled search learns its judgement from three identical observed states.
 for(let i=0;i<3;i++){let v=await api.call('manual.run',{id:'workspace',chapter:'files',procedure:'find-source',inputs:{query:'orchard',includeGlob:'*.txt'}});v=await api.call('manual.run',{id:'workspace',chapter:'files',procedure:'find-source',runId:v.runId,decisions:{'search-coverage':'use-matches'}});check(v.status==='completed','real compiler source search judgement retained');warmups.push(v.runId);}
 const searchCompile=await api.call('manual.compile',{id:'workspace',chapter:'files',procedure:'find-source',inputs:{query:'orchard',includeGlob:'*.txt'},minRuns:3});check(searchCompile.zeroToken,'identical search judgement compiled');
 api.close();api=null;
 backend=startServer();await ready();
 check((await http('/api/ui/autopilot')).status===401,'owner HTTP denies unauthenticated inspection');
 check((await http('/api/auth/local-session',{})).ok,'scratch owner local sign-in');
 for(const task of tasks){
  const launch=await http('/api/ui/autopilot',{operation:'start',requestId:'T17-'+task.id,text:task.text,scopeTools:task.scope,sessionId:'t17-'+task.id});check(launch.ok && launch.data.run.runId,'owner start returns durable run immediately');
  const run=await terminal(launch.data.run.runId);fs.writeFileSync(path.join(saved,'autopilot-'+task.id+'.json'),JSON.stringify(run,null,2));
  check(run.status==='completed','autopilot '+task.id+' completes all asks without human check-ins');check(run.items.length>=3 && run.items.every(x=>x.verification.passed),'autopilot '+task.id+' final checks independently observed');verifyTask(task,root);
  const normal=await baseline(task);journeys.push({task,autopilot:run,normal,humanCheckins:0});
 }
 check(journeys[0].autopilot.items.every(x=>x.route==='script'),'exact learned cohort uses T5 scripts for every first-task item');
 check(journeys[0].autopilot.models.length===1,'compiled task needs model only for initial intent selection');
 const repeat=await http('/api/ui/autopilot',{operation:'start',requestId:'T17-read-search',text:tasks[0].text,scopeTools:tasks[0].scope,sessionId:'t17-read-search'});check(repeat.data.replayed && repeat.data.run.runId===journeys[0].autopilot.runId,'request retry retains original completed receipts');
 check((await http('/api/ui/autopilot',{operation:'start',requestId:'T17-read-search',text:'Different intent',scopeTools:tasks[0].scope})).status===400,'changed intent cannot reuse request id');
 check((await http('/api/ui/autopilot',{operation:'start',requestId:'T17-external',text:'Run a shell command',scopeTools:['terminal.exec']})).ok===false,'outside-scope external action denied before models');
 const badRoot=await http('/api/ui/autopilot',{operation:'list',_expectedStateRoot:path.join(root,'other')});check(badRoot.status===409,'desktop forwarding refuses wrong workspace');
 const resume=await http('/api/ui/autopilot',{operation:'resume',runId:journeys[0].autopilot.runId,scopeTools:['workspace.read']});check(!resume.ok,'resume cannot silently narrow/replace original saved tool scope');
 const ipc=spawnSync(python,['-m','grant_agent.desktop_bridge','--root',root],{cwd:repo,env,input:JSON.stringify({command:'autopilot_get_command',payload:{runId:journeys[0].autopilot.runId}}),encoding:'utf8',windowsHide:true});check(ipc.status===0 && ipc.stdout.includes(journeys[0].autopilot.runId),'fresh desktop IPC worker reads persistent owner run');
 const stopped=await http('/api/ui/autopilot',{operation:'start',requestId:'T17-stop',text:'Read delta.txt and confirm violet river. Also inspect the runtime environment.',scopeTools:['workspace.read','runtime.environment']});await http('/api/ui/autopilot',{operation:'stop',runId:stopped.data.run.runId});await sleep(18000);const retained=await terminal(stopped.data.run.runId);check(retained.status==='stopped' && retained.items.every(x=>!x.receipt),'stop during planning prevents subsequent deterministic actions');
 // Controlled, explicit durable-state fault: one procedure mapping is unmapped.
 // Real models/observations/execution must repair it; no model response is mocked.
 const beforeManual=await http('/api/ui/tools/call',{tool:'neyvia.manual.load',arguments:{id:'workspace',chapter:'files'}});
 retained.items[0].selection.procedure='unmapped-read-label';fs.writeFileSync(path.join(root,'.neyvia/autopilot',retained.runId+'.json'),JSON.stringify(retained));
 await http('/api/ui/autopilot',{operation:'resume',runId:retained.runId});const frontier=await terminal(retained.runId);
 check(frontier.status==='completed' && frontier.items[0].frontier?.[0].status==='quarantined','real big-model frontier exploration repairs controlled unmapped procedure and completes its checks');
 check(frontier.models.some(x=>x.model==='gpt-6.1-sol' && x.reason.startsWith('frontier')),'frontier uses explicit large route after observed missing mapping');
 const afterManual=await http('/api/ui/tools/call',{tool:'neyvia.manual.load',arguments:{id:'workspace',chapter:'files'}});check(beforeManual.data.result.sha256===afterManual.data.result.sha256,'explored patch leaves live manual hash unchanged');
 fs.writeFileSync(path.join(saved,'frontier-controlled.json'),JSON.stringify({injection:'Unknown procedure in stopped durable checklist; no model/tool replies mocked',run:frontier},null,2));
 const failedLaunch=await http('/api/ui/autopilot',{operation:'start',requestId:'T17-verifier-failure',text:'Read delta.txt and verify the phrase missing-marker-9999. Also inspect the runtime environment.',scopeTools:['workspace.read','runtime.environment']});const failed=await terminal(failedLaunch.data.run.runId);check(failed.status==='blocked' && failed.items[0].failedReceipt?.checks.some(c=>c.passed===false),'real failed executable check stays incomplete with explored quarantine');fs.writeFileSync(path.join(saved,'failed-check.json'),JSON.stringify(failed,null,2));
 const uncertain=structuredClone(journeys[1].autopilot);uncertain.runId=createHash('sha256').update('T17-uncertain').digest('hex').slice(0,32);uncertain.requestId='T17-uncertain';uncertain.status='stopped';uncertain.items[0].status='pending';uncertain.items[0].effectUncertain=true;fs.writeFileSync(path.join(root,'.neyvia/autopilot',uncertain.runId+'.json'),JSON.stringify(uncertain));const beforeBytes=fs.readFileSync(path.join(root,'alpha.txt'),'utf8');await http('/api/ui/autopilot',{operation:'resume',runId:uncertain.runId});const uncertainResult=await terminal(uncertain.runId);check(uncertainResult.status==='blocked' && /reconciliation/.test(uncertainResult.error) && fs.readFileSync(path.join(root,'alpha.txt'),'utf8')===beforeBytes,'uncertain effect is reconciled explicitly and never replayed');
 stop(backend);backend=null;await sleep(800);backend=startServer();await ready();cookie='';await http('/api/auth/local-session',{});const restored=(await http('/api/ui/autopilot?runId='+journeys[1].autopilot.runId)).data.run;check(restored.status==='completed' && restored.items[0].receipt.runId===journeys[1].autopilot.items[0].receipt.runId,'backend restart retains exact item receipts without replay');
 api=mcp(root,'read-only');let denied=false;try{await api.call('autopilot.start',{requestId:'T17-readonly-denial',text:tasks[1].text,scopeTools:['workspace.read','workspace.write']});}catch{denied=true;}check(denied,'read-only MCP cannot grant itself workspace writes');
 const retainedMcp=await api.call('autopilot.get',{runId:journeys[0].autopilot.runId});check(retainedMcp.run.status==='completed','real stdio MCP reads same durable run');
 // Export durable engine/compiler/model proof, excluding account data and credentials.
 for(const dir of ['autopilot-model','manual-runs','manual-scripts','manual-patches']){const from=path.join(root,'.neyvia',dir);if(fs.existsSync(from)){fs.mkdirSync(path.join(saved,dir),{recursive:true});for(const name of fs.readdirSync(from))if(name.endsWith('.json'))fs.copyFileSync(path.join(from,name),path.join(saved,dir,name));}}
 fs.copyFileSync(path.join(root,'.neyvia','manual-runs.jsonl'),path.join(saved,'manual-runs.jsonl'));
 const sources={};for(const file of ['src/grant_agent/neyvia_autopilot.py','src/grant_agent/autopilot_model.py','src/grant_agent/neyvia_agent.py','src/grant_agent/neyvia_ui_api.py','src/grant_agent/desktop_bridge.py'])sources[file]=createHash('sha256').update(fs.readFileSync(path.join(repo,file))).digest('hex');
 const proof={schema:'neyvia.T17.acceptance.v1',at:new Date().toISOString(),passed:true,root,port:48191,checks,warmups:{sourceRuns:warmups,count:warmups.length,models:0,note:'Real manual compiler training is separate from measured task execution; scripts are exact input/hash cohorts.'},journeys,sources,calls,limitations:['Claude UI is pending; no rendered Autopilot chat claim.','Automatic authority currently supports observations and saved-source CAS file edits.','CLI model context overhead is measured, not assumed efficient.','NAS sync pending under task isolation.']};
 fs.writeFileSync(path.join(evidence,'T17.json'),JSON.stringify(proof,null,2)+'\n');console.log(JSON.stringify({passed:true,checks:checks.length,journeys:journeys.map(j=>({task:j.task.id,autopilotTokens:j.autopilot.tokens.total,normalTokens:j.normal.tokens.total,autopilotMs:j.autopilot.elapsedMs,normalMs:j.normal.elapsedMs})),receipt:'scripts/evidence/T17.json'}));
}catch(error){fs.writeFileSync(path.join(evidence,'T17-failure.json'),JSON.stringify({error:error.stack,checks,journeys,calls,root},null,2));throw error;}finally{api?.close();stop(backend);}
