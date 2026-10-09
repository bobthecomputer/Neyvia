// Actual two-backend HTTP -> T16 -> native Windows journey, no mocked driver.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawn, spawnSync} = require('node:child_process');
const crypto = require('node:crypto');
const repo = path.resolve(__dirname,'..'), scratch=path.join(repo,'.agent_control/t19/proof');
const host='http://127.0.0.1:48271', relay='http://127.0.0.1:48279';
const python='C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const checks=[], receipts={}; let driver, apps=[], cookieHost='', cookieRelay='', sequence=0, pending=new Map();
const delay=ms=>new Promise(r=>setTimeout(r,ms));
function check(name,value){assert.ok(value,name);checks.push({name,passed:true});}
async function native(op,args={}){
  const id=String(++sequence);
  return new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Native observation timeout')),25000);pending.set(id,{resolve,reject,timer});driver.stdin.write(JSON.stringify({id,op,args})+'\n');});
}
async function request(base,op,args={},cookie=base===host?cookieHost:cookieRelay, extra={}){
 const response=await fetch(base+'/api/ui/remote',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie,...extra},body:JSON.stringify({op,args})});
 const value=await response.json();return {status:response.status,...value};
}
async function good(base,op,args){const r=await request(base,op,args);assert.equal(r.ok,true,`${op}: ${r.status}/${r.code}`);return r.data;}
async function login(base){const r=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});assert.ok(r.ok);return r.headers.getSetCookie().map(s=>s.split(';')[0]).join('; ');}
async function backend(base,command,payload){const r=await fetch(base+'/api/backend',{method:'POST',headers:{'Content-Type':'application/json',Cookie:base===host?cookieHost:cookieRelay},body:JSON.stringify({command,payload})});return {status:r.status,body:await r.json()};}
async function tool(name,args){const r=await fetch(relay+'/api/ui/tools/call',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookieRelay},body:JSON.stringify({tool:name,arguments:args})});const v=await r.json();assert.equal(v.ok,true,`${name}: ${v.error}`);return v.data;}
async function until(fn,seconds=15){const end=Date.now()+seconds*1000;while(Date.now()<end){const v=await fn();if(v)return v;await delay(100);}throw Error('Timed out waiting for actual native state');}
async function buildApps(){
 fs.mkdirSync(scratch,{recursive:true});
 const source=path.join(repo,'tools/cua-driver-win/remote-probe.cs'), binary=path.join(scratch,'T19NativeProbe.exe');
 const framework='C:/Windows/Microsoft.NET/Framework64/v4.0.30319';
 const build=spawnSync(framework+'/csc.exe',['/nologo','/target:winexe','/out:'+binary,source,'/reference:'+framework+'/System.Windows.Forms.dll','/reference:'+framework+'/System.Drawing.dll'],{windowsHide:true,encoding:'utf8'});
 assert.equal(build.status,0,build.stdout+build.stderr);
 const compiled=spawnSync(python,['-B','-c','from grant_agent.cua_native import NativeWorker; print(NativeWorker.assembly())'],{cwd:repo,env:{...process.env,PYTHONPATH:'src'},windowsHide:true,encoding:'utf8'});
 assert.equal(compiled.status,0,compiled.stderr);
 driver=spawn('powershell.exe',['-NoLogo','-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','Bypass','-File',path.join(repo,'tools/cua-driver-win/driver.ps1'),'-AssemblyPath',compiled.stdout.trim()],{windowsHide:true,stdio:['pipe','pipe','ignore']});
 let buffer='';driver.stdout.setEncoding('utf8');driver.stdout.on('data',chunk=>{buffer+=chunk;while(buffer.includes('\n')){const pos=buffer.indexOf('\n');const r=JSON.parse(buffer.slice(0,pos));buffer=buffer.slice(pos+1);const p=pending.get(r.id);if(p){pending.delete(r.id);clearTimeout(p.timer);r.ok?p.resolve(r.data):p.reject(Error(r.error));}}});
 const before=await native('status');
 for(const [name,mode] of [['allowed',''],['same-app-denied',''],['private','masked'],['large','large']]){
   const state=path.join(scratch,name+'-'+Date.now());const proc=spawn(binary,[state,...(mode?[mode]:[])],{windowsHide:true,stdio:'ignore'});apps.push({proc,state,name});
   await until(()=>fs.existsSync(state));apps.at(-1).windowId=Number(fs.readFileSync(state,'utf8'));
 }
 const after=await native('status');check('Disposable native app compiled and opened without changing foreground or cursor',before.foregroundWindowId===after.foregroundWindowId&&JSON.stringify(before.cursor)===JSON.stringify(after.cursor));
 receipts.probe={sourceSha256:crypto.createHash('sha256').update(fs.readFileSync(source)).digest('hex'),pid:apps[0].proc.pid,windowId:apps[0].windowId};
}
function files(root){if(!fs.existsSync(root))return [];return fs.readdirSync(root,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(root,e.name)):[path.join(root,e.name)]);}
async function main(){
 await buildApps();cookieHost=await login(host);cookieRelay=await login(relay);
 check('Anonymous remote state refused', (await request(host,'state',{},'')).status===401);
 check('Unrelated browser origin refused',(await request(host,'state',{},cookieHost,{Origin:'https://unrelated.invalid'})).status===403);
 check('Unknown peer operations rejected before delegation',(await fetch(host+'/api/ui/remote/peer/driver',{method:'POST',body:'{}'})).status===403);
 check('Public URL cannot become relay target',(await request(relay,'connect',{url:'http://example.com',invite:'x'.repeat(32)})).status===403);
 check('Peer capability checked before reading input body',(await fetch(host+'/api/ui/remote/peer/input',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).status===401);
 check('Oversized redeem body refused',(await fetch(host+'/api/ui/remote/peer/redeem',{method:'POST',headers:{'Content-Type':'application/json'},body:'x'.repeat(65537)})).status===413);
 check('Host enable cannot be requested through peer delegation',(await fetch(host+'/api/ui/remote/peer/enable',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).status===403);
 const member='t19proof'+Date.now(), password=crypto.randomBytes(24).toString('hex');
 assert.equal((await backend(relay,'accounts_update_command',{op:'create',username:member,password})).status,200);
 try {
  const signed=await fetch(relay+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:member,password})});assert.ok(signed.ok);
  const memberCookie=signed.headers.getSetCookie().map(s=>s.split(';')[0]).join('; ');
  check('Real authenticated secondary account denied remote state',(await request(relay,'state',{},memberCookie)).status===403);
  check('Real authenticated secondary account denied remote connect',(await request(relay,'connect',{url:host,invite:'x'.repeat(32)},memberCookie)).status===403);
 } finally {await backend(relay,'accounts_update_command',{op:'remove',username:member});}
 check('Protected native window cannot be enabled',(await request(host,'enable',{windowIds:[apps[2].windowId]})).code==='protected_window');
 const privateTree=await native('inspect',{windowId:String(apps[2].windowId),maxDepth:8,maxNodes:100});
 check('Native password values omitted before any relay',!JSON.stringify(privateTree).includes('DISPOSABLE_MASKED_SENTINEL')&&privateTree.tree.some(e=>e.isPassword&&!('value'in e)));
 const enabled=await good(host,'enable',{windowIds:[apps[0].windowId],minutes:5,name:'T19 proof'}); const sessionId=enabled.session.id;
 receipts.hostEnabled={...enabled.session};check('Host indicator explicitly visible',enabled.session.indicator.visible);
 const indicatorTree=await native('inspect',{windowId:String(enabled.session.indicator.windowId),maxDepth:6,maxNodes:100});
 check('Real native host warning and Stop button present',indicatorTree.tree.some(e=>e.name==='Being controlled remotely')&&indicatorTree.tree.some(e=>e.name==='Stop remote control now'));
 const indicatorCapture=await native('capture',{windowId:String(enabled.session.indicator.windowId)});
 fs.writeFileSync(path.join(repo,'scripts/evidence/T19-host-indicator.png'),Buffer.from(indicatorCapture.pngBase64,'base64'));
 const connected=await good(relay,'connect',{url:host,invite:enabled.invite}); const connectionId=connected.connection.id;
 receipts.connection=connected.connection;
 check('Other backend redeemed explicit one-use consent',connected.connection.sessionId===sessionId);
 check('Consumed invite cannot be replayed',(await request(relay,'connect',{url:host,invite:enabled.invite})).status===401);
 const ordinary=await fetch(host+'/api/ui/cua',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookieHost},body:JSON.stringify({op:'input',args:{sessionId:(await (await fetch(host+'/api/ui/cua/state',{headers:{Cookie:cookieHost}})).json()).data.sessions.find(s=>s.owner?.chatId===sessionId)?.id,windowId:apps[0].windowId,kind:'type_text',text:'bypass denied'}})});
 check('Ordinary CUA route cannot operate remote ephemeral session',ordinary.status===400);
 const bridge=spawnSync(python,['-B','-m','grant_agent.desktop_bridge','--root',path.join(repo,'.agent_control/t19/relay')],{cwd:repo,env:{...process.env,PYTHONPATH:'src',NEYVIA_UI_BACKEND_URL:relay},input:JSON.stringify({command:'remote_state_command',payload:{}}),encoding:'utf8',windowsHide:true});
 assert.equal(bridge.status,0,bridge.stderr);check('Fresh desktop IPC worker forwards to same persistent relay connection',JSON.parse(bridge.stdout).data.connections.some(c=>c.id===connectionId));
 const wrong=spawnSync(python,['-B','-m','grant_agent.desktop_bridge','--root',path.join(repo,'.agent_control/t19/wrong-root')],{cwd:repo,env:{...process.env,PYTHONPATH:'src',NEYVIA_UI_BACKEND_URL:relay},input:JSON.stringify({command:'remote_state_command',payload:{}}),encoding:'utf8',windowsHide:true});
 check('Desktop IPC workspace mismatch fails closed',wrong.status!==0);
 const windows=await good(relay,'windows',{connectionId});
 check('Only exact pinned native window exposed',windows.windows.length===1&&windows.windows[0].window_id===apps[0].windowId);
 const denied=await request(relay,'snapshot',{connectionId,windowId:apps[1].windowId});
 check('Second instance of same allowed executable refused',denied.ok===false);
 check('Private window and all other apps refused',(await request(relay,'snapshot',{connectionId,windowId:apps[2].windowId})).ok===false);
 const snap=await good(relay,'snapshot',{connectionId,windowId:apps[0].windowId});
 const edit=snap.elements.find(e=>e.label==='Task input'&&e.role==='Edit');assert.ok(edit);
 const initialStatus=await native('status');
 const marker='T19 remote owner completed '+crypto.randomBytes(6).toString('hex');
 const input=await good(relay,'input',{connectionId,windowId:apps[0].windowId,kind:'type_text',element_token:edit.element_token,text:marker});
 receipts.input=input;check('Relay input reused T16 log and background native dispatch',input.by==='remote'&&input.result.effect==='confirmed');
 const independently=await native('inspect',{windowId:String(apps[0].windowId),maxDepth:8,maxNodes:100});
 check('Independent native UIA readback confirms other-backend input',independently.tree.some(e=>e.name==='Task input'&&e.value==='initial'+marker));
 const bot=await tool('neyvia.remote.snapshot',{connectionId,windowId:apps[0].windowId});
 check('Model-visible tool reaches same live remote state without durable native receipt',bot.recording===false&&!bot.receipt_path&&bot.result.elements.some(e=>e.value==='initial'+marker));
 const validated=await tool('neyvia.manual.validate',{id:'remote'});
 check('Remote manual validates actual registered tool schemas',validated.result.ok===true);
 const observed=await tool('neyvia.manual.observe',{id:'remote',state:'connections'});
 check('Manual observer is volatile instead of recording connection state',observed.recording===false&&observed.result.recording===false&&observed.result.observed.connections.some(c=>c.id===connectionId));
 const manual=await tool('neyvia.manual.run',{id:'remote',procedure:'observe-allowed-window',inputs:{connectionId,windowId:apps[0].windowId}});
 check('Executable manual reaches the live window and checks it without recording',manual.recording===false&&manual.result.status==='completed'&&manual.result.recording===false&&manual.result.checks.every(c=>c.passed));
 receipts.manual={status:manual.result.status,checks:manual.result.checks.length,recording:manual.result.recording};
 const after=await native('status');check('Remote control preserved foreground and cursor',initialStatus.foregroundWindowId===after.foregroundWindowId&&JSON.stringify(initialStatus.cursor)===JSON.stringify(after.cursor));
 const newer=await good(relay,'snapshot',{connectionId,windowId:apps[0].windowId});
 const button=newer.elements.find(e=>e.label==='Apply');const b=button.screenshot_frame;
 fs.writeFileSync(apps[0].state+'.rename','change harmless label');await delay(250);
 const renamed=await request(relay,'input',{connectionId,windowId:apps[0].windowId,kind:'click',element_token:button.element_token});
 check('Reused UIA control with changed consequential label refused',renamed.ok===false);
 fs.renameSync(apps[0].state+'.rename',apps[0].state+'.rename-complete');await delay(250);
 const freshAfterRename=await good(relay,'snapshot',{connectionId,windowId:apps[0].windowId});
 const click=await good(relay,'input',{connectionId,windowId:apps[0].windowId,kind:'click',captureId:freshAfterRename.capture_id,x:Math.round(b.x+b.w/2),y:Math.round(b.y+b.h/2)});
 check('Interactive preview pixel click applied real native app result',click.by==='remote'&&await until(()=>fs.existsSync(apps[0].state+'.result')&&fs.readFileSync(apps[0].state+'.result','utf8')==='Applied: initial'+marker));
 const frame=await fetch(relay+`/api/ui/remote/frame?connectionId=${connectionId}&windowId=${apps[0].windowId}`,{headers:{Cookie:cookieRelay}});
 const bytes=Buffer.from(await frame.arrayBuffer());
 check('Second backend returns real PNG with shared capture binding',frame.ok&&bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))&&frame.headers.get('X-Capture-Id')&&frame.headers.get('Cache-Control')==='no-store');
 receipts.frame={bytes:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),captureId:frame.headers.get('X-Capture-Id')};
 fs.writeFileSync(path.join(repo,'scripts/evidence/T19-remote-frame.png'),bytes);
 check('Sensitive/global keyboard shortcut denied',(await request(relay,'input',{connectionId,windowId:apps[0].windowId,kind:'hotkey',keys:['CTRL','L']})).ok===false);
 check('Enter is never forwarded to a credential or submit dialog',(await request(relay,'input',{connectionId,windowId:apps[0].windowId,kind:'press_key',element_token:edit.element_token,key:'Enter'})).code==='key_not_allowed');
 const log=await good(relay,'log',{connectionId});receipts.log=log;
 check('Shared remote log contains no typed content or native readbacks',log.entries.some(e=>e.by==='remote')&&!JSON.stringify(log).includes(marker)&&log.entries.every(e=>Object.keys(e.args||{}).length===0));
 fs.writeFileSync(apps[0].state+'.protect','enable masked control');await delay(250);
 check('Protected control appearing after consent blocks observation',(await request(relay,'snapshot',{connectionId,windowId:apps[0].windowId})).code==='protected_window');
 check('Protected control appearing after consent blocks frame',(await fetch(relay+`/api/ui/remote/frame?connectionId=${connectionId}&windowId=${apps[0].windowId}`,{headers:{Cookie:cookieRelay}})).status===409);
 check('Protected control appearing after consent blocks input',(await request(relay,'input',{connectionId,windowId:apps[0].windowId,kind:'type_text',element_token:edit.element_token,text:'should never arrive'})).code==='protected_window');
 const stoppedAt=Date.now();await good(host,'kill',{sessionId});
 const killed=await request(relay,'snapshot',{connectionId,windowId:apps[0].windowId});
 check('Host kill revokes already connected backend immediately',killed.ok===false&&['capability_invalid','session_stopped'].includes(killed.code));
 receipts.kill={elapsedMs:Date.now()-stoppedAt,refusal:killed.code};
 check('Killed session cannot forward another input',(await request(relay,'input',{connectionId,windowId:apps[0].windowId,kind:'type_text',element_token:edit.element_token,text:'blocked after stop'})).ok===false);
 fs.renameSync(apps[0].state+'.protect',apps[0].state+'.protected-complete');await delay(250);
 const second=await good(host,'enable',{windowIds:[apps[0].windowId],minutes:5,name:'T19 native Stop proof'});
 const secondConn=(await good(relay,'connect',{url:host,invite:second.invite})).connection;
 const stopTree=await native('inspect',{windowId:String(second.session.indicator.windowId),maxDepth:6,maxNodes:100});
 const stopElement=stopTree.tree.find(e=>e.name==='Stop remote control now');
 await native('action',{windowId:String(second.session.indicator.windowId),elementId:stopElement.id,action:'buttonClick'});
 await until(async()=>!(await request(relay,'windows',{connectionId:secondConn.id})).ok);
 check('Native host Stop button revokes live relay without browser UI',true);
 const big=await good(host,'enable',{windowIds:[apps[3].windowId],minutes:5,name:'T19 scaled-window proof'});
 const bigConnection=(await good(relay,'connect',{url:host,invite:big.invite})).connection.id;
 const bigSnap=await good(relay,'snapshot',{connectionId:bigConnection,windowId:apps[3].windowId});
 check('Large native window uses T16 bounded preview geometry',bigSnap.screenshot_width===1600&&bigSnap.screenshot_scale<1);
 const bigButton=bigSnap.elements.find(e=>e.label==='Apply').screenshot_frame;
 await good(relay,'input',{connectionId:bigConnection,windowId:apps[3].windowId,kind:'click',captureId:bigSnap.capture_id,x:Math.round(bigButton.x+bigButton.w/2),y:Math.round(bigButton.y+bigButton.h/2)});
 check('Scaled preview coordinates click the real native control',await until(()=>fs.existsSync(apps[3].state+'.result')&&fs.readFileSync(apps[3].state+'.result','utf8')==='Applied: initial'));
 const bigFrame=await fetch(relay+`/api/ui/remote/frame?connectionId=${bigConnection}&windowId=${apps[3].windowId}`,{headers:{Cookie:cookieRelay}});
 const bigBytes=Buffer.from(await bigFrame.arrayBuffer());check('Large-window PNG is actually 1600 pixels wide',bigFrame.ok&&bigBytes.readUInt32BE(16)===1600);
 fs.writeFileSync(path.join(repo,'scripts/evidence/T19-scaled-frame.png'),bigBytes);
 await good(host,'kill',{sessionId:big.session.id});
 const records=files(path.join(repo,'.agent_control/t19/host/.neyvia/cua')).concat(files(path.join(repo,'.agent_control/t19/relay/.neyvia/cua')));
 check('Default session created zero frame/transcript/session files',records.length===0);
 const disk=files(path.join(repo,'.agent_control/t19/host')).concat(files(path.join(repo,'.agent_control/t19/relay'))).filter(p=>!p.endsWith('.sqlite3')&&!p.endsWith('.sqlite3-wal')&&!p.endsWith('.sqlite3-shm'));
 check('Typed remote marker absent from all host/relay file payloads',disk.every(p=>!fs.readFileSync(p).includes(Buffer.from(marker))));
 receipts.storage={cuaFiles:records.length,recording:false};
}
main().then(()=>{fs.writeFileSync(path.join(repo,'scripts/evidence/T19.json'),JSON.stringify({schema:'neyvia.T19.two-backend-native-proof.v1',at:new Date().toISOString(),passed:true,checks,receipts,boundary:{host,relay,separateRoots:true,network:'explicit loopback stand-in, no Tailscale configuration/read',target:'disposable real Windows Forms app',renderedProductUI:false,realSecondPC:false}},null,2)+'\n');console.log(JSON.stringify({passed:true,checks:checks.length}));}).catch(e=>{fs.writeFileSync(path.join(repo,'scripts/evidence/T19.json'),JSON.stringify({schema:'neyvia.T19.two-backend-native-proof.v1',at:new Date().toISOString(),passed:false,checks,receipts,error:e.message},null,2)+'\n');console.error(e.message);process.exitCode=1;}).finally(async()=>{try{if(cookieHost)await request(host,'kill',{});}catch{}for(const a of apps)a.proc.kill();if(driver){driver.stdin.end();setTimeout(()=>driver.kill(),1000).unref();}});
