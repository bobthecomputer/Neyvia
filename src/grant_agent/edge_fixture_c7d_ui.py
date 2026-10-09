"""Inspected UI argument models with independent effects, never rendered proof.

Only exact argument-model claims are bound here. Browser/native/provider work
continues to require separately observed production journeys.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OWNERS = {
    "devices": ("next/nxDevicesModel.js", "dropIntent sendTarget transferFraction transferLine pcTarget parsePcTarget"),
    "gamedev": ("next/nxGameDevModel.js", "actionFields keepSelection tabForStage visibleFields initialValues buildArgs"),
    "conductor": ("next/nxConductorModel.js", "turnKind shapeJob mergeJobs planProblems"),
    "missions": ("next/nxMissionsModel.js", "shapeMission draftProblems createRequest planPrompt"),
    "outputs": ("next/nxOutputsModel.js", "perceptionTarget parsePerceptionTarget outsideDock dropSpot"),
    "nightshift": ("next/nxNightShiftModel.js", "shapeBoard startable evidenceView morning quietNow treeLayout policyForm policyPatch"),
}
IDS = {prefix + "." + name for prefix, (_, names) in OWNERS.items() for name in names.split()}
DICTATION = {"anchor": "shiftAnchor", "sentence-state": "endsMidSentence", "join": "joinSpoken",
             "sentence-boundary": "lastSentenceStart", "scratch": "dropLastPhrase", "delete-sentence": "dropLastSentence",
             "edit": "applySegments", "preview": "previewParts", "overlap": "withoutOverlap",
             "answer": "normalizeAnswer", "commands": "liveCommands"}
IDS |= {"dictation." + name for name in DICTATION} | {"chat.cancellation-result", "chat.cancelled", "chat.runtime-source"}
COMPOSER_PURE = {"composer." + name for name in ("stripDataUrl", "base64Chars", "admitImages", "planImageReads", "imageBlocker", "sendIdentity", "parseArguments", "argumentSkeleton", "filterTools", "toolMutates", "toolScope")}
LOCAL_IDS = {"dictation.names.persisted", "dictation.names.scoped", "dictation.prompt.structure", "dictation.prompt.commands", "dictation.prompt.route", "dictation.stream.preallocation"}
LIVE_PURE = {"livecontrol.builder-url", "livecontrol.redaction", "livecontrol.report-truth", "livecontrol.api-not-dom"}
IMAGE_LOCAL = {"image.provider.adapter", "image.provider.receipt", "image.provider.history", "image.prompt.presets"}

NODE = r'''
import assert from 'node:assert/strict';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [repo,category]=process.argv.slice(1);
const load=name=>import(pathToFileURL(path.join(repo,'web/src/neyvia',name)));
const [d,g,c,m,o,n,q,v,a]=await Promise.all(['next/nxDevicesModel.js','next/nxGameDevModel.js','next/nxConductorModel.js','next/nxMissionsModel.js','next/nxOutputsModel.js','next/nxNightShiftModel.js','next/nxDictationEdit.js','transcriptVisibility.js','chatCancellation.js'].map(load));
const composer=await load('next/nxComposerModel.js');
const [image,providers]=await Promise.all(['imagePlaygroundState.js','imageProviderAdapters.js'].map(load));
const text=category==='empty'?'':category==='huge'?'owned-content '.repeat(2048).trim():'雪 café e\u0301 العربية';
const count=category==='empty'?0:category==='huge'?512:3;
const rows=[];
function record(contract,fn){try{fn();rows.push({contract,status:'passed',detail:{inputCharacters:text.length,inputRows:count,observation:'Exact output and caller conservation asserted'}})}catch(e){rows.push({contract,status:'failed',detail:String(e.stack||e).slice(-3000)})}}
function equal(owner,name,args,expected){const before=JSON.stringify(args);assert.deepEqual(owner[name](...args),expected);assert.equal(JSON.stringify(args),before,'Caller snapshot mutated')}
record('devices.dropIntent',()=>{equal(d,'dropIntent',[{path:text},{device:null}],text?'move':null);assert.equal(d.dropIntent({path:'owned',device:'other'},{device:'another'}),null);assert.equal(d.dropIntent({path:'owned'},{device:'other'}),'send');assert.equal(d.dropIntent({path:'owned',device:'other'},{}),'take')});
record('devices.sendTarget',()=>{equal(d,'sendTarget',[{theyShare:{writeAnywhere:false}},{kind:'folder',write:false},text],null);equal(d,'sendTarget',[{}, {kind:'inbox'},text],text||null);equal(d,'sendTarget',[{theyShare:{writeAnywhere:true}},{kind:'folder'},text],text||null)});
record('devices.transferFraction',()=>{for(const [input,expected] of [[{},null],[{status:'done'},1],[{size:10,done:-4},0],[{size:10,done:40},1],[{size:10,done:5},0.5]])equal(d,'transferFraction',[{...input,name:text}],expected)});
record('devices.transferLine',()=>{equal(d,'transferLine',[{status:'failed',error:text}],text?'Stopped: '+text:'Stopped');equal(d,'transferLine',[{status:'cancelled',error:text}],'Cancelled');equal(d,'transferLine',[{status:'done',size:1024}],'Done · 1.0 KB · checked')});
record('devices.pcTarget',()=>equal(d,'pcTarget',[text,'folder|piece'],'pc:'+text+'|folder|piece'));
record('devices.parsePcTarget',()=>{equal(d,'parsePcTarget',['pc:'+text+'|folder|piece'],text?{device:text,path:'folder|piece'}:null);assert.equal(d.parsePcTarget(text),null)});
record('gamedev.tabForStage',()=>{equal(g,'tabForStage',[text,text],'babylon');assert.equal(g.tabForStage('unity','GODOT'),'godot');assert.equal(g.tabForStage('unity',''),'unity')});
const fields=[{key:'name',kind:'text',initial:text},{key:'value',kind:'number',initial:2},{key:'value',kind:'bool',initial:true,when:x=>x.name==='visible'}];
record('gamedev.actionFields',()=>{equal(g,'actionFields',[text,text],[]);const fields=g.actionFields('godot','edit');assert.deepEqual(fields.map(x=>[x.key,x.kind]),[['node','text'],['property','choice'],['value','vec3'],['value','bool']]);assert.equal(g.actionFields('unity','edit')[0].kind,'json')});
record('gamedev.initialValues',()=>{equal(g,'initialValues',[fields],{name:text,value:2});equal(g,'initialValues',[[]],{});assert.equal(g.initialValues([{key:'name',initial:'visible'},...fields.slice(1)]).value,true)});
record('gamedev.visibleFields',()=>{equal(g,'visibleFields',[fields,{name:text}],fields.slice(0,2));equal(g,'visibleFields',[fields,{name:'visible'}],fields)});
record('gamedev.buildArgs',()=>{equal(g,'buildArgs',[fields,{name:' '+text+' ',value:12}],{...(text?{name:text}:{}),value:12});assert.throws(()=>g.buildArgs([{key:'v',kind:'vec3',label:'Position'}],{v:[1,2]}));assert.throws(()=>g.buildArgs([{key:'v',kind:'json',label:'Arguments'}],{v:'[]'}));equal(g,'buildArgs',[[{key:'*',kind:'json',label:'Arguments'}],{'*':JSON.stringify({message:text})}],{message:text})});
record('gamedev.keepSelection',()=>{const sessions=[{sessionId:'a',status:'ended',environment:'native-editor'},{sessionId:'b',status:'connected'}];equal(g,'keepSelection',['a',sessions],'a');equal(g,'keepSelection',['missing'+text,sessions],'missing'+text);equal(g,'keepSelection',['',sessions],'b');assert.equal(g.keepSelection('',[]),'')});
const tasks=Array.from({length:count},(_,i)=>({id:'t'+i,title:text,prompt:text,status:i?'waiting':'done',needs:i?['t0']:[]}));
record('conductor.turnKind',()=>{equal(c,'turnKind',[text+'-classify',text],'classify');equal(c,'turnKind',[text+'-plan',text],'plan');equal(c,'turnKind',[text+'-t0',text],'task')});
record('conductor.shapeJob',()=>{assert.equal(c.shapeJob(null),null);const args={id:'owned'+text,status:'interrupted',conductor:{phase:'completed',goal:text,tasks:tasks.map(x=>({...x,status:x.status==='done'?'completed':x.status})),receipts:[{runId:'owned'+text+'-plan',usage:{totalTokens:14},durationMs:9},{runId:'unreported',durationMs:4}]}};const before=JSON.stringify(args);const r=c.shapeJob(args);assert.equal(r.phase,'interrupted');assert.equal(r.live,false);assert.equal(r.goal,text);assert.equal(r.tasks.length,count);assert.equal(r.tokens,14);assert.equal(r.tokensComplete,false);assert.equal(r.durationMs,13);assert.equal(r.canStart,false);assert.equal(JSON.stringify(args),before)});
record('conductor.mergeJobs',()=>{const prior=tasks.map(x=>({id:x.id,createdAt:'2026-10-01',title:text}));const r=c.mergeJobs(prior,[{id:'fresh',createdAt:'2026-10-02'},{id:'t0',createdAt:'2026-10-03',title:'replacement'}]);assert.equal(r[0].title,'replacement');assert.equal(r[1].id,'fresh');assert.equal(new Set(r.map(x=>x.id)).size,r.length);assert.equal(prior.length,count)});
record('conductor.planProblems',()=>{equal(c,'planProblems',[{goal:text,folder:text,checks:text},{planner:true,executor:true,verifier:true}],text?[]:["Say what should be true when it's done.","Choose the folder it works in.","Add at least one check the verifier can prove."]);assert.ok(c.planProblems({goal:'g',folder:'f',checks:'check'},{}).at(-1).includes('planner, executor, verifier'))});
record('missions.shapeMission',()=>{const r=m.shapeMission({id:'m',goal:text,tasks:tasks.map(x=>({...x,id:'m:'+x.id,needs:x.needs.map(x=>'m:'+x)}))});assert.equal(r.tasks.length,count);assert.equal(r.counts.done,count?1:0);assert.equal(r.progress,count?1/count:0);if(count>1){assert.equal(r.tasks[1].localId,'t1');assert.equal(r.tasks[1].level,1)}});
const draft={goal:text,folder:text,acceptance:text,maxTokens:'10',tasks:tasks.map(x=>({...x,harness:'codex',model:'',needs:[x.id,'removed',...x.needs]}))};
record('missions.draftProblems',()=>{const r=m.draftProblems(draft);assert.equal(r.length,text?0:4);assert.equal(m.draftProblems({...draft,maxTokens:'-1'}).at(-1),'The token budget must be a positive number.')});
record('missions.createRequest',()=>{const before=JSON.stringify(draft);const r=m.createRequest(draft);assert.equal(r.goal,text);assert.equal(r.folder,text);assert.deepEqual(r.acceptanceChecks,text?[text]:[]);assert.deepEqual(r.budget,{maxTokens:10});assert.equal(r.tasks.length,count);for(const task of r.tasks)assert.deepEqual(task.needs,task.id==='t0'?[]:['t0']);assert.equal(JSON.stringify(draft),before)});
record('missions.planPrompt',()=>{const r=m.planPrompt(text,text);assert.ok(r.startsWith('Plan a Neyvia mission for this goal: '+text+'\nProject folder: '+text+'\n'));assert.ok(r.includes("Do not start it: I'll review and start it from Missions."))});
record('outputs.perceptionTarget',()=>{equal(o,'perceptionTarget',['file',text],'file:'+text);equal(o,'perceptionTarget',['window',text,42],'window:'+text+':42')});
record('outputs.parsePerceptionTarget',()=>{equal(o,'parsePerceptionTarget',['file:'+text],text?{layer:'file',path:text}:null);equal(o,'parsePerceptionTarget',['window:'+text+':42'],text?{layer:'window',sessionId:text,windowId:42}:null);assert.equal(o.parsePerceptionTarget('browser:javascript:alert(1)'),null)});
record('outputs.outsideDock',()=>{equal(o,'outsideDock',[{x:0,y:0},null],false);equal(o,'outsideDock',[{x:128,y:0},{left:0,right:100,top:0,bottom:100}],false);equal(o,'outsideDock',[{x:129,y:0},{left:0,right:100,top:0,bottom:100}],true)});
record('outputs.dropSpot',()=>{equal(o,'dropSpot',[{x:-100,y:-100},100,100],{x:0,y:0});equal(o,'dropSpot',[{x:1000,y:1000},100,100],{x:1,y:1})});
record('nightshift.shapeBoard',()=>{const before=JSON.stringify(tasks);const r=n.shapeBoard(tasks);assert.equal(r.tasks.length,count);assert.equal(r.counts.done,count?1:0);assert.equal(r.progress,count?1/count:0);assert.equal(JSON.stringify(tasks),before);if(count>1){assert.deepEqual(r.tasks[1].open,[]);assert.equal(r.tasks[1].level,1);assert.deepEqual(r.tasks[0].dependents,tasks.slice(1).map(x=>x.id))}});
record('nightshift.startable',()=>{equal(n,'startable',[[{id:text,status:'waiting',owner:'Paul'},{id:'armed',status:'waiting',armed:true},{id:'blocked',status:'blocked'},{id:'admit',status:'waiting'}]],[{id:'admit',status:'waiting'}]);assert.deepEqual(n.startable([]),[])});
record('nightshift.evidenceView',()=>{equal(n,'evidenceView',[text],text?{kind:'note',label:text,detail:text}:null);equal(n,'evidenceView',[{type:'file',path:'folder/'+text,sha256:'bound'}],{kind:'file',label:text||'folder',detail:'folder/'+text+'\nSHA-256 bound',path:'folder/'+text})});
record('nightshift.morning',()=>{assert.equal(n.morning(null),null);const r=n.morning({tasks,usage:{reportedTokens:12,complete:false},perHarness:{codex:{unknownCompletedRuns:2,knownRuns:3}},blocked:[{id:text}],waitingOnPaul:[{id:'paul'}],elapsedSeconds:8});assert.equal(r.tokens,12);assert.equal(r.tokensComplete,false);assert.equal(r.unknownRuns,2);assert.equal(r.workSeconds,8);assert.equal(r.done.length,count?1:0);assert.equal(r.blocked[0].id,text);assert.equal(r.empty,!count)});
record('nightshift.quietNow',()=>{const now=new Date('2026-10-05T12:00:00Z');equal(n,'quietNow',[{start:'08:00',end:'12:00',timeZone:'UTC'},now],false);equal(n,'quietNow',[{start:'12:00',end:'13:00',timeZone:'UTC'},now],true);equal(n,'quietNow',[{start:'13:00',end:'08:00',timeZone:'UTC'},now],false);equal(n,'quietNow',[{start:'08:00',end:'08:00',timeZone:'UTC'},now],true);assert.equal(n.quietNow({start:text,end:text},now),false)});
record('nightshift.treeLayout',()=>{const board=n.shapeBoard(tasks);const r=n.treeLayout(board);assert.equal(r.leaves.length,count);assert.deepEqual(r.leaves.map(x=>x.task.id).sort(),tasks.map(x=>x.id).sort());assert.ok(r.leaves.every(x=>Number.isFinite(x.x)&&Number.isFinite(x.y)));assert.equal(r.width,280);assert.equal(r.height,180)});
const policy={maxTaskTokens:count?1000000:null,quietGpuHours:{start:'22:00',end:'06:00',timeZone:'UTC'},gpuReservedFor:text||null,perHarnessBudgets:{codex:{maxTokens:100,maxSeconds:3600}}};
record('nightshift.policyForm',()=>{const r=n.policyForm(policy);assert.equal(r.maxTaskTokens,count?'1000000':'');assert.equal(r.quietTz,'UTC');assert.equal(r.quietStart,'22:00');assert.equal(r.gpuReservedFor,text||'ASR');assert.deepEqual(r.budgets.codex,{tokens:'100',hours:'1'})});
record('nightshift.policyPatch',()=>{const form=n.policyForm(policy);const r=n.policyPatch(form);assert.deepEqual(r.problems,[]);assert.equal(r.patch.maxTaskTokens,policy.maxTaskTokens);assert.deepEqual(r.patch.quietGpuHours,policy.quietGpuHours);assert.equal(r.patch.perHarnessBudgets.codex.maxSeconds,3600);assert.ok(n.policyPatch({...form,maxConcurrent:'-1'}).problems.length);assert.ok(n.policyPatch({...form,budgets:{opencode:{tokens:'10'}}}).problems.some(x=>x.startsWith('OpenCode')))});
record('chat.cancellation-result',()=>{equal(a,'isChatCancellationResult',[{status:text}],false);equal(a,'isChatCancellationResult',[{status:' CANCELLED '}],true);equal(a,'isChatCancellationResult',[{compartment:{state:'cancelled'}}],true);equal(a,'isChatCancellationResult',[{cancelled:true}],true)});
record('chat.cancelled',()=>{equal(a,'cancelledChatTurnPatch',[{title:text,body:text}],{title:text||'Stopped by you.',detail:'Stopped by you.',pending:false,tone:'neutral',source:'chat-cancelled'});assert.equal(a.cancelledChatTurnPatch({title:'thinking...'},text).title,text||'Stopped by you.')});
record('chat.runtime-source',()=>{equal(v,'isRealRuntimeReplySource',[text],false);for(const source of ['backend-model-message','backend-runtime-reply','runtime-stream','runtime-compartment','runtime_compartment'])assert.equal(v.isRealRuntimeReplySource(' '+source.toUpperCase()+' '),true);assert.equal(v.isRealRuntimeReplySource('synthetic-provider'),false)});
record('dictation.anchor',()=>equal(q,'shiftAnchor',[text+'tail',text+'insertedtail',text.length],text.length+8));
record('dictation.sentence-state',()=>{equal(q,'endsMidSentence',[text],!!text);equal(q,'endsMidSentence',[text+'\n'],false);equal(q,'endsMidSentence',[text+'.'],false)});
record('dictation.join',()=>{equal(q,'joinSpoken',[text,'The word'],text?text+' the word':'The word');equal(q,'joinSpoken',[text,', extra'],text+', extra');equal(q,'joinSpoken',[text,''],text)});
record('dictation.sentence-boundary',()=>{equal(q,'lastSentenceStart',[text+'. Previous. Last'],text.length+12);equal(q,'lastSentenceStart',[''],0)});
record('dictation.scratch',()=>equal(q,'dropLastPhrase',[text+', final phrase'],text+','));
record('dictation.delete-sentence',()=>equal(q,'dropLastSentence',[text+'. Last sentence'],text+'.'));
record('dictation.edit',()=>{const r=q.applySegments(text+'TAIL',text.length,[{type:'text',text:'new words'},{type:'command',op:'send'}]);assert.ok(r.value.endsWith(' TAIL'));assert.equal(r.actions.send,true);assert.equal(r.actions.cancel,false);assert.equal(r.caret,r.end);assert.deepEqual(r.done,['send']);const cancelled=q.applySegments(text,text.length,[{type:'text',text:'discarded'},{type:'command',op:'cancel'}]);assert.equal(cancelled.value,text);assert.equal(cancelled.inserted,'')});
record('dictation.preview',()=>{const r=q.previewParts(text+'TAIL',text.length,'stable','pending');assert.equal(r.before,text);assert.equal(r.stable,text?' stable':'Stable');assert.equal(r.provisional,' pending');assert.equal(r.after,' TAIL')});
record('dictation.overlap',()=>{equal(q,'withoutOverlap',[text,text+' fresh'],text?'fresh':'fresh');equal(q,'withoutOverlap',['earlier stable','stable fresh'],'fresh')});
record('dictation.answer',()=>{const r=q.normalizeAnswer({text},true);assert.equal(r.stable,text);assert.equal(r.provisional,'');assert.deepEqual(r.segments,text?[{type:'text',text}]:[]);assert.equal(r.policy,false);const modern=q.normalizeAnswer({stable:text,provisional:text+' fresh'},false);assert.equal(modern.stable,text);assert.equal(modern.provisional,'fresh');assert.equal(modern.policy,true)});
record('dictation.commands',()=>equal(q,'liveCommands',[[{type:'text',text},{type:'command',op:'send'},{type:'command',name:'cancel'}]],['send','cancel']));
record('composer.imageBlocker',()=>{equal(composer,'imageBlocker',[{appName:text,capabilities:{images:true},model:{label:text,images:false}}],{reason:(text||'undefined')+" doesn't accept images. Pick another model to send them."});assert.equal(composer.imageBlocker({capabilities:{images:true},model:{images:true}}),null)});
record('composer.toolMutates',()=>{equal(composer,'toolMutates',[{mutability_class:text}],!!text);assert.equal(composer.toolMutates({mutability_class:'read'}),false);assert.equal(composer.toolMutates({mutability_class:'write'}),true)});
record('image.provider.adapter',()=>{if(!text)assert.throws(()=>providers.registerImageProviderAdapter({id:''}));const adapter=providers.registerImageProviderAdapter({id:'  owned-'+text+'  ',name:text});assert.equal(adapter.id,'owned-'+text);assert.equal(typeof adapter.request,'function');assert.equal(providers.getProviderAdapter(adapter.id),adapter);assert.throws(()=>providers.registerImageProviderAdapter({id:adapter.id}));});
if(category==='empty')record('image.prompt.presets',()=>{assert.deepEqual(image.IMAGE_PROMPT_PRESETS.map(x=>x.id),['saas-workbench','artifact-review','mobile-safe-controls']);assert.ok(image.IMAGE_PROMPT_PRESETS.every(x=>x.strength>0&&x.strength<1&&x.negative.includes('generic AI-purple glow')));assert.ok(image.IMAGE_PROMPT_PRESETS[1].negative.includes('invented metrics'));assert.ok(image.IMAGE_PROMPT_PRESETS[2].style.includes('44px targets'))});
const project=structuredClone(image.DEFAULT_IMAGE_PROJECT);project.prompt.text=text;project.provider.id='local-composition-draft';
const initial=JSON.stringify(project);
let imageDraft,blocked;
try{
 imageDraft=await providers.requestProviderOperation(project,'generate');
 const blockedProject={...project,provider:{...project.provider,id:'codex-gpt-image2'}};
 blocked=await providers.requestProviderOperation(blockedProject,'generate');
 assert.equal(imageDraft.kind,'local-draft');assert.equal(imageDraft.meta.providerStatus,'fallback');assert.ok(imageDraft.layer.src.startsWith('data:image/svg+xml'));
 assert.equal(blocked.kind,'provider-blocked');assert.equal(blocked.blockedReason,'backend_unavailable');assert.equal(blocked.meta.providerStatus,'blocked');
 for(const result of [imageDraft,blocked]){assert.ok(result.meta.requestId);assert.ok(result.meta.receipt.promptHash);assert.equal(result.meta.receipt.promptEvidence,text);assert.ok(result.meta.receipt.failureReason);assert.ok(result.meta.requestTimeline.durationMs>=0);assert.equal(result.meta.layerHandoff.stage,result.layer?'layer_ready':'no_layer');}
 assert.equal(JSON.stringify(project),initial);
 rows.push({contract:'image.provider.receipt',status:'passed',detail:{productionLocalDraftExecuted:true,missingBackendRefused:true,providerContacted:false,renderedProof:false}});
}catch(error){rows.push({contract:'image.provider.receipt',status:'failed',detail:String(error.stack||error).slice(-2000)});}
record('image.provider.history',()=>{
 assert.ok(imageDraft&&blocked);
 const local=providers.applyProviderResult(project,imageDraft,'generate');
 assert.deepEqual(local.history,project.history.filter(image.isRealImageSession),'Local draft entered real-provider session history');
 assert.equal(local.layers.length,project.layers.length+1);
 const updated=providers.applyProviderResult(project,blocked,'generate');const h=updated.history[0];
 assert.equal(h.status,'provider_blocked');assert.equal(h.requestId,blocked.meta.requestId);assert.deepEqual(h.receipt,blocked.meta.receipt);assert.deepEqual(h.requestTimeline,blocked.meta.requestTimeline);assert.equal(h.outputArtifactPath,'');assert.equal(h.issueThread.requestId,blocked.meta.requestId);assert.equal(updated.layers.length,project.layers.length);
 assert.equal(JSON.stringify(project),initial);
});
console.log(JSON.stringify(rows));
'''

ATTACH_PERMISSION_NODE = r'''
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [repo,source]=process.argv.slice(1);
const owner=await import(pathToFileURL(path.join(repo,'web/src/neyvia/next/nxComposerModel.js')));
const store=owner.createDraftStore();
store.update('origin',[{name:'keeper',mime:'image/png',data:'aGVsbG8='}]);
store.update('other',[{name:'other keeper',mime:'image/png',data:'a2VlcA=='}]);
const before=JSON.stringify([store.get('origin'),store.get('other')]);let reads=0;
const explanation=await owner.attachToDraft(store,'origin',[{name:'owned.png',type:'image/png',size:5}],async files=>{
 reads++;const data=await fs.readFile(source);return files.map(file=>({name:file.name,mime:file.type,data:data.toString('base64')}));
});
assert.equal(reads,1);assert.match(explanation,/EACCES|EPERM|EBUSY|permission denied|operation not permitted/i);
assert.equal(JSON.stringify([store.get('origin'),store.get('other')]),before);
console.log(JSON.stringify({actualFileReadSharingDenied:true,originAndOtherDraftUnchanged:true,returnedReadableRefusal:true}));
'''

IMAGE_PARALLEL_NODE = r'''
import assert from 'node:assert/strict';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [repo,category]=process.argv.slice(1);
const image=await import(pathToFileURL(path.join(repo,'web/src/neyvia/imagePlaygroundState.js')));
const owner=await import(pathToFileURL(path.join(repo,'web/src/neyvia/imageProviderAdapters.js')));
const project=structuredClone(image.DEFAULT_IMAGE_PROJECT);const before=JSON.stringify(project);
const count=category==='concurrency'?16:1;
const rows=await Promise.all(Array.from({length:count},async(_,i)=>{
 const value={...project,prompt:{...project.prompt,text:'Actual local operation '+i},provider:{...project.provider,id:i%2?'codex-gpt-image2':'local-composition-draft'}};
 const result=await owner.requestProviderOperation(value,'generate');
 assert.equal(result.kind,i%2?'provider-blocked':'local-draft');assert.equal(result.meta.providerStatus,i%2?'blocked':'fallback');
 assert.equal(result.meta.receipt.promptEvidence,value.prompt.text);assert.ok(result.meta.receipt.failureReason);assert.ok(result.meta.receipt.promptHash);
 assert.equal(result.meta.layerHandoff.stage,result.layer?'layer_ready':'no_layer');assert.ok(result.meta.requestTimeline.durationMs>=0);
 if(i%2)assert.equal(result.blockedReason,'backend_unavailable');
 return result.meta.requestId;
}));
assert.equal(new Set(rows).size,count);assert.equal(JSON.stringify(project),before);
console.log(JSON.stringify({actualBuiltinLocalOperations:count,uniqueRequestReceipts:count,backendTransportAbsent:true,providerContacted:false,renderedProof:false}));
'''


def run(root, contracts, categories):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    repo = Path(__file__).resolve().parents[2]
    rows = []
    for category in categories:
        if category == "permissions" and "composer.attachResult" in contracts:
            from .edge_fixture_models import _deny_read
            area = Path(root) / ("attachment-permissions-" + uuid.uuid4().hex[:8]); area.mkdir(parents=True)
            source = area / "owned.png"; source.write_bytes(b"hello")
            with _deny_read(source):
                result = subprocess.run(["node", "--input-type=module", "-e", ATTACH_PERMISSION_NODE, str(repo), str(source)],
                    cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=30, **hidden_windows_subprocess_kwargs())
            rows.append({"id": "c7d-ui.composer.attachResult.permissions", "contracts": ["composer.attachResult"], "category": category,
                "status": "passed" if not result.returncode else "failed", "detail": json.loads(result.stdout) if not result.returncode else result.stderr[-2500:],
                "boundary": "Actual attachment model with real OS-denied supplied file reader; no browser FileReader/rendered claim"})
        if category in {"concurrency", "offline"} and "image.provider.receipt" in contracts:
            result = subprocess.run(["node", "--input-type=module", "-e", IMAGE_PARALLEL_NODE, str(repo), category],
                cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=30, **hidden_windows_subprocess_kwargs())
            rows.append({"id": "c7d-ui.image.provider.receipt." + category, "contracts": ["image.provider.receipt"], "category": category,
                "status": "passed" if not result.returncode else "failed", "detail": json.loads(result.stdout) if not result.returncode else result.stderr[-2500:],
                "boundary": "Actual built-in local draft and absent backend transport receipts; no provider or rendered proof"})
    for category in categories:
        if category not in {"empty", "huge", "unicode"}:
            continue
        result = subprocess.run(["node", "--input-type=module", "-e", NODE, str(repo), category],
                                cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=90,
                                **hidden_windows_subprocess_kwargs())
        if result.returncode:
            raise RuntimeError(result.stderr[-3000:])
        for case in json.loads(result.stdout):
            if case["contract"] in contracts:
                rows.append({"id": f"c7d-ui.{case['contract']}.{category}", "contracts": [case["contract"]],
                             "category": category, "status": case["status"], "detail": case["detail"],
                             "boundary": "Actual production argument model, synthetic supplied data; no rendered/device/provider proof",
                             "proofType": "production_argument_model"})
    for category in categories:
        for family, identities, supported in (
            ("dictation-names", {"dictation.names.persisted", "dictation.names.scoped"}, {"empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "stale"}),
            ("dictation-prompt", {"dictation.prompt.structure", "dictation.prompt.commands", "dictation.prompt.route"}, {"empty", "huge", "unicode"}),
            ("dictation-preallocation", {"dictation.stream.preallocation"}, {"empty", "huge", "unicode", "concurrency"}),
            ("livecontrol-pure", LIVE_PURE, {"empty", "huge", "unicode"}),
        ):
            selected = identities & contracts.keys()
            if not selected or category not in supported:
                continue
            scratch = Path(root) / (family + "-" + category + "-" + uuid.uuid4().hex[:8])
            scratch.mkdir(parents=True)
            row = {"id": f"c7d-ui.{family}.{category}", "contracts": sorted(selected), "category": category,
                   "boundary": "Exact local production dictation parser/policy store; no audio engine or microphone proof",
                   "proofType": "production_local_owner"}
            try:
                row.update(status="passed", detail=_livecontrol_local(scratch, category) if family == "livecontrol-pure" else _dictation_local(scratch, family, category))
            except Exception as error:
                row.update(status="failed", detail={"type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()[-2500:]})
            rows.append(row)
    return rows


def _livecontrol_local(root, category):
    import importlib.util
    from urllib.parse import urlsplit, parse_qs, quote
    script = Path(__file__).resolve().parents[2] / "scripts/verify_authenticated_live_control.py"
    spec = importlib.util.spec_from_file_location("c7d_livecontrol_compiler", script)
    owner = importlib.util.module_from_spec(spec); spec.loader.exec_module(owner)
    text = "" if category == "empty" else "long-diagnostic " * 4000 if category == "huge" else "東京 café e\u0301 العربية"
    url = "http://127.0.0.1:48744/control?fixture=unsafe&tag=" + quote(text) + "#old"
    result = owner._builder_url(url)
    parsed = urlsplit(result); query = parse_qs(parsed.query)
    assert parsed.scheme == "http" and parsed.netloc == "127.0.0.1:48744" and not parsed.fragment
    assert "fixture" not in query and query["mode"] == ["builder"] and query["surface"] == ["builder"]
    assert query.get("tag", [""])[0] == text
    synthetic = "owned-synthetic-secret-123456"
    diagnostic = owner._redact_text(text + " password=" + synthetic + " Authorization: Bearer synthetic-bearer api_key=synthetic-key", [synthetic])
    assert len(diagnostic) <= 1200 and all(value not in diagnostic for value in (synthetic, "synthetic-bearer", "synthetic-key"))
    measured = [owner._check("owned-observation", True, "local receipt observation")]
    skipped = [owner._skipped_check(identity, "No browser measurement") for identity in owner.DOM_CHECK_IDS]
    report = owner._assemble_report(measured + skipped, {"missions": []}, {}, with_browser=False, url=url, report_path=root / "report.json")
    assert report["ok"] and not report["complete"] and not report["summary"]["browserProofComplete"]
    assert report["summary"]["measuredCheckCount"] == 1 and report["summary"]["skippedCheckCount"] == len(skipped)
    failed = owner._assemble_report(measured + [owner._check("actual-refusal", False, text)] + skipped, {}, {}, with_browser=False, url=url, report_path=root / "failed.json")
    assert not failed["ok"] and not failed["complete"] and failed["summary"]["failedCheckCount"] == 1
    assert not list(root.iterdir()), "Compiler unexpectedly wrote report files"
    return {"inputCharacters": len(text), "diagnosticCharacters": len(diagnostic), "unmeasuredDomClaims": len(skipped), "apiReportCannotClaimRenderedProof": True, "networkCalls": 0}


def _dictation_local(root, family, category):
    from . import neyvia_dictation as owner
    from .neyvia_prompt_dictation import process_prompt
    def require(condition, message):
        if not condition:
            raise AssertionError(message)
    def refuse(action):
        try:
            action()
        except (ValueError, OSError):
            return
        raise AssertionError("Invalid dictation operation was admitted")
    if family == "dictation-prompt":
        value = "" if category == "empty" else " ".join("word" + str(i) for i in range(4000)) if category == "huge" else "東京 café e\u0301 العربية"
        preview = process_prompt(value + " send it", ["en"], final=False)
        require(preview["text"] == value + " send it" and preview["commands"] == [] and preview["requiresPreview"], "Unfinished utterance executed a command or changed text")
        final = process_prompt(value + " send it", ["en"], final=True)
        require(final["commands"] == [{"op": "send"}] and "send it" not in final["text"] and final["requiresPreview"], "Final send remained words or escaped preview")
        quoted = process_prompt('please type "send it" here', ["en"])
        require(quoted["commands"] == [] and '"send it"' in quoted["text"], "Quoted command acquired authority")
        for phrase, language, route in (("the build is ready", "en", "phonon2"), ("bonjour je veux le document", "fr", "qwen"), ("je veux le document and the build", "mixed", "qwen")):
            actual = process_prompt(phrase, ["en"])
            require(actual["language"] == language and actual["route"] == route, "Text language selected incorrect declared route")
        refuse(lambda: process_prompt("x" * 100001))
        refuse(lambda: process_prompt("hello", ["en"] * 21))
        return {"inputCharacters": len(value), "previewLiteral": True, "quotedCommandLiteral": True, "declaredRoutesChecked": 3, "enginesContacted": 0}
    if family == "dictation-preallocation":
        before = dict(owner._sessions)
        invalid = [("append", "", 0, b""), ("append", "owned-audio", -1, b""), ("wrong", "owned-audio", 0, b""), ("append", "owned-audio", 0, b"x")]
        if category == "huge":
            invalid.append(("append", "owned-audio", 0, b"x" * (4 * 1024 * 1024 + 2)))
        if category == "unicode":
            invalid.append(("append", "東京-audio", 0, b""))
        def reject_one(args):
            refuse(lambda: owner.stream(root, *args))
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(reject_one, invalid * 8))
        else:
            for args in invalid:
                reject_one(args)
        require(owner._sessions == before and not list(root.iterdir()), "Rejected audio allocated state or persisted engine settings")
        return {"rejectedBeforeAllocation": len(invalid) * (8 if category == "concurrency" else 1), "engineCalls": 0, "allocatedSessions": 0}
    canonical = "Owned canonical" if category != "unicode" else "東京 café"
    aliases = ["owned alias"] if category != "huge" else ["a" * 90 + str(i) for i in range(30)]
    if category == "unicode":
        aliases = ["雪 café e\u0301 العربية"]
    if category == "empty":
        refuse(lambda: owner.names(root, {"action": "add", "to": "", "from": []}))
    if category == "interrupted":
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        code = "import os,sys;from pathlib import Path;from grant_agent.proof_credential_guard import install;r=Path(sys.argv[1]);install(r);from grant_agent.neyvia_dictation import names;names(r,{'action':'add','to':'Owned canonical','from':['owned alias']});os._exit(23)"
        result = subprocess.run([sys.executable, "-c", code, str(root.resolve())], capture_output=True,
                                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
                                timeout=30, **hidden_windows_subprocess_kwargs())
        require(result.returncode == 23, "Interruption child did not finish durable policy write")
    else:
        owner.names(root, {"action": "add", "to": canonical, "from": aliases})
    path = owner._policy_path(root, "names")
    require(json.loads(path.read_bytes())[canonical] == sorted(aliases), "Returned alias registration differs from disk bytes")
    if category == "concurrency":
        def add(index):
            return owner.names(root, {"action": "add", "to": canonical, "from": [f"parallel alias {index}"]})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add, range(16)))
        require(set(json.loads(path.read_bytes())[canonical]) == set(aliases) | {f"parallel alias {i}" for i in range(16)}, "Concurrent alias additions lost a row")
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        before = path.read_bytes()
        with _deny_read(path):
            refuse(lambda: owner.names(root, {"action": "add", "to": canonical, "from": ["denied alias"]}))
        require(path.read_bytes() == before, "Denied alias mutation replaced original keeper")
    if category == "stale":
        old = owner.names(root, {})
        owner.names(root, {"action": "add", "to": canonical, "from": ["changed alias"]})
        current = owner.names(root, {})
        require("changed alias" not in next(r["from"] for r in old["names"] if r["to"] == canonical) and "changed alias" in next(r["from"] for r in current["names"] if r["to"] == canonical), "Existing owner reused stale alias cache or mutated old return")
    other = root / "other"; other.mkdir()
    require(all(r["to"] != canonical for r in owner.names(other, {})["names"]), "Custom aliases leaked across workspace boundary")
    refuse(lambda: owner.names(root, {"action": "remove", "to": "Neyvia", "from": ["neyvia"]}))
    return {"policyBytes": path.stat().st_size, "customAliases": len(json.loads(path.read_bytes())[canonical]), "foreignWorkspaceIsolated": True, "builtinRemovalRefused": True}


def blocker(contract, category):
    identity = contract.get("id", "")
    if identity == "image.prompt.presets" and category != "empty":
        return {"kind": "not_applicable", "reason": "IMAGE_PROMPT_PRESETS is a fixed zero-argument module catalog. Its exact invariant has no supplied size/text/grant/store/worker/transport/revision field to perturb; the empty-category startup import checks all IDs, strengths and guidance. Editing application source itself is outside generated input categories."}
    if identity in IMAGE_LOCAL and category in {"concurrency", "interrupted", "permissions", "offline", "stale"}:
        if identity == "image.provider.receipt":
            if category in {"concurrency", "offline"}:
                return None
            if category in {"interrupted", "permissions"}:
                return {"kind": "not_applicable", "reason": f"Exact receipt assembly in requestProviderOperation copies completed adapter output into caller-owned request/timing/handoff metadata; it owns no durable writer, resumable queue or OS grant field for {category}. Its actual built-in draft and missing-backend branches are exercised directly; permission admission and interrupted external provider execution belong to their separate backend/provider contracts, and are not established by these receipts."}
        return {"kind": "not_applicable", "reason": f"Inspected exact {identity} registers/returns a local adapter descriptor or applies a supplied provider receipt into an immutable caller-owned project history. It owns no durable store/revision or OS grant; {category} cannot exercise a runtime mechanism there. Actual transport/rendered/provider execution remains separate from these local argument-model observations."}
    if identity in LIVE_PURE and category not in {"empty", "huge", "unicode"}:
        return {"kind": "not_applicable", "reason": f"Inspected exact {identity} owner in verify_authenticated_live_control.py is a supplied URL/diagnostic/report classification transform. It neither authenticates nor invokes a browser or network request; no grant, concurrent store, worker or revision precondition exists for {category}. Browser DOM/provider claims remain separate obligations."}
    if identity in LOCAL_IDS:
        if identity.startswith("dictation.names"):
            if category == "offline":
                return {"kind": "not_applicable", "reason": "The exact local dictation alias policy owner reads/writes its selected workspace JSON. It contains no speech engine request or network operation; network outage has no mechanism in this policy mutation."}
            return None
        if category not in {"empty", "huge", "unicode", "concurrency"} or category == "concurrency" and identity.startswith("dictation.prompt"):
            return {"kind": "not_applicable", "reason": f"Exact {identity} parses supplied text or rejects invalid stream metadata before settings/timers/engine allocation. It has no durable writer, permission admission, endpoint call or resumable worker in this checked boundary. {category} cannot reach an effect at the precondition/parser owner; valid live engine sessions require separate audio proof."}
        return None
    if identity == "composer.base64Chars" and category == "unicode":
        return {"kind": "not_applicable", "reason": "Inspected nxComposerModel.raw_base64Chars takes only numeric file byte count. It has no text/filename argument; Unicode metadata is exercised in planImageReads/admitImages, not this scalar length formula."}
    if identity in COMPOSER_PURE | {"composer.draftUpdate"} and category in {"concurrency", "interrupted", "permissions", "offline", "stale"}:
        if identity == "composer.draftUpdate" and category == "concurrency":
            return None
        return {"kind": "not_applicable", "reason": f"Inspected exact {identity} in nxComposerModel.js computes from supplied arguments or atomically replaces a caller-owned synchronous Map entry. It has no persistent revision token, OS grant, transport or interruptible worker for {category}. Route availability inputs remain decision data; asynchronous attachment reading has separate composer.attachResult obligations."}
    if identity not in IDS or category in {"empty", "huge", "unicode"}:
        return None
    prefix = identity.split(".")[0]
    owner = OWNERS[prefix][0] if prefix in OWNERS else "next/nxDictationEdit.js" if prefix == "dictation" else "chatCancellation.js / transcriptVisibility.js"
    return {"kind": "not_applicable", "reason": f"Inspected exact {identity} at web/src/neyvia/{owner} is a synchronous argument-only model. It receives snapshots and returns a fresh value without OS grant admission, transport, durable worker, shared revision or I/O. {category} has no mechanism at this exact owner. Supplied terminal/blocked state assertions cover presentation only; real execution/rendering has separate proof obligations."}
