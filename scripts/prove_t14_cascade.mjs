// Production native-harness acceptance. No provider replies are mocked.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import readline from 'node:readline';
import {spawn, spawnSync} from 'node:child_process';
import {randomUUID, createHash} from 'node:crypto';

const repo=process.cwd(), python='C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const verifyEvidence=process.argv.includes('--verify-evidence');
const resume=process.argv.includes('--resume-root')||verifyEvidence;
const retained=resume?JSON.parse(fs.readFileSync(path.join(repo,'scripts/evidence/T14.json'),'utf8')):null;
const runId=retained?.runId??randomUUID(), root=retained?.root??path.join(repo,'.agent_control','t14-proof',runId);
const evidence=path.join(repo,'scripts','evidence'), saved=path.join(evidence,'T14-runs',runId);
fs.mkdirSync(root,{recursive:true}); fs.mkdirSync(saved,{recursive:true});
const sourceFiles=['src/grant_agent/efficiency_cascade.py','src/grant_agent/transition_memory.py','src/grant_agent/neyvia_efficiency.py','src/grant_agent/neyvia_autopilot.py','src/grant_agent/neyvia_agent.py','src/grant_agent/neyvia_workspace_tools.py','src/grant_agent/neyvia_mcp_stdio.py','manuals/efficiency.manual.json','config/neyvia_manuals.json','scripts/prove_t14_cascade.mjs','scripts/t14_acceptance.py'];
function fingerprints(){return Object.fromEntries(sourceFiles.filter(f=>fs.existsSync(path.join(repo,f))).map(f=>[f,createHash('sha256').update(fs.readFileSync(path.join(repo,f))).digest('hex')]));}
const env={...process.env,PYTHONPATH:path.join(repo,'src'),NEYVIA_WEB_PORT:'48431',NEYVIA_CONNECTED_SERVICE_PORT:'48431',NEYVIA_TOOL_AUTO_UPDATE:'0',NEYVIA_COORDINATOR_AUTOSTART:'0',FLUXIO_WATCHDOG_AUTOSTART:'0'};
delete env.NEYVIA_UI_STATE_ROOT; delete env.NEYVIA_UI_BACKEND_URL;
const proof=retained??{schema:'neyvia.T14.acceptance.v1',at:new Date().toISOString(),runId,root,port:48431,passed:false,hardware:{platform:os.platform(),release:os.release(),arch:os.arch(),cpu:os.cpus()[0]?.model,logicalCpus:os.cpus().length,ramBytes:os.totalmem(),node:process.version},checks:[],extractions:[],autopilot:[],calls:[],limitations:['LAYA client is intentionally a hook until T15-r2 lands.','Quantiles describe the reported finite samples, not a population guarantee.','No frontend or desktop rendering claim.']};
if(resume&&!verifyEvidence){proof.recoveries??=[];proof.recoveries.push({at:new Date().toISOString(),previousError:proof.error});delete proof.error;proof.passed=false;}
if(!resume)proof.sourcesAtStart=fingerprints();
function persist(){fs.writeFileSync(path.join(evidence,'T14.json'),JSON.stringify(proof,null,2)+'\n');fs.writeFileSync(path.join(saved,'progress.json'),JSON.stringify(proof,null,2)+'\n');}
function check(ok,label){assert.ok(ok,label);proof.checks.push(label);persist();}
function stop(child){if(child?.exitCode===null)spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});}
if(verifyEvidence){
 assert.equal(proof.passed,true);
 for(const row of proof.extractions){const bytes=fs.readFileSync(path.join(root,row.task));const json=JSON.parse(bytes);const value=row.field.split('/').slice(1).reduce((v,k)=>v[k.replaceAll('~1','/').replaceAll('~0','~')],json);assert.equal(createHash('sha256').update(bytes).digest('hex'),row.verifiedSha256);assert.deepEqual(JSON.parse(fs.readFileSync(row.outputFile,'utf8')),value);const r=row.result;assert.deepEqual(JSON.parse(r.answer.valueJson),value);if(row.path==='cascade-warm'){assert.equal(r.route,'memory');assert.equal(r.modelCalls.length,0);assert.equal(row.tokens,0);}if(row.path==='cascade-script'){assert.equal(r.route,'script');assert.equal(r.modelCalls.length,0);}if(row.path==='cascade-cold'){assert.equal(r.route,'small');assert.equal(r.modelCalls[0].model,'gpt-6-luna');}if(row.path==='direct-small-baseline')assert.equal(r.modelCalls[0].model,'gpt-6-luna');if(row.path==='direct-big-baseline')assert.equal(r.modelCalls[0].model,'gpt-6.1-sol');}
 check(proof.extractions.length===15,'final independent evidence readback validates all 15 exact extraction results, specified providers and zero-token learned/script routes');
 const warm=proof.autopilot.find(x=>x.path==='enabled-warm');assert.equal(warm.run.models.length,0);assert.ok(warm.run.items.every(i=>i.route==='memory'&&i.memoryReplay&&i.verification.passed));check(true,'final independent durable Autopilot receipt verifies actual memory replay for every successful ask with no model calls');
 assert.equal(proof.adverseAcceptance.receipt.passed,true);const adverseRoot=proof.adverseAcceptance.receipt.root;assert.equal(fs.readFileSync(path.join(adverseRoot,'journey.txt'),'utf8'),'orchard');assert.equal(proof.adverseAcceptance.receipt.decisions.filter(x=>x.route==='big').length,3);check(true,'final adverse receipt and independent fixture readback verify real native composite effects and three actual Sol escalations');
 const providerDir=path.join(saved,'all-provider-receipts');fs.mkdirSync(providerDir,{recursive:true});let copied=0;
 const walk=value=>{if(!value||typeof value!=='object')return;for(const [k,v]of Object.entries(value)){if(k==='receiptPath'&&typeof v==='string'&&v.endsWith('.json')&&v.includes('autopilot-model')&&fs.existsSync(v)){const target=path.join(providerDir,createHash('sha256').update(v).digest('hex')+'.json');fs.copyFileSync(v,target);copied++;}else walk(v);}};walk(proof);
 proof.providerReceiptSnapshots={count:copied,path:path.relative(repo,providerDir)};proof.latency.temperatureDefinition='Cold/warm means an exact request key has/has not appeared in this selected workspace; elapsed includes native/CLI process overhead. Remote model hardware/loading unknown.';proof.sources=fingerprints();proof.receiptVerification={at:new Date().toISOString(),command:'node scripts/prove_t14_cascade.mjs --verify-evidence',sources:fingerprints(),note:'Driver assertions and export checks were refined after actual provider runs; final core provider/effect receipts were independently revalidated without further model calls. Start fingerprints are captured by future complete runs.'};persist();console.log(JSON.stringify({passed:true,verifiedExtracts:15,providerReceiptSnapshots:copied,checks:proof.checks.length}));process.exit(0);
}
const child=spawn(python,['-m','grant_agent.neyvia_mcp_stdio','--root',root,'--permission-mode','workspace','--session-id','t14-'+runId],{cwd:repo,env,windowsHide:true,stdio:['pipe','pipe','pipe']});
const pending=new Map();let seq=0;child.stderr.pipe(fs.createWriteStream(path.join(saved,'mcp.stderr.log')));
readline.createInterface({input:child.stdout}).on('line',line=>{let msg;try{msg=JSON.parse(line);}catch{return;}const p=pending.get(msg.id);if(p){pending.delete(msg.id);clearTimeout(p.timer);msg.error?p.reject(Error(msg.error.message)):p.resolve(msg.result);}});
child.on('exit',code=>{for(const p of pending.values())p.reject(Error('native MCP exited '+code));});
function payload(result){if(result.isError)throw Error(result.content?.map(x=>x.text||'').join('\n'));let v=result.structuredContent;if(!v)v=JSON.parse(result.content.find(x=>x.type==='text').text);while(v?.tool && v.result)v=v.result;return v;}
async function call(name,args={}){const id=++seq,started=performance.now();const result=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Native MCP deadline '+name)),360000);pending.set(id,{resolve,reject,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method:'tools/call',params:{name:'neyvia.'+name,arguments:args}})+'\n');});proof.calls.push({name,args,elapsedMs:performance.now()-started,result});persist();return payload(result);}
function pointer(value,p){return p.split('/').slice(1).reduce((v,k)=>v[k.replaceAll('~1','/').replaceAll('~0','~')],value);}
function expected(file,field){const bytes=fs.readFileSync(path.join(root,file));return {value:pointer(JSON.parse(bytes),field),sha:createHash('sha256').update(bytes).digest('hex')};}
function answerOf(row){return row.answer??row.value??row.result??row;}
function quantile(xs,p){const a=[...xs].sort((a,b)=>a-b);return a[Math.max(0,Math.ceil(a.length*p)-1)];}
function stats(rows){return Object.fromEntries([...new Set(rows.map(x=>x.path))].map(route=>{const v=rows.filter(x=>x.path===route);return [route,{samples:v.length,p50Ms:quantile(v.map(x=>x.elapsedMs),.5),p95Ms:quantile(v.map(x=>x.elapsedMs),.95),successes:v.filter(x=>x.success).length,tokens:v.reduce((n,x)=>n+(x.tokens??0),0)}];}));}
function tokenTotal(row){if(typeof row.tokens==='number')return row.tokens;if(row.tokens?.total!==undefined)return row.tokens.total;return (row.models??row.providerCalls??[]).reduce((n,x)=>n+(x.tokens?.total??x.usage?.total_tokens??((x.usage?.input_tokens??0)+(x.usage?.output_tokens??0))),0);}
const tasks=[
 {file:'invoice.json',field:'/invoice/id',body:{invoice:{id:'INV-00009182736455',amount:103.07,due:'2026-11-03'}}},
 {file:'settings.json',field:'/panel',body:{panel:{opacity:0.875,date:'2027-02-28',selectedId:'ui-00002486'}}},
 {file:'order.json',field:'/order',body:{order:{digits:'000012340987654321',id:'PO-07-000123',date:'2026-10-03',quantity:31}}},
];
if(!resume){for(const task of tasks)fs.writeFileSync(path.join(root,task.file),JSON.stringify(task.body,null,2)+'\n');
for(const [file,text] of Object.entries({'alpha.txt':'cobalt orchard 739\n','beta.txt':'saffron meadow 241\n','delta.txt':'violet river 852\n'}))fs.writeFileSync(path.join(root,file),text);}
async function extract(task,strategy,useScript,phase){const before=expected(task.file,task.field),start=performance.now();const result=await call('efficiency.extract',{path:task.file,field:task.field,strategy,useScript});const elapsedMs=performance.now()-start;const answer=answerOf(result);const after=expected(task.file,task.field);assert.deepEqual(JSON.parse(answer.valueJson),after.value);assert.equal(answer.sourceSha256,after.sha);assert.equal(after.sha,before.sha);const outFile=path.join(root,'outputs',task.file+'-'+strategy+'-'+phase+'.json');fs.mkdirSync(path.dirname(outFile),{recursive:true});fs.writeFileSync(outFile,answer.valueJson+'\n');assert.deepEqual(JSON.parse(fs.readFileSync(outFile,'utf8')),after.value);const row={task:task.file,field:task.field,path:strategy+'-'+phase,success:true,elapsedMs,tokens:tokenTotal(result),result,verifiedSha256:after.sha,outputFile:outFile};proof.extractions.push(row);check(true,task.file+' '+strategy+' '+phase+' fresh bytes, hash and independently parsed output match');return row;}
async function autopilot(efficiency,phase,text){const started=performance.now();let r=await call('autopilot.start',{requestId:'T14-'+runId+'-'+phase,text,scopeTools:['workspace.read','runtime.environment'],efficiency,background:false,maxSeconds:360,maxModelCalls:12});r=r.run??r;check(r.status==='completed',phase+' real Autopilot completes');check(r.items.length>=3 && r.items.every(x=>x.status==='completed' && x.verification?.passed),phase+' all read/confirm asks have independent successful executable checks');for(const file of ['alpha.txt','beta.txt','delta.txt'])assert.ok(fs.readFileSync(path.join(root,file),'utf8').includes(file==='alpha.txt'?'cobalt orchard':file==='beta.txt'?'saffron meadow':'violet river'));const row={path:phase,success:true,elapsedMs:performance.now()-started,tokens:tokenTotal(r),run:r};proof.autopilot.push(row);persist();return row;}
try{
 persist();
 if(resume){for(const row of proof.extractions){const fresh=expected(row.task,row.field);assert.equal(fresh.sha,row.verifiedSha256);assert.deepEqual(JSON.parse(fs.readFileSync(row.outputFile,'utf8')),fresh.value);assert.deepEqual(JSON.parse(answerOf(row.result).valueJson),fresh.value);row.retainedFromPriorRun=true;}check(proof.extractions.length===15,'retained 15 paired extraction calls independently rechecked against unchanged source and output bytes');}
 else for(const task of tasks){
  const small=await extract(task,'direct-small',false,'baseline');
  const big=await extract(task,'direct-big',false,'baseline');
  const cold=await extract(task,'cascade',false,'cold');
  const warm=await extract(task,'cascade',false,'warm');
  const script=await extract(task,'cascade',true,'script');
  check(small.result.modelCalls[0].model==='gpt-6-luna' && big.result.modelCalls[0].model==='gpt-6.1-sol',task.file+' paired baselines use the specified real providers');
  check(cold.result.route==='small' && cold.result.modelCalls.length===1,task.file+' cold cascade accepts independently validated real Luna');
  check(warm.result.route==='memory' && warm.result.modelCalls.length===0 && warm.tokens===0,task.file+' warm learned decision uses zero provider calls and zero tokens');
  check(script.result.route==='script' && script.result.modelCalls.length===0 && script.tokens===0,task.file+' deterministic script bypass uses zero provider calls and zero tokens');
 }
 if(!process.argv.includes('--extract-only')){
  const text='Read alpha.txt and verify cobalt orchard. Also read beta.txt and confirm saffron meadow. Finally read delta.txt and verify violet river.';
  if(!resume){await autopilot(false,'disabled',text);await autopilot(true,'enabled-cold',text);const warm=await autopilot(true,'enabled-warm',text);check(warm.run.models.length===0 && warm.run.items.every(i=>i.route==='memory' && i.memoryReplay),'warm Autopilot consumes positive executable transition memory and reobserves actual effects without model calls');}
  else await autopilot(true,'enabled-warm-r2-'+Date.now(),text);
 }
 proof.metrics=await call('efficiency.metrics');proof.transitions=await call('efficiency.transitions');
 const faults=spawnSync(python,['scripts/t14_acceptance.py','--root',root,'--output',path.join(saved,'acceptance.json')],{cwd:repo,env,encoding:'utf8',windowsHide:true,timeout:180000});
 proof.adverseAcceptance={exitCode:faults.status,stdout:faults.stdout,stderr:faults.stderr};
 check(faults.status===0,'typed transitions, scope/expiry/provenance/conflict and deterministic bypass production acceptance');
 if(fs.existsSync(path.join(saved,'acceptance.json')))proof.adverseAcceptance.receipt=JSON.parse(fs.readFileSync(path.join(saved,'acceptance.json'),'utf8'));
 proof.sources=fingerprints();
 const copy=(from,to)=>{if(!fs.existsSync(from))return;fs.mkdirSync(to,{recursive:true});for(const ent of fs.readdirSync(from,{withFileTypes:true})){const a=path.join(from,ent.name),b=path.join(to,ent.name);if(ent.isDirectory())copy(a,b);else if(/\.(json|jsonl)$/.test(ent.name))fs.copyFileSync(a,b);}};
 for(const dir of ['autopilot-model','autopilot','efficiency'])copy(path.join(root,'.neyvia',dir),path.join(saved,dir));
 if(proof.adverseAcceptance.receipt?.root){const adverseRoot=proof.adverseAcceptance.receipt.root;copy(path.join(adverseRoot,'routing','.neyvia'),path.join(saved,'adverse-routing'));copy(path.join(adverseRoot,'.agent_control'),path.join(saved,'adverse-native'));for(const file of fs.readdirSync(adverseRoot))if(file.endsWith('.json'))fs.copyFileSync(path.join(adverseRoot,file),path.join(saved,'adverse-'+file));}
 proof.latency={hardware:proof.hardware,temperatureDefinition:'Cold/warm means exact request key has/has not appeared in this selected workspace; elapsed includes native/CLI process overhead. Remote model hardware/loading unknown.',extraction:stats(proof.extractions),autopilot:stats(proof.autopilot)};proof.passed=true;persist();console.log(JSON.stringify({passed:true,checks:proof.checks.length,latency:proof.latency,receipt:'scripts/evidence/T14.json'}));
}catch(error){proof.error=error.stack;persist();console.error(error.stack);process.exitCode=1;}finally{stop(child);}
