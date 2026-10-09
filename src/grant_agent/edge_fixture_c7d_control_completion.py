"""Exact remaining control/runtime observations in guarded disposable state.

Metadata, durable effects, and real owned children are separate boundaries.
Nothing here is rendered, provider-authenticated, public or physical-device proof.
"""
from __future__ import annotations
import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from .edge_fixture_c7d_desktop import _stop_at_marker,_interrupted_write
from .edge_fixture_host_runtime import _check,_reject,_sharing,_environment

REPO=Path(__file__).resolve().parents[2]
TEXT={"empty":"","huge":"owned explicit content "*12000,"unicode":"雪🙂 café e\u0301 العربية"}
CATEGORIES=set(TEXT)|{"concurrency","interrupted","permissions","offline","stale"}


def _bridge(root,category,identity):
    from . import connected_device_bridge as b
    from .models import WorkspaceProfile
    text=TEXT.get(category,"Owned policy evidence")
    local=root/"local";remote=root/"remote-label-only";local.mkdir();remote.mkdir()
    workspace=WorkspaceProfile(workspace_id="owned",name=text,root_path=str(local),default_runtime="hermes",workspace_type="python",local_project_path=str(local),nas_project_path=str(remote),sync_mode="manual",sync_direction="bidirectional")
    presence={"local":{"gh":False,"git":False},"nas":{"gh":False,"git":False}}
    def snapshot():return b.build_dual_path_bridge_snapshot(root,workspaces=[workspace],provider_auth_presence={"github":False},command_presence=presence)
    grants={"local":[b.PermissionGrant("file.read","approved",str(local),text,"owned fixture")]}
    if identity=="control.bridge-grants":
        path=b.save_bridge_permission_grants(root,grants)
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:paths=list(pool.map(lambda i:b.save_bridge_permission_grants(root,{"local":[b.PermissionGrant("file.read","approved",str(local),f"writer-{i}","owned fixture")]}),range(8)))
            _check(len(paths)==8 and len(b.load_bridge_permission_grants(root)["local"])==1,"competing complete grant writes tore current list")
        elif category=="permissions":
            before=path.read_bytes()
            with _sharing(path):_reject(lambda:b.save_bridge_permission_grants(root,{}),(OSError,))
            _check(path.read_bytes()==before,"denied grant save replaced keeper")
        elif category=="interrupted":
            code="\n".join(["import sys,json,threading","from pathlib import Path","from grant_agent.connected_device_bridge import save_bridge_permission_grants,PermissionGrant","r=Path(sys.argv[1]);marker=Path(sys.argv[2])","p=save_bridge_permission_grants(r,{'local':[PermissionGrant('file.read','denied',str(r/'local'),'actual stopped grant','owned fixture')]})","marker.write_text(json.dumps({'path':str(p)}));threading.Event().wait(60)"])
            _stop_at_marker(root,"bridge-grants",code)
            _check(b.load_bridge_permission_grants(root)["local"][0].state=="denied","killed grant writer borrowed old authority")
        elif category=="stale":
            b.save_bridge_permission_grants(root,{"local":[b.PermissionGrant("file.read","denied",str(local),"revoked","owned fixture")]})
            _check(b.load_bridge_permission_grants(root)["local"][0].state=="denied","grant observer reused old approval")
        return {"actualGrantFile":str(path),"syncPerformed":False}
    if identity=="control.bridge-snapshot":
        b.save_bridge_permission_grants(root,grants);before=snapshot()
        path=root/b.PERMISSIONS_RELATIVE_PATH
        if category=="permissions":
            b.save_bridge_permission_grants(root,{"local":[b.PermissionGrant("file.read","denied",str(local))]})
            with _sharing(path):_reject(snapshot,(RuntimeError,))
        elif category=="interrupted":
            _interrupted_write(path,'{"hosts":');_reject(snapshot,(RuntimeError,))
        elif category=="stale":
            b.save_bridge_permission_grants(root,{"local":[b.PermissionGrant("file.read","denied",str(local))]});current=snapshot()
            _check(any(r["capability"]=="file.read" for r in current["denials"]),"fresh revoked grant hidden in snapshot")
        elif category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:snapshot(),range(8)))
            def stable(value):
                if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in {"updatedAt","checkedAt","lastHealthAt"}}
                if isinstance(value,list):return [stable(v) for v in value]
                return value
            _check(all(stable(r["hosts"])==stable(before["hosts"]) for r in rows),"concurrent current host projections changed authority")
        return {"hostLabels":[r["hostId"] for r in before["hosts"]],"declaredMappingOnly":True,"syncPerformed":False}
    hosts=b.build_connected_host_manifests(root,workspaces=[workspace],provider_auth_presence={"github":False},command_presence=presence)
    request=b.BridgeActionRequest("owned","read_file","nas_to_local","nas","local",path=str(local/"selected.txt"),metadata={"selected":text})
    local_host=next(h for h in hosts if h.host_id=="local")
    local_host.file_roots=[b.FileRootScope("owned",str(local),"read","approved",text)]
    local_host.permissions=[b.PermissionGrant("file.read","approved",str(local))]
    if identity=="control.bridge-authority":
        first=b.evaluate_bridge_action(hosts,request)
        _check(first.status=="approved","explicit granted local read proposal refused")
        if category in {"permissions","stale"}:
            local_host.permissions=[b.PermissionGrant("file.read","denied",str(local))]
            _check(b.evaluate_bridge_action(hosts,request).status!="approved","revoked grant retained authority")
        elif category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:b.evaluate_bridge_action(hosts,request),range(16)))
            _check(all(r.status==first.status for r in rows),"parallel authority decisions disagree")
        return {"proposedOnly":True,"fileReadExecuted":False}
    path=root/b.RECEIPTS_RELATIVE_PATH
    def publish(index=0):
        if identity=="control.bridge-feedback":return b.build_live_review_structured_feedback_receipt(event_id=f"owned-{index}",route_context={"label":text},task_context={"objective":text},verifier_feedback={"summary":text},planner_executor_handoff_id="owned-handoff",next_idea=text,audit_root=root)
        denied=copy.deepcopy(request);denied.action_id="outside";denied.path=str(root/"outside.txt")
        return b.build_bridge_operation_receipt(hosts,[request,denied] if category!="empty" else [],operation_id=f"owned-{index}",audit_root=root,execute=False)
    first=publish()
    if category=="permissions":
        before=path.read_bytes()
        with _sharing(path):_reject(lambda:publish(1),(OSError,))
        _check(path.read_bytes()==before,"denied receipt append changed keeper")
    elif category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(publish,range(1,9)))
        durable=b.load_bridge_receipts(root,limit=20)
        key="eventId" if identity=="control.bridge-feedback" else "operationId"
        _check({r[key] for r in rows}|{first[key]}=={r[key] for r in durable},"concurrent bridge receipts lost an actual result")
    elif category=="stale":
        local_host.permissions=[b.PermissionGrant("file.read","denied",str(local))]
        fresh=publish(1)
        if identity=="control.bridge-receipt":_check(fresh["status"]=="denied","new operation hid revoked grant")
        else:_check(fresh["eventId"]!=first["eventId"] and b.load_bridge_receipts(root)[-1]==fresh,"feedback reused old event identity")
    return {"actualReceiptRows":len(b.load_bridge_receipts(root)),"metadataOnly":True,"renderedFeedbackProof":False,"syncPerformed":False}


def _console(root,category,identity):
    from . import thunder_compute as owner
    text=TEXT.get(category,"Owned pointer metadata")
    if identity=="control.console-observation":
        for value,expected in ((text,(None,"none")),("Sign in to your account",(False,"high")),("Instances Dashboard Billing",(True,"high"))):
            observed=owner._assess_authentication(value)
            _check(observed[:2]==expected,"console text invented authenticated state")
        instances=owner._extract_instances("Owned instance\nRunning\n"+text)
        return {"suppliedTextOnly":True,"instanceRows":len(instances),"accountAccessed":False}
    first=owner.save_project_memory(root,{"purpose":text,"latestCheckpoint":"keeper","password":"generated-rejected"});path=owner.project_memory_path(root)
    if category=="permissions":
        before=path.read_bytes()
        with _sharing(path):_reject(lambda:owner.save_project_memory(root,{"latestCheckpoint":"denied"}),(OSError,))
        _check(path.read_bytes()==before,"denied memory write lost keeper")
    elif category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda i:owner.save_project_memory(root,{"latestCheckpoint":f"writer-{i}"}),range(8)))
        _check(owner.load_project_memory(root)["latestCheckpoint"] in {r["latestCheckpoint"] for r in rows},"concurrent pointer memory returned absent final state")
    elif category=="interrupted":
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.thunder_compute import save_project_memory","r=Path(sys.argv[1]);marker=Path(sys.argv[2])","result=save_project_memory(r,{'latestCheckpoint':'actual stopped checkpoint'})","marker.write_text(json.dumps(result));threading.Event().wait(60)"])
        _stop_at_marker(root,"console-memory",code);_check(owner.load_project_memory(root)["latestCheckpoint"]=="actual stopped checkpoint","stopped memory writer lost checkpoint")
    elif category=="stale":
        owner.save_project_memory(root,{"latestCheckpoint":"fresh checkpoint"});_check(owner.load_project_memory(root)["latestCheckpoint"]=="fresh checkpoint" and first["latestCheckpoint"]=="keeper","memory replacement borrowed old result")
    _check("password" not in json.loads(path.read_text(encoding="utf8")),"memory persisted rejected secret field")
    return {"actualPointerMemory":True,"publicUnknownFieldsDropped":True}


