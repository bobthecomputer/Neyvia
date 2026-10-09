/* Real production commands: site learning/reuse/demotion and single-dispatch batches. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),net=require('node:net'),crypto=require('node:crypto');
const {spawn}=require('node:child_process');
const repo=path.resolve(__dirname,'..'),ports=[48725,48726,48727],base='http://127.0.0.1:48725';
const root=path.join(repo,'.agent_control/proofs/C2d/site-'+crypto.randomUUID());
const report={schema:'neyvia.C2d.site-proof@1',startedAt:new Date().toISOString(),ports,root:path.relative(repo,root),checks:[],calls:[]};
report.sources=Object.fromEntries(['src/grant_agent/browser_site_manuals.py','src/grant_agent/neyvia_browser.py','src/grant_agent/browser_dom.js','src/grant_agent/browser_obscura.py','scripts/c2d_site_proof.cjs'].map(p=>[p,crypto.createHash('sha256').update(fs.readFileSync(path.join(repo,p))).digest('hex')]));
let backend,fixture,cookie='',tabId,forbiddenHits=0;
fs.mkdirSync(path.join(root,'config'),{recursive:true});
fs.writeFileSync(path.join(root,'config/neyvia_browser_authority.json'),JSON.stringify({schema:'neyvia.browser-authority.v1',proofPorts:ports}));
const env={...process.env,PYTHONPATH:path.join(repo,'src'),PYTHONDONTWRITEBYTECODE:'1',NEYVIA_PROOF_CREDENTIAL_GUARD:'1',NEYVIA_WEB_PORT:'48725',FLUXIO_WEB_PORT:'48725',NEYVIA_UI_BACKEND_URL:base,NEYVIA_BROWSER_BASE:base,NEYVIA_CONNECTED_SERVICE_PORT:'48725',NEYVIA_BROWSER_PROOF_PORTS:ports.join(','),NEYVIA_BROWSER_PROOF_SCOPE:'C2',NEYVIA_BROWSER_PROOF_ROOT:root,NEYVIA_TOOL_AUTO_UPDATE:'0',FLUXIO_RUNTIME_AUTO_UPDATE:'0',NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0',FLUXIO_LOCAL_SESSION_BOOTSTRAP:'1',NEYVIA_OBSCURA_EXE:path.join(repo,'.agent_control/C2d/obscura/obscura.exe'),NEYVIA_LAYA_URL:'http://127.0.0.1:48724'};
report.engineBinary={path:path.relative(repo,env.NEYVIA_OBSCURA_EXE),sha256:crypto.createHash('sha256').update(fs.readFileSync(env.NEYVIA_OBSCURA_EXE)).digest('hex'),identityBoundary:'Existing task-local executable; historical binary hash equivalence not established'};
function check(name,ok){ok=!!ok;report.checks.push({name,ok});if(!ok)throw Error(name);}
async function call(op,args={}){
 const began=performance.now(),r=await fetch(base+'/api/ui/browser',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op,args}),signal:AbortSignal.timeout(60000)}),data=await r.json();
 report.calls.push({op,status:r.status,ok:data.ok,ms:performance.now()-began,error:data.error});return data;
}
async function free(p){await new Promise((resolve,reject)=>{const s=net.connect(p,'127.0.0.1');s.on('connect',()=>{s.destroy();reject(Error('Assigned port occupied '+p));});s.on('error',resolve);});}
const html=`<!doctype html><title>C2d site proof</title><form onsubmit="event.preventDefault();document.getElementById('result').textContent='Submitted: '+document.getElementById('query').value"><label id="query-label">Search<input id="query" name="q" placeholder="Search records" type="search"></label><button>Search</button></form><button onclick="document.getElementById('query').setAttribute('aria-label','Lookup')">Rename search</button><button onclick="document.getElementById('counter').textContent=String(Number(document.getElementById('counter').textContent)+1)">Commit once</button><button>Duplicate</button><button>Duplicate</button><p id="result">Ready</p><p id="counter">0</p>`;
async function main(){
 for(const port of ports)await free(port);
 const log=fs.openSync(path.join(root,'backend.log'),'a');backend=spawn('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe',['scripts/run_web_backend.py','--host','127.0.0.1','--port','48725','--root',root,'--skip-runtime-auto-update','--skip-proof-self-check'],{cwd:repo,env,windowsHide:true,stdio:['ignore',log,log]});fs.closeSync(log);
 const deadline=Date.now()+60000;let ready=false;while(Date.now()<deadline){if(backend.exitCode!==null)throw Error('Owned backend exited');try{ready=(await fetch(base+'/api/health',{signal:AbortSignal.timeout(700)})).ok;if(ready)break;}catch{}await new Promise(r=>setTimeout(r,100));}if(!ready)throw Error('Owned backend readiness timeout');
 const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!login.ok)throw Error('Local owner session failed');cookie=login.headers.get('set-cookie').split(';')[0];
 fixture=http.createServer((q,r)=>{if(q.url==='/forbidden.js'){forbiddenHits++;r.setHeader('Content-Type','application/javascript');r.end('document.body.textContent="Forbidden load occurred"');return;}r.setHeader('Content-Type','text/html');r.end(q.url==='/policy'?'<title>Resource policy</title><script src="http://localhost:48727/forbidden.js"></script><p>Allowed fixture</p>':q.url==='/unlabelled'?'<title>Conventional search</title><form name="f"><input name="q"><button>Go</button></form>':q.url==='/auth'?'<title>Sign in</title><form><input type="password"><button>Sign in</button></form>':html);});await new Promise(r=>fixture.listen(48727,'127.0.0.1',r));
 check('explicit nonstealth engine started',(await call('headless.start',{port:48726,allowLocalFixtures:true,allowPublicResources:true})).ok);
 const opened=await call('tab.open',{url:'http://127.0.0.1:48727/',engine:'obscura'});check('owned fixture homepage opened in actual engine',opened.ok&&opened.tabId);tabId=opened.tabId;await call('tab.grant',{tabId,enabled:true});
 let manual=await call('site.manual',{tabId});check('first visit learned actual CL with typed site-search procedure',manual.status==='learned'&&manual.cl.includes('P grounded-batch')&&manual.cl.includes('P site-search-')&&manual.procedures.some(p=>p.kind==='search-first'));
 manual=await call('site.manual',{tabId});check('fresh structure admitted reuse',manual.status==='reused'&&manual.validation.structureMatches);
 const target=manual.procedures.find(p=>p.kind==='search-first').steps[0].target;
 let batch=await call('action.batch',{tabId,revision:manual.revision,steps:[{target,action:'fill',value:'alpha'},{target,action:'submit',expect:{path:'/text',contains:'Submitted: alpha'}}]});
 check('batched real search fill and submit independently verified',batch.ok&&batch.completed===2&&batch.receipts.every(r=>r.verification.verified)&&batch.observation.text.includes('Submitted: alpha'));
 manual=await call('site.manual',{tabId});check('query changes do not invalidate structure',manual.status==='reused');
 const saved=fs.readFileSync(path.join(root,'.neyvia/browser/site-manuals',fs.readdirSync(path.join(root,'.neyvia/browser/site-manuals'))[0]),'utf8');check('stored manual excludes query and result text',!saved.includes('alpha')&&!saved.includes('Submitted:'));
 const obs=manual.observation,rename=obs.elements.find(e=>e.name==='Rename search'),queryIndex=obs.elements.findIndex(e=>e.inputName==='q');
 check('rename actual observed control effect verified',(await call('action',{tabId,revision:obs.revision,element:rename.id,action:'click',expect:{path:'/elements/'+queryIndex+'/name',equals:'Lookup'}})).ok);
 manual=await call('site.manual',{tabId});check('changed controls demote prior facts and relearn',manual.status==='relearned'&&manual.validation.priorFactsDemoted&&manual.quarantined.length===1);
 check('new structure subsequently reused',(await call('site.manual',{tabId})).status==='reused');
 batch=await call('action.batch',{tabId,revision:manual.revision,steps:[{target:{role:'button',name:'Duplicate'},action:'click'},{target:{role:'button',name:'Commit once'},action:'click'}]});check('ambiguous target stops before any effect',!batch.ok&&batch.completed===0&&batch.error.code==='ambiguous_target');
 batch=await call('action.batch',{tabId,revision:manual.revision,steps:[{target:{role:'button',name:'Commit once'},action:'click',expect:{path:'/text',contains:'impossible expected text'}},{target:{role:'button',name:'Commit once'},action:'click'}]});
 check('failed dispatched effect receipt retained without replay',!batch.ok&&batch.receipts.length===1&&batch.receipts[0].status==='failed'&&batch.receipts[0].verification.verified===false&&batch.replaySafe===false&&/\n1\s*$/.test(batch.observation.text));
 const stale=await call('action.batch',{tabId,revision:manual.revision,steps:[{target:{role:'button',name:'Commit once'},action:'click'}]});check('stale initial revision rejected before effect',!stale.ok&&stale.error.code==='stale_projection');
 const invalid=await call('action.batch',{tabId,revision:batch.observation.revision,steps:[{target:{role:'button',name:'Commit once'},action:'click'},{target:{role:'button',name:'Commit once'},action:'invented'}]});
 check('invalid later batch step rejected before first effect',!invalid.ok&&invalid.error.code==='invalid_batch'&&/\n1\s*$/.test((await call('observe',{tabId})).text));
 report.final={fingerprint:manual.fingerprint,status:manual.status,quarantined:manual.quarantined,failedBatchReceipt:batch.receipts,observedFinalText:batch.observation.text};
 await call('tab.navigate',{tabId,url:'http://127.0.0.1:48727/unlabelled'});
 const conventional=await call('site.manual',{tabId});check('unlabelled observed q textbox yields search-first without invented route',conventional.procedures.some(p=>p.kind==='search-first'&&p.steps[0].target.inputName==='q'&&p.steps[0].target.name===''));
 await call('tab.navigate',{tabId,url:'http://127.0.0.1:48727/auth'});
 const auth=await call('site.manual',{tabId});check('authentication wall refuses manual learning',!auth.ok&&auth.error.code==='auth_required');
 await call('tab.navigate',{tabId,url:'http://127.0.0.1:48727/policy'});
 const policy=await call('observe',{tabId});report.publicResourcePolicy={forbiddenHits,networkPolicy:policy.networkPolicy,text:policy.text,error:policy.error,
   verdict:'Static-script probe did not establish a request; use the separately source-bound c2d_resource_proof.cjs real DOM-click/fetch control and denial receipts'};
}
main().catch(e=>{report.error=e.stack;process.exitCode=1;}).finally(async()=>{
 if(tabId)try{await call('tab.close',{tabId});}catch{}if(cookie)try{await call('headless.stop');}catch{}
 if(fixture)await new Promise(r=>fixture.close(r));if(backend&&backend.exitCode===null){const done=new Promise(r=>backend.once('exit',r));backend.kill();await done;}
 report.finishedAt=new Date().toISOString();report.cleanup={backendExited:backend?.exitCode!==null||backend?.signalCode!==null,engineStopRequested:true};
 fs.writeFileSync('scripts/evidence/C2d-site-proof.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({checks:report.checks,error:report.error,cleanup:report.cleanup}));
});
