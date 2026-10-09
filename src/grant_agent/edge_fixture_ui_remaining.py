"""Generated production frontend-model fixtures, explicitly below rendering authority.

Family builders share adversarial inputs; assertions observe values, preserved inputs,
ordering and a real disposable file, rather than source strings or checker success.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

TEXT = {'empty', 'huge', 'unicode'}
OWNERS = {
    'replay': 'next/nxReplayModel.js', 'plan': 'next/nxPlanModel.js',
    'onboarding': 'next/nxOnboardingModel.js', 'dashboard': 'next/nxDashboardModel.js',
    'cua': 'next/nxCuaModel.js', 'mesh': 'neyviaPersonalMeshModel.js',
    'ecosystem': 'neyviaEcosystemActionModel.js', 'factory': 'neyviaAppFactoryModel.js',
    'transparency': 'next/nxTransparencyModel.js', 'roles': 'neyviaModeStarters.js',
    'starters': 'neyviaModeStarters.js', 'batch': 'neyviaHarnessBatchModel.js',
    'workflow': 'neyviaWorkflows.js', 'office': 'neyviaOfficeSuiteModel.js',
    'marketplace': 'neyviaMarketplaceModel.js', 'permission': 'workspaceToolAccess.js',
}
IDS = {
    'replay.'+name for name in ['buildTimeline', 'visibleCount', 'recordedAt', 'playbackMs', 'timelineMarks', 'formatSpan']
} | {
    'plan.'+name for name in ['applyPlanOp', 'planOf', 'planProgress', 'showChecklist', 'planFromPage']
} | {
    'onboarding.'+name for name in ['interestsFor', 'recommend', 'timeline', 'locate', 'downloadView', 'packView', 'plainMissing', 'runtimeHeadline']
} | {
    'dashboard.'+name for name in ['resetsIn', 'limitTone', 'mergePages']
} | {
    'cua.'+name for name in ['toCapture', 'keyToInput', 'wheelToScroll', 'elementAt', 'pickSession', 'mergeLog']
} | {
    'mesh.'+name for name in ['value', 'boolean', 'count', 'duration', 'bytes', 'hash', 'snapshot']
} | {
    'factory.'+name for name in ['progress', 'tone', 'catalog', 'create', 'job', 'import', 'capability', 'eligible', 'handoff', 'hash', 'commands']
} | {
    'transparency.'+name for name in ['normalize', 'expanded', 'visible', 'notice', 'text', 'details', 'metadata', 'patch']
} | {
    'permission.'+name for name in ['normalize', 'tools', 'runtime', 'scope', 'grant', 'read', 'write', 'get', 'transfer']
} | {'ecosystem.capture', 'ecosystem.benchmark', 'ecosystem.submit', 'ecosystem.conclude',
     'roles.normalize', 'roles.default', 'roles.meta', 'starters.catalog', 'batch.prompts',
     'workflow.availability', 'workflow.explain', 'workflow.list',
     'office.classify', 'office.describe', 'office.execute', 'office.payload', 'marketplace.snapshots'}
CONSTANTS = {'factory.commands', 'starters.catalog'}
NUMERIC_ONLY = {'replay.formatSpan', 'cua.toCapture', 'cua.wheelToScroll'}
STORAGE = {'permission.read', 'permission.write', 'permission.get', 'permission.transfer'}

NODE = r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [repo, category, root]=process.argv.slice(1);
const base=path.join(repo,'web/src/neyvia');
const load=async name=>import(pathToFileURL(path.join(base,name)));
const [replay,plan,onboarding,dash,cua,mesh,eco,factory,tr,roles,batch,wf,office,market,perm]=await Promise.all([
 'next/nxReplayModel.js','next/nxPlanModel.js','next/nxOnboardingModel.js','next/nxDashboardModel.js',
 'next/nxCuaModel.js','neyviaPersonalMeshModel.js','neyviaEcosystemActionModel.js','neyviaAppFactoryModel.js',
 'next/nxTransparencyModel.js','neyviaModeStarters.js','neyviaHarnessBatchModel.js','neyviaWorkflows.js',
 'neyviaOfficeSuiteModel.js','neyviaMarketplaceModel.js','workspaceToolAccess.js'].map(load));
const text=category==='empty'?'':category==='huge'?'long-observed-data '.repeat(1000):'雪 café e\u0301 العربية';
const count=category==='empty'?0:category==='huge'?2048:3;
const rows=[];
const snapshot=x=>JSON.stringify(x);
function record(contract,fn){try{const observed=fn();rows.push({contract,status:'passed',detail:{inputCharacters:text.length,inputRows:count,observation:observed??'exact assertions passed'}})}catch(error){rows.push({contract,status:'failed',detail:String(error.stack||error)})}}
function equalCall(owner,name,args,expected){const before=snapshot(args);const result=owner[name](...args);assert.deepEqual(result,expected);assert.equal(snapshot(args),before,'caller data mutated');return {outputCharacters:typeof result==='string'?result.length:null};}
const file=path.join(root,'modes.json');
const storage={getItem(key){assert.equal(key,perm.WORKSPACE_PERMISSION_STORAGE_KEY);return fs.readFileSync(file,'utf8')},setItem(key,value){assert.equal(key,perm.WORKSPACE_PERMISSION_STORAGE_KEY);fs.writeFileSync(file,value)}};
const disk=()=>JSON.parse(fs.readFileSync(file,'utf8'));
if(category==='permissions'){
 record('permission.read',()=>assert.deepEqual(perm.readWorkspacePermissionModes(storage),{}));
 record('permission.get',()=>assert.equal(perm.workspacePermissionModeForScope(storage,'locked','read-only'),'read-only'));
 record('permission.write',()=>assert.equal(perm.writeWorkspacePermissionMode(storage,'locked','workspace'),false));
 record('permission.transfer',()=>assert.equal(perm.transferDraftWorkspacePermissionMode(storage,JSON.stringify(['w','p','new-chat']),JSON.stringify(['w','p','live'])),false));
}else if(category==='stale'){
 const scope=JSON.stringify(['owned','path','live']);
 for(const [contract,fn] of Object.entries({
  'permission.read':()=>{fs.writeFileSync(file,JSON.stringify({[scope]:'read-only'}));const old=perm.readWorkspacePermissionModes(storage);fs.writeFileSync(file,JSON.stringify({[scope]:'workspace'}));assert.equal(old[scope],'read-only');assert.equal(perm.readWorkspacePermissionModes(storage)[scope],'workspace');},
  'permission.get':()=>{fs.writeFileSync(file,JSON.stringify({[scope]:'read-only'}));assert.equal(perm.workspacePermissionModeForScope(storage,scope),'read-only');fs.writeFileSync(file,JSON.stringify({[scope]:'full-access'}));assert.equal(perm.workspacePermissionModeForScope(storage,scope),'full-access');},
  'permission.write':()=>{fs.writeFileSync(file,JSON.stringify({keep:'workspace'}));perm.readWorkspacePermissionModes(storage);fs.writeFileSync(file,JSON.stringify({keep:'read-only',external:'workspace'}));assert.equal(perm.writeWorkspacePermissionMode(storage,scope,'full-access'),true);assert.deepEqual(disk(),{keep:'read-only',external:'workspace',[scope]:'full-access'});},
  'permission.transfer':()=>{const prior=JSON.stringify(['owned','path','new-chat']);fs.writeFileSync(file,JSON.stringify({[prior]:'workspace',[scope]:'read-only'}));assert.equal(perm.transferDraftWorkspacePermissionMode(storage,prior,scope),false);assert.equal(disk()[scope],'read-only');}
 }))record(contract,fn);
}else{
 const items=Array.from({length:count},(_,i)=>({id:'row'+i+(i===0?text:''),seq:i+1,kind:i%2?'assistant':'user',at:1000+i*10000,data:{text:i===0?text:''}}));
 const expectedEntries=items.map((item,i)=>({item,t:i*10000,rt:i*4000,at:1000+i*10000}));
 const timeline={entries:expectedEntries,duration:Math.max(0,count-1)*10000,replayDuration:Math.max(0,count-1)*4000,startedAt:count?1000:null};
 record('replay.buildTimeline',()=>equalCall(replay,'buildTimeline',[[...items].reverse().concat([{id:'optimistic'+text,seq:count+1,optimistic:true}])],timeline));
 const pos=count?4000:-1;
 record('replay.visibleCount',()=>equalCall(replay,'visibleCount',[timeline,pos],Math.min(count,2)));
 record('replay.recordedAt',()=>equalCall(replay,'recordedAt',[timeline,pos],count?11000:null));
 record('replay.playbackMs',()=>equalCall(replay,'playbackMs',[timeline,16],Math.ceil(timeline.replayDuration/16)));
 record('replay.timelineMarks',()=>equalCall(replay,'timelineMarks',[timeline],items.map((x,i)=>({id:x.id,at:i*4000/(timeline.replayDuration||1),tone:i%2?'reply':'user'}))));
 if(category!=='unicode')record('replay.formatSpan',()=>equalCall(replay,'formatSpan',[category==='empty'?0:8040000],category==='empty'?'0s':'2h 14m'));
 const list=Array.from({length:count},(_,i)=>({id:String(i+1),text:i===0?text:'item'+i,status:i===0?'in_progress':'completed'}));
 const model=count?{items:list,source:'owner',explanation:text,throughSeq:5}:null;
 record('plan.applyPlanOp',()=>{const input=snapshot(model);const r=plan.applyPlanOp(model,{op:'replace',source:'owner',items:list,explanation:text},{at:'fixed',seq:10});assert.equal(snapshot(model),input);assert.deepEqual(r,count?{items:list,source:'owner',explanation:text,throughSeq:10,updatedAt:'fixed'}:null);return {items:r?.items.length||0};});
 record('plan.planOf',()=>{const r=plan.planOf({plan:model,planSeq:5,items:[{seq:4,data:{plan:{op:'replace',items:[{id:'stale'}]}}},{seq:6,optimistic:true,data:{plan:{op:'replace',items:[{id:'optimistic'}]}}},{seq:7,at:'live',data:{plan:{op:'add',source:'owner',item:{id:'live'+text,text,status:'pending'}}}}]});assert.deepEqual(r.items,[...list,{id:'live'+text,text,status:'pending'}]);assert.equal(r.throughSeq,7);assert.equal(r.updatedAt,'live');});
 record('plan.planProgress',()=>{const r=plan.planProgress(model);assert.equal(r.total,count);assert.equal(r.done,Math.max(0,count-1));assert.equal(r.current?.text??null,count?text:null);assert.equal(r.next,null);assert.equal(r.finished,false);});
 record('plan.showChecklist',()=>equalCall(plan,'showChecklist',[model,false],count>0));
 record('plan.planFromPage',()=>equalCall(plan,'planFromPage',[{plan:model,items:[{seq:8},{seq:9}]}],{plan:model,planSeq:count?5:9}));
 const chapters=Array.from({length:count},(_,i)=>({id:'chapter'+i+(i===0?text:''),durationMs:10000,interests:['chosen']}));
 const catalog={tiers:[{id:text,interests:['chosen']}],interests:[{id:'chosen',apps:[text,'app',text],packs:['pack'],runtimes:['runtime'],chapters:chapters.map(x=>x.id)}],tutorial:{chapters}};
 record('onboarding.interestsFor',()=>equalCall(onboarding,'interestsFor',[catalog,{tier:text}],['chosen']));
 record('onboarding.recommend',()=>equalCall(onboarding,'recommend',[catalog,category==='empty'?[]:['chosen']],{apps:category==='empty'?[]:[text,'app'],packs:category==='empty'?[]:['pack'],runtimes:category==='empty'?[]:['runtime'],chapters:category==='empty'?[]:chapters}));
 const target=count?Math.max(60000,Math.min(90000,count*10000)):0;
 const placed=chapters.map((x,i)=>({...x,start:Math.round(i*target/count),durationMs:Math.round((i+1)*target/count)-Math.round(i*target/count)}));
 const tour={chapters:placed,totalMs:target};
 record('onboarding.timeline',()=>{equalCall(onboarding,'timeline',[chapters],tour);assert.deepEqual(onboarding.timeline([{id:'zero',durationMs:0}]),{chapters:[],totalMs:0});assert.deepEqual(onboarding.timeline([{id:'one',durationMs:1},{id:'two',durationMs:2},{id:'four',durationMs:4}]),{totalMs:60000,chapters:[{id:'one',durationMs:8571,start:0},{id:'two',durationMs:17143,start:8571},{id:'four',durationMs:34286,start:25714}]});const zeroTail=onboarding.timeline([{id:'first',durationMs:1},{id:'last',durationMs:0}]);assert.deepEqual(zeroTail,{totalMs:60000,chapters:[{id:'first',durationMs:60000,start:0},{id:'last',durationMs:0,start:60000}]});return {chapters:count,totalMs:target,minimumDuration:count?Math.min(...placed.map(x=>x.durationMs)):null};});
 record('onboarding.locate',()=>{equalCall(onboarding,'locate',[tour,target],count?{index:count-1,chapter:placed.at(-1),progress:1}:{index:0,chapter:null,progress:0});const zeroTail={totalMs:60000,chapters:[{id:'first',durationMs:60000,start:0},{id:'last',durationMs:0,start:60000}]};assert.deepEqual(onboarding.locate(zeroTail,60000),{index:1,chapter:zeroTail.chapters[1],progress:1});});
 record('onboarding.downloadView',()=>{const r=onboarding.downloadView({state:'failed',error:text,totalBytes:category==='huge'?1e12:0,doneBytes:category==='huge'?5e11:0});assert.equal(r.detail,text||'Something went wrong.');assert.equal(r.percent,category==='huge'?50:0);assert.equal(r.busy,false);assert.equal(r.headline,'The download stopped');});
 record('onboarding.packView',()=>{const r=onboarding.packView({resourceClass:'heavy',missing:[text]},{state:'failed',error:text});assert.equal(r.detail,text||'The install stopped.');assert.deepEqual(r.missing,[text]);assert.equal(r.canInstall,true);assert.equal(r.busy,false);});
 record('onboarding.plainMissing',()=>equalCall(onboarding,'plainMissing',[text+' tool.pandoc'],text+' Pandoc'));
 record('onboarding.runtimeHeadline',()=>{const r=onboarding.runtimeHeadline({runtimes:items.map(x=>({label:x.id,found:true}))});assert.equal(r.title,count?"You're set to start":'Begin with…');if(count)assert.ok(r.sub.includes(items[0].id)&&r.sub.includes(items.at(-1).id));});
 record('dashboard.resetsIn',()=>equalCall(dash,'resetsIn',[text,1000],''));
 record('dashboard.limitTone',()=>equalCall(dash,'limitTone',[{status:text,usedPercent:category==='empty'?'':category==='huge'?1e12:text}],category==='huge'?'red':'idle'));
 record('dashboard.mergePages',()=>{const sessions=items.map(x=>({id:x.id,title:x.data.text}));const r=dash.mergePages([{sessions},{sessions:[...sessions,{id:'new'+text,title:text}],total:count+1,nextOffset:null}]);assert.deepEqual(r.sessions,[...sessions,{id:'new'+text,title:text}]);assert.equal(r.total,count+1);assert.equal(r.hasMore,false);});
 if(category!=='unicode'){
 record('cua.toCapture',()=>equalCall(cua,'toCapture',category==='empty'?[0,0,{},{}]:[1e9,1e9,{left:0,top:0,width:1e9,height:1e9},{width:1e6,height:1e6}],category==='empty'?null:{x:999999,y:999999}));
 record('cua.wheelToScroll',()=>equalCall(cua,'wheelToScroll',[category==='empty'?0:1e12,0],category==='empty'?null:{direction:'right',amount:10}));
 }
 record('cua.keyToInput',()=>equalCall(cua,'keyToInput',[{key:category==='unicode'?'雪':text}],category==='unicode'?{kind:'text',text:'雪'}:null));
 const elements=items.map((x,i)=>({id:x.id,screenshot_frame:{x:0,y:0,w:count-i+1,h:count-i+1}}));
 record('cua.elementAt',()=>equalCall(cua,'elementAt',[elements,1,1],elements.at(-1)||null));
 record('cua.pickSession',()=>equalCall(cua,'pickSession',[items.map(x=>({...x,status:'active'})),items.at(-1)?.id],items.length?{...items.at(-1),status:'active'}:null));
 record('cua.mergeLog',()=>{const start=items.map((x,i)=>({id:x.id,seq:i+1,text:x.data.text}));const r=cua.mergeLog(start,{id:'new'+text,seq:0,text},3);const expected=[{id:'new'+text,seq:0,text},...start].slice(-3);assert.deepEqual(r,expected);assert.deepEqual(start,items.map((x,i)=>({id:x.id,seq:i+1,text:x.data.text})));if(count){const updated=cua.mergeLog(start,{id:start[0].id,seq:count+10,text},count+1);assert.ok(updated.every((x,i)=>!i||updated[i-1].seq<=x.seq),'updated log must retain seq order');}});
 for(const [id,name,args,expected] of [
  ['value','formatValue',[text],text||'Unavailable'],['boolean','formatBooleanStatus',[true,{trueLabel:text}],text],
  ['count','formatCount',[category==='huge'?1e12:text],category==='huge'?'1000000000000':'Unavailable'],
  ['duration','formatDuration',[category==='huge'?1e12:text],category==='huge'?'1000000000000 ms':'Unavailable'],
  ['bytes','formatBytes',[category==='huge'?1048576*1e6:text],category==='huge'?'1000000.00 MiB':'Unavailable'],
  ['hash','shortHash',[text],!text?'Unavailable':text.length>16?text.slice(0,8)+'…'+text.slice(-6):text],
  ['snapshot','hasMeshSnapshot',[category==='empty'?{}:{label:text}],category!=='empty']
 ])record('mesh.'+id,()=>equalCall(mesh,name,args,expected));
 record('ecosystem.capture',()=>equalCall(eco,'buildPresentationCapturePayload',[{source:text,content:text,destinationKind:'mission',destinationId:text,userInitiated:true}],{source:text.trim(),direction:'chatgpt-to-neyvia',content:{selectedText:text.trim()},userInitiated:true,projectId:'',conversationId:'',missionId:text.trim()}));
 record('ecosystem.benchmark',()=>equalCall(eco,'buildBenchmarkResultPayload',[{subjectId:text,measuredFacts:text,success:text,comparableContext:'true'}],{subjectId:text.trim(),measuredFacts:text.trim()||'not-reported',success:'not-reported',comparableContext:false,budgetExceeded:false}));
 record('ecosystem.submit',()=>equalCall(eco,'canSubmitBenchmarkResult',[{runId:'local-observation',subjects:[text.trim()]},{subjectId:text}],Boolean(text.trim())));
 record('ecosystem.conclude',()=>equalCall(eco,'canConcludeExperiment',[{experimentId:'local-observation',state:'ready'},text],Boolean(text.trim())));
 const jobs=items.map(x=>({jobId:x.id,brief:x.data.text}));
 const handoffs=items.map(x=>({materializationId:x.id,candidateDigest:'digest',state:'review_required',canCreateApp:true}));
 record('factory.progress',()=>equalCall(factory,'appFactoryProgress',[{stages:category==='empty'?[]:[{state:'completed',description:text},{state:'running'}]}],{completed:category==='empty'?0:1,total:5,percent:category==='empty'?0:20}));
 record('factory.tone',()=>equalCall(factory,'appFactoryJobTone',[{status:text,nativeBuild:{state:text}}],'neutral'));
 record('factory.catalog',()=>{const r=factory.normalizeAppFactoryCatalog({jobs:[null,...jobs],targets:[],capabilityHandoffs:handoffs});assert.deepEqual(r.jobs,jobs);assert.equal(r.summary.total,count);assert.equal(r.summary.capabilityReady,count);assert.equal(r.summary.capabilityMaintenanceDue,0);});
 record('factory.create',()=>equalCall(factory,'appFactoryCreatePayload',[{name:text,brief:text,directory:text},text],{name:text.trim(),brief:text.trim(),target:'desktop',template:'auto',theme:'midnight',directory:text.trim(),...(text.trim()?{root:text.trim()}:{})}));
 record('factory.job',()=>equalCall(factory,'appFactoryJobPayload',[text,text],{jobId:text.trim(),...(text.trim()?{root:text.trim()}:{})}));
 record('factory.import',()=>{const bundle={schema:'neyvia.capability-run-bundle/v2',appFactoryJobId:text,runs:jobs};const r=factory.appFactoryOutcomeImportPayload(bundle,text);if(category==='empty')assert.equal(r,null);else{assert.equal(r.bundle,bundle);assert.equal(r.importedBy,'operator');assert.equal(r.root,text.trim());}assert.equal(factory.appFactoryOutcomeImportPayload({...bundle,runs:[]},text),null);});
 record('factory.capability',()=>{const h={materializationId:'m'+text,candidateDigest:'digest',canCreateApp:true,state:'review_required'};assert.equal(factory.appFactoryCapabilityPayload(h,{brief:text},text,false),null);const r=factory.appFactoryCapabilityPayload(h,{brief:text},text,true);assert.equal(r.brief,text.trim());assert.equal(r.materializationId,('m'+text).trim());assert.equal(r.reviewConfirmed,true);});
 record('factory.eligible',()=>equalCall(factory,'appFactoryEligibleHandoffs',[{capabilityHandoffs:[...handoffs,{materializationId:'denied'+text,state:'review_required',canCreateApp:false}]}],handoffs));
 record('factory.handoff',()=>equalCall(factory,'appFactoryHandoffForJob',[{capabilityHandoffs:handoffs},{capabilityHandoff:{materializationId:handoffs.at(-1)?.materializationId}}],handoffs.at(-1)||null));
 record('factory.hash',()=>equalCall(factory,'compactFactoryHash',[text],!text.trim()?'Not recorded':text.trim().length>18?text.trim().slice(0,10)+'…'+text.trim().slice(-6):text.trim()));
 if(category==='empty')record('factory.commands',()=>{assert.equal(factory.appFactoryCommands().create,'create_app_factory_job_command');assert.equal(Object.keys(factory.appFactoryCommands()).length,10);});
 for(const [id,name,args,expected] of [
  ['normalize','normalizeTransparency',[text],'everything'],['text','detailText',[text],text],
  ['expanded','detailExpanded',[text,'summaries',new Set([text])],true],
  ['visible','itemVisible',[{kind:'reasoning',data:{notice:text}},'minimal'],Boolean(text)],
  ['notice','reasoningNotice',[{notice:text},'Observed provider'],text||'Observed provider didn’t share its reasoning for this step'],
  ['details','toolDetails',[{command:text,args:text,input:text,output:''}], [...(text?[{label:'Command',text}]:[]),{label:'Output',text:'(empty output)'}]],
  ['metadata','toolMetadata',[{exitCode:text,category:'command',durationMs:category==='huge'?1e12:0,durationSource:'transport-observed'}],'Exit '+text+' · Observed '+(category==='huge'?'1000000000.00':'0.000')+' s'],
  ['patch','diffText',[{files:[{patch:text},{diff:'other'}]}],[text,'other'].filter(Boolean).join('\n\n')]
 ])record('transparency.'+id,()=>equalCall(tr,name,args,expected));
 record('roles.normalize',()=>equalCall(roles,'normalizeNeyviaOrchestrationRoleIds',[[text,'planner',text]],['planner','executor','verifier',...(text.trim()?text.trim().toLowerCase()==='planner'?[]:[text.trim().toLowerCase()]:[])]));
 record('roles.default',()=>equalCall(roles,'isNeyviaDefaultOrchestrationRole',[text],false));
 record('roles.meta',()=>{const r=roles.neyviaOrchestrationRoleMeta(text);assert.equal(r.tone,'specialist');assert.equal(r.label,text.trim()?text.toLowerCase().trim().split(/[-_\s]+/).map(x=>x[0].toUpperCase()+x.slice(1)).join(' '):'Specialist');});
 if(category==='empty')record('starters.catalog',()=>{const r=roles.modeStarterCatalog();assert.equal(r.chat.length,6);assert.equal(r.orchestration.length,4);assert.ok(r.chat.every(x=>x.id&&x.prompt));});
 record('batch.prompts',()=>{if(!text){assert.throws(()=>batch.parseBatchPrompts(text));return;}const r=batch.parseBatchPrompts(JSON.stringify({prompt:text}));assert.deepEqual(r,[text]);if(category==='huge')assert.throws(()=>batch.parseBatchPrompts(Array.from({length:101},()=>text).join('\n')));});
 record('workflow.availability',()=>{const r=wf.workflowAvailability({route:{provider:text,model:text,runtimeId:text},selectedRuntime:text,evidence:{runtimeStatus:{[text]:{available:true,credentialPresent:true}}},workspacePath:text,tools:[{toolId:'tool.playwright',agentReady:true}]});assert.equal(r.model,Boolean(text));assert.equal(r.files,Boolean(text));assert.equal(r.browser,true);assert.equal(r.cli,Boolean(text));assert.equal(r.mcp,false);});
 record('workflow.explain',()=>{const r=wf.explain({requires:category==='empty'?[]:['files'],name:text},{files:false});assert.equal(r.runnable,category==='empty');assert.deepEqual(r.missing,category==='empty'?[]:['files']);});
 record('workflow.list',()=>{const r=wf.listWorkflows({model:Boolean(text),files:Boolean(text)});assert.equal(r.length,wf.WORKFLOWS.length);assert.deepEqual(r.map(x=>x.id),wf.WORKFLOWS.map(x=>x.id));assert.ok(r.every(x=>typeof x.runnable==='boolean'));});
 record('office.classify',()=>equalCall(office,'classifyOfficeSuiteOutcome',[{status:text,ok:false,error:text}],text?'backend-error':'unavailable'));
 record('office.describe',()=>{const r=office.normalizeOfficeToolDescribe({toolId:text,name:text,agentReady:false,operations:items.map(x=>({operationId:x.id,name:x.data.text}))});assert.equal(r.agentReady,false);assert.equal(r.outcome,'unavailable');assert.equal(r.operations.length,count);if(count)assert.equal(r.operations[0].operationId,items[0].id.trim());});
 record('office.execute',()=>{const r=office.normalizeOfficeExecuteResult({ok:true,status:'completed',operationId:text,result:{outputPath:text,bytes:count,unrelated:text},artifactReceipt:{artifacts:[]}});assert.equal(r.operationId,text.trim());assert.equal(r.outcome,'completed');assert.equal(r.verification,null);assert.deepEqual(r.registeredArtifacts,[]);assert.equal(r.artifact?.unrelated,undefined);assert.equal(r.artifact.bytes,count);});
 record('office.payload',()=>{const arguments_={content:text};const r=office.buildOfficeSuiteExecutePayload({toolId:text,operationId:text,arguments:arguments_,approvedPermissions:[text],capabilityId:text});assert.equal(r.toolId,text.trim());assert.equal(r.operationId,text.trim());assert.deepEqual(r.arguments,arguments_);assert.deepEqual(r.approvedPermissions,[text]);});
 record('marketplace.snapshots',()=>{const modules=items.map(x=>({moduleId:x.id,name:x.data.text,state:'installed',signatureReceipt:{state:'missing'}}));const r=market.normalizeMarketplaceSnapshots({schema:'neyvia.installed-module-catalog/v1',modules},{schema:'neyvia.marketplace-toolchain-snapshot/v1',tools:{cosign:{healthy:false,reason:text}}});assert.equal(r.moduleCount,count);assert.equal(r.installedCount,count);assert.equal(r.tools.find(x=>x.name==='cosign').healthy,false);if(count){assert.equal(r.modules[0].id,items[0].id.trim());assert.equal(r.modules[0].signature.state,'Missing');assert.equal(r.modules[0].signature.toolReady,false);}});
 record('permission.normalize',()=>equalCall(perm,'normalizeWorkspacePermissionMode',[text],'read-only'));
 record('permission.tools',()=>equalCall(perm,'workspacePermissionAllowsTools',[text],false));
 record('permission.runtime',()=>equalCall(perm,'supportsNativeWorkspacePermissionModes',[text],false));
 const scope=JSON.stringify([text.trim(),text.trim(),text.trim()]);
 record('permission.scope',()=>equalCall(perm,'buildWorkspacePermissionScope',[text,text,text],scope));
 record('permission.grant',()=>equalCall(perm,'workspacePermissionGrantForScope',[{scope,permissionMode:'workspace'},scope],'workspace'));
 record('permission.read',()=>{const content=category==='empty'?{}:Object.fromEntries(items.map(x=>[x.id,'workspace']));fs.writeFileSync(file,JSON.stringify(content));assert.deepEqual(perm.readWorkspacePermissionModes(storage),content);assert.deepEqual(disk(),content);});
 record('permission.write',()=>{fs.writeFileSync(file,JSON.stringify({keep:'read-only'}));assert.equal(perm.writeWorkspacePermissionMode(storage,scope,'workspace'),true);assert.deepEqual(disk(),{keep:'read-only',[scope]:'workspace'});});
 record('permission.get',()=>{fs.writeFileSync(file,JSON.stringify({[scope]:'workspace'}));assert.equal(perm.workspacePermissionModeForScope(storage,scope),'workspace');assert.equal(perm.workspacePermissionModeForScope(storage,'missing'+text,'read-only'),'read-only');});
 record('permission.transfer',()=>{const prior=JSON.stringify([text.trim(),text.trim(),'new-chat']),next=JSON.stringify([text.trim(),text.trim(),'live']);fs.writeFileSync(file,JSON.stringify({keep:'read-only',[prior]:'workspace'}));assert.equal(perm.transferDraftWorkspacePermissionMode(storage,prior,next),true);assert.deepEqual(disk(),{keep:'read-only',[prior]:'workspace',[next]:'workspace'});assert.equal(perm.transferDraftWorkspacePermissionMode(storage,prior,next),false);});
}
console.log(JSON.stringify(rows));
'''


def run(root, contracts, categories):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    repo = Path(__file__).resolve().parents[2]
    rows = []
    for category in categories:
        if category not in TEXT | {'permissions', 'stale'}:
            continue
        selected_root = Path(root) / category
        selected_root.mkdir(parents=True, exist_ok=True)
        file = selected_root / 'modes.json'
        if category == 'permissions':
            from .edge_fixture_models import _deny_read
            file.write_text(json.dumps({'locked': 'workspace'}), encoding='utf-8')
            before = file.read_bytes()
            with _deny_read(file):
                result = subprocess.run(['node', '--input-type=module', '-e', NODE, str(repo), category, str(selected_root)],
                                        cwd=repo, capture_output=True, text=True, encoding='utf-8', timeout=60,
                                        **hidden_windows_subprocess_kwargs())
            if file.read_bytes() != before:
                raise AssertionError('Actual denied file changed bytes')
        else:
            result = subprocess.run(['node', '--input-type=module', '-e', NODE, str(repo), category, str(selected_root)],
                                    cwd=repo, capture_output=True, text=True, encoding='utf-8', timeout=60,
                                    **hidden_windows_subprocess_kwargs())
        if result.returncode:
            raise RuntimeError(result.stderr[-2500:])
        for item in json.loads(result.stdout):
            if item['contract'] in contracts:
                rows.append({'id': 'remaining-ui.'+item['contract']+'.'+category,
                             'category': category, 'contracts': [item['contract']],
                             'status': item['status'], 'detail': item['detail'],
                             'boundary': 'Actual production model with mutated synthetic observations; no rendered/provider claim. Permission storage uses real disposable disk I/O.'})
    return rows


def blocker(contract, category):
    ident = contract['id']
    if ident not in IDS:
        return None
    owner = 'web/src/neyvia/'+OWNERS[ident.split('.')[0]]
    if ident in CONSTANTS and category in {'huge', 'unicode'}:
        return {'kind': 'not_applicable', 'reason': f'{owner}: {ident} has a zero-argument frozen catalog export; no text or collection argument can be mutated for this category.'}
    if ident in NUMERIC_ONLY and category == 'unicode':
        return {'kind': 'not_applicable', 'reason': f'{owner}: {ident} accepts numeric coordinates/duration only, no textual field or label. Unicode typing has the separate cua.keyToInput contract.'}
    if ident in STORAGE:
        if category in {'concurrency', 'interrupted', 'offline'}:
            return {'kind': 'fixture_gap', 'reason': f'{owner}: actual persistent storage needs a separate coordinated process/crash/local-storage-unavailability journey for {category}; not proved by synchronous model calls.'}
        return None
    if category in {'concurrency', 'interrupted', 'permissions', 'offline', 'stale'}:
        return {'kind': 'not_applicable', 'reason': f'{owner}: inspected {ident} transforms caller-supplied in-memory observations with no shared persistent revision, transport, worker, permission grant or I/O. Model presentation is distinct from runtime execution/rendering.'}
    return None


def receipt(destination, root):
    """Standalone raw run preserving failures and source bytes for lead integration."""
    from .edge_contracts import inventory, CATEGORIES
    repo = Path(__file__).resolve().parents[2]
    paths = [Path(__file__), *[repo/'web/src/neyvia'/name for name in sorted(set(OWNERS.values()))],
             repo/'web/src/neyvia/next/nxProofsEContracts.js',
             repo/'web/src/neyvia/neyviaFrontendContracts.js', repo/'web/src/neyvia/neyviaPresentationContracts.js']
    def hashes():
        return {str(path.relative_to(repo)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    before = hashes()
    contracts = {ident: row for ident, row in inventory()[1].items() if ident in IDS}
    started = time.monotonic()
    cases = run(root, contracts, CATEGORIES)
    after = hashes()
    bindings = {(ident, row['category']) for row in cases for ident in row['contracts']}
    audit = [{'contract': ident, 'category': category, **(blocker(contract, category) or {'kind': 'fixture_gap', 'reason': 'No real fixture implemented for this exact contract/category yet.'})}
             for ident, contract in contracts.items() for category in CATEGORIES if (ident, category) not in bindings]
    payload = {'schema': 'neyvia.c7b.remaining-ui-fixtures.v1', 'root': str(root), 'elapsedSeconds': round(time.monotonic()-started, 3),
               'sourceBindings': before, 'sourceStable': before == after, 'afterSourceBindings': after,
               'cases': cases, 'summary': {'cases': len(cases), 'passed': sum(row['status']=='passed' for row in cases),
                                         'failed': sum(row['status']=='failed' for row in cases), 'pairs': len(bindings), 'contracts': len(contracts)},
               'audit': audit, 'boundary': 'Production model exports and real disposable storage, not browser rendering or external-provider proof.'}
    Path(destination).write_text(json.dumps(payload, ensure_ascii=True, indent=2)+'\n', encoding='utf-8')
    return payload['summary']
