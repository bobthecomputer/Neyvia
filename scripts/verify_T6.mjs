/** Real signed Rust transfers and an installed Python backend, on scratch ports only. */
import { createServer } from 'node:http';
import { createHash, generateKeyPairSync, randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, existsSync, statSync, createReadStream } from 'node:fs';
import { join, resolve, dirname, relative } from 'node:path';
import { tmpdir } from 'node:os';
import { signer } from './prepare_slim_release.mjs';

const repo = resolve(import.meta.dirname, '..');
const workRoot = resolve(process.env.T6_WORK_ROOT || join(repo,'src-tauri/target'));
if(relative(repo,workRoot).startsWith('..')) throw Error('Proof work root must remain in this worktree.');
const work = join(workRoot,`T6-run-${Date.now()}`);
const evidencePath = resolve(process.env.T6_EVIDENCE || join(repo,'scripts/evidence/T6.json'));
if(relative(repo,evidencePath).startsWith('..')) throw Error('Proof receipt must remain in this worktree.');
function proofPort(name, fallback) {
  if(!process.env[name]) return fallback;
  const value=Number(process.env[name]);
  if(!Number.isInteger(value)||value<48351||value>48359) throw Error(`${name} must use INT6 ports 48351–48359.`);
  return value;
}
const backendPort=proofPort('T6_BACKEND_PORT',48161), transferPort=proofPort('T6_TRANSFER_PORT',48163);
if(backendPort===transferPort) throw Error('Backend and transfer proof ports must differ.');
mkdirSync(work,{recursive:true});
const evidence = {schema:'neyvia.T6-proof/v1',startedAt:new Date().toISOString(),checks:[],fixedIssues:[{issue:'Zero-byte standard-library files failed installation',repair:'Create and hash the empty partial before publishing'},{issue:'Windows status reader briefly blocked atomic rename with os error 5',repair:'Close the flushed temporary file and retry atomic replacement'}],boundaries:{ports:[backendPort,transferPort],downloads:'loopback only; every pack <200 MB',nativeModule:'src-tauri/src/base_pack.rs',desktopWebView:false,productionRelease:false}};
const keyDir = mkdtempSync(join(tmpdir(),'neyvia-t6-key-'));
const keyPath = join(keyDir,'key.pem');
writeFileSync(keyPath,generateKeyPairSync('ed25519').privateKey.export({type:'pkcs8',format:'pem'}));
const signing=signer(keyPath), probe=resolve(process.env.T6_PROBE || join(repo,'src-tauri/target/pack-probe/debug/neyvia-pack-probe.exe'));
if(!existsSync(probe)) throw new Error('Build scripts/pack-probe/Cargo.toml first.');
const files = new Map(), requests = [], delay = new Map();
function manifest(name, changes={}) {
  const payload=randomBytes(2*1024*1024), url=`/${name}/data.bin`;
  files.set(url,payload);delay.set(url,10);
  const row={schema:'neyvia.base-pack/v1',packId:'pack.proof',version:'1',totalSize:payload.length,files:[{path:'data.bin',url:'data.bin',size:payload.length,sha256:createHash('sha256').update(payload).digest('hex')}],...changes};
  const bytes=Buffer.from(JSON.stringify(row));
  files.set(`/${name}/manifest.json`,bytes);
  files.set(`/${name}/manifest.json.minisig`,Buffer.from(signing.sign(bytes,`pack=${name}`)));
  return row;
}
const good=manifest('good'), corrupt=manifest('corrupt');files.get('/corrupt/data.bin')[0]^=1;
manifest('tampered');files.get('/tampered/manifest.json')[30]^=1;
manifest('unsafe',{files:[{...good.files[0],path:'../escape.bin'}]});
manifest('oversize',{totalSize:201*1024*1024,files:[{...good.files[0],size:201*1024*1024}]});
manifest('blocked',{deliveryStatus:'needs-paul'});
manifest('duplicate',{totalSize:good.totalSize*2,files:[good.files[0],{...good.files[0],path:'DATA.BIN'}]});
manifest('invalid-range');
manifest('ignored-range');
manifest('empty-file',{totalSize:0,files:[{path:'empty.txt',url:'empty.txt',size:0,sha256:createHash('sha256').update('').digest('hex')}]});
files.set('/empty-file/empty.txt',Buffer.alloc(0));
manifest('invalid-runtime',{packId:'base',runtime:{python:'python/python.exe',backend:'.'},totalSize:good.totalSize+9,files:[good.files[0],{path:'python/python.exe',url:'python.exe',size:4,sha256:createHash('sha256').update('nope').digest('hex')},{path:'src/grant_agent/cli.py',url:'cli.py',size:5,sha256:createHash('sha256').update('# cli').digest('hex')}]});
files.set('/invalid-runtime/python.exe',Buffer.from('nope'));files.set('/invalid-runtime/cli.py',Buffer.from('# cli'));
files.set('/invalid-runtime/data.bin',files.get('/good/data.bin'));
let uiChild=null,uiState={state:'idle'},backend=null,releaseRoot=process.argv[2]?resolve(process.argv[2]):null;
let releaseKey=releaseRoot?readFileSync(join(releaseRoot,'release-public-key.txt'),'utf8').trim():'';
const uiRoot=join(work,'ui-base');
const resumeIndex=process.argv.indexOf('--resume-base');
const installedRoot=resumeIndex>=0?resolve(process.argv[resumeIndex+1]):join(work,'installed-base');
if(relative(workRoot,installedRoot).startsWith('..'))throw Error('Resume root must remain in this proof work root.');
let uiThrottle=true;
function run(args, {pauseOnProgress=false,pauseOnRuntime=false}={}) {
  return new Promise((done,reject)=>{
    const child=spawn(probe,args,{stdio:['pipe','pipe','pipe'],windowsHide:true});let output='',error='';
    let pending='',paused=false;
    child.stdout.on('data',b=>{output+=b;pending+=b;let i;while((i=pending.indexOf('\n'))>=0){const row=JSON.parse(pending.slice(0,i));pending=pending.slice(i+1);if(!paused&&((pauseOnProgress&&row.doneBytes>0)||(pauseOnRuntime&&row.phase==='verifyRuntime'))){paused=true;child.stdin.write('pause\n');}}});child.stderr.on('data',b=>error+=b);
    child.on('error',reject);child.on('exit',code=>{const lines=output.trim().split('\n');const last=JSON.parse(lines.at(-1));done({code,...last,stderr:error});});
  });
}
function check(name,ok,details={}) {evidence.checks.push({name,ok,...details});writeEvidence();if(!ok)throw new Error(`Failed: ${name}`);console.log(`${name}: OK`);}
function writeEvidence(){mkdirSync(dirname(evidencePath),{recursive:true});writeFileSync(evidencePath,JSON.stringify(evidence,null,2)+'\n');}
const origin=`http://127.0.0.1:${transferPort}`;
const server=createServer(async(req,res)=>{
  const path=new URL(req.url,origin).pathname;
  if(path==='/gate.js'){res.setHeader('Content-Type','text/javascript');res.end(readFileSync(join(repo,'web/src/basePackGate.js')));return;}
  if(path==='/journey'){
    res.setHeader('Content-Type','text/html');res.end(`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Neyvia base pack proof</title></head><body style="margin:0"><div id="root"></div><script type="module">import {runBasePackGate} from '/gate.js'; await runBasePackGate(async command=>{const r=await fetch('/api/bootstrap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command})});const state=await r.json();if(!r.ok)throw Error(state.error);return state;});document.getElementById('root').innerHTML='<main style="padding:64px;font:20px Segoe UI;background:#0a0f0c;color:#f1ede3;min-height:100vh"><h1>Your workspace is ready</h1><p>Python and the backend arrived in the signed base pack.</p><a style="color:#6fbf8a" href="/workspace/">Open workspace</a></main>';</script></body></html>`);return;
  }
  if(path==='/api/bootstrap') {
    let body='';for await(const b of req)body+=b;
    const {command}=JSON.parse(body);
    if(command==='onboarding_base_pack_start_command'&&!uiChild){
      if(!releaseRoot){res.writeHead(500);res.end(JSON.stringify({error:'Pass a release directory'}));return;}
      uiState={state:'running',phase:'manifest'};
      uiChild=spawn(probe,['install',uiRoot,origin+'/release/base/manifest.json',releaseKey,'base'],{stdio:['pipe','pipe','pipe'],windowsHide:true});
      let pending='';uiChild.stdout.on('data',b=>{pending+=b;let i;while((i=pending.indexOf('\n'))>=0){const row=JSON.parse(pending.slice(0,i));pending=pending.slice(i+1);if(row.state)uiState=row;}});
      uiChild.on('exit',()=>{uiChild=null;});
    } else if(command==='onboarding_base_pack_pause_command'&&uiChild){uiChild.stdin.write('pause\n');uiState.pauseRequested=true;}
    else if(command!=='onboarding_base_pack_status_command'&&command!=='onboarding_base_pack_pause_command'&&command!=='onboarding_base_pack_start_command'){res.writeHead(400);res.end('{}');return;}
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify(uiState));return;
  }
  if(path==='/api/proof-fast'){uiThrottle=false;res.end('{}');return;}
  if(path.startsWith('/api/')||path==='/health'){
    try {const headers={...req.headers};delete headers.host;
      let body='';for await(const b of req)body+=b;
      const response=await fetch(`http://127.0.0.1:${backendPort}`+req.url,{method:req.method,headers,body:['GET','HEAD'].includes(req.method)?undefined:body});res.writeHead(response.status,Object.fromEntries(response.headers));res.end(Buffer.from(await response.arrayBuffer()));
    }catch(error){res.writeHead(502);res.end(String(error));}return;
  }
  if(path.startsWith('/workspace/')) {
    const file=resolve(repo,'web/dist',decodeURIComponent(path.slice('/workspace/'.length)||'index.html'));
    if(relative(join(repo,'web/dist'),file).startsWith('..')){res.writeHead(403);res.end();return;}
    if(!existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream');createReadStream(file).pipe(res);return;
  }
  let bytes=files.get(path),source;
  if(!bytes&&path.startsWith('/release/')&&releaseRoot){source=resolve(releaseRoot,decodeURIComponent(path.slice('/release/'.length)));if(relative(releaseRoot,source).startsWith('..')||!existsSync(source)||!statSync(source).isFile())source=null;}
  if(!bytes&&!source){res.writeHead(404);res.end();return;}
  const length=bytes?bytes.length:statSync(source).size;
  let offset=Number((req.headers.range||'').match(/bytes=(\d+)-/)?.[1]||0);
  requests.push({path,range:req.headers.range||null});
  if(path==='/ignored-range/data.bin')offset=0;
  const isPartial=offset>0;
  const headers={'Content-Length':length-offset};
  if(isPartial)headers['Content-Range']=`bytes ${path==='/invalid-range/data.bin'?offset+1:offset}-${length-1}/${length}`;
  res.writeHead(isPartial?206:200,headers);
  if(source&&!uiThrottle){createReadStream(source,{start:offset}).pipe(res);return;}
  const interval=delay.get(path)||(uiThrottle&&source?1:0);
  if(!interval){if(source)createReadStream(source,{start:offset}).pipe(res);else res.end(bytes.subarray(offset));return;}
  if(source)bytes=readFileSync(source);
  let timer;const send=()=>{if(res.destroyed)return;const end=Math.min(offset+32768,length);res.write(bytes.subarray(offset,end));offset=end;if(offset>=length)res.end();else timer=setTimeout(send,interval);};res.on('close',()=>clearTimeout(timer));send();
});
await new Promise((done,reject)=>server.once('error',reject).listen(transferPort,'127.0.0.1',done));
try {
  const args=(name,root=join(work,name),id='pack.proof')=>['install',root,`${origin}/${name}/manifest.json`,signing.pubkey,id];
  let result=await run(args('good'),{pauseOnProgress:true});
  check('pause persists partial bytes',result.code===1&&result.error==='paused');
  result=await run(args('good'));check('HTTP range resumes and SHA-256 verifies',result.ok&&result.receipt.resumedBytes>0&&requests.some(r=>r.path==='/good/data.bin'&&r.range),{resumedBytes:result.receipt?.resumedBytes});
  result=await run(args('good'));check('verified files reused on retry',result.ok&&result.receipt.reusedBytes===good.totalSize);
  result=await run(args('empty-file'));check('zero-byte payload materializes and verifies',result.ok&&existsSync(join(result.receipt?.target||'','empty.txt')));
  for(const [name,fragment] of [['corrupt','SHA-256'],['tampered','signature'],['unsafe','Unsafe'],['oversize','approval'],['blocked','Needs Paul'],['duplicate','Duplicate']]){
    result=await run(args(name));check(`${name} rejected`,!result.ok&&result.error.includes(fragment),{error:result.error});
    if(['tampered','unsafe','oversize','blocked','duplicate'].includes(name))check(`${name} fetched no payload`,!requests.some(r=>r.path===`/${name}/data.bin`));
  }
  result=await run(args('invalid-runtime',join(work,'invalid-runtime'),'base'));check('broken Python never activates',!result.ok&&result.error.includes('Python')&&!existsSync(join(work,'invalid-runtime/active.json')),{error:result.error});
  for(const name of ['invalid-range','ignored-range']){
    await run(args(name),{pauseOnProgress:true});result=await run(args(name));check(name==='invalid-range'?'invalid Content-Range refused':'200 response restarts partial safely',name==='invalid-range'?!result.ok&&result.error.includes('Content-Range'):result.ok,{error:result.error||''});
  }
  if(releaseRoot){
    const manifest=JSON.parse(readFileSync(join(releaseRoot,'base/manifest.json')));
    check('actual Python plus backend base under 200 MB',manifest.totalSize<=200_000_000,{bytes:manifest.totalSize,files:manifest.files.length});
    uiThrottle=false;
    const release=JSON.parse(readFileSync(join(releaseRoot,'release-receipt.json')));
    evidence.release={publicKey:release.publicKey,runtimeProvenance:release.runtimeProvenance,runtimeProbe:release.runtimeProbe};
    for(const pack of release.packs.filter(p=>p.packId!=='base')){
      result=await run(['install',join(work,'addons',pack.packId),`${origin}/release/addons/${pack.packId}/manifest.json`,releaseKey,pack.packId]);
      check(`real local add-on ${pack.packId} signed install`,result.ok&&result.receipt.signatureVerified,{bytes:pack.bytes,files:pack.files});
    }
    for(const pack of release.external){
      result=await run(['install',join(work,'external',pack.packId),`${origin}/release/external/${pack.packId}/manifest.json`,releaseKey,pack.packId]);
      check(`external ${pack.packId} stops before payload transfer`,!result.ok&&result.error.includes('Needs Paul'),{pinnedSources:pack.sourceArtifacts,needsPaul:pack.needsPaul});
    }
    result=await run(['install',installedRoot,origin+'/release/base/manifest.json',releaseKey,'base']);
    check('actual signed base installs and imports backend',result.ok&&result.receipt.runtimeProbe.backendImported,{manifestSha256:result.receipt?.manifestSha256,runtimeProbe:result.receipt?.runtimeProbe,error:result.error});
    const active=JSON.parse(readFileSync(join(installedRoot,'active.json'))),python=join(active.target,active.python);
    const bridge=await new Promise((done,reject)=>{const child=spawn(python,['-I','-B','-m','grant_agent.desktop_bridge','--root',join(work,'desktop-state')],{cwd:active.target,stdio:['pipe','pipe','pipe'],windowsHide:true});let output='',error='';child.stdout.on('data',b=>output+=b);child.stderr.on('data',b=>error+=b);child.on('error',reject);child.on('exit',code=>done({code,output,error}));child.stdin.end(JSON.stringify({command:'onboarding_state_command',payload:{}}));});
    const envelope=JSON.parse(bridge.output);check('downloaded Python executes actual desktop command',bridge.code===0&&envelope.ok&&Boolean(envelope.data.catalog),{command:'onboarding_state_command',packCount:envelope.data?.packs?.length});
    backend=spawn(python,['-B',join(active.target,'scripts/run_web_backend.py'),'--host','127.0.0.1','--port',String(backendPort),'--root',join(work,'backend-state'),'--skip-runtime-auto-update'],{cwd:active.target,stdio:['ignore','pipe','pipe'],windowsHide:true,env:{...process.env,PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1',FLUXIO_WEB_BACKEND_PORT:String(backendPort),FLUXIO_WATCHDOG_AUTOSTART:'0',NEYVIA_COORDINATOR_AUTOSTART:'0',NEYVIA_TOOL_AUTO_UPDATE:'0'}});
    let backendLog='';backend.stderr.on('data',b=>backendLog+=b);backend.stdout.on('data',b=>backendLog+=b);
    let health;for(let i=0;i<80;i++){try{health=await(await fetch(`http://127.0.0.1:${backendPort}/health`)).json();if(health.ok)break;}catch{}await new Promise(done=>setTimeout(done,250));}
    check('downloaded Python launches real backend',health?.ok===true,{health,python:relative(repo,python),backendLog:backendLog.slice(-1000)});
    result=await run(['verify',installedRoot,origin+'/OFFLINE',releaseKey,'base']);check('restart verifies active pack offline',result.ok&&result.receipt.backendImported);
    const damaged=join(active.target,'src/grant_agent/cli.py');writeFileSync(damaged,Buffer.concat([readFileSync(damaged),Buffer.from('\n# tamper\n')]));
    result=await run(['verify',installedRoot,origin+'/OFFLINE',releaseKey,'base']);check('changed active code refused on restart',!result.ok&&result.error.includes('changed'),{error:result.error});
    result=await run(['install',installedRoot,origin+'/release/base/manifest.json',releaseKey,'base']);check('changed active code repairs through signed download',result.ok&&result.receipt.reusedBytes>0,{reusedBytes:result.receipt?.reusedBytes});
    result=await run(['install',installedRoot,origin+'/release/base/manifest.json',releaseKey,'base'],{pauseOnRuntime:true});check('pause interrupts delivered runtime import',!result.ok&&result.error==='paused',{error:result.error});
    result=await run(['verify',installedRoot,origin+'/OFFLINE',releaseKey,'base']);check('healthy prior activation survives runtime pause offline',result.ok&&result.receipt.backendImported);
    evidence.installedBase={root:relative(repo,installedRoot),target:relative(repo,active.target),version:manifest.version,localProofOnly:true};
    uiThrottle=true;
  }
  evidence.native={path:relative(repo,probe),sha256:createHash('sha256').update(readFileSync(probe)).digest('hex')};
  evidence.sourceHashes=Object.fromEntries(['src-tauri/src/base_pack.rs','scripts/pack-probe/main.rs','scripts/pack-probe/Cargo.lock','scripts/verify_T6.mjs','scripts/prepare_slim_release.mjs'].map(file=>[file,createHash('sha256').update(readFileSync(join(repo,file))).digest('hex')]));
  evidence.passed=evidence.checks.every(c=>c.ok);evidence.completedAt=new Date().toISOString();writeEvidence();
  if(process.argv.includes('--serve')){console.log(`Journey: ${origin}/journey`);await new Promise(()=>{});}else{server.close();backend?.kill();}
} catch(error){evidence.error=error.stack;writeEvidence();server.close();backend?.kill();throw error;}
