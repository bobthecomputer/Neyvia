"""Exact supplied-input control projections; no rendered or runtime proof."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

PURE_IDS = {"attention." + name for name in ("activity", "description", "filter", "projects", "recent", "sections", "showcase", "subagents", "thread")}
PURE_IDS |= {"autopilot." + name for name in ("scopeTools", "scopeOf", "attributeCalls", "checkLine")}
PURE_IDS |= {"batch.runtime-options", "mission.review.projection", "proofs-e.chat.streamTransition", "proofs-e.chat.safe-display"}
NODE_IDS = {"attention.activity", "attention.recent", "attention.showcase", "attention.subagents", "autopilot.scopeTools", "autopilot.scopeOf", "batch.runtime-options", "mission.review.projection", "proofs-e.chat.surfaces"}

NODE = r'''
import assert from 'node:assert/strict';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [repo,category]=process.argv.slice(1);
const load=name=>import(pathToFileURL(path.join(repo,'web/src/neyvia',name)));
const [attention,showcase,subagents,autopilot,mode,mission,workspace]=await Promise.all(['neyviaAttentionInbox.js','neyviaAttentionFixtures.js','neyviaSubagents.js','next/nxAutopilotModel.js','neyviaProductMode.js','missionControlModel.js','workspaceModel.js'].map(load));
const text=category==='empty'?'':category==='huge'?'owned input '.repeat(2048).trim():'雪 café e\u0301 العربية';
const count=category==='empty'?0:category==='huge'?512:3;const rows=[];
function check(contract,fn){try{fn();rows.push({contract,status:'passed',detail:{inputCharacters:text.length,inputRows:count,renderedProof:false}})}catch(error){rows.push({contract,status:'failed',detail:String(error.stack||error).slice(-2500)})}}
check('attention.activity',()=>{const now=Date.parse('2026-10-05T12:00:00Z');assert.equal(attention.attentionActivityTier(text,now),'unknown');for(const [age,tier] of [[1,'now'],[15*60000,'recent'],[6*3600000,'today'],[24*3600000,'older']])assert.equal(attention.attentionActivityTier(now-age,now),tier)});
check('attention.recent',()=>{const now=Date.parse('2026-10-05T12:00:00Z');const thread=(id,at)=>attention.projectAttentionThread({conversation:{conversationId:id,title:text,lastMeaningfulActivityAt:at},now});const first=thread('a','2020-01-01T00:00:00Z');const second=thread('b','2026-10-05T12:00:00Z');assert.ok(attention.compareRecentThreads(first,second)>0);assert.ok(attention.compareRecentThreads(second,first)<0);assert.equal(attention.compareRecentThreads(first,first),0)});
if(category!=='unicode')check('attention.showcase',()=>{const now=category==='huge'?8640000000000000:0;const rows=showcase.buildAttentionShowcaseConversations(now);assert.equal(rows.length,5);assert.equal(new Set(rows.map(x=>x.conversationId)).size,5);assert.deepEqual(rows.map(x=>Date.parse(x.lastMeaningfulActivityAt)),[4,11,38,74,780].map(minutes=>now-minutes*60000));assert.equal(rows[3].hasBlockingApproval,true);assert.equal(rows[2].hasVerificationEvidence,true)});
check('attention.subagents',()=>{const supplied=Array.from({length:count},(_,i)=>({id:'a'+i,name:text,status:i?'running':'waiting_for_approval',startedAt:count-i,task:text}));const before=JSON.stringify(supplied);const r=subagents.summarizeSubagents(supplied);assert.equal(r.total,count);assert.equal(r.state,count?'approval':'idle');assert.equal(r.blockingCount,count?1:0);assert.equal(r.needsYou,!!count);assert.equal(r.counts.working||0,Math.max(0,count-1));if(count){assert.equal(r.agents[0].id,'a0');assert.equal(r.agents[0].task,text);assert.equal(r.agents.at(-1).id,count>1?'a1':'a0')}assert.equal(JSON.stringify(supplied),before);const invalid=subagents.summarizeSubagents([null,{}, {id:'unknown',status:text}]);assert.equal(invalid.total,1);assert.equal(invalid.state,'unknown')});
check('autopilot.scopeOf',()=>{const tools=Array.from({length:count},()=>text);const before=JSON.stringify(tools);assert.equal(autopilot.scopeOf(tools),'look');assert.equal(autopilot.scopeOf([...tools,'workspace.write']),'edit');assert.equal(JSON.stringify(tools),before)});
check('autopilot.scopeTools',()=>{assert.deepEqual(autopilot.scopeTools(text),['workspace.read','workspace.search','runtime.environment','neyvia.manual.compiled','neyvia.manual.versions','neyvia.manual.index','neyvia.notes.list','neyvia.notes.read','neyvia.files.list','neyvia.files.stat','neyvia.files.read']);assert.equal(autopilot.scopeTools('edit').at(-1),'workspace.write')});
check('batch.runtime-options',()=>{const options=Array.from({length:count},(_,i)=>({value:'  owned-'+i+'  ',label:text,family:'owned'}));if(count)options.push({value:'owned-0',label:'Duplicate must not replace'},{runtime_id:'owned-extra',name:text});const before=JSON.stringify(options);const r=mode.mergeRuntimePickerOptions(options);assert.equal(new Set(r.map(x=>x.value)).size,r.length);assert.equal(r.filter(x=>x.family==='owned').length,count);if(count){assert.equal(r[0].value,'owned-0');assert.equal(r[0].label,text||'owned-0');assert.equal(r[count].value,'owned-extra')}for(const id of ['codex','claude-code','kimi-code','opencode','hermes','openclaw'])assert.ok(r.some(x=>x.value===id));assert.equal(JSON.stringify(options),before)});
check('mission.review.projection',()=>{const input={mission:null,workspace:{changed:[]},snapshot:{},pendingQuestions:[],pendingApprovals:[],inbox:[],previewMode:'fixture',lastPushReason:text};const before=JSON.stringify(input);const r=mission.buildMissionControlModel(input).drawers.builder.liveReviewStudio;const kinds=['file_change','browser_qa','computer_use','preview_refresh','verification','image_playground','operator_followup','progress_update','runtime_activity','continuation_supervisor','replay_marker'];assert.deepEqual(r.events.map(x=>x.kind).sort(),kinds.sort());assert.equal(new Set(r.events.map(x=>x.id)).size,kinds.length);assert.ok(r.annotationReadiness.blocks.every(x=>x.recoveryAction&&x.page&&(x.pin||x.rectangle)));const progress=r.events.find(x=>x.kind==='progress_update');assert.equal(progress.selectedSkills,r.plannerProof.selectedSkills);assert.equal(r.events.find(x=>x.kind==='continuation_supervisor').continuationSupervisor,r.continuationSupervisor);assert.equal(typeof r.continuationSupervisor.externalHeartbeatRequired,'boolean');for(const key of ['selectedSkills','designPrompts','nextIdea','model','provider','effort','executionRoot'])assert.ok(Object.hasOwn(r.continuationSupervisor.routePreservation,key));assert.ok(r.events.find(x=>x.kind==='replay_marker').replayMarkers.every(x=>x.deepLink.proofTarget&&x.deepLink.threadTarget));assert.equal(JSON.stringify(input),before)});
if(category==='empty')check('proofs-e.chat.surfaces',()=>{assert.deepEqual(workspace.WORKSPACE_SURFACE_IDS,workspace.WORKSPACE_SURFACES.map(x=>x.id));assert.equal(new Set(workspace.WORKSPACE_SURFACE_IDS).size,workspace.WORKSPACE_SURFACE_IDS.length);for(const id of ['agent','builder','harnesses','images','skills','browser'])assert.ok(workspace.WORKSPACE_SURFACE_IDS.includes(id));assert.equal(Object.isFrozen(workspace.WORKSPACE_SURFACE_IDS),true)});
console.log(JSON.stringify(rows));
'''


def run(root, contracts, categories):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    repo = Path(__file__).resolve().parents[2]
    rows = []
    if not NODE_IDS & contracts.keys():
        return rows
    for category in categories:
        if category not in {"empty", "huge", "unicode"}:
            continue
        result = subprocess.run(["node", "--input-type=module", "-e", NODE, str(repo), category], cwd=repo,
                                capture_output=True, text=True, encoding="utf-8", timeout=60, **hidden_windows_subprocess_kwargs())
        if result.returncode:
            raise RuntimeError(result.stderr[-2500:])
        for row in json.loads(result.stdout):
            if row["contract"] in contracts:
                rows.append({"id": "c7d-ui-control." + row["contract"] + "." + category, "contracts": [row["contract"]],
                             "category": category, "status": row["status"], "detail": row["detail"],
                             "boundary": "Actual production argument projection; synthetic supplied snapshots/default example fields, no rendered/runtime/provider proof",
                             "proofType": "production_argument_model"})
    return rows


def blocker(contract, category):
    identity = contract.get("id", "")
    if identity == "proofs-e.chat.desktop-stream" and category == "offline":
        return {"kind": "not_applicable", "reason": "Exact read_chat_stream reads selected local append bytes and a byte cursor. It has no transport, endpoint or connectivity condition; owner interruption, sharing denial and malformed/stale bytes are covered separately."}
    if identity == "proofs-e.chat.pollDelivery" and category == "stale":
        return {"kind": "not_applicable", "reason": "The exact polling delivery invariant delivers each supplied snapshot's events and adopts its finite byte cursor. It accepts no shared revision/CAS token and never mutates the upstream stream. Stale byte cursor and appended/current content are separately exercised at read_chat_stream; these polling projections cannot establish upstream revision admission."}
    if identity == "proofs-e.chat.surfaces" and category != "empty":
        return {"kind": "not_applicable", "reason": "WORKSPACE_SURFACE_IDS is a zero-argument frozen startup catalog. No supplied size/text/worker/grant/transport/revision exists for this category; startup import independently checks exact IDs, uniqueness and freeze."}
    if identity == "attention.showcase" and category == "unicode":
        return {"kind": "not_applicable", "reason": "The development-only showcase constructor accepts only a numeric millisecond clock. It has no supplied Unicode text argument; exact fixed records and clock-derived timestamps are exercised at zero and maximum supported clock values. These development examples are not execution evidence."}
    if identity in PURE_IDS and category in {"concurrency", "interrupted", "permissions", "offline", "stale"}:
        return {"kind": "not_applicable", "reason": f"Inspected exact {identity} at {contract.get('checkedAt', [])} computes from supplied arguments into a caller-owned value. No durable/shared revision, OS grant, transport or resumable worker is admitted there for {category}. State labels, routes, annotations and development example events are presentation data only, never evidence of executed work or rendering."}
    return None
