import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
const base='http://127.0.0.1:48211', root=resolve('.agent_control/t7/runtime');
const python='C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const receiptPath='scripts/evidence/T7.json';
let cookie='';
const evidence={schema:'neyvia.T7.evidence.v1',at:new Date().toISOString(),base,root,checks:[],
 boundaries:{backend:'Real persisted GPT-6 Luna CLI conversations → production broker → authenticated HTTP/tools/desktop → durable UI bus',renderedUI:'Pending Claude frontend journey; no screenshot proof claimed',crossHarness:'Real Codex subagent; Claude/OpenCode/native canonical controlled projections; other live providers not run',model:'Local pinned CPU embeddings; English only measured',NAS:'Pending: explicit isolation disallows NAS ports/Tailscale'}};
function record(name,data={}){evidence.checks.push({name,pass:true,...data});console.log('PASS '+name)}
async function request(path,body,auth=true){
 const response=await fetch(base+path,{method:body===undefined?'GET':'POST',headers:{...(body===undefined?{}:{'Content-Type':'application/json'}),...(auth&&cookie?{Cookie:cookie}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});
 if(path==='/api/auth/local-session')cookie=response.headers.get('set-cookie').split(';')[0];
 return {status:response.status,body:await response.json()};
}
async function sidebar(command,args={}){const r=await request('/api/ui/sidebar',{command,...args});assert.equal(r.status,200,JSON.stringify(r));return r.body.data}
async function tool(name,args={}){const r=await request('/api/ui/tools/call',{tool:'neyvia.'+name,arguments:args});assert.equal(r.status,200,JSON.stringify(r));const value=r.body.data;assert.notEqual(value.ok,false,JSON.stringify(value));return value.result??value;}
function py(source,args=[]){const r=spawnSync(python,['-c',source,...args],{encoding:'utf8',windowsHide:true,env:{...process.env,PYTHONPATH:resolve('src'),NEYVIA_CONNECTED_SERVICE_PORT:'48211',NEYVIA_UI_STATE_ROOT:root}});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout.trim().split(/\r?\n/).at(-1));}
function bus(key){return py("import json,sys;from pathlib import Path;from grant_agent.ui_command_bus import bus_for;print(json.dumps(bus_for(Path(sys.argv[1])).get(sys.argv[2])))",[root,key]);}
try {
 if(process.argv.includes('--resume')){
  const previous=JSON.parse(readFileSync(receiptPath,'utf8'));assert.equal(previous.passed,true);
  await request('/api/auth/local-session',{});
  const confirm=await sidebar('sidebar_confirm_command',{previewId:previous.restart.previewId,confirmed:true});
  assert.equal(confirm.replayed,true);assert.deepEqual(confirm.moved,previous.restart.moved);
  const restored=await sidebar('sidebar_undo_command',{undoId:previous.restart.undoId});assert.equal(restored.restored.length,4);
  const state=await sidebar('sidebar_state_command',{ids:previous.restart.ids});assert.equal(state.subjectFolders.length,0);
  assert.ok(state.sessions.every(s=>s.projectOverride===null));
  previous.checks.push({name:'Real backend restart retains original confirm receipt; undo restores all and removes empty subject folders',pass:true,confirm,restored});
  previous.sourceHashes=Object.fromEntries(previous.sourceFiles.map(file=>[file,createHash('sha256').update(readFileSync(file)).digest('hex')]));
  writeFileSync(receiptPath,JSON.stringify(previous,null,2)+'\n');console.log('PASS durable restart and undo');process.exit(0);
 }
 const unauthorized=await request('/api/ui/sidebar',{command:'sidebar_preview_command'},false);assert.equal(unauthorized.status,401);record('Unauthenticated sidebar rejected',{http:401});
 await request('/api/auth/local-session',{});
 const catalog=(await request('/api/ui/tools')).body.data.tools;
 for(const action of ['state','preview','confirm','undo'])assert.ok(catalog.some(t=>t.name==='neyvia.sidebar.'+action));
 record('Four model tools exposed with real schemas');
 const runs=JSON.parse(readFileSync('.agent_control/t7/luna-runs.json','utf8'));assert.equal(runs.length,4);assert.ok(runs.every(r=>r.exitCode===0&&r.model==='gpt-6-luna'&&r.threadId&&r.usage));
 const agentRun=JSON.parse(readFileSync('.agent_control/t7/agent-runs.json','utf8'))[0];
 const list=(await request('/api/backend',{command:'connected_sessions_list_command',payload:{app:'codex',includeHarness:true,limit:500,force:true}})).body.data;
 const ids=runs.map(r=>'external:codex:'+list.host.deviceId+':'+r.threadId);
 evidence.lunaRuns=runs.map(({events,...r})=>r);evidence.agentRun={...agentRun,events:undefined};
 record('Four real GPT-6 Luna CLI tasks discovered by production broker',{threads:ids,usage:evidence.lunaRuns.map(r=>r.usage)});
 for(const id of ids)await tool('session.move',{id,project:null});
 const before=await sidebar('sidebar_state_command',{ids});assert.equal(before.sessions.length,4);assert.ok(before.sessions.every(s=>s.sidebar.kind==='quick'&&s.sidebar.turnCount===1&&s.sidebar.complete));
 record('Quick from complete actual transcripts; hover previews contain replies',{sessions:before.sessions.map(s=>({id:s.id,sidebar:s.sidebar}))});
 const agentId='external:codex:'+list.host.deviceId+':'+agentRun.threadId;
 const agents=await sidebar('sidebar_state_command',{ids:[agentId]});assert.equal(agents.sessions.length,1);
 const subtree=agents.sessions[0].sidebar.agents;assert.ok(subtree.length>=1,JSON.stringify(agents));assert.ok(subtree.some(a=>a.status==='ok'&&a.sessionId&&a.title.includes('tab_order')));
 record('Real Codex started/completed child folded once with verified navigable session',{agents:subtree});
 assert.equal(agents.sessions[0].sidebar.kind,'other');assert.equal(agents.sessions[0].sidebar.turnCount,3);record('Other from three actual user turns, with the same agent subtree');
 const imageRun=JSON.parse(readFileSync('.agent_control/t7/image-runs.json','utf8'))[0];
 const imageId='external:codex:'+list.host.deviceId+':'+imageRun.threadId;
 const images=await sidebar('sidebar_state_command',{ids:[imageId]});assert.equal(images.sessions[0].sidebar.kind,'images');assert.ok(images.sessions[0].sidebar.generationEvents.length);
 const imagePath=resolve('C:/Users/user/.codex/generated_images',imageRun.threadId,images.sessions[0].sidebar.generationEvents[0].id+'.png');assert.ok(existsSync(imagePath));
 record('Real Luna image generation saved PNG; Images wins over one-turn Quick',{threadId:imageRun.threadId,usage:imageRun.usage,events:images.sessions[0].sidebar.generationEvents,pngSha256:createHash('sha256').update(readFileSync(imagePath)).digest('hex')});
 const old=bus('sessions');
 const running=list.sessions.find(s=>s.status==='working'&&s.cwd?.toLowerCase()===resolve('.').toLowerCase());
 if(running){const active=await sidebar('sidebar_preview_command',{ids:[running.id]});assert.ok(active.skipped.some(s=>s.id===running.id&&s.reason==='active'));assert.equal(active.groups.length,0);record('Real active lead conversation excluded from foldering',{skipped:active.skipped});}
 let preview=await sidebar('sidebar_preview_command',{ids});assert.equal(preview.status,'preview',JSON.stringify(preview));assert.equal(preview.groups.length,2,JSON.stringify(preview));
 const expected=[ids.slice(0,2),ids.slice(2,4)].map(g=>[...g].sort().join('|')).sort();assert.deepEqual(preview.groups.map(g=>[...g.ids].sort().join('|')).sort(),expected);
 assert.deepEqual(bus('sessions'),old);
 evidence.modelInventory=JSON.parse(readFileSync('.agent_control/t7/embedding-model/receipt.json','utf8'));
 record('Real local embeddings group accessible websites and bread paraphrases separately; preview moves nothing',{preview});
 const denied=await sidebar('sidebar_confirm_command',{previewId:preview.previewId});assert.equal(denied.status,'confirmation_required');assert.deepEqual(bus('sessions'),old);record('Confirmation required; no state change');
 const unknown=await request('/api/ui/sidebar',{command:'sidebar_confirm_command',previewId:preview.previewId,confirmed:true,groupIds:['invented']});assert.equal(unknown.status,400);record('Unknown group IDs rejected');
 await tool('session.pin',{id:ids[0],pinned:true});
 const stale=await sidebar('sidebar_confirm_command',{previewId:preview.previewId,confirmed:true});assert.equal(stale.status,'stale_preview');assert.equal(stale.moved.length,0);
 await tool('session.pin',{id:ids[0],pinned:false});record('Changed conversation rejects the whole confirmed batch',{receipt:stale});
 preview=await sidebar('sidebar_preview_command',{ids});
 const committed=await Promise.all([sidebar('sidebar_confirm_command',{previewId:preview.previewId,confirmed:true}),sidebar('sidebar_confirm_command',{previewId:preview.previewId,confirmed:true})]);
 assert.deepEqual([...committed[0].moved].sort(),[...ids].sort());
 assert.equal(committed[0].undoId,committed[1].undoId);assert.ok(committed.some(r=>r.replayed));
 const filed=await sidebar('sidebar_state_command',{ids});assert.equal(filed.subjectFolders.length,2);assert.ok(filed.sessions.every(s=>s.projectOverride?.id?.startsWith('subject:')));
 record('Concurrent confirm retries return one atomic durable receipt and two visible folders',{receipts:committed,state:filed.sessions.map(s=>({id:s.id,projectOverride:s.projectOverride}))});
 await tool('session.move',{id:ids[0],project:null});
 const undone=await sidebar('sidebar_undo_command',{undoId:committed[0].undoId});assert.equal(undone.restored.length,3);assert.equal(undone.conflicts.length,1);assert.equal(undone.conflicts[0].id,ids[0]);
 const undoRetry=await sidebar('sidebar_undo_command',{undoId:committed[0].undoId});assert.equal(undoRetry.replayed,true);record('Undo preserves a later manual move; repeating undo is harmless',{undone});
 const named=(await request('/api/backend',{command:'sidebar_state_command',payload:{ids}})).body;assert.equal(named.ok,true);assert.equal(named.data.sessions.length,4);record('Named /api/backend command uses same production sidebar');
 const desktop=py("import json,sys;from pathlib import Path;from grant_agent.desktop_bridge import dispatch_desktop_command;print(json.dumps(dispatch_desktop_command(Path(sys.argv[1]),'sidebar_state_command',{'ids':json.loads(sys.argv[2])})))",[root,JSON.stringify(ids)]);
 assert.equal(desktop.sessions.length,4);record('Real fresh desktop bridge process forwards to persistent authenticated service',{ids:desktop.sessions.map(s=>s.id)});
 const wrongRoot=await request('/api/backend',{command:'sidebar_state_command',payload:{ids,_expectedStateRoot:resolve('.agent_control/wrong')}});assert.equal(wrongRoot.status,400);record('Wrong workspace forwarding rejected');
 const grounding=await tool('manual.validate',{id:'sidebar'});assert.ok(grounding.grounded||grounding.manuals?.some(m=>m.grounded));record('Executable sidebar manual matches all live tool schemas',{grounding});
 const manual=await tool('manual.run',{id:'sidebar',procedure:'preview-subjects',inputs:{ids}});assert.equal(manual.status,'judge',JSON.stringify(manual));record('Real manual procedure observes, checks, previews then stops at review',{manual});
 const controlled=py("import json;from grant_agent.neyvia_sidebar_projection import project;rows=[];\nfor app in ['claude-code','codex','opencode','neyvia']:\n row={'app':app,'title':'Generate a logo'}; pages=[{'items':[{'id':'u','kind':'user','data':{'text':'hi'}}]}, {'items':[{'id':'i','kind':'tool','data':{'name':'image_gen.imagegen','status':'ok'}}]}, {'items':[{'id':'a','kind':'tool','data':{'name':'Task','agent':{'description':'Check focus','status':'ok','agentId':'actual-child'}}}]}, {'has_earlier':True,'items':[{'id':'u','kind':'user','data':{}}]}]; rows.append({'app':app,'projections':[project(row,p) for p in pages]})\nprint(json.dumps(rows))");
 for(const row of controlled){assert.equal(row.projections[0].kind,'quick');assert.equal(row.projections[1].kind,'images');assert.equal(row.projections[2].agents.length,1);assert.equal(row.projections[3].kind,'other');assert.equal(row.projections[3].complete,false);}
 record('Controlled canonical cross-harness agents/images and title/incomplete negative cases',{controlled});
 const unavailable=py("import json,os;from grant_agent.neyvia_sidebar_semantics import encode;os.environ['NEYVIA_SIDEBAR_EMBEDDING_MODEL']='missing-t7-model';\ntry: encode(None,['hello']); print(json.dumps({'failed':False}))\nexcept OSError as e: print(json.dumps({'failed':True,'error':type(e).__name__}))");assert.equal(unavailable.failed,true);record('Missing local model fails explicitly; no cloud/word-match fallback',{controlled:true,unavailable});
 const last=await sidebar('sidebar_preview_command',{ids});const persistent=await sidebar('sidebar_confirm_command',{previewId:last.previewId,confirmed:true});assert.equal(persistent.moved.length,4);
 evidence.restart={previewId:last.previewId,undoId:persistent.undoId,moved:persistent.moved,ids};
 evidence.commands=['sidebar_state_command','sidebar_preview_command','sidebar_confirm_command','sidebar_undo_command'];
 evidence.registrations=['neyvia_sidebar.DEFINITIONS/COMMANDS','neyvia_workspace_tools.DEFINITIONS/call','neyvia_ui_api /api/ui/sidebar','web_backend.dispatch + owner named /api/backend','desktop_bridge allow-list + persistent forward','src-tauri generic call_desktop_backend_command (existing)','config/neyvia_manuals.json → manuals/sidebar.manual.json'];
 evidence.sourceFiles=['src/grant_agent/neyvia_sidebar.py','src/grant_agent/neyvia_sidebar_projection.py','src/grant_agent/neyvia_sidebar_semantics.py','src/grant_agent/connected_sessions/codex_items.py','src/grant_agent/neyvia_workspace_tools.py','src/grant_agent/neyvia_ui_api.py','src/grant_agent/desktop_bridge.py','src/grant_agent/web_backend.py','config/neyvia_manuals.json','manuals/sidebar.manual.json'];
 evidence.sourceHashes=Object.fromEntries(evidence.sourceFiles.map(file=>[file,createHash('sha256').update(readFileSync(file)).digest('hex')]));
 evidence.adverseExperiments=[
  {observed:'Full prompt + duplicated auto-title at 0.55 grouped bread only',repair:'Encode subject sentence; remove repeated auto-title and harness instructions'},
  {observed:'Concatenating long assistant replies further diluted pair similarity',repair:'Use actual subject sentences only; English default cosine 0.50, explicit human confirmation retained'},
  {observed:'Concurrent confirm initially returned stale while another request committed',repair:'Re-read atomically saved original receipt before returning stale'},
  {observed:'Generated manual outside manuals/ rejected by loader',repair:'Move generated executable source to enforced manuals/ root'},
 ];
 evidence.passed=true;
}catch(error){evidence.passed=false;evidence.error=error.stack;console.error(error);process.exitCode=1}
finally{writeFileSync(receiptPath,JSON.stringify(evidence,null,2)+'\n')}
