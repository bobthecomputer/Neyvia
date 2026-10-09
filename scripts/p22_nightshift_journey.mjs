import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { dirname, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash, randomBytes } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { build } from 'esbuild';
import { chromium } from 'playwright';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const option = key => args.includes(key) ? args[args.indexOf(key) + 1] : undefined;
const root = resolve(option('--root') || '.agent_control/p22/nightshift-journey');
const under = (child, parent) => { const rel = relative(resolve(parent), resolve(child)); return !rel || (rel !== '..' && !rel.startsWith('..' + sep)); };
if (!under(root, resolve(repo, '.agent_control/p22')) && !under(root, resolve('D:/NeyviaRuns/P22'))) throw new Error('Receipt root must be under .agent_control/p22 or D:/NeyviaRuns/P22');
const outFile = resolve(root, 'nightshift-journey.json');
const selected = process.env.NEYVIA_GATE_CONTRACTS ? new Set(JSON.parse(process.env.NEYVIA_GATE_CONTRACTS)) : null;
const id = 'p22.nightshift.local-policy-ui-journey';
if (selected && (!selected.size || [...selected].some(value => value !== id))) throw new Error('NEYVIA_GATE_CONTRACTS must select the Night Shift UI journey');
const admittedPorts = JSON.parse(process.env.NEYVIA_PROOF_ALLOWED_PORTS || '[]');
const portMap = JSON.parse(process.env.NEYVIA_PROOF_PORT_MAP || 'null');
function proofPort(original) {
 const port = portMap?.[String(original)];
 if (!Number.isInteger(port) || !admittedPorts.includes(port)) throw new Error('Night Shift ports must resolve through the caller assigned proof port map');
 return port;
}
const backendPort = proofPort(48461), enginePort = proofPort(48462), base = `http://127.0.0.1:${backendPort}`;
if (backendPort === enginePort) throw new Error('Backend and Obscura require distinct assigned ports');
const admissionPath = 'D:/NeyviaRuns/engines/obscura-c2h/4028d3ec7e4a-d25dbe93fae7/ADMISSION.json';
const admission = JSON.parse(await readFile(admissionPath, 'utf8'));
if (admission.stealth !== false || admission.systemInstall !== false) throw new Error('Obscura admission must remain non-stealth and user-local');
const admittedHashes = {};
for (const key of ['engineBinary', 'workerBinary']) { const row=admission[key], bytes=await readFile(row.path), info=await stat(row.path), digest=createHash('sha256').update(bytes).digest('hex'); if(info.size!==row.bytes||digest!==row.sha256) throw new Error(`Obscura ${key} differs from admission`); admittedHashes[key]=digest; }
await mkdir(root, {recursive:true});
const profile = resolve(root, 'obscura-profile'); await mkdir(profile,{recursive:true});
const entry = `
 import React from 'react'; import {createRoot} from 'react-dom/client';
 import '${resolve(repo,'web/src/neyvia/next/nxTokens.css').replaceAll('\\','/')}';
 import '${resolve(repo,'web/src/neyvia/next/nxThemes.css').replaceAll('\\','/')}';
 import {NxNightShift} from '${resolve(repo,'web/src/neyvia/next/NxNightShift.jsx').replaceAll('\\','/')}';
 window.p22MountNightShift = folders => { const root=createRoot(document.querySelector('#owned')); root.render(React.createElement('div',{className:'nx'},React.createElement(NxNightShift,{folders}))); return root; };
`;
const built = await build({stdin:{contents:entry,resolveDir:repo,loader:'js'},outdir:resolve(root,'bundle'),bundle:true,write:false,format:'iife',platform:'browser',target:'chrome120',sourcemap:'inline',sourcesContent:true,jsx:'automatic',define:{'process.env.NODE_ENV':'"production"','import.meta.env':'{"DEV":false,"PROD":true,"MODE":"production"}'},logLevel:'silent'});
const js=built.outputFiles.find(file=>file.path.endsWith('.js'))?.text, css=built.outputFiles.find(file=>file.path.endsWith('.css'))?.text||'';
if(!js) throw new Error('NxNightShift production component bundle missing');
const bundleFile=resolve(root,'bundle/p22-nightshift.js'); await mkdir(dirname(bundleFile),{recursive:true}); await writeFile(bundleFile,js,'utf8');
const report={area:'nightshift-journey',schema:'neyvia.p22.nightshift-ui-journey.v1',engine:'admitted Obscura (headless CDP)',contract:id,checks:[],ok:false,limitations:['Mounted production NxNightShift UI against an owned local backend/state root; no provider task was started.']};
report.engineAdmission={path:admissionPath,version:admission.engineVersion,stealth:admission.stealth,systemInstall:admission.systemInstall,...admittedHashes};
const python='C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const backendEnv={...process.env}; for(const key of Object.keys(backendEnv)) if(/API.?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH.*FILE|BROKER/i.test(key)) delete backendEnv[key];
Object.assign(backendEnv,{PYTHONPATH:resolve(repo,'src'),NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0',FLUXIO_LOCAL_SESSION_BOOTSTRAP:'1',HOME:profile,USERPROFILE:profile,APPDATA:resolve(profile,'roaming'),LOCALAPPDATA:resolve(profile,'local'),TEMP:resolve(profile,'temp'),TMP:resolve(profile,'temp')});
await mkdir(resolve(profile,'temp'),{recursive:true});
const backend=spawn(python,['scripts/run_web_backend.py','--host','127.0.0.1','--port',String(backendPort),'--root',root,'--skip-runtime-auto-update'],{cwd:repo,windowsHide:true,stdio:['ignore','ignore','pipe'],env:backendEnv});
const token=randomBytes(32).toString('base64url');
const engineEnv={...process.env}; for(const key of Object.keys(engineEnv)) if(/API.?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH.*FILE|BASE.?URL|BROKER/i.test(key)) delete engineEnv[key];
Object.assign(engineEnv,{HOME:profile,USERPROFILE:profile,APPDATA:resolve(profile,'roaming'),LOCALAPPDATA:resolve(profile,'local'),OBSCURA_CDP_TOKEN:token,OBSCURA_ROTATE_PROFILE:'0'});
const engine=spawn(admission.engineBinary.path,['serve','--host','127.0.0.1','--port',String(enginePort),'--max-connections','4','--allow-private-network'],{windowsHide:true,stdio:['ignore','ignore','pipe'],env:engineEnv});
let browser, currentPage, backendOut='', engineOut=''; backend.stderr.on('data',chunk=>backendOut+=chunk.toString()); engine.stderr.on('data',chunk=>engineOut+=chunk.toString());
const stop=proc=>{ if(proc.exitCode===null){ try{spawnSync('taskkill',['/PID',String(proc.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});}catch{} } };
try {
 const ready=async(url,headers={})=>{const until=Date.now()+25000;while(Date.now()<until){if(backend.exitCode!==null)throw Error('Owned backend exited before readiness');try{const r=await fetch(url,{headers,signal:AbortSignal.timeout(1200)});if(r.ok)return await r.json();}catch{}await delay(150);}throw Error('Owned service did not become ready');};
 const health=await ready(`${base}/api/health`);
 const cdpReady=await ready(`http://127.0.0.1:${enginePort}/json/version`,{Authorization:`Bearer ${token}`});
 browser=await chromium.connectOverCDP(`http://127.0.0.1:${enginePort}`,{headers:{Authorization:`Bearer ${token}`},timeout:10000});
 const context=await browser.newContext({reducedMotion:'reduce'}); const page=await context.newPage(); currentPage=page;
 report.browserErrors=[]; page.on('pageerror',error=>report.browserErrors.push(String(error)));
 report.browserConsoleErrors=[]; page.on('console',message=>{if(message.type()==='error')report.browserConsoleErrors.push(message.text());});
 page.setDefaultTimeout(8000);
 const cdp=await context.newCDPSession(page), parsed=new Map(); cdp.on('Debugger.scriptParsed',e=>parsed.set(String(e.scriptId),e.url||'')); let coverageStarted=false;
 try{await cdp.send('Debugger.enable');await cdp.send('Profiler.enable');await cdp.send('Profiler.startPreciseCoverage',{callCount:true,detailed:true});coverageStarted=true;}catch(error){report.executionCoverage={available:false,reason:String(error).slice(0,250)};}
 await page.goto(`${base}/api/health`,{waitUntil:'domcontentloaded',timeout:10000});
 await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>${css}</style><style>html,body{margin:0;min-height:100%;}body{padding:18px;background:#101820;color:#f3f6f8}.nx{min-height:90vh}</style></head><body><main id="owned"></main></body></html>`);
 const login=await page.evaluate(async()=>fetch('/api/auth/local-session',{method:'POST',credentials:'include',headers:{'content-type':'application/json'},body:'{}'})); if(!login.ok) throw Error(`Owned local session refused (${login.status})`);
 await page.evaluate(url=>{window.__FLUXIO_BACKEND_URL__=url;},base);
 await page.addScriptTag({content:`${js}\n//# sourceURL=${base}/p22-nightshift.js`});
 const folders=[{path:root,name:'Owned Night Shift receipt root'}]; await page.evaluate(folders=>window.p22MountNightShift(folders),folders);
 await page.getByRole('region',{name:'Night Shift'}).waitFor({state:'visible',timeout:7000});
 await page.getByRole('button',{name:'Budget'}).click(); await page.getByRole('form',{name:'Budget and quiet hours'}).waitFor({state:'visible'});
 const fillLabel=async (name,value)=>page.locator('label').filter({hasText:name}).last().locator('input').fill(String(value));
 await fillLabel('Hours per night','1'); await fillLabel('Tasks at once','2'); await fillLabel('Minutes per task','15'); await fillLabel('Tokens per task','1200');
 const checkText=async (text)=>{const label=page.locator('label.nx-ns-check').filter({hasText:text}).last(); if(!(await label.locator('input').isChecked())) await label.click();};
 await checkText('Hold new tasks when a plan limit reaches'); await fillLabel('Hold at','70'); await checkText('Keep the GPU for dictation'); await checkText('Quiet GPU hours');
 for(const field of [page.locator('.nx-ns-quiet input[type=time]').nth(0),page.locator('.nx-ns-quiet input[type=time]').nth(1)]) await field.evaluate(node=>{const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;set.call(node,'00:00');node.dispatchEvent(new Event('input',{bubbles:true}));node.dispatchEvent(new Event('change',{bubbles:true}));});
 await page.locator('.nx-ns-quiet select').selectOption('UTC');
 const quietFieldsBeforeSave=await page.locator('.nx-ns-quiet').evaluate(node=>[...node.querySelectorAll('input[type=time],select')].map(field=>field.value));
 await page.getByRole('button',{name:'Save budget'}).click(); await page.waitForTimeout(140);
 const policy=await page.evaluate(async()=>{const r=await fetch(`${window.__FLUXIO_BACKEND_URL__}/api/backend`,{method:'POST',credentials:'include',headers:{'content-type':'application/json'},body:JSON.stringify({command:'nightshift_resources_command',payload:{}})});return r.ok?await r.json():{error:`HTTP ${r.status}`};});
 const p=policy.data||policy.result?.data||policy.result||policy.policy||policy;
 const policyOK=p.maxConcurrent===2&&p.maxNightSeconds===3600&&p.maxTaskSeconds===900&&p.maxTaskTokens===1200&&p.holdAtPlanPercent===70&&p.gpuReservedFor==='ASR'&&p.quietGpuHours?.start==='00:00'&&p.quietGpuHours?.end==='00:00'&&p.quietGpuHours?.timeZone==='UTC';
 const visiblePolicy=await page.locator('form[aria-label="Budget and quiet hours"]').evaluate(form=>({checked:[...form.querySelectorAll('input[type=checkbox]')].map(x=>x.checked),hours:form.querySelector('input[type=number]')?.value,visible:getComputedStyle(form).display!=='none'&&form.getBoundingClientRect().height>0}));
 report.checks.push({name:'saved-bounded-policy-and-observed-ui-state',ok:policyOK&&visiblePolicy.visible&&visiblePolicy.checked[1]&&visiblePolicy.checked[2]&&visiblePolicy.checked[3],observed:{policy:p,visiblePolicy,quietFieldsBeforeSave,health:{ok:health.ok,backend:health.backend}}});
 await page.getByRole('button',{name:'Budget',exact:true}).click(); await page.getByRole('button',{name:'Add task'}).first().click();
 const form=page.getByRole('form',{name:'New task'}); await form.waitFor({state:'visible'});
 const setField=label=>page.locator('label.nx-ns-field').filter({hasText:label}).last().locator('input,textarea,select');
 await setField('Short title').fill('P22 local held task'); await setField('Prompt the agent gets, in full').fill('Review a local-only task prompt; do not execute commands or contact providers.');
 await setField('Folder').fill(root); await page.locator('label.nx-ns-field').filter({hasText:'Who does it'}).locator('select').selectOption('codex');
 await page.locator('label.nx-ns-field').filter({hasText:'The agent can'}).locator('select').selectOption('read-only');
 await page.locator('label.nx-ns-field').filter({hasText:'Token limit'}).locator('input').fill('800'); await page.locator('label.nx-ns-field').filter({hasText:'Minutes limit'}).locator('input').fill('10');
 const gpu=page.getByLabel('Needs the GPU'); if(!(await gpu.isChecked())) await gpu.check();
 report.submittedFields=await form.evaluate(node=>[...node.querySelectorAll('input,textarea,select')].map(field=>({name:field.name,type:field.type,value:field.value,checked:field.checked})));
 await form.getByRole('button',{name:'Add task'}).click();
 try{await page.getByText('P22 local held task',{exact:true}).first().waitFor({state:'visible',timeout:7000});}
 catch(error){report.creationState=await page.evaluate(async()=>{const r=await fetch(`${window.__FLUXIO_BACKEND_URL__}/api/backend`,{method:'POST',credentials:'include',headers:{'content-type':'application/json'},body:JSON.stringify({command:'nightshift_tasks_command',payload:{}})});return {status:r.status,body:await r.json(),markup:document.querySelector('[aria-label="Night Shift"]')?.outerHTML};}).catch(failure=>({error:String(failure)}));await page.screenshot({path:resolve(root,'nightshift-failure.png'),fullPage:true}).catch(()=>{});throw error;}
 await page.waitForTimeout(250);
 const taskState=await page.evaluate(async()=>{const r=await fetch(`${window.__FLUXIO_BACKEND_URL__}/api/backend`,{method:'POST',credentials:'include',headers:{'content-type':'application/json'},body:JSON.stringify({command:'nightshift_tasks_command',payload:{}})});return r.ok?await r.json():{error:`HTTP ${r.status}`};});
 const tasks=taskState.tasks||taskState.data?.tasks||taskState.result?.tasks||taskState.result?.data?.tasks||taskState.result||[]; const task=Array.isArray(tasks)?tasks.find(item=>item.title==='P22 local held task'):null;
 const taskVisible=await page.locator('[data-ns-task]').filter({hasText:'P22 local held task'}).first().evaluate(node=>({text:node.innerText,box:(()=>{const b=node.getBoundingClientRect(),s=getComputedStyle(node);return {width:b.width,height:b.height,display:s.display,visibility:s.visibility,opacity:s.opacity};})()}));
 const noStart=Boolean(task)&&task.status==='waiting'&&task.armed===false&&!task.runId&&!task.completionEvidence&&!task.evidence&&taskVisible.box.width>0&&taskVisible.box.height>0&&taskVisible.box.display!=='none'&&taskVisible.box.visibility!=='hidden'&&!/done|completed/i.test(taskVisible.text);
 report.checks.push({name:'unarmed-task-waits-without-run-or-fake-completion',ok:noStart,observed:{task,taskResponse:taskState,taskVisible,explicitStartRequired:taskVisible.text.includes('Not started')||taskVisible.text.includes('Waiting')}});
 if(coverageStarted){try{const coverage=await cdp.send('Profiler.takePreciseCoverage');await cdp.send('Profiler.stopPreciseCoverage');const scripts=[];for(const row of coverage.result||[]){const url=parsed.get(String(row.scriptId))||'';if(url.includes('p22-nightshift')||url.includes('NxNightShift')||url.includes('nxNightShift'))scripts.push({url,functions:row.functions?.length||0,executedRanges:(row.functions||[]).flatMap(fn=>fn.ranges||[]).filter(range=>range.count>0).length});}report.executionCoverage={available:true,sourceScripts:scripts.length,scripts};}catch(error){report.executionCoverage={available:false,reason:String(error).slice(0,250)};}}
 await page.screenshot({path:resolve(root,'nightshift-ui.png'),fullPage:true});
 report.contracts=[{id,status:report.checks.every(check=>check.ok)?'passed':'failed'}]; report.failures=report.checks.filter(check=>!check.ok).map(check=>check.name); report.ok=report.contracts[0].status==='passed'; report.health={backend:health.backend,root}; report.engineReady=Boolean(cdpReady.Browser);
 await writeFile(outFile,JSON.stringify(report,null,2));
} catch(error) {report.error=String(error?.stack||error).slice(0,1800);if(currentPage)report.renderedBody=await currentPage.locator('body').innerText().catch(()=> '');report.backendLog=backendOut.slice(-1000);report.engineLog=engineOut.slice(-800);report.contracts=[{id,status:'failed'}];report.failures=[String(error?.message||error)];await writeFile(outFile,JSON.stringify(report,null,2)).catch(()=>{});}
finally { if(browser) await browser.close().catch(()=>{}); stop(engine); stop(backend); }
console.log(JSON.stringify(report));
if(!report.ok) process.exitCode=1;
