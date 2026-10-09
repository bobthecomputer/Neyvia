"""Remaining C7d local engine and harness owner observations.

Legacy planning state, file integrity and owned child execution are explicit
boundaries. These fixtures never attest model/provider authentication, rendering,
live desktop activation, publication, or enrolled credential access.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .edge_fixture_c7d_desktop import _stop_at_marker, _interrupted_write
from .edge_fixture_host_runtime import _check, _reject, _sharing, _environment

REPO = Path(__file__).resolve().parents[2]
TEXT = {"empty": "", "huge": "owned selected evidence " * 16000, "unicode": "雪 café e\u0301 العربية"}
CATEGORIES = set(TEXT) | {"permissions", "stale", "concurrency", "interrupted", "offline"}


def _legacy(root, category):
    from .constitution import AgentConstitution
    from .context_manager import ContextWindowManager
    from .engine import AutonomousEngine
    from .memory import MemoryStore
    from .persona import PersonaRegistry
    from .session_store import SessionStore
    from .skills import SkillRegistry
    from .verification import VerificationRunner
    from .checkpoints import CheckpointStore
    from .eval import summarize_runs
    text = TEXT.get(category, "owned selected planning-state evidence")
    document = root / "selected.txt"; document.write_text(text, encoding="utf-8")
    catalog = root / "skills.json"; catalog.write_text("[]")
    def engine(tokens=600):
        return AutonomousEngine(AgentConstitution(), PersonaRegistry(root / "personas.json"), ContextWindowManager(max_tokens=tokens),
            SessionStore(root / "runs"), VerificationRunner(), SkillRegistry(catalog), MemoryStore(root / "memory.json"))
    def invoke(instance, **changes):
        arguments = {"objective": "Inspect explicit owned evidence " + text[:2000], "docs":["selected.txt"],"persona":"balanced_builder",
            "iterations":2,"repo_path":root,"verify_commands":[],"project_profile":"C7d local planning proof",
            "max_handoffs":4,"max_runtime_seconds":20}
        arguments.update(changes); return instance.run(**arguments)
    if category == "permissions":
        with _sharing(document): denied = invoke(engine())
        _check(denied["status"] == "blocked" and denied["preflight_failures"], "unreadable selected document invented runnable planning state")
    if category == "interrupted":
        code = """import json,sys,threading
from pathlib import Path
from grant_agent.constitution import AgentConstitution
from grant_agent.context_manager import ContextWindowManager
from grant_agent.engine import AutonomousEngine
from grant_agent.memory import MemoryStore
from grant_agent.persona import PersonaRegistry
from grant_agent.session_store import SessionStore
from grant_agent.skills import SkillRegistry
from grant_agent.verification import VerificationRunner
from grant_agent import checkpoints
r=Path(sys.argv[1]);marker=Path(sys.argv[2]);original=checkpoints.CheckpointStore.save
def saved(*args,**kwargs):
 value=original(*args,**kwargs)
 marker.write_text(json.dumps({'checkpoint':str(value)}));threading.Event().wait(60)
 return value
checkpoints.CheckpointStore.save=saved
owner=AutonomousEngine(AgentConstitution(),PersonaRegistry(r/'personas.json'),ContextWindowManager(max_tokens=600),SessionStore(r/'runs'),VerificationRunner(),SkillRegistry(r/'skills.json'),MemoryStore(r/'memory.json'))
owner.run(objective='Actual stopped local planner',docs=['selected.txt'],persona='balanced_builder',iterations=2,repo_path=r,verify_commands=[],project_profile='C7d',max_handoffs=4,max_runtime_seconds=20)
"""
        stopped = _stop_at_marker(root,"legacy-checkpoint",code)
        checkpoint = Path(stopped["observed"]["checkpoint"])
        _check(checkpoint.is_file(), "stopped planner lost actual durable checkpoint")
    first = invoke(engine(), iterations=1, parallel_agents=3, merge_policy="consensus")
    state_path = Path(first["session_path"]) / "state.json"; state = json.loads(state_path.read_text(encoding="utf-8"))
    _check(first["status"] == "ok" and state["worker_merge_events"] and len(state["completed_steps"]) >= 3, "planning-state engine omitted actual parallel merge")
    checkpoint = CheckpointStore.latest(Path(first["session_path"])); _check(checkpoint is not None, "planner omitted recoverable checkpoint")
    resumed = invoke(engine(), docs=[], iterations=1, resume_from_session_id=Path(first["session_path"]).name, resume_from_checkpoint_path=str(checkpoint))
    _check(first["session_path"].split(os.sep)[-1] in resumed["session_lineage"] and resumed["status"] == "ok", "checkpoint resume lost actual session lineage")
    if category == "stale":
        document.write_text("replacement explicit evidence", encoding="utf-8")
        replaced = invoke(engine(), iterations=1)
        _check(replaced["readable_docs"] == 1 and json.loads((Path(replaced["session_path"])/"docs_evidence.json").read_text(encoding="utf-8"))[0]["chars"] == len("replacement explicit evidence"), "new run reused stale selected document")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            parallel = list(pool.map(lambda _: invoke(engine(), iterations=1), range(8)))
        _check(len({r["session_path"] for r in parallel}) == 8 and all(r["status"] == "ok" for r in parallel), "parallel planners collided or lost their own runs")
    rolled = invoke(engine(50), iterations=8)
    _check(rolled["handoff_packets"] and rolled["checkpoints"] and rolled["vibe_next_steps"] and Path(rolled["report_path"]).is_file(), "bounded context rollover lost actual handoff/checkpoint artifacts")
    measured = invoke(engine(), iterations=1, verify_commands=[f'"{sys.executable}" -c "print(21)"',f'"{sys.executable}" -c "raise SystemExit(1)"'])
    _check(len(measured["verification_failures"]) == 1, "actual failed child command disappeared from run state")
    summary = summarize_runs(root / "runs")
    _check(summary["verification_failures"] == 1 and summary["sessions_with_handoff"] >= 1 and summary["runs_with_checkpoints"] >= 1, "aggregation changed actual durable session facts")
    if category == "permissions":
        with _sharing(state_path): _reject(lambda: summarize_runs(root / "runs"), (PermissionError,))
    return {"sessions":summary["total_sessions"],"verificationFailures":summary["verification_failures"],"checkpoint":str(checkpoint),"localPlanningStateOnly":True,"modelExecutionProof":False}


def _ecosystem(root, category, kind):
    from .ecosystem_fabric import NeyviaEcosystemFabric
    from . import edge_fixture_engine as prior
    owner = NeyviaEcosystemFabric(root)
    if category == "interrupted":
        expressions = {
            "account": "owner.register_communication_account({'accountId':'stopped','route':'file-import','permissions':['read'],'configuration':{}})",
            "capture": "owner.capture_presentation_content({'source':'file:///owned','userInitiated':True,'content':'stopped capture'})",
            "capsule": "owner.build_share_capsule({'content':{'text':'stopped export'}})",
            "experiment": "owner.create_experiment({'title':'Stopped experiment','hypothesis':'Actual committed observation'})",
        }
        code = """import json,sys,threading
