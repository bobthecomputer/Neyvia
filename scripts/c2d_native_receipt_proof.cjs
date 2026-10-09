/* Actual WebView2 single-dispatch failed-wait receipts, current source and binary. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),net=require('node:net'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const {spawn,execFile}=require('node:child_process'),{promisify}=require('node:util');
const repo=path.resolve(__dirname,'..'),base='http://127.0.0.1:48725',ports=[48725,48726,48727];
const root=path.join(repo,'.agent_control/proofs/C2d/native-receipt-'+crypto.randomUUID()),output=path.join(repo,'scripts/evidence/C2d-native-receipt-proof.json');
const nativeExe=path.resolve(process.env.C2D_NATIVE_EXE||path.join(repo,'.agent_control/C2d/native/browser-proof-c2d-roles.exe')),sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const report={schema:'neyvia.C2d.native-receipt-proof@1',startedAt:new Date().toISOString(),ports,root:path.relative(repo,root),checks:[],calls:[],native:{path:path.relative(repo,nativeExe),sha256:sha(nativeExe)}};
assert.match(process.env.C2D_NATIVE_EXPECTED_SHA||'',/^[a-f0-9]{64}$/);assert.equal(report.native.sha256,process.env.C2D_NATIVE_EXPECTED_SHA);
report.sources=Object.fromEntries(['src/grant_agent/neyvia_browser.py','src/grant_agent/browser_site_manuals.py','src/grant_agent/browser_dom.js','src-tauri/src/browser_runtime.rs','src-tauri/src/browser_projection.js','scripts/c2d_native_receipt_proof.cjs'].map(p=>[p,sha(path.join(repo,p))]));
let backend,native,fixture,cookie='',tabId;
const env={...process.env,PYTHONPATH:path.join(repo,'src'),PYTHONDONTWRITEBYTECODE:'1',NEYVIA_PROOF_CREDENTIAL_GUARD:'1',NEYVIA_WEB_PORT:'48725',FLUXIO_WEB_PORT:'48725',NEYVIA_UI_BACKEND_URL:base,NEYVIA_BROWSER_BASE:base,NEYVIA_CONNECTED_SERVICE_PORT:'48725',NEYVIA_BROWSER_PROOF_PORTS:ports.join(','),NEYVIA_BROWSER_PROOF_SCOPE:'C2b',NEYVIA_BROWSER_PROOF_ROOT:root,NEYVIA_TOOL_AUTO_UPDATE:'0',FLUXIO_RUNTIME_AUTO_UPDATE:'0',NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0',FLUXIO_LOCAL_SESSION_BOOTSTRAP:'1',NEYVIA_LAYA_URL:'http://127.0.0.1:48724'};
fs.mkdirSync(path.join(root,'config'),{recursive:true});fs.writeFileSync(path.join(root,'config/neyvia_browser_authority.json'),JSON.stringify({schema:'neyvia.browser-authority.v1',proofPorts:ports}));
const sleep=ms=>new Promise(r=>setTimeout(r,ms)),save=()=>fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
async function request(route,body){const began=performance.now(),r=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',Cookie:cookie},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(45000)}),value=await r.json();report.calls.push({route,op:body?.op,status:r.status,ms:performance.now()-began,response:JSON.parse(JSON.stringify(value,(key,v)=>key==='token'?'[memory-only]':v))});return {http:r,value};}
async function call(op,args={}){return (await request('/api/ui/browser',{op,args})).value;}
async function successful(op,args={}){const v=await call(op,args);assert.equal(v.ok,true,JSON.stringify(v));return v;}
async function eventual(fn,ms=30000){const deadline=Date.now()+ms;while(Date.now()<deadline){const v=await fn();if(v)return v;await sleep(50);}throw Error('Actual native transition timed out');}
async function completed(row){if(!row.actionId)return row;const v=await successful('wait',{actionId:row.actionId,timeoutMs:30000});assert.equal(v.status,'done');return v;}
async function observe(){const r=await completed(await successful('observe',{tabId}));return r.result?.observation||r;}
function check(name,condition,detail){report.checks.push({name,ok:!!condition,detail});save();assert.ok(condition,name);}
async function free(p){await new Promise((resolve,reject)=>{const s=net.connect(p,'127.0.0.1');s.on('connect',()=>{s.destroy();reject(Error('Assigned port occupied '+p));});s.on('error',resolve);});}
const html=`<!doctype html><html><head><title>Neyvia native receipt proof</title><style>body{font:24px system-ui;background:#f7faf6;color:#163321;padding:32px}button,input,[role=gridcell]{font:inherit;margin:12px;padding:10px}</style></head><body><h1>Neyvia native receipt proof</h1><p id="counter">Clicks: 0</p><button onclick="window.clickCount=(window.clickCount||0)+1;document.getElementById('counter').textContent='Clicks: '+window.clickCount">Count once</button><form onsubmit="event.preventDefault();document.getElementById('result').textContent='Submitted: '+document.getElementById('query').value"><label>Query<input id="query" name="q" type="search"></label><button>Search</button></form><p id="result">Waiting</p><div role="gridcell" tabindex="0" onclick="document.getElementById('selection').textContent='Selected October 5'">Choose October 5</div><div role="gridcell" aria-readonly="true" tabindex="0" onclick="document.getElementById('selection').textContent='Unexpected readonly selection'">Readonly October 6</div><p id="selection">No date selected</p></body></html>`;
async function main(){
 for(const p of ports)await free(p);
 const passive=Array.from({length:530},(_,i)=>'<h2 style="height:1px;margin:0;font-size:1px">Passive result '+i+'</h2>').join('');
 const pointerHtml=html.replace('</body>',passive+'<button style="position:fixed;right:20px;top:20px" onpointerdown="document.getElementById(\'pointer\').textContent=\'Pointer opened\'">Open pointer menu</button><p style="position:fixed;right:20px;top:100px" id="pointer">Pointer waiting</p></body>');
 fixture=http.createServer((q,r)=>{r.setHeader('Content-Type','text/html; charset=utf-8');r.end(pointerHtml);});await new Promise(r=>fixture.listen(48727,'127.0.0.1',r));
 const log=fs.openSync(path.join(root,'backend.log'),'a');backend=spawn('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe',['scripts/run_web_backend.py','--host','127.0.0.1','--port','48725','--root',root,'--skip-runtime-auto-update','--skip-proof-self-check'],{cwd:repo,env,windowsHide:true,stdio:['ignore',log,log]});fs.closeSync(log);
 await eventual(async()=>{if(backend.exitCode!==null)throw Error('Owned backend exited');try{return (await fetch(base+'/api/health',{signal:AbortSignal.timeout(700)})).ok;}catch{return false;}},60000);
 const login=await request('/api/auth/local-session',{});assert.equal(login.http.status,200);cookie=login.http.headers.get('set-cookie').split(';')[0];
 const {token}=await successful('runtime.connect'),nativeLog=fs.openSync(path.join(root,'native.log'),'a');native=spawn(nativeExe,[],{cwd:repo,env:{...env,NEYVIA_BROWSER_TOKEN:token},windowsHide:true,stdio:['ignore',nativeLog,nativeLog]});fs.closeSync(nativeLog);
 await eventual(async()=>{if(native.exitCode!==null)throw Error('Owned native exited '+native.exitCode);return (await successful('state')).runtime.connected;},40000);
 tabId=(await completed(await successful('tab.open',{url:'http://127.0.0.1:48727/',engine:'webview2'}))).tabId;
 // The operation receipt always carries tabId even if its result is empty.
 assert.ok(tabId);
 await completed(await successful('layout',{tabs:[{tabId,x:0,y:0,width:1200,height:730,visible:true}]}));
 const initial=await eventual(async()=>{const o=await observe();return o.readyState==='complete'&&o.elements.some(e=>e.name==='Count once')?o:false;});
 check('actual native initial counter zero',initial.text.includes('Clicks: 0'));
 check('bounded native projection includes actual late actionable control',initial.truncated===true&&initial.elements.length<=500&&Number(initial.elements.find(e=>e.name==='Open pointer menu')?.id)>500,{total:initial.totalElements,retained:initial.elements.length,pointer:initial.elements.find(e=>e.name==='Open pointer menu')?.id});
 await completed(await successful('tab.grant',{tabId,enabled:true}));
 check('owner grant applied after actual page readiness',(await successful('state')).tabs.find(t=>t.id===tabId)?.agentGranted===true);
 const failed=await call('action.batch',{tabId,revision:initial.revision,steps:[{target:{role:'button',name:'Count once'},action:'click',expect:{path:'/text',contains:'IMPOSSIBLE native expectation'}},{target:{role:'button',name:'Count once'},action:'click'}]});
 report.failedBatch=failed;const receipt=failed.receipts?.[0];
 check('failed native wait is retained with actionId, nativeStatus and verification',failed.ok===false&&failed.completed===0&&failed.receipts?.length===1&&receipt?.actionId&&receipt.nativeStatus==='effect_unconfirmed'&&receipt.verification?.verified===false&&failed.observation?.text.includes('Clicks: 1'),receipt);
 const terminal=await successful('action.get',{actionId:receipt.actionId});report.terminalReceipt=terminal;
 check('same native actionId has completed failed effect receipt',terminal.id===receipt.actionId&&terminal.status==='failed'&&terminal.result?.status==='effect_unconfirmed'&&terminal.result.verification?.verified===false,terminal);
 const wait=await call('wait',{actionId:receipt.actionId,timeoutMs:1000});report.waitError=wait;
 check('direct wait exposes the actual effect_unconfirmed cause',wait.ok===false&&wait.error?.code==='action_failed'&&wait.error.message.includes('effect_unconfirmed'));
 check('standalone HTTP wait exposes attached exact failed native receipt',wait.receipt?.actionId===receipt.actionId&&wait.receipt.nativeStatus==='effect_unconfirmed'&&wait.receipt.verification?.verified===false&&wait.receipt.observation?.text.includes('Clicks: 1'),wait.receipt);
 let obs=await observe();check('fresh observation proves no repeated count click',obs.text.includes('Clicks: 1')&&!obs.text.includes('Clicks: 2'),{text:obs.text});
 const stale=await call('action',{tabId,revision:initial.revision,element:initial.elements.find(e=>e.name==='Count once').id,action:'click'});report.stale=stale;
 check('native stale revision guard rejects before dispatch',stale.ok===false&&stale.error?.code==='stale_projection'&&!stale.actionId,stale);
 obs=await observe();check('stale refusal preserves actual counter one',obs.text.includes('Clicks: 1')&&!obs.text.includes('Clicks: 2'));
 const target={role:'textbox',name:'Query',inputName:'q'};
 const filled=await successful('action.batch',{tabId,revision:obs.revision,steps:[{target,action:'fill',value:'native receipt'}]});
 obs=await observe();
 const submitted=await successful('action.batch',{tabId,revision:obs.revision,steps:[{target,action:'submit',expect:{path:'/text',contains:'Submitted: native receipt'}}]});
 const search={completed:filled.completed+submitted.completed,receipts:[...filled.receipts,...submitted.receipts],observation:submitted.observation};
 const formTerminals=[];for(const r of search.receipts)formTerminals.push(await successful('action.get',{actionId:r.actionId}));
 check('typed native form fill and submit independently verified',search.completed===2&&search.receipts.every(r=>r.actionId&&r.verification?.verified)&&formTerminals.every(r=>r.status==='done'&&r.result.verification?.verified)&&search.observation.text.includes('Submitted: native receipt'),{receipts:search.receipts,terminals:formTerminals});
 obs=await observe();const cell=obs.elements.find(e=>e.role==='gridcell'&&e.name==='Choose October 5'),readonly=obs.elements.find(e=>e.role==='gridcell'&&e.name==='Readonly October 6');
 check('current native binary projects writable gridcell click and readonly refusal',cell?.actions.includes('click')&&readonly&&!readonly.actions.includes('click'),{cell,readonly});
 const chosen=await completed(await successful('action',{tabId,revision:obs.revision,element:cell.id,action:'click',expect:{path:'/text',contains:'Selected October 5'}}));
 check('actual native semantic gridcell click verifies selected date',chosen.result?.verification?.verified&&chosen.result.observation.text.includes('Selected October 5'),chosen.result);
 obs=await observe();const denied=await call('action',{tabId,revision:obs.revision,element:obs.elements.find(e=>e.name==='Readonly October 6').id,action:'click'});
 check('readonly native gridcell click denied before dispatch',denied.ok===false&&denied.error?.code==='invalid_target'&&!denied.actionId,denied);
 obs=await observe();check('readonly refusal preserves actual selected date',obs.text.includes('Selected October 5')&&!obs.text.includes('Unexpected readonly selection'));
 const pointer=await successful('action.batch',{tabId,revision:obs.revision,steps:[{target:{role:'button',name:'Open pointer menu'},action:'click',expect:{path:'/text',contains:'Pointer opened'}}]});
 check('native pointerdown menu activates with one click sequence',pointer.ok===true&&pointer.completed===1&&pointer.receipts[0].verification?.verified&&pointer.observation.text.includes('Pointer opened'),pointer.receipts);
 check('pointer activation preserves single click effect',pointer.observation.text.includes('Clicks: 1')&&!pointer.observation.text.includes('Clicks: 2'));
 await completed(await successful('layout',{tabs:[{tabId,x:0,y:0,width:1200,height:730,visible:true}]}));
 const capture=await completed(await successful('capture',{tabId})),managed=capture.result.path;assert.equal(fs.readFileSync(managed).subarray(1,4).toString(),'PNG');
 const jpeg=path.join(repo,'scripts/evidence/C2d-native-receipt-proof.jpg');report.capture={managedPath:path.relative(repo,managed),pngSha256:sha(managed),pngBytes:fs.statSync(managed).size};
 const q=s=>"'"+s.replaceAll("'","''")+"'",compress=`Add-Type -AssemblyName System.Drawing; $img=[System.Drawing.Image]::FromFile(${q(managed)}); $codec=[System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object MimeType -eq 'image/jpeg'; $params=New-Object System.Drawing.Imaging.EncoderParameters(1); $params.Param[0]=New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality,[long]60); try {$img.Save(${q(jpeg)},$codec,$params)} finally {$params.Dispose();$img.Dispose()}`;
 await promisify(execFile)('powershell.exe',['-NoProfile','-Command',compress],{windowsHide:true,timeout:30000});
 report.capture.jpeg={path:path.relative(repo,jpeg),sha256:sha(jpeg),bytes:fs.statSync(jpeg).size};check('actual native capture compressed under500KB',report.capture.jpeg.bytes<=500000,report.capture);
 report.finalObservation=await observe();check('captured final native page retains counter one and submitted query',report.finalObservation.text.includes('Clicks: 1')&&report.finalObservation.text.includes('Submitted: native receipt'));
}
async function stop(p){if(p&&p.exitCode===null){const done=new Promise(r=>p.once('exit',r));p.kill();await done;}}
main().catch(e=>{report.error=e.stack;process.exitCode=1;}).finally(async()=>{if(tabId)try{await completed(await successful('tab.close',{tabId}));}catch{}await stop(native);await stop(backend);if(fixture)await new Promise(r=>fixture.close(r));report.finishedAt=new Date().toISOString();report.sourceStable=Object.entries(report.sources).every(([p,h])=>sha(path.join(repo,p))===h);report.cleanup={nativeExited:native?.exitCode!==null||native?.signalCode!==null,backendExited:backend?.exitCode!==null||backend?.signalCode!==null};save();console.log(JSON.stringify({checks:report.checks.map(({name,ok})=>({name,ok})),error:report.error,capture:report.capture,sourceStable:report.sourceStable,cleanup:report.cleanup}));});
