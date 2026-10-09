/* Owned real-browser operator harness; no answers, route hints or references. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),http=require('node:http'),net=require('node:net');
const {spawn}=require('node:child_process');
const repo=path.resolve(__dirname,'..'),evidence=path.join(repo,'scripts/evidence');
const args=process.argv.slice(2),arg=name=>args[args.indexOf(name)+1];
const ports=['--backend-port','--control-port','--engine-port'].map(n=>Number(arg(n)));
if(ports.some(p=>!Number.isInteger(p)||p<48721||p>48726)||new Set(ports).size!==3)throw Error('Supply three distinct explicit ports48721-48726');
const [backendPort,controlPort,enginePort]=ports,base=`http://127.0.0.1:${backendPort}`;
const taskBytes=fs.readFileSync(path.join(evidence,'C2-webvoyager-tasks.json')),set=JSON.parse(taskBytes);
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const root=path.join(repo,'.agent_control/proofs/C2c',crypto.randomUUID());
fs.mkdirSync(path.join(root,'config'),{recursive:true});
fs.writeFileSync(path.join(root,'config/neyvia_browser_authority.json'),JSON.stringify({schema:'neyvia.browser-authority.v1',proofPorts:ports}));
const env={...process.env,PYTHONPATH:path.join(repo,'src'),PYTHONDONTWRITEBYTECODE:'1',NEYVIA_PROOF_CREDENTIAL_GUARD:'1',NEYVIA_WEB_PORT:String(backendPort),FLUXIO_WEB_PORT:String(backendPort),NEYVIA_UI_BACKEND_URL:base,NEYVIA_BROWSER_BASE:base,NEYVIA_CONNECTED_SERVICE_PORT:String(backendPort),NEYVIA_BROWSER_PROOF_PORTS:ports.join(','),NEYVIA_BROWSER_PROOF_SCOPE:'C2',NEYVIA_BROWSER_PROOF_ROOT:root,NEYVIA_TOOL_AUTO_UPDATE:'0',FLUXIO_RUNTIME_AUTO_UPDATE:'0',NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0',FLUXIO_LOCAL_SESSION_BOOTSTRAP:'1',NEYVIA_OBSCURA_EXE:arg('--obscura-exe')};
if(!env.NEYVIA_OBSCURA_EXE||!fs.existsSync(env.NEYVIA_OBSCURA_EXE))throw Error('Supply existing Obscura executable explicitly');
const report={schema:'neyvia.C2c.webvoyager-run@1',startedAt:new Date().toISOString(),root:path.relative(repo,root),ports,taskSetSha256:sha(taskBytes),engine:'Obscura',executor:'Codex lead and explicitly delegated GPT-6.1 Sol; model reasoning over live CL, LAYA only where separately admitted',stealth:false,automationUserAgent:'NeyviaAgent/1.0 (Automation; Obscura)',costBoundary:'No API-key provider calls. Codex subscription/model tool costs and local compute unmeasured, not zero.',tasks:[],calls:[],missing:[]};
// No implicit default service port may escape this task's assigned range.
env.NEYVIA_LAYA_URL='http://127.0.0.1:48727';
let backend,cookie='',server;const live=new Map();
const output=path.join(evidence,arg('--output')||'C2c-webvoyager.json');
if(fs.existsSync(output))throw Error('Preserve existing receipt; supply a fresh --output filename');
const save=()=>fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
async function call(op,args={},task){
 const began=performance.now(),record={op,args,taskId:task?.id||null,status:null,startedAt:new Date().toISOString()};
 report.calls.push(record);if(task)task.calls.push(report.calls.length-1);save();
 try{
  const response=await fetch(base+'/api/ui/browser',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op,args}),signal:AbortSignal.timeout(60000)});
  const value=await response.json();Object.assign(record,{status:response.status,response:value});
  if(!response.ok||!value.ok){const err=Error(JSON.stringify(value));err.value=value;throw err;}return value;
 }catch(err){record.error=err.message;throw err;}
 finally{record.ms=performance.now()-began;save();}
}
function compact(obs){return {url:obs.url,title:obs.title,revision:obs.revision,readyState:obs.readyState,authentication:obs.authentication,text:obs.text.slice(0,12000),tables:obs.tables.slice(0,4),elements:obs.elements.filter(e=>e.actions.some(a=>a!=='scroll')).map(({id,role,name,value,actions,enabled,secret})=>({id,role,name:name.slice(0,180),value,actions,enabled,secret})),truncated:obs.truncated};}
async function observation(task){const obs=await call('observe',{tabId:task.tabId},task);task.lastObservation=obs;const filename=`${arg('--observations')||path.basename(output,'.json')+'-observations'}/${task.id.replace(/[^a-z0-9-]/gi,'_')}-${task.observations.length}.json`;fs.mkdirSync(path.dirname(path.join(evidence,filename)),{recursive:true});const bytes=JSON.stringify(obs,null,2)+'\n';fs.writeFileSync(path.join(evidence,filename),bytes,{flag:'wx'});task.observations.push({path:'scripts/evidence/'+filename,sha256:sha(bytes),url:obs.url,revision:obs.revision,capturedAt:new Date().toISOString()});save();return compact(obs);}
async function command(body){
 if(body.op==='stop'){setTimeout(stop,100);return {stopping:true};}
 if(body.op==='list')return {tasks:set.tasks.map(({id,site,startUrl,goal})=>({id,site,startUrl,goal,status:live.get(id)?.status||'not_started'}))};
 if(body.op==='status')return {tasks:report.tasks.map(({id,status,steps,elapsedMs,reason,answer})=>({id,status,steps,elapsedMs,reason,answer})),root};
 const definition=set.tasks.find(t=>t.id===body.id);if(!definition)throw Error('Unknown frozen public task');
 let task=live.get(body.id);
 if(body.op==='start'){
  if(task)throw Error('Task already started; preserve first attempt');
  task={...definition,startedAt:new Date().toISOString(),began:performance.now(),status:'running',steps:0,calls:[],observations:[],trace:[],providerCostUSD:null,paidApiCalls:0};live.set(body.id,task);report.tasks.push(task);save();
  try{task.tabId=(await call('tab.open',{url:task.startUrl,engine:'obscura'},task)).tabId;await call('tab.grant',{tabId:task.tabId,enabled:true},task);return await observation(task);}catch(e){task.status='failed';task.reason='Start URL acquisition failed: '+e.message;task.elapsedMs=performance.now()-task.began;save();return {status:task.status,error:task.reason};}
 }
 if(!task||!task.tabId)throw Error('Start task first');
 if(body.op==='observe')return observation(task);
 if(body.op==='decide'){
  const response=await call('decide',{tabId:task.tabId,question:'grounded_action',context:body.context},task);
  task.trace.push({kind:'laya_decision',response});save();return response;
 }
 if(body.op==='action'){
  if(task.status!=='running'||task.steps>=definition.maxActions)throw Error('Task terminal or action budget exhausted');
  if(!body.revision||body.revision!==task.lastObservation?.revision)throw Error('Action must bind the latest supplied observation revision');
  const action={tabId:task.tabId,revision:body.revision,element:String(body.element),action:body.action,...(body.value===undefined?{}:{value:body.value}),...(body.expect?{expect:body.expect}:{})};
  task.steps++;const t=performance.now();let result;
  try{result=await call('action',action,task);task.trace.push({kind:'action',action,response:result,ms:performance.now()-t});}catch(e){task.trace.push({kind:'action',action,error:e.message,response:e.value,ms:performance.now()-t});save();return {error:e.message,observation:await observation(task)};}
  save();return {verification:result.verification,observation:await observation(task)};
 }
 if(body.op==='finish'){
  if(!['failed','skipped','answered'].includes(body.status))throw Error('Finish is failed, skipped or answered pending separate grading');
  if(body.status==='skipped'&&!/login|log.?in|sign.?in|captcha|bot|access wall|account|automation.*block/i.test(body.reason||''))throw Error('Skip needs observed access-wall reason; engine/network errors are failures');
  if(body.status==='answered'&&(!body.answer||!body.evidence?.length||task.steps<2))throw Error('Answer requires evidence pointers and a genuine multi-action journey');
  task.status=body.status;task.answer=body.answer||null;task.reason=body.reason||null;task.answerEvidence=body.evidence||[];task.elapsedMs=performance.now()-task.began;task.finishedAt=new Date().toISOString();delete task.lastObservation;save();try{await call('tab.close',{tabId:task.tabId},task);}catch(e){task.closeError=e.message;}save();return {id:task.id,status:task.status,steps:task.steps,ms:task.elapsedMs};
 }
 throw Error('Unsupported coordinator operation');
}
async function free(port){await new Promise((resolve,reject)=>{const s=net.connect(port,'127.0.0.1');s.on('connect',()=>{s.destroy();reject(Error('Assigned port occupied '+port));});s.on('error',resolve);});}
async function start(){
 for(const port of ports)await free(port);
 const log=fs.openSync(path.join(root,'backend.log'),'a');backend=spawn('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe',['scripts/run_web_backend.py','--host','127.0.0.1','--port',String(backendPort),'--root',root,'--skip-runtime-auto-update','--skip-proof-self-check'],{cwd:repo,env,windowsHide:true,stdio:['ignore',log,log]});fs.closeSync(log);
 const deadline=Date.now()+60000;let ready=false;while(Date.now()<deadline){if(backend.exitCode!==null)throw Error('Owned backend exited; '+root);try{ready=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(700)})).ok;if(ready)break;}catch{}await new Promise(r=>setTimeout(r,100));}if(!ready)throw Error('Owned backend health timed out');
 const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!login.ok)throw Error('Owner local session bootstrap failed');cookie=login.headers.get('set-cookie').split(';')[0];
 await call('headless.start',{port:enginePort,allowLocalFixtures:true});
 server=http.createServer(async(req,res)=>{try{if(req.method!=='POST'||req.url!=='/command')throw Error('POST /command only');let bytes='';for await(const chunk of req){bytes+=chunk;if(bytes.length>50000)throw Error('Request too large');}const value=await command(JSON.parse(bytes));res.setHeader('Content-Type','application/json');res.end(JSON.stringify(value));}catch(e){res.statusCode=400;res.end(JSON.stringify({error:e.message}));}});await new Promise(r=>server.listen(controlPort,'127.0.0.1',r));
 console.log(JSON.stringify({ready:true,control:`http://127.0.0.1:${controlPort}/command`,output,root}));
}
let stopping=false;async function stop(){if(stopping)return;stopping=true;for(const task of report.tasks)if(task.status==='running'){task.status='failed';task.reason='Run interrupted before completion';task.elapsedMs=performance.now()-task.began;}try{if(cookie)await call('headless.stop');}catch(e){report.cleanupError=e.message;}if(backend&&backend.exitCode===null){const done=new Promise(r=>backend.once('exit',r));backend.kill();await done;}if(server)server.close();report.finishedAt=new Date().toISOString();report.cleanup={backendExited:backend?.exitCode!==null||backend?.signalCode!=null,headlessStopRequested:true};save();process.exit();}
process.on('SIGINT',stop);process.on('SIGTERM',stop);start().catch(e=>{report.fatal=e.stack;save();console.error(e.stack);stop();});