def _context(root,category,identity):
    text=TEXT.get(category,"Owned selected context")
    if identity=="control.context-bundle":
        import sqlite3
        from .context_engine import DurableContextEngine
        owner=DurableContextEngine(root,"owned",max_context_tokens=4000)
        owner.append("system","Explicit policy",kind="contract",pinned=True,importance=1.)
        owner.append("user",text,kind="message")
        first=owner.bundle(text)
        if category=="permissions":
            with _sharing(owner.db_path):_reject(lambda:owner.bundle(text),(sqlite3.Error,OSError))
        elif category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:owner.bundle(text),range(8)))
            _check(all(r["stable_prefix_cache_key"]==first["stable_prefix_cache_key"] for r in rows),"parallel bundle readers changed stable policy identity")
        elif category=="stale":
            owner.append("system","Fresh explicit task boundary",kind="contract",pinned=True,importance=1.)
            second=owner.bundle(text);_check(second["stable_prefix_cache_key"]!=first["stable_prefix_cache_key"],"fresh task contract reused old policy cache")
        elif category=="interrupted":
            code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.context_engine import DurableContextEngine","r=Path(sys.argv[1]);marker=Path(sys.argv[2]);owner=DurableContextEngine(r,'owned',max_context_tokens=4000)","owner.append('user','Actual stopped context evidence',kind='message')","result=owner.bundle('Actual stopped context evidence');marker.write_text(json.dumps({'cache_key':result['cache_key']}));threading.Event().wait(60)"])
            _stop_at_marker(root,"context-bundle",code);current=DurableContextEngine(root,"owned",max_context_tokens=4000).bundle("Actual stopped context evidence")
            _check(any("Actual stopped" in str(r) for r in current["items"]),"stopped local context producer lost selected evidence")
        return {"bundleItems":len(first["items"]),"actualLedger":str(owner.db_path),"modelCalled":False}
    from .context_microkernel import ContextTurnMetrics
    def metrics(index=0):
        item=ContextTurnMetrics(mission_id="owned",session_id="owned")
        item.record_model_invocation(role=text,uncached_input_tokens=index+10,cached_input_tokens=2,metadata={"selected":text})
        item.record_tool_round_trip(tool_name="selected.local",output_text=text)
        return item,item.write_receipt(root)
    item,path=metrics()
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(metrics,range(8)))
        _check(all(json.loads(p.read_text(encoding="utf8"))["uncached_input_tokens"]==m.uncached_input_tokens for m,p in rows),"competing metrics lost independently completed receipt")
    elif category=="permissions":
        before=path.read_bytes()
        from .edge_fixture_c7d_local import _deny_child_creation
        with _deny_child_creation(path.parent,root):_reject(lambda:metrics(1),(OSError,))
        _check(path.read_bytes()==before,"denied metric publication replaced keeper")
    elif category=="interrupted":
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.context_microkernel import ContextTurnMetrics","r=Path(sys.argv[1]);marker=Path(sys.argv[2]);owner=ContextTurnMetrics(mission_id='stopped',session_id='owned');owner.record_model_invocation(uncached_input_tokens=17)","p=owner.write_receipt(r);marker.write_text(json.dumps({'path':str(p)}));threading.Event().wait(60)"])
        stopped=_stop_at_marker(root,"context-metrics",code);_check(json.loads(Path(stopped["observed"]["path"]).read_text(encoding="utf8"))["uncached_input_tokens"]==17,"stopped metric writer lost measured counters")
    elif category=="stale":
        _,later=metrics(9);_check(json.loads(later.read_text(encoding="utf8"))["uncached_input_tokens"]==19,"fresh metrics reused prior counters")
    return {"metricsReceipt":str(path),"declaredCountersOnly":True,"providerMeasurementClaimed":False}


def _result(root,category,identity):
    from .chat_run_control import record_chat_run_result
    text=TEXT.get(category,"Owned result")
    source={"reply":text,"status":"completed","conversationPersistence":{"conversationId":"owned-c","turnId":"owned-t"},"turnReceipt":{"usage":{"inputTokens":10,"outputTokens":2}},"compartment":{"state":"ready","messages":[{"text":text}],"turnReceipts":[{}]}}
    path=root/".agent_control/chat_runs/results/owned.json"
    def save(index=0):
        value={**source,"reply":text+str(index)};record_chat_run_result(root,"owned",value);return value
    first=save()
    if category=="permissions":
        before=path.read_bytes()
        with _sharing(path):_reject(lambda:save(1),(OSError,))
        _check(path.read_bytes()==before,"denied final result replaced keeper")
    elif category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(save,range(8)))
        _check(json.loads(path.read_text(encoding="utf8"))["reply"] in {r["reply"] for r in rows},"competing result writers lost current completed result")
    elif category=="stale":
        save(9);_check(json.loads(path.read_text(encoding="utf8"))["reply"]==text+"9","fresh result reused prior reply")
    elif category=="interrupted":
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.chat_run_control import record_chat_run_result","r=Path(sys.argv[1]);marker=Path(sys.argv[2])","record_chat_run_result(r,'owned',{'reply':'actual stopped result','status':'completed','turnReceipt':{'usage':{'inputTokens':11}}})","marker.write_text(json.dumps({'path':str(r/'.agent_control/chat_runs/results/owned.json')}));threading.Event().wait(60)"])
        _stop_at_marker(root,"chat-result",code);_check(json.loads(path.read_text(encoding="utf8"))["reply"]=="actual stopped result","stopped result producer lost durable selected reply")
    else:
        recorded=json.loads(path.read_text(encoding="utf8"));_check(recorded["compartment"]=={"state":"ready","windowRef":{"conversationId":"owned-c","turnId":"owned-t"}},"recorded result duplicated transcript window")
    return {"actualRetainedResult":True,"sessionWindowOmitted":True}


def _cu(root,category,identity):
    from . import cu_acceptance as owner
    # An explicitly empty discovery allowlist can never select an unrelated
    # listener or initialize the legacy browser acceptance runner.
    discovery=[]
    if identity=="control.cu-recovery":
        reason=owner.skip_reason_no_server(discovery)
        _check(reason,"explicit empty discovery allowlist lost recovery hint")
        return {"recoveryReason":reason,"renderedProof":False}
    if identity=="control.cu-receipt":
        text=TEXT.get(category,"Owned failed acceptance detail")
        def write(index=0):return owner.write_receipt("c7d-owned",{"pass":False,"status":"server_unavailable","reason":text,"writer":index,"tree":{"excluded":text},"nodes":[text],"accessibilityTree":text},root=root)
        path=write()
        if category=="permissions":
            latest=path.parent/"c7d-owned_latest.json";before=latest.read_bytes()
            with _sharing(latest):_reject(lambda:write(1),(OSError,))
            _check(latest.read_bytes()==before,"denied CU latest publication replaced keeper")
        elif category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:paths=list(pool.map(write,range(8)))
            _check(len(set(paths))==8 and all(json.loads(p.read_text(encoding="utf8"))["pass"] is False and json.loads(p.read_text(encoding="utf8"))["writer"]==i for i,p in enumerate(paths)),"concurrent unavailable acceptance lost an independent result or invented pass")
            _check((path.parent/"c7d-owned_latest.json").read_bytes() in [p.read_bytes() for p in paths],"latest CU receipt was not an actual completed publication")
        elif category=="interrupted":
            code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.cu_acceptance import write_receipt","r=Path(sys.argv[1]);marker=Path(sys.argv[2])","p=write_receipt('c7d-stopped',{'pass':False,'status':'server_unavailable'},root=r)","marker.write_text(json.dumps({'path':str(p)}));threading.Event().wait(60)"])
            stopped=_stop_at_marker(root,"cu-receipt",code);_check(json.loads(Path(stopped["observed"]["path"]).read_text(encoding="utf8"))["pass"] is False,"stopped CU receipt invented pass")
        elif category=="stale":
            later=write(9);_check(json.loads(later.read_text(encoding="utf8"))["writer"]==9,"fresh CU latest reused old failure")
        stored=json.loads(path.read_text(encoding="utf8"));_check(not set(stored)&{"tree","nodes","accessibilityTree"},"CU stored giant native tree")
        return {"failedReceipt":str(path),"renderedProof":False}
    if category in {"empty","huge","unicode"}:
        _reject(lambda:owner.run_flow(TEXT[category],root=root,discovery_urls=discovery),(ValueError,))
    if identity=="control.cu-aliases":
        canonical=next(iter(owner.CANONICAL_FLOWS));aliases=[k for k,v in owner.FLOW_ALIASES.items() if v==canonical]
        result=owner.run_flow(aliases[0],root=root,discovery_urls=discovery)
        _check(result["flow"]==canonical and result["pass"] is False and result["status"]=="server_unavailable","alias mismatch or unavailable flow invented pass")
    else:
        result=owner.run_suite(root=root,flows=[owner.CANONICAL_FLOWS[0]],discovery_urls=discovery)
        _check(result["pass"] is False and result["summary"]=={"passed":0,"failed":1,"total":1},"unavailable standalone CU gate counted failure as pass/skip")
    return {"actualStandaloneFailureGate":True,"renderedProof":False,"status":result["status"]}


def _prompt_denied(root,category,identity):
    from . import agent_prompt_library as owner
    owner.save_prompt_library(root,{"expectedRevision":0,"roles":{"reader":{"instructions":"Keeper"}}})
    path=owner._library_path(root);before=path.read_bytes()
    with _sharing(path):
        if identity=="control.prompts-composition":_reject(lambda:owner.load_prompt_library(root),(ValueError,OSError))
        else:_reject(lambda:owner.save_prompt_library(root,{"expectedRevision":1,"roles":{"reader":{"instructions":"Denied"}}}),(ValueError,OSError))
    _check(path.read_bytes()==before,"denied authored prompt changed durable instructions")
    return {"actualSharingDenied":True,"keeperPreserved":True}


def _limits(root,category,identity):
    from .connected_sessions import plan_limits as owner
    text=TEXT.get(category,"owned")
    def save(index=0):
        owner.record_claude({"rateLimitType":f"owned-{index}","utilization":.28,"status":text,"resetsAt":1791000000},root)
    save();path=root/".neyvia/plan-limits.json"
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(save,range(1,9)))
        _check(set(json.loads(path.read_text(encoding="utf8")))=={f"owned-{i}" for i in range(9)},"reported plan windows lost concurrent writes")
    elif category=="permissions":
        before=path.read_bytes()
        with _sharing(path):save(1)
        _check(path.read_bytes()==before,"denied plan-limit publication replaced actual window")
    elif category=="stale":
        owner.record_claude({"rateLimitType":"owned-0","utilization":.82,"status":"current"},root)
        _check(next(v for v in owner.claude_limits(root) if v["window"]=="owned-0")["usedPercent"]==82.,"current reported limit reused old percentage")
    elif category=="interrupted":
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.connected_sessions.plan_limits import record_claude","r=Path(sys.argv[1]);m=Path(sys.argv[2]);record_claude({'rateLimitType':'stopped','utilization':.17},r)","m.write_text(json.dumps({'window':'stopped'}));threading.Event().wait(60)"])
        _stop_at_marker(root,"plan-limit",code);_check(json.loads(path.read_text(encoding="utf8"))["stopped"]["usedPercent"]==17.,"stopped reporter lost actual window")
    else:_check(json.loads(path.read_text(encoding="utf8"))["owned-0"]["status"]==(text or None),"reported status changed accepted text")
    return {"reportedWindows":len(json.loads(path.read_text(encoding="utf8"))),"providerQueried":False}


