/* One actual DOM-click/fetch attempt; no inferred resource-policy proof. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),net=require('node:net'),crypto=require('node:crypto'),{spawn}=require('node:child_process');
const repo=path.resolve(__dirname,'..'),ports=[48725,48726,48727],base='http://127.0.0.1:48725';
const root=path.join(repo,'.agent_control/proofs/C2d/resource-'+crypto.randomUUID());
const report={schema:'neyvia.C2d.resource-proof@1',startedAt:new Date().toISOString(),ports,root:path.relative(repo,root),calls:[],controlHits:0,crossOriginHits:0};
report.sources=Object.fromEntries(['src/grant_agent/browser_obscura.py','src/grant_agent/neyvia_browser.py','src/grant_agent/browser_dom.js','scripts/c2d_resource_proof.cjs'].map(p=>[p,crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')]));
let backend,fixture,cookie='',tabId;
fs.mkdirSync(path.join(root,'config'),{recursive:true});fs.writeFileSync(path.join(root,'config/neyvia_browser_authority.json'),JSON.stringify({schema:'neyvia.browser-authority.v1',proofPorts:ports}));
const env={...process.env,PYTHONPATH:path.join(repo,'src'),PYTHONDONTWRITEBYTECODE:'1',NEYVIA_PROOF_CREDENTIAL_GUARD:'1',NEYVIA_WEB_PORT:'48725',FLUXIO_WEB_PORT:'48725',NEYVIA_UI_BACKEND_URL:base,NEYVIA_BROWSER_BASE:base,NEYVIA_CONNECTED_SERVICE_PORT:'48725',NEYVIA_BROWSER_PROOF_PORTS:ports.join(','),NEYVIA_BROWSER_PROOF_SCOPE:'C2',NEYVIA_BROWSER_PROOF_ROOT:root,NEYVIA_TOOL_AUTO_UPDATE:'0',FLUXIO_RUNTIME_AUTO_UPDATE:'0',NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0',FLUXIO_LOCAL_SESSION_BOOTSTRAP:'1',NEYVIA_OBSCURA_EXE:path.join(repo,'.agent_control/C2d/obscura/obscura.exe'),NEYVIA_LAYA_URL:'http://127.0.0.1:48724'};
report.engineBinary={path:path.relative(repo,env.NEYVIA_OBSCURA_EXE),sha256:crypto.createHash('sha256').update(fs.readFileSync(env.NEYVIA_OBSCURA_EXE)).digest('hex'),identityBoundary:'Existing task-local executable; historical binary hash equivalence not established'};
async function call(op,args={}){const began=performance.now(),r=await fetch(base+'/api/ui/browser',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op,args}),signal:AbortSignal.timeout(60000)}),data=await r.json();report.calls.push({op,status:r.status,ok:data.ok,ms:performance.now()-began,error:data.error});return data;}
async function free(p){await new Promise((resolve,reject)=>{const s=net.connect(p,'127.0.0.1');s.on('connect',()=>{s.destroy();reject(Error('Assigned port occupied '+p));});s.on('error',resolve);});}
async function main(){
 for(const p of ports)await free(p);
 fixture=http.createServer((q,r)=>{if(q.url==='/control'){report.controlHits++;r.end('Allowed control');return;}if(q.url==='/blocked'){report.crossOriginHits++;r.end('Unexpected fetch');return;}r.setHeader('Content-Type','text/html');r.end(`<!doctype html><title>Resource check</title><button onclick="fetch('/control').then(()=>{document.getElementById('status').textContent='Control completed'}).catch(()=>{document.getElementById('status').textContent='Control refused'})">Control request</button><button onclick="fetch('http://localhost:48727/blocked').then(()=>{document.getElementById('status').textContent='Cross request completed'}).catch(()=>{document.getElementById('status').textContent='Cross request refused'})">Cross request</button><p id="status">Ready</p>`);});await new Promise(r=>fixture.listen(48727,'127.0.0.1',r));
 const log=fs.openSync(path.join(root,'backend.log'),'a');backend=spawn('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe',['scripts/run_web_backend.py','--host','127.0.0.1','--port','48725','--root',root,'--skip-runtime-auto-update','--skip-proof-self-check'],{cwd:repo,env,windowsHide:true,stdio:['ignore',log,log]});fs.closeSync(log);
 const deadline=Date.now()+60000;let ready=false;while(Date.now()<deadline){if(backend.exitCode!==null)throw Error('Owned backend exited');try{ready=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(700)})).ok;if(ready)break;}catch{}await new Promise(r=>setTimeout(r,100));}if(!ready)throw Error('Backend readiness timeout');
 const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!login.ok)throw Error('Local owner session failed');cookie=login.headers.get('set-cookie').split(';')[0];
 await call('headless.start',{port:48726,allowLocalFixtures:true,allowPublicResources:true});
 const opened=await call('tab.open',{url:'http://127.0.0.1:48727/',engine:'obscura'});if(!opened.ok)throw Error('Owned fixture open failed: '+JSON.stringify(opened.error));tabId=opened.tabId;await call('tab.grant',{tabId,enabled:true});
 for(const name of ['Control request','Cross request']){
  let obs=await call('observe',{tabId});const target=obs.elements.find(e=>e.name===name);if(!target)throw Error('Actual named request control missing');
  const result=await call('action',{tabId,revision:obs.revision,element:target.id,action:'click'});
  obs=await call('observe',{tabId});(report.observations??=[]).push({name,actionOk:result.ok,verification:result.verification,error:result.error,text:obs.text,networkPolicy:obs.networkPolicy,controlHits:report.controlHits,crossOriginHits:report.crossOriginHits});
 }
 const last=report.observations.at(-1),blocked=last.networkPolicy?.blockedOrigins||{};
 report.verdict=report.controlHits===1&&report.crossOriginHits===0&&blocked['http://localhost:48727']>=1&&last.text.includes('Cross request refused')?'deny_verified':report.crossOriginHits>0?'unexpected_local_fetch':report.controlHits===0?'fetch_path_not_established':'deny_unproven';
}
main().catch(e=>{report.error=e.stack;process.exitCode=1;}).finally(async()=>{
 if(tabId)try{await call('tab.close',{tabId});}catch{}if(cookie)try{await call('headless.stop');}catch{}
 if(fixture)await new Promise(r=>fixture.close(r));if(backend&&backend.exitCode===null){const done=new Promise(r=>backend.once('exit',r));backend.kill();await done;}
 report.finishedAt=new Date().toISOString();report.cleanup={backendExited:backend?.exitCode!==null||backend?.signalCode!==null,engineStopRequested:true};
 fs.writeFileSync('scripts/evidence/C2d-resource-proof.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({verdict:report.verdict,controlHits:report.controlHits,crossOriginHits:report.crossOriginHits,observations:report.observations,error:report.error,cleanup:report.cleanup}));
});
