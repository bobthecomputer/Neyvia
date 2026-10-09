"""Generated chat trace, recovery, sidebar and shell bus feature witnesses.

Node runs the real production helpers; Python runs the real local byte-stream
writer/reader. The optional poll witness uses an owned loopback HTTP endpoint,
never a provider substitute. These are model/transport proofs, not rendering.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TEXTS = {"empty": "", "huge": "recorded output " * 5000,
         "unicode": "雪🙂e\u0301\u202e العربية"}
NODE_OWNERS = {
    "recovery.interrupted", "recovery.decision", "recovery.recorded", "recovery.unowned", "recovery.quiet", "recovery.merge",
    "activity.href", "activity.duration", "chat.stopped-visibility", "chat.stopped-body",
    *{"proofs-e.chat." + value for value in ("streamState", "normalizedCalls", "trace", "streamTransition", "pollDelivery", "phase", "chip", "activity", "visibleActivity", "presentation", "commandSummary", "stringField", "utf16", "diff", "family")},
    *{"proofs-e.shell." + value for value in ("kindOf", "placeSession", "agentSummary", "buildTree", "staleCandidates", "shouldOfferTidy", "initial", "overrides", "reducer", "parseNewChat", "searchLauncher")},
}


def blocker(contract, category):
    identity = contract.get("id", "")
    if identity == "proofs-e.chat.streamState" and category in {"huge", "unicode"}:
        return {"kind": "not_applicable", "reason": "The audited stream constructor accepts no input; size and Unicode mutations have no feature argument to modify. Its actual empty state is separately exercised."}
    if identity in NODE_OWNERS - {"proofs-e.chat.pollDelivery", "proofs-e.chat.streamTransition"} and category in {"concurrency", "interrupted", "permissions", "offline", "stale"}:
        return {"kind": "not_applicable", "reason": f"{identity} is an audited argument-only reducer/projector at {contract.get('checkedAt', [])}; it owns no durable revision, grant, worker or endpoint. Recorded status inputs are exercised separately, and do not constitute an actual {category} boundary."}
    return None


NODE = r'''
import assert from 'node:assert/strict';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {join} from 'node:path';
import http from 'node:http';
import * as stream from './web/src/neyvia/neyviaChatStream.js';
import * as recovery from './web/src/neyvia/neyviaChatRecovery.js';
import * as activity from './web/src/neyvia/neyviaRunActivity.js';
import * as visual from './web/src/neyvia/neyviaToolVisuals.js';
import * as presentation from './web/src/neyvia/neyviaToolCallPresentation.js';
import * as visibility from './web/src/neyvia/transcriptVisibility.js';
import * as sidebar from './web/src/neyvia/next/nxSidebarModel.js';
import * as os from './web/src/neyvia/next/nxOsStore.js';
import * as launcher from './web/src/neyvia/next/nxLauncherModel.js';
const root=process.argv[2], port=Number(process.argv[3]), rows=[];
assert.ok(Number.isInteger(port)&&((port>=48741&&port<=48749)||(port>=48941&&port<=48999)));const origin='http://127.0.0.1:'+port;
const variants={empty:'',huge:'recorded output '.repeat(5000),unicode:'雪🙂é\u202e العربية'};
const boundary='real production Node state/trace helper; independent input/output assertions; no rendered or provider claim';
async function run(contract,category,action){const start=performance.now();try{await action();rows.push({id:`chat-shell.${contract}.${category}`,category,contracts:[contract],status:'passed',detail:'Generated actual feature inputs preserved the independently observed state/evidence',boundary});}catch(error){rows.push({id:`chat-shell.${contract}.${category}`,category,contracts:[contract],status:'failed',detail:`${error.name}: ${error.message.slice(0,1800)}`,boundary});}rows.at(-1).durationMs=Math.round((performance.now()-start)*1000)/1000;}
const tool=(text,status='completed')=>({id:'call-1',tool:'workspace_read',status,input:text,output:text});
for(const [category,text] of Object.entries(variants)){
  const count=category==='empty'?0:category==='huge'?400:3;
  if(category==='empty') await run('proofs-e.chat.streamState',category,()=>{const a=stream.createNeyviaChatStreamState(),b=stream.createNeyviaChatStreamState();assert.equal(a.answer,'');assert.deepEqual(a.toolCalls,[]);assert.notEqual(a.toolCalls,b.toolCalls);});
  await run('proofs-e.chat.normalizedCalls',category,()=>{const input=Array.from({length:count},(_,i)=>({kind:'runtime.tool',data:{callId:`call-${i}`,tool:'workspace_read',toolStatus:'completed',input:text,output:JSON.stringify({ok:false,error:'observed refusal-'+i})}}));const actual=stream.normalizeNeyviaChatStreamToolCalls(input);assert.equal(actual.length,count);for(let i=0;i<count;i++){assert.equal(actual[i].id,`call-${i}`);assert.equal(actual[i].status,'failed');assert.equal(actual[i].error,'observed refusal-'+i);assert.equal(actual[i].input,text.slice(0,24000));}});
  await run('proofs-e.chat.trace',category,()=>{const input={reasoningSummary:text,toolCalls:count?[tool(text)]:[]};const actual=stream.neyviaChatTraceFields(input);assert.equal(actual.reasoningSummary,text);assert.equal(actual.toolCalls.length,count?1:0);if(count){assert.equal(actual.toolCalls[0].output,text.slice(0,24000));assert(actual.activitySegments.some(s=>s.kind==='reasoning_summary'&&s.text===text));}});
  await run('proofs-e.chat.streamTransition',category,()=>{const state=stream.createNeyviaChatStreamState();const start={kind:'runtime.answer_start',data:{responseId:'new',itemId:'answer',outputIndex:0}};stream.applyNeyviaChatStreamEvents(state,[start,{kind:'runtime.answer_delta',message:text},start,{kind:'runtime.answer_delta',message:text},{kind:'runtime.tool',data:{callId:'one',tool:'workspace_read',input:text,toolStatus:'started'}},{kind:'runtime.tool',data:{callId:'one',tool:'workspace_read',output:'actual-output',toolStatus:'completed'}}]);assert.equal(state.answer,text+text);assert.equal(state.toolCalls.length,1);assert.equal(state.toolCalls[0].input,text.slice(0,24000));assert.equal(state.toolCalls[0].output,'actual-output');});
  await run('proofs-e.chat.phase',category,()=>{assert.equal(visual.inferNeyviaToolPhase({status:'failed',tone:'good',pending:true,detail:text}),'error');assert.equal(visual.inferNeyviaToolPhase({status:'cancelled',tone:'good',detail:text}),'idle');assert.equal(visual.inferNeyviaToolPhase({status:text}),'idle');});
  await run('proofs-e.chat.chip',category,()=>{const actual=visual.resolveNeyviaMessageChip({label:text,status:'failed',tone:'good'});assert.equal(actual.phase,'error');});
  await run('proofs-e.chat.activity',category,()=>{const input={kind:'app_call',name:'mcp__notes__open_document',input:{file:text},output:text,status:'completed'};const actual=activity.presentRunActivity(input,7);assert.equal(actual.category,'App');assert.equal(actual.title,'Notes · open document');assert.equal(JSON.parse(actual.input).file,text);assert.equal(actual.phase,'success');assert.notEqual(actual.key,activity.presentRunActivity(input,8).key);});
  await run('proofs-e.chat.visibleActivity',category,()=>{const actual=activity.visibleRunActivityEvents([{kind:'runtime.answer_delta',message:text},{kind:'runtime.progress',message:text},{kind:'runtime.tool',itemId:'one',tool:'commandExecution',command:text,status:'started'},{kind:'runtime.tool',itemId:'one',tool:'commandExecution',output:text,status:'completed'}]);assert.equal(actual.length,1);assert.equal(actual[0].command??'',text);assert.equal(actual[0].output??'',text);});
  await run('proofs-e.chat.presentation',category,()=>{const input={tool:'terminal.exec',status:'failed',input:JSON.stringify({command:text,shell:'powershell',cwd:'D:/owned/chat-shell'}),error:JSON.stringify({ok:false,failure:{message:'Recorded refusal'},toolResult:{exitCode:4294967295,stderr:text}})};const actual=presentation.presentToolCall(input);assert.equal(actual.kind,category==='empty'?'generic':'command');assert.equal(actual.failed,true);assert.equal(actual.error,'Recorded refusal');if(category!=='empty')assert.equal(actual.command.exitCode,4294967295);else assert.equal(actual.command,undefined);});
  await run('proofs-e.chat.commandSummary',category,()=>{const command={exitCode:4294967295,stdout:category==='empty'?'':text+'\n'+text,stderr:''};assert.equal(presentation.commandOutputSummary(command),`exit -1 · ${category==='empty'?'no output':'2 lines of output'}`);});
  await run('proofs-e.chat.stringField',category,()=>{assert.deepEqual(presentation.readJsonStringField(JSON.stringify({path:text}),'path'),{value:text,complete:true});assert.deepEqual(presentation.readJsonStringField('{"path":"before\\u12','path'),{value:'before',complete:false});});
  await run('proofs-e.chat.utf16',category,()=>{assert.equal(presentation.repairUtf16Text(text),text);assert.equal(presentation.repairUtf16Text('N\0A\0M\0E\0'),'NAME');});
  await run('proofs-e.chat.diff',category,()=>{const count=category==='empty'?0:category==='huge'?600:3;const diff=count?'--- a/x\n+++ b/x\n@@ -7,1 +7,'+(count+1)+' @@\n old\n'+Array.from({length:count},(_,i)=>'+'+text.slice(0,30)+i).join('\n'):'';const actual=presentation.parseUnifiedDiff(diff);assert.equal(actual.added,count);assert.equal(actual.removed,0);assert.deepEqual(actual.lines.filter(l=>l.type==='add').map(l=>l.number),Array.from({length:count},(_,i)=>8+i));});
  await run('proofs-e.chat.family',category,()=>{assert.equal(presentation.toolFamily(text),'generic');assert.equal(presentation.toolFamily('mcp.neyvia.workspace_read'),'read');assert.equal(presentation.toolFamily('command_execution'),'command');});
  const turn={id:'turn',role:'assistant',pending:true,title:text,source:'runtime-stream',toolCalls:[{id:'running',status:'running'},{id:'done',status:'completed'}],createdAt:'2026-10-04T00:00:00Z'};
  await run('recovery.interrupted',category,()=>{const actual=recovery.interruptedChatTurnPatch(turn,'Recorded stop');assert.equal(actual.pending,false);assert.equal(actual.source,'chat-interrupted');assert.equal(actual.toolCalls[0].status,'interrupted');assert.equal(actual.toolCalls[1].status,'completed');assert.equal(actual.title,text.trim()?text:'This response was interrupted before a reply arrived.');assert.equal(turn.toolCalls[0].status,'running');});
  await run('recovery.decision',category,()=>{const now=Date.parse('2026-10-04T01:00:00Z');const actual=recovery.chatRecoveryDecision({status:'interrupted',message:text},turn,{now});assert.equal(actual.action,'settle');assert.equal(actual.patch.pending,false);assert.equal(actual.patch.source,'chat-interrupted');assert.equal(recovery.chatRecoveryDecision({status:'running'},turn,{now}).action,'watch');});
  await run('recovery.recorded',category,()=>{const actual=recovery.recordedResultChatTurnPatch(turn,{reply:text,status:'completed',runtime:'manual-observed'});assert.equal(actual.pending,false);assert.equal(actual.title,text.trim()||'The runtime finished without a readable reply.');assert.equal(actual.runtimeId,'manual-observed');});
  await run('recovery.unowned',category,()=>{const turns=Array.from({length:count},(_,i)=>({...turn,id:'turn-'+i,createdAt:new Date(1700000000000+i*1000).toISOString()}));const actual=recovery.unownedPendingChatTurns({[text||'empty']:turns},new Set(['turn-0']),12);assert.equal(actual.length,Math.min(12,Math.max(0,count-1)));if(actual.length)assert.equal(actual[0].turn.id,'turn-'+(count-1));});
  await run('recovery.quiet',category,()=>{assert.equal(recovery.quietResponseLabel(text,1700000000000),'');assert.equal(recovery.quietResponseLabel(1700000000000,1700000120000),'No new output for 2 min');});
  await run('recovery.merge',category,()=>{const original={...turn,title:'old',pending:true};const actual=recovery.mergeStreamedTrace(original,{answer:text,reasoningSummary:text,toolCalls:[tool(text)]});assert.equal(actual.title,text.trim()&&text.length>=3?text:'old');assert.equal(actual.toolCalls[0].output,text.slice(0,24000));assert.equal(original.title,'old');});
  await run('activity.href',category,()=>{assert.equal(activity.safeReceiptHref(text),'');assert.equal(activity.safeReceiptHref('/api/artifact?path='+encodeURIComponent(text)),'/api/artifact?path='+encodeURIComponent(text));assert.equal(activity.safeReceiptHref('javascript:'+text),'');});
  await run('activity.duration',category,()=>{assert.equal(activity.runDurationLabel(text),'Not recorded');assert.equal(activity.runDurationLabel(999),'999ms');assert.equal(activity.runDurationLabel(61000),'1m 1s');});
  await run('chat.stopped-visibility',category,()=>{const actual={...turn,pending:false,source:'chat-interrupted',title:text||'Stopped before reply'};assert.equal(visibility.describeHiddenTurn(actual),null);});
  await run('chat.stopped-body',category,()=>{assert.equal(visibility.dialogueBody({...turn,pending:false,source:'chat-interrupted',detail:'Receipt fallback'}),text||'Receipt fallback');});
  const session={id:'one',title:text,cwd:'D:/owned/'+(category==='unicode'?'雪-project':'project'),project_known:true,status:'idle',sidebar:{kind:category==='empty'?'other':'images'},updated_at:'2026-08-01T00:00:00Z',cleanup_safety:{status:'observed'}};
  await run('proofs-e.shell.kindOf',category,()=>{assert.equal(sidebar.kindOf({...session,sidebar:{kind:text}}),'other');assert.equal(sidebar.kindOf(session),category==='empty'?'other':'images');});
  await run('proofs-e.shell.placeSession',category,()=>{assert.equal(sidebar.placeSession(session).group,'project');assert.equal(sidebar.placeSession({...session,cwd:'D:/owned/.agent_control/scratch/'+text}).group,'nofolder');assert.equal(sidebar.placeSession({...session,projectOverride:null}).group,'nofolder');});
  await run('proofs-e.shell.agentSummary',category,()=>{const agents=Array.from({length:count},(_,i)=>({id:text+i,status:'running',children:[{id:'child-'+i,status:'failed'}]}));assert.deepEqual(sidebar.agentSummary(agents),{total:count*2,running:count,failed:count});});
  await run('proofs-e.shell.buildTree',category,()=>{const sessions=Array.from({length:count},(_,i)=>({...session,id:'chat-'+i,title:text+i,pinned:i%2===0,project_known:false}));const tree=sidebar.buildTree(sessions,{projects:[{name:'empty-project-'+text.slice(0,30),path:'D:/owned/empty'}],now:Date.parse('2026-10-04T00:00:00Z')});assert.equal(tree.total,count);assert.equal(tree.pinned.length,Math.ceil(count/2));assert.equal(tree.noFolderCount,Math.floor(count/2));assert.equal(tree.projects.length,1);});
  await run('proofs-e.shell.staleCandidates',category,()=>{const sessions=Array.from({length:count},(_,i)=>({...session,id:'chat-'+i,title:text,pinned:i%2===0}));const actual=sidebar.staleCandidates(sessions,undefined,Date.parse('2026-10-04T00:00:00Z'));assert.deepEqual(actual.map(s=>s.id),sessions.filter(s=>!s.pinned).map(s=>s.id));assert.equal(sidebar.staleCandidates([{...session,has_uncommitted:true}],undefined,Date.parse('2026-10-04T00:00:00Z')).length,0);});
  await run('proofs-e.shell.shouldOfferTidy',category,()=>{const total=category==='empty'?0:category==='huge'?100000:31,stale=category==='empty'?0:1;assert.equal(sidebar.shouldOfferTidy(total,stale),category!=='empty');});
  await run('proofs-e.shell.initial',category,()=>{const bubbles=Array.from({length:count},(_,i)=>({id:text+i,x:99,y:-2}));const actual=os.initialOsState({theme:text,bubbles});assert.equal(actual.theme,'dark');assert.equal(actual.bubbles.length,Math.min(6,count));assert(actual.bubbles.every(b=>b.x===1&&b.y===0));assert.equal(actual.stage,null);});
  await run('proofs-e.shell.overrides',category,()=>{const original={...session};const actual=os.withOverrides(original,{one:{title:text,pinned:true,archived:false,project:'subject:hidden-id'}},{'subject:hidden-id':{name:'Named subject-'+text.slice(0,50),path:null,subject:true}});assert.equal(actual.pinned,true);assert.equal(actual.projectOverride.name,'Named subject-'+text.slice(0,50));assert(!actual.projectOverride.name.includes('hidden-id'));assert.equal(original.pinned,undefined);});
  await run('proofs-e.shell.reducer',category,()=>{let state=os.initialOsState();const before=structuredClone(state);state=os.reduceUiAction(state,'session.pinned',{id:'one',pinned:true});state=os.reduceUiAction(state,'session.moved',{id:'one',project:text||null});state=os.reduceUiAction(state,'session.moved',{id:'one',clearOverride:true});assert.equal(state.overrides.one.pinned,true);assert(!('project'in state.overrides.one));assert.deepEqual(before.overrides,{});state=os.reduceUiAction(state,'pdf.open',{source:'D:/owned/'+encodeURIComponent(text||'empty')+'.pdf',page:1});state=os.reduceUiAction(state,'pdf.search',{query:text});assert.deepEqual(state.inbox.map(e=>e.action),['pdf.open','pdf.search']);assert.equal(state.inbox[1].payload.query,text);});
  await run('proofs-e.shell.parseNewChat',category,()=>{const phrase=category==='empty'?'':`new claude code chat in ${text}`;assert.deepEqual(launcher.parseNewChat(phrase),category==='empty'?null:{app:'claude-code',project:text.trim()});});
  await run('proofs-e.shell.searchLauncher',category,()=>{const query=category==='empty'?'':'match';const projects=Array.from({length:count},(_,i)=>({name:'match-'+i+'-'+text.slice(0,20),path:'D:/owned/p-'+i}));const actual=launcher.searchLauncher(query,{projects},Math.max(1,count));assert.equal(actual.filter(r=>r.group==='Projects').length,count);if(count){assert.equal(actual[0].rank,80);assert.equal(actual[0].payload.project.path,'D:/owned/p-0');}});
}
// Real file-backed loopback transport for the production polling lifecycle.
await mkdir(root,{recursive:true});
const ledgers={};for(const [category,text]of Object.entries(variants)){const path=join(root,category+'-snapshot.json');await writeFile(path,JSON.stringify({cursor:Buffer.byteLength(text)+31,events:[{kind:'runtime.answer_delta',message:text},{kind:'runtime.done'}]}));ledgers[category]=path;}
let firstOffline=true,lateArrived;
const server=http.createServer(async(req,res)=>{try{const url=new URL(req.url,origin);if(url.pathname==='/protected'&&req.headers['x-fixture-grant']!=='owned-grant'){res.writeHead(403,{'content-type':'application/json'});res.end(JSON.stringify({error:'The owned stream requires its explicit local grant.'}));return;}if(url.pathname==='/offline'&&firstOffline){firstOffline=false;req.socket.destroy();return;}if(url.pathname==='/late'){lateArrived?.();await new Promise(r=>setTimeout(r,120));}const body=await readFile(ledgers[url.searchParams.get('category')||'unicode']);res.writeHead(200,{'content-type':'application/json'});res.end(body);}catch(error){res.writeHead(500);res.end('owned fixture read failed');}});
const previousWindow=globalThis.window;globalThis.window=globalThis;
try{
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});
 const poll=(path,category)=>async(_id,_cursor,signal)=>{const response=await fetch(`${origin}/${path}?category=${category}`,{signal});assert.equal(response.status,200);return response.json();};
 for(const [category,text]of Object.entries(variants))await run('proofs-e.chat.pollDelivery',category,async()=>{const state=stream.createNeyviaChatStreamState(),loop=stream.startNeyviaChatStreamPoll({turnId:'owned-'+category,poll:poll('snapshot',category),onEvents:e=>stream.applyNeyviaChatStreamEvents(state,e)});await loop.done;assert.equal(state.answer,text);});
 await run('proofs-e.chat.pollDelivery','offline',async()=>{const errors=[],state=stream.createNeyviaChatStreamState(),loop=stream.startNeyviaChatStreamPoll({turnId:'owned-offline',intervalMs:40,poll:poll('offline','unicode'),onError:e=>errors.push(e),onEvents:e=>stream.applyNeyviaChatStreamEvents(state,e)});await loop.done;assert(errors[0]);assert.equal(errors.at(-1),'');assert.equal(state.answer,variants.unicode);});
 await run('proofs-e.chat.pollDelivery','interrupted',async()=>{const arrived=new Promise(resolve=>{lateArrived=resolve;});const received=[],loop=stream.startNeyviaChatStreamPoll({turnId:'owned-stop',poll:poll('late','unicode'),onEvents:e=>received.push(...e)});await arrived;loop.stop();await loop.done;assert.equal(received.length,0);lateArrived=null;});
 await run('proofs-e.chat.pollDelivery','concurrency',async()=>{const answers=[];await Promise.all(['huge','unicode'].map(async category=>{const state=stream.createNeyviaChatStreamState(),loop=stream.startNeyviaChatStreamPoll({turnId:'owned-parallel-'+category,poll:poll('snapshot',category),onEvents:e=>stream.applyNeyviaChatStreamEvents(state,e)});await loop.done;assert.equal(state.answer,variants[category]);answers.push(category);}));assert.equal(answers.length,2);});
 await run('proofs-e.chat.pollDelivery','permissions',async()=>{const received=[],errors=[];let loop;loop=stream.startNeyviaChatStreamPoll({turnId:'owned-denied',poll:async(_id,_cursor,signal)=>{const response=await fetch(origin+'/protected',{signal});const body=await response.json();if(!response.ok)throw new Error('HTTP '+response.status+': '+body.error);return body;},onEvents:e=>received.push(...e),onError:error=>{errors.push(error);loop.stop();}});await loop.done;assert.equal(received.length,0);assert.equal(errors.length,1);assert.ok(errors[0].includes('HTTP 403'));assert.ok(errors[0].includes('explicit local grant'));});
}finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));if(previousWindow===undefined)delete globalThis.window;else globalThis.window=previousWindow;}
console.log(JSON.stringify(rows));
'''


def _python_cases(root, contracts, categories):
    from .chat_stream import begin_chat_stream, append_chat_stream, read_chat_stream, safe_tool_display
    rows = []
    def run(identity, category, action):
        if identity not in contracts or category not in categories:
            return
        start = time.perf_counter()
        row = {"id": f"chat-shell.{identity}.{category}", "category": category, "contracts": [identity],
               "boundary": "real production byte stream or safe activity projection over synthetic public fixture data; no provider/home discovery"}
        try:
            action(); row.update(status="passed", detail="Independent durable byte cursor/text or redaction/nonmutation observations agreed")
        except Exception as error:
            row.update(status="failed", detail=f"{type(error).__name__}: {error}")
        row["durationMs"] = round((time.perf_counter() - start) * 1000, 3); rows.append(row)
    def display(text):
        data = {"apiKey": "synthetic-secret-sentinel", "media": "data:image/png;base64,AAAA", "ordinary": text}
        before = json.dumps(data, ensure_ascii=True)
        actual = safe_tool_display(data)
        assert "synthetic-secret-sentinel" not in actual and "AAAA" not in actual and "[REDACTED]" in actual
        assert json.dumps(data, ensure_ascii=True) == before
        if len(text) < 1000:
            assert json.loads(actual)["ordinary"] == text
    def ledger(category, text):
        area = root / ("ledger-" + category); area.mkdir(exist_ok=True)
        assert begin_chat_stream(area, "owned-turn")
        append_chat_stream(area, "owned-turn", {"kind": "runtime.answer_delta", "message": text})
        path = area / ".agent_control/chat_streams/owned-turn.jsonl"
        all_rows, cursor = [], 0
        while cursor < path.stat().st_size:
            snapshot = read_chat_stream(area, "owned-turn", cursor)
            assert snapshot["cursor"] > cursor
            cursor = snapshot["cursor"]; all_rows.extend(snapshot["events"])
        assert "".join(row["message"] for row in all_rows) == text and cursor == len(path.read_bytes())
        before = path.read_bytes()
        with path.open("ab") as handle:
            handle.write(b'{"kind":"runtime.answer_delta","message":"incomplete')
        pending = read_chat_stream(area, "owned-turn", cursor)
        assert pending["events"] == [] and pending["cursor"] == cursor and path.read_bytes().startswith(before)
    def stale():
        area = root / "ledger-stale"; area.mkdir(exist_ok=True)
        begin_chat_stream(area, "owned-turn")
        append_chat_stream(area, "owned-turn", {"kind": "runtime.answer_delta", "message": "old" * 5000})
        path = area / ".agent_control/chat_streams/owned-turn.jsonl"
        old_cursor = path.stat().st_size
        begin_chat_stream(area, "owned-turn")
        append_chat_stream(area, "owned-turn", {"kind": "runtime.answer_delta", "message": "new-雪"})
        assert old_cursor > path.stat().st_size
        current = read_chat_stream(area, "owned-turn", old_cursor)
        assert current["cursor"] == path.stat().st_size and "".join(row["message"] for row in current["events"]) == "new-雪"
    def concurrent():
        area = root / "ledger-concurrent"; area.mkdir(exist_ok=True)
        begin_chat_stream(area, "owned-turn")
        barrier = threading.Barrier(8)
        messages = [f"writer-{index}-雪🙂" * 3000 for index in range(8)]
        def append(index):
            barrier.wait(timeout=10)
            append_chat_stream(area, "owned-turn", {"kind": "runtime.answer_delta", "message": messages[index], "data": {"writer": index}})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(append, range(8)))
        path = area / ".agent_control/chat_streams/owned-turn.jsonl"
        raw_rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        assert len(raw_rows) == sum((len(message) + 3999) // 4000 for message in messages), "concurrent append changed complete frame count"
        cursor, output = 0, {index: [] for index in range(8)}
        while cursor < path.stat().st_size:
            snapshot = read_chat_stream(area, "owned-turn", cursor)
            assert snapshot["cursor"] > cursor
            cursor = snapshot["cursor"]
            for row in snapshot["events"]:
                output[row["data"]["writer"]].append(row["message"])
        assert all("".join(output[index]) == message for index, message in enumerate(messages)), "concurrent real append lost/tore complete writer messages"
    def permissions():
        from .edge_fixture_native import _sharing_denied
        area = root / "ledger-permissions"; area.mkdir(exist_ok=True)
        begin_chat_stream(area, "owned-turn")
        append_chat_stream(area, "owned-turn", {"kind": "runtime.answer_delta", "message": "keeper-雪"})
        path = area / ".agent_control/chat_streams/owned-turn.jsonl"; before = path.read_bytes()
        with _sharing_denied(path):
            try:
                read_chat_stream(area, "owned-turn")
            except OSError:
                pass
            else:
                raise AssertionError("native sharing-denied stream read succeeded")
        assert path.read_bytes() == before
    def interrupted():
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        area = root / "ledger-interrupted"; area.mkdir(exist_ok=True)
        ready = area / "owned-ready.json"
        code = "\n".join([
            "import json,sys,time,os",
            "from pathlib import Path",
            "from grant_agent.chat_stream import begin_chat_stream,append_chat_stream",
            "root=Path(sys.argv[1]);begin_chat_stream(root,'owned-turn')",
            "append_chat_stream(root,'owned-turn',{'kind':'runtime.answer_delta','message':'arrived-雪'})",
            "path=root/'.agent_control/chat_streams/owned-turn.jsonl'",
            "with path.open('ab',buffering=0) as stream:",
            " stream.write(b'{\"kind\":\"runtime.answer_delta\",\"message\":\"unfinished')",
            " Path(sys.argv[2]).write_text(json.dumps({'pid':os.getpid()}),encoding='utf-8')",
            " time.sleep(60)",
        ])
        child = subprocess.Popen([sys.executable, "-c", code, str(area), str(ready)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 **hidden_windows_subprocess_kwargs())
        try:
            deadline = time.monotonic() + 15
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            assert ready.exists(), "owned stream writer did not reach partial-record boundary"
            assert json.loads(ready.read_text(encoding="utf-8"))["pid"] == child.pid
            child.kill(); child.wait(timeout=10)
            snapshot = read_chat_stream(area, "owned-turn")
            assert [row["message"] for row in snapshot["events"]] == ["arrived-雪"]
            assert snapshot["cursor"] < (area / ".agent_control/chat_streams/owned-turn.jsonl").stat().st_size
            assert read_chat_stream(area, "owned-turn", snapshot["cursor"])["events"] == []
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=10)
            child.stderr.close()
    for category, text in TEXTS.items():
        run("proofs-e.chat.safe-display", category, lambda text=text: display(text))
        run("proofs-e.chat.desktop-stream", category, lambda category=category, text=text: ledger(category, text))
    for category, action in (("stale", stale), ("concurrency", concurrent), ("permissions", permissions), ("interrupted", interrupted)):
        run("proofs-e.chat.desktop-stream", category, action)
    return rows


def run(root, contracts, categories):
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    repository = Path(__file__).resolve().parents[2]
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    from .proof_ports import c7_port_block
    assigned = c7_port_block(int(os.environ['NEYVIA_C7_PORT']))
    port = int(os.environ.get("NEYVIA_C7_CHAT_PORT", str(assigned[-1])))
    if port not in assigned:
        raise ValueError("Assigned explicit chat fixture port required")
    child = subprocess.run(["node", "--input-type=module", "-", str(root / "http-ledgers"), str(port)], input=NODE,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=repository,
                           timeout=90, **hidden_windows_subprocess_kwargs())
    if child.returncode:
        raise RuntimeError("Production Node chat/shell campaign failed to return: " + child.stderr[-2000:])
    rows = [row for row in json.loads(child.stdout) if row["contracts"][0] in contracts and row["category"] in categories]
    rows.extend(_python_cases(root, contracts, categories))
    return rows
