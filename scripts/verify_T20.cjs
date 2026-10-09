/* Real owned HTTP + native WebView2 journeys. No pytest or simulated runtime. */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {spawn, spawnSync} = require('node:child_process');
const repo = path.resolve(__dirname, '..');
const python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const integrationProof = process.env.T20_PROOF_SCOPE === 'INT6';
function proofPort(name, fallback) {
  if(!process.env[name]) return fallback;
  const value=Number(process.env[name]);
  if(!integrationProof||!Number.isInteger(value)||value<48351||value>48359) throw Error(`${name} requires INT6 ports 48351–48359.`);
  return value;
}
const backendPort=proofPort('T20_BACKEND_PORT',48321), fixturePort=proofPort('T20_FIXTURE_PORT',48323), headlessPort=proofPort('T20_HEADLESS_PORT',48324);
if(new Set([backendPort,fixturePort,headlessPort]).size!==3) throw Error('Browser proof ports must differ.');
const root = path.join(repo, integrationProof?'.agent_control/INT6':'.agent_control/T20', 'browser-proof-' + Date.now());
const base = 'http://127.0.0.1:'+backendPort;
const fixtureBase = 'http://127.0.0.1:'+fixturePort;
const nativePath = process.env.T20_NATIVE_EXE || path.join(repo, 'src-tauri/target/browser-probe/debug/browser-proof.exe');
const output = path.resolve(process.env.T20_EVIDENCE || path.join(repo, 'scripts/evidence/T20.json'));
if(path.relative(repo,output).startsWith('..')) throw Error('Proof receipt must remain in this worktree.');
const env = {...process.env, PYTHONPATH:path.join(repo,'src'), NEYVIA_UI_BACKEND_URL:base,
  NEYVIA_OBSCURA_EXE:process.env.NEYVIA_OBSCURA_EXE||path.join(repo,'.agent_control/T20/obscura-v0.2.3/bin/obscura.exe'),
  NEYVIA_BROWSER_PROOF_SCOPE:integrationProof?'INT6':'T20',
  ...(integrationProof?{NEYVIA_BROWSER_PROOF_PORTS:[backendPort,fixturePort,headlessPort].join(',')}:{}),
  NEYVIA_UI_STATE_ROOT:root, NEYVIA_CONNECTED_SERVICE_PORT:String(backendPort), NEYVIA_COORDINATOR_AUTOSTART:'0',
  FLUXIO_WATCHDOG_AUTOSTART:'0', NEYVIA_TOOL_AUTO_UPDATE:'0'};
let server, native, fixture, cookie = '', token;const fixtureRequests=[];let slowActive=0,slowPeak=0;
const receipt = {track:'T20',startedAt:new Date().toISOString(),root,ports:[backendPort,fixturePort,headlessPort],checks:[],journeys:[],
  boundary:'Actual Tauri 2 child WebView2 tabs and real authenticated backend; Arc-like UI belongs to Claude.',
  missing:['Arc-like UI rendered journey (Claude)', 'LAYA provider (explicit unavailable hook)', 'NAS sync (Tailscale/port exclusion)', 'Cross-origin frames/canvas/closed shadow DOM', 'Vault, extensions, private tabs, shield/reader/PiP, full browser permissions UI', 'Download size enforcement beyond this tiny proof', 'Physical user-input takeover path (implementation present, semantic proof only)']};
