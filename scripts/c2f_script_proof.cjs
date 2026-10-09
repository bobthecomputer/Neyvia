/* Real native tool admission, restart persistence, early goal exit and failure quarantine. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto'),{spawn}=require('node:child_process');
const repo=path.resolve(__dirname,'..'),base='http://127.0.0.1:48726',root=path.join(repo,'.agent_control/proofs/C2f/script-'+crypto.randomUUID());
const out='scripts/evidence/C2f-script-proof.json',report={schema:'neyvia.C2f.native-script-proof@1',ports:[48726,48728,48729],checks:[],calls:[]};
fs.mkdirSync(path.join(root,'config'),{recursive:true});fs.writeFileSync(path.join(root,'config/neyvia_browser_authority.json'),JSON.stringify({schema:'neyvia.browser-authority.v1',proofPorts:report.ports}));
report.engineAdmission=JSON.parse(fs.readFileSync(path.join(repo,'scripts/evidence/C2f-engine-admission.json')));
const env={...process.env,PYTHONPATH:path.join(repo,'src'),PYTHONDONTWRITEBYTECODE:'1',NEYVIA_PROOF_CREDENTIAL_GUARD:'1',NEYVIA_WEB_PORT:'48726',FLUXIO_WEB_PORT:'48726',NEYVIA_UI_BACKEND_URL:base,NEYVIA_BROWSER_BASE:base,NEYVIA_CONNECTED_SERVICE_PORT:'48726',NEYVIA_BROWSER_PROOF_PORTS:report.ports.join(','),NEYVIA_BROWSER_PROOF_SCOPE:'C2',NEYVIA_BROWSER_PROOF_ROOT:root,NEYVIA_TOOL_AUTO_UPDATE:'0',FLUXIO_RUNTIME_AUTO_UPDATE:'0',NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0',FLUXIO_LOCAL_SESSION_BOOTSTRAP:'1',NEYVIA_LAYA_URL:'http://127.0.0.1:48724'};delete env.NEYVIA_OBSCURA_EXE;
let backend,fixture,cookie;
function check(name,ok,detail){report.checks.push({name,ok:!!ok,detail});if(!ok)throw Error(name);}
async function post(route,body){const start=performance.now();const r=await fetch(base+route,{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie||''},body:JSON.stringify(body),signal:AbortSignal.timeout(60000)});const v=await r.json();report.calls.push({route,body,status:r.status,ms:performance.now()-start,value:v});return v;}
const call=(op,args={})=>post('/api/ui/browser',{op,args});
async function tool(op,args){const v=await post('/api/ui/tools/call',{tool:'neyvia.browser.'+op,arguments:args});return v.data?.result&&Object.keys(v.data.result).length?v.data.result:v.result||v;}
async function manualTool(op,args){const v=await post('/api/ui/tools/call',{tool:'neyvia.manual.'+op,arguments:args});return v.data?.result&&Object.keys(v.data.result).length?v.data.result:v.result||v;}
async function launch(){const log=fs.openSync(path.join(root,'backend.log'),'a');backend=spawn('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe',['scripts/run_web_backend.py','--host','127.0.0.1','--port','48726','--root',root,'--skip-runtime-auto-update','--skip-proof-self-check'],{cwd:repo,env,windowsHide:true,stdio:['ignore',log,log]});fs.closeSync(log);const end=Date.now()+60000;while(Date.now()<end){try{if((await fetch(base+'/api/health',{signal:AbortSignal.timeout(500)})).ok)break;}catch{}if(backend.exitCode!==null)throw Error('Backend exited');await new Promise(r=>setTimeout(r,100));}const r=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!r.ok)throw Error('Session unavailable');cookie=r.headers.get('set-cookie').split(';')[0];await call('headless.start',{port:48728,allowLocalFixtures:true});}
async function halt(){if(!backend)return;await call('headless.stop');const done=new Promise(r=>backend.once('exit',r));backend.kill();await done;backend=null;}
async function open(){const v=await tool('open',{url:'http://127.0.0.1:48729/',engine:'obscura'});check('native tab creation returns actual tab',!!v.tabId,v);await call('tab.grant',{tabId:v.tabId,enabled:true});return v.tabId;}
async function main(){fixture=http.createServer((q,r)=>{r.setHeader('Content-Type','text/html');if(q.url==='/broken'){r.end('<!doctype html><title>Changed fixture</title><p>Apply control removed</p>');return;}r.end('<!doctype html><title>Compiled procedure fixture</title><label>Query<input aria-label="Query" id="q"></label><button onclick="history.replaceState(null,\'\',\'?q=\'+encodeURIComponent(document.getElementById(\'q\').value));document.getElementById(\'result\').textContent=document.getElementById(\'q\').value;document.getElementById(\'count\').textContent=Number(document.getElementById(\'count\').textContent)+1">Apply query</button><p id="result">Ready</p><p id="count">0</p>');});await new Promise((resolve,reject)=>{fixture.once('error',reject);fixture.listen(48729,'127.0.0.1',resolve);});await launch();let tabId=await open();
 const steps=[{target:{role:'textbox',name:'Query'},action:'fill',value:{$input:'query'}},{target:{role:'button',name:'Apply query'},action:'click',expect:{path:'/text',contains:{$input:'query'}}}],checks=[{path:'/text',contains:{$input:'query'}},{path:'/elements/0/name',equals:'Query'}];
 const first=await tool('script.learn',{tabId,name:'native-query',inputs:{query:'first success'},steps,checks});check('native first success compiles only verified effects',first.status==='compiled'&&first.verification?.verified&&first.receipts.length===2,first);
 const manual=await tool('site.manual',{tabId});check('site CL exposes admitted parameterized procedure',manual.compiledProcedures?.some(p=>p.name==='native-query')&&manual.cl.includes('script.run'),manual.compiledProcedures);
 await halt();await launch();tabId=await open();const replay=await tool('script.run',{tabId,name:'native-query',inputs:{query:'fresh parameter'}});check('persisted native replay uses fresh input and zero tokens',replay.status==='done'&&replay.verification?.verified&&replay.tokens===0&&replay.modelCalls===0,replay);
 const early=await tool('script.run',{tabId,name:'native-query',inputs:{query:'fresh parameter'}});check('fresh passing goal dispatches no actions',early.earlyExit===true&&early.receipts.length===0&&early.observation.text===replay.observation.text,early);
 const inputs={tabId,name:'native-query',inputs:{query:'fresh parameter'},expectedText:'fresh parameter'},procedure={id:'browser',chapter:'compiled-browser',procedure:'replay-first-success',inputs};
 for(let n=0;n<2;n++){const run=await manualTool('run',procedure);check('authored CL manual runs with independent fresh goal '+n,run.status==='completed',run);}
 const compiled=await manualTool('compile',{...procedure,minRuns:2});check('existing CL compiler admits grounded zero-token script',compiled.zeroToken===true&&!!compiled.scriptId,compiled);
 const compiledRun=await manualTool('script.run',{scriptId:compiled.scriptId,inputs});check('compiled CL executes through existing runner with actual goal',compiledRun.status==='completed',compiledRun);
 const withURL=[...checks,{path:'/url',contains:{$input:'queryParam'}}];
 const bound=await tool('script.learn',{tabId,name:'url-query',inputs:{query:'bound value',queryParam:'q=bound%20value'},steps,checks:withURL});check('URL parameter binding learned from actual successful navigation',bound.status==='compiled',bound);
 const learned=await tool('site.manual',{tabId}),binding=learned.compiledProcedures.find(p=>p.name==='url-query')?.inputBindings?.queryParam;
 const stored=fs.readFileSync(path.join(root,'.neyvia/browser/compiled/url-query.json'),'utf8');
 check('site CL exposes URL binding without cached query values',binding?.urlQueryParameter==='q'&&binding.sourceInput==='query'&&binding.encoding==='percent'&&!stored.includes('bound value'),binding);
 const rebound=await tool('script.run',{tabId,name:'url-query',inputs:{query:'another phrase',queryParam:'q=another%20phrase'}});check('learned URL binding replays a fresh arbitrary query',rebound.ok===true&&rebound.tokens===0&&rebound.observation.url.includes('q=another%20phrase'),rebound);
 // This input already exists in the field, so require an independent outcome
 // that the fixture cannot produce; failure must quarantine, never retry.
 const bad=await tool('script.learn',{tabId,name:'quarantine-query',inputs:{query:'admitted'},steps,checks:[{path:'/text',contains:'admitted'}]});check('second procedure admitted before adverse path',bad.status==='compiled',bad);
 // A real changed page removes the observed Apply control. Its URL is still the
 // same explicitly granted origin; no synthetic success response is supplied.
 await call('tab.close',{tabId});const broken=(await tool('open',{url:'http://127.0.0.1:48729/broken',engine:'obscura'})).tabId;await call('tab.grant',{tabId:broken,enabled:true});
 const failed=await tool('script.run',{tabId:broken,name:'quarantine-query',inputs:{query:'failure'}});check('changed controls fail without model or action replay',failed.ok===false&&failed.replaySafe===false&&failed.receipts.length===0,failed);const refused=await tool('script.run',{tabId:broken,name:'quarantine-query',inputs:{query:'failure'}});check('quarantined procedure refuses second attempt',refused.ok===false&&JSON.stringify(refused).includes('Relearn changed controls before replay'),refused);
 await call('tab.close',{tabId:broken});
 const active=[];let nextSpace;
 for(let i=0;i<9;i++){
   const profile=await call('profile.create',{name:'Native capacity '+i});
   const space=await call('space.create',{name:'Native capacity '+i,profileId:profile.id});
   if(i===8){nextSpace=space.id;break;}
   const opened=await call('tab.open',{url:'http://127.0.0.1:48729/',engine:'obscura',spaceId:space.id});
   check('capacity profile opens actual page '+i,!!opened.tabId,opened);active.push(opened.tabId);
 }
 const capped=await call('tab.open',{url:'http://127.0.0.1:48729/',engine:'obscura',spaceId:nextSpace});
 check('eight active profiles retain capacity refusal',capped.ok===false&&JSON.stringify(capped).includes('profile worker limit'),capped);
 await call('tab.close',{tabId:active.shift()});
 const reclaimed=await call('tab.open',{url:'http://127.0.0.1:48729/',engine:'obscura',spaceId:nextSpace});
 check('idle profile retires before ninth native connection',!!reclaimed.tabId,reclaimed);
 const preserved=await call('observe',{tabId:active.at(-1)});
 check('idle reclamation preserves another live profile',!!preserved.revision,preserved);
 for(const tabId of active.concat(reclaimed.tabId))await call('tab.close',{tabId});
 report.ok=true;
}
main().catch(e=>{report.error=e.stack;report.ok=false;process.exitCode=1}).finally(async()=>{try{await halt();}catch(e){report.cleanupError=e.message;if(backend)backend.kill();}if(fixture)await new Promise(r=>fixture.close(r));report.sources=Object.fromEntries(['src/grant_agent/browser_scripts.py','src/grant_agent/browser_site_manuals.py','src/grant_agent/neyvia_browser.py','src/grant_agent/browser_obscura.py'].map(p=>[p,crypto.createHash('sha256').update(fs.readFileSync(path.join(repo,p))).digest('hex')]));const raw=JSON.stringify(report,null,2)+'\n';fs.writeFileSync(path.join(root,'report.json'),raw);fs.writeFileSync(path.join(repo,out.replace('.json','-'+path.basename(root)+'.json')),raw);if(report.ok)fs.writeFileSync(path.join(repo,out),raw);console.log(JSON.stringify({ok:report.ok,error:report.error,checks:report.checks.map(({name,ok})=>({name,ok}))}));});
