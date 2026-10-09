// Real isolated backend + native Babylon journeys. No editor mocks.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn,spawnSync} from 'node:child_process';
const base='http://127.0.0.1:48261', root=process.cwd();
const receiptPath=path.join(root,'scripts/evidence/T12.json');
const project=path.join(root,'.agent_control/t12/proof-'+Date.now());fs.mkdirSync(project,{recursive:true});
const createRequest='T12-create-room-'+path.basename(project);
const receipt={track:'T12',at:new Date().toISOString(),base,project,boundary:'Real backend and Babylon NullEngine semantic journey; no rendered browser or native editor claim.',checks:[],journeys:[],limitations:[],sourceHashes:{}};
let cookie='', worker;
async function request(url,body,anonymous=false){const res=await fetch(base+url,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',...(cookie&&!anonymous?{Cookie:cookie}:{})},...(body?{body:JSON.stringify(body)}:{})});const set=res.headers.get('set-cookie');if(set&&!anonymous)cookie=set.split(';')[0];const value=await res.json();return {httpStatus:res.status,...value};}
async function command(op,payload={}){const r=await request('/api/backend',{command:'gamedev_'+op+'_command',payload});if(!r.ok)throw Error(r.error||JSON.stringify(r));return r.data;}
function check(name,passed,observed){receipt.checks.push({name,passed,observed});if(!passed)throw Error(name+' failed: '+JSON.stringify(observed));}
async function failure(name,op,payload){const r=await request('/api/backend',{command:'gamedev_'+op+'_command',payload});check(name,!r.ok,r);}
async function done(action,args={},expected='succeeded',id){const queued=await command('action',{sessionId:worker.sessionId,action,args,...(id?{requestId:id}:{})});const start=Date.now();let result;do{result=await command('receipt',{requestId:queued.requestId});if(!['queued','running'].includes(result.status))break;await new Promise(r=>setTimeout(r,150));}while(Date.now()-start<25000);check(action+' '+expected,result.status===expected,{requestId:result.requestId,status:result.status,error:result.error});receipt.journeys.push(result);return result;}
async function startWorker(websocket=false){
 const process=spawn('node',['scripts/gamedev/native-scene.cjs',project,...(websocket?['--websocket']:[])],{cwd:root,stdio:['ignore','pipe','pipe']});const logs=[];process.stderr.on('data',b=>logs.push(String(b)));const ready=new Promise((resolve,reject)=>{let text='';process.stdout.on('data',b=>{text+=b;for(const line of text.split('\n')){try{const row=JSON.parse(line);if(row.sessionId)resolve(row);}catch{}}});process.on('exit',code=>reject(Error('Native runtime exited '+code+': '+logs.join('').slice(-1000))));});
 const timer=setTimeout(()=>process.kill(),15000);let readyData;try{readyData=await ready;}finally{clearTimeout(timer);}worker={process,...readyData,logs};return worker;
}
async function stopWorker(){if(!worker)return;const process=worker.process;if(process.exitCode===null){const closed=new Promise(resolve=>process.once('exit',resolve));process.kill();await closed;}}
try{
 check('unauthenticated command refused',!(await request('/api/backend',{command:'gamedev_status_command',payload:{}},true)).ok);
 await request('/api/auth/local-session',{});
 const status=await command('status');receipt.initialStatus=status;
 for(const e of status.engines.filter(e=>e.engine!=='babylon')){check(e.engine+' absent reported honestly',!e.installed&&e.status==='needs_editor',e);}
 const setup=await command('setup',{engine:'babylon',projectPath:project});receipt.setup=setup;
 check('project setup has no token in response',!JSON.stringify(setup).includes('"token"'),setup);
 await failure('outside workspace setup refused','setup',{engine:'babylon',projectPath:'C:/Windows'});
 const refused=await request('/api/gamedev/bridge/register',{engine:'godot',projectPath:project});check('bridge token required',!refused.ok,refused);
 await startWorker();receipt.nativeRuntime={sessionId:worker.sessionId,nativeEngine:worker.nativeEngine};
 const tools=await request('/api/ui/tools');const names=tools.data.tools.map(t=>t.name);check('all six bot tools registered',['status','sessions','setup','action','receipt','asset_validate'].every(n=>names.includes('neyvia.gamedev.'+n)),names.filter(n=>n.includes('gamedev')));
 const toolRead=await request('/api/ui/tools/call',{tool:'neyvia.gamedev.sessions',arguments:{}});check('bot observes same session',JSON.stringify(toolRead).includes(worker.sessionId),toolRead);
 const first=await done('edit',{op:'create',name:'ChronosRoom',position:[1,2,3],color:[.2,.7,.4]},'succeeded',createRequest);
 check('native mesh real geometry',first.result.meshes[0].vertices===24,first.result.meshes[0]);
 const duplicate=await command('action',{sessionId:worker.sessionId,action:'edit',args:{op:'create',name:'ChronosRoom',position:[1,2,3],color:[.2,.7,.4]},requestId:createRequest});
 check('retry does not execute twice',duplicate.requestId===first.requestId&&duplicate.status==='succeeded',duplicate);
 await failure('changed requestId intent refused','action',{sessionId:worker.sessionId,action:'inspect',args:{},requestId:createRequest});
 await failure('wrong native context refused','action',{sessionId:worker.sessionId,action:'run',args:{context:'Server'}});
 await failure('unsupported action refused','action',{sessionId:worker.sessionId,action:'render',args:{}});
 await done('select',{name:'ChronosRoom'});
 await done('run');const interaction=await done('interact',{name:'ChronosRoom',rotateY:.5});
 check('real interaction changed rotation',interaction.result.meshes.find(m=>m.name==='ChronosRoom').rotation[1]===.5,interaction.result);
 await done('test',{name:'ChronosRoom',position:[1,2,3],minVertices:24});
 await done('edit',{op:'transform',name:'ChronosRoom',position:[4,5,6],expectedRevision:0},'failed');
 await done('edit',{op:'transform',name:'ChronosRoom',position:[4,5,6]});
 await done('test',{name:'ChronosRoom',position:[4,5,6]});
 await done('test',{name:'ChronosRoom',position:[999,5,6]},'failed');
 await done('stop');
 const exported=await done('export',{path:path.join(project,'exports/room.glb')});
 const validation=await command('asset_validate',{path:exported.result.path});receipt.assetValidation=validation;check('Khronos validation passes',validation.valid,validation);
 const loaded=await done('load_asset',{path:exported.result.path});check('engine loaded real glTF meshes',loaded.result.loaded.length>0,loaded.result);
 const broken=path.join(project,'broken.gltf');fs.writeFileSync(broken,JSON.stringify({asset:{version:'2.0'},buffers:[{uri:'missing.bin',byteLength:36}]}));
 const bad=await command('asset_validate',{path:broken});check('broken asset rejected',!bad.valid,bad);
 await failure('invalid asset never reaches engine','action',{sessionId:worker.sessionId,action:'load_asset',args:{path:broken}});
 await failure('output traversal refused','action',{sessionId:worker.sessionId,action:'export',args:{path:'../escape.glb'}});
 await done('export',{path:exported.result.path},'failed');
 const observed=await done('inspect');check('failed stale edit preserved actual position',observed.result.meshes.find(m=>m.name==='ChronosRoom').position[0]===4,observed.result);
 const bridgeConfig=JSON.parse(fs.readFileSync(path.join(project,'.neyvia/gamedev-bridge.json'),'utf8'));
 const completionBody={sessionId:worker.sessionId,requestId:observed.requestId,status:'succeeded',result:observed.result,error:''};
 const completeAgain=await fetch(base+'/api/gamedev/bridge/complete',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+bridgeConfig.token},body:JSON.stringify(completionBody)});const completedAgain=await completeAgain.json();
 check('lost completion response retry is idempotent',completedAgain.ok&&completedAgain.data.requestId===observed.requestId,{ok:completedAgain.ok,requestId:completedAgain.data?.requestId});
 const wrongComplete=await fetch(base+'/api/gamedev/bridge/complete',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+bridgeConfig.token},body:JSON.stringify({...completionBody,result:{tampered:true}})});const wrongCompleted=await wrongComplete.json();check('changed completion cannot overwrite receipt',!wrongCompleted.ok,{ok:wrongCompleted.ok,error:wrongCompleted.error});
 const sceneFile=path.join(project,'.neyvia/scene.babylon');check('scene persisted on disk',fs.statSync(sceneFile).size>100,sceneFile);
 const persisted=await request('/api/gamedev/browser-state?project='+encodeURIComponent(project));check('browser reload endpoint exposes persisted scene and hash',persisted.ok&&persisted.data.scene.meshes.length>0&&persisted.data.sha256.length===64,{sha256:persisted.data?.sha256,meshes:persisted.data?.scene?.meshes?.length});
 const signedBrowser=await fetch(base+'/api/gamedev/browser?project='+encodeURIComponent(project),{headers:{Cookie:cookie}});check('owner browser runtime served',signedBrowser.ok&&(await signedBrowser.text()).includes('new NeyviaScene'),{status:signedBrowser.status});
 const unsignedBrowser=await fetch(base+'/api/gamedev/browser?project='+encodeURIComponent(project));check('unsigned browser runtime refused',unsignedBrowser.status===403,{status:unsignedBrowser.status});
 const oldSession=worker.sessionId;await stopWorker();await startWorker(true);
 const restored=await done('inspect');check('native runtime restart restores actual scene',restored.result.meshes.some(m=>m.name==='ChronosRoom'&&m.position[0]===4),restored.result);
 await done('test',{name:'ChronosRoom',position:[4,5,6]});
 check('WebSocket bridge drives real native Babylon receipts',(await command('sessions')).sessions.some(s=>s.sessionId===worker.sessionId&&s.environment==='headless-native-proof-ws'),{sessionId:worker.sessionId});
 const desktop=spawnSync('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe',['-m','grant_agent.desktop_bridge','--root',path.join(root,'.agent_control/t12/runtime')],{input:JSON.stringify({command:'gamedev_sessions_command',payload:{}}),cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src'),NEYVIA_CONNECTED_SERVICE_PORT:'48261'},encoding:'utf8'});
 receipt.desktop={code:desktop.status,stdout:desktop.stdout,stderr:desktop.stderr};check('desktop reaches persistent bridge',desktop.status===0&&desktop.stdout.includes(worker.sessionId),receipt.desktop);
 receipt.oldSession=oldSession;receipt.status='backend_native_semantics_proven';
}catch(error){receipt.status='failed';receipt.error=String(error);process.exitCode=1;}
finally{
 await stopWorker();
 receipt.limitations=['Unity, Roblox Studio, Godot and Blender are not installed; plugin compilation and defining journeys unproven.','Chrome CUA reports Browser is not available; no rendered browser screenshot or pointer journey.','Roblox StudioTestService player launch/end path and actual Client/Server plugin contexts require native host proof.','Unity glTF import needs a project importer; bridge fails if absent.','Blender render/export pipeline needs the native host.','NAS sync pending: saved access uses prohibited Tailscale route.'];
 const sources=['src/grant_agent/neyvia_gamedev.py','src/grant_agent/web_backend.py','src/grant_agent/neyvia_workspace_tools.py','src/grant_agent/desktop_bridge.py','config/neyvia_manuals.json','manuals/game-dev.manual.json','scripts/verify-t12.mjs','scripts/verify-t12-recovery.mjs','scripts/verify-t12-proxy.mjs'];
 const walk=directory=>{for(const entry of fs.readdirSync(directory,{withFileTypes:true})){if(entry.name==='__pycache__')continue;const file=path.join(directory,entry.name);if(entry.isDirectory())walk(file);else sources.push(file.replaceAll('\\','/'));}};walk('scripts/gamedev');
 for(const file of sources)receipt.sourceHashes[file]=crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
 fs.mkdirSync(path.dirname(receiptPath),{recursive:true});fs.writeFileSync(receiptPath,JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify({status:receipt.status,checks:receipt.checks.length,passed:receipt.checks.filter(c=>c.passed).length,error:receipt.error,receipt:receiptPath}));
}
