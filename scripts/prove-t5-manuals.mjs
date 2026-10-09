// Real stdio MCP journeys. Assertions belong to this Node acceptance driver.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import {spawn, spawnSync} from 'node:child_process';
import {randomUUID} from 'node:crypto';

const repo=process.cwd(), python='C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const root=path.join(repo,'.agent_control','t5-proof',randomUUID());
fs.mkdirSync(root,{recursive:true});
const calls=[],checks=[];
function require(value,label){assert.ok(value,label);checks.push(label);}
function client(){
  const child=spawn(python,['-m','grant_agent.neyvia_mcp_stdio','--root',root,'--permission-mode','workspace','--session-id','t5-proof'],
    {cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},windowsHide:true,stdio:['pipe','pipe','pipe']});
  let id=0,stderr='';const pending=new Map();
  child.stderr.on('data',chunk=>{stderr+=chunk;});
  readline.createInterface({input:child.stdout}).on('line',line=>{
    let answer;try{answer=JSON.parse(line);}catch{throw new Error(line);}
    const waiter=pending.get(answer.id);if(!waiter)return;
    pending.delete(answer.id);clearTimeout(waiter.timer);waiter.resolve(answer);
  });
  child.on('exit',code=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error(`MCP exited ${code}: ${stderr}`));}});
  return {async call(name,args={}){
    const request={jsonrpc:'2.0',id:++id,method:'tools/call',params:{name:'neyvia.'+name,arguments:args}};
    const answer=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('MCP timed out: '+name)),90000);pending.set(request.id,{resolve,reject,timer});child.stdin.write(JSON.stringify(request)+'\n');});
    calls.push({name:request.params.name,arguments:args,answer});
    if(answer.error)throw new Error(answer.error.message);
    let value=answer.result.structuredContent;
    while(value?.tool && value.result){if(value.ok===false)throw new Error(value.error || value.status);value=value.result;}
    return value;
  },async close(){child.stdin.end();await new Promise(resolve=>child.on('exit',resolve));}};
}
let api=client();
async function denied(operation,label){let error;try{await operation();}catch(exc){error=exc.message;}require(error,label);return error;}
const runArgs={id:'workspace',chapter:'files',procedure:'read-and-confirm'};
try{
  const validated=await api.call('manual.validate');require(validated.manuals.every(x=>x.grounded),'all registered manuals grounded against actual tools');
  const inspectScripts=await api.call('manual.run',{id:'manuals-next',chapter:'scripts',procedure:'inspect-scripts',inputs:{}});
  require(inspectScripts.status==='judge' && inspectScripts.checks[0].passed,'new executable manual verifies scripts and exposes explicit selection judgement');
  require((await api.call('manual.run',{id:'manuals-next',chapter:'scripts',procedure:'inspect-scripts',runId:inspectScripts.runId,decisions:{'script-choice':'recompile'}})).status==='completed','script inspection resumes with explicit choice');
  const inspectHistory=await api.call('manual.run',{id:'manuals-next',chapter:'versions',procedure:'inspect-history',inputs:{id:'workspace'}});
  require(inspectHistory.status==='judge' && inspectHistory.checks[0].passed,'new executable manual verifies version history and exposes patch review judgement');
  require((await api.call('manual.run',{id:'manuals-next',chapter:'versions',procedure:'inspect-history',runId:inspectHistory.runId,decisions:{'patch-review':'quarantine'}})).status==='completed','version inspection resumes with explicit review choice');
  const large='row: orchard 739 '+('0123456789abcdef\n'.repeat(900));
  fs.writeFileSync(path.join(root,'large.txt'),large);
  fs.writeFileSync(path.join(root,'small.txt'),'orchard original\n');
  const observeArgs={id:'workspace',chapter:'files',state:'current',inputs:{path:'large.txt'},stream:'large'};
  const first=await api.call('manual.observe',observeArgs);
  require(first.mode==='handle' && !first.observed && JSON.stringify(first).length<1000,'large live file observation returns compact durable handle');
  const projection=await api.call('manual.project',{handle:first.handle,path:'/content',offset:0,limit:100});
  require(projection.value===large.slice(0,100) && projection.nextOffset===100,'handle projects exact selected file characters');
  fs.appendFileSync(path.join(root,'large.txt'),'changed end\n');
  const second=await api.call('manual.observe',observeArgs);
  require(second.mode==='diff' && second.previousHandle===first.handle && second.diffHandle,'large delta uses a handle instead of pasting changed content');
  let contentIndex;
  for(let i=0;i<second.changes;i++){
    const item=await api.call('manual.project',{handle:second.diffHandle,path:`/${i}/path`});
    if(item.value==='/content')contentIndex=i;
  }
  require(Number.isInteger(contentIndex),'large delta identifies actual changed content field');
  const delta=await api.call('manual.project',{handle:second.diffHandle,path:`/${contentIndex}`,offset:0,limit:100});
  require(delta.tooLarge===true,'oversized projection refuses payload and asks for deeper selection');
  const exactDelta=await api.call('manual.project',{handle:second.diffHandle,path:`/${contentIndex}/value`,offset:0,limit:60});
  require(typeof exactDelta.value==='string','delta content can itself be projected');
  const smallArgs={...observeArgs,inputs:{path:'small.txt'},stream:'small'};
  const small=await api.call('manual.observe',smallArgs);require(small.observed.content==='orchard original\n','small first observation returns snapshot');
  fs.writeFileSync(path.join(root,'small.txt'),'orchard changed\n');
  const update=await api.call('manual.observe',smallArgs);
  require(update.mode==='diff' && update.diff.some(x=>x.path==='/content' && x.value==='orchard changed\n') && !update.observed,'later observation returns precise JSON patch without repeated snapshot');
  const unchanged=await api.call('manual.observe',smallArgs);require(unchanged.diff.length===0,'unchanged state emits empty delta');
  await denied(()=>api.call('manual.observe',{...smallArgs,previousHandle:first.handle}),'cross-stream handle rejected');
  await denied(()=>api.call('manual.project',{handle:'../outside'}),'path traversal cannot become a handle');
  await api.close();api=client();
  const retained=await api.call('manual.project',{handle:first.handle,path:'/content',offset:0,limit:100});
  require(retained.value===projection.value,'immutable observation handle survives MCP process restart');
  const afterRestart=await api.call('manual.observe',smallArgs);require(afterRestart.diff.length===0,'stream baseline survives process restart');

  const failed=await api.call('manual.run',{...runArgs,inputs:{path:'small.txt',phrase:'absent'}});
  require(failed.status==='failed' && failed.frontier.quarantined && !failed.checks[0].passed,'verifier failure creates machine-detected quarantined frontier');
  const binding=await api.call('manual.recovery.bind',{runId:failed.runId,chapter:'files',procedure:'read-and-confirm',inputs:{path:'small.txt',phrase:'orchard'}});
  const recovered=await api.call('manual.recover',{runId:failed.runId,recipeId:binding.recipeId});
  require(recovered.status==='completed' && recovered.checks[0].passed && recovered.runId!==failed.runId,'bound recovery uses new real checked run without replaying failed effects');
  const retainedRecovery=await api.call('manual.recover',{runId:failed.runId,recipeId:binding.recipeId});
  require(retainedRecovery.replayed && retainedRecovery.runId===recovered.runId,'repeated recovery returns original receipt without repeating effects');
  const repeated=await api.call('manual.run',{...runArgs,inputs:{path:'small.txt',phrase:'absent'}});
  require(repeated.recoveryRecipes.some(x=>x.recipeId===binding.recipeId) && !repeated.frontier,'known nogood is recognized and offers its bound recovery');
  const another=await api.call('manual.run',{...runArgs,inputs:{path:'large.txt',phrase:'absent'}});
  await denied(()=>api.call('manual.recover',{runId:another.runId,recipeId:binding.recipeId}),'same error on different inputs cannot use wrong recovery');
  await denied(()=>api.call('manual.recover',{runId:failed.runId,recipeId:binding.recipeId,scopeTools:[]}),'recovery cannot bypass narrowed caller tools');
  const unmapped=await api.call('manual.run',{id:'workspace',chapter:'files',procedure:'unknown-procedure'});
  require(unmapped.status==='frontier' && unmapped.quarantined,'unknown procedure is machine-detected frontier, no model called');
  const unknownState=await api.call('manual.observe',{id:'workspace',chapter:'files',state:'unknown-state'});
  require(unknownState.status==='frontier' && unknownState.quarantined,'unknown state is machine-detected frontier');

  const loaded=await api.call('manual.load',{id:'workspace',chapter:'files'});
  const patch=await api.call('manual.frontier',{id:'workspace',note:'Verified local guidance addition',observed:{runId:recovered.runId},operations:[{op:'add',path:'/chapters/files/guidance/-',value:'Use manual.project for large state; failed verifiers must be reconciled.'}]});
  require((await api.call('manual.load',{id:'workspace',chapter:'files'})).sha256===loaded.sha256,'quarantined patch does not affect live manual');
  const apply={id:'workspace',patchId:patch.patchId,expectedSha256:loaded.sha256,approved:true,reviewer:'T5 acceptance operator',evidence:[recovered.runId]};
  await denied(()=>api.call('manual.patch.apply',{...apply,approved:false}),'patch promotion requires explicit approval');
  const promoted=await api.call('manual.patch.apply',apply);
  require(promoted.parentSha256===loaded.sha256 && promoted.sha256!==loaded.sha256,'grounded patch creates distinct version with parent lineage');
  require((await api.call('manual.load',{id:'workspace',chapter:'files'})).text.includes('Use manual.project'),'promoted revision is consumed by actual manual loader');
  const invalidPatch=await api.call('manual.frontier',{id:'workspace',note:'Disposable invalid tool grounding probe',observed:{},operations:[{op:'replace',path:'/chapters/files/actions/workspace.read/tool',value:'neyvia.missing-tool'}]});
  await denied(()=>api.call('manual.patch.apply',{...apply,patchId:invalidPatch.patchId,expectedSha256:promoted.sha256}),'patch naming a missing tool cannot promote');
  require((await api.call('manual.versions',{id:'workspace'})).sha256===promoted.sha256,'invalid patch leaves live version unchanged');
  await denied(()=>api.call('manual.patch.apply',apply),'stale/repeated patch cannot overwrite current version');
  const demotion=await api.call('manual.demote',{id:'workspace',chapter:'files',procedure:'find-source',reason:'Obsolete search strategy in this scratch scenario'});
  require((await api.call('manual.load',{id:'workspace',chapter:'files'})).text.includes('PROCEDURE find-source'),'demotion stays quarantined until explicit promotion');
  await api.call('manual.patch.apply',{...apply,patchId:demotion.patchId,expectedSha256:promoted.sha256,evidence:[recovered.runId,'validated grounded removal']});
  const versions=await api.call('manual.versions',{id:'workspace'});
  require(versions.lineage.length===2 && versions.lineage[1].demoted.includes('files/find-source'),'obsolete procedure demotion recorded in lineage');
  const obsolete=await api.call('manual.run',{id:'workspace',chapter:'files',procedure:'find-source',inputs:{query:'orchard',includeGlob:'*.txt'}});
  require(obsolete.status==='frontier','demoted procedure cannot execute and returns frontier');
  require((await api.call('manual.run',{...runArgs,inputs:{path:'small.txt',phrase:'orchard'}})).status==='completed','remaining procedures execute against promoted revision');
  await denied(()=>api.call('manual.recover',{runId:failed.runId,recipeId:binding.recipeId}),'recovery bound to obsolete version is rejected');
  await api.close();api=client();
  require((await api.call('manual.versions',{id:'workspace'})).lineage.length===2,'lineage survives process restart');
  const overhead={before:JSON.stringify({observed:{content:large}}),after:JSON.stringify(first)};
  const tokenCount=spawnSync(python,['-c',"import json,sys,tiktoken; d=json.load(sys.stdin); e=tiktoken.get_encoding('o200k_base'); print(json.dumps({k:len(e.encode(v)) for k,v in d.items()}))"],{input:JSON.stringify(overhead),encoding:'utf8',windowsHide:true});
  require(tokenCount.status===0,'state payload tokens measured using installed tokenizer');
  const tokens=JSON.parse(tokenCount.stdout);
  const proof={schema:'neyvia.t5-state-versions-recovery.v1',at:new Date().toISOString(),passed:true,root,checks,tokens,firstObservation:first,projection,largeDelta:second,smallDelta:update,recoveredRun:recovered,versions,calls};
  fs.mkdirSync(path.join(repo,'scripts','evidence'),{recursive:true});
  fs.writeFileSync(path.join(repo,'scripts','evidence','T5-runtime.json'),JSON.stringify(proof,null,2)+'\n');
  console.log(JSON.stringify({passed:true,checks:checks.length,tokens,receipt:'scripts/evidence/T5-runtime.json'}));
}finally{await api.close();}
