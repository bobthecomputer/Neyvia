import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-host-http-'));
const server = spawn(resolveNeyviaPython(process.cwd()).python, ['-u','-c',
  'import json,sys\nfrom pathlib import Path\nfrom http.server import ThreadingHTTPServer\nfrom grant_agent.web_backend import FluxioWebBackend,make_handler\nr=Path(sys.argv[1]);b=FluxioWebBackend(r,r)\nb.sessions["fixture-token"]={"username":"fixture","role":"admin"}\ns=ThreadingHTTPServer(("127.0.0.1",0),make_handler(b))\nprint(json.dumps({"port":s.server_address[1]}),flush=True)\ns.serve_forever()', root],
  { env: {...process.env, PYTHONPATH:path.resolve('src')}, stdio:['ignore','pipe','pipe'] });
let startup = '', errors = '', base = '', sessionId = '', terminal = false;
server.stderr.on('data', data => { errors += data; });
try {
  const ready = await new Promise((resolve,reject) => {
    const timer = setTimeout(()=>reject(new Error(`Server startup timed out: ${errors.slice(-1000)}`)),30000);
    server.once('error',reject);
    server.stdout.on('data', data => { startup += data; if(startup.includes('\n')) {clearTimeout(timer);try{resolve(JSON.parse(startup.split('\n')[0]));}catch(error){reject(error);}} });
  });
  base = `http://127.0.0.1:${ready.port}`;
  async function invoke(tool, arguments_={}, authenticated=true) {
    const response = await fetch(`${base}/api/backend`, {method:'POST',headers:{'Content-Type':'application/json',...(authenticated?{Cookie:'grand_agent_session=fixture-token'}:{})},
      body:JSON.stringify({command:'call_native_tool_command',payload:{tool,arguments:arguments_}})});
    return {status:response.status,body:await response.json()};
  }
  assert.equal((await invoke('host.launch',{executable:process.execPath},false)).status,401);
  const discovery=await invoke('host.programs');
  assert.equal(discovery.status,200);assert.equal(discovery.body.data.ok,true);
  assert.equal((await invoke('runtime.preflight',{},false)).status,401);
  const preflight=await invoke('runtime.preflight',{tools:['host.programs','preview.inspect']});
  assert.equal(preflight.body.data.ok,true);
  assert.equal(preflight.body.data.result.executionReady,false);
  const evidence=await invoke('runtime.evidence',{limit:20});
  assert.equal(evidence.body.data.ok,true);
  const completion=await invoke('runtime.completion');
  assert.equal(completion.body.data.ok,true);
  assert.equal(completion.body.data.result.status,'missing');
  assert.equal((await invoke('lab.status',{},false)).status,401);
  mkdirSync(path.join(root,'sample-app'));
  writeFileSync(path.join(root,'sample-app','app.js'),'console.log("rehearsal");');
  const instrument=await invoke('lab.instrument',{identity:'http-comparison',spec:{kind:'json_numeric',key:'durationMs',max:1000}});
  assert.equal(instrument.body.data.ok,true);
  const comparisonArgs={workId:'http-proof',identity:'http-comparison',source:'sample-app',candidates:['baseline','alternative'],instruments:['http-comparison']};
  const disabledComparison=await invoke('lab.competition',comparisonArgs);
  assert.equal(disabledComparison.body.data.ok,false,'evaluation must be off by default');
  async function commandRequest(command,payload) {
    const response=await fetch(`${base}/api/backend`,{method:'POST',headers:{'Content-Type':'application/json',Cookie:'grand_agent_session=fixture-token'},body:JSON.stringify({command,payload})});
    const body=await response.json();assert.equal(response.status,200,JSON.stringify(body));return body.data;
  }
  const conversation=await commandRequest('create_neyvia_conversation_command',{title:'Evaluation proof'});
  comparisonArgs.workId=conversation.conversationId;
  await commandRequest('save_agent_collaboration_command',{conversationId:conversation.conversationId,expectedRevision:0,preferences:{evaluation:true}});
  const comparison=await invoke('lab.competition',comparisonArgs);
  assert.equal(comparison.body.data.ok,true,JSON.stringify(comparison.body));
  assert.equal(comparison.body.data.result.candidates.length,2);
  assert((await invoke('lab.status')).body.data.result.records.length>0);
  assert(evidence.body.data.result.tools.some(row=>row.tool==='host.programs'&&row.successfulCalls===1));
  const program = `const s=require('http').createServer((q,r)=>{if(q.url==='/redirect'){r.writeHead(302,{Location:'https://example.com'});r.end();return;}r.setHeader('Content-Type','text/html');r.end('<html><title>Live application</title><p>http-host-proof cookie:'+(q.headers.cookie||'none')+'</p><script>excludedScript</script>'+ (q.url==='/large'?'x'.repeat(1100000):'')+'</html>');}).listen(0,'127.0.0.1',()=>console.log('http://127.0.0.1:'+s.address().port));`;
  const launch=await invoke('host.launch',{executable:process.execPath,arguments:['-e',program],timeoutSeconds:60});
  assert.equal(launch.body.data.ok,true);
  sessionId=launch.body.data.result.session.sessionId;
  let endpoint='';
  for(let i=0;i<50;i++) {
    const result=await invoke('host.status',{sessionId});
    assert.equal(result.body.data.ok,true);
    const session=result.body.data.result.session;
    if(session.status==='running' && session.stdout.includes('http://')) { endpoint=session.stdout.trim();break; }
    if(['failed','unknown','timed_out'].includes(session.status)) throw new Error(JSON.stringify(session));
    await new Promise(resolve=>setTimeout(resolve,150));
  }
  assert(endpoint,'HTTP-launched application did not report its endpoint');
  assert.equal((await invoke('host.inspect_preview',{sessionId,url:endpoint},false)).status,401);
  const observed=await invoke('host.inspect_preview',{sessionId,url:endpoint});
  assert.equal(observed.body.data.ok,true,JSON.stringify(observed.body));
  const preview=observed.body.data.result.preview;
  assert(preview.text.includes('http-host-proof cookie:none'));
  assert(!preview.text.includes('excludedScript'));
  assert.equal(preview.title,'Live application');
  assert.equal(preview.processOwnership,'unverified');
  assert.match(preview.contentSha256,/^[a-f0-9]{64}$/);
  assert.equal((await invoke('host.status',{sessionId})).body.data.result.session.preview.contentSha256,preview.contentSha256);
  for(const url of ['https://example.com','file:///secret',endpoint+'/redirect','http://user:pass@127.0.0.1']) {
    assert.equal((await invoke('host.inspect_preview',{sessionId,url})).body.data.ok,false,url);
  }
  const large=await invoke('host.inspect_preview',{sessionId,url:endpoint+'/large'});
  assert.equal(large.body.data.result.preview.truncated,true);
  assert(large.body.data.result.preview.text.length<=16000);
  async function control(owner, expectedRevision, authenticated=true) {
    const response=await fetch(`${base}/api/backend`,{method:'POST',headers:{'Content-Type':'application/json',...(authenticated?{Cookie:'grand_agent_session=fixture-token'}:{})},
      body:JSON.stringify({command:'set_host_session_control_command',payload:{sessionId,owner,expectedRevision,_operatorIdentity:'spoofed'}})});
    return {status:response.status,body:await response.json()};
  }
  assert.equal((await control('agent',0,false)).status,401);
  const granted=await control('agent',0);
  assert.equal(granted.body.data.owner,'agent');
  assert.equal(granted.body.data.operatorIdentity,'fixture');
  assert.equal((await control('operator',0)).body.ok,false,'stale user handoff must fail');
  assert.equal((await control('operator',1)).body.data.revision,2);
  assert.equal((await control('agent',2)).body.data.revision,3);
  const desktop=spawnSync(resolveNeyviaPython(process.cwd()).python,['-m','grant_agent.desktop_bridge','--root',root],
    {input:JSON.stringify({command:'set_host_session_control_command',payload:{sessionId,owner:'operator',expectedRevision:3,_operatorIdentity:'spoofed'}}),
      encoding:'utf8',timeout:15000,env:{...process.env,PYTHONPATH:path.resolve('src')}});
  assert.equal(desktop.status,0,desktop.stderr || desktop.stdout);
  assert.equal(JSON.parse(desktop.stdout).data.operatorIdentity,'local-desktop');
  assert.equal((await control('agent',4)).body.data.revision,5);
  const rejected=spawnSync(resolveNeyviaPython(process.cwd()).python,['-m','grant_agent.desktop_bridge','--root',root],
    {input:JSON.stringify({command:'call_native_tool_command',payload:{tool:'nas.transfer',arguments:{}}}),
      encoding:'utf8',timeout:15000,env:{...process.env,PYTHONPATH:path.resolve('src')}});
  assert.equal(rejected.status,1,'desktop preview bridge must not admit unrelated tools');
  const attempt=spawnSync(resolveNeyviaPython(process.cwd()).python,['-c',
    'import json,sys\nfrom pathlib import Path\nfrom grant_agent.neyvia_agent import NeyviaToolGateway\ng=NeyviaToolGateway(Path(sys.argv[1]),allow_mutations=True,action_scope="stale-control-proof",allowed_mutation_tools={"host.stop"})\nprint(json.dumps(g.call_native("host.stop",{"sessionId":sys.argv[2],"expectedRevision":1,"_actor":"operator"},action_id="stale-stop")))',root,sessionId],
    {encoding:'utf8',timeout:15000,env:{...process.env,PYTHONPATH:path.resolve('src')}});
  assert.equal(attempt.status,0,attempt.stderr);
  assert.equal(JSON.parse(attempt.stdout).ok,false,'agent cannot spoof operator or use an old revision');
  assert.equal((await invoke('host.status',{sessionId})).body.data.result.session.status,'running');
  const stopped=await invoke('host.stop',{sessionId});
  assert.equal(stopped.body.data.ok,true,JSON.stringify(stopped.body));
  for(let i=0;i<50;i++) {
    const session=(await invoke('host.status',{sessionId})).body.data.result.session;
    if(session.status==='stopped') {terminal=true;break;}
    await new Promise(resolve=>setTimeout(resolve,150));
  }
  assert(terminal,'Stop did not complete');
  assert.equal((await invoke('host.inspect_preview',{sessionId,url:endpoint})).body.data.ok,false);
  console.log('PASS: authenticated real app launch, endpoint inspection and persisted hash; no cookie forwarding; redirects/remote URLs/stopped sessions denied; bounded response; stop');
} finally {
  server.kill();
  await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));
  if(terminal || !sessionId) rmSync(root,{recursive:true,force:true});
  else console.error(`Preserved unfinished session: ${root}`);
}