def _plan_history(root,category,identity):
    from .connected_sessions.claude_transcript import ItemStore
    from .connected_sessions.plan import _text
    def call(key,name,args):return {"type":"assistant","timestamp":key,"message":{"content":[{"type":"tool_use","id":key,"name":name,"input":args}]}}
    def result(key):return {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":key,"content":"ok"}]},"toolUseResult":{"task":{"id":"41"}}}
    path=root/"owned-transcript.jsonl";text=TEXT.get(category,"Owned selected task")
    rows=[call("create","TaskCreate",{"subject":text}),result("create")]
    path.write_text("".join(json.dumps(v)+"\n" for v in rows),encoding="utf8")
    def read():
        store=ItemStore(path,"owned");store.refresh();return store.plan()
    first=read()
    if category=="empty":
        _check(first is None,"empty task title invented an accepted task")
        return {"actualEmptyTranscriptRefused":True}
    _check(first["items"][0]["text"]==_text(text),"history lost accepted bounded task title")
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:observed=list(pool.map(lambda _:read(),range(8)))
        _check(all(v==first for v in observed),"independent transcript readers changed canonical history")
    elif category=="permissions":
        with _sharing(path):_reject(read,(OSError,))
    elif category in {"stale","interrupted"}:
        extra=call("update","TaskUpdate",{"taskId":"41","status":"completed"})
        if category=="interrupted":
            code="\n".join(["import json,sys,threading,os","from pathlib import Path","p=Path(sys.argv[3]);m=Path(sys.argv[2])","with p.open('a',encoding='utf8') as f:f.write(sys.argv[4]);f.flush();os.fsync(f.fileno())","m.write_text(json.dumps({'appendCommitted':True}));threading.Event().wait(60)"])
            _stop_at_marker(root,"history-producer",code,str(path),json.dumps(extra)+"\n"+json.dumps(result("update"))+"\n")
        else:
            with path.open("a",encoding="utf8") as f:f.write(json.dumps(extra)+"\n"+json.dumps(result("update"))+"\n")
        _check(read()["items"][0]["status"]=="completed" and first["items"][0]["status"]=="pending","fresh/stopped history producer lost final transition")
    return {"actualTranscriptBytes":path.stat().st_size,"externalSessionRead":False}


def _stream(root,category,identity):
    from . import chat_stream as owner
    text=TEXT.get(category,"Owned accepted chunk")
    if identity=="control.stream-order":
        def run_order():
            seen=[];relay=owner.StreamCoalescer(seen.append,window=10)
            for message,item in ((text,"one"),("same","one"),("changed","two")):
                relay.push({"kind":"runtime.answer_delta","message":message,"data":{"itemId":item}})
            relay.flush();_check("".join(v["message"] for v in seen)==text+"samechanged" and seen[-1]["data"]["itemId"]=="two","coalescer changed accepted ordered prefix/item")
            return seen
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:run_order(),range(8)))
        else:run_order()
        return {"independentCoalescers":8 if category=="concurrency" else 1}
    owner.begin_chat_stream(root,"owned");path=owner._path(root,"owned")
    event={"kind":"runtime.answer_delta","message":text,"at":1790793676.1304,"data":{"eventType":"selected","writer":0}}
    owner.append_chat_stream(root,"owned",event)
    if category=="permissions":
        before=path.read_bytes()
        with _sharing(path):
            if identity=="control.stream-tail":_reject(lambda:owner.last_stream_event(root,"owned","selected"),(OSError,))
            else:_reject(lambda:owner.append_chat_stream(root,"owned",event),(OSError,))
        _check(path.read_bytes()==before,"denied stream write replaced keeper")
    elif category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda i:owner.append_chat_stream(root,"owned",{**event,"message":str(i),"data":{"eventType":"selected","writer":i+1}}),range(8)))
        _check({v["data"]["writer"] for v in [json.loads(s) for s in path.read_text(encoding="utf8").splitlines()]}==set(range(9)),"concurrent append lost an accepted frame")
    elif category=="interrupted":
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.chat_stream import append_chat_stream","r=Path(sys.argv[1]);m=Path(sys.argv[2]);append_chat_stream(r,'owned',{'message':'actual stopped chunk','data':{'eventType':'selected','writer':9}})","m.write_text(json.dumps({'appendCommitted':True}));threading.Event().wait(60)"])
        _stop_at_marker(root,"stream-writer",code);_check(owner.last_stream_event(root,"owned","selected")["data"]["writer"]==9,"stopped stream writer lost actual accepted chunk")
    elif category=="stale":
        owner.append_chat_stream(root,"owned",{**event,"message":"new","data":{"eventType":"selected","writer":9}})
        _check(owner.last_stream_event(root,"owned","selected",tail_bytes=31)["data"]["writer"]==9,"backward block scan reused prior event")
    else:
        rows=[json.loads(s) for s in path.read_text(encoding="utf8").splitlines()];_check("".join(v["message"] for v in rows)==text and all(len(v["message"])<=4000 and v["at"]==1790793676.13 for v in rows),"persisted frames changed accepted bytes/timestamp")
    return {"actualStreamBytes":path.stat().st_size}


