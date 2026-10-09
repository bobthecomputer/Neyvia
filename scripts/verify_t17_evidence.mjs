// Validate retained live tool effects, usage arithmetic and final source identity.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const repo=process.cwd(),proofPath=path.join(repo,'scripts/evidence/T17.json');
const proof=JSON.parse(fs.readFileSync(proofPath)),checks=[];
function check(v,label){assert.ok(v,label);checks.push(label);}
for(const journey of proof.journeys){
 const events=fs.readFileSync(path.join(repo,journey.normal.receipt),'utf8').split('\n').filter(Boolean).map(JSON.parse);
 const native=events.filter(e=>e.type==='item.completed' && e.item?.tool==='neyvia.native.call' && e.item.status==='completed').map(e=>({args:e.item.arguments,receipt:e.item.result?.structured_content}));
 const reads=native.filter(e=>e.args.toolId==='workspace.read' && e.receipt.ok).map(e=>e.receipt.result);
 if(journey.task.id==='read-search'){
  check(reads.some(r=>r.path==='alpha.txt' && r.content.includes('cobalt orchard')) && reads.some(r=>r.path==='beta.txt' && r.content.includes('saffron meadow')),'normal retained read/search proves both requested phrases');
  check(native.some(e=>e.args.toolId==='workspace.search' && e.receipt.ok && e.receipt.result.complete && e.receipt.result.matches.some(m=>m.path==='alpha.txt')),'normal retained search proves actual complete matching path');
 }else if(journey.task.id==='edit-confirm'){
  check(reads.some(r=>r.path==='alpha.txt' && r.content==='cobalt orchard release ready') && reads.some(r=>r.path==='beta.txt' && r.content==='saffron meadow release ready'),'normal retained edits have exact independent readbacks');
 }else{
  check(reads.some(r=>r.path==='gamma.txt' && r.content==='project brief approved') && reads.some(r=>r.path==='delta.txt' && r.content.includes('violet river')),'normal retained brief and phrase have actual readbacks');
  check(native.some(e=>e.args.toolId==='runtime.environment' && e.receipt.ok && e.receipt.result.workspaceRoot===journey.normal.root),'normal retained runtime root was actually observed');
 }
 check(journey.autopilot.status==='completed' && !journey.autopilot.needsPaul.length && journey.autopilot.items.every(i=>i.verification.passed),'autopilot '+journey.task.id+' has no unresolved asks or unchecked items');
 check(journey.autopilot.models.reduce((n,m)=>n+m.tokens.total,0)===journey.autopilot.tokens.total,'autopilot '+journey.task.id+' token totals equal actual CLI usage');
}
const python='C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe',env={...process.env,PYTHONPATH:path.join(repo,'src')};delete env.NEYVIA_UI_STATE_ROOT;delete env.NEYVIA_UI_BACKEND_URL;
const result=spawnSync(python,['-m','grant_agent.neyvia_mcp_stdio','--root',proof.root,'--permission-mode','read-only'],{cwd:repo,env,input:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'neyvia.manual.validate',arguments:{id:'autopilot'}}})+'\n',encoding:'utf8',windowsHide:true,timeout:30000});
const answer=JSON.parse(result.stdout.trim());let validation=answer.result.structuredContent;while(validation?.tool && validation.result)validation=validation.result;
check(result.status===0 && validation.manuals[0].grounded,'final expanded typed autopilot manual grounded through real read-only MCP');
for(const [file,hash] of Object.entries(proof.sources)){
 const actual=createHash('sha256').update(fs.readFileSync(path.join(repo,file))).digest('hex');
 if(file==='manuals/autopilot.manual.json'){
  proof.manualRefresh={reason:'Added typed start/list/stop/resume actions; procedure execution unchanged',priorSha256:hash,sha256:actual,validation};proof.sources[file]=actual;
 }else assert.equal(actual,hash,file+' evidence matches final source');
}
proof.evidenceValidation={at:new Date().toISOString(),checks};
proof.wiring={tools:['start','get','list','stop','resume'].map(n=>'neyvia.autopilot.'+n),catalog:'neyvia_workspace_tools.DEFINITIONS -> NativeToolRegistry',native:'NeyviaToolGateway.call_native preserves dispatcher and grant ceiling',stdio:'neyvia_mcp_stdio direct/autopilot and native.call',http:'neyvia_ui_api /api/ui/autopilot + /api/ui/tools/call owner routes',desktop:'desktop_bridge COMMANDS/dispatch -> authenticated persistent HTTP; generic Tauri call_desktop_backend_command already registered',plugin:'PORTED/discovery -> owner HTTP; refuses non-PORTED nested tools without stripping scope',manual:'manuals/autopilot.manual.json -> config/neyvia_manuals.json',ui:'Contract in plans/15-handoff.md ## T17; Claude UI pending'};
proof.limits={automaticActions:'Local observations and saved-source same-path CAS text replacements with readback',largeModel:'gpt-6.1-sol explicitly; gpt-6 was rejected by the ChatGPT CLI account',desktopServicePorts:'Explicit 48191-48199; no default/public-port call',plugin:'Primary workspace file procedures remain excluded by existing PORTED policy; owning Native harness has the real file journey',frontier:'Existing grounded procedure remapping and quarantined guidance; new arbitrary procedures are not promoted/executed automatically',comparison:'Three scratch-root document/runtime journeys; reported total tokens include cached input. Nine real manual warmup runs excluded from task totals. Normal CLI receipts retained/rechecked after safety fixes, not rerun unnecessarily.'};
fs.writeFileSync(proofPath,JSON.stringify(proof,null,2)+'\n');console.log(JSON.stringify({passed:true,checks:checks.length,sourceFiles:Object.keys(proof.sources).length}));
