"""Actual isolated, pinned Syncthing owner observations; never configured NAS."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import secrets
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .edge_fixture_host_runtime import _check,_reject,_sharing,_environment
from .edge_fixture_c7d_desktop import _stop_at_marker

IDS={"adapters.sync."+v for v in ("compatibility","discovery","native-runtime","plan-activation","policy","recovery","rollback","stale")}
TEXT={"empty":"","huge":"owned label "*10000,"unicode":"雪🙂 café العربية"}


def observe(repository,root,category,identity):
    from .proof_ports import c7_port_block
    gui_port, tcp_port = c7_port_block(int(os.environ['NEYVIA_C7_PORT']))[-2:]
    from .folder_sync import FolderSyncService
    from .proofs_b_adapters import _verified_native_executable
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    binary=repository/".agent_control/proofs-b/native-syncthing/syncthing-windows-amd64-v2.1.5/syncthing.exe"
    expected=_verified_native_executable(binary)
    home=root/"owned-native-home";home.mkdir(parents=True)
    # This seed is authored, then handed to the native owner. Generated config,
    # keys, certificates and credentials are never opened by this observer.
    (home/"config.xml").write_text(f'<configuration version="52"><gui enabled="true" tls="false"><address>127.0.0.1:{gui_port}</address></gui><options><listenAddress>tcp://127.0.0.1:{tcp_port}</listenAddress><globalAnnounceEnabled>false</globalAnnounceEnabled><localAnnounceEnabled>false</localAnnounceEnabled><localAnnouncePort>{tcp_port}</localAnnouncePort><relaysEnabled>false</relaysEnabled><natEnabled>false</natEnabled><startBrowser>false</startBrowser><autoUpgradeIntervalH>0</autoUpgradeIntervalH><urAccepted>-1</urAccepted><crashReportingEnabled>false</crashReportingEnabled></options></configuration>',encoding="utf8")
    key=secrets.token_hex(32);environment={**os.environ,"STGUIAPIKEY":key,"GOMAXPROCS":"2"}
    flags=hidden_windows_subprocess_kwargs()
    subprocess.run([str(binary),"generate","--home",str(home),"--no-port-probing"],env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=30,**flags)
    argv=[str(binary),"serve","--home",str(home),"--gui-address",f"127.0.0.1:{gui_port}","--no-port-probing","--no-browser","--no-console","--no-restart","--no-upgrade","--log-level","ERROR"]
    process=subprocess.Popen(argv,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**flags)
    def request(path,method="GET",payload=None):
        data=None if payload is None else json.dumps(payload).encode()
        req=urllib.request.Request(f"http://127.0.0.1:{gui_port}"+path,data=data,method=method,headers={"X-API-Key":key,"Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=3) as response:raw=response.read()
        return json.loads(raw) if raw else None
    def ready():
        deadline=time.monotonic()+30
        while True:
            _check(process.poll() is None,"owned native Syncthing exited")
            try:return request("/rest/system/status")
            except OSError:
                _check(time.monotonic()<deadline,"native service startup deadline");time.sleep(.1)
    def terminate_owned_tree():
        # Syncthing's launcher owns a worker descendant even with no-restart.
        # Killing only the launcher would leave that owned endpoint alive.
        if process.poll() is None:
            subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],capture_output=True,check=False,timeout=15,**hidden_windows_subprocess_kwargs())
            process.wait(timeout=10)
        deadline=time.monotonic()+10
        while True:
            try:request("/rest/system/status")
            except OSError:return
            _check(time.monotonic()<deadline,"owned native descendant remained reachable after tree termination");time.sleep(.1)
    try:
        status=ready();options=request("/rest/config/options")
        _check(options["listenAddresses"]==[f"tcp://127.0.0.1:{tcp_port}"] and all(options[k] is False for k in ("globalAnnounceEnabled","localAnnounceEnabled","relaysEnabled","natEnabled","startBrowser","crashReportingEnabled")) and options["autoUpgradeIntervalH"]==0,"native service broadened authority or opened discovery")
        config={"transport":{"endpoint":f"http://127.0.0.1:{gui_port}","apiKeyRef":"c7d:generated-memory-only","timeoutSeconds":3},"binary":{"installPath":str(binary),"executableSha256":expected,"version":"2.1.5"},"policy":{"allowedRoots":["${workspace}"],"folderTypes":["sendonly","receiveonly","sendreceive"],"versioningTypes":["trashcan","simple","staggered"],"inboundVersioningRequiredFor":["receiveonly","sendreceive"],"defaultVersioning":{"type":"staggered"}}}
        config["binary"]["signature"]=TEXT.get(category,"Owned signature metadata")
        config_path=root/"config/neyvia_folder_sync.json";config_path.parent.mkdir();config_path.write_text(json.dumps(config),encoding="utf8")
        service=FolderSyncService(root,config_path=config_path,credential_resolver=lambda _:key)
        text=TEXT.get(category,"Owned folder label");folder=root/"shared";folder.mkdir()
        def plan(index=0):
            selected=folder if index==0 else root/("folder-"+str(index))
            selected.mkdir(exist_ok=True)
            return service.build_folder_plan(folder_id="owned"+str(index),path=selected,device_ids=[status["myID"]],label=text,folder_type="sendonly",ignore_patterns=[".git"])
        def compat():
            row=service.compatibility_snapshot();_check(row["binary"]["hashVerified"] and row["transport"]["credentialsExposed"] is False and key not in json.dumps(row),"native compatibility lost actual pin or exposed in-memory authority");return row
        detail={"executableSha256":expected,"actualNativePid":process.pid,"guiPort":gui_port,"tcpPort":tcp_port,"remoteDevices":0,"generatedCredentialFilesRead":False,"category":category}
        if identity in {"adapters.sync.compatibility","adapters.sync.discovery","adapters.sync.native-runtime"}:
            row=compat();_check(row["binary"]["signature"]==config["binary"]["signature"],"compatibility changed selected metadata bytes")
            discover=None
            if identity=="adapters.sync.discovery":
                from .capability_service import CapabilityService
                from .proofs_b_adapters import _fixture_root
                capability=CapabilityService(_fixture_root(root))
                def discover():return capability.execute_tool_operation({"toolId":"tool.neyvia-folder-sync","operationId":"sync.compatibility","arguments":{},"permissionMode":"workspace_safe"})
                result=discover()
                _check(result["ok"] and result["capabilityId"]=="sync.health" and result["result"]["binary"]["hashVerified"],"typed native compatibility operation lost registry binding")
            if category=="concurrency":
                with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:compat(),range(8)))
                _check(len(rows)==8,"concurrent actual hash observations missing")
                if discover:
                    with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:discover(),range(8)))
                    _check(all(v["ok"] and v["capabilityId"]=="sync.health" for v in rows),"concurrent typed compatibility operations lost registry binding")
                if identity=="adapters.sync.native-runtime":
                    def version():return subprocess.run([str(binary),"--version"],env=environment,capture_output=True,text=True,check=True,timeout=10,**hidden_windows_subprocess_kwargs())
                    with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:version(),range(8)))
                    _check(all("v2.1.5" in v.stdout for v in rows),"concurrent actual native versions differed")
            elif category=="permissions":
                terminate_owned_tree()
                with _sharing(binary):
                    _reject(compat,(OSError,))
                    if identity=="adapters.sync.native-runtime":_reject(lambda:subprocess.run([str(binary),"--version"],env=environment,capture_output=True,timeout=10,**flags),(OSError,))
                    if discover:_check(not discover()["ok"],"unreadable native executable was discovered as a successful capability")
            elif category=="stale":
                service.config["binary"]["executableSha256"]="0"*64;changed=service.compatibility_snapshot();_check(not changed["binary"]["hashVerified"],"changed pin reused old readiness")
                if identity=="adapters.sync.native-runtime":
                    clone=root/"changed-owned-native.specimen";clone.write_bytes(binary.read_bytes()+b"actual changed native package");_reject(lambda:_verified_native_executable(clone),(ValueError,))
            elif category=="interrupted":
                terminate_owned_tree();process=subprocess.Popen(argv,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**flags);fresh=ready();_check(fresh["myID"]==status["myID"],"killed native service lost isolated identity")
            elif category=="offline":
                terminate_owned_tree();_reject(lambda:request("/rest/system/status"),(OSError,));_check(compat()["binary"]["hashVerified"],"offline native service erased exact installed-byte identity")
            elif identity=="adapters.sync.native-runtime":
                version=subprocess.run([str(binary),"--version"],env=environment,capture_output=True,text=True,check=True,timeout=10,**flags);_check("v2.1.5" in version.stdout,"actual pinned runtime version differs")
            return detail
        if identity=="adapters.sync.policy":
            _reject(lambda:service._allowed_folder_path(root.parent/"outside"),(ValueError,))
            _reject(lambda:service.build_folder_plan(folder_id="",path=folder,device_ids=[status["myID"]]),(ValueError,))
            _reject(lambda:service._validate_ignore_patterns(["#include generated"]),(ValueError,))
            if category=="permissions":
                service.config["policy"]["allowedRoots"]=[str(root/"other")];_reject(lambda:service._allowed_folder_path(folder),(ValueError,))
            elif category=="stale":
                service.config["policy"]["allowedRoots"]=[str(root/"other")];_reject(lambda:service._allowed_folder_path(folder),(ValueError,))
            elif category=="concurrency":
                with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:service._validate_ignore_patterns([text,text,".git"]),range(8)))
                _check(all(len(v)==len(set(v)) for v in rows),"concurrent ignore normalization admitted duplicate includes")
            elif category=="huge":_reject(lambda:service._validate_ignore_patterns([text,".git"]),(ValueError,))
            else:service._validate_ignore_patterns([text,".git"])
            return detail
        planned=plan();_check(planned["desiredFolder"]["paused"] is True and planned["summary"]["appliesDataChanges"] is False and planned["desiredFolder"]["label"]==str(text or "owned0")[:128],"plan preview started data movement or changed selected bounded label")
        if category=="offline":
            terminate_owned_tree()
            if identity=="adapters.sync.recovery":operation=lambda:service.override_folder("owned0",confirmation="owned0",approved=True)
            elif identity=="adapters.sync.rollback":operation=lambda:service._restore_folder("owned0",folder=None,ignores=[])
            else:operation=lambda:service.apply_folder_plan(planned,approved=True)
            _reject(operation,(RuntimeError,OSError));return detail
        if identity=="adapters.sync.stale" or (category=="stale" and identity not in {"adapters.sync.recovery","adapters.sync.rollback"}):
            changed={**planned["desiredFolder"],"label":"Independent actual native edit"};request("/rest/config/folders","POST",changed);before=request("/rest/config/folders/owned0")
            if category=="concurrency":
                with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:service.apply_folder_plan(planned,approved=True),range(8)))
            else:rows=[service.apply_folder_plan(planned,approved=category!="permissions")]
            _check(all(v["status"] in {"stale_plan","approval_required"} for v in rows) and request("/rest/config/folders/owned0")==before,"stale/unapproved plan replaced independent native state")
            if category=="interrupted":
                terminate_owned_tree();process=subprocess.Popen(argv,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**flags);ready();_check(request("/rest/config/folders/owned0")==before and service.apply_folder_plan(planned,approved=True)["status"]=="stale_plan","restarted native service lost independent revision authority")
            return detail
        if identity=="adapters.sync.rollback":
            (folder/".stignore").mkdir()
            def failed_restore():
                try:result=service.apply_folder_plan(planned,approved=True)
                except RuntimeError:return "actual-native-write-failure-restored"
                _check(category=="concurrency" and result["status"]=="stale_plan" and not result["ok"],"unsafe failed rollback attempt was accepted")
                return "concurrent-actual-CAS-refusal"
            if category=="concurrency":
                with ThreadPoolExecutor(max_workers=8) as pool:outcomes=list(pool.map(lambda _:failed_restore(),range(8)))
                _check("actual-native-write-failure-restored" in outcomes,"concurrent rollback observed no actual provider failure")
                detail["rollbackOutcomes"]=outcomes
            elif category=="permissions":
                from .edge_fixture_c7d_local import _deny_child_creation
                with _deny_child_creation(folder,root):failed_restore()
            else:failed_restore()
            _check(not any(v["id"]=="owned0" for v in request("/rest/config/folders")) and (folder/".stignore").is_dir(),"actual ignore write failure left relationship or removed collision")
            if category=="interrupted":
                terminate_owned_tree();process=subprocess.Popen(argv,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**flags);ready();_check(not any(v["id"]=="owned0" for v in request("/rest/config/folders")),"restarted native service revived rolled-back relationship")
            elif category=="stale":
                fresh=plan();_check(fresh["planId"]!=planned["planId"],"new rollback attempt reused earlier plan");_reject(lambda:service.apply_folder_plan(fresh,approved=True),(RuntimeError,));_check(not any(v["id"]=="owned0" for v in request("/rest/config/folders")),"fresh actual rollback revived earlier relationship")
            return detail
        if category=="permissions":
            refused=service.override_folder("owned0",confirmation="owned0",approved=False) if identity=="adapters.sync.recovery" else service.apply_folder_plan(planned)
            _check(refused["status"]=="approval_required" and request("/rest/config/folders")==[],"unapproved native operation mutated state")
            return detail
        if category=="concurrency" and identity!="adapters.sync.recovery":
            plans=[plan(i+1) for i in range(8)]
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda p:service.apply_folder_plan(p,approved=True),plans))
            _check(all(v["status"]=="configured_paused" for v in rows) and {v["id"] for v in request("/rest/config/folders")}=={f"owned{i+1}" for i in range(8)},"concurrent distinct plans lost actual native paused configuration")
            return detail
        applied=service.apply_folder_plan(planned,approved=True);_check(request("/rest/config/folders/owned0")["paused"] is True,"approved plan was not configured paused")
        if category=="interrupted":
            terminate_owned_tree();process=subprocess.Popen(argv,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**flags);ready();_check(request("/rest/config/folders/owned0")["paused"] is True and json.loads((service.receipt_root/(applied["receiptId"]+".json")).read_text(encoding="utf8"))==applied,"killed native service lost durable paused relationship/receipt")
        _check(service.resume_folder("owned0",approved=True)["status"]=="approval_required","missing deletion propagation grant activated folder")
        activated=service.resume_folder("owned0",approved=True,approved_deletion_propagation=True);_check(request("/rest/config/folders/owned0")["paused"] is False,"actual native activation/readback failed")
        if identity=="adapters.sync.recovery":
            _check(service.override_folder("owned0",confirmation="wrong",approved=True)["status"]=="approval_required","wrong exact recovery confirmation admitted")
            deadline=time.monotonic()+10
            while request("/rest/db/status?folder=owned0").get("state")!="idle":
                _check(time.monotonic()<deadline,"native folder idle deadline");time.sleep(.1)
            if category=="stale":
                current=request("/rest/config/folders/owned0");request("/rest/config/folders","POST",{**current,"type":"receiveonly"});_reject(lambda:service.override_folder("owned0",confirmation="owned0",approved=True),(ValueError,))
            elif category=="concurrency":
                with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:service.override_folder("owned0",confirmation="owned0",approved=True),range(8)))
                _check(len({v["receiptId"] for v in rows})==8 and all(v["status"]=="override_requested" for v in rows),"concurrent actual native recovery requests lost durable distinct identities")
            else:
                recovered=service.override_folder("owned0",confirmation="owned0",approved=True);_check(recovered["status"]=="override_requested","native override request failed")
        _check(key not in json.dumps(activated),"native receipt exposed generated authority")
        return detail
    finally:
        if process.poll() is None:
            try:request("/rest/system/shutdown","POST")
            except OSError:pass
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
        _check(process.poll() is not None,"owned native Syncthing survived cleanup")