def _relay(root,category,identity):
    from .web_backend import _communicate_runtime_events
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    text=TEXT.get(category,"Owned accepted runtime delta")
    script=root/"owned-emitter.py"
    # Completion depends on the parent observing the first delta. A buffered
    # relay cannot pass by delivering both lines after the child's exit.
    script.write_text("import json,time,sys\nfrom pathlib import Path\nvalue="+repr(text)+"\nprint('FLUXIO_EVENT:'+json.dumps({'kind':'runtime.answer_delta','message':value,'data':{'itemId':'owned'}}),flush=True)\nif len(sys.argv)>1:\n ack=Path(sys.argv[1]);deadline=time.monotonic()+8\n while not ack.exists():\n  if time.monotonic()>=deadline:raise RuntimeError('first delta was not acknowledged while child was alive')\n  time.sleep(.01)\nelse:\n time.sleep(60)\nprint('FLUXIO_EVENT:'+json.dumps({'kind':'runtime.tool','message':'end'}),flush=True)\n",encoding="utf8")
    def observe(index=0):
        ack=root/f"relay-ack-{index}-{uuid.uuid4().hex}"
        process=subprocess.Popen([sys.executable,str(script),str(ack)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf8",**hidden_windows_subprocess_kwargs())
        arrivals=[]
        acknowledged_alive=False
        def accept(event):
            nonlocal acknowledged_alive
            arrivals.append(event)
            if event.get("kind")=="runtime.answer_delta" and event.get("message")==text:
                acknowledged_alive=process.poll() is None
                ack.write_text("first delta observed",encoding="utf8")
        try:
            raw,errors=_communicate_runtime_events(process,timeout=10,on_event=accept)
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
        _check(process.returncode==0 and not errors and raw.count("FLUXIO_EVENT:")==2 and len(arrivals)==2 and arrivals[0]["message"]==text and acknowledged_alive and ack.exists(),"actual child relay held first delta until exit or lost raw stdout")
        return {"returnCode":process.returncode,"rawBytes":len(raw.encode()),"observedBeforeSilenceEnded":True,"completionRequiredObservedDelta":True}
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:return {"children":list(pool.map(observe,range(8)))}
    if category=="permissions":
        with _sharing(script):
            process=subprocess.run([sys.executable,str(script)],capture_output=True,text=True,**hidden_windows_subprocess_kwargs())
        _check(process.returncode!=0 and "FLUXIO_EVENT:" not in process.stdout,"denied runtime source invented delta")
        return {"actualDeniedChild":process.returncode}
    if category=="stale":
        first=observe();text="Fresh actual runtime delta";script.write_text(script.read_text(encoding="utf8").replace("value="+repr(TEXT.get(category,"Owned accepted runtime delta")),"value="+repr(text)),encoding="utf8");return {"first":first,"fresh":observe()}
    if category=="interrupted":
        # An actual child is terminated after its first accepted line; the relay
        # still delivers that line and exposes the nonzero native exit.
        process=subprocess.Popen([sys.executable,str(script)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf8",**hidden_windows_subprocess_kwargs())
        arrivals=[]
        def interrupt_after_accept(event):
            arrivals.append(event)
            process.terminate()
        try:raw,_=_communicate_runtime_events(process,timeout=10,on_event=interrupt_after_accept)
        finally:
            if process.poll() is None:process.terminate()
            process.wait(timeout=10)
        _check(process.returncode!=0 and len(arrivals)==1 and arrivals[0]["message"]==text and raw.count("FLUXIO_EVENT:")==1,"terminated real child lost accepted prefix or invented completion")
        return {"actualTerminatedChild":process.returncode,"acceptedPrefixRetained":True}
    return observe()


def _toolchain(root,category,identity):
    from .edge_fixture_c7d_control import _toolchain_cache
    if identity=="runtime.toolchain.integrity":
        from .marketplace_toolchain import MarketplaceToolchainUpdateManager
        binary=root/"owned.bin";binary.write_bytes(b"owned exact bytes");digest=hashlib.sha256(binary.read_bytes()).hexdigest()
        config=root/"toolchain.json";config.write_text(json.dumps({"schema":"neyvia.marketplace-toolchain/v1","tools":{"owned":{"path":str(binary),"version":"1","executableSha256":digest}}}),encoding="utf8")
        manager=MarketplaceToolchainUpdateManager(root,toolchain_path=config)
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:manager.local_integrity(),range(8)))
            _check(all(v["healthy"] and v["tools"]["owned"]["actualSha256"]==digest for v in rows),"parallel hash observations guessed pinned identity")
        elif category=="permissions":
            with _sharing(binary):_reject(manager.local_integrity,(OSError,))
        else:
            binary.write_bytes(b"fresh changed bytes");row=manager.local_integrity();_check(not row["healthy"] and row["invalidTools"]==["owned"],"fresh changed executable kept old integrity")
        return {"actualPinnedByteDigest":digest,"binaryExecuted":False}
    if category=="interrupted":
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.edge_fixture_c7d_control import _toolchain_cache","r=Path(sys.argv[1]);m=Path(sys.argv[2]);result=_toolchain_cache(r,'unicode','runtime.toolchain.cache')","m.write_text(json.dumps(result));threading.Event().wait(60)"])
        _stop_at_marker(root,"toolchain-cache",code)
        _check(json.loads((root/"cache.json").read_text(encoding="utf8"))["schema"],"stopped discovery producer lost durable exact metadata")
        return {"actualPublishedCacheReopened":True,"upstreamRequests":0}
    return _toolchain_cache(root,category,identity)


def _service(root,category,identity):
    from .proof_ports import c7_port_block
    port = c7_port_block(int(os.environ['NEYVIA_C7_PORT']))[-2]
    from .managed_local_service import ManagedLocalService,ManagedServiceSpec
    from dataclasses import replace
    script=root/"owned-service.py";text=TEXT.get(category,"owned")
    script.write_text("from http.server import HTTPServer,BaseHTTPRequestHandler\nimport json\nclass Handler(BaseHTTPRequestHandler):\n def do_GET(self):\n  body=json.dumps({'status':'ok','identity':'c7d-owned','selected':"+repr(text)+"}).encode();self.send_response(200);self.end_headers();self.wfile.write(body)\n def log_message(self,*args):pass\nHTTPServer(('127.0.0.1',"+str(port)+"),Handler).serve_forever()\n",encoding="utf8")
    executable=Path(sys.executable);digest=hashlib.sha256(executable.read_bytes()).hexdigest()
    spec=ManagedServiceSpec(service_id="c7d-owned",executable=executable,executable_sha256=digest,argv=(str(script),),state_root=root/"state",health_url=f"http://127.0.0.1:{port}/health",health_expected={"status":"ok"},identity_url=f"http://127.0.0.1:{port}/identity",identity_value="c7d-owned",required_files=((script,hashlib.sha256(script.read_bytes()).hexdigest()),),startup_timeout_seconds=8,stop_timeout_seconds=3)
    service=ManagedLocalService(spec)
    if identity=="runtime.service.installation":
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:service._validate_installation(),range(8)))
        elif category=="permissions":
            with _sharing(script):_reject(service._validate_installation,(OSError,))
        elif category in {"interrupted","stale"}:
            if category=="interrupted":_interrupted_write(script,"print('partial changed source')")
            else:script.write_text("print('fresh changed source')",encoding="utf8")
            _reject(service.start,(RuntimeError,ValueError));_check(not spec.state_path.exists(),"invalid source spawned a service")
        else:service._validate_installation()
        return {"realExecutableDigest":digest,"requiredFileValidated":True,"spawned":False}
    if category=="permissions":
        spec.state_root.mkdir(parents=True)
        from .edge_fixture_c7d_local import _deny_child_creation
        with _deny_child_creation(spec.state_root,root):_reject(service.start,(OSError,))
        _check(not spec.state_path.exists(),"denied durable service ownership published a PID")
        return {"actualStatePublicationDenied":True}
    if identity=="runtime.service.identity":
        foreign=root/"foreign.bin";foreign.write_bytes(b"foreign declaration")
        fspec=replace(spec,executable=foreign,executable_sha256=hashlib.sha256(foreign.read_bytes()).hexdigest(),state_root=root/"foreign-state")
        fspec.state_root.mkdir();fspec.state_path.write_text(json.dumps({"pid":os.getpid(),"specHash":fspec.spec_hash}),encoding="utf8")
        fservice=ManagedLocalService(fspec);_check(fservice.status()["status"]=="foreign_pid","foreign PID was claimed as running");_reject(fservice.stop,(RuntimeError,));_check(os.getpid()>0,"foreign PID stopped")
    try:
        launched=service.start();_check(launched["status"]=="running" and not launched["reused"],"new exact service was not launched")
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:ManagedLocalService(spec).start(),range(8)))
            _check(all(v["pid"]==launched["pid"] and v["reused"] for v in rows),"simultaneous exact starts spawned replacement or lost identity")
        elif category=="stale":
            changed=ManagedLocalService(replace(spec,environment={"C7D_CHANGED_SPEC":"1"}))
            observed=changed.status();_check(observed["status"]!="running","changed specification reused old owned process");_reject(changed.stop,(RuntimeError,))
        elif category=="interrupted":
            code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.managed_local_service import ManagedServiceSpec,ManagedLocalService","p=json.loads(sys.argv[3]);p['executable']=Path(p['executable']);p['state_root']=Path(p['state_root']);p['required_files']=tuple((Path(a),b) for a,b in p['required_files']);p['argv']=tuple(p['argv'])","r=ManagedLocalService(ManagedServiceSpec(**p)).start();Path(sys.argv[2]).write_text(json.dumps(r));threading.Event().wait(60)"])
            stopped=_stop_at_marker(root,"service-client",code,json.dumps(asdict(spec),default=str));_check(stopped["observed"]["pid"]==launched["pid"] and service.start()["pid"]==launched["pid"],"killed client lost live exact service identity")
        elif category=="offline":
            service.stop();_check(service.status()["status"]!="running","offline stopped service remained ready")
            return {"actualStoppedEndpoint":True,"pid":launched["pid"]}
        else:_check(service.start()["pid"]==launched["pid"],"healthy exact service was not reused")
        stopped=service.stop();_check(stopped["status"]=="stopped" and not stopped["pid"],"owned service stop left a live PID")
        return {"actualPid":launched["pid"],"exactHealthyIdentity":True,"ownedProcessStopped":True}
    finally:
        if service.status()["status"]=="running":service.stop()


def _execution(root,category,identity):
    from . import action_executor as owner
    from .models import ActionProposal,PlannedStep,ExecutionScope
    project=root/"project";project.mkdir();text=TEXT.get(category,"Owned selected source")
    source=project/"README.md";source.write_text(text,encoding="utf8")
    policy=owner.build_execution_policy("builder")
    if identity=="control.execution-proposal":
        def proposal(index=0):return owner.build_action_proposal(PlannedStep(step_id=str(index),title="Review referenced docs and extract constraints"),text,project,[],runtime_id="openclaw",execution_scope=owner.prepare_execution_scope(project,str(index),requested_scope="direct"),execution_policy=policy)
        first=proposal();_check(first.source_step_id=="0" and first.target_scope=="workspace","proposal lost explicit source-step or scope identity")
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(proposal,range(8)))
            _check([v.source_step_id for v in rows]==[str(i) for i in range(8)] and all(v.target_scope=="workspace" for v in rows),"parallel proposal classification changed explicit step/scope identity")
        return {"proposalKind":first.kind,"executed":False}
    if identity=="control.execution-result":
        from .crashproof import CrashProofStore
        scope=owner.prepare_execution_scope(project,"owned",requested_scope="direct")
        script=project/"owned-command.py";script.write_text("from pathlib import Path\nimport hashlib,os,time\np=Path(__file__).with_name('README.md')\nprint(hashlib.sha256(p.read_bytes()).hexdigest(),flush=True)\n"+("os._exit(23)\n" if category=="interrupted" else ""),encoding="utf8")
        command=ActionProposal(action_id="owned",kind="shell_command",title="Owned actual command",command=f'"{sys.executable}" "{script}"',requires_approval=True,policy_decision="requires_approval",mutability_class="read",risk_level="medium")
        lease=CrashProofStore(project).create_autonomy_lease(mission_id="owned",duration_seconds=600,policy={"allowedActions":["shell_command"],"allowedRoots":[str(project.resolve())],"destructiveAllowed":False,"publicCommunicationAllowed":False,"maxSpend":0})
        def execute(index=0):return owner.execute_action(command,project,execution_scope=scope,autonomy_lease_id=None if category=="permissions" else lease["leaseId"])
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(execute,range(8)))
        else:rows=[execute()]
        if category=="permissions":_check(all(v.gate.status!="approved" and not v.result.ok for v in rows),"unapproved actual command executed")
        elif category=="interrupted":_check(rows[0].result.exit_code==23 and not rows[0].result.ok,"real self-terminated child was counted successful")
        else:_check(all(v.result.ok and hashlib.sha256(source.read_bytes()).hexdigest() in v.result.stdout and v.gate.approved_by=="autonomy:"+lease["leaseId"] for v in rows),"actual native child lost source readback or scoped lease attribution")
        if category=="stale":
            source.write_text("Fresh selected source",encoding="utf8");fresh=execute();_check(hashlib.sha256(source.read_bytes()).hexdigest() in fresh.result.stdout and fresh.result.stdout!=rows[0].result.stdout,"new actual child reused prior stdout")
        timeout=ActionProposal(action_id="timeout",kind="test_run",title="Finite child deadline",command=f'"{sys.executable}" -c "import time; time.sleep(2)"',target_path=str(project),mutability_class="execute",policy_decision="auto_run",requires_approval=False)
        result=owner.execute_action(timeout,project,execution_scope=scope,execution_policy=policy,timeout_seconds=1)
        _check(not result.result.ok and result.result.exit_code==124,"native deadline was counted completed")
        return {"actualChildren":len(rows),"deadlineExitCode":124,"providerInvoked":False}
    scope=owner.prepare_execution_scope(project,"owned")
    target=Path(scope.execution_root);target.resolve().relative_to(root.resolve())
    _check(scope.strategy=="filesystem_copy" and target!=project and (target/"README.md").read_text(encoding="utf8")==text,"execution copy lost actual source/local isolation identity")
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:scopes=list(pool.map(lambda i:owner.prepare_execution_scope(project,"writer-"+str(i)),range(8)))
        _check(len({v.execution_root for v in scopes})==8,"concurrent isolation roots collided")
        for v in scopes:_check(owner.cleanup_execution_scope(v)["cleaned"],"concurrent owned copy cleanup left root")
    elif category=="stale":
        source.write_text("Fresh selected source",encoding="utf8");fresh=owner.prepare_execution_scope(project,"fresh");_check((Path(fresh.execution_root)/"README.md").read_text(encoding="utf8")=="Fresh selected source" and (target/"README.md").read_text(encoding="utf8")==text,"fresh isolation reused or mutated earlier snapshot");owner.cleanup_execution_scope(fresh)
    elif category=="permissions":
        if identity=="control.execution-cleanup":
            with _sharing(target/"README.md"):refused=owner.cleanup_execution_scope(scope)
            _check(not refused["cleaned"] and target.exists(),"denied cleanup falsely claimed removal")
        else:
            with _sharing(source):denied=owner.prepare_execution_scope(project,"denied")
            _check(denied.strategy=="direct" and not denied.isolated and denied.status=="fallback" and Path(denied.execution_root)==project.resolve(),"denied copy falsely claimed isolated scope")
    elif category=="interrupted":
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.action_executor import prepare_execution_scope","v=prepare_execution_scope(Path(sys.argv[3]),'stopped');Path(sys.argv[2]).write_text(json.dumps({'executionRoot':v.execution_root}));threading.Event().wait(60)"])
        stopped=_stop_at_marker(root,"isolation-client",code,str(project));owned=Path(stopped["observed"]["executionRoot"]);_check((owned/"README.md").read_text(encoding="utf8")==text,"killed isolation client lost published snapshot")
        cleanup=ExecutionScope(isolated=True,strategy="filesystem_copy",workspace_root=str(project),execution_root=str(owned),worktree_path=str(owned));_check(owner.cleanup_execution_scope(cleanup)["cleaned"],"reopened exact stopped scope not cleaned")
    _check(owner.cleanup_execution_scope(scope)["cleaned"] and project.exists(),"cleanup escaped source or left owned isolation")
    return {"actualFilesystemCopy":True,"guardedCleanup":True,"sourceKeeper":str(source)}