from pathlib import Path
from grant_agent import proofs_b_engine
from grant_agent.ecosystem_fabric import NeyviaEcosystemFabric
r=Path(sys.argv[1]);marker=Path(sys.argv[2]);kind=sys.argv[3];original=proofs_b_engine.check
def checked(identity,args,result):
 original(identity,args,result)
 if identity=='proofs-b.engine.'+kind:
  marker.write_text(json.dumps(result));threading.Event().wait(60)
proofs_b_engine.check=checked
owner=NeyviaEcosystemFabric(r)
""" + expressions[kind]
        stopped = _stop_at_marker(root,kind+"-committed",code,kind)
        observed = stopped["observed"]
        if kind == "capsule":
            _check(json.loads(Path(observed["recordPath"]).read_text(encoding="utf-8")) == {k:v for k,v in observed.items() if k!="recordPath"}
                   and observed["transportState"] == "prepared-not-sent", "stopped export lost durable preparation or invented send")
        else:
            with sqlite3.connect(owner.database_path) as db:
                table = {"account":"communication_accounts","capture":"presentation_captures","experiment":"experiments"}[kind]
                _check(db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0] == 1, "stopped owner lost acknowledged durable mutation")
        return {"stoppedAfterRealCommitBeforeDelivery": True, "childExit":stopped["returnCode"]}
    if kind == "experiment" and category == "permissions":
        item=owner.create_experiment({"title":"Keeper","hypothesis":"unchanged"})
        before=owner.database_path.read_bytes()
        with _sharing(owner.database_path):
            _reject(lambda:owner.record_experiment_observation({"experimentId":item["experimentId"],"observation":"denied"}),(sqlite3.Error, OSError))
        _check(owner.database_path.read_bytes()==before,"denied journal write changed keeper")
        return {"nativeSharingDenied":True,"journalEntries":len(owner.experiment_snapshot()["experiments"][0]["journal"])}
    if kind in {"capture","capsule"} and category == "stale":
        if kind == "capture":
            first=owner.capture_presentation_content({"source":"file:///owned","userInitiated":True,"content":"original"})
            second=owner.capture_presentation_content({"source":"file:///owned","userInitiated":True,"content":"replacement"})
            with sqlite3.connect(owner.database_path) as db:
                rows=db.execute("SELECT content_sha256 FROM presentation_captures").fetchall()
            _check(first["contentSha256"]!=second["contentSha256"] and {r[0] for r in rows}=={first["contentSha256"],second["contentSha256"]},"new explicit capture overwrote original lineage")
        else:
            first=owner.build_share_capsule({"content":{"text":"original"}}); keeper=Path(first["recordPath"]).read_bytes()
            second=owner.build_share_capsule({"content":{"text":"replacement"}})
            _check(first["capsuleId"]!=second["capsuleId"] and Path(first["recordPath"]).read_bytes()==keeper and second["content"]["text"]=="replacement","new capsule reused stale content or destroyed keeper")
        return {"originalAndReplacementRetained":True}
    if kind == "authorization":
        item=owner.create_experiment({"title":"Recorded scope","hypothesis":"Plan only","authorizationContext":"explicit owned scope"})
        payload={"experimentId":item["experimentId"],"tier":"act","target":"owned target"}
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(lambda _:owner.plan_experiment_action(payload),range(8)))
            _check(all(r["executable"] is False and r["approval"]=="per-action" for r in rows),"concurrent plan widened authority")
        elif category == "stale":
            first=owner.plan_experiment_action(payload)
            with sqlite3.connect(owner.database_path) as db:
                db.execute("UPDATE experiments SET authorization_context='' WHERE experiment_id=?",(item["experimentId"],));db.commit()
            _reject(lambda:owner.plan_experiment_action(payload),(ValueError,PermissionError))
            _check(first["executable"] is False,"prior proposal executed")
        return {"actExecuted":False,"freshRecordedScopeRequired":True}
    return getattr(prior,"_"+kind)(root,category)


def _recorder_denied(root, category):
    from .flight_recorder import MissionFlightRecorder, read_flight_recorder_events
    owner=MissionFlightRecorder(root,"owned")
    owner.append_event(kind="keeper",message="original")
    before=owner.events_path.read_bytes()
    with _sharing(owner.events_path):
        _reject(lambda:owner.append_event(kind="denied",message="never committed"),(OSError,))
        _reject(lambda:read_flight_recorder_events(owner.events_path),(OSError,))
    _check(owner.events_path.read_bytes()==before and len(read_flight_recorder_events(owner.events_path))==1,"denied recorder changed actual event log")
    return {"deniedAppendAndRead":True,"keeperBytes":len(before)}


def _skill_rows(root, category):
    from .skill_library import SkillLibrary
    owner=object.__new__(SkillLibrary); target=root/"explicit-selected-skills.json"
    values=[{"id":"keeper","description":"雪"}];target.write_text(json.dumps(values))
    if category=="interrupted":
        _interrupted_write(target,'[{"id":"partial')
        _check(owner._load_skill_rows(target)==[],"partial child write admitted a skill record")
    elif category=="stale":
        first=owner._load_skill_rows(target); values=[{"id":"replacement"}];target.write_text(json.dumps(values))
        _check(owner._load_skill_rows(target)==values and first!=values,"loader reused old skill rows")
    elif category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(lambda _:owner._load_skill_rows(target),range(16)))
        _check(all(r==values for r in rows),"independent skill readers changed selected rows")
    return {"explicitSelectedPathOnly":True,"loaded":len(owner._load_skill_rows(target))}


def _verdict(root, category):
    from .efficient_workflow import verification_result
    target=root/"artifact.txt";target.write_bytes(b"original owned evidence")
    encoded=json.dumps({"verdict":"pass","evidence":[{"path":"artifact.txt","sha256":hashlib.sha256(target.read_bytes()).hexdigest()}]})
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(lambda _:verification_result(encoded,root=root),range(16)))
        _check(all(r["status"]=="completed" for r in rows),"parallel actual digest readers changed verdict")
    else:
        _interrupted_write(target,"partial replacement")
        observed=verification_result(encoded,root=root)
        _check(observed["status"]!="completed" and any(r["status"]!="matched" for r in observed["verification"]["artifactChecks"]),"partial artifact retained old pass")
    return {"actualArtifactInspected":True,"renderedProof":False}


def _workflow(root, category):
    from .efficient_workflow import build_efficient_workflow
    from .agent_prompt_library import save_prompt_library, _library_path
    value=TEXT.get(category,"Inspect explicit owned evidence")
    if category in {"empty","huge"}:
        _reject(lambda:build_efficient_workflow(root,{"objective":value}),(ValueError,))
        value="Valid bounded selected task"
    first=build_efficient_workflow(root,{"objective":value})
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(lambda _:build_efficient_workflow(root,{"objective":value}),range(8)))
        _check(len({t["id"] for r in rows for t in r["tasks"]})==32,"concurrent plans collided task identity")
    elif category=="stale":
        save_prompt_library(root,{"expectedRevision":0,"roles":{"reader":{"instructions":"Fresh explicit reader instruction"}}})
        second=build_efficient_workflow(root,{"objective":value})
        _check("Fresh explicit" in second["tasks"][0]["teamContract"]["handback"]["systemPrompt"] and "Fresh explicit" not in first["tasks"][0]["teamContract"]["handback"]["systemPrompt"],"preparation reused old role prompt")
    elif category=="interrupted":
        target=_library_path(root);target.parent.mkdir(parents=True,exist_ok=True)
        _interrupted_write(target,'{"revision":')
        _reject(lambda:build_efficient_workflow(root,{"objective":value}),(ValueError,RuntimeError))
    elif category=="permissions":
        _reject(lambda:build_efficient_workflow(root,{"objective":value,"readOnly":"false"}),(ValueError,))
        _check(all(not t["teamContract"]["authority"]["allowWorkspaceMutation"] for t in first["tasks"]),"read-only plan widened role authority")
    return {"taskRoles":[t["role"] for t in first["tasks"]],"preparedOnly":True}


def _mcp(root,category):
    from .neyvia_mcp_stdio import CompactNeyviaMCPServer
    from .proofs_b_engine import _fixture_root
    text=TEXT.get(category,"Owned selected input")
    target=root/"selected.txt";target.write_text(text,encoding="utf-8")
    def server():return CompactNeyviaMCPServer(_fixture_root(root),read_only=True,session_id="c7d-owned")
    def call(owner,name,args):return owner.handle({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":name,"arguments":args}})
    owner=server();args={"toolId":"workspace.read","arguments":{"path":"selected.txt"}}
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: reads=list(pool.map(lambda _:call(server(),"neyvia.native.call",args),range(8)))
        _check(all("error" not in r for r in reads),"independent MCP read projection failed")
    elif category=="stale":
        call(owner,"neyvia.native.call",args);target.write_text("Fresh selected evidence",encoding="utf-8")
        _check("Fresh selected evidence" in json.dumps(call(owner,"neyvia.native.call",args)),"MCP read reused stale file")
    elif category=="permissions":
        with _sharing(target):
            denied=call(owner,"neyvia.native.call",args)
        _check("error" in denied or "error" in json.dumps(denied).lower(),"denied MCP file returned successful evidence")
    nested=call(owner,"model.tools.run",{"calls":[{"callTarget":"neyvia.workspace.browser","arguments":{"operation":"click"}}]})
    write=call(owner,"neyvia.native.call",{"toolId":"context.compact","arguments":{}})
    question=call(owner,"neyvia.ask_user",{"question":"Owned selected question","options":["Text","JSON"]})
    paused=call(owner,"neyvia.native.call",args)
    _check(nested["error"]["code"]==-32003 and "approval_required" in json.dumps(write) and "pending" in json.dumps(question) and paused["error"]["code"]==-32003,"MCP bypassed read-only or unanswered-question gate")
    return {"nestedMutationRefused":True,"pendingQuestionPauses":True,"actualRenderedBrowser":False}


def _chat(root,category,kind):
    from .encrypted_chat import EncryptedChatService
    private=root/"opaque-local-paths";private.mkdir();opaque=private/"opaque-handle";opaque.touch();store=private/"store";store.mkdir()
    account={"accountId":"owned","userId":"@owned:local.invalid","deviceId":"OWNEDLOCAL","credentialsPath":str(opaque),"storePath":str(store),"rooms":[{"roomId":"!owned:local.invalid","agentWritable":True,"agentReadable":True,"agentAttachments":True}]}
    config={"policy":{"secretRoot":str(private),"accounts":[account]}}
    path=root/"public-path-config.json";path.write_text(json.dumps(config))
    owner=EncryptedChatService(root,config_path=path)
    catalog=owner.account_catalog();room=catalog["accounts"][0]["rooms"][0]["roomRef"]
    if kind=="chat-public":
        if category=="stale":
            owner.config["policy"]["accounts"][0]["rooms"]=[]
            _check(owner.account_catalog()["summary"]["rooms"]==0,"public catalog reused removed room")
        elif category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(lambda _:owner.account_catalog(),range(16)))
            _check(all(r==catalog for r in rows),"public concurrent projection changed identities")
        elif category in TEXT:
            owner.config["policy"]["accounts"][0]["label"]=TEXT[category]
            catalog=owner.account_catalog()
        encoded=json.dumps(catalog)
        _check(all(v not in encoded for v in [account["userId"],account["deviceId"],str(opaque),str(store),account["rooms"][0]["roomId"]]),"private chat identity escaped public projection")
        return {"rooms":catalog["summary"]["rooms"],"opaqueHandleNeverRead":True}
    target=root/"selected.txt";target.write_text(TEXT.get(category,"Selected owned artifact"),encoding="utf-8")
    def plan():return owner.build_message_plan(account_id="owned",room_ref=room,actor="Owned fixture",message=TEXT.get(category,"Owned public message"),attachments=[target],format="markdown")
    if category=="huge":
        _reject(plan,(ValueError,))
        first=owner.build_message_plan(account_id="owned",room_ref=room,actor="Owned fixture",message="Bounded selected artifact",attachments=[target])
        _check(first["attachments"][0]["sha256"]==hashlib.sha256(target.read_bytes()).hexdigest(),"huge selected attachment changed digest")
        return {"oversizedMessageRefused":True,"actualAttachmentBytes":target.stat().st_size}
    if category=="permissions":
        with _sharing(target):_reject(plan,(OSError,))
        owner.config["policy"]["accounts"][0]["rooms"][0]["agentWritable"]=False
        _reject(plan,(PermissionError,));return {"deniedFileAndRoomRefused":True}
    first=plan()
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(lambda _:plan(),range(16)))
        _check(all(r["attachments"][0]["sha256"]==hashlib.sha256(target.read_bytes()).hexdigest() for r in rows),"parallel plans changed attachment hash")
    elif category=="stale":
        target.write_text("Fresh explicit artifact",encoding="utf-8");second=plan()
        _check(first["attachments"][0]["sha256"]!=second["attachments"][0]["sha256"],"new chat plan reused old artifact digest")
    elif category=="interrupted":
        _interrupted_write(target,"stopped changed artifact")
        _check(plan()["attachments"][0]["sha256"]==hashlib.sha256(target.read_bytes()).hexdigest()!=first["attachments"][0]["sha256"],"partially written selected artifact borrowed old plan hash")
    _check(owner.send(first)["status"]=="approval_required","preparation sent unapproved chat")
    return {"attachments":1,"approvalRequired":True,"matrixRuntimeProof":False}


def _watchdog(root,category,enforce=False):
    from datetime import datetime,timedelta,timezone
    from .mission_control import ControlRoomStore
    from .mission_watchdog import evaluate_fake_running_mission,enforce_fake_running_missions
    from .mission_receipts import load_mission_receipts
    from .models import DelegatedRuntimeSession,MissionEvent
    now=datetime.now(timezone.utc);store=ControlRoomStore(root);workspace=store.load_workspaces()[0]
    mission=store.create_mission(workspace_id=workspace.workspace_id,runtime_id="hermes",objective=TEXT.get(category,"Inspect owned local evidence") or "Empty selected output",success_checks=["Selected output exists"],mode="Autopilot",verification_commands=[],max_runtime_seconds=12000)
    mission.created_at=(now-timedelta(hours=4)).isoformat();mission.state.status="running";mission.proof.changed_files=[];mission.proof.artifacts=[]
    mission.delegated_runtime_sessions=[DelegatedRuntimeSession(delegated_id="owned-idle",runtime_id="hermes",launch_command="not-launched",mission_id=mission.mission_id,status="queued",pid=0)]
    stats={mission.mission_id:{"missingOutputStreak":3,"missingOutputEventCount":3,"latestEvents":[{"text":TEXT.get(category,"Missing explicit output")}],"artifactGateStatus":"missing_required_output"}}
    def evaluate():return evaluate_fake_running_mission(mission,stats=stats,now=now,threshold_minutes=120)
    _check(evaluate() is not None,"old workerless mission escaped explicit evidence diagnosis")
    if not enforce:
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(lambda _:evaluate(),range(16)))
            _check(all(r==rows[0] for r in rows),"concurrent evaluator changed supplied evidence")
        elif category=="stale":
            mission.proof.changed_files=["fresh-owned-result.txt"]
            _check(evaluate() is None,"fresh evidence inherited stale workerless diagnosis")
            mission.proof.changed_files=[];mission.created_at=now.isoformat()
            _check(evaluate() is None,"new mission inherited old elapsed age")
        return {"actualCurrentMissionEvaluated":True,"supervisorStarted":False}
    store.save_missions([mission])
    for index in range(3):store.append_event(MissionEvent(mission_id=mission.mission_id,kind="mission.output-missing",message="Absent explicit output",metadata={"artifactGateStatus":"missing_required_output","attempt":index}))
    log=root/".agent_control/mission_async"/(mission.mission_id+".log");log.parent.mkdir(parents=True,exist_ok=True);log.write_text(TEXT.get(category,"Actual missing-output diagnosis"),encoding="utf-8")
    def apply():return enforce_fake_running_missions(root=root,store=ControlRoomStore(root),now=now)
    if category=="permissions":
        with _sharing(log): rows=apply()
        receipts=load_mission_receipts(root,mission_id=mission.mission_id)
        _check(rows and receipts[0]["last_stdout"]=="","denied diagnostic log invented stdout evidence")
    elif category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(lambda _:apply(),range(8)))
        rows=[r for batch in results for r in batch]
    elif category=="interrupted":
        code="\n".join([
            "import json,sys,threading",
            "from pathlib import Path",
            "from grant_agent.mission_control import ControlRoomStore",
            "from grant_agent.mission_watchdog import enforce_fake_running_missions",
            "r=Path(sys.argv[1]);marker=Path(sys.argv[2]);owner=ControlRoomStore(r);original=owner.save_missions",
            "def saved(missions):",
            " original(missions);marker.write_text(json.dumps({'statuses':[m.state.status for m in missions]}));threading.Event().wait(60)",
            "owner.save_missions=saved",
            "enforce_fake_running_missions(root=r,store=owner)",
        ])
        stopped=_stop_at_marker(root,"watchdog-durable",code)
        _check(stopped["observed"]["statuses"]==["blocked"] and not apply(),"stopped enforcement revived a blocked mission")
        rows=[]
    elif category=="stale":
        rows=apply();_check(rows and not apply(),"new enforcement reused old running state")
    else:rows=apply()
    receipts=load_mission_receipts(root,mission_id=mission.mission_id);saved=store.load_missions()[0]
    _check(saved.state.status=="blocked" and receipts and all(r["receiptId"] in {p["receipt_id"] for p in receipts} for r in rows),"enforcement lost durable blocked state or returned missing receipt")
    return {"blockedMission":True,"durableReceipts":len(receipts),"supervisorStarted":False}


def _jobs(root,category,kind):
    from .harness_jobs import HarnessJobStore
    owner=HarnessJobStore(root,max_open_jobs=8);request={"message":TEXT.get(category,"owned durable request"),"harnessId":"neyvia-agent","workspacePath":str(root)}
    first=owner.create(request,job_id="harness-job-owned");target=owner.job_path(first["id"])
    if category=="permissions":
        before=target.read_bytes()
        with _sharing(target):
            action=(lambda:owner.create(request,job_id=first["id"])) if kind=="identity" else (lambda:owner.finish(first["id"],result={"status":"completed"})) if kind=="lifecycle" else (lambda:owner.load(first["id"],reconcile=False))
            _reject(action,(OSError,RuntimeError))
        _check(target.read_bytes()==before,"denied durable job owner changed saved request/state")
    elif category=="interrupted":
        _interrupted_write(target,'{"schema":"neyvia.harness_job.v1",')
        _reject(lambda:owner.load(first["id"],reconcile=False),(RuntimeError,))
        _check(owner.capacity()["unreadableJobs"]==1,"partial job receipt freed unresolved admission")
    elif kind=="identity":
        before=target.read_bytes()
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:owner.create(request,job_id=first["id"]),range(16)))
            _check(all(r["id"]==first["id"] for r in rows),"same exact concurrent request lost identity")
        _reject(lambda:owner.create({**request,"message":"changed"},job_id=first["id"]),(ValueError,RuntimeError))
        _check(target.read_bytes()==before,"identity conflict changed request bytes")
    elif kind=="lifecycle":
        owner.finish(first["id"],result={"status":"blocked","detail":"operator boundary"});before=target.read_bytes()
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:owner.finish(first["id"],result={"status":"completed"}),range(16)))
        else:owner.mark_started(first["id"],pid=os.getpid());owner.finish(first["id"],result={"status":"completed"})
        _check(target.read_bytes()==before,"late worker overwrote durable blocker")
        owner.cancel(first["id"]);_check(owner.load(first["id"],reconcile=False)["status"]=="cancelled","operator cleanup failed")
    else:
        owner.mark_started(first["id"],pid=os.getpid());owner.finish(first["id"],result={"status":"completed","message":request["message"]})
        before=target.read_bytes()
        with ThreadPoolExecutor(max_workers=8 if category=="concurrency" else 1) as pool:rows=list(pool.map(lambda _:owner.load(first["id"],reconcile=False),range(16 if category=="concurrency" else 1)))
        _check(all(r["metrics"]["terminal"] and [p["phase"] for p in r["timeline"]]==["queued","running","completed"] for r in rows) and target.read_bytes()==before,"read projection changed terminal evidence")
    return {"requestIdentity":first["id"],"actualDurableFile":str(target),"providerLaunched":False}


def _capacity(root,category,kind):
    from .harness_jobs import HarnessJobStore
    from .harness_execution_capacity import HarnessExecutionCapacity
    from .harness_job_worker import _mark_waiting_for_execution_capacity
    message=TEXT.get(category,"Owned local queue")
    if kind=="admission" and category=="concurrency":
        from .edge_fixture_control import _admission
        _admission(root)
        return {"actualEightWayAdmission":True,"limit":3}
    if kind=="policy":
        if category in TEXT:
            _reject(lambda:HarnessJobStore(root,max_open_jobs=message),(ValueError,TypeError))
        wide=HarnessJobStore(root,max_open_jobs=8);_check(wide.capacity()["maxOpenJobs"]==8,"explicit initial limit lost")
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(lambda limit:HarnessJobStore(root,max_open_jobs=limit).capacity(),[7,6,5,4,3,2,1,8]))
        else:HarnessJobStore(root,max_open_jobs=1).capacity()
        _check(wide.capacity()["maxOpenJobs"]==1,"old operator limit expanded tightened policy")
        if category=="permissions":
            before=wide._admission_policy_path().read_bytes()
            with _sharing(wide._admission_policy_path()):_reject(wide.capacity,(RuntimeError,OSError))
            _check(wide._admission_policy_path().read_bytes()==before,"denied policy changed retained hard limit")
        if category=="interrupted":
            _interrupted_write(wide._admission_policy_path(),'{"schema":"neyvia.harness_admission_policy.v1",')
            _reject(wide.capacity,(RuntimeError,))
        return {"tightenedLimit":1,"malformedPolicyRefusesAdmission":category=="interrupted"}
    owner=HarnessJobStore(root,max_open_jobs=3);first=owner.create({"message":message,"harnessId":"neyvia-agent"})["id"]
    if kind=="admission":
        path=owner.job_path(first)
        if category=="interrupted":_interrupted_write(path,'{"id":')
        if category=="permissions":
            with _sharing(path):snapshot=owner.capacity();_check(snapshot["unreadableJobs"]==1,"denied receipt freed admission")
        else:
            if category=="stale":owner.finish(first,result={"status":"completed"});_check(owner.capacity()["openJobs"]==0,"old open status concealed terminal state")
            snapshot=owner.capacity()
        _check(snapshot["maxOpenJobs"]==3 and snapshot["availableSlots"]==max(0,3-snapshot["openJobs"]),"admission pressure differs from durable jobs")
        return {"openJobs":snapshot["openJobs"],"unreadableJobs":snapshot["unreadableJobs"]}
    second=owner.create({"message":message+" second","harnessId":"neyvia-agent"})["id"]
    for job in (first,second):owner.mark_started(job,pid=os.getpid());_mark_waiting_for_execution_capacity(owner,job,max_running_jobs=1)
    scheduler=HarnessExecutionCapacity(root,max_running_jobs=1)
    if category=="permissions":
        scheduler.effective_limit();before=scheduler._policy_path().read_bytes()
        with _sharing(scheduler._policy_path()):_reject(lambda:scheduler.try_acquire(first),(OSError,RuntimeError))
        _check(scheduler._policy_path().read_bytes()==before,"denied scheduler changed policy")
        return {"nativePolicyReadDenied":True}
    if category=="interrupted":
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.harness_execution_capacity import HarnessExecutionCapacity","r=Path(sys.argv[1]);marker=Path(sys.argv[2]);owner=HarnessExecutionCapacity(r,max_running_jobs=1)","lease,snapshot=owner.try_acquire(sys.argv[3]);assert lease is not None","marker.write_text(json.dumps({'slot':lease.slot,'snapshot':snapshot}));threading.Event().wait(60)"])
        stopped=_stop_at_marker(root,"execution-lease",code,first)
        _check(stopped["observed"]["slot"]==1,"stopped worker never acquired real OS slot")
    lease,snapshot=scheduler.try_acquire(first);_check(lease is not None and lease.slot==1,"oldest owned waiter could not acquire available OS slot")
    try:
        if category=="concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:scheduler.try_acquire(second),range(16)))
            _check(all(other is None for other,_ in rows),"parallel contender exceeded held execution limit")
        else:
            other,blocked=scheduler.try_acquire(second);_check(other is None,"newer waiter bypassed held lease/FIFO")
        if category=="stale":
            _check(HarnessExecutionCapacity(root,max_running_jobs=8).effective_limit()==1,"fresh instance widened retained execution policy")
    finally:lease.release()
    owner.finish(first,result={"status":"completed"});lease,snapshot=scheduler.try_acquire(second)
    _check(lease is not None,"released OS slot could not dispatch next waiter");lease.release()
    return {"actualSlot":1,"fifoAndHeldLeaseEnforced":True,"providerLaunched":False}


def _lock(root,category):
    from .harness_jobs import _exclusive_job_lock,_job_guard_path
    from .edge_fixture_control import _interrupted
    if category=="stale":
        _interrupted(root,"lock-recovery")
        return {"actualKilledOwnerRecovered":True}
    target=root/"guarded.json";target.write_text("keeper")
    if category in TEXT:
        marker=target.with_suffix(".json.lock");marker.write_text(TEXT[category],encoding="utf-8")
        before=marker.read_bytes()
        def enter():
            with _exclusive_job_lock(target,timeout_seconds=.1):raise AssertionError("uncertain compatibility fence stolen")
        _reject(enter,(RuntimeError,));_check(marker.read_bytes()==before,"uncertain marker overwritten")
    elif category=="permissions":
        guard=_job_guard_path(target);guard.touch(exist_ok=True)
        with _sharing(guard):
            def enter():
                with _exclusive_job_lock(target,timeout_seconds=.2):pass
            _reject(enter,(OSError,RuntimeError))
        _check(target.read_text(encoding="utf-8")=="keeper","denied OS guard changed protected effect")
    elif category=="concurrency":
        trace=root/"serialized.jsonl"
        def mutate(index):
            with _exclusive_job_lock(target,timeout_seconds=10):
                previous=json.loads(target.read_text(encoding="utf-8")) if target.read_text(encoding="utf-8")!="keeper" else []
                previous.append(index);target.write_text(json.dumps(previous))
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(mutate,range(16)))
        _check(set(json.loads(target.read_text(encoding="utf-8")))==set(range(16)),"OS-guarded read-modify-write lost effects")
    return {"actualOSOwnershipBoundary":True}


def _budget(root,category):
    from .harness_jobs import HarnessJobStore
    from . import harness_job_worker as worker
    owner=HarnessJobStore(root);budget={"maxRuntimeSeconds":30,"maxTokens":700,"maxCostUsd":.75}
    request={"message":TEXT.get(category,"Owned budget"),"budget":budget};job=owner.create(request)["id"];owner.mark_started(job,pid=os.getpid())
    if category=="permissions":
        path=owner.job_path(job);before=path.read_bytes()
        with _sharing(path):_reject(lambda:worker._arm_runtime_budget(owner,job,request,max_runtime_seconds=30),(OSError,RuntimeError))
        _check(path.read_bytes()==before,"denied budget arming changed durable state")
    remaining=worker._arm_runtime_budget(owner,job,request,max_runtime_seconds=30)
    _check(remaining is not None and 0<=remaining<=30,"arming forgot actual elapsed startup time")
    if category=="interrupted":
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.harness_jobs import HarnessJobStore","from grant_agent.harness_job_worker import _claim_runtime_budget_exhaustion","r=Path(sys.argv[1]);marker=Path(sys.argv[2]);owner=HarnessJobStore(r)","claimed=_claim_runtime_budget_exhaustion(owner,sys.argv[3],max_runtime_seconds=30,exhausted_at='owned stopped expiry')","marker.write_text(json.dumps({'claimed':claimed}));threading.Event().wait(60)"])
        stopped=_stop_at_marker(root,"budget-expiry",code,job);_check(stopped["observed"]["claimed"],"stopped child did not establish durable expiry")
    elif category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(lambda _:worker._claim_runtime_budget_exhaustion(owner,job,max_runtime_seconds=30,exhausted_at="owned expiry"),range(16)))
        _check(rows.count(True)==1,"multiple expiry callers claimed one active budget")
    elif category=="stale":
        worker._settle_runtime_budget(owner,job,status="released",outcome="normal-finish");owner.finish(job,result={"status":"completed"})
        _check(not worker._claim_runtime_budget_exhaustion(owner,job,max_runtime_seconds=30,exhausted_at="late"),"late deadline rewrote terminal completion")
        return {"lateDeadlineRefused":True}
    else:_check(worker._claim_runtime_budget_exhaustion(owner,job,max_runtime_seconds=30,exhausted_at="owned expiry"),"actual active expiry not claimed")
    owner.finish(job,result={"status":"completed","late":True});saved=owner.load(job,reconcile=False)
    _check(saved["status"]=="cancelled" and saved["budget"]["status"]=="exhausted" and saved["budget"]["maxTokens"]==700 and saved["budget"]["maxCostUsd"]==.75,"late success erased expiry or other budget dimensions")
    return {"durableExpiryWon":True,"budgetDimensionsRetained":True,"providerLaunched":False}


def _registry(root,category,kind):
    from . import harness_registry as owner
    profile={"id":"owned","harnessId":"neyvia-agent","model":"owned-model","baseUrl":"http://127.0.0.1:48749/v1","credentialEnv":"C7D_OWNED_SENTINEL","label":TEXT.get(category,"Owned public route"),"secret":"generated-noncredential"}
    saved=owner.save_harness_profile(root,profile);path=root/owner.HARNESS_PROFILE_RELATIVE_PATH
    if kind=="instruction":
        first=owner.save_harness_instruction(root,"AGENTS.md","keeper-雪")
        if category=="interrupted":
            code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.harness_registry import save_harness_instruction","r=Path(sys.argv[1]);marker=Path(sys.argv[2])","result=save_harness_instruction(r,'AGENTS.md','actual stopped replacement')","marker.write_text(json.dumps(result));threading.Event().wait(60)"])
            stopped=_stop_at_marker(root,"instruction-published",code);result=stopped["observed"]
            _check(Path(result["backupPath"]).read_text(encoding="utf-8")=="keeper-雪\n" and Path(result["path"]).read_text(encoding="utf-8")=="actual stopped replacement\n","stopped instruction owner lost selected effect or keeper")
        else:
            result=owner.save_harness_instruction(root,"AGENTS.md","fresh selected instruction")
            _check(owner.read_harness_instruction(root,"AGENTS.md")["content"]=="fresh selected instruction\n" and Path(result["backupPath"]).read_text(encoding="utf-8")=="keeper-雪\n","replaced instruction lost fresh bytes or backup")
        return {"recoverableInstruction":True,"providerLaunched":False}
    if category=="permissions":
        before=path.read_bytes()
        with _sharing(path):
            if kind=="public-profile":_reject(lambda:owner.save_harness_profile(root,{**profile,"model":"denied"}),(OSError,))
            else:_check(owner.harness_gateway_environment(root,"neyvia-agent","owned",{"C7D_OWNED_SENTINEL":"generated-noncredential"})=={},"denied profile fabricated gateway environment")
        _check(path.read_bytes()==before,"denied public route changed saved projection")
    elif category=="interrupted":
        if kind=="gateway":
            _interrupted_write(path,'{"schema":"fluxio.harness_profiles.v1",')
            _check(owner.harness_gateway_environment(root,"neyvia-agent","owned",{"C7D_OWNED_SENTINEL":"generated-noncredential"})=={} and owner._load_profiles(root).get("recoveryWarning"),"partial producer profile invented gateway route")
            return {"partialProfileRefusesGateway":True,"recoveryCopyPreserved":True}
        code="\n".join(["import json,sys,threading","from pathlib import Path","from grant_agent.harness_registry import save_harness_profile","r=Path(sys.argv[1]);marker=Path(sys.argv[2]);original=Path.replace","def published(self,target):"," result=original(self,target)"," if Path(target).name=='harness_profiles.json':marker.write_text(json.dumps({'published':str(target)}));threading.Event().wait(60)"," return result","Path.replace=published","save_harness_profile(r,{'id':'owned','harnessId':'neyvia-agent','model':'stopped-published'})"])
        _stop_at_marker(root,"profile-published",code)
        _check(owner.resolve_harness_profile(root,"neyvia-agent","owned")["model"]=="stopped-published","killed profile writer lost atomic published selection")
    elif category=="stale":
        owner.save_harness_profile(root,{**profile,"model":"fresh-model"})
        _check(owner.resolve_harness_profile(root,"neyvia-agent","owned")["model"]=="fresh-model" and owner.harness_gateway_environment(root,"neyvia-agent","owned",{"C7D_OWNED_SENTINEL":"generated-noncredential"})["FLUXIO_HARNESS_MODEL"]=="fresh-model","fresh profile reader reused old model")
    elif category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:owner.harness_gateway_environment(root,"neyvia-agent","owned",{"C7D_OWNED_SENTINEL":"generated-noncredential"}),range(16)))
        _check(all(r==rows[0] for r in rows),"parallel gateway projection changed explicit auth mapping")
    if kind=="gateway" and category not in {"permissions","stale"}:
        env=owner.harness_gateway_environment(root,"neyvia-agent","owned",{"C7D_OWNED_SENTINEL":"generated-noncredential"})
        _check(env["FLUXIO_HARNESS_MODEL"]=="owned-model" and env["OPENAI_API_KEY"]=="generated-noncredential" and env["OPENAI_BASE_URL"]=="http://127.0.0.1:48749/v1","gateway lost explicit public route or in-memory sentinel mapping")
    _check("generated-noncredential" not in path.read_text(encoding="utf-8"),"public profile persisted input secret")
    return {"publicProfileOnly":True,"credentialFilesRead":False,"providerContacted":False}


def _catalog(root,category):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    managed=root/"managed-runtime";(managed/"bin").mkdir(parents=True);home=root/"home";home.mkdir()
    (root/"selected-status.txt").write_text(TEXT.get(category,"Supplied unconfigured runtime status"),encoding="utf-8")
    code="\n".join([
        "import json,sys,os",
        "from pathlib import Path",
        "from concurrent.futures import ThreadPoolExecutor",
        "from grant_agent.proof_credential_guard import install",
        "from grant_agent.harness_registry import HARNESS_SPECS,build_harness_catalog,save_harness_profile,HARNESS_PROFILE_RELATIVE_PATH",
        "r=Path(sys.argv[1]);category=sys.argv[2];install(r)",
        "def deny(event,args):",
        " if event in {'socket.connect','socket.getaddrinfo'}:raise OSError('owned offline catalog denies transport')",
        "sys.addaudithook(deny)",
        "text=(r/'selected-status.txt').read_text(encoding='utf-8')",
        "supplied=[{'runtime_id':s.execution_adapter,'detected':s.harness_id=='deepseek-harness','command':str(r/'uninstalled-runtime'),'version':'supplied-status-only','issues':[text]} for s in HARNESS_SPECS]",
        "def invoke():return build_harness_catalog(r,runtime_statuses=supplied,provider_env={'DEEPSEEK_API_KEY':'','OPENAI_API_KEY':'','ANTHROPIC_API_KEY':'','XAI_API_KEY':''})",
        "first=invoke()",
        "if category=='concurrency':",
        " with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:invoke(),range(8)))",
        " assert all([x['harnessId'] for x in row['harnesses']]==[s.harness_id for s in HARNESS_SPECS] for row in rows)",
        "if category=='stale':",
        " supplied=[{**row,'detected':False} for row in supplied];second=invoke();assert next(x for x in second['harnesses'] if x['harnessId']=='deepseek-harness')['detected'] is False",
        "assert [x['harnessId'] for x in first['harnesses']]==[s.harness_id for s in HARNESS_SPECS]",
        "row=next(x for x in first['harnesses'] if x['harnessId']=='deepseek-harness');assert row['providerConfigured'] is False and not any(x['available'] for x in row['capabilities'])",
        "print(json.dumps({'canonicalHarnesses':len(first['harnesses']),'unconfiguredCapabilitiesUnavailable':True,'suppliedStatusProjectionOnly':True,'transportDenied':True}))",
    ])
    env=dict(os.environ)
    for key in ("FLUXIO_RUNTIME_ROOT","SYNTELOS_RUNTIME_ROOT","SYNTHELOS_RUNTIME_ROOT"):env.pop(key,None)
    env.update(NEYVIA_MANAGED_RUNTIME_ROOT=str(managed.resolve()),USERPROFILE=str(home.resolve()),HOME=str(home.resolve()),PYTHONPATH=str(REPO/"src"))
    result=subprocess.run([sys.executable,"-c",code,str(root),category],env=env,capture_output=True,text=True,timeout=30,**hidden_windows_subprocess_kwargs())
    _check(result.returncode==0,"isolated production catalog failed: "+result.stderr[-1800:])
    return json.loads(result.stdout)


FAMILIES = {
    "legacy": (_legacy, {"proofs-b.engine.run","proofs-b.engine.summary"}, CATEGORIES-{"offline"}),
    "recorder-denied":(_recorder_denied,{"proofs-b.engine.recorder","proofs-b.engine.event-tail"},{"permissions"}),
    "skill-load":(_skill_rows,{"proofs-b.engine.skill-load"},{"interrupted","stale","concurrency"}),
    "verdict":(_verdict,{"proofs-b.engine.verdict"},{"concurrency","interrupted"}),
    "workflow":(_workflow,{"proofs-b.engine.workflow"},CATEGORIES-{"offline"}),
    "mcp":(_mcp,{"proofs-b.engine.mcp-authority"},CATEGORIES-{"offline","interrupted"}),
    "watchdog":(lambda root,category:_watchdog(root,category),{"proofs-b.engine.watchdog"},set(TEXT)|{"stale","concurrency"}),
    "watchdog-enforce":(lambda root,category:_watchdog(root,category,True),{"proofs-b.engine.watchdog-enforce"},CATEGORIES-{"offline"}),
}
for _kind in ("identity","lifecycle","observation"):
    FAMILIES["harness-"+_kind]=(lambda root,category,kind=_kind:_jobs(root,category,kind),{"proofs-b.harness."+_kind},CATEGORIES-{"offline"})
for _kind in ("admission","policy","execution"):
    FAMILIES["harness-"+_kind]=(lambda root,category,kind=_kind:_capacity(root,category,kind),{"proofs-b.harness."+_kind},CATEGORIES-{"offline"})
FAMILIES["harness-lock"]=(_lock,{"proofs-b.harness.lock-recovery"},CATEGORIES-{"offline","interrupted"})
FAMILIES["harness-budget"]=(_budget,{"proofs-b.harness.budget"},CATEGORIES-{"offline"})
for _kind in ("public-profile","gateway","instruction"):
    FAMILIES["harness-"+_kind]=(lambda root,category,kind=_kind:_registry(root,category,kind),{"proofs-b.harness."+_kind},({"interrupted","stale"} if _kind=="instruction" else {"interrupted","stale","permissions","concurrency"}))
FAMILIES["harness-catalog"]=(_catalog,{"proofs-b.harness.catalog"},set(TEXT)|{"stale","concurrency","offline"})
for _kind, _categories in {"account":{"interrupted"},"capture":{"interrupted","stale"},"capsule":{"interrupted","stale"},"experiment":{"interrupted","permissions"},"authorization":{"concurrency","stale"}}.items():
    FAMILIES[_kind]=(lambda root,category,kind=_kind:_ecosystem(root,category,kind),{"proofs-b.engine."+_kind},_categories)
for _kind in ("chat-public","chat-plan"):
    FAMILIES[_kind]=(lambda root,category,kind=_kind:_chat(root,category,kind),{"proofs-b.engine."+_kind},CATEGORIES-({"offline","interrupted","permissions"} if _kind=="chat-public" else {"offline"}))


def run(root, contracts, categories):
    from .proof_credential_guard import install
    base = Path(root).resolve(); base.mkdir(parents=True, exist_ok=True); install(base)
    rows = []
    for name,(builder,identities,supported) in FAMILIES.items():
        selected = sorted(identities & set(contracts))
        if not selected: continue
        for category in categories:
            if category not in supported: continue
            scratch = base / ".agent_control/proofs" / ("c7d-engine-"+name+"-"+category); scratch.mkdir(parents=True, exist_ok=False)
            row={"id":"c7d-engine."+name+"."+category,"category":category,"contracts":selected,
                "boundary":"Actual owned local production calls and independent effects; no rendered, live provider, enrolled credential or public activation proof"}
            try:
                with _environment({"FLUXIO_CLUSTER_ROOT":str(scratch),"FLUXIO_CONTROL_PROJECT_ROOT":str(scratch),
                    "FLUXIO_NAS_VOLUME_ROOT":str(scratch/"no-network/volume"),"FLUXIO_WINDOWS_NAS_VOLUME_MIRROR":str(scratch/"no-network/mirror"),
                    "NEYVIA_TOOL_AUTO_UPDATE":"0","FLUXIO_WATCHDOG_AUTOSTART":"0","NEYVIA_COORDINATOR_AUTOSTART":"0"}):
                    row.update(status="passed",detail=builder(scratch,category))
            except Exception as error:
                row.update(status="failed",detail={"error":str(error),"type":type(error).__name__,"traceback":traceback.format_exc()[-5000:]})
            rows.append(row)
    return rows


def blocker(contract, category):
    identity=contract.get("id","")
    exact={
        "proofs-b.engine.authorization":({"interrupted"},"plan_experiment_action reads the current recorded authorization and creates a non-executable per-action proposal; it commits no mutation, owns no worker and cannot replay an uncertain action"),
        "proofs-b.engine.benchmark":({"interrupted","permissions"},"_benchmark_claim compares explicitly supplied subjects, budgets and measured results in memory; durable benchmark admission/journal mutation and authorization belong to other owners"),
        "proofs-b.engine.chat-public":({"interrupted","permissions","offline"},"account_catalog projects already-loaded public account/room identities and opaque references; it neither opens the opaque credentials handle nor admits room writes or starts transport"),
        "proofs-b.engine.chat-plan":({"offline"},"build_message_plan hashes explicitly selected local attachment files and prepares an encryption-required plan; sending and Matrix authentication have separate invariants"),
        "proofs-b.engine.mcp-authority":({"interrupted","offline"},"CompactNeyviaMCPServer.handle applies the current read-only and pending-question gate before dispatch; this permission decision owns no resumable worker or network operation"),
        "proofs-b.engine.skill-load":({"offline"},"SkillLibrary._load_skill_rows parses only the explicitly selected local JSON file; skill acquisition and runtime execution are separate owners"),
        "proofs-b.engine.watchdog":({"interrupted","permissions","offline"},"evaluate_fake_running_mission inspects the supplied current Mission, stats and time (plus non-destructive process liveness); it starts no supervisor, persists no decision and requests no mutation grant or network transport"),
        "proofs-b.engine.watchdog-enforce":({"offline"},"enforce_fake_running_missions reads and writes the selected local control/receipt/log stores; it starts no supervisor or remote provider"),
        "proofs-b.engine.workflow":({"offline"},"build_efficient_workflow validates selected objective/routes and current local role prompts, then prepares dependency/authority metadata; actual route dispatch belongs to the execution adapter"),
        "proofs-b.engine.run":({"offline"},"AutonomousEngine.run records the local legacy planner/session/checkpoint state and explicitly supplied verification commands; its saved-state invariant does not assert remote model execution or authenticated provider reachability"),
        "proofs-b.engine.summary":({"offline"},"summarize_runs aggregates selected local session files without any network or provider operation"),
        "proofs-b.harness.admission":({"offline"},"HarnessJobStore.capacity/create calculate and fence local durable open-job pressure; provider connectivity is deferred until execution"),
        "proofs-b.harness.budget":({"offline"},"the hard runtime budget atomically arms/claims/settles selected local job state and owned process lifecycles; it performs no provider request"),
        "proofs-b.harness.catalog":({"interrupted","permissions"},"build_harness_catalog projects canonical HARNESS_SPECS ownership/transport/tier and supplied runtime/provider status; the invariant owns no mutable authorization grant, durable operation or resumable worker"),
        "proofs-b.harness.execution":({"offline"},"HarnessExecutionCapacity uses local FIFO receipts, retained operator limits and OS advisory slots; its execution admission invariant precedes any provider request"),
        "proofs-b.harness.gateway":({"offline"},"harness_gateway_environment reads a public local route and maps an explicitly supplied in-memory environment; it never opens credentials or contacts the selected base URL"),
        "proofs-b.harness.identity":({"offline"},"HarnessJobStore's immutable request/receipt identity uses local durable files and OS guards before provider execution"),
        "proofs-b.harness.instruction":({"offline"},"save_harness_instruction/read_harness_instruction retain selected workspace instruction bytes and backups entirely locally"),
        "proofs-b.harness.lifecycle":({"offline"},"HarnessJobStore's terminal/block/cancellation conservation is a local guarded state transition independent of provider transport"),
        "proofs-b.harness.lock-recovery":({"offline"},"_exclusive_job_lock and _process_alive use local OS advisory guards and non-destructive process ownership observations, with no peer service"),
        "proofs-b.harness.observation":({"offline"},"_with_job_observability projects metrics/timeline from the supplied durable local job receipt without provider I/O"),
        "proofs-b.harness.policy":({"offline"},"local admission/execution policy files monotonically retain the explicit hard operator limit; no remote service participates"),
        "proofs-b.harness.public-profile":({"offline"},"save_harness_profile filters and atomically retains public local route fields, never resolving or reading saved credentials or contacting a provider"),
    }
    if identity in exact and category in exact[identity][0]:
        return {"kind":"not_applicable","reason":f"Audited exact {identity} applicability: {exact[identity][1]}. The {category} strategy has no corresponding operation at this invariant's site."}
    return None
