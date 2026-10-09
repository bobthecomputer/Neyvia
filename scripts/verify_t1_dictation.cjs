/* Real authenticated prompt-dictation journey. No Python tests, model downloads,
 * live-tree access or GPU use. Replays Paul's existing non-math speech through
 * the production HTTP stream; grammar checks use the production text endpoint.
 * --keep-running keeps this run's isolated servers for Chrome/Claude UI proof.
 */
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const project = path.resolve(__dirname, '..');
const python = 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const engineDir = 'C:\\Users\\user\\Projects\\dictation-phonon2';
const enginePython = 'C:\\Users\\user\\Projects\\dictation-workbench-recovery-20260825\\.venv\\Scripts\\python.exe';
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'neyvia-T1-'));
const root = path.join(scratch, 'state');
const evidence = path.join(project, 'scripts', 'evidence', 'T1.json');
const base = 'http://127.0.0.1:48111';
const children = [], checks = [], clips = [];
let cookie = '';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const env = {...process.env, PYTHONPATH:path.join(project,'src'), PYTHONIOENCODING:'utf-8', PYTHONUNBUFFERED:'1',
  NEYVIA_UI_STATE_ROOT:root, NEYVIA_DICTATION_ENGINE_URL:'http://127.0.0.1:48113', NEYVIA_DICTATION_QWEN_URL:'http://127.0.0.1:48114',
  NEYVIA_CONNECTED_SERVICE_PORT:'48111', NEYVIA_COORDINATOR_AUTOSTART:'0', FLUXIO_WATCHDOG_AUTOSTART:'0', NEYVIA_TOOL_AUTO_UPDATE:'0', FLUXIO_RUNTIME_AUTO_UPDATE:'0',
  HF_HUB_OFFLINE:'1', TRANSFORMERS_OFFLINE:'1', HF_DATASETS_OFFLINE:'1', OMP_NUM_THREADS:'4', MKL_NUM_THREADS:'4'};