def _submission(root,category,identity):
    from .agent_submission_gate import SCHEMA,validate_receipt
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    folder=root/"submission";(folder/"src").mkdir(parents=True);source=folder/"src/owned.txt";source.write_bytes(b"before")
    def git(*args):return subprocess.run(["git","-C",str(folder),*args],capture_output=True,text=True,check=True,**hidden_windows_subprocess_kwargs()).stdout.strip()
    git("init","-q");git("add",".");git("-c","user.name=C7d fixture","-c","user.email=fixture@example.invalid","commit","-qm","owned baseline");baseline=git("rev-parse","HEAD")
    text=TEXT.get(category,"Owned source");source.write_text(text,encoding="utf8");proof=folder/"proof.json"
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    proof.write_text(json.dumps({"sourceHashes":{"src/owned.txt":digest(source)}}),encoding="utf8")
    receipt={"schema":SCHEMA,"agent":"owned","phase":"local","lane":"owned","baseline":{"commit":baseline},"allowedFiles":["src/**","proof.json"],"forbiddenFiles":[".agent_control/**"],"changedFiles":[{"path":"src/owned.txt","changeType":"modified","beforeSha256":hashlib.sha256(b"before").hexdigest(),"afterSha256":digest(source)},{"path":"proof.json","changeType":"added","beforeSha256":None,"afterSha256":digest(proof)}],"commands":[{"command":"local producer","exitCode":0,"result":{"passed":1,"failed":0,"skipped":0}}],"proofs":[{"path":"proof.json","sha256":digest(proof),"kind":"local","sourceHashes":{"src/owned.txt":digest(source)}}],"blockers":[],"claims":{"live":{"claimed":False},"physicalDevice":{"claimed":False}},"summary":{"changedFiles":2,"proofFiles":1,"commandCount":1}}
    def observe(value=receipt):return validate_receipt(value,root=folder)
    first=observe();_check(first.ok,"current owned local submission receipt rejected")
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:observe(),range(8)))
        _check(all(v==first for v in rows),"parallel independent source-bound validators changed verdict")
    elif category=="permissions":
        with _sharing(proof):_reject(observe,(OSError,))
    elif category=="interrupted":
        _interrupted_write(proof,'{"sourceHashes":');_check(not observe().ok,"partial actual proof producer was accepted")
    elif category=="stale":
        source.write_text("fresh changed source",encoding="utf8");_check(not observe().ok,"stale source receipt was accepted")
    else:
        bad=copy.deepcopy(receipt)
        if identity=="control.submission-counts":bad["summary"]["proofFiles"]=9
        elif identity=="control.submission-git-delta":(folder/"src/omitted.txt").write_text(text,encoding="utf8")
        elif identity=="control.submission-lineage":bad["claims"]["live"]["claimed"]=True
        elif identity=="control.submission-secrets":bad["password"]="generated rejection specimen"
        elif identity=="control.submission-source-phase":bad["forbiddenFiles"]=["src/**"]
        else:bad["schema"]="invalid"
        verdict=observe(bad);_check(not verdict.ok and bool(verdict.errors),"invalid specific incoming obligation was accepted")
        if identity=="control.submission-secrets":_check(verdict.errors==("receipt contains secret-like key or value",),"secret-like rejection echoed submitted value")
    return {"sourceBoundLocalValidator":True,"renderedProof":False,"providerProof":False,"physicalDeviceProof":False}


def _interrupted_import(root,category,identity):
    if identity=="control.attachments-content":
        data=b"Actual completed owned attachment";encoded=base64.b64encode(data).decode()
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.connected_sessions.attachments import save_files","r=Path(sys.argv[1]);m=Path(sys.argv[2]);p=save_files([{'name':'nested/owned.txt','data':sys.argv[3]}],directory=r/'files')[0]","m.write_text(json.dumps({'path':str(p)}));threading.Event().wait(60)"])
        stopped=_stop_at_marker(root,"attachment-client",code,encoded);path=Path(stopped["observed"]["path"]);_check(path.read_bytes()==data and path.is_relative_to(root),"killed attachment client lost exact bounded content")
        return {"actualContentSha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    if identity=="control.import-upload":
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.context_import import stage_upload","r=Path(sys.argv[1]);m=Path(sys.argv[2]);v=stage_upload(r,filename='../owned.txt',chunks=[b'Actual owned upload'])","m.write_text(json.dumps(v));threading.Event().wait(60)"])
    else:
        source=root/"owned.txt";source.write_text("Actual selected context",encoding="utf8")
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.context_import import preview_export,import_selection,SUPPORTED_PROVIDERS","r=Path(sys.argv[1]);m=Path(sys.argv[2]);p=r/'owned.txt';provider=next(iter(SUPPORTED_PROVIDERS));v=preview_export(provider,p,root=r)","result=import_selection(r,provider=provider,export_path=p,selected_item_ids=[v['items'][0]['itemId']],expected_sha256=v['source']['sha256'])","m.write_text(json.dumps(result));threading.Event().wait(60)"])
    stopped=_stop_at_marker(root,"context-import-client",code);value=stopped["observed"]
    from . import context_import as owner
    if identity=="control.import-upload":
        _,stored=owner._resolve_staged_upload(root,value["uploadId"]);_check(stored["sha256"]==value["sha256"],"killed upload client lost bound bytes")
    else:_check(Path(value["contentPath"]).is_file() and value["importedItems"]==1,"killed import client lost selected durable rows")
    return {"actualStoppedClient":stopped["returnCode"],"durableSelectedIdentity":value.get("uploadId",value.get("importId"))}


def _runtime_model(root,category,identity):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    text=TEXT.get(category,"Owned model label");count=0 if category=="empty" else 600 if category=="huge" else 1
    payload={"catalog":{"harnesses":[{"harnessId":"neyvia-agent" if i==0 else "owned-"+str(i),"label":text,"installed":i%2==0,"detected":False,"readiness":"missing","capabilities":[]} for i in range(count)]},"matrix":{"runtimes":[{"id":"neyvia","kind":"native","connected":True,"capabilities":{"start":True},"options":{"models":[{"id":text,"default":True}]}}] if count else [],"policies":{"neyvia":{"permissionCeiling":"read-only","allowedModels":[text]}}}}
    path=root/"selected-model-input.json";path.write_text(json.dumps(payload),encoding="utf8")
    module=(REPO/"web/src/neyvia/next/nxRuntimeModel.js").as_uri()
    script=root/"owned-runtime-model.mjs";script.write_text("import {readFileSync} from 'node:fs';import {mergeRuntimes,runtimeSummary} from "+json.dumps(module)+";const p=JSON.parse(readFileSync(process.argv[2],'utf8'));const rows=mergeRuntimes(p.catalog,p.matrix);const result=runtimeSummary(rows);if(rows.length!==p.catalog.harnesses.length||result.installed!==rows.filter(r=>r.installed).length||result.ready!==rows.filter(r=>r.tone==='green').length)throw Error('authoritative counts differ');if(rows.length&&rows.filter(r=>r.id==='neyvia').length!==1)throw Error('alias duplicated');console.log(JSON.stringify({summary:result,first:rows[0]||null}));",encoding="utf8")
    completed=subprocess.run(["node",str(script),str(path)],capture_output=True,text=True,encoding="utf8",check=True,timeout=30,**hidden_windows_subprocess_kwargs())
    result=json.loads(completed.stdout);_check(result["summary"]["total"]==count,"runtime projection invented detected rows")
    return {"actualNodeModelCall":result["summary"],"renderedProof":False,"installedRuntimeProof":False}


def _vision(root,category,identity):
    from .proof_ports import c7_port_block
    # Managed services and Syncthing use the last two slots. Give the loop's
    # explicitly bound client a separate pair so their exclusive Windows
    # listener/TIME_WAIT state cannot deny its source-port admission.
    gui_port, tcp_port = c7_port_block(int(os.environ['NEYVIA_C7_PORT']))[:2]
    from PIL import Image
    from agents import OpenAIProvider
    from agents.tool_context import ToolContext
    from openai import AsyncOpenAI
    from .neyvia_agent import NeyviaAgentConfig,build_neyvia_agent
    from .proof_credential_guard import prepare_broker_fixture
    import asyncio,socket
    class LocalToolLoop(asyncio.SelectorEventLoop):
        def _make_self_pipe(self):
            # Keep Windows' standard thread wake-up semantics with the two
            # explicitly allocated loopback ports; never let it bind port0.
            listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            client=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            try:
                listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                client.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                listener.bind(("127.0.0.1",gui_port));listener.listen(1)
                client.bind(("127.0.0.1",tcp_port));client.connect(("127.0.0.1",gui_port))
                self._ssock,_=listener.accept();self._csock=client
                self._ssock.setblocking(False);self._csock.setblocking(False)
                self._internal_fds+=1
                self._add_reader(self._ssock.fileno(),self._read_from_self)
            except BaseException:
                client.close();raise
            finally:listener.close()
    prepare_broker_fixture(root)
    path=root/"owned.png";size=512 if category=="huge" else 16
    if category=="empty":path.write_bytes(b"")
    else:Image.new("RGB",(size,size),(25,90,160)).save(path)
    provider=OpenAIProvider(openai_client=AsyncOpenAI(api_key="generated-fixture-only",base_url=f"http://127.0.0.1:{tcp_port}/v1"),use_responses=False)
    agent,_,_=build_neyvia_agent(NeyviaAgentConfig(root=root,session_id="owned",agent_role="verifier",transport="chat-completions",model="owned",provider_id="openai",enable_specialists=False),provider=provider)
    describe=next(v for v in agent.tools if v.name=="neyvia_tools_describe")
    ctx=ToolContext(context=None,tool_name=describe.name,tool_call_id="describe",tool_arguments="{}")
    with asyncio.Runner(loop_factory=LocalToolLoop) as runner:
        invoke=runner.run
        invoke(describe.on_invoke_tool(ctx,json.dumps({"tool_id":"neyvia_view_image"})))
        tool=next(v for v in agent.tools if v.name=="neyvia_view_image");ctx=ToolContext(context=None,tool_name=tool.name,tool_call_id="image",tool_arguments="{}")
        def read():return invoke(tool.on_invoke_tool(ctx,json.dumps({"path":"owned.png"})))
        if category=="empty":
            value=read();_check(not hasattr(value,"image_url"),"empty file invented real image pixels")
            return {"actualEmptyImageRefused":True,"modelCalled":False}
        if category=="permissions":
            with _sharing(path):value=read()
            _check(not hasattr(value,"image_url"),"OS-denied image invented pixel output")
            return {"actualOSPixelReadDenied":True,"modelCalled":False}
        if category=="interrupted":
            _interrupted_write(path,"partial PNG producer")
            value=read();_check(not hasattr(value,"image_url"),"partial image producer invented decoded pixels")
            return {"actualPartialImageRefused":True,"modelCalled":False}
        if category=="concurrency":
            async def concurrent_reads():
                return await asyncio.gather(*(tool.on_invoke_tool(ctx,json.dumps({"path":"owned.png"})) for _ in range(8)))
            values=invoke(concurrent_reads())
        else:values=[read()]
        _check(all(base64.b64decode(v.image_url.split(",",1)[1])==path.read_bytes() for v in values),"workspace tool changed exact encoded image bytes")
        if category=="stale":
            previous=path.read_bytes();Image.new("RGB",(16,16),(70,80,90)).save(path);fresh=read();_check(base64.b64decode(fresh.image_url.split(",",1)[1])==path.read_bytes()!=previous,"fresh image call reused earlier pixels")
        denied=invoke(tool.on_invoke_tool(ctx,json.dumps({"path":str(root.parent/"outside.png")})))
        _check(not hasattr(denied,"image_url"),"outside image path produced pixels")
        return {"actualImageSha256":hashlib.sha256(path.read_bytes()).hexdigest(),"modelCalled":False,"renderedProof":False}



def _metadata(root,category,identity):
    environment={"PATH":"","HERMES_HOME":str(root/"hermes-home")}
    if identity=="runtime.hermes-metadata":
        from .hermes_integration import plugin_inventory
        environment["PATH"]=TEXT.get(category,str(root/"explicitly-unavailable-cli"))
        if category=="huge":environment["PATH"]=os.pathsep.join(str(root/("missing-"+str(i))) for i in range(1000))
        def read():return plugin_inventory(environment=environment)
        value=read();_check(value["available"] is False and value["plugins"]==[],"absent explicit Hermes command exposed installed plugins")
    else:
        from .runtime_capability_inventory import build_runtime_capability_inventory
        from .proof_credential_guard import prepare_broker_fixture
        prepare_broker_fixture(root);home=root/"codex-home";home.mkdir()
        config=root/".agent_control/mcp_broker.json";config.parent.mkdir(exist_ok=True);label=TEXT.get(category,"generated-private-env-value")
        config.write_text(json.dumps({"schema":"neyvia.mcp-broker/v1","servers":{"owned":{"transport":"sse","url":"https://example.invalid/generated-private-url","env":{"OWNED_VALUE":label or "generated-private-env"}}}}),encoding="utf8")
        def read():return build_runtime_capability_inventory(root,home,environment=environment)
        value=read();public=json.dumps(value);_check("generated-private-url" not in public and "generated-private-env" not in public and value["hermes"]["available"] is False,"public inventory exposed private endpoint/environment or invented CLI readiness")
        if category=="permissions":
            with _sharing(config):denied=read()
            _check("mcp" in denied["degradedSources"],"unreadable metadata owner did not expose degraded source")
        elif category=="interrupted":
            _interrupted_write(config,'{"servers":');denied=read();_check("mcp" in denied["degradedSources"],"partial actual metadata producer was not degraded")
        elif category=="stale":
            config.write_text(json.dumps({"servers":{}}),encoding="utf8");fresh=read();_check(not any(v["name"]=="owned" for v in fresh["mcpServers"]),"fresh inventory reused removed config server")
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:read(),range(8)))
        _check(all(v.get("hermes",v).get("available") is False for v in rows),"parallel inventory invented absent native runtime")
    return {"actualInventorySchema":value.get("schema"),"nativeHermesAvailable":False,"providerCalled":False,"renderedProof":False}


