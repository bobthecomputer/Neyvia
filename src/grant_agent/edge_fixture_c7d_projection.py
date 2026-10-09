"""Exact local mission projection edges and actual attachment read denial."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PREFIX = "proofs-c.missions."
SUPPORTED = {
    PREFIX+"artifact-layout": {"concurrency","interrupted","permissions"},
    PREFIX+"control-durable": {"concurrency","interrupted","stale"},
    PREFIX+"local-read-model": {"concurrency","permissions"},
    PREFIX+"local-flight": {"stale"},
    "composer.attachResult": {"permissions"},
}
IDS = set(SUPPORTED)
AUDITS = {
    (PREFIX+"artifact-layout","stale"): "Exact build_mission_run_artifact_layout validates a supplied immutable mission ID and derives canonical directories from the selected root. It accepts no saved receipt, revision, timestamp or cache entry to become stale. Actual concurrent directory creation, caller exit after creation and OS-denied child creation are separate exercised mechanisms.",
    (PREFIX+"local-read-model","interrupted"): "Exact _mission_run_read_model_payload synchronously reads already saved immutable mission/snapshot/receipt inputs and returns a projection without committing state or launching a worker. It owns no transaction or resumable mutation to interrupt. Writer durability and actual denied snapshot reads are separate exercised contracts.",
    (PREFIX+"local-flight","concurrency"): "Exact _compact_flight_recorder_payload receives a caller-supplied snapshot dict and path label, then returns a fresh bounded dict. It reads no file, mutates no shared state and starts no worker. Concurrency at the flight-recorder writer is a separate contract.",
    (PREFIX+"local-flight","interrupted"): "Exact _compact_flight_recorder_payload performs a synchronous dict projection without file access, a durable commit or a child process. No resumable mutation exists at this owner to interrupt; actual recorder writes are governed separately.",
    (PREFIX+"local-flight","permissions"): "Exact _compact_flight_recorder_payload accepts an already supplied snapshot dict and a path used only as a returned label. It never opens that path and accepts no authority/grant input, so OS permission denial cannot act at this owner. The enclosing read-model has an actual denied-snapshot fixture.",
}


def require(condition, message):
    if not condition: raise AssertionError(message)


def _child(root, program):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    prelude = "from pathlib import Path;import os,sys;from grant_agent.proof_credential_guard import install;r=Path(sys.argv[1]);install(r);"
    result = subprocess.run([sys.executable,"-c",prelude+program,str(root)], capture_output=True,
                            text=True,encoding="utf8",timeout=40,env={**os.environ,"PYTHONPATH":str(REPO/"src")},
                            **hidden_windows_subprocess_kwargs())
    require(result.returncode==23,"Actual interrupted caller did not exit after its completed owner call: "+result.stderr[-2000:])
    return result.returncode


def _layout(root, category):
    from .mission_artifacts import build_mission_run_artifact_layout, MISSION_RUN_ARTIFACT_DIRS
    canonical=root/".agent_control/mission_runs/owned"
    if category=="permissions":
        from .edge_fixture_c7d_local import _deny_child_creation
        parent=canonical.parent;parent.mkdir(parents=True)
        with _deny_child_creation(parent,root):
            try: build_mission_run_artifact_layout(root,"owned",create=True)
            except OSError as error: denied=error.winerror
            else: raise AssertionError("Actual denied directory creation passed")
        require(not canonical.exists(),"Denied layout creation wrote a partial mission root")
        layout=build_mission_run_artifact_layout(root,"owned",create=False)
        require(not canonical.exists() and Path(layout.root)==canonical,"create=false wrote through a denied/nonexistent root")
        return {"actualWindowsCreationDenial":denied,"createFalseWrites":0}
    if category=="interrupted":
        code=_child(root,"from grant_agent.mission_artifacts import build_mission_run_artifact_layout;build_mission_run_artifact_layout(r,'owned',create=True);os._exit(23)")
        layouts=[build_mission_run_artifact_layout(root,"owned",create=False)]
    else:
        with ThreadPoolExecutor(max_workers=8) as pool:
            layouts=list(pool.map(lambda _:build_mission_run_artifact_layout(root,"owned",create=True),range(8)))
        code=None
    require(all(Path(row.root)==canonical for row in layouts),"Layout root escaped the canonical selected mission")
    require(all((canonical/name).is_dir() for name in MISSION_RUN_ARTIFACT_DIRS),"Completed layout omitted a declared directory")
    before={str(p.relative_to(root)) for p in root.rglob('*')}
    build_mission_run_artifact_layout(root,"owned",create=False)
    require(before=={str(p.relative_to(root)) for p in root.rglob('*')},"Projection-only layout wrote files")
    return {"canonicalDirectories":len(MISSION_RUN_ARTIFACT_DIRS),"successfulCallers":len(layouts),"childExit":code,"createFalsePreservedTree":True}


def _control(root, category):
    from .mission_control import ControlRoomStore
    store=ControlRoomStore(root);path=store.missions_path
    values=[{"index":i,"text":"雪 café e\u0301 "+str(i),"nested":{"owned":True}} for i in range(8)]
    if category=="concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda value:ControlRoomStore(root)._write_json_if_changed(path,[value]),values))
        require(json.loads(path.read_bytes()) in [[value] for value in values],"Concurrent successful writes left a partial or foreign JSON payload")
        return {"actualSameTargetSuccessfulWriters":8,"actualOwnerReadbackEnforcedBeforeReturn":True,"independentFinalWholePayload":True}
    if category=="interrupted":
        code=_child(root,"from grant_agent.mission_control import ControlRoomStore;s=ControlRoomStore(r);s._write_json_if_changed(s.missions_path,[{'index':23,'text':'owned returned write'}]);os._exit(23)")
        require(json.loads(path.read_bytes())==[{"index":23,"text":"owned returned write"}],"Returned JSON write vanished after actual caller exit")
        return {"childExit":code,"independentReturnedPayloadReadback":True}
    store._write_json_if_changed(path,[values[0]])
    require(store._load_json(path,[])==[values[0]],"Initial cached control value was absent")
    store._write_json_if_changed(path,[values[1]])
    require(json.loads(path.read_bytes())==[values[1]] and store._load_json(path,[])==[values[1]],"New durable control write retained stale cached JSON")
    return {"freshDurablePayload":True,"sameStoreCacheInvalidated":True}


def _read_model(root, category):
    from .models import Mission, VerificationReceipt
    from .mission_control import ControlRoomStore
    from .mission_artifacts import build_mission_run_artifact_layout
    from .mission_receipts import append_mission_receipt
    mission=Mission(mission_id="owned",workspace_id="scratch",runtime_id="local",objective="Owned projection",success_checks=[])
    mission.state.current_cycle_phase="planner"
    store=ControlRoomStore(root);store.save_missions([mission]);before=store.missions_path.read_bytes()
    layout=build_mission_run_artifact_layout(root,"owned")
    snapshot=Path(layout.snapshots_dir)/"mission_run.json"
    snapshot.write_text(json.dumps({"schema_version":"fluxio.mission_run.v1","mission_id":"owned","mission_run_id":"owned-run","current_phase":"verifier","status":"running"}),encoding="utf8")
    for index in range(4):
        append_mission_receipt(Path(layout.receipts_jsonl),VerificationReceipt(receipt_id="r-"+str(index),mission_id="owned" if index%2==0 else "foreign",host="fixture",runtime="local",workspace=str(root),status="accepted",summary="Owned saved evidence",decision="accepted"))
    def observe():
        result=store._mission_run_read_model_payload(mission,root=root)
        require(result['missionId']=='owned' and [row['receipt_id'] for row in result['receipts']]==['r-0','r-2'],"Projection lost identity or filtered receipt order")
        return result
    if category=="permissions":
        from .edge_fixture_missions import exclusive
        with exclusive(snapshot): result=observe()
        require(not result['snapshotPresent'] and result['currentPhase']=='planner',"Actual denied lifecycle snapshot invented present verifier state")
        require(observe()['snapshotPresent'],"Released snapshot denial did not restore observation")
        detail={"actualWindowsSnapshotReadDenial":True,"legacyLifecycleRetained":True}
    else:
        with ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(lambda _:observe(),range(8)))
        require(all(row==rows[0] and row['snapshotPresent'] and row['currentPhase']=='verifier' for row in rows),"Concurrent immutable read projections disagreed")
        detail={"actualConcurrentReaders":8,"orderedOwnReceipts":2}
    require(store.missions_path.read_bytes()==before,"Read-model observation mutated missions.json")
    return {**detail,"independentSourceBytesPreserved":True}


def _flight(root, _category):
    from .flight_recorder import MissionFlightRecorder
    from .mission_control import ControlRoomStore
    recorder=MissionFlightRecorder(root,"owned")
    for index in range(28): recorder.append_event(kind="owned.output",message="Owned event "+str(index),phase="executor",payload={"index":index})
    recorder.snapshot(current_phase="executor",process_ids=[os.getpid()])
    old=json.loads(recorder.snapshot_path.read_bytes())
    first=ControlRoomStore._compact_flight_recorder_payload(old,snapshot_path=recorder.snapshot_path)
    recorder.append_event(kind="owned.current",message="Fresh written phase",phase="verifier",payload={"index":28})
    recorder.snapshot(current_phase="verifier",process_ids=[os.getpid(),23])
    fresh=json.loads(recorder.snapshot_path.read_bytes())
    value=ControlRoomStore._compact_flight_recorder_payload(fresh,snapshot_path=recorder.snapshot_path)
    require(first['currentPhase']=='executor' and value['currentPhase']=='verifier' and value['processIds']==[os.getpid(),23] and value['events']==fresh['events'][-20:] and value['eventCount']==29,"Fresh supplied recorder snapshot reused stale phase/process/event evidence")
    invalid=ControlRoomStore._compact_flight_recorder_payload({"schema":"invalid","events":fresh['events']},snapshot_path=recorder.snapshot_path)
    require(not invalid['present'] and not invalid['events'] and invalid['eventCount']==0,"Invalid supplied snapshot invented events")
    return {"actualWrittenFreshPhase":"verifier","independentSnapshotEventCount":29,"boundedEventTail":20,"invalidSnapshotEvents":0}


def _attachment(root, _category):
    from .edge_fixture_missions import exclusive
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    path=root/'owned.png';path.write_bytes(b'Owned local file bytes')
    program=r'''import assert from 'node:assert/strict';import fs from 'node:fs/promises';import {pathToFileURL} from 'node:url';
const [repo,file]=process.argv.slice(1);const m=await import(pathToFileURL(repo+'/web/src/neyvia/next/nxComposerModel.js'));const store=m.createDraftStore();store.update('owned',[{name:'keeper',mime:'image/png',data:'AA=='}]);store.update('other',[{name:'other',mime:'image/png',data:'BB=='}]);const before=JSON.stringify([store.get('owned'),store.get('other')]);let code='';let attempts=0;
const text=await m.attachToDraft(store,'owned',[{name:'owned.png',type:'image/png',size:22}],async files=>{attempts++;try{const bytes=await fs.readFile(file);return [{name:files[0].name,mime:files[0].type,data:bytes.toString('base64')}]}catch(error){code=error.code;throw error}});assert.equal(attempts,1);assert.ok(['EACCES','EPERM','EBUSY'].includes(code),code);assert.ok(text.length>0);assert.equal(JSON.stringify([store.get('owned'),store.get('other')]),before);console.log(JSON.stringify({actualWindowsReadDenial:code,actualReadAttempts:attempts,originAndOtherDraftsPreserved:true,renderedProof:false}));'''
    with exclusive(path):
        result=subprocess.run(['node','--input-type=module','-e',program,str(REPO),str(path)],capture_output=True,text=True,encoding='utf8',timeout=30,**hidden_windows_subprocess_kwargs())
    require(result.returncode==0,'Actual Node attachment read-denial journey failed: '+result.stderr[-2500:])
    return json.loads(result.stdout)


def blocker(contract, category):
    reason=AUDITS.get((contract['id'],category))
    return {'kind':'not_applicable','reason':reason} if reason else None


def run(root, contracts, categories):
    from .proof_credential_guard import install
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True);install(root)
    builders={'artifact-layout':_layout,'control-durable':_control,'local-read-model':_read_model,'local-flight':_flight,'composer.attachResult':_attachment}
    rows=[]
    for identity,supported in SUPPORTED.items():
        if identity not in contracts: continue
        for category in categories:
            if category not in supported: continue
            target=root/(identity.rsplit('.',1)[-1]+'-'+category+'-'+uuid.uuid4().hex[:8]);target.mkdir()
            row={'id':'c7d-projection.'+identity+'.'+category,'contracts':[identity],'category':category,'boundary':'Actual confined local file/directory/caller effects and exact data projections; no rendered, provider or device proof','scratchRoot':str(target)}
            try: row.update(status='passed',detail=builders[identity.removeprefix(PREFIX)](target,category))
            except Exception as error: row.update(status='failed',detail={'type':type(error).__name__,'error':str(error)})
            rows.append(row)
    return rows