const sleep = ms=>new Promise(r=>setTimeout(r,ms));
const hash = file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const sanitize = value=>JSON.parse(JSON.stringify(value,(k,v)=>/token|password/i.test(k)?'[masked]':v));
function save(){fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(receipt,null,2)+'\n');}
async function request(route,body,auth=true){
  const started=Date.now();
  const response=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...(auth&&cookie?{Cookie:cookie}:{})},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(45000)});
  const data=await response.json();receipt.journeys.push({route,request:sanitize(body||{}),status:response.status,ms:Date.now()-started,response:sanitize(data)});
  return {status:response.status,data,response};
}
async function login(){const r=await request('/api/auth/local-session',{},false);assert.equal(r.status,200);cookie=r.response.headers.get('set-cookie').split(';')[0];}
async function browser(op,args={}){const r=await request('/api/ui/browser',{op,args});assert.equal(r.status,200,JSON.stringify(r.data));assert.equal(r.data.ok,true);return r.data;}
async function check(name,fn){const began=Date.now();try{const detail=await fn();receipt.checks.push({name,ok:true,ms:Date.now()-began,detail});save();}catch(e){receipt.checks.push({name,ok:false,ms:Date.now()-began,error:e.stack});save();throw e;}}
async function eventual(fn,timeout=25000){const end=Date.now()+timeout;while(Date.now()<end){const value=await fn();if(value)return value;await sleep(150);}throw Error('Expected runtime transition timed out');}
async function completed(row){if(!row.actionId)return row;return eventual(async()=>{const r=await browser('action.get',{actionId:row.actionId});if(r.status==='failed')throw Error('Native failed: '+JSON.stringify(r));return r.status==='done'?r:false;});}
async function observe(tabId){return eventual(async()=>{const row=await completed(await browser('observe',{tabId}));return row.result.observation?.readyState==='complete'?row.result.observation:false;});}
function unwrap(row){assert.notEqual(row?.ok,false,JSON.stringify(row));while(row&&row.result){row=row.result;assert.notEqual(row?.ok,false,JSON.stringify(row));}return row;}
async function tool(name,args={}){const r=await request('/api/ui/tools/call',{tool:'neyvia.'+name,arguments:args});assert.equal(r.status,200,JSON.stringify(r));return unwrap(r.data.data);}
function desktop(command,payload){const r=spawnSync(python,['-m','grant_agent.desktop_bridge','--root',root],{cwd:repo,env,windowsHide:true,input:JSON.stringify({command,payload}),encoding:'utf8',timeout:60000});assert.equal(r.status,0,r.stderr);const answer=JSON.parse(r.stdout);receipt.journeys.push({desktop:command,payload:sanitize(payload),response:sanitize(answer)});assert.notEqual(answer.ok,false,JSON.stringify(answer));return answer.data||answer;}
async function free(port){try{await fetch('http://127.0.0.1:'+port,{signal:AbortSignal.timeout(500)});throw Error('Assigned port already occupied: '+port);}catch(e){if(e.message.includes('occupied'))throw e;}}
async function startBackend(){await free(backendPort);fs.mkdirSync(root,{recursive:true});const log=fs.openSync(path.join(root,'backend-'+Date.now()+'.log'),'a');server=spawn(python,['scripts/run_web_backend.py','--host','127.0.0.1','--port',String(backendPort),'--root',root,'--skip-runtime-auto-update'],{cwd:repo,env,windowsHide:true,stdio:['ignore',log,log]});fs.closeSync(log);await eventual(async()=>{if(server.exitCode!==null)throw Error('Backend exited '+server.exitCode);try{return (await fetch(base+'/api/health',{signal:AbortSignal.timeout(700)})).ok;}catch{return false;}},60000);await login();}
async function kill(child){if(child&&child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.kill();});}
async function startNative(){assert.ok(fs.existsSync(nativePath),'Native binary unavailable: '+nativePath);const grant=await browser('runtime.connect');token=grant.token;const log=fs.openSync(path.join(root,'native-'+Date.now()+'.log'),'a');native=spawn(nativePath,[],{cwd:repo,env:{...env,NEYVIA_BROWSER_BASE:base,NEYVIA_BROWSER_TOKEN:token},windowsHide:true,stdio:['ignore',log,log]});fs.closeSync(log);await eventual(async()=>{if(native.exitCode!==null)throw Error('Native exited '+native.exitCode);const state=await browser('state');const visible=new Set([state.activeTabId,state.peekTabId,...Object.values(state.split||{})]);return state.tabs.filter(t=>visible.has(t.id)).every(t=>t.live)?state:false;},45000);}
function page(url,req){
  const cookieValue=(req.headers.cookie||'').replace(/</g,'&lt;');
  return `<!doctype html><meta charset="utf-8"><title>T20 ${url.pathname}</title><style>body{font:20px system-ui;background:#f5f8f4;color:#173622;padding:36px}input,button,select{font:inherit;margin:8px;padding:10px}#result{margin:20px}</style><h1>Shared native browser</h1><p id="location">${url.pathname}</p><label>Name<input id="name" aria-label="Name"></label><button id="save" onclick="document.getElementById('result').textContent='Saved: '+document.getElementById('name').value">Save</button><p id="result">Waiting</p><label>Secret<input type="password" value="T20-private-canary" aria-label="Secret"></label><label>Theme<select aria-label="Theme" onchange="document.getElementById('result').textContent='Theme: '+this.value"><option>Calm</option><option>Forest</option></select></label><a href="/second">Second page</a><a href="/download" download="proof.txt">Download proof</a><a href="/popup" target="_blank">Open popup tab</a><button onclick="document.getElementById('result').textContent='Changed outside agent'">Change page</button><pre id="cookie">Cookie: ${cookieValue}</pre><p id="storage"></p><p id="ipc">IPC isolation pending</p><script>
  if(location.pathname==='/headless')localStorage.setItem('t20-work','obscura task');document.getElementById('storage').textContent='Storage: '+localStorage.getItem('t20-work');
  if(window.__TAURI_INTERNALS__)Promise.all(['get_overlay_state','browser_runtime_stop','plugin:process|exit'].map(command=>window.__TAURI_INTERNALS__.invoke(command).then(()=>command+':ALLOWED',()=>command+':denied'))).then(rows=>document.getElementById('ipc').textContent=rows.join(' '));
  if(location.pathname==='/mutable')setTimeout(()=>document.getElementById('result').textContent='Changed after observation',1800);
  </script>`;
}
async function startFixture(){await free(fixturePort);fixture=http.createServer((req,res)=>{const url=new URL(req.url,fixtureBase);fixtureRequests.push({path:url.pathname,userAgent:req.headers['user-agent'],at:Date.now()});if(url.pathname==='/download'){const body=Buffer.from('T20 actual WebView2 download\n');res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Disposition':'attachment; filename="proof.txt"','Content-Length':body.length});res.end(body);return;}if(url.pathname==='/cookie-set'||url.pathname==='/headless'){res.setHeader('Set-Cookie','t20=shared-profile; Path=/; SameSite=Lax');}res.setHeader('Content-Type','text/html; charset=utf-8');if(url.pathname.startsWith('/parallel')){slowActive++;slowPeak=Math.max(slowPeak,slowActive);setTimeout(()=>{slowActive--;res.end(page(url,req));},1600);}else res.end(page(url,req));});await new Promise((resolve,reject)=>fixture.once('error',reject).listen(fixturePort,'127.0.0.1',resolve));}
async function main(){
  await startFixture();await startBackend();let tab1,tab2,tab3,space;
  await check('Anonymous and secondary account cannot access browser state or runtime grants',async()=>{
    assert.equal((await request('/api/ui/browser',undefined,false)).status,401);
    assert.equal((await request('/api/ui/browser/runtime',{op:'poll',token:'invalid'},false)).status,403);
    const foreign=await fetch(base+'/api/ui/browser',{method:'POST',headers:{Cookie:cookie,Origin:fixtureBase,'Content-Type':'application/json'},body:JSON.stringify({op:'runtime.connect'})});assert.equal(foreign.status,403);
    const password=crypto.randomBytes(18).toString('hex');const created=await request('/api/backend',{command:'accounts_update_command',payload:{op:'create',username:'T20guest',password}});assert.equal(created.status,200);
    const owner=cookie;const guest=await request('/api/auth/login',{username:'T20guest',password},false);assert.equal(guest.status,200);cookie=guest.response.headers.get('set-cookie').split(';')[0];
    try{assert.equal((await request('/api/ui/browser')).status,403);assert.equal((await request('/api/backend',{command:'browser_state_command',payload:{}})).status,403);}finally{cookie=owner;}
  });
  await check('Persistent profiles/spaces/tabs exist before native runtime without claiming load',async()=>{
    const profile=await browser('profile.create',{name:'Research'});space=await browser('space.create',{name:'Research',profileId:profile.id});
    tab1=(await tool('browser.open',{url:fixtureBase+'/first',pinned:true})).tabId;
    const state=await browser('state');assert.equal(state.runtime.connected,false);assert.equal(state.tabs[0].live,false);
    const bad=await request('/api/ui/browser',{op:'tab.open',args:{url:'file:///C:/Windows'}});assert.equal(bad.status,400);
  });
  await check('Actual Tauri child WebView2 opens and renders shared native tab',async()=>{
    await startNative();await completed(await browser('layout',{tabs:[{tabId:tab1,x:0,y:0,width:1200,height:730,visible:true}]}));
    const obs=await observe(tab1);assert.match(obs.text,/Shared native browser/);assert.match(obs.text,/get_overlay_state:denied/);assert.match(obs.text,/browser_runtime_stop:denied/);assert.match(obs.text,/plugin:process\|exit:denied/);assert.ok(!JSON.stringify(obs).includes('T20-private-canary'));
    return {tabId:tab1,revision:obs.revision,title:obs.title,secretRedacted:true,childPrivilegedIpcDenied:true};
  });
  await check('Owner grant + agent fills and clicks actual shared DOM, then user state changes',async()=>{
    let obs=await tool('browser.observe',{tabId:tab1});const name=obs.elements.find(e=>e.name==='Name');
    const denied=await request('/api/ui/browser',{op:'action',args:{tabId:tab1,revision:obs.revision,element:name.id,action:'fill',value:'Paul'}});assert.equal(denied.data.error.code,'tab_not_granted');
    await browser('tab.grant',{tabId:tab1,enabled:true});await completed(await tool('browser.action',{tabId:tab1,revision:obs.revision,element:name.id,action:'fill',value:'Paul'}));
    obs=await tool('browser.observe',{tabId:tab1});const save=obs.elements.find(e=>e.name==='Save');await completed(await tool('browser.action',{tabId:tab1,revision:obs.revision,element:save.id,action:'click'}));
    const final=await tool('browser.observe',{tabId:tab1});assert.match(final.text,/Saved: Paul/);const secret=final.elements.find(e=>e.secret);assert.deepEqual(secret.actions,[]);
    assert.equal((await request('/api/ui/browser',{op:'action',args:{tabId:tab1,revision:final.revision,element:secret.id,action:'fill',value:'bad'}})).data.error.code,'invalid_target');
    return {saved:final.text.includes('Saved: Paul')};
  });
  await check('Stale page observation and revoked grant fail before effect',async()=>{
    const obs=await observe(tab1);const old=obs.revision;await completed(await browser('tab.navigate',{tabId:tab1,url:fixtureBase+'/mutable'}));
    await eventual(async()=>{try{return (await observe(tab1)).url.endsWith('/mutable');}catch{return false;}});await sleep(2200);
    await browser('tab.grant',{tabId:tab1,enabled:true});
    const stale=await request('/api/ui/browser',{op:'action',args:{tabId:tab1,revision:old,element:'0',action:'click'}});assert.equal(stale.data.error.code,'stale_projection');
    await browser('tab.grant',{tabId:tab1,enabled:false});const now=await observe(tab1);const revoked=await request('/api/ui/browser',{op:'action',args:{tabId:tab1,revision:now.revision,element:now.elements.find(e=>e.name==='Save').id,action:'click'}});assert.equal(revoked.data.error.code,'tab_not_granted');
  });
  await check('Multiple real tabs, split layout and profile cookie isolation',async()=>{
    await completed(await browser('tab.navigate',{tabId:tab1,url:fixtureBase+'/cookie-set'}));await eventual(async()=>{try{return (await observe(tab1)).url.endsWith('/cookie-set');}catch{return false;}});
    tab2=(await browser('tab.open',{url:fixtureBase+'/second'})).tabId;await eventual(async()=>{const s=await browser('state');return s.tabs.find(t=>t.id===tab2)?.live;});
    tab3=(await browser('tab.open',{url:fixtureBase+'/isolated',spaceId:space.id})).tabId;await eventual(async()=>{const s=await browser('state');return s.tabs.find(t=>t.id===tab3)?.live;});
    await browser('split',{left:tab1,right:tab2});await completed(await browser('layout',{tabs:[{tabId:tab1,x:0,y:0,width:600,height:730,visible:true},{tabId:tab2,x:600,y:0,width:600,height:730,visible:true},{tabId:tab3,x:0,y:0,width:600,height:730,visible:false}]}));
    assert.match((await observe(tab2)).text,/t20=shared-profile/);assert.ok(!(await observe(tab3)).text.includes('t20=shared-profile'));
    const state=await browser('state');assert.equal(state.tabs.length,3);assert.equal(state.tabs.find(t=>t.id===tab1).pinned,true);assert.deepEqual(state.split,{left:tab1,right:tab2});
    await browser('peek',{tabId:tab3});assert.equal((await browser('state')).peekTabId,tab3);
    return {tabs:state.tabs.map(t=>({id:t.id,profileId:t.profileId})),sharedCookie:true,isolatedCookie:true};
  });
  await check('T18 compact perception handles/diffs use the same live tab; LAYA unavailable is explicit',async()=>{
    const first=await tool('perception.observe',{layer:'browser',source:{tabId:tab2}});assert.ok(first.handle);const second=await tool('perception.observe',{layer:'browser',source:{tabId:tab2},previousHandle:first.handle});assert.ok(second.handle);
    const decision=await tool('browser.decide',{tabId:tab2,question:'Is the page loaded?'});assert.equal(decision.available,false);assert.equal(decision.decision,null);return {first,second,decision};
  });
  await check('Real native download saved, hashed and exposed through bot/UI shared state',async()=>{
    await browser('tab.grant',{tabId:tab2,enabled:true});const obs=await observe(tab2);const link=obs.elements.find(e=>e.name==='Download proof');await completed(await tool('browser.action',{tabId:tab2,revision:obs.revision,element:link.id,action:'click'}));
    const row=await eventual(async()=>{const r=await browser('downloads');return r.downloads.find(d=>d.status==='completed');});assert.equal(fs.readFileSync(row.path,'utf8'),'T20 actual WebView2 download\n');assert.equal(row.sha256,hash(row.path));return {path:row.path,bytes:row.bytes,sha256:row.sha256};
  });
  await check('Real history/back/forward/reload and fresh desktop worker see the same tabs',async()=>{
    await completed(await browser('tab.navigate',{tabId:tab2,url:fixtureBase+'/third'}));await eventual(async()=>{try{return (await observe(tab2)).url.endsWith('/third');}catch{return false;}});
    await completed(await browser('tab.back',{tabId:tab2}));await eventual(async()=>{try{return (await observe(tab2)).url.endsWith('/second');}catch{return false;}});
    await completed(await browser('tab.forward',{tabId:tab2}));await eventual(async()=>{try{return (await observe(tab2)).url.endsWith('/third');}catch{return false;}});
    await completed(await browser('tab.reload',{tabId:tab2}));assert.ok((await browser('history')).history.some(h=>h.url.endsWith('/third')));
    const shared=desktop('browser_state_command',{});assert.equal(shared.tabs.length,3);
    const wrong=await request('/api/ui/browser',{op:'state',_expectedStateRoot:root+'-wrong'});assert.equal(wrong.status,409);
  });
  await check('Actual non-stealth Obscura engine executes a headless agent task through shared tools and T18',async()=>{
    const engine=await browser('headless.start',{port:headlessPort,allowLocalFixtures:true});assert.equal(engine.stealth,false);
    const profile=await browser('profile.create',{name:'Agent task'});const headlessSpace=await browser('space.create',{name:'Agent task',profileId:profile.id});
    const tab=(await tool('browser.open',{url:fixtureBase+'/headless',spaceId:headlessSpace.id,engine:'obscura'})).tabId;receipt.headlessTabId=tab;
    let obs=await tool('browser.observe',{tabId:tab});assert.equal(obs.engine,'obscura');assert.equal(obs.automation.webdriver,true);assert.match(obs.automation.userAgent,/NeyviaAgent.*Automation/);assert.ok(!JSON.stringify(obs).includes('T20-private-canary'));
    await browser('tab.grant',{tabId:tab,enabled:true});const name=obs.elements.find(e=>e.name==='Name');await tool('browser.action',{tabId:tab,revision:obs.revision,element:name.id,action:'fill',value:'Headless Paul'});
    obs=await tool('browser.observe',{tabId:tab});await tool('browser.action',{tabId:tab,revision:obs.revision,element:obs.elements.find(e=>e.name==='Save').id,action:'click'});
    const done=await tool('browser.observe',{tabId:tab});assert.match(done.text,/Saved: Headless Paul/);const perception=await tool('perception.observe',{layer:'browser',source:{tabId:tab}});assert.ok(perception.handle);
    const actualRequest=fixtureRequests.find(r=>r.path==='/headless'&&r.userAgent.includes('NeyviaAgent'));assert.ok(actualRequest);
    return {engine,tabId:tab,webdriver:true,actualRequest,perceptionHandle:perception.handle};
  });
  await check('Obscura profile workers fetch concurrently without stealth or a substituted browser',async()=>{
    const a=await browser('profile.create',{name:'Parallel A'}),b=await browser('profile.create',{name:'Parallel B'});
    const sa=await browser('space.create',{name:'Parallel A',profileId:a.id}),sb=await browser('space.create',{name:'Parallel B',profileId:b.id});
    const tabs=await Promise.all([tool('browser.open',{url:fixtureBase+'/parallel-a',spaceId:sa.id,engine:'obscura'}),tool('browser.open',{url:fixtureBase+'/parallel-b',spaceId:sb.id,engine:'obscura'})]);assert.ok(slowPeak>=2,'Real fixture requests did not overlap');
    for(const tab of tabs)await browser('tab.close',{tabId:tab.tabId});return {peakConcurrentFixtureRequests:slowPeak,requests:fixtureRequests.filter(r=>r.path.startsWith('/parallel'))};
  });
  await check('Obscura task promotes to same real visible tab with cookies/storage/non-secret form state',async()=>{
    const tab=receipt.headlessTabId;const promotion=await tool('browser.promote',{tabId:tab});await completed(promotion);
    await completed(await browser('layout',{tabs:[{tabId:tab1,x:0,y:0,width:600,height:730,visible:false},{tabId:tab2,x:0,y:0,width:600,height:730,visible:false},{tabId:tab,x:0,y:0,width:1200,height:730,visible:true}]}));
    const obs=await observe(tab);assert.equal(obs.elements.find(e=>e.name==='Name').value,'Headless Paul');assert.match(obs.text,/t20=shared-profile/);assert.match(obs.text,/Storage: obscura task/);
    const state=await browser('state');const visible=state.tabs.find(t=>t.id===tab);assert.equal(visible.engine,'webview2');assert.equal(visible.agentGranted,false);
    const action=await browser('action.get',{actionId:promotion.actionId});assert.ok(!JSON.stringify(action).includes('importState'));
    const capture=await completed(await tool('browser.capture',{tabId:tab}));assert.equal(fs.readFileSync(capture.result.path).subarray(1,4).toString(),'PNG');
    const screenshot=integrationProof?path.join(path.dirname(output),'INT6-promoted-page.png'):path.join(repo,'scripts/evidence/T20-promoted-page.png');fs.copyFileSync(capture.result.path,screenshot);
    await completed(await browser('tab.close',{tabId:tab}));await browser('headless.stop');
    return {sameTabId:tab,cookieTransferred:true,formTransferred:true,storageTransferred:true,screenshot,sha256:hash(screenshot),boundary:promotion.boundary};
  });
  await check('Popup opens a canonical ungranted tab in the same profile instead of an uncontrolled window',async()=>{
    await browser('tab.grant',{tabId:tab2,enabled:true});const obs=await observe(tab2);const link=obs.elements.find(e=>e.name==='Open popup tab');
    await completed(await tool('browser.action',{tabId:tab2,revision:obs.revision,element:link.id,action:'click'}));
    const popup=await eventual(async()=>{const s=await browser('state');return s.tabs.find(t=>t.url.endsWith('/popup')&&t.live);});const parent=(await browser('state')).tabs.find(t=>t.id===tab2);
    assert.equal(popup.profileId,parent.profileId);assert.equal(popup.agentGranted,false);await completed(await browser('tab.close',{tabId:popup.id}));return {tabId:popup.id,profileId:popup.profileId,agentGranted:false};
  });
  await check('Actual native/backend restart restores tab IDs, profile cookies, history/downloads; grants revoked',async()=>{
    await browser('peek',{tabId:null});await browser('tab.activate',{tabId:tab2});
    await kill(native);native=null;await kill(server);server=null;await sleep(1200);await startBackend();
    const saved=await browser('state');assert.equal(saved.tabs.length,3);assert.ok(saved.tabs.every(t=>!t.live&&!t.agentGranted));assert.ok(saved.downloads.some(d=>d.status==='completed'));await startNative();
    await completed(await browser('layout',{tabs:[{tabId:tab2,x:0,y:0,width:1200,height:730,visible:true}]}));const obs=await observe(tab2);assert.match(obs.text,/t20=shared-profile/);assert.equal((await browser('state')).tabs.find(t=>t.id===tab1).pinned,true);
    assert.equal((await browser('state')).tabs.find(t=>t.id===tab3).status,'suspended');
    await completed(await browser('tab.activate',{tabId:tab3}));assert.match((await observe(tab3)).text,/Shared native browser/);
    await completed(await browser('tab.close',{tabId:tab3}));assert.equal((await browser('state')).tabs.length,2);assert.equal((await request('/api/ui/browser',{op:'observe',args:{tabId:tab3}})).data.error.code,'unknown_tab');
    return {restoredTabIds:saved.tabs.map(t=>t.id),grantsRevoked:true,cookiePersisted:true};
  });
  await check('Executable grounded browser manual runs against the real native tab',async()=>{
    const manual=await tool('manual.validate',{id:'browser'});assert.ok(manual);
    const run=await tool('manual.run',{id:'browser',chapter:'backend',procedure:'observe-tab',inputs:{tabId:tab2}});assert.equal(run.status,'completed');return {manual,run};
  });
  receipt.ok=true;receipt.finishedAt=new Date().toISOString();receipt.native={path:nativePath,sha256:hash(nativePath)};receipt.sourceHashes={};
  for(const file of ['src/grant_agent/neyvia_browser.py','src/grant_agent/browser_obscura.py','src/grant_agent/neyvia_workspace_tools.py','src/grant_agent/neyvia_ui_api.py','src/grant_agent/neyvia_perception.py','src/grant_agent/desktop_bridge.py','src/grant_agent/web_backend.py','src/grant_agent/native_tools.py','src/grant_agent/local_network_policy.py','src-tauri/src/browser_runtime.rs','src-tauri/src/browser_projection.js','src-tauri/src/lib.rs','scripts/browser-probe/src/main.rs','src-tauri/Cargo.toml','src-tauri/Cargo.lock','scripts/browser-probe/Cargo.toml','scripts/browser-probe/Cargo.lock','scripts/browser-probe/build.rs','scripts/browser-probe/tauri.conf.json','scripts/browser-probe/capabilities/default.json','src-tauri/capabilities/default.json','src-tauri/capabilities/desktop.json','config/neyvia_manuals.json','config/browser.manual.contract.json','manuals/browser.manual.json','plugins/neyvia/mcp/neyvia_mcp.py','scripts/verify_T20.cjs','scripts/prepare_T20_obscura.cjs','scripts/build_T20_browser_manual.py'])receipt.sourceHashes[file]=hash(path.join(repo,file));save();
}
main().catch(e=>{receipt.ok=false;receipt.error=e.stack;save();console.error(e.stack);process.exitCode=1;}).finally(async()=>{try{if(server&&server.exitCode===null)await browser('headless.stop');}catch{}await kill(native);await kill(server);if(fixture)await new Promise(r=>fixture.close(r));receipt.ownedProcessesStopped=true;save();});