def _bridge_interrupted(root,category,identity):
    # Stop the actual owner client after the durable append closes, then reopen
    # its committed row through the real receipt loader.
    code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.edge_fixture_c7d_control_completion import _bridge","r=Path(sys.argv[1]);m=Path(sys.argv[2]);v=_bridge(r,'unicode',sys.argv[3])","m.write_text(json.dumps(v));threading.Event().wait(60)"])
    stopped=_stop_at_marker(root,"bridge-receipt-client",code,identity)
    from .connected_device_bridge import load_bridge_receipts
    rows=load_bridge_receipts(root);_check(len(rows)==1 and rows[0].get("status") in {"received","denied","empty","approved"},"killed bridge client lost committed exact receipt")
    return {"actualDurableRows":len(rows),"stoppedClientCode":stopped["returnCode"],"renderedProof":False}


def _browser_diagnostic(root,category,identity):
    from . import browser_preflight as owner
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    source=root/"OwnedDiagnostic.cs";binary=root/"owned-diagnostic.exe";selected=root/"selected-diagnostic.txt";text=TEXT.get(category,"Owned diagnostic")
    selected.write_text(text,encoding="utf8")
    source.write_text('using System; using System.IO; class Probe { static int Main() { var text=File.ReadAllText(Environment.GetEnvironmentVariable("C7D_DIAGNOSTIC_TEXT")); Console.Error.WriteLine("error while loading shared libraries: libatk-1.0.so.0: missing "+text); return Environment.GetEnvironmentVariable("C7D_INTERRUPTED")=="1" ? 23 : 127; } }',encoding="utf8")
    powershell=Path(os.environ["SystemRoot"])/"System32/WindowsPowerShell/v1.0/powershell.exe"
    quote=lambda v:"'"+str(v).replace("'","''")+"'"
    compiled=subprocess.run([str(powershell),"-NoProfile","-NonInteractive","-Command","Add-Type -Path "+quote(source)+" -OutputAssembly "+quote(binary)+" -OutputType ConsoleApplication"],capture_output=True,text=True,timeout=30,**hidden_windows_subprocess_kwargs())
    _check(compiled.returncode==0,"finite diagnostic protocol compilation failed")
    package=root/"package-protocol";package.mkdir()
    for name in ("apt-get","sudo"):(package/(name+".cmd")).write_text("@echo off\r\nexit /b 77\r\n",encoding="ascii")
    home=root/"explicit-empty-home";home.mkdir()
    updates={"PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH":str(binary),"PLAYWRIGHT_BROWSERS_PATH":str(home/"absent-cache"),"HOME":str(home),"USERPROFILE":str(home),"PATH":str(package),"C7D_DIAGNOSTIC_TEXT":str(selected),"C7D_INTERRUPTED":"1" if category=="interrupted" else "0"}
    def observe():return owner.repair_browser_dependencies(root,dry_run=True) if identity=="control.browser-repair" else owner.build_browser_dependency_preflight(root)
    with _environment(updates):
        if category=="permissions" and identity=="control.browser-preflight":
            with _sharing(binary):denied=observe()
            _check(denied["status"]=="failed" and not denied["browserProofAvailable"],"denied version process was available")
        else:
            value=observe();diagnosis=value["before"] if identity=="control.browser-repair" else value
            _check(diagnosis["status"]=="dependency_missing" and diagnosis["missingLibraries"]==["libatk-1.0.so.0"] and "libatk1.0-0" in diagnosis["repairPlan"]["packages"],"actual failed subprocess did not bind diagnostic repair package")
            if identity=="control.browser-repair":
                _check(value["before"]==value["after"] and all(v["dryRun"] and v["status"]=="planned" for v in value["actions"]),"dry repair executed or changed before/after")
                if category=="permissions":
                    path=Path(value["receiptPath"]);before=path.read_bytes()
                    with _sharing(path):_reject(observe,(OSError,))
                    _check(path.read_bytes()==before,"denied dry plan changed keeper")
            if category=="concurrency":
                with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:observe(),range(8)))
                _check(len(rows)==8,"concurrent diagnostic results missing")
            elif category=="stale":
                selected.write_text("Fresh native diagnostic text",encoding="utf8");fresh=observe();row=fresh["before"] if identity=="control.browser-repair" else fresh;_check("Fresh native diagnostic text" in row["error"],"new version diagnosis reused old stdout")
    return {"finiteActualExecutableProtocol":True,"actualChromeLaunched":False,"renderedProof":False,"installationExecuted":False}


