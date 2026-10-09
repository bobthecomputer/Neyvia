// Drive the actual running UI and retain DOM/pixels for the CL outcome chapter.
import {chromium} from 'playwright';
import {mkdir,writeFile,readFile,stat,access} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash,randomBytes} from 'node:crypto';
import {spawn,spawnSync} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';
import {build} from 'esbuild';
const origin=process.env.APPLE_PREVIEW_ORIGIN, project=process.env.APPLE_PREVIEW_PROJECT;
const repo=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const root=resolve(process.env.APPLE_PREVIEW_ROOT||'.agent_control/apple/preview');
const out=resolve(root,'captures');
await mkdir(out,{recursive:true});
const contextAdmission=resolve(repo,'scripts/evidence/browser-context-engine-admission.json');
const admissionPath=await access(contextAdmission).then(()=>contextAdmission,()=>resolve(repo,'scripts/evidence/C2h-engine-admission.json'));
const admission=JSON.parse(await readFile(admissionPath,'utf8'));
if(admission.stealth!==false||admission.systemInstall!==false)throw Error('Apple preview requires admitted non-stealth user-local Obscura');
for(const name of ['engineBinary','workerBinary']){const row=admission[name],bytes=await readFile(row.path);if((await stat(row.path)).size!==row.bytes||createHash('sha256').update(bytes).digest('hex')!==row.sha256)throw Error('Obscura admission bytes changed');}
const enginePort=Number(process.env.APPLE_PREVIEW_ENGINE_PORT),token=randomBytes(32).toString('base64url');
const profile=resolve(root,'engine-home');await mkdir(profile,{recursive:true});
const engineEnv={...process.env,HOME:profile,USERPROFILE:profile,APPDATA:profile,LOCALAPPDATA:profile,OBSCURA_CDP_TOKEN:token};
for(const key of Object.keys(engineEnv))if(/API.?KEY|SECRET|PASSWORD|CREDENTIAL|AUTH.*FILE|BROKER/i.test(key))delete engineEnv[key];
const engine=spawn(admission.engineBinary.path,['serve','--host','127.0.0.1','--port',String(enginePort),'--max-connections','4','--allow-private-network'],{windowsHide:true,stdio:'ignore',env:engineEnv});
let browser;
try{const until=Date.now()+20000;while(Date.now()<until){if(engine.exitCode!==null)throw Error('Owned Obscura exited');try{const r=await fetch(`http://127.0.0.1:${enginePort}/json/version`,{headers:{Authorization:`Bearer ${token}`}});if(r.ok)break;}catch{}await delay(100);}
browser=await chromium.connectOverCDP(`http://127.0.0.1:${enginePort}`,{headers:{Authorization:`Bearer ${token}`},timeout:10000});}
catch(error){spawnSync('taskkill',['/PID',String(engine.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});throw error;}
const context=await browser.newContext({viewport:{width:1560,height:1050}});
const page=await context.newPage();
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const consoleDiagnostics=[];page.on('console',message=>{if(message.type()==='error')consoleDiagnostics.push(message.text());});
const previewResponses=[];page.on('response',response=>{if(response.url().includes('/api/ui/mobile-preview/'))previewResponses.push({url:response.url(),status:response.status(),type:response.headers()['content-type']});});
const calls=[];
const uiCalls=[];
page.on('response',async response=>{
  if(!response.url().endsWith('/api/ui/tools/call'))return;
  try {
    const request=response.request().postDataJSON(),body=await response.json();
    const value=body.data?.result?.data??body.data?.result??body.data??body;
    uiCalls.push({tool:request.tool,arguments:request.arguments,status:response.status(),ok:value.ok,
      outcome:value.status,error:value.error,results:value.results?.map(row=>({status:row.status,error:row.error,checks:row.checks})),text:value.ok === false ? value.text?.slice(-3000) : undefined});
  }catch{}
});
async function tool(name,args,timeout=30000){
  const response=await page.request.post(origin+'/api/ui/tools/call',{data:{tool:'neyvia.'+name,arguments:args},timeout});
  const body=await response.json();
  const result=body.data?.result??body.result??body;
  calls.push({name,args,status:response.status(),result});
  if(!response.ok())throw new Error(`${name}: HTTP ${response.status()} ${body.error||''}`);
  return result.data??result;
}
try {
  const login=await page.request.post(origin+'/api/auth/local-session',{data:{}});
  if(!login.ok())throw new Error('Disposable local login failed');
  const started=Date.now();
  // A source-drifted manual cache takes the full strict reload on this disposable
  // first request. Keep a bounded startup budget; subsequent UI calls retain 30s.
  const initial=await tool('cl',{lines:`G: mobile.status(project=${JSON.stringify(project)})["preview"]["ready"] == true\nrun mobile-studio.preview-apple(project=${JSON.stringify(project)},device="iphone-16-pro")\ndone()`},120000);
  const initialManualLoadMs=Date.now()-started;
  if(!initial.ok)throw new Error(JSON.stringify({status:initial.status,results:initial.results?.map(r=>({status:r.status,error:r.error,checks:r.checks}))}));
  const component=resolve(repo,'web/src/neyvia/next/NxMobileStudio.jsx').replaceAll('\\','/');
  const entry=`import React from 'react';import {createRoot} from 'react-dom/client';import {NxMobileStudio} from '${component}';import '${resolve(repo,'web/src/neyvia/next/nxTokens.css').replaceAll('\\','/')}'; window.p22Mount=project=>createRoot(document.querySelector('#owned')).render(React.createElement('div',{className:'nx'},React.createElement(NxMobileStudio,{target:project})));`;
  const built=await build({stdin:{contents:entry,resolveDir:repo,loader:'js'},bundle:true,write:false,outdir:resolve(root,'bundle'),format:'iife',platform:'browser',target:'chrome120',jsx:'automatic',define:{'process.env.NODE_ENV':'"production"','import.meta.env':'{"DEV":false,"PROD":true,"MODE":"production"}'},logLevel:'silent'});
  const js=built.outputFiles.find(f=>f.path.endsWith('.js'))?.text,css=built.outputFiles.find(f=>f.path.endsWith('.css'))?.text||'';
  if(!js)throw Error('Production Mobile Studio bundle missing');
  await page.goto(origin+'/api/health',{waitUntil:'domcontentloaded'});
  await page.setContent(`<!doctype html><html><head><style>${css}</style><style>html,body{margin:0;background:#101820;color:#f3f6f8}#owned,.nx{height:100vh}</style></head><body><main id="owned"></main></body></html>`);
  await page.evaluate(url=>{window.__FLUXIO_BACKEND_URL__=url;},origin);
  await page.addScriptTag({content:js});await page.evaluate(project=>window.p22Mount(project),project);
  await page.waitForTimeout(1500);
  await page.screenshot({path:out+'/starting.png'});
  // Production mode controls operate the actual authenticated backend.
  await page.getByRole('combobox',{name:'Phone',exact:true}).waitFor({timeout:30000});
  const full=page.getByRole('button',{name:/Full screen \(Alt/});
  if(await full.count())await full.first().click();
  const frames=[];
  for(const [device,name] of [['iphone-16-pro','iphone'],['mac-window','mac'],['ipad-pro-13','ipad']]){
    await page.getByRole('combobox',{name:'Phone',exact:true}).selectOption(device);
    const frame=page.frameLocator('iframe[title="Your app in the device frame"]');
    await frame.locator('.ss-page').first().waitFor({timeout:30000});
    await page.waitForTimeout(500);
    const text=await frame.locator('body').innerText();
    const observation=await frame.locator('body').evaluate(()=>({title:document.title,text:document.body.innerText,
      width:innerWidth,height:innerHeight,ua:navigator.userAgent,touch:navigator.maxTouchPoints,
      coarse:matchMedia('(pointer: coarse)').matches,fontSize:getComputedStyle(document.documentElement).fontSize,
      dark:matchMedia('(prefers-color-scheme: dark)').matches,safe:window.__NX_MOBILE__.safe}));
    if(observation.title !== 'Scroll Study' || text.length < 60)throw new Error(`Scroll Study did not render in ${name} frame`);
    await page.locator('.nx-ms').screenshot({path:out+'/'+name+'.png'});
    frames.push({device,...observation,screenshot:out+'/'+name+'.png'});
  }
  // Real keyboard navigation and reload; observe storage without concealing
  // the opaque sandbox's IndexedDB limitation.
  const frame=page.frameLocator('iframe[title="Your app in the device frame"]');
  const before=await frame.locator('body').evaluate(()=>window.scrollStudy.state());
  await frame.locator('#viewport').click();
  await page.keyboard.press('ArrowDown');
  await page.waitForTimeout(600);
  const advanced=await frame.locator('body').evaluate(()=>window.scrollStudy.state());
  if(advanced.index <= before.index)throw new Error('Scroll Study navigation did not advance: '+JSON.stringify({before:before.index,after:advanced.index}));
  await page.getByRole('button',{name:'Reload the app',exact:true}).click();
  await frame.locator('.ss-page').first().waitFor();
  const restored=await frame.locator('body').evaluate(()=>window.scrollStudy.state());
  await page.getByRole('combobox',{name:'Text size'}).selectOption('1.5');
  await frame.locator('.ss-page').first().waitFor();
  const font=await frame.locator('body').evaluate(()=>getComputedStyle(document.documentElement).fontSize);
  if(font !== '24px')throw new Error('Emulated text scale did not apply');
  await page.getByRole('button',{name:'Phone in light mode',exact:true}).click();
  await frame.locator('.ss-page').first().waitFor();
  const dark=await frame.locator('body').evaluate(()=>matchMedia('(prefers-color-scheme: dark)').matches);
  if(!dark)throw new Error('Emulated dark mode did not apply');
  await page.getByRole('button',{name:'Keyboard off',exact:true}).click();
  await page.getByLabel('Emulated keyboard', {exact:true}).waitFor();
  await frame.locator('.ss-card').first().waitFor({timeout:30000});
  await page.waitForTimeout(500);
  await page.locator('.nx-ms').screenshot({path:out+'/ipad-behaviours.png'});
  await page.getByRole('button',{name:'Keyboard on',exact:true}).click();
  const apple=page.getByRole('region',{name:'Apple targets'});
  await apple.getByRole('combobox',{name:'Apple build target'}).selectOption('macos');
  const previousBuild=await tool('mobile.status',{project});
  await apple.getByRole('button',{name:'Build .app + ZIP',exact:true}).click();
  // Wait for the production UI's CL call and independently observe its new job.
  await page.waitForFunction(()=>!document.querySelector('[aria-label="Apple targets"] button')?.disabled,null,{timeout:90000});
  const completed=await tool('mobile.status',{project});
  if(completed.builds.macos.receiptPath === previousBuild.builds.macos.receiptPath || completed.jobs.find(row=>row.platform==='macos')?.status !== 'done')throw new Error('UI build did not complete a new Mac bundle');
  await apple.getByRole('button',{name:'Verify bundle',exact:true}).click();
  await apple.getByRole('status').filter({hasText:'Bundle hashes verified'}).waitFor({timeout:30000});
  await apple.locator('summary').click();
  await apple.getByRole('button',{name:'Show Mac frame',exact:true}).click();
  await page.getByRole('combobox',{name:'Phone',exact:true}).selectOption('mac-window');
  await apple.getByRole('button',{name:'Prepare iPhone Simulator workflow',exact:true}).click();
  await apple.getByRole('status').filter({hasText:'No run was started'}).waitFor({timeout:30000});
  await apple.getByRole('combobox',{name:'Apple build target'}).selectOption('watchos');
  if(!await apple.getByRole('button',{name:'Build .ipa',exact:true}).isDisabled())throw new Error('Watch native build must be disabled');
  const behaviours={navigation:{before,advanced,restored},persistenceVerified:!restored.storageError,
    storageLimitation:restored.storageError||null,font,dark,keyboardRendered:true,verifiedFromUi:true,cloudPreparedOff:true,watchBuildDisabled:true};
  const result={ok:true,runId:process.env.APPLE_PREVIEW_RUN_ID,headless:true,engine:"obscura",browserVersion:browser.version(),origin,project,initialManualLoadMs,frames,behaviours,errors,uiCalls,calls};
  await writeFile(resolve(root,'receipt.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({ok:true,frames:frames.map(f=>f.device),errors}));
} catch(error){
  await page.screenshot({path:out+'/failed.png'}).catch(()=>{});
  const frameDiagnostics=page.frames().map(frame=>({url:frame.url()}));
  await writeFile(resolve(root,'receipt.json'),JSON.stringify({ok:false,error:String(error),errors,consoleDiagnostics,previewResponses,frameDiagnostics,uiCalls,calls},null,2));
  throw error;
} finally {await context.close();await browser.close();if(engine.exitCode===null)spawnSync('taskkill',['/PID',String(engine.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});}
