/* Owned real-browser operator harness; no answers, route hints or references. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),http=require('node:http'),net=require('node:net');
const {spawn}=require('node:child_process');
const repo=path.resolve(__dirname,'..'),evidence=path.join(repo,'scripts/evidence');
const args=process.argv.slice(2),arg=name=>{const index=args.indexOf(name);return index<0?undefined:args[index+1];};
const ports=['--backend-port','--control-port','--engine-port'].map(n=>Number(arg(n)));
if(ports.some(p=>!Number.isInteger(p)||p<48721||p>48729)||new Set(ports).size!==3)throw Error('Supply three distinct explicit ports48721-48729');
const extraPorts=(arg('--fixture-ports')||'').split(',').filter(Boolean).map(Number);if(extraPorts.some(p=>!Number.isInteger(p)||p<48721||p>48729))throw Error('Explicit fixture origins must remain in assigned range');const proofPorts=[...new Set([...ports,...extraPorts])];
const [backendPort,controlPort,enginePort]=ports,base=`http://127.0.0.1:${backendPort}`;
const taskBytes=fs.readFileSync(path.join(evidence,'C2-webvoyager-tasks.json')),set=JSON.parse(taskBytes);
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const resumed=arg('--resume')?JSON.parse(fs.readFileSync(path.resolve(repo,arg('--resume')))):null;
const root=resumed?path.resolve(repo,resumed.root):path.join(repo,'.agent_control/proofs/C2d',crypto.randomUUID());
if(!root.startsWith(path.join(repo,'.agent_control/proofs/C2d')+path.sep))throw Error('Resume root must stay in this task proof area');
fs.mkdirSync(path.join(root,'config'),{recursive:true});
fs.writeFileSync(path.join(root,'config/neyvia_browser_authority.json'),JSON.stringify({schema:'neyvia.browser-authority.v1',proofPorts}));
const env={...process.env,PYTHONPATH:path.join(repo,'src'),PYTHONDONTWRITEBYTECODE:'1',NEYVIA_PROOF_CREDENTIAL_GUARD:'1',NEYVIA_WEB_PORT:String(backendPort),FLUXIO_WEB_PORT:String(backendPort),NEYVIA_UI_BACKEND_URL:base,NEYVIA_BROWSER_BASE:base,NEYVIA_CONNECTED_SERVICE_PORT:String(backendPort),NEYVIA_BROWSER_PROOF_PORTS:proofPorts.join(','),NEYVIA_BROWSER_PROOF_SCOPE:'C2b',NEYVIA_BROWSER_PROOF_ROOT:root,NEYVIA_TOOL_AUTO_UPDATE:'0',FLUXIO_RUNTIME_AUTO_UPDATE:'0',NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0',FLUXIO_LOCAL_SESSION_BOOTSTRAP:'1',NEYVIA_OBSCURA_EXE:arg('--obscura-exe')};
if(!env.NEYVIA_OBSCURA_EXE||!fs.existsSync(env.NEYVIA_OBSCURA_EXE))throw Error('Supply existing Obscura executable explicitly');
const report=resumed||{schema:'neyvia.C2d.webvoyager-run@1',startedAt:new Date().toISOString(),root:path.relative(repo,root),ports,taskSetSha256:sha(taskBytes),engine:'Obscura or explicitly selected WebView2',executor:'Codex lead and explicitly delegated GPT-6.1 Sol; live CL, learned site manuals, checked batches and admitted LAYA clicks',stealth:false,automationUserAgent:'NeyviaAgent/1.0 (Automation; Obscura)',costBoundary:'Codex token logs metered separately; dollar cost requires an explicit model tariff.',tasks:[],calls:[],missing:[]};
if(report.taskSetSha256!==sha(taskBytes))throw Error('Frozen task set changed');
// No implicit default service port may escape this task's assigned range.
env.NEYVIA_LAYA_URL='http://127.0.0.1:48724';
env.NEYVIA_LAYA_BROWSER_CALIBRATION=path.join(evidence,'C2c-laya-calibration.json');
let backend,native,cookie='',server;const live=new Map();
const output=path.join(evidence,arg('--output')||'C2d-webvoyager.json');
if(fs.existsSync(output)&&!resumed)throw Error('Preserve existing receipt; supply a fresh --output filename');
if(resumed){fs.writeFileSync(output+'.before-resume-'+Date.now()+'.json',JSON.stringify(resumed,null,2)+'\n',{flag:'wx'});delete report.finishedAt;delete report.cleanup;for(const task of report.tasks){live.set(task.id,task);task.began=performance.now()-(Date.now()-Date.parse(task.startedAt));if(task.status==='failed'&&/Cannot read properties of undefined.*slice|Run interrupted before completion/.test(task.reason||'')){task.trace.push({kind:'acquisition_adapter_failure',reason:task.reason,failedAt:task.finishedAt});task.status='needs_recovery';delete task.finishedAt;}if(task.observations.length){const ref=task.observations.at(-1);task.lastObservation=JSON.parse(fs.readFileSync(path.resolve(repo,ref.path)));}}}
const save=()=>fs.writeFileSync(output,JSON.stringify(report,(k,v)=>k==='lastObservation'?undefined:v,2)+'\n');
async function call(op,args={},task){
 const began=performance.now(),record={op,args,taskId:task?.id||null,status:null,startedAt:new Date().toISOString()};
 report.calls.push(record);if(task)task.calls.push(report.calls.length-1);save();
 try{
  const response=await fetch(base+'/api/ui/browser',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op,args}),signal:AbortSignal.timeout(60000)});
  const value=await response.json();Object.assign(record,{status:response.status,ok:value.ok,response:{status:value.status,error:value.error,verification:value.verification,decision_policy:value.decision_policy,selected_action:value.selected_action}});
  if(!response.ok||value.ok===false){const err=Error(JSON.stringify(value));err.value=value;throw err;}return value;
 }catch(err){record.error=err.message;throw err;}
 finally{record.ms=performance.now()-began;save();}
}
function compact(obs){return {...obs,accessibility:undefined,text:obs.text.slice(0,16000),elements:obs.elements.map(e=>({...e,name:e.name.slice(0,240),bounds:undefined})),truncated:obs.truncated};}
function capture(task,obs){task.lastObservation=obs;const filename=`${arg('--observations')||path.basename(output,'.json')+'-observations'}/${task.id.replace(/[^a-z0-9-]/gi,'_')}-${task.observations.length}.json`;fs.mkdirSync(path.dirname(path.join(evidence,filename)),{recursive:true});const bytes=JSON.stringify(obs)+'\n';fs.writeFileSync(path.join(evidence,filename),bytes,{flag:'wx'});task.observations.push({path:'scripts/evidence/'+filename,sha256:sha(bytes),url:obs.url,revision:obs.revision,capturedAt:new Date().toISOString()});save();return compact(obs);}
async function completed(value,task){if(value.actionId&&value.status==='queued'){const row=await call('wait',{actionId:value.actionId,timeoutMs:30000},task);return row.result||row;}return value;}
async function observation(task){const value=await completed(await call('observe',{tabId:task.tabId},task),task);const obs=value.observation||value;if(typeof obs.text!=='string'||!Array.isArray(obs.elements))throw Error('Actual page observation unavailable; queued receipts are not snapshots');return capture(task,obs);}
async function command(body){
 if(body.op==='stop'){setTimeout(stop,100);return {stopping:true};}
 if(body.op==='list')return {tasks:set.tasks.map(({id,site,startUrl,goal})=>({id,site,startUrl,goal,status:live.get(id)?.status||'not_started'}))};
 if(body.op==='status')return {tasks:report.tasks.map(({id,status,steps,elapsedMs,reason,answer})=>({id,status,steps,elapsedMs,reason,answer})),root};
 const definition=set.tasks.find(t=>t.id===body.id);if(!definition)throw Error('Unknown frozen public task');
 let task=live.get(body.id);
 if(body.op==='start'||body.op==='recover'){
  if(task&&body.op==='start')throw Error('Task already started; preserve first attempt');
  const retry=body.op==='recover'&&body.retry===true&&['failed','skipped'].includes(task?.status)&&typeof body.reason==='string'&&body.reason.length>10;
  const observedResume=body.op==='recover'&&body.resumeObserved===true;
  if(observedResume&&(task?.status!=='needs_recovery'||!task.lastObservation?.url||task.lastObservation.authentication?.required||task.steps>=definition.maxActions))throw Error('Observed recovery needs a captured interrupted page, no login wall and remaining action budget');
  const recoveryUrl=observedResume?task.lastObservation.url:task?.startUrl||definition.startUrl;
  if(body.op==='recover'&&!retry&&task?.status!=='needs_recovery'&&!(task?.status==='running'&&body.engine&&body.engine!==task.engine))throw Error('Recovery requires interrupted acquisition, explicit engine change, or reasoned owner retry preserving the terminal attempt');
  if(retry){task.attempts??=[];task.attempts.push({status:task.status,reason:task.reason,answer:task.answer,finishedAt:task.finishedAt,elapsedMs:task.elapsedMs,steps:task.steps,engine:task.engine,answerEvidence:task.answerEvidence});task.trace.push({kind:'explicit_owner_retry',reason:body.reason,at:new Date().toISOString(),timerReset:false});delete task.finishedAt;delete task.reason;delete task.answer;}
  const engine=body.engine||task?.engine||'obscura';if(!['obscura','webview2'].includes(engine)||engine==='webview2'&&!report.native?.connected)throw Error('Explicit selected engine unavailable');
  if(task){task.trace.push({kind:'recover_acquisition',engine,at:new Date().toISOString(),timerReset:false});task.status='running';task.engine=engine;}else{task={...definition,engine,startedAt:new Date().toISOString(),began:performance.now(),status:'running',steps:0,calls:[],observations:[],trace:[],providerCostUSD:null,paidApiCalls:0};live.set(body.id,task);report.tasks.push(task);}save();
  if(observedResume){task.steps++;task.trace.push({kind:'recover_observed_page',url:recoveryUrl,evidence:task.observations.at(-1),timerReset:false});save();}
  try{const opened=await call('tab.open',{url:recoveryUrl,engine},task);task.tabId=opened.tabId;if(opened.actionId)await call('wait',{actionId:opened.actionId,timeoutMs:30000},task);await call('tab.grant',{tabId:task.tabId,enabled:true},task);return await observation(task);}catch(e){task.status='failed';task.reason='Page acquisition failed: '+e.message;task.elapsedMs=performance.now()-task.began;task.finishedAt=new Date().toISOString();save();return {status:task.status,error:task.reason};}
 }
 if(!task||!task.tabId)throw Error('Start task first');
 if(body.op==='observe')return observation(task);
 if(body.op==='cached')return compact(task.lastObservation);
 if(body.op==='passage'){const text=task.lastObservation.text;const start=body.query?Math.max(0,text.toLowerCase().indexOf(String(body.query).toLowerCase())-300):Number(body.start||0);return {url:task.lastObservation.url,start,text:text.slice(start,start+Math.min(20000,Number(body.length||10000))),total:text.length};}
 if(body.op==='manual'){const result=await call('site.manual',{tabId:task.tabId},task);task.manualUses??=[];task.manualUses.push({status:result.status,origin:result.origin,page:result.page,fingerprint:result.fingerprint,validation:result.validation});return {...result,observation:capture(task,result.observation)};}
 if(body.op==='batch'){
  if(task.status!=='running'||task.steps+body.steps.length>definition.maxActions)throw Error('Task terminal or action budget exhausted');
  if(body.revision!==task.lastObservation?.revision)throw Error('Batch requires latest supplied revision');
  const t=performance.now();let result;try{result=await call('action.batch',{tabId:task.tabId,revision:body.revision,steps:body.steps},task);}catch(e){result=e.value||{ok:false,error:e.message};}
  task.steps+=result.receipts?.length||0;task.trace.push({kind:'batch',steps:body.steps,receipts:result.receipts,error:result.error,ms:performance.now()-t});save();return {...result,observation:result.observation?capture(task,result.observation):await observation(task)};
 }
 if(body.op==='follow'){
  if(task.status!=='running'||task.steps>=definition.maxActions||body.revision!==task.lastObservation?.revision)throw Error('Fresh revision and remaining action budget required');
  const link=task.lastObservation.elements.find(e=>e.id===String(body.element)&&e.href&&e.enabled&&!e.secret);if(!link)throw Error('Follow requires an observed link');
  const previous=task.tabId,engine=body.engine||task.engine;task.steps++;const opened=await call('tab.open',{url:link.href,engine},task);task.tabId=opened.tabId;task.engine=engine;if(opened.actionId)await call('wait',{actionId:opened.actionId,timeoutMs:30000},task);await completed(await call('tab.grant',{tabId:task.tabId,enabled:true},task),task);task.trace.push({kind:'follow',from:previous,href:link.href,element:link.id,engine});await call('tab.close',{tabId:previous},task);return observation(task);
 }
 if(body.op==='adopt'){
  if(task.status!=='running'||body.revision!==task.lastObservation?.revision)throw Error('Adoption requires the observed redirect revision');
  if(task.lastObservation.authentication?.required)throw Error('Owner authentication is required');
  const url=task.lastObservation.url,previous=task.tabId;task.steps++;
  const engine=body.engine||task.engine,opened=await call('tab.open',{url,engine},task);task.tabId=opened.tabId;task.engine=engine;if(opened.actionId)await call('wait',{actionId:opened.actionId,timeoutMs:30000},task);await completed(await call('tab.grant',{tabId:task.tabId,enabled:true},task),task);task.trace.push({kind:'adopt_observed_redirect',from:previous,url,engine});await call('tab.close',{tabId:previous},task);return observation(task);
 }
 if(body.op==='decide'){
  const response=await call('decide',{tabId:task.tabId,question:'grounded_action',context:body.context},task);
  task.trace.push({kind:'laya_decision',response});save();return response;
 }
 if(body.op==='action'){
  if(task.status!=='running'||task.steps>=definition.maxActions)throw Error('Task terminal or action budget exhausted');
  if(!body.revision||body.revision!==task.lastObservation?.revision)throw Error('Action must bind the latest supplied observation revision');
  const action={tabId:task.tabId,revision:body.revision,element:String(body.element),action:body.action,...(body.value===undefined?{}:{value:body.value}),...(body.expect?{expect:body.expect}:{})};
  task.steps++;const t=performance.now();let result;
  try{result=await completed(await call('action',action,task),task);task.trace.push({kind:'action',action,response:{verification:result.verification,status:result.status,ok:result.ok},ms:performance.now()-t});}catch(e){task.trace.push({kind:'action',action,error:e.message,response:e.value,ms:performance.now()-t});save();return {error:e.message,observation:await observation(task)};}
  save();return {verification:result.verification,observation:result.observation?capture(task,result.observation):await observation(task)};
 }
 if(body.op==='finish'){
  if(!['failed','skipped','answered'].includes(body.status))throw Error('Finish is failed, skipped or answered pending separate grading');
  if(body.status==='skipped'&&!/login|log.?in|sign.?in|captcha|bot|access wall|account|automation.*block/i.test(body.reason||''))throw Error('Skip needs observed access-wall reason; engine/network errors are failures');
  if(!body.evidence?.length&&task.lastObservation)body.evidence=[{url:task.lastObservation.url,observation:task.observations.at(-1),passage:task.lastObservation.text.slice(0,8000)}];
  if(body.status==='answered'&&(!body.answer||!body.evidence?.length))throw Error('Answer requires evidence pointers');
  if(body.status==='failed'&&!body.reason)throw Error('Failure requires exact cause');
  task.status=body.status;task.answer=body.answer||null;task.reason=body.reason||null;task.answerEvidence=body.evidence||[];task.elapsedMs=performance.now()-task.began;task.finishedAt=new Date().toISOString();delete task.lastObservation;save();try{await call('tab.close',{tabId:task.tabId},task);}catch(e){task.closeError=e.message;}save();return {id:task.id,status:task.status,steps:task.steps,ms:task.elapsedMs};
 }
 throw Error('Unsupported coordinator operation');
}
async function free(port){await new Promise((resolve,reject)=>{const s=net.connect(port,'127.0.0.1');s.on('connect',()=>{s.destroy();reject(Error('Assigned port occupied '+port));});s.on('error',resolve);});}
async function start(){
 report.runtimeSegments??=[];report.runtimeSegments.push({startedAt:new Date().toISOString(),resumed:!!resumed,sourceHashes:Object.fromEntries(['src/grant_agent/browser_dom.js','src/grant_agent/browser_obscura.py','src/grant_agent/browser_site_manuals.py','src/grant_agent/neyvia_browser.py','scripts/c2d_webvoyager.cjs'].map(p=>[p,sha(fs.readFileSync(path.join(repo,p)))]))});save();
 for(const port of ports)await free(port);
 const log=fs.openSync(path.join(root,'backend.log'),'a');backend=spawn('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe',['scripts/run_web_backend.py','--host','127.0.0.1','--port',String(backendPort),'--root',root,'--skip-runtime-auto-update','--skip-proof-self-check'],{cwd:repo,env,windowsHide:true,stdio:['ignore',log,log]});fs.closeSync(log);
 const deadline=Date.now()+60000;let ready=false;while(Date.now()<deadline){if(backend.exitCode!==null)throw Error('Owned backend exited; '+root);try{ready=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(700)})).ok;if(ready)break;}catch{}await new Promise(r=>setTimeout(r,100));}if(!ready)throw Error('Owned backend health timed out');
 const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!login.ok)throw Error('Owner local session bootstrap failed');cookie=login.headers.get('set-cookie').split(';')[0];
 await call('headless.start',{port:enginePort,allowLocalFixtures:true,allowPublicResources:true});
 if(arg('--native-exe')){
  const executable=arg('--native-exe');if(!fs.existsSync(executable))throw Error('Explicit native executable absent');
  const connected=await call('runtime.connect');const fd=fs.openSync(path.join(root,'native.log'),'a');
  native=spawn(executable,[],{cwd:repo,env:{...env,NEYVIA_BROWSER_TOKEN:connected.token},windowsHide:true,stdio:['ignore',fd,fd]});fs.closeSync(fd);
  const buildFile=path.join(evidence,'C2d-native-build.json'),build=fs.existsSync(buildFile)?JSON.parse(fs.readFileSync(buildFile)):null,executableHash=sha(fs.readFileSync(executable));
  report.native={path:executable,sha256:executableHash,connected:false,embeddedSourceBoundary:build?.sha256===executableHash?'Current C2d source-bound offline native build; see C2d-native-build.json':'Existing compiled runtime; embedded-source currency is unproved'};
  const end=Date.now()+45000;while(Date.now()<end&&native.exitCode===null){try{const r=await fetch(base+'/api/ui/browser',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op:'state',args:{}})});const state=await r.json();if(state.runtime?.connected){report.native.connected=true;break;}}catch{}await new Promise(r=>setTimeout(r,200));}
  if(!report.native.connected){report.missing.push('Existing native WebView2 runtime failed to attach within45s; see native.log');native.kill();}save();
 }
 server=http.createServer(async(req,res)=>{try{if(req.method!=='POST'||req.url!=='/command')throw Error('POST /command only');let bytes='';for await(const chunk of req){bytes+=chunk;if(bytes.length>50000)throw Error('Request too large');}const value=await command(JSON.parse(bytes));res.setHeader('Content-Type','application/json');res.end(JSON.stringify(value));}catch(e){res.statusCode=400;res.end(JSON.stringify({error:e.message}));}});await new Promise(r=>server.listen(controlPort,'127.0.0.1',r));
 console.log(JSON.stringify({ready:true,control:`http://127.0.0.1:${controlPort}/command`,output,root}));
}
let stopping=false;async function stop(){if(stopping)return;stopping=true;for(const task of report.tasks)if(task.status==='running'){task.status='failed';task.reason='Run interrupted before completion';task.elapsedMs=performance.now()-task.began;task.finishedAt=new Date().toISOString();}try{if(cookie)await call('headless.stop');}catch(e){report.cleanupError=e.message;}if(native&&native.exitCode===null)native.kill();if(backend&&backend.exitCode===null){const done=new Promise(r=>backend.once('exit',r));backend.kill();await done;}if(server)server.close();report.finishedAt=new Date().toISOString();report.cleanup={backendExited:backend?.exitCode!==null||backend?.signalCode!=null,headlessStopRequested:true,nativeStopRequested:!!native};save();process.exit();}
process.on('SIGINT',stop);process.on('SIGTERM',stop);start().catch(e=>{report.fatal=e.stack;save();console.error(e.stack);stop();});