def _manual(root,category,identity):
    import shutil
    # Select the manual repository only inside an owned child process, so other
    # concurrent product readers keep their current source authority.
    cloned=root/"selected-manual-repository";(cloned/"config").mkdir(parents=True)
    shutil.copytree(REPO/"manuals",cloned/"manuals")
    shutil.copyfile(REPO/"config/neyvia_manuals.json",cloned/"config/neyvia_manuals.json")
    code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent import neyvia_manuals as owner","from grant_agent.native_tools import NativeToolRegistry","from grant_agent.neyvia_workspace_tools import workspace_for","from grant_agent.proof_credential_guard import install,prepare_broker_fixture","from grant_agent.edge_fixture_host_runtime import _sharing","r=Path(sys.argv[1]);m=Path(sys.argv[2]);category=sys.argv[3];owner.REPO=r/'selected-manual-repository';install(r);prepare_broker_fixture(r)","record=next(v for v in owner.records() if v['id']=='agents');source=owner.REPO/record.get('clSource',record['path'])","service=workspace_for(r);registry=NativeToolRegistry(r,nas_root=r/'unused-local-label')","def load():return owner.call(service,'manual.load',{'id':'agents'},registry=registry)","try:"," if category=='permissions':", "  with _sharing(source):", "   try:load();raise AssertionError('unreadable manual accepted')", "   except OSError:pass", "  result={'actualManualReadDenied':True}"," elif category=='stale':", "  artifact=owner.REPO/record['path'];data=json.loads(artifact.read_text(encoding='utf8'));data['title']='Changed independent artifact';artifact.write_text(json.dumps(data),encoding='utf8')", "  try:load();raise AssertionError('stale compiled artifact accepted')", "  except ValueError as e:assert 'stale' in str(e)", "  result={'actualStaleArtifactRefused':True}"," else:","  result=load();assert result['ok'] and result['id']=='agents'", " m.write_text(json.dumps({'ok':True,'detail':result}))", " threading.Event().wait(60)","finally:service.close()"])
    stopped=_stop_at_marker(root,"manual-client",code,category)
    return {"actualManualOwner":stopped["observed"],"selectedRepository":str(cloned),"renderedProof":False}


def _image_magic(root,category,identity):
    import importlib.util
    specification=importlib.util.spec_from_file_location("c7d_magic_owner",REPO/"scripts/run_controlled_ai_safety_review.py")
    owner=importlib.util.module_from_spec(specification);sys.modules[specification.name]=owner;specification.loader.exec_module(owner)
    path=root/"wrong-extension.txt";path.write_bytes(b"\x89PNG\r\n\x1a\nOwned bytes")
    _check(owner.detected_image_extension(path)==".png","actual image signature inferred from filename")
    if category=="permissions":
        with _sharing(path):_reject(lambda:owner.detected_image_extension(path),(OSError,))
    elif category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:owner.detected_image_extension(path),range(8)))
        _check(rows==[".png"]*8,"parallel signatures differed from actual bytes")
    elif category=="interrupted":
        _interrupted_write(path,"partial image header");_check(owner.detected_image_extension(path)=="","actual unfinished image producer invented extension")
    else:path.write_bytes(b"\xff\xd8\xffFresh selected bytes");_check(owner.detected_image_extension(path)==".jpg","new bytes reused earlier signature")
    return {"actualByteSignature":True,"modelOrDecoderInvoked":False}


def _approval_parallel(root,category,identity):
    from .edge_fixture_surfaces import _approval
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _: _approval(root,"unicode"),range(8)))
    return {"independentExactActionGrants":8,"externalActionExecuted":False}


def _cu_extra(root,category,identity):
    from . import cu_acceptance as owner
    canonical=owner.CANONICAL_FLOWS[0]
    def fail():return owner.run_flow(canonical,root=root,discovery_urls=[]) if identity=="control.cu-aliases" else owner.run_suite(root=root,flows=[canonical],discovery_urls=[])
    first=fail();_check(first["pass"] is False,"unavailable gate invented successful acceptance")
    latest=owner.receipt_dir(root)/((canonical if identity=="control.cu-aliases" else "suite")+"_latest.json")
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:fail(),range(8)))
        _check(all(v["pass"] is False for v in rows),"parallel unavailable gates counted failure as success")
    elif category=="permissions":
        before=latest.read_bytes()
        with _sharing(latest):_reject(fail,(OSError,))
        _check(latest.read_bytes()==before,"denied gate write changed failed keeper")
    elif category=="stale":
        first["pass"]=True
        fresh=fail();_check(fresh["pass"] is False and json.loads(latest.read_text(encoding="utf8"))["pass"] is False,"fresh unavailable gate reused stale returned success")
    else:
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.cu_acceptance import run_flow,run_suite,CANONICAL_FLOWS","r=Path(sys.argv[1]);m=Path(sys.argv[2]);v=run_flow(CANONICAL_FLOWS[0],root=r,discovery_urls=[]) if sys.argv[3]=='control.cu-aliases' else run_suite(root=r,flows=[CANONICAL_FLOWS[0]],discovery_urls=[])","m.write_text(json.dumps({'pass':v['pass']}));threading.Event().wait(60)"])
        stopped=_stop_at_marker(root,"cu-gate-client",code,identity);_check(stopped["observed"]["pass"] is False and json.loads(latest.read_text(encoding="utf8"))["pass"] is False,"killed client lost durable failed gate")
    return {"actualUnavailableGate":True,"explicitDiscoveryUrls":[],"renderedProof":False}


def _hermes_protocol(root,category,identity):
    from .hermes_integration import plugin_inventory
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    source=root/"OwnedMetadataProtocol.cs";binary=root/"hermes.exe";data=root/"owned-public-metadata.json"
    data.write_text(json.dumps([{"name":"owned finite CLI protocol","description":"Observed protocol metadata","version":"1","status":"enabled","source":"generated","password":"generated-redaction-specimen","command":"generated-private-command"}]),encoding="utf8")
    source.write_text('using System;using System.IO;class OwnedProtocol {static int Main(){Console.Write(File.ReadAllText(Environment.GetEnvironmentVariable("C7D_METADATA_FILE")));return Environment.GetEnvironmentVariable("C7D_METADATA_INTERRUPTED")=="1" ? 23 : 0;}}',encoding="utf8")
    powershell=Path(os.environ["SystemRoot"])/"System32/WindowsPowerShell/v1.0/powershell.exe";quote=lambda v:"'"+str(v).replace("'","''")+"'"
    child=subprocess.run([str(powershell),"-NoProfile","-NonInteractive","-Command","Add-Type -Path "+quote(source)+" -OutputAssembly "+quote(binary)+" -OutputType ConsoleApplication"],capture_output=True,text=True,timeout=30,**hidden_windows_subprocess_kwargs());_check(child.returncode==0,"finite CLI metadata protocol compilation failed")
    env={"PATH":str(root),"HERMES_HOME":str(root/"selected-home"),"C7D_METADATA_FILE":str(data),"C7D_METADATA_INTERRUPTED":"1" if category=="interrupted" else "0"}
    if category=="permissions":
        with _sharing(binary):value=plugin_inventory(environment=env)
        _check(value["available"] is False and value["plugins"]==[],"denied command exposed metadata rows")
    elif category=="interrupted":
        value=plugin_inventory(environment=env);_check(not value["available"] and value["plugins"]==[],"native nonzero CLI exit exposed installed plugins")
    else:
        first=plugin_inventory(environment=env);_check(first["available"] and set(first["plugins"][0])=={"name","description","version","status","source"},"actual CLI protocol leaked nonpublic fields")
        binary.rename(root/"retired-owned-protocol.exe");fresh=plugin_inventory(environment=env);_check(not fresh["available"] and fresh["plugins"]==[],"removed command exposed cached installed rows")
    return {"actualFiniteCLIProtocol":True,"realHermesInstallationClaimed":False,"providerCalled":False}


def _syncthing(root,category,identity):
    from .edge_fixture_c7d_syncthing import observe
    return observe(REPO,root,category,identity)


FAMILIES={
    "bridge":(_bridge,{"control.bridge-authority","control.bridge-feedback","control.bridge-grants","control.bridge-receipt","control.bridge-snapshot"},CATEGORIES-{"offline","interrupted"}),
}
FAMILIES["bridge-durable-interrupted"]=(_bridge,{"control.bridge-grants","control.bridge-snapshot"},{"interrupted"})
FAMILIES["console-memory"]=(_console,{"control.console-memory"},CATEGORIES-{"offline"})
FAMILIES["console-observation"]=(_console,{"control.console-observation"},set(TEXT))
FAMILIES["context"]=(_context,{"control.context-bundle","control.context-metrics"},CATEGORIES-{"offline"})
FAMILIES["result"]=(_result,{"control.result-retention"},CATEGORIES-{"offline"})
FAMILIES["cu-receipt"]=(_cu,{"control.cu-receipt"},CATEGORIES-{"offline"})
FAMILIES["cu-failure"]=(_cu,{"control.cu-aliases","control.cu-verdict","control.cu-recovery"},set(TEXT)|{"offline"})
FAMILIES["prompt-denied"]=(_prompt_denied,{"control.prompts-composition","control.prompts-durable"},{"permissions"})
FAMILIES["limits"]=(_limits,{"control.plan-limits"},CATEGORIES-{"offline"})
FAMILIES["history"]=(_plan_history,{"control.plan-history"},CATEGORIES-{"offline"})
FAMILIES["stream"]=(_stream,{"control.stream-frame","control.stream-tail"},CATEGORIES-{"offline"})
FAMILIES["stream-order"]=(_stream,{"control.stream-order"},set(TEXT)|{"concurrency"})
FAMILIES["stream-relay"]=(_relay,{"control.stream-relay"},CATEGORIES)
FAMILIES["toolchain-cache"]=(_toolchain,{"runtime.toolchain.cache"},{"interrupted"})
FAMILIES["toolchain-discovery"]=(_toolchain,{"runtime.toolchain.discovery"},{"concurrency","permissions","stale"})
FAMILIES["toolchain-integrity"]=(_toolchain,{"runtime.toolchain.integrity"},{"concurrency","permissions","stale"})
FAMILIES["service"]=(_service,{"runtime.service.identity","runtime.service.lifecycle"},CATEGORIES)
FAMILIES["service-installation"]=(_service,{"runtime.service.installation"},{"concurrency","permissions","interrupted","stale"})
FAMILIES["execution"]=(_execution,{"control.execution-result","control.execution-scope","control.execution-cleanup"},CATEGORIES-{"offline"})
FAMILIES["execution-proposal"]=(_execution,{"control.execution-proposal"},set(TEXT)|{"concurrency"})
FAMILIES["submission"]=(_submission,{"control.submission-"+v for v in ("counts","git-delta","lineage","secrets","source-phase","verdict")},CATEGORIES-{"offline"})
FAMILIES["import-client"]=(_interrupted_import,{"control.attachments-content","control.import-selection","control.import-upload"},{"interrupted"})
FAMILIES["runtime-model"]=(_runtime_model,{"runtime.mergeRuntimes","runtime.runtimeSummary"},set(TEXT))
FAMILIES["vision"]=(_vision,{"control.vision-pixels"},CATEGORIES)
FAMILIES["metadata"]=(_metadata,{"runtime.capability-metadata"},CATEGORIES)
FAMILIES["hermes-metadata"]=(_metadata,{"runtime.hermes-metadata"},set(TEXT)|{"concurrency","offline"})
FAMILIES["bridge-append-interrupted"]=(_bridge_interrupted,{"control.bridge-feedback","control.bridge-receipt"},{"interrupted"})
FAMILIES["diagnostic"]=(_browser_diagnostic,{"control.browser-preflight","control.browser-repair"},CATEGORIES)
FAMILIES["manual"]=(_manual,{"control.agents-manual"},{"interrupted","permissions","stale"})
FAMILIES["image-magic"]=(_image_magic,{"control.image-magic"},{"concurrency","interrupted","permissions","stale"})
FAMILIES["approval-parallel"]=(_approval_parallel,{"control.approval-policy"},{"concurrency"})
FAMILIES["cu-extra"]=(_cu_extra,{"control.cu-aliases","control.cu-verdict"},{"concurrency","interrupted","permissions","stale"})
FAMILIES["hermes-protocol"]=(_hermes_protocol,{"runtime.hermes-metadata"},{"interrupted","permissions","stale"})
FAMILIES["syncthing"]=(_syncthing,{"adapters.sync."+v for v in ("native-runtime","plan-activation","recovery","rollback","stale")},CATEGORIES)
FAMILIES["sync-metadata"]=(_syncthing,{"adapters.sync.compatibility","adapters.sync.discovery"},CATEGORIES-{"interrupted","offline"})
FAMILIES["sync-policy"]=(_syncthing,{"adapters.sync.policy"},CATEGORIES-{"interrupted","offline"})