function record(name, detail) { checks.push({name, ok:true, detail}); console.log('PASS ' + name); }
async function freePort(port) {
  await new Promise((resolve,reject) => { const probe=net.createServer(); probe.once('error',reject); probe.listen(port,'127.0.0.1',()=>probe.close(resolve)); });
}
function launch(name, exe, args, cwd=project, extra={}) {
  const logPath=path.join(scratch,name+'.log'), log=fs.openSync(logPath,'a');
  const child=spawn(exe,args,{cwd,windowsHide:true,detached:process.argv.includes('--keep-running'),env:{...env,...extra},stdio:['ignore',log,log]});
  fs.closeSync(log); children.push({name,child,logPath});
  return child;
}
async function until(fn, timeout, message) {
  const began=Date.now();
  while(Date.now()-began<timeout) {
    for(const item of children) if(item.child.exitCode!==null) throw Error(item.name+' exited: '+fs.readFileSync(item.logPath,'utf8').slice(-4000));
    try {const result=await fn(); if(result) return result;} catch(error) {if(error.message.includes(' exited: ')) throw error;}
    await sleep(500);
  }
  throw Error(message);
}
async function http(route, body, authenticated=true) {
  const response=await fetch(base+route,{method:body===undefined?'GET':'POST',body:body===undefined?undefined:Buffer.isBuffer(body)?body:JSON.stringify(body),
    headers:{...(authenticated&&cookie?{Cookie:cookie}:{}),...(body!==undefined&&!Buffer.isBuffer(body)?{'Content-Type':'application/json'}:{})},signal:AbortSignal.timeout(180000)});
  if(authenticated&&response.headers.get('set-cookie')) cookie=response.headers.get('set-cookie').split(';')[0];
  const result=await response.json(); return {status:response.status,...result};
}
async function api(route, body) {const answer=await http(route,body); assert.equal(answer.status,200,JSON.stringify(answer)); assert.equal(answer.ok,true,JSON.stringify(answer)); return answer.data;}
const processText=(text,extra={})=>api('/api/ui/dictation/process',{text,history:[],...extra});
const command=(name,payload={})=>api('/api/backend',{command:name,payload});
function readWav(file) {
  const wav=fs.readFileSync(file); assert.equal(wav.toString('ascii',0,4),'RIFF');
  let pcm=null,format=null;
  for(let at=12;at+8<=wav.length;) {
    const tag=wav.toString('ascii',at,at+4), size=wav.readUInt32LE(at+4),start=at+8;
    if(tag==='fmt ') format={kind:wav.readUInt16LE(start),channels:wav.readUInt16LE(start+2),rate:wav.readUInt32LE(start+4),bits:wav.readUInt16LE(start+14)};
    if(tag==='data') pcm=wav.subarray(start,start+size);
    at=start+size+(size%2);
  }
  assert.deepEqual(format,{kind:1,channels:1,rate:16000,bits:16}); assert.ok(pcm); return pcm;
}
async function grammar() {
  const cases={undo:['undo','undo that','annule ça'],scratch:['scratch that','strike that','efface ça'],
    delete_last_sentence:['delete the last sentence','delete last sentence','supprime la dernière phrase'],
    new_line:['new line','newline','next line','à la ligne','nouvelle ligne'],new_paragraph:['new paragraph','nouveau paragraphe'],
    send:['send it','send','send that','envoie','envoie-le'],cancel:['cancel','cancel that','annule']};
  for(const [op,phrases] of Object.entries(cases)) for(const phrase of phrases) {
    const answer=await processText(phrase.toUpperCase()+'.'); assert.deepEqual(answer.commands,[{op}],phrase); assert.equal(answer.text,'');
  }
  record('all English/French command phrases',cases);
  for(const text of ['send it to Paul tomorrow','undo that change in the parser','please cancel that operation','write "new line" in the docs','literally new line','write \'send it\' in the docs']) {
    const answer=await processText(text); assert.deepEqual(answer.commands,[],text); assert.ok(answer.text);
  }
  record('literal and mid-sentence commands preserved');
  const ordered=await processText('write the draft new paragraph scratch that keep the revision send it');
  assert.deepEqual(ordered.commands.map(c=>c.op),['new_paragraph','scratch','send']);
  record('ordered inline edits and end-only send',ordered);
  const live=await processText('send it',{final:false}); assert.deepEqual(live.commands,[]); assert.equal(live.provisional,'send it');
  record('provisional send never acts',live);
  const clean=await processText('um the the cloud code uses code ex with neevia and laya');
  assert.equal(clean.text,'The Claude Code uses Codex with Neyvia and LAYA.'); assert.ok(clean.fixes.some(f=>f.kind==='name')); assert.ok(clean.fixes.some(f=>f.kind==='repeat'));
  assert.equal((await processText('how can we improve the prompt')).text,'How can we improve the prompt?');
  record('name/filler/repeat/capital/punctuation receipts',clean);
  const mixed=await processText('please add the notes pour demain avec les détails'); assert.equal(mixed.language,'mixed'); assert.equal(mixed.route,'qwen'); assert.ok(mixed.route_note);
  const fr=await processText('je veux ajouter les notes pour demain'); assert.equal(fr.language,'fr'); assert.equal(fr.route,'qwen');
  const prior=await processText('Neyvia',{history:['fr']}); assert.equal(prior.language,'fr'); assert.equal(prior.language_source,'history');
  record('French/mixed/prior routing and explicit unavailable path',{mixed,fr,prior});
  await command('dictation_names_command',{action:'add',to:'PaulExample',from:['paul example']});
  assert.equal((await processText('paul example')).text,'PaulExample.');
  assert.equal((await http('/api/ui/dictation/names',{action:'remove',to:'Neyvia',from:['nevia']})).status,400);
  record('persisted custom dictionary and protected built-ins');
  assert.equal((await http('/api/ui/dictation/process',[])).status,400);
  assert.equal((await http('/api/ui/dictation/process',{text:'hello',history:123})).status,400);
  assert.equal((await http('/api/ui/dictation/process',{text:'hello'},false)).status,401);
  record('malformed request and unauthenticated refusal');
  const tool=await api('/api/ui/tools/call',{tool:'neyvia.dictation.process',arguments:{text:'cloud code',history:[]}});
  assert.ok(JSON.stringify(tool).includes('Claude Code')); record('native/model tool reaches same parser',tool);
}
async function realStream(row, index) {
  const pcm=readWav(row.audio_path), sid='t1-real-'+index+'-'+Date.now(); const responses=[];
  const start=Date.now(); let seq=0;
  for(let at=0;at<pcm.length;at+=8000) {
    const chunk=pcm.subarray(at,Math.min(at+8000,pcm.length));
    const answer=await api(`/api/ui/dictation/stream/${sid}/append?seq=${seq++}&history=%5B%22en%22%5D`,chunk);
    const previous=responses.at(-1)?.stable||'';
    assert.ok(answer.stable.startsWith(previous)||answer.revision,'stable text changed silently');
    responses.push({atMs:Date.now()-start,...answer});
    if(index===0&&seq===1) {
      const duplicate=await api(`/api/ui/dictation/stream/${sid}/append?seq=0`,chunk); assert.equal(duplicate.duplicate,true);
    }
    const deadline=start+Math.min(at+8000,pcm.length)/32; if(deadline>Date.now()) await sleep(deadline-Date.now());
  }
  const released=Date.now();
  const final=await api(`/api/ui/dictation/stream/${sid}/finish?seq=${seq}`,Buffer.alloc(0));
  const previous=responses.at(-1)?.stable||'';
  assert.ok(final.stable.startsWith(previous)||final.revision,'final changed settled text without a revision');
  assert.ok(final.text.toLowerCase().includes('ordinary sentence'),final.text); assert.equal(final.provisional,''); assert.equal(final.engine,'phonon2'); assert.equal(final.route,'phonon2');
  assert.equal(final.device,'cpu');
  const duplicate=await api(`/api/ui/dictation/stream/${sid}/finish?seq=${seq}`,Buffer.alloc(0)); assert.equal(duplicate.duplicate,true); assert.equal(duplicate.text,final.text);
  const receipt={id:row.id,reference:row.literal_transcript,audioSha256:crypto.createHash('sha256').update(pcm).digest('hex'),
    audioMs:pcm.length/32,releaseToTextMs:Date.now()-released,partials:responses,final}; clips.push(receipt);
  record('real recorded non-math speech '+row.id,{text:final.text,releaseToTextMs:receipt.releaseToTextMs,partials:responses.filter(r=>r.provisional).length,stablePartials:responses.filter(r=>r.stable).length});
}
async function cancellation() {
  await api('/api/ui/dictation/stream/t1-cancel/append?seq=0',Buffer.alloc(16000));
  await api('/api/ui/dictation/stream/t1-cancel/cancel?seq=1',Buffer.alloc(0));
  assert.equal((await http('/api/ui/dictation/stream/t1-cancel/finish?seq=1',Buffer.alloc(0))).status,400);
  assert.equal((await http('/api/ui/dictation/stream/t1-order/append?seq=2',Buffer.alloc(0))).status,400);
  assert.equal((await http('/api/ui/dictation/stream/t1-odd/append?seq=0',Buffer.alloc(3))).status,400);
  record('cancel tombstone, ordering and malformed PCM');
  assert.equal((await http('/api/ui/dictation/redecode/no-such-session',{})).status,400);
  assert.equal((await http('/api/ui/dictation/transcribe?engine=qwen',Buffer.alloc(16000))).status,503);
  record('unavailable re-decode fails explicitly without audio spill');
}
async function desktop(name,payload={}) {
  return new Promise((resolve,reject)=>{
    const child=spawn(python,['-m','grant_agent.desktop_bridge','--root',root],{cwd:project,windowsHide:true,env,stdio:['pipe','pipe','pipe']});
    let output='',error=''; child.stdout.on('data',data=>output+=data); child.stderr.on('data',data=>error+=data);
    child.stdin.end(JSON.stringify({command:name,payload}));
    child.on('error',reject); child.on('exit',code=>{try{assert.equal(code,0,error); const answer=JSON.parse(output.trim()); assert.equal(answer.ok,true,JSON.stringify(answer)); assert.notEqual(answer.data?.ok,false,JSON.stringify(answer)); resolve(answer.data);}catch(e){reject(e);}});
  });
}
async function desktopJourney() {
  const text=await desktop('dictation_process_command',{text:'cloud code',history:[]}); assert.equal(text.text,'Claude Code.');
  const sid='t1-desktop-'+Date.now();
  const a=await desktop('dictation_stream_command',{sid,op:'append',seq:0,pcm:Buffer.alloc(8000).toString('base64')}); assert.equal(a.sid,sid);
  const b=await desktop('dictation_stream_command',{sid,op:'append',seq:1,pcm:Buffer.alloc(8000).toString('base64')}); assert.equal(b.seq,1);
  const final=await desktop('dictation_stream_command',{sid,op:'finish',seq:2,pcm:''}); assert.equal(final.final,true); assert.equal(final.sid,sid);
  record('fresh desktop bridge workers share the persistent HTTP frontier',{text,first:a.seq,second:b.seq,final});
  const wrong=await command('dictation_process_command',{text:'hello',_expectedStateRoot:path.join(scratch,'other')}).catch(e=>e);
  assert.ok(wrong instanceof Error); record('desktop service rejects another workspace root');
}
async function manualJourney() {
  const validation=await api('/api/ui/tools/call',{tool:'neyvia.manual.validate',arguments:{id:'dictation'}});
  assert.equal(validation.result.manuals[0].grounded,true);
  const run=await api('/api/ui/tools/call',{tool:'neyvia.manual.run',arguments:{id:'dictation',chapter:'prompts',procedure:'check-a-command',inputs:{text:'new paragraph',op:'new_paragraph'}}});
  assert.equal(run.result.status,'completed'); assert.equal(run.result.checks[0].passed,true);
  record('grounded dictation manual validates and executes a checked command procedure',{validation,run});
  record('real stream and finish never change settled words without a revision',clips.map(c=>({id:c.id,
    corrections:[...c.partials.filter(p=>p.revision).map(p=>p.revision),...(c.final.revision?[c.final.revision]:[])]})));
}
async function main() {
  fs.mkdirSync(path.join(root,'.neyvia'),{recursive:true});
  fs.writeFileSync(path.join(root,'.neyvia','dictation.json'),JSON.stringify({engineDir,python:enginePython,port:48113,device:'cpu'}));
  for(const port of [48111,48112]) await freePort(port);
  if(!process.argv.includes('--reuse-engine')) await freePort(48113);
  launch('backend',python,['scripts/run_web_backend.py','--host','127.0.0.1','--port','48111','--root',root,'--static-root',path.join(root,'static'),'--skip-runtime-auto-update']);
  const engineEnv={...env}; delete engineEnv.PYTHONPATH;
  if(process.argv.includes('--reuse-engine')) {
    const health=await (await fetch('http://127.0.0.1:48113/v1/health')).json();
    assert.equal(health.engine,'phonon2'); assert.ok(health.state==='loading'||health.device==='cpu');
    record('explicit reuse of shared T1 CPU engine',{pid:health.pid,state:health.state});
  } else launch('engine',enginePython,[path.join(engineDir,'phonon2_engine.py'),'--port','48113','--device','cpu','--idle-exit-minutes','20'],engineDir,engineEnv);
  launch('vite',process.execPath,[path.join(project,'node_modules','vite','bin','vite.js'),'--config','vite.config.mjs','--port','48112'],project,{FLUXIO_WEB_BACKEND_URL:base,TAURI_DEV_PORT:'48112'});
  await until(async()=>{try{return(await http('/health')).status===200}catch{return false}},60000,'Backend did not start');
  await api('/api/auth/local-session',{}); await grammar();
  const ready=await until(async()=>{const s=await api('/api/ui/dictation/status'); if(s.state==='error') throw Error(s.error); return s.state==='ready'&&s},600000,'Engine did not load locally on CPU');
  record('local CPU engine ready with offline downloads disabled',ready);
  const rows=fs.readFileSync(path.join(engineDir,'runs','phonon2','paul_voice_seed16.jsonl'),'utf8').trim().split(/\r?\n/).map(JSON.parse).filter(row=>row.id.includes('seed-line-08'));
  for(let index=0;index<rows.length;index++) await realStream(rows[index],index);
  await cancellation();
  await desktopJourney();
  await manualJourney();
  const history=JSON.parse(fs.readFileSync(path.join(root,'.neyvia','dictation-history.json'),'utf8'));
  assert.ok(history.length<=20); assert.ok(history.every(row=>Object.keys(row).sort().join(',')==='at,language'));
  record('language history stores codes/time only',history);
}
main().then(()=>finish(true)).catch(error=>{console.error(error); finish(false,String(error.stack||error));});
function finish(ok,error='') {
  fs.mkdirSync(path.dirname(evidence),{recursive:true});
  let previous={};try{previous=JSON.parse(fs.readFileSync(evidence,'utf8'));}catch{}
  const sources=['src/grant_agent/neyvia_dictation.py','src/grant_agent/neyvia_prompt_dictation.py','src/grant_agent/desktop_bridge.py','src/grant_agent/connected_sessions/forward.py'];
  const receipt={at:new Date().toISOString(),ok,branch:'track/t1-dictation',engineCommit:'b84b56b',
    sourceSha256:Object.fromEntries(sources.map(file=>[file,crypto.createHash('sha256').update(fs.readFileSync(path.join(project,file))).digest('hex')])),
    boundary:'Real recorded English audio over authenticated production HTTP; text grammar is supplied text, not ASR proof. UI receipts added separately.',
    missing:['French/mixed ASR: no local multilingual PCM recognizer available','Physical microphone quality not measured','NAS sync excluded by port/Tailscale restrictions'],
    checks,clips,error,frontierRegression:previous.frontierRegression,
    servers:children.map(({name,child,logPath})=>({name,pid:child.pid,logPath})),scratchRoot:root};
  fs.writeFileSync(evidence,JSON.stringify(receipt,null,2)+'\n');
  console.log(JSON.stringify({ok,checks:checks.length,evidence,root}));
  if(ok&&process.argv.includes('--keep-running')) {
    console.log('T1 proof servers held by this verification session; interrupt this session after UI proof.');
    const alive=setInterval(()=>{},1000);
    process.once('SIGINT',()=>{clearInterval(alive);for(const {child} of children) child.kill();});
  }
  else for(const {child} of children) child.kill();
  process.exitCode=ok?0:1;
}
