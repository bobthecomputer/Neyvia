// Explicit proof fixture port selection (int3_ports.py).
import { execFileSync as proofExecFileSync } from 'node:child_process';
import { fileURLToPath as proofFileURLToPath } from 'node:url';
const proofPortSelection = process.env.NEYVIA_PROOF_PORT_MAP === undefined ? null : JSON.parse(proofExecFileSync(
  process.env.NEYVIA_SYSTEM_PYTHON || process.env.PYTHON || 'python',
  [proofFileURLToPath(new URL('../src/grant_agent/proof_ports.py', import.meta.url))],
  { encoding: 'utf8', env: process.env }).trim());
function proofPort(original) { return proofPortSelection === null ? original : proofPortSelection[String(original)]; }
function proofText(text) { return text.replace(/(?<!\d)(48461|48462|48463|48465|48466|48467|48468|48469|48472|48473|48474|48475|48476|48477|48478|48479|48481|48487|48488|48489|48491|48492|48494|48495|48496|48497|48498|48499|48501|48502|48503|48508|48509)(?!\d)/g, value => String(proofPort(Number(value)))); }
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import net from 'node:net';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ownedBuild = path.join(repo,'.agent_control/proofs-b/build');
// An explicitly owned build, else the production build this worktree serves (web/dist).
const buildPath = process.env.NEYVIA_PROOF_BUILD_ROOT ? path.resolve(process.env.NEYVIA_PROOF_BUILD_ROOT) : fs.existsSync(path.join(ownedBuild,'index.html')) ? ownedBuild : path.join(repo,'web/dist');
const buildRoots = [repo, path.resolve('D:/NeyviaRuns')];
const resolvedBuild = fs.existsSync(buildPath) ? fs.realpathSync(buildPath) : buildPath;
if (!buildRoots.some(base => { const rel=path.relative(base,resolvedBuild);return !rel.startsWith('..')&&!path.isAbsolute(rel); })) throw new Error('Browser proof build must stay in the worktree or owned D-drive evidence root');
const rootIndex = process.argv.indexOf('--root');
const root = rootIndex >= 0 ? path.resolve(process.argv[rootIndex+1]) : path.join(repo,'.agent_control/proofs-b/browser');
const stateRoot = process.env.NEYVIA_PROOF_STATE_ROOT ? path.resolve(process.env.NEYVIA_PROOF_STATE_ROOT) : repo;
if (path.relative(stateRoot,root).startsWith('..') || path.isAbsolute(path.relative(stateRoot,root))) throw new Error('Browser proof root must stay in its explicitly owned state root');
const output = path.join(root, `journey-${crypto.randomUUID()}`);
const started = performance.now();
const state = path.join(output, 'state');
const home = path.join(output, 'home');
for (const p of [output, state, home]) fs.mkdirSync(p, { recursive: true });
const python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const password = crypto.randomBytes(24).toString('hex');
const env = { ...process.env };
for (const key of Object.keys(env)) if (/API.?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH.*FILE|BASE.?URL|BROKER|NEYVIA_UI_|FLUXIO_WORKSPACE|WORKSPACE_ROOTS|FOLDER_ROOTS/i.test(key)) delete env[key];
Object.assign(env, { HOME:home, USERPROFILE:home, CODEX_HOME:path.join(home,'codex'), HERMES_HOME:path.join(home,'hermes'), OPENCLAW_STATE_DIR:path.join(home,'openclaw'), APPDATA:path.join(home,'appdata'), LOCALAPPDATA:path.join(home,'localappdata'), NEYVIA_MANAGED_RUNTIME_ROOT:path.join(home,'runtimes'), PYTHONPATH:[path.join(repo,'src'),process.env.PYTHONPATH].filter(Boolean).join(path.delimiter), PYTHONDONTWRITEBYTECODE:'1', NEYVIA_COORDINATOR_AUTOSTART:'0', FLUXIO_WATCHDOG_AUTOSTART:'0', NEYVIA_TOOL_AUTO_UPDATE:'0', FLUXIO_RUNTIME_AUTO_UPDATE:'0', SYNTELOS_ACCOUNT_USER:'proofs-b', SYNTELOS_ACCOUNT_PASSWORD:password, NEYVIA_WEB_PORT:proofText('48472'), FLUXIO_WEB_PORT:proofText('48472'), NEYVIA_UI_BACKEND_URL:proofText('http://127.0.0.1:48472'), PATH:`${path.dirname(python)};C:/Windows/System32;C:/Windows` });
env.FLUXIO_LOCAL_SESSION_BOOTSTRAP='1';
const seed = `from pathlib import Path
import sys,json
from grant_agent.harness_jobs import HarnessJobStore
from grant_agent.ui_command_bus import bus_for
root=Path(sys.argv[1]); bus_for(root).put('settings', {'localOnly':True})
store=HarnessJobStore(root)
blocked=store.create({'harnessId':'neyvia-agent','runtime':'neyvia-agent','mode':'direct','message':'Review this local blocked receipt without calling a provider','workspacePath':str(root)},job_id='harness-job-browser-blocked')
store.finish(blocked['id'],result={'status':'blocked','reason':'Local fixture has no selected execution route','detail':'This fixture records a recoverable provider-free blocker','evidencePath':'scratch-local-receipt'})
waiting=store.create({'harnessId':'neyvia-agent','runtime':'neyvia-agent','mode':'direct','message':'Saved local request waiting for a capacity slot','workspacePath':str(root)},job_id='harness-job-browser-waiting')
store.update(waiting['id'],waitingReason='execution-capacity',executionQueue={'schema':'neyvia.harness_execution_queue.v1','state':'waiting','maxRunningJobs':1})
print(json.dumps({'seeded':'production-HarnessJobStore','ids':[blocked['id'],waiting['id']],'providerCalls':0,'waitingFixture':'queued-durable-wait-label-without-worker'}))`;
const seedResult=spawnSync(python,['-c',seed,state],{cwd:repo,env,encoding:'utf8',windowsHide:true});
if(seedResult.status) throw new Error('Fixture creation failed: '+seedResult.stderr);
const report={schema:'neyvia.proofs-b-browser-owned.v1',area:'proofs-b-browser',output,seed:JSON.parse(seedResult.stdout.trim()),startupChecks:'fixture skips proof startup to avoid recursive verification; parent startup checks are separate',requests:[],refusedRequests:[],errors:[],checks:[],rejections:[],screenshots:[],contracts:[],frontier:['The general conversation-fabric verifier case and 75 desktop source cases remain unproven.','Scratch saved-state UI proof; actual provider inference, native desktop and capacity scheduling are separate.']};
const sourcePaths=['web/src/neyvia/HarnessesSurface.jsx','web/src/neyvia/proofsBViewContracts.js','scripts/proofs-b-browser.mjs'];
const digest=p=>crypto.createHash('sha256').update(fs.readFileSync(path.join(repo,p),'utf8').replace(/\r\n/g,'\n')).digest('hex');
const sources=()=>Object.fromEntries(sourcePaths.map(p=>[p,digest(p)]));
report.browserSourceBindings=sources();
let backend,context,page,backendExit,browser,obscura,engine;
let backendExited=false;
let backendDiagnostics='';
let backendTraceFile;
const safe = text => String(text).split(password).join('[ephemeral-redacted]');
const diagnosticText = text => safe(text).replace(/https?:\/\/[^\s"'<>]+/g, value => {
 try { const url=new URL(value);return url.origin+url.pathname; } catch { return '[url]'; }
}).replace(/\bBearer\s+[^\s,;]+/gi,'Bearer [redacted]').replace(/\b(api[-_ ]?key|password|secret|credential|token|cookie|authorization)\s*[:=]\s*[^\s,;]+/gi,'$1=[redacted]').slice(0,700);
const requestDiagnostics=new Map();
report.consoleDiagnostics=[];
const pause = ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function screenshot(page,name){const p=path.join(output,`${name}.png`);await page.screenshot({path:p,fullPage:true,timeout:5000});report.screenshots.push(p);}
function saved(id){const code="from pathlib import Path; import sys,json,hashlib; from grant_agent.harness_jobs import HarnessJobStore; s=HarnessJobStore(Path(sys.argv[1])); p=s.job_path(sys.argv[2]); print(json.dumps({'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'job':json.loads(p.read_text())}))";const p=spawnSync(python,['-c',code,state,id],{cwd:repo,env,encoding:'utf8',windowsHide:true});if(p.status)throw new Error('Could not observe owned durable job');return JSON.parse(p.stdout);}
function obscuraEngine(){
 // NEYVIA_OBSCURA_EXE names an explicitly prepared engine; otherwise the locally admitted one.
 const explicit=process.env.NEYVIA_OBSCURA_EXE;
 let resolved=explicit,source='NEYVIA_OBSCURA_EXE';
 if(!resolved){source='admitted (browser_obscura.managed_executable)';const r=spawnSync(python,['-c','from grant_agent.browser_obscura import managed_executable; print(managed_executable())'],{cwd:repo,env,encoding:'utf8',windowsHide:true});resolved=r.status===0?r.stdout.trim():'';if(!resolved)return {path:'',reason:'No admitted headless Obscura engine on this host ('+String(r.stderr||'').trim().split(String.fromCharCode(10)).pop()+'); set NEYVIA_OBSCURA_EXE to a prepared engine'};}
 if(!fs.existsSync(resolved))return {path:'',reason:'Configured Obscura engine is missing: '+resolved};
 return {path:resolved,source,sha256:crypto.createHash('sha256').update(fs.readFileSync(resolved)).digest('hex')};
}
function mark(stage){(report.stages||=[]).push({stage,atMs:Math.round(performance.now()-started)});}
function acceptance(claim,condition,evidence={}){report.checks.push({claim,ok:!!condition,...evidence});if(!condition)throw new Error(claim+' failed');}
async function main(){
 const occupied=await new Promise(resolve=>{const socket=net.connect({host:'127.0.0.1',port:proofPort(48472)});socket.once('connect',()=>{socket.destroy();resolve(true)});socket.once('error',()=>resolve(false));socket.setTimeout(1000,()=>{socket.destroy();resolve(false)});});
 if(occupied)throw new Error(proofText('Assigned browser fixture port 48472 is occupied; no existing backend was used'));
 const {checkHarnessView}=await import(pathToFileURL(path.join(repo,'web/src/neyvia/proofsBViewContracts.js')));
 const calibration={job:{status:'blocked',result:{status:'blocked'}},label:'needs attention',output:JSON.stringify({status:'blocked'},null,2),terminal:true,attention:true,cleanup:true,retry:true,rows:[]};
 try{checkHarnessView(calibration);throw new Error('Wrong terminal view was accepted');}catch(error){if(!String(error.message).includes('Contract proofs-b.browser.blocked-receipt'))throw error;report.rejections.push({contract:'proofs-b.browser.blocked-receipt',rejected:true});}
 const waitView={job:{status:'queued',waitingReason:'execution-capacity'},label:'running',output:'Active execution',terminal:false,attention:false,cleanup:true,retry:false,rows:[]};
 for(const [contract,view] of [['proofs-b.browser.capacity-label',waitView],['proofs-b.browser.capacity-explanation',{...waitView,label:'waiting for capacity'}]]){try{checkHarnessView(view);throw new Error('Incorrect capacity view was accepted');}catch(error){if(!String(error.message).includes(`Contract ${contract}`))throw error;report.rejections.push({contract,rejected:true});}}
 engine=obscuraEngine();
 if(!engine.path){
  // The admitted headless engine is a separately prepared dependency; startup never downloads
  // one and never substitutes Chrome/Edge. Without it the journey is not run and its
  // contracts are reported as skipped with the reason, never as passed.
  report.skipped=['proofs-b.browser.blocked-receipt','proofs-b.browser.capacity-label','proofs-b.browser.capacity-explanation'].map(contract=>({contract,status:'skipped',reason:engine.reason}));
  report.frontier.push('Rendered Harnesses journey not exercised: '+engine.reason);
  report.contracts=[];report.ok=true;return;
 }
 if(!fs.existsSync(path.join(buildPath,'index.html')))throw new Error('No production build at '+path.relative(repo,buildPath)+'; build the frontend first');
 const backendArgs=[path.join(repo,'scripts/run_web_backend.py'),'--host','127.0.0.1','--port',proofText('48472'),'--root',state,'--static-root',buildPath,'--skip-runtime-auto-update','--skip-proof-self-check'];
 if(process.env.NEYVIA_PROOF_BACKEND_TRACE==='1'){
  const tracePath=path.join(output,'backend-trace.py');
  backendTraceFile=path.join(output,'backend-stacks.log');
  fs.writeFileSync(tracePath,"import runpy,sys,threading,time,traceback\nfrom pathlib import Path\ntrace_stream=Path(__file__).with_name('backend-stacks.log').open('w',encoding='utf-8')\nstop_trace=threading.Event()\ntrace_started=time.monotonic()\ndef sample_stacks():\n for sample in range(45):\n  if stop_trace.wait(2): return\n  trace_stream.write('\\nSample '+str(sample)+' at '+str(round(time.monotonic()-trace_started,3))+' seconds\\n')\n  for identity,frame in sys._current_frames().items():\n   trace_stream.write('Thread '+str(identity)+'\\n'+''.join(traceback.format_stack(frame)))\n  trace_stream.flush()\ntrace_thread=threading.Thread(target=sample_stacks,name='owned-browser-diagnostic',daemon=True)\ntrace_thread.start()\nsys.argv=sys.argv[1:]\ntry:\n runpy.run_path(sys.argv[0],run_name='__main__')\nfinally:\n stop_trace.set()\n trace_thread.join(2)\n trace_stream.close()\n");
  backendArgs.unshift(tracePath);
 }
 backend=spawn(python,backendArgs,{cwd:repo,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
 backendExit=new Promise(resolve=>backend.once('exit',(code,signal)=>{backendExited=true;report.backendExit={code,signal,atMs:Math.round(performance.now()-started)};resolve(true)}));
 let logs='';const log=b=>{logs+=safe(b);backendDiagnostics=logs.slice(-12000);report.backendDiagnostics=backendDiagnostics;};backend.stdout.on('data',log);backend.stderr.on('data',log);
 for(let n=0;n<360;n++){if(backend.exitCode!==null)throw new Error('Owned backend exited: '+logs.slice(-3000));if(logs.includes(proofText('web backend listening on http://127.0.0.1:48472'))){try{const r=await fetch(proofText('http://127.0.0.1:48472/api/health'),{signal:AbortSignal.timeout(2000)});if(r.ok)break;}catch{}}await pause(250);if(n===359)throw new Error('Owned backend health timed out after 90 s');}
 // Headless Obscura only (never Chrome/Edge): a pinned engine this run starts on
 // its own assigned port, with a fresh engine directory inside the owned output.
 mark('backend healthy');
 const engineDirectory=path.join(output,'obscura');
 fs.mkdirSync(engineDirectory,{recursive:true});
 const freshEngine=fs.readdirSync(engineDirectory).length===0;
 const enginePort=proofPort(48478);
 const token=crypto.randomBytes(27).toString('base64url');
 const engineLogPath=path.join(engineDirectory,'engine.log');const engineLog=fs.openSync(engineLogPath,'a');
 const engineEnv={...process.env};
 for(const key of Object.keys(engineEnv))if(/API.?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH.*FILE|BASE.?URL|BROKER/i.test(key))delete engineEnv[key];
 Object.assign(engineEnv,{OBSCURA_CDP_TOKEN:token,OBSCURA_ROTATE_PROFILE:'0',OBSCURA_NAV_TIMEOUT_MS:'20000',OBSCURA_SCRIPT_DEADLINE_MS:'15000'});
 obscura=spawn(engine.path,['serve','--host','127.0.0.1','--port',String(enginePort),'--user-agent','NeyviaAgent/1.0 (proofs-b browser; Obscura)','--max-connections','8','--allow-private-network'],{cwd:engineDirectory,env:engineEnv,windowsHide:true,stdio:['ignore',engineLog,engineLog]});
 const endpoint=`http://127.0.0.1:${enginePort}`;
 for(let n=0;;n++){if(obscura.exitCode!==null)throw new Error('Obscura exited before CDP startup: '+safe(fs.readFileSync(engineLogPath,'utf8')).slice(-600));try{const r=await fetch(endpoint+'/json/version',{headers:{Authorization:`Bearer ${token}`},signal:AbortSignal.timeout(500)});if(r.ok)break;}catch{}if(n>=300)throw new Error('Obscura did not become ready: '+safe(fs.readFileSync(engineLogPath,'utf8')).slice(-600));await pause(100);}
 const unauthorized=await fetch(endpoint+'/json/version',{signal:AbortSignal.timeout(2000)}).then(r=>r.status).catch(()=>0);
 report.engineAttestation={engine:'obscura',executable:engine.path,sha256:engine.sha256,source:engine.source,port:enginePort,directory:engineDirectory,freshBeforeLaunch:freshEngine,unauthenticatedStatus:unauthorized};
 acceptance('Owned headless Obscura engine starts fresh on its assigned port and refuses unauthenticated CDP',freshEngine&&unauthorized!==200);
 mark('engine ready');
 browser=await chromium.connectOverCDP(endpoint,{headers:{Authorization:`Bearer ${token}`},timeout:15000});
 context=browser.contexts()[0]||await browser.newContext();
 context.setDefaultTimeout(5000);context.setDefaultNavigationTimeout(15000);
 await context.route('**/*',async route=>{const u=new URL(route.request().url());if(['data:','blob:','about:'].includes(u.protocol))return route.continue();const port=Number(u.port);if(u.origin===proofText('http://127.0.0.1:48472'))return route.continue();report.refusedRequests.push({url:u.origin+u.pathname,method:route.request().method(),reason:port===47881?'forbidden-live-port':'outside-owned-fixture-origin'});return route.abort('blockedbyclient');});
 page=await context.newPage();
 await page.setViewportSize?.({width:1440,height:1050}).catch(()=>{});
 // Record backend command names in the page itself: some engines do not expose request
 // bodies over CDP, and the no-provider-launch check must see every command.
 await page.addInitScript(()=>{
  const commands=[];Object.defineProperty(window,'__proofBackendCommands',{value:commands});
  const original=window.fetch.bind(window);
  window.fetch=(input,init)=>{try{const url=new URL(typeof input==='string'?input:input.url,location.href);if(['/api/backend','/api/command','/api/commands'].includes(url.pathname)){let command=null;try{const body=JSON.parse(typeof init?.body==='string'?init.body:'{}');command=body.command||body.name||body.op||null;}catch{}commands.push(command);}}catch{}return original(input,init);};
 });
 await page.addInitScript(()=>{
  const events=[];Object.defineProperty(window,'__C7bStylesheetEvents',{value:events});
  const seen=new WeakSet();const observe=link=>{if(link.rel!=='stylesheet'||seen.has(link))return;seen.add(link);const url=()=>{try{const u=new URL(link.href);return u.origin+u.pathname;}catch{return '';}};const note=kind=>{if(events.length<80)events.push({kind,url:url(),atMs:Math.round(performance.now())});};note('inserted');link.addEventListener('load',()=>note('load'),{once:true});link.addEventListener('error',()=>note('error'),{once:true});};
  new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes){if(node.nodeName==='LINK')observe(node);if(node.querySelectorAll)for(const link of node.querySelectorAll('link[rel="stylesheet"]'))observe(link);}}).observe(document,{childList:true,subtree:true});
 });
 page.on('console',message=>{if(['warning','error'].includes(message.type())&&report.consoleDiagnostics.length<40)report.consoleDiagnostics.push({type:message.type(),text:diagnosticText(message.text())});});
 page.on('pageerror',e=>report.errors.push(safe(e.message)));
 page.on('request',r=>{const u=new URL(r.url());if(u.protocol==='http:'||u.protocol==='https:'){if(requestDiagnostics.size<500)requestDiagnostics.set(r,{url:u.origin+u.pathname,method:r.method(),resourceType:r.resourceType(),startedMs:Math.round(performance.now()-started),status:null,finished:false});const row={url:u.origin+u.pathname,method:r.method()};if(['/api/backend','/api/command','/api/commands'].includes(u.pathname)){try{const body=JSON.parse(r.postData()||'{}');row.command=body.command||body.name||body.op;}catch{}}report.requests.push(row);}});
 page.on('response',response=>{const row=requestDiagnostics.get(response.request());if(row){row.status=response.status();row.responseMs=Math.round(performance.now()-started);}});
 page.on('requestfinished',request=>{const row=requestDiagnostics.get(request);if(row){row.finished=true;row.finishedMs=Math.round(performance.now()-started);}});
 page.on('requestfailed',request=>{const row=requestDiagnostics.get(request);if(row){row.finished=true;row.failure=diagnosticText(request.failure()?.errorText||'request failed');row.finishedMs=Math.round(performance.now()-started);}});
 const loadedBundles=[];
 page.on('response',response=>{if(response.url().endsWith('.js'))loadedBundles.push(response.body().then(bytes=>{const u=new URL(response.url());const relative=u.pathname.replace(/^\/control\//,'');const file=path.join(buildPath,relative);return {url:u.origin+u.pathname,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),matchesOwnedBuild:fs.existsSync(file)&&fs.readFileSync(file).equals(bytes),guardIncluded:bytes.includes(Buffer.from('proofs-b.browser.blocked-receipt'))};}));});
 await page.goto(proofText('http://127.0.0.1:48472/control/'),{waitUntil:'domcontentloaded',timeout:15000});
 // A fresh workspace first shows setup; a person can skip it.
 const skip=page.getByRole('button',{name:'Skip setup',exact:true});
 if(await skip.waitFor({timeout:20000}).then(()=>true,()=>false)){await skip.click();report.checks.push({claim:'fresh workspace setup skipped the way a person does',ok:true});}
 // The way a person opens it: Apps, type "harnesses", Enter.
 await page.locator('button[aria-label="Apps"]').first().click({timeout:30000});
 await page.locator('.nx-launcher input').fill('harnesses');
 await page.locator('.nx-launcher input').press('Enter');
 await page.locator('[data-harnesses-surface=true]').waitFor({timeout:30000});
 mark('harnesses visible');
 await screenshot(page,'harnesses');
 report.rendered={url:page.url(),title:await page.title(),text:(await page.locator('[data-harnesses-surface=true]').innerText()).slice(0,14000),buttons:await page.locator('[data-harnesses-surface=true] button').allTextContents()};
 report.checks.push({claim:'headless Obscura with local-session authentication opens the Harnesses tool screen from the Apps launcher on the owned backend',ok:true});
 const waiting=page.locator('.neyvia-harnesses__jobs button[data-status=queued]');await waiting.click();
 report.waiting={receipt:await page.locator('[data-harness-receipt=true]').innerText(),row:await waiting.innerText(),label:await waiting.getAttribute('aria-label')};
 // Casing comes from CSS text-transform, which engines apply differently to innerText.
 acceptance('Capacity wait is labeled from durable waitingReason in receipt, visible queue and accessible queue label',report.waiting.receipt.toLowerCase().includes('waiting for capacity')&&report.waiting.row.toLowerCase().includes('waiting for capacity')&&report.waiting.label.includes('waiting for capacity'));
 acceptance('Waiting output explains capacity and says no execution slot is claimed',report.waiting.receipt.includes('Provider/model execution is waiting for a workspace capacity slot')&&report.waiting.receipt.includes('no execution slot is claimed yet'));
 await screenshot(page,'waiting-capacity');
 const blocked=page.locator('.neyvia-harnesses__jobs button[data-status=blocked]');report.blockedMatches=await blocked.count();await blocked.click();
 await page.locator('[data-harness-blocker=true]').waitFor();
 report.blockedReceipt=await page.locator('[data-harness-receipt=true]').innerText();report.blockedAttributes=await page.locator('[data-harness-receipt=true]').evaluate(e=>({terminal:e.dataset.harnessTerminal,attention:e.dataset.harnessAttention}));
 acceptance('Blocked receipt is visible and actionable without becoming terminal',report.blockedAttributes.terminal==='false'&&report.blockedAttributes.attention==='true'&&await page.locator('[data-harness-terminal=true]').count()===0&&await page.getByRole('button',{name:'Prepare retry',exact:true}).isVisible()&&await page.getByRole('button',{name:'Cancel & clean up',exact:true}).isVisible());
 acceptance('Blocked output shows the actual saved structured result',report.blockedReceipt.includes('Local fixture has no selected execution route')&&report.blockedReceipt.includes('scratch-local-receipt'));
 const before=saved('harness-job-browser-blocked');
 await screenshot(page,'blocked-selected');
 await page.getByRole('button',{name:'Prepare retry',exact:true}).click();
 acceptance('Prepare retry restores objective and preserves original receipt bytes',await page.getByRole('textbox',{name:'Harness objective'}).inputValue()===before.job.prompt&&saved('harness-job-browser-blocked').sha256===before.sha256,{originalSha256:before.sha256});
 acceptance('Retry notice states original receipt stays preserved until explicit cleanup',(await page.locator('.neyvia-harnesses__notice').innerText()).includes('original receipt stays preserved until you clean it up'));
 await screenshot(page,'retry-prepared');
 await page.getByRole('button',{name:'Cancel & clean up',exact:true}).click();
 await page.locator('.neyvia-harnesses__notice').filter({hasText:'explicitly cleaned up as cancelled'}).waitFor();
 const cleaned=saved('harness-job-browser-blocked');
 acceptance('Explicit cleanup durably cancels blocked job while preserving original result',cleaned.job.status==='cancelled'&&cleaned.job.cancelOutcome==='blocked-cleanup'&&JSON.stringify(cleaned.job.result)===JSON.stringify(before.job.result));
 await page.locator('[data-harness-receipt=true][data-harness-terminal=true]').waitFor();
 acceptance('Cleaned up receipt becomes terminal and retains structured blocker evidence',(await page.locator('[data-harness-receipt=true]').innerText()).includes('scratch-local-receipt'));
 await screenshot(page,'blocked-cleaned');
 mark('journey done');
 report.durableAfter={blocked:cleaned.job,waiting:saved('harness-job-browser-waiting').job};
 report.pageBackendCommands=await page.evaluate(()=>[...window.__proofBackendCommands]);
 const networkBackend=report.requests.filter(r=>['/api/backend','/api/command','/api/commands'].some(suffix=>r.url.endsWith(suffix))).length;
 acceptance('No provider/model launch command was issued',report.pageBackendCommands.length>=networkBackend&&report.pageBackendCommands.every(command=>typeof command==='string')&&!report.pageBackendCommands.some(command=>/start_harness_job|run_harness|send_agent_chat|connected_session_send|call_native_tool/.test(command))&&report.durableAfter.waiting.status==='queued',{networkBackendRequests:networkBackend,pageBackendCommands:report.pageBackendCommands.length});
 report.loadedBundles=await Promise.all(loadedBundles);
 mark('bundles observed');
 if(!report.loadedBundles.length){
  // Engines that do not report script responses over CDP: take the scripts the page itself
  // loaded (resource timing, script tags, module preloads) and fetch those exact URLs from
  // the owned backend, comparing their bytes with the owned build.
  const scriptUrls=await Promise.race([pause(15000).then(()=>{throw new Error('Page did not report its loaded scripts within 15 s');}),page.evaluate(()=>[...new Set([...performance.getEntriesByType('resource').map(row=>row.name),...[...document.scripts].map(s=>s.src),...[...document.querySelectorAll('link[rel=modulepreload]')].map(l=>l.href)].filter(u=>/\.js(\?|$)/.test(u)))])]);
  report.pageScriptUrls=scriptUrls.map(u=>{try{const x=new URL(u);return x.origin+x.pathname;}catch{return '';}});
  for(const url of scriptUrls){const u=new URL(url);if(u.origin!==proofText('http://127.0.0.1:48472'))continue;const bytes=Buffer.from(await (await fetch(url,{signal:AbortSignal.timeout(10000)})).arrayBuffer());const file=path.join(buildPath,u.pathname.replace(/^\/control\//,''));report.loadedBundles.push({url:u.origin+u.pathname,via:'page-reported',sha256:crypto.createHash('sha256').update(bytes).digest('hex'),matchesOwnedBuild:fs.existsSync(file)&&fs.readFileSync(file).equals(bytes),guardIncluded:bytes.includes(Buffer.from('proofs-b.browser.blocked-receipt'))});}
 }
 acceptance('Actual served bundle matches the owned build and includes the production semantic guard',report.loadedBundles.some(b=>b.guardIncluded&&b.matchesOwnedBuild));
 acceptance('Page stayed on the exact owned fixture origin without JavaScript errors',report.refusedRequests.length===0&&report.errors.length===0);
 report.sourceStable=JSON.stringify(report.browserSourceBindings)===JSON.stringify(sources());
 acceptance('Browser proof sources did not change during actual journey',report.sourceStable);
 report.contracts=['proofs-b.browser.blocked-receipt','proofs-b.browser.capacity-label','proofs-b.browser.capacity-explanation'];
 report.ok=true;
}
main().catch(async e=>{report.ok=false;report.failure=safe(e.message);report.networkDiagnostics=[...requestDiagnostics.values()].slice(-100);report.pendingRequests=report.networkDiagnostics.filter(row=>!row.finished);if(page&&!page.isClosed()){try{report.stylesheetDiagnostics=await page.evaluate(()=>{const url=value=>{try{const u=new URL(value);return u.origin+u.pathname;}catch{return '';}};return {events:window.__C7bStylesheetEvents||[],links:[...document.querySelectorAll('link[rel="stylesheet"]')].slice(0,50).map(link=>{let ruleCount=null;try{ruleCount=link.sheet?.cssRules?.length??null;}catch{}return {url:url(link.href),sheetPresent:!!link.sheet,ruleCount,disabled:link.disabled,media:link.media};}),resources:performance.getEntriesByType('resource').filter(row=>['link','script','css'].includes(row.initiatorType)).slice(-100).map(row=>({url:url(row.name),initiatorType:row.initiatorType,startTimeMs:Math.round(row.startTime),durationMs:Math.round(row.duration),responseEndMs:Math.round(row.responseEnd),transferSize:row.transferSize}))};});report.failurePageText=safe(await page.locator('body').innerText({timeout:1000}));await screenshot(page,'failure-state');}catch(error){report.diagnosticFailure=diagnosticText(error.message);}}}).finally(async()=>{if(browser)await browser.close().catch(()=>{});if(obscura&&obscura.exitCode===null&&obscura.signalCode===null){const exited=new Promise(resolve=>obscura.once('exit',resolve));spawnSync('C:/Windows/System32/taskkill.exe',['/PID',String(obscura.pid),'/T','/F'],{windowsHide:true,stdio:'ignore',timeout:5000});await Promise.race([exited,pause(3000)]);}report.ownedEngineStopped=obscura?obscura.exitCode!==null||obscura.signalCode!==null:true;if(backend&&!backendExited){backend.kill();await Promise.race([backendExit,pause(2000)]);if(!backendExited){spawnSync('C:/Windows/System32/taskkill.exe',['/PID',String(backend.pid),'/T','/F'],{windowsHide:true,stdio:'ignore',timeout:5000});await Promise.race([backendExit,pause(2000)]);}}if(backendTraceFile&&fs.existsSync(backendTraceFile)){report.backendTrace={path:backendTraceFile,bytes:fs.statSync(backendTraceFile).size,text:safe(fs.readFileSync(backendTraceFile,'utf8')).slice(-60000)};}report.ownedBackendStopped=backend?backendExited:true;report.ok=report.ok&&report.ownedBackendStopped&&report.ownedEngineStopped;report.elapsedMs=Math.round(performance.now()-started);fs.writeFileSync(path.join(output,'receipt.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));if(!report.ok)process.exitCode=1;});