def run(root,contracts,categories):
    from .proof_credential_guard import install
    base=Path(root).resolve();base.mkdir(parents=True,exist_ok=True);install(base);rows=[]
    for family,(builder,identities,supported) in FAMILIES.items():
        for identity in sorted(identities&set(contracts)):
            for category in categories:
                if category not in supported:continue
                scratch=base/".agent_control/proofs"/("c7d-cct-"+hashlib.sha256(identity.encode()).hexdigest()[:12]+"-"+category);scratch.mkdir(parents=True,exist_ok=False)
                row={"id":"c7d-control-completion."+identity+"."+category,"contracts":[identity],"category":category,"boundary":("Actual pinned Syncthing process/REST effects in isolated owned state; no NAS, remote peer, physical device or public release proof" if identity.startswith("adapters.sync.") else "Actual local production effects in owned state; no rendered/provider/native activation/public release proof")}
                try:
                    with _environment({"FLUXIO_CLUSTER_ROOT":str(scratch),"FLUXIO_CONTROL_PROJECT_ROOT":str(scratch),"FLUXIO_NAS_VOLUME_ROOT":str(scratch/"no-network/volume"),"FLUXIO_WINDOWS_NAS_VOLUME_MIRROR":str(scratch/"no-network/mirror"),"NEYVIA_NAS_TRANSFER_ROOT":str(scratch/"no-network/explicit-unavailable"),"NEYVIA_COORDINATOR_AUTOSTART":"0","FLUXIO_WATCHDOG_AUTOSTART":"0","NEYVIA_TOOL_AUTO_UPDATE":"0"}):
                        row.update(status="passed",detail=builder(scratch,category,identity))
                except Exception as error:row.update(status="failed",detail={"error":str(error),"type":type(error).__name__,"traceback":traceback.format_exc()[-5000:]})
                rows.append(row)
    return rows


def blocker(contract,category):
    identity=contract.get("id","")
    if identity=="control.chrome-live-action" and category in CATEGORIES:
        return {"kind":"authority_boundary","reason":"Original execute_proposal specifically controls an actual Chrome/CDP surface. Paul explicitly prohibits Chrome, Edge, and his browser in this task. Exact needed authority: permission to open/use one isolated owned Chrome/CDP browser action session (with its explicit owner action grants and selected account authorization if applicable). The separate execute_neyvia_proposal API and real Neyvia native proof do not relabel or discharge this legacy Chrome contract."}
    argument_only={
        "control.approval-policy":"evaluate classifies the explicitly supplied action, current SessionApprovals mode, trust and exact grants; it executes no action, owns no interrupted worker and uses no network",
        "control.bridge-authority":"evaluate_bridge_action reads the explicitly supplied current HostCapability and action values; it has no saved worker lifecycle and does not execute the requested command or transfer",
        "control.console-observation":"_assess_authentication/_extract_instances consume explicitly supplied readable text; browser capture, account access, permission grants and revision refresh belong to the live observation/action owners",
        "control.cu-recovery":"skip_reason_no_server formats actual unavailable discovery context and recovery commands; it starts no server, writes no receipt, owns no mutable revision, and grants no action authority",
        "control.execution-proposal":"build_action_proposal preserves explicitly supplied step, scope and branch values and selects declared verification surfaces; authority enforcement, saved scope freshness and child lifetime belong to execute_action/prepare_execution_scope",
        "control.stream-order":"StreamCoalescer._emit validates and emits caller-owned ordered events; there is no durable worker, saved revision, filesystem permission or transport in the coalescing invariant",
        "runtime.mergeRuntimes":"mergeRuntimes joins explicitly supplied catalog/matrix/policy values in one pure JavaScript invocation; runtime discovery, grants, saved revision and rendered browser interaction are different owners",
        "runtime.runtimeSummary":"runtimeSummary counts the explicitly supplied rows by tone and installed boolean; it does not discover, render, save, grant or execute any runtime",
    }
    absent={"control.approval-policy":{"interrupted","offline"},"control.bridge-authority":{"interrupted","offline"},"control.console-observation":CATEGORIES-set(TEXT),"control.cu-recovery":{"concurrency","interrupted","permissions","stale"},"control.execution-proposal":{"interrupted","permissions","offline","stale"},"control.stream-order":{"interrupted","permissions","offline","stale"},"runtime.mergeRuntimes":CATEGORIES-set(TEXT),"runtime.runtimeSummary":CATEGORIES-set(TEXT)}
    if category in absent.get(identity,set()):return {"kind":"not_applicable","reason":f"Inspected exact {identity} owner: {argument_only[identity]}. Therefore the {category} mechanism does not apply to this specific invariant."}
    local_only={"control.bridge-feedback":"build_live_review_structured_feedback_receipt appends current supplied feedback context to local JSONL; no feedback delivery transport is claimed","control.bridge-grants":"save_bridge_permission_grants serializes one explicitly selected local operator-grant file","control.bridge-receipt":"build_bridge_operation_receipt preserves supplied identity and current decisions in a plan-only local JSONL receipt; execute=False makes no sync or command call","control.bridge-snapshot":"build_dual_path_bridge_snapshot derives current local capabilities/mappings/grants without executing a bridge operation","control.console-memory":"save_project_memory merges allowlisted pointer metadata into one selected local file","control.context-bundle":"DurableContextEngine.bundle selects the current local SQLite ledger and computes cache identities without model invocation","control.context-metrics":"ContextTurnMetrics.write_receipt publishes the caller's recorded counters to a local receipt without measuring a provider","control.cu-receipt":"write_receipt compacts supplied acceptance results and publishes local exact latest mirror; rendered acceptance is a separate owner","control.execution-cleanup":"cleanup_execution_scope removes only a guarded owned local sibling isolation root","control.execution-result":"execute_action executes the selected local file/shell command under current approval/lease and native deadline; this fixture selects no runtime/provider delegation","control.execution-scope":"prepare_execution_scope creates direct/local copy/Git worktree scope from selected local source without transport","control.image-magic":"detected_image_extension reads selected local file signature bytes without model, decoder, download or endpoint","control.plan-history":"ItemStore.plan folds an explicitly selected local transcript file and current tail stamp; it never queries a provider","control.plan-limits":"record_claude/_save_claude persist only app-reported local window values; codex_windows maps explicit values and never refreshes a CLI","control.result-retention":"record_chat_run_result publishes the supplied compact final result into selected local state","control.stream-frame":"append_chat_stream serializes accepted local chunks and timestamps to selected JSONL","control.stream-tail":"last_stream_event scans explicitly selected local JSONL blocks backwards for current event type","runtime.service.installation":"_validate_installation streams explicitly selected executable/required-file hashes before process launch and performs no health/identity request","runtime.toolchain.discovery":"_release_candidate validates explicitly supplied official release metadata, and _publish_discovery saves those exact local values; upstream retrieval is a separate _check_tool transport"}
    for suffix in ("counts","git-delta","lineage","secrets","source-phase","verdict"):local_only["control.submission-"+suffix]="validate_receipt inspects the supplied incoming receipt and selected current local Git/file evidence; it never performs publication, provider execution, rendered verification or physical device capture"
    if category=="offline" and identity in local_only:return {"kind":"not_applicable","reason":f"Inspected exact {identity} owner: {local_only[identity]}. No network operation occurs at this invariant; other transport/native readiness contracts remain independently applicable."}
    if identity=="runtime.toolchain.discovery" and category=="interrupted":return {"kind":"not_applicable","reason":"_release_candidate validates a supplied parsed official-release object without an owned worker or durable effect. Discovery publication interruption is independently exercised by runtime.toolchain.cache.interrupted; this invariant asserts candidate fields and signed-release policy, not cache recovery or upstream transfer completion."}
    if identity in {"adapters.sync.compatibility","adapters.sync.discovery"} and category in {"interrupted","offline"}:return {"kind":"not_applicable","reason":f"{identity} computes current local executable SHA256 and secret-safe configuration metadata (discovery binds that read-only compatibility operation to its tool/capability manifest). It does not start or contact Syncthing, persist a worker, or execute a folder transfer. Actual native lifetime/offline behavior remains independently applicable under adapters.sync.native-runtime and the plan/recovery owners."}
    if identity=="adapters.sync.policy" and category in {"interrupted","offline"}:return {"kind":"not_applicable","reason":"The scoped policy invariant validates current explicit local allowed-root paths, ignore patterns, folder modes and versioning choices before any provider request. There is no worker/transport at those validators; actual Syncthing requests, activation, recovery and rollback are independently covered."}
    return None
