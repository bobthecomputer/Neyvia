// Matched Haiku comparison and zero-model-token execution on six real Notes/Files tasks.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
const repo=process.cwd(),python='C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const base=process.env.RECOVERY_BACKEND||'http://127.0.0.1:48186';
const root=path.resolve(process.env.RECOVERY_ROOT||'tmp/r-proof');
const out=path.resolve(process.env.RECOVERY_EVIDENCE||'scripts/evidence/manual-recovery.json');
const repeats=Number(process.env.RECOVERY_REPEATS||2);
const suite=process.env.RECOVERY_SUITE||path.join(root,'bench-'+Date.now());fs.mkdirSync(suite,{recursive:true});fs.mkdirSync(path.dirname(out),{recursive:true});
let cookie='';
function unwrap(v){while(v?.tool&&v.result&&typeof v.result==='object')v=v.result;return v;}
async function tool(name,args={}){
 if(!cookie){const r=await fetch(base+'/api/auth/local-session',{method:'POST',body:'{}',headers:{'Content-Type':'application/json'}});assert(r.ok);cookie=r.headers.get('set-cookie').split(';')[0];}
 const r=await fetch(base+'/api/ui/tools/call',{method:'POST',body:JSON.stringify({tool:name,arguments:args}),headers:{'Content-Type':'application/json',Cookie:cookie},signal:AbortSignal.timeout(90000)});
 const v=await r.json();assert(r.ok,JSON.stringify(v));return unwrap(v.data);
}
const setup=spawnSync(python,['-c',String.raw`
import json,sys
from pathlib import Path
sys.path.insert(0,'src')
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_manuals import get_manual,validate,render
r=NativeToolRegistry(Path(sys.argv[1]));data=get_manual('handoff-recovery')[2];validate(data,r)
names=['neyvia.notes.read','neyvia.notes.write','neyvia.notes.pin','neyvia.files.stat','neyvia.files.move','neyvia.files.undo','neyvia.manual.run']
print(json.dumps({'tools':[r.describe(n) for n in names],'manual':render(data['chapters']['intake'],data['schemas']),'manualSha256':get_manual('handoff-recovery')[1]}))
`,root],{cwd:repo,encoding:'utf8',windowsHide:true});assert.equal(setup.status,0,setup.stderr);
const catalog=JSON.parse(setup.stdout),catalogPath=path.join(suite,'catalog.json');fs.writeFileSync(catalogPath,JSON.stringify(catalog));
const evidence={protocol:'Six environment-specific handoff tasks; identical prompt, schemas, Haiku route and isolated fixtures. Only manual text differs. Two fresh repeats; fixed state scoring, no response-based grading. Extra manual information is intentional; no general model improvement claimed.',backend:base,sourceHead:spawnSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).stdout.trim(),tokenAccounting:'Provider cumulative input + cache creation + cache read + output; repeated context counted.',repeats,modelRuns:[],deterministicRuns:[]};
function persist(){fs.writeFileSync(out,JSON.stringify(evidence,null,2)+'\n');}
if(process.env.RECOVERY_SUITE&&fs.existsSync(out)){Object.assign(evidence,JSON.parse(fs.readFileSync(out,'utf8')));delete evidence.error;evidence.scoringRepair='Missing moved fixture files score false; original model logs retained and rescored, no model retry.';}
async function fixture(arm,repeat){
 const prefix=path.basename(suite)+'-'+arm+'-'+repeat+'-',folder=path.join(suite,arm+'-'+repeat);fs.mkdirSync(folder,{recursive:true});
 const existing=path.join(folder,'fixture.json');if(process.env.RECOVERY_SUITE&&fs.existsSync(existing))return {...JSON.parse(fs.readFileSync(existing,'utf8')),file:existing};
 const tasks=[];
 const specs=[['approved','Apply the approved handoff intake to this reviewed draft.','stage-reviewed','#ready'],['pending','Apply handoff intake to this draft; review is still pending.','record-review','#needs-review'],['stale','Capture this handoff message while a second editor may be active.','capture-once','#ready'],['collision','Stage this reviewed draft at its requested destination; that destination already contains another draft.','record-blocked','#blocked'],['duplicate','Capture this handoff message; it may already be recorded.','capture-once','#ready'],['undo','Undo staging of this selected draft. Another Files operation happened afterward; preserve that operation.','restore-selected','#restored']];
 for(const [id,request,procedure,tag]of specs){
  const note=prefix+id+'.md',message='Handoff '+id+' '+tag;
  await tool('neyvia.notes.write',{path:note,body:'# Intake\n\nOriginal notebook paragraph.'+(id==='duplicate'?'\n\n'+message:'')});
  const dir=path.join(folder,id);fs.mkdirSync(dir);const source=path.join(dir,'draft.txt'),target=path.join(dir,'review.txt');
  fs.writeFileSync(source,'Original '+id+' draft.');
  if(id==='collision')fs.writeFileSync(target,'Existing reviewed draft.');
  if(id==='undo'){
   assert((await tool('neyvia.files.move',{from:source,to:target})).ok!==false);
   const unrelated=path.join(dir,'unrelated.txt'),moved=path.join(dir,'unrelated-moved.txt');fs.writeFileSync(unrelated,'Unrelated operation.');
   assert((await tool('neyvia.files.move',{from:unrelated,to:moved})).ok!==false);
  }
  tasks.push({id,request,procedure,inputs:{path:note,message,source:id==='undo'?target:source,target:id==='undo'?source:target},tag});
 }
 const f={prefix,folder,tasks};const file=path.join(folder,'fixture.json');fs.writeFileSync(file,JSON.stringify(f));return {...f,file};
}
async function score(f,trace){
 const read=p=>fs.existsSync(p)?fs.readFileSync(p,'utf8'):null;
 const results=[];for(const t of f.tasks){
  const state=await tool('neyvia.notes.read',{path:t.inputs.path}),body=state.body||'';
  const guardedWrites=trace.filter(r=>r.tool==='neyvia.notes.write'&&r.args.path===t.inputs.path&&r.result.ok!==false);
  const manualRuns=trace.filter(r=>r.tool==='neyvia.manual.run'&&(r.args.inputs?.path===t.inputs.path||r.result.inputs?.path===t.inputs.path));
  const protectedWrite=guardedWrites.every(r=>r.args.mode==='append'&&Boolean(r.args.expectedModified))&&(guardedWrites.length>0||manualRuns.length>0||t.id==='duplicate');
  let semantic=body.includes('Original notebook paragraph.'),protocol=body.split(t.inputs.message).length===2;
  if(t.id!=='duplicate')protocol=protocol&&state.pinned===true&&protectedWrite;
  if(t.id==='approved')semantic=semantic&&!fs.existsSync(t.inputs.source)&&read(t.inputs.target)==='Original approved draft.';
  if(t.id==='pending')semantic=semantic&&read(t.inputs.source)==='Original pending draft.'&&!fs.existsSync(t.inputs.target);
  if(t.id==='collision')semantic=semantic&&read(t.inputs.source)==='Original collision draft.'&&read(t.inputs.target)==='Existing reviewed draft.';
  if(t.id==='stale')semantic=semantic&&body.includes('Concurrent editor paragraph.');
  if(t.id==='duplicate')semantic=semantic&&body.split(t.inputs.message).length===2&&guardedWrites.length===0;
  if(t.id==='undo')semantic=semantic&&!fs.existsSync(t.inputs.source)&&read(t.inputs.target)==='Original undo draft.'&&fs.existsSync(path.join(path.dirname(t.inputs.target),'unrelated-moved.txt'))&&!fs.existsSync(path.join(path.dirname(t.inputs.target),'unrelated.txt'));
  results.push({task:t.id,semantic,protocol,success:semantic&&protocol,note:state,guardedWrites:guardedWrites.length,manualRuns:manualRuns.map(r=>({status:r.result.status,runId:r.result.runId}))});
 }return results;
}
async function modelRun(arm,repeat){
 const f=await fixture(arm,repeat),tracePath=path.join(f.folder,'trace.jsonl'),logPath=path.join(f.folder,'haiku.jsonl'),errPath=path.join(f.folder,'haiku.stderr');
 const config=path.join(f.folder,'mcp.json');fs.writeFileSync(config,JSON.stringify({mcpServers:{recovery:{command:process.execPath,args:[path.join(repo,'scripts/manual-recovery-mcp.mjs')],env:{RECOVERY_BACKEND:base,RECOVERY_FIXTURE:f.file,RECOVERY_CATALOG:catalogPath,RECOVERY_TRACE:tracePath}}}}));
 const launcher=spawnSync('where.exe',['claude'],{encoding:'utf8'}).stdout.trim().split(/\r?\n/)[0],entry=path.join(path.dirname(launcher),'node_modules/@anthropic-ai/claude-code/bin/claude.exe');assert(fs.existsSync(entry));
 const prompt='Perform these six independent Notes/Files tasks under the workspace handoff protocol. Preserve unrelated bytes. Record receipts in the selected notes. Do not guess missing protocol; report a stop if needed. Use real tools; stop at unresolved judgement. Each task provides note, message and selected source/target.\n'+JSON.stringify(f.tasks.map(({id,request,inputs})=>({id,request,inputs})))+(arm.startsWith('manual')?'\nGrounded handoff protocol manual:\n'+catalog.manual:'');
 const start=Date.now();let exitCode=0,reused=false;
 if(process.env.RECOVERY_SUITE&&fs.existsSync(logPath)&&fs.readFileSync(logPath,'utf8').split('\n').some(l=>{try{return JSON.parse(l).type==='result';}catch{return false;}}))reused=true;
 else{
  const cli=spawn(entry,['--print','--verbose','--output-format','stream-json','--model','haiku','--effort','low','--no-session-persistence','--no-chrome','--disable-slash-commands','--setting-sources','','--strict-mcp-config','--mcp-config',config,'--tools','','--permission-mode','dontAsk','--allowedTools','mcp__recovery__*','--system-prompt','Act only through the supplied scratch tools in this isolated benchmark. No other files, services, agents or providers.','--',prompt],{cwd:f.folder,windowsHide:true,env:{...process.env,CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:'1'}});
  const log=fs.createWriteStream(logPath),err=fs.createWriteStream(errPath);cli.stdout.pipe(log);cli.stderr.pipe(err);
  exitCode=await new Promise((resolve,reject)=>{cli.once('error',reject);cli.once('exit',resolve);});await Promise.all([new Promise(r=>log.end(r)),new Promise(r=>err.end(r))]);
 }
 const lines=fs.readFileSync(logPath,'utf8').split('\n').filter(Boolean).map(l=>{try{return JSON.parse(l);}catch{return{};}}),final=lines.findLast(r=>r.type==='result')||{},usage=final.usage||{};
 const trace=fs.existsSync(tracePath)?fs.readFileSync(tracePath,'utf8').trim().split('\n').filter(Boolean).map(JSON.parse):[];
 const scores=await score(f,trace),actualModel=lines.find(r=>r.type==='system'&&r.subtype==='init')?.model||Object.keys(final.modelUsage||{})[0];
 assert(/^claude-haiku-/.test(actualModel||''),'Haiku model identity must be reported, no substitution');
 const row={arm,repeat,requestedModel:'haiku',actualModel,exitCode,isError:final.is_error||false,totalTokens:['input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens'].reduce((n,k)=>n+(usage[k]||0),0),usage,modelUsage:final.modelUsage,latencyMs:reused?final.duration_ms:Date.now()-start,reusedOriginalLog:reused,scores,successes:scores.filter(s=>s.success).length,semanticSuccesses:scores.filter(s=>s.semantic).length,finalText:final.result,trace,logPath,error:fs.readFileSync(errPath,'utf8').slice(-1500)};
 evidence.modelRuns.push(row);persist();console.log(JSON.stringify({arm,repeat,actualModel,successes:row.successes,semanticSuccesses:row.semanticSuccesses,totalTokens:row.totalTokens,latencyMs:row.latencyMs}));
}
async function deterministic(repeat){
 const f=await fixture('procedures',repeat),trace=[],start=Date.now();
 for(const t of f.tasks){
  let run=await tool('neyvia.manual.run',{id:'handoff-recovery',chapter:'intake',procedure:t.procedure,inputs:t.inputs});trace.push({tool:'neyvia.manual.run',args:{inputs:t.inputs},result:run});
  if(t.id==='stale'){
   const note=await tool('neyvia.notes.read',{path:t.inputs.path});await tool('neyvia.notes.write',{path:t.inputs.path,body:'Concurrent editor paragraph.',mode:'append',expectedModified:note.modified});
  }
  const choose=t.id==='duplicate'?'skip':t.id==='approved'?'approved':t.id==='undo'?'restore':'record';
  if(run.status==='judge'){run=await tool('neyvia.manual.run',{id:'handoff-recovery',chapter:'intake',procedure:t.procedure,runId:run.runId,decisions:{[run.judge.id]:choose}});trace.push({tool:'neyvia.manual.run',args:{inputs:t.inputs},result:run});}
  if(t.id==='stale'){
   assert.equal(run.status,'failed','stale attempt must fail its check');const blocked=await tool('neyvia.manual.run',{id:'handoff-recovery',chapter:'intake',procedure:t.procedure,runId:run.runId});assert.equal(blocked.status,'blocked');
   run=await tool('neyvia.manual.run',{id:'handoff-recovery',chapter:'intake',procedure:t.procedure,inputs:t.inputs});
   run=await tool('neyvia.manual.run',{id:'handoff-recovery',chapter:'intake',procedure:t.procedure,runId:run.runId,decisions:{[run.judge.id]:'record'}});trace.push({tool:'neyvia.manual.run',args:{inputs:t.inputs},result:run});
  }
  assert.equal(run.status,'completed',JSON.stringify(run));
 }
 const scores=await score(f,trace);evidence.deterministicRuns.push({repeat,modelTokens:0,decisionSource:'Predeclared fixture decisions, not model inference; human judgement cost excluded.',latencyMs:Date.now()-start,scores,successes:scores.filter(s=>s.success).length,trace});persist();console.log('procedures repeat '+repeat+': '+scores.filter(s=>s.success).length+'/6; model tokens 0');
}
try{
 for(let i=1;i<=repeats;i++)if(!evidence.deterministicRuns.some(r=>r.repeat===i))await deterministic(i);
 if(process.argv.includes('--manual-v2')){
  evidence.manualRepair='The initial compact renderer hid typed step arguments and workflow guidance. V2 exposes both; same six tasks, scoring and tools. Original failed manual runs retained. Baseline runs reused for comparison, not retried.';
  evidence.manualSha256=catalog.manualSha256;
  for(let i=1;i<=repeats;i++)if(!evidence.modelRuns.some(r=>r.arm==='manual-v2'&&r.repeat===i))await modelRun('manual-v2',i);
 }else if(!process.argv.includes('--procedures-only'))for(let i=1;i<=repeats;i++)for(const arm of i%2?['baseline','manual']:['manual','baseline'])if(!evidence.modelRuns.some(r=>r.arm===arm&&r.repeat===i))await modelRun(arm,i);
 evidence.complete=true;persist();
}catch(e){evidence.complete=false;evidence.error=String(e.stack);persist();throw e;}
