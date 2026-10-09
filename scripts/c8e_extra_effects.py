"""Additional C8e journeys through real owners, peers and mounted app controls."""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNCTHING_ROOT=ROOT/".agent_control/proofs/C8/c8e-syncthing"
SYNCTHING_EXECUTABLE=SYNCTHING_ROOT/"syncthing-windows-amd64-v2.1.5/syncthing.exe"
SYNCTHING_EXECUTABLE_SHA256="36a0f7bc372f64fa7cc4f5654fa324c0dd9f7fef2e07565e00c6e1cf73f50344"

def acquire_syncthing():
    """Explicit public pinned portable acquisition; never called by a verifier.

    It neither installs nor starts a service. Production compatibility below
    consumes the prepared executable only and cannot download a fallback.
    """
    import urllib.request,zipfile,stat,subprocess,os
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    cap=30_000_000;total=0;downloads=[]
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    SYNCTHING_ROOT.mkdir(parents=True,exist_ok=True)
    def download(url,expected_size,maximum):
        nonlocal total
        if expected_size>maximum or total+expected_size>cap:raise ValueError("Public artifact exceeds assigned byte budget before streaming")
        request=urllib.request.Request(url,headers={"User-Agent":"Neyvia-C8e-public-pinned-portable"})
        with opener.open(request,timeout=45) as response:
            declared=response.headers.get("Content-Length")
            if declared and int(declared)>maximum:raise ValueError("Declared public response exceeds assigned bound")
            chunks=[];count=0
            while chunk:=response.read(min(65536,maximum-count+1)):
                count+=len(chunk);total+=len(chunk)
                if count>maximum or total>cap:raise ValueError("Public stream exceeded assigned byte bound")
                chunks.append(chunk)
        raw=b"".join(chunks)
        if expected_size and count!=expected_size:raise ValueError("Public artifact byte count differs from official metadata")
        downloads.append({"url":url,"bytes":count,"sha256":hashlib.sha256(raw).hexdigest()})
        return raw
    metadata_raw=download("https://api.github.com/repos/syncthing/syncthing/releases/tags/v2.1.5",0,250000)
    metadata=json.loads(metadata_raw)
    asset=next(a for a in metadata["assets"] if a["name"]=="syncthing-windows-amd64-v2.1.5.zip")
    sums=next(a for a in metadata["assets"] if a["name"]=="sha256sum.txt.asc")
    expected_zip="39571e4d0900c2a2cab14c0b170f49751340a869e49734ccc8079d9b98a7974b"
    if asset["digest"]!="sha256:"+expected_zip or asset["size"]!=11975789:raise ValueError("Official release pin changed")
    public_sums=download(sums["browser_download_url"],sums["size"],20000)
    if hashlib.sha256(public_sums).hexdigest()!=sums["digest"].removeprefix("sha256:"):raise ValueError("Official checksum artifact digest differs")
    if not any(line.split()==[expected_zip,asset["name"]] for line in public_sums.decode("utf-8").splitlines()):raise ValueError("Pinned portable checksum is absent from official checksum list")
    archive=SYNCTHING_ROOT/asset["name"]
    cached=archive.is_file() and hashlib.sha256(archive.read_bytes()).hexdigest()==expected_zip
    raw=archive.read_bytes() if cached else download(asset["browser_download_url"],asset["size"],20_000_000)
    if hashlib.sha256(raw).hexdigest()!=expected_zip:raise ValueError("Portable archive checksum differs")
    archive.write_bytes(raw)
    with zipfile.ZipFile(archive) as zipped:
        entries=zipped.infolist()
        if sum(e.file_size for e in entries)>60_000_000:raise ValueError("Portable archive unpacked bound exceeded")
        for entry in entries:
            name=entry.filename
            if "\\" in name or ":" in name or name.startswith("/") or ".." in Path(name).parts or stat.S_ISLNK(entry.external_attr>>16):raise ValueError("Unsafe portable archive member")
            destination=(SYNCTHING_ROOT/name).resolve();destination.relative_to(SYNCTHING_ROOT.resolve())
            if entry.is_dir():destination.mkdir(parents=True,exist_ok=True)
            else:
                destination.parent.mkdir(parents=True,exist_ok=True)
                with zipped.open(entry) as source,destination.open("wb") as target:
                    import shutil
                    shutil.copyfileobj(source,target,length=65536)
    digest=hashlib.sha256(SYNCTHING_EXECUTABLE.read_bytes()).hexdigest()
    if digest!=SYNCTHING_EXECUTABLE_SHA256:raise ValueError("Extracted executable differs from original production pin")
    temporary=SYNCTHING_ROOT/"temporary";temporary.mkdir(exist_ok=True)
    windows=os.environ.get("SystemRoot",r"C:\Windows")
    profile=SYNCTHING_ROOT/"profile";profile.mkdir(exist_ok=True)
    env={"SystemRoot":windows,"WINDIR":windows,"PATH":str(Path(windows)/"System32"),"TEMP":str(temporary),"TMP":str(temporary),"USERPROFILE":str(profile),"LOCALAPPDATA":str(profile/"AppData/Local"),"APPDATA":str(profile/"AppData/Roaming"),"STNOUPGRADE":"1"}
    version=subprocess.run([str(SYNCTHING_EXECUTABLE),"--version"],cwd=SYNCTHING_ROOT,env=env,capture_output=True,text=True,timeout=15,**hidden_windows_subprocess_kwargs())
    if version.returncode or not version.stdout.startswith("syncthing v2.1.5"):raise ValueError("Pinned portable version command refused: "+version.stderr[:200])
    receipt={"schema":"neyvia.c8e.public-portable.v1","version":"2.1.5","officialRelease":"https://github.com/syncthing/syncthing/releases/tag/v2.1.5","downloads":downloads,"downloadedBytesThisInvocation":total,"archiveBytes":len(raw),"cachedArchive":cached,"totalAcquisitionBytesUpperBound":total+(asset["size"]+250000+20000 if cached else 0),"byteBudget":cap,"archiveSha256":expected_zip,"executable":str(SYNCTHING_EXECUTABLE),"executableSha256":digest,"versionOutput":version.stdout.strip(),"versionExitCode":version.returncode,"boundary":"Pinned portable version command only; no install, service, native desktop or synchronization"}
    (SYNCTHING_ROOT/"acquisition.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    return receipt

def apply(bindings):
    overlay = json.loads((ROOT / "config/inception_c8e_extra_effects.json").read_text(encoding="utf-8"))["bindings"]
    for identity, addition in overlay.items():
        for key, value in addition.items():
            if key == "c8eEffect": bindings[identity].setdefault(key, {}).update(value)
            else: bindings[identity][key] = value
    return bindings

def _check(identity, passed, observed, boundary="production-state"):
    return {"id":identity,"passed":bool(passed),"fresh":True,"boundary":boundary,"observed":observed}

def before_manual(worker, binding, inputs, root):
    from c8e_effects import before_manual as produce
    if binding["c8eEffect"].get("renderedWitness")=="nightshift-model-real":
        # Real Git production precedes the model producer, so the manual's
        # latest report is still the actual model report it was authored to read.
        prepare={**binding,"c8eEffect":{"producerAdmission":"scoped-production-chapters","producerAreas":["proofs-b-adapters"],"adapterChapters":["git"]}}
        produce(worker,prepare,inputs,root)
        worker.step_results["extraNightshiftGitProducer"]=worker.c8e_effect.copy()
    produce(worker,binding,inputs,root)
    if binding["c8eEffect"].get("renderedWitness") == "cross-pc-live":
        from c8e_prerequisites import _peer
        _peer(worker,binding,inputs,Path(root))
    if binding["c8eEffect"].get("renderedWitness") == "outputs-model-real":
        created=worker.tool("backend:create_neyvia_conversation_command",{"kind":"chat","title":"C8e docked authored conversation","titleMode":"off"})
        cid=created["conversationId"]
        worker.tool("backend:append_neyvia_conversation_turn_command",{"conversationId":cid,"role":"user","content":"This actual saved user note stays unchanged when its chat floats.","source":"C8e-authored-user-fixture"})
        from c8e_ui_effects import _fresh_summary
        worker.step_results["extraOutputConversation"]=_fresh_summary(worker,cid)

def _path_row(scope, path):
    return scope.locator('[data-path=' + json.dumps(str(path)) + ']')

def _wait_transfer(worker, previous, source):
    for _ in range(200):
        rows = worker.tool("neyvia.devices.transfers", {})["transfers"]
        found = [r for r in rows if r["id"] not in previous and r["from"] == str(source)]
        if found and found[-1]["status"] in {"done","failed","cancelled"}: return found[-1]
        worker.page.wait_for_timeout(100)
    raise RuntimeError("Actual UI transfer did not complete: " + str(source))

def _cross_pc(worker, binding, root):
    from c8e_prerequisites import owner
    from c8_journey import Candidate
    peer = Candidate(binding["peerUrl"])
    root = Path(root).resolve()
    device_id = worker.step_results["prerequisitePeer"]["device"]
    state = worker.tool("neyvia.devices.list", {})
    device = next(d for d in state["devices"] if d["id"] == device_id)
    places = worker.tool("neyvia.devices.files.list", {"device":device_id})["places"]
    share = next(p for p in places if p["kind"] == "shared")
    inbox = next(p for p in places if p["kind"] == "inbox")
    remote_folder = Path(share["path"]).resolve()
    remote_folder.relative_to(ROOT / ".agent_control/proofs/C8")
    base = root / "c8"
    base.mkdir(exist_ok=True)
    (base / "moved").mkdir(exist_ok=True)
    remote_source = remote_folder / ("c8e-remote-" + worker.args.run_id + ".txt")
    remote_content = "Actual independently rooted peer bytes " + worker.args.run_id
    owner(worker,"/api/backend",{"command":"call_native_tool_command","payload":{"tool":"workspace.write","arguments":{"path":str(remote_source),"content":remote_content}}},peer)
    local_source = base / "c8e-local.txt"
    local_source.write_text("Actual local send bytes " + worker.args.run_id,encoding="utf-8")
    move_source = base / "c8e-move.txt"
    move_source.write_text("Actual local move bytes " + worker.args.run_id,encoding="utf-8")
    remote_digest = hashlib.sha256(remote_content.encode("utf-8")).hexdigest()
    local_digest = hashlib.sha256(local_source.read_bytes()).hexdigest()
    requests=[]
    def record(request):
        if request.url.endswith("/api/ui/devices") and request.method == "POST":
            requests.append(request.post_data_json)
    worker.page.on("request",record)
    checks=[]
    # Accounts' actual Open button computes pcTarget, and Files decodes it.
    worker.tool("neyvia.pane.show", {"kind":"accounts","target":"other-pcs"})
    card = worker.page.locator(".nx-ac-person").filter(has=worker.page.get_by_text(device["name"],exact=True))
    card.get_by_role("button",name="Open",exact=True).click(timeout=30000)
    remote = worker.page.locator(".nx-pc-pane")
    remote.wait_for(timeout=30000)
    _path_row(remote,remote_folder).wait_for(timeout=30000)
    checks.append(_check("c8e.pc-target-account-open",True,{"device":device_id,"remoteTitle":remote.get_attribute("aria-label"),"places":places},"rendered-user-action"))
    # Full path pane target is consumed by the mounted Files app and observed
    # in its real network request; no model module or React state is injected.
    target = "pc:" + device_id + "|" + str(remote_folder)
    worker.tool("neyvia.app.open", {"app":"files","target":target})
    _path_row(worker.page.locator(".nx-pc-pane"),remote_source).wait_for(timeout=30000)
    decoded = any(r.get("op") == "files.list" and r.get("args",{}).get("device") == device_id
                  and r.get("args",{}).get("path") == str(remote_folder) for r in requests)
    checks.append(_check("c8e.pc-target-real-path-decoded",decoded,{"target":target,"actualRequests":requests.copy()},"rendered-user-action"))
    # Return to a local scratch folder, then open this paired PC alongside it.
    worker.tool("neyvia.app.open", {"app":"files","target":str(base)})
    local = worker.page.get_by_role("region",name="This PC",exact=True)
    _path_row(local,move_source).wait_for(timeout=30000)
    _path_row(local,move_source).drag_to(_path_row(local,base / "moved"))
    for _ in range(50):
        if (base/"moved"/move_source.name).is_file(): break
        worker.page.wait_for_timeout(100)
    moved = base/"moved"/move_source.name
    checks.append(_check("c8e.drop-local-move",moved.is_file() and not move_source.exists(),
                         {"source":str(move_source),"destination":str(moved),"sha256":hashlib.sha256(moved.read_bytes()).hexdigest() if moved.is_file() else None},"rendered-user-action"))
    worker.page.locator(".nx-pc-tree .nx-pc-node").filter(has_text=device["name"]).click()
    remote = worker.page.locator(".nx-pc-pane")
    _path_row(remote,remote_folder).dblclick(timeout=30000)
    _path_row(remote,remote_source).wait_for(timeout=30000)
    split = remote.get_by_role("button",name="Side by side with this PC",exact=True)
    if split.count(): split.click()
    local.wait_for(timeout=30000)
    # A remote drop into the local folder starts the production Take procedure.
    previous={r["id"] for r in worker.tool("neyvia.devices.transfers",{})["transfers"]}
    destination=local.locator(".nx-files-crumbs li").last
    _path_row(remote,remote_source).drag_to(destination)
    taken=_wait_transfer(worker,previous,remote_source)
    taken_path=Path(taken["to"])
    take_ok=taken["status"]=="done" and taken["sha256"]==remote_digest and taken_path.is_file() and hashlib.sha256(taken_path.read_bytes()).hexdigest()==remote_digest and remote_source.is_file()
    checks.append(_check("c8e.drop-remote-take",take_ok,{"actualTransfer":taken,"expectedSha256":remote_digest,"destinationExists":taken_path.is_file()},"rendered-user-action"))
    # The read-only shared folder redirects local drops to the agreed inbox.
    previous={r["id"] for r in worker.tool("neyvia.devices.transfers",{})["transfers"]}
    _path_row(local,local_source).drag_to(remote.locator(".nx-files-list"))
    sent=_wait_transfer(worker,previous,local_source)
    sent_path=Path(sent["to"])
    send_ok=sent["status"]=="done" and sent["sha256"]==local_digest and sent_path.is_file() and sent_path.parent==Path(inbox["path"]) and hashlib.sha256(sent_path.read_bytes()).hexdigest()==local_digest and not (remote_folder/local_source.name).exists()
    checks.append(_check("c8e.send-readonly-share-to-inbox",send_ok,{"actualTransfer":sent,"inbox":inbox,"readOnlyShare":share},"rendered-user-action"))
    # An actual remote-to-remote drag creates neither copy nor queued transfer.
    previous=worker.tool("neyvia.devices.transfers",{})
    req_start=len(requests)
    _path_row(remote,remote_source).drag_to(remote.locator(".nx-files-list"))
    worker.page.wait_for_timeout(500)
    unchanged=worker.tool("neyvia.devices.transfers",{})==previous
    refused=not any(r.get("op") in {"files.send","files.fetch"} for r in requests[req_start:])
    checks.append(_check("c8e.drop-remote-remote-no-effect",unchanged and refused,{"before":previous,"after":worker.tool("neyvia.devices.transfers",{}),"actualRequests":requests[req_start:]},"rendered-user-action"))
    # Transfer helpers consume the actual durable transfer; finished rows retain
    # checked byte count. A separate real queued transfer is paused at a known
    # measured byte count so the mounted progressbar can be checked directly.
    done_row=worker.page.locator(".nx-pc-transfer").filter(has=worker.page.get_by_text(local_source.name,exact=True))
    done_row.locator(".nx-pc-transfer-line").wait_for(timeout=30000)
    line=done_row.locator(".nx-pc-transfer-line").inner_text()
    expected=f'Done \u00b7 {sent["size"]} B \u00b7 checked' 
    checks.append(_check("c8e.transfer-line-actual-done",line==expected,{"actualTransfer":sent,"mountedLine":line,"expected":expected},"rendered-user-action"))
    # Completed state still invokes transferFraction in the real TransferRow.
    # Fresh production pause/resume progress is mandatory for its visible effect.
    big=base/"c8e-progress.bin"
    with big.open("wb") as stream:
        for _ in range(48): stream.write(bytes(range(256))*4096)
    started=owner(worker,"/api/ui/devices",{"op":"files.send","args":{"device":device_id,"from":str(big)}})["transfer"]
    paused=None
    if started["status"] in {"running","queued"}:
        owner(worker,"/api/ui/devices",{"op":"transfer.pause","args":{"id":started["id"]}})
    for _ in range(100):
        actual=worker.tool("neyvia.devices.transfers",{"id":started["id"]})["transfers"][0]
        if actual["status"]=="paused":
            paused=actual
            break
        if actual["status"] in {"running","queued"}:
            owner(worker,"/api/ui/devices",{"op":"transfer.pause","args":{"id":actual["id"]}})
            paused=worker.tool("neyvia.devices.transfers",{"id":actual["id"]})["transfers"][0]
            break
        if actual["status"] in {"done","failed"}: break
        worker.page.wait_for_timeout(20)
    progress_ok=False
    progress_observed={"started":started,"paused":paused}
    if paused:
        progress_row=worker.page.locator(".nx-pc-transfer").filter(has=worker.page.get_by_text(big.name,exact=True))
        progress_row.get_by_role("progressbar").wait_for(timeout=30000)
        value=progress_row.get_by_role("progressbar").get_attribute("aria-valuenow")
        fraction=max(0,min(1,paused["done"]/paused["size"]))
        progress_ok=int(value)==int(fraction*100+0.5)
        progress_observed.update(mountedPercent=value,expectedPercent=int(fraction*100+0.5),mountedLine=progress_row.locator(".nx-pc-transfer-line").inner_text())
        progress_row.get_by_role("button",name="Resume",exact=True).click()
        resumed=_wait_transfer(worker,set(),big)
        progress_ok=progress_ok and resumed["status"]=="done" and Path(resumed["to"]).is_file() and hashlib.sha256(Path(resumed["to"]).read_bytes()).hexdigest()==hashlib.sha256(big.read_bytes()).hexdigest()
        progress_observed["resumed"]=resumed
    checks.append(_check("c8e.transfer-fraction-real-paused-resumed",progress_ok,progress_observed,"rendered-user-action"))
    worker.page.remove_listener("request",record)
    worker.observe()
    all_pass=all(c["passed"] for c in checks)
    contracts=[{"id":identity,"passed":all_pass,"fresh":True,"boundary":"rendered-user-action","observed":{"checks":checks,"artifact":worker.screenshot("effect-cross-pc"),"peerBoundary":"Two independently rooted services on this PC; no second-machine or WAN claim"}} for identity in binding["c8eEffect"]["requiredContractIds"]]
    return checks,{"contractEffects":contracts,"rendered":{"witness":"cross-pc-live","url":worker.page.url}}

def run_effects(worker,binding,inputs,root):
    from c8e_effects import after_manual
    import c8e_effects
    if not hasattr(worker,"c8e_effect"): before_manual(worker,binding,inputs,root)
    def witness(w,e,r):
        if e.get("renderedWitness")=="cross-pc-live": return _cross_pc(w,binding,r)
        if e.get("renderedWitness")=="adapter-owner": return _adapter_witness(w,binding,r)
        if e.get("renderedWitness")=="outputs-model-real": return _outputs_models(w,binding,r)
        if e.get("renderedWitness")=="nightshift-model-real": return _nightshift_models(w,binding,r)
        return c8e_effects._rendered_witness(w,e,r)
    skip=worker.page.get_by_role("button",name="Skip setup",exact=True)
    # Reload can complete before onboarding's async owner snapshot arrives.
    # Wait for that actual dialog before starting any rendered procedure.
    for _ in range(60):
        if skip.count() and skip.is_visible(): break
        worker.page.wait_for_timeout(100)
    if skip.count() and skip.is_visible():
        skip.click(timeout=30000)
        worker.page.locator(".nx-onb-scrim").wait_for(state="hidden",timeout=30000)
    return after_manual(worker,inputs,root,witness=witness)

def _contract(identity,passed,observed,boundary="rendered-user-action"):
    return {"id":identity,"passed":bool(passed),"fresh":True,"boundary":boundary,"observed":observed}

def nightshift_command(path):
    """Exact admitted terminal probe: write owned bytes and report actual output."""
    import uuid
    target=Path(path).resolve()
    target.relative_to(Path("C:/Users/user/Projects/nx-c8-inception/.agent_control/proofs/C8"))
    if target!=Path.cwd().resolve()/"c8/command.txt":raise ValueError("NightShift probe target differs from its task root")
    target.parent.mkdir(exist_ok=True)
    value="Actual NightShift command output "+uuid.uuid4().hex
    target.write_text(value+"\n",encoding="utf-8",newline="\n")
    print(value,flush=True)
    return {"path":str(target),"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"output":value}

def _outputs_models(worker,binding,root):
    root=Path(root);base=root/"c8";base.mkdir(exist_ok=True)
    path=base/"actual-observed-file.txt";content="Real file observation retains the full drive path and this exact content: "+worker.args.run_id
    path.write_text(content,encoding="utf-8",newline="\n")
    title="C8e actual parsed file output"
    published=worker.tool("neyvia.artifact.publish",{"path":str(path),"kind":"file","title":title,"requestId":"c8e-model-output"})
    calls=[]
    def record(request):
        if request.url.endswith("/api/ui/tools/call") and request.method=="POST": calls.append(request.post_data_json)
    worker.page.on("request",record)
    worker.tool("neyvia.app.open",{"app":"outputs"})
    worker.page.locator(".nx-out-row").filter(has=worker.page.get_by_text(title,exact=True)).click(timeout=30000)
    worker.page.get_by_role("button",name="See as the agent",exact=True).click(timeout=30000)
    worker.page.locator(".nx-pcv").wait_for(timeout=30000)
    worker.page.get_by_role("radio",name="Exact",exact=True).click()
    worker.page.locator(".nx-pcv-pre").wait_for(timeout=30000)
    actual=json.loads(worker.page.locator(".nx-pcv-pre").inner_text())
    source_calls=[r for r in calls if r.get("tool")=="neyvia.perception.observe"]
    target_ok=bool(source_calls) and source_calls[-1]["arguments"]=={"layer":"file","source":{"path":str(path)}}
    read=worker.tool("workspace.read",{"path":str(path)})
    observed_ok=actual.get("source",{}).get("path")==str(path) and actual.get("state",{}).get("sha256")==read["sha256"] and actual.get("state",{}).get("text")==content
    checks=[_check("c8e.outputs.actual-file-target-and-fresh-observation",target_ok and observed_ok,{"published":published,"actualRequest":source_calls,"mountedExact":actual,"freshNativeReader":read},"rendered-user-action")]
    page_path=base/"actual-browser-page.html"
    page_title="Actual C8e own browser observation "+worker.args.run_id
    page_path.write_text('<!doctype html><title>'+page_title+'</title><h1>'+page_title+'</h1><label>Owned text<input value="actual DOM value"></label>',encoding="utf-8",newline="\n")
    worker.tool("neyvia.pane.show",{"kind":"artifact","target":str(page_path)})
    preview=worker.page.locator(".nx-ap-frame");preview.wait_for(timeout=30000)
    worker.page.frame_locator(".nx-ap-frame").get_by_role("heading",name=page_title,exact=True).wait_for(timeout=30000)
    from urllib.parse import urljoin
    page_url=urljoin(worker.args.candidate_url,preview.get_attribute("src"))
    worker.tool("neyvia.pane.show",{"kind":"perception","target":"browser:"+page_url})
    worker.page.locator('.nx-pcv').get_by_role("radio",name="Exact",exact=True).click()
    browser_exact=worker.page.locator('.nx-pcv-text .nx-pcv-pre')
    browser_value={}
    for _ in range(180):
        if browser_exact.count():browser_value=json.loads(browser_exact.inner_text())
        if browser_value.get("layer")=="browser" and browser_value.get("state",{}).get("title")==page_title:break
        worker.page.wait_for_timeout(250)
    browser_ok=browser_value.get("layer")=="browser" and browser_value.get("state",{}).get("title")==page_title and page_title in browser_value.get("state",{}).get("text","") and any(row.get("value")=="actual DOM value" for row in browser_value.get("state",{}).get("elements",[]))
    checks.append(_check("c8e.outputs.actual-http-browser-parser-observation",browser_ok,{"url":page_url,"freshSource":worker.tool("workspace.read",{"path":str(page_path)}),"mountedExact":browser_value},"rendered-user-action"))
    invalid=[]
    for value in ("file:","image:","browser:javascript:alert(1)","window:opaque:1.5","window::17","unknown:content"):
        before=len(calls)
        refusal=None
        try:
            worker.tool("neyvia.pane.show",{"kind":"perception","target":value})
            worker.page.get_by_text("Nothing to read",exact=True).wait_for(timeout=15000)
            worker.page.wait_for_timeout(150)
        except Exception as error:refusal=getattr(error,"reply",str(error))
        requested=[r for r in calls[before:] if r.get("tool") in {"neyvia.perception.observe","neyvia.perception.browser.open","neyvia.perception.project"}]
        cleanup=[r for r in calls[before:] if r.get("tool")=="neyvia.perception.browser.close"]
        invalid.append({"target":value,"mountedNothingToRead":refusal is None,"gatewayRefusal":refusal,"sourceRequests":requested,"priorOwnedBrowserCleanup":cleanup,"passed":refusal is None and not requested})
    checks.append(_check("c8e.outputs.invalid-targets-no-observation",all(r["passed"] for r in invalid),{"cases":invalid},"rendered-user-action"))
    # Floating uses the real saved user conversation. It cannot imply that an
    # assistant or provider executed the authored note.
    conversation=worker.step_results["extraOutputConversation"];identity=conversation["id"]
    canonical_before=worker.tool("backend:connected_session_read_command",{"id":identity,"limit":100})
    worker.page.locator(".nx-side").get_by_text(conversation["title"],exact=True).click(timeout=30000)
    worker.tool("neyvia.app.open",{"app":"outputs"})
    header=worker.page.locator(".nx-work-chat .nx-head.is-draggable")
    header.wait_for(timeout=30000)
    def drag(x,y):
        start=header.locator(".nx-head-title").bounding_box()
        worker.page.mouse.move(start["x"]+min(40,start["width"]/2),start["y"]+start["height"]/2)
        worker.page.mouse.down();worker.page.mouse.move(x,y,steps=16);worker.page.mouse.up()
        worker.page.wait_for_timeout(200)
    dock=worker.page.locator(".nx-work-chat").bounding_box()
    before=worker.page.locator(".nx-bubble-float").count()
    drag(dock["x"]+dock["width"]/2,dock["y"]+dock["height"]/2)
    inside=worker.page.locator(".nx-bubble-float").count()==before and header.is_visible()
    measurements=[]
    for side,y in (("left",250),("right",600),("left",0),("right",100000)):
        viewport=worker.page.viewport_size
        dock=worker.page.locator(".nx-work-chat").bounding_box()
        x=20 if side=="left" else (dock["x"]-40 if dock["x"]>viewport["width"]/2+40 else dock["x"]+dock["width"]+40)
        x=min(x,viewport["width"]-20);y=min(y,viewport["height"]-1)
        drag(x,y)
        bubble=worker.page.locator(".nx-bubble-float").filter(has=worker.page.locator(".nx-bubble-mark"))
        if not bubble.count():bubble=worker.page.locator(".nx-bubble-float")
        bubble.wait_for(timeout=15000)
        box=bubble.bounding_box()
        wanted_x=10 if x<viewport["width"]/2 else viewport["width"]-52-10
        wanted_y=min(viewport["height"]-52-40,max(10,y-26))
        sample={"released":{"x":x,"y":y},"viewport":viewport,"box":box,"expected":{"x":wanted_x,"y":wanted_y},"passed":abs(box["x"]-wanted_x)<1 and abs(box["y"]-wanted_y)<1}
        measurements.append(sample)
        dock_button=worker.page.get_by_role("button",name="Dock beside the app",exact=True)
        if not dock_button.count() or not dock_button.is_visible():bubble.click()
        dock_button.click(timeout=15000)
        header.wait_for(timeout=15000)
    canonical_after=worker.tool("backend:connected_session_read_command",{"id":identity,"limit":100})
    unchanged=canonical_after==canonical_before
    checks.append(_check("c8e.outputs.dock-drop-inside-preserves-chat",inside and unchanged,{"insideDropNoBubble":inside,"before":canonical_before,"after":canonical_after},"rendered-user-action"))
    checks.append(_check("c8e.outputs.actual-outside-drop-measured-side-and-height",all(m["passed"] for m in measurements) and unchanged,{"drops":measurements,"sameSavedConversation":unchanged},"rendered-user-action"))
    worker.page.remove_listener("request",record)
    contract=[_contract("outputs.perceptionTarget",False,{"actualFile":checks[0],"missingCase":"The window target variant requires the C11 isolated native session."}),_contract("outputs.parsePerceptionTarget",False,{"actualFile":checks[0],"actualHttpBrowser":checks[1],"actualInvalidTargets":checks[2],"missingCase":"Actual accepted window/session delimiter case requires the C11 isolated native session. Image source variant requires a genuine authorized visual extraction transport; no fake device/provider is substituted."}),_contract("outputs.outsideDock",inside and all(m["passed"] for m in measurements) and unchanged,checks[3:]),_contract("outputs.dropSpot",all(m["passed"] for m in measurements) and unchanged,checks[4])]
    worker.observe()
    return checks,{"contractEffects":contract,"rendered":{"witness":"outputs-model-real","artifact":worker.screenshot("effect-output-models")},"missingSourceCases":["outputs.parsePerceptionTarget actual window/session delimiter and image-source variants remain unproved; file and malformed-target cases are independently exercised"]}


def _nightshift_models(worker,binding,root):
    from c8e_prerequisites import owner
    root=Path(root);base=root/"c8";base.mkdir(exist_ok=True)
    def ns(action,args=None):
        return owner(worker,"/api/backend",{"command":"nightshift_"+action+"_command","payload":args or {}})
    initial_policy=ns("resources",{"paused":True,"maxConcurrent":2})
    # Neither dormant creation nor arming under this actual paused policy may
    # launch a harness, consume provider tokens, or write outside the test root.
    ids={name:"c8e-"+name for name in ("file","after","paul","blocked","commit","command","missing")}
    def create(name,**fields):
        return ns("create",{"id":ids[name],"title":"Actual "+name+" task","prompt":"Authored dormant C8e task "+name,"folder":str(base),"owner":"Codex","harness":"codex",**fields})
    create("file");create("after",needs=[ids["file"]]);create("paul",owner="Paul",harness=None)
    create("blocked");ns("block",{"id":ids["blocked"],"reason":"Actual owned prerequisite remains unavailable"})
    report=worker.step_results["extraNightshiftGitProducer"].get("producer",{})
    git_area=next(a for a in report["areas"] if a["area"]=="proofs-b-adapters")
    objects=next(c["observed"] for c in git_area["checks"] if c.get("contract")=="adapters.git.objects")
    git_receipt=objects["independentReceipts"][0]
    git_read=worker.tool("workspace.read",{"path":git_receipt["path"]})
    git_data=json.loads(git_read["content"])
    operation=objects["operations"][0]
    if git_read["sha256"]!=git_receipt["sha256"] or git_data["lineage"]["sources"][0]["head"]!=operation["head"]:
        raise RuntimeError("Actual disposable Git receipt changed before NightShift used its commit")
    repository=Path(operation["repository"])
    if not repository.is_absolute():repository=Path(git_receipt["path"]).parents[len(Path(operation["receipt"]["path"]).parts)-1]/repository
    # Use the actual repo retained by the selected Git producer, not a made-up
    # commit label or an unrelated source-repository object.
    repository=Path(operation.get("repositoryPath",repository))
    create("commit",folder=str(repository));create("command")
    mission=worker.tool("neyvia.mission.create",{"id":"c8e-hidden-mission","goal":"Preserve a dormant actual mission separately from the NightShift board","folder":str(base),"acceptanceChecks":["No task is armed"],"tasks":[{"id":"dormant","title":"Actual mission-only task","prompt":"Stored only; do not launch","harness":"codex","owner":"Codex","permissionMode":"read-only"}]})
    worker.tool("neyvia.pane.show",{"kind":"mission","target":"nightshift"})
    pane=worker.page.locator(".nx-ns");pane.wait_for(timeout=30000)
    worker.page.locator('[data-ns-task="'+ids["after"]+'"]').wait_for(timeout=30000)
    def current():return ns("tasks")
    checks=[];contracts=[]
    start=pane.locator(".nx-ns-start");start.wait_for(timeout=30000)
    before=current();before_rows=before.get("tasks",before) if isinstance(before,dict) else before
    eligible=[t["id"] for t in before_rows if not t.get("missionId") and t["owner"]!="Paul" and not t["armed"] and t["status"]=="waiting"]
    initial_label=start.inner_text().strip();start.click()
    for _ in range(100):
        after=current();after_rows=after.get("tasks",after) if isinstance(after,dict) else after
        if all(next(t for t in after_rows if t["id"]==identity)["armed"] for identity in eligible):break
        worker.page.wait_for_timeout(100)
    armed=[t["id"] for t in after_rows if t["armed"]]
    start_ok=initial_label=="Start "+str(len(eligible)) and set(armed)==set(eligible) and all(t["status"]!="running" and not t.get("runId") for t in after_rows) and ns("resources")["paused"] is True
    checks.append(_check("c8e.nightshift.actual-startable-paused-arming",start_ok,{"before":before_rows,"eligible":eligible,"mountedStart":initial_label,"after":after_rows,"policy":initial_policy},"rendered-user-action"))
    contracts.append(_contract("nightshift.startable",start_ok,checks[-1]))
    # Real UI completion: the typed evidence is verified by the original owner.
    evidence_file=base/"actual-evidence.txt";evidence_file.write_text("Actual checked NightShift file "+worker.args.run_id,encoding="utf-8",newline="\n")
    def tick_form(name,kind,value,output=None):
        pane.locator('[data-ns-task="'+ids[name]+'"]').click()
        detail=pane.get_by_role("complementary",name="Task Actual "+name+" task",exact=True)
        detail.wait_for(timeout=30000)
        worker.page.wait_for_timeout(150)
        detail.get_by_role("button",name="Mark done…",exact=True).click()
        form=detail.get_by_role("form",name="Mark done with evidence",exact=True)
        form.get_by_role("radio",name=kind,exact=True).click()
        label={"File":"File, inside the task's folder","Commit":"Commit in the task's folder","Command":"Command you ran"}[kind]
        form.get_by_label(label,exact=True).fill(value)
        if output is not None:form.get_by_label("What it printed",exact=True).fill(output)
        form.get_by_role("button",name="Mark done",exact=True).click()
        for _ in range(100):
            rows=current();rows=rows.get("tasks",rows) if isinstance(rows,dict) else rows
            task=next(t for t in rows if t["id"]==ids[name])
            if task["status"]=="done":
                pane.locator('[data-ns-task="'+ids[name]+'"].is-done').wait_for(timeout=30000)
                form.wait_for(state="hidden",timeout=30000)
                return task
            worker.page.wait_for_timeout(100)
        raise RuntimeError("Actual evidence did not complete "+name+": "+detail.inner_text())
    done_file=tick_form("file","File",str(evidence_file))
    done_commit=tick_form("commit","Commit",operation["head"])
    command_body="import runpy; runpy.run_path('scripts/c8e_extra_effects.py')['nightshift_command']('c8/command.txt')"
    command=worker.tool("terminal.exec",{"command":command_body,"shell":"python","cwd":str(root),"timeoutMs":15000,"maxOutputChars":3000})
    while isinstance(command,dict) and isinstance(command.get("data"),dict):command=command["data"]
    while isinstance(command,dict) and isinstance(command.get("result"),dict):command=command["result"]
    printed=command["stdout"].strip()
    command_read=worker.tool("workspace.read",{"path":str(base/"command.txt")})
    command_ok=command["exitCode"]==0 and command_read["content"].strip()==printed and printed.startswith("Actual NightShift command output ")
    done_command=tick_form("command","Command",command_body,printed)
    refusals=[]
    for label,args in (("owner-command-rejected-from-bot",{"id":ids["paul"],"evidence":{"type":"command","command":command_body,"exitCode":0,"output":printed}}),("file-outside-task-folder",{"id":ids["paul"],"evidence":{"type":"file","path":str(ROOT/"README.md")}}),("done-evidence-immutable",{"id":ids["file"],"evidence":{"type":"file","path":str(base/"command.txt")}}),("unowned-run-evidence",{"id":ids["paul"],"evidence":{"type":"run","runId":"not-an-actual-owned-run"}})):
        try:worker.tool("neyvia.nightshift.tick",args)
        except Exception as error:refusals.append({"case":label,"refused":True,"actualReply":getattr(error,"reply",str(error))})
        else:refusals.append({"case":label,"refused":False})
    worker.page.wait_for_timeout(600)
    morning=pane.get_by_role("region",name="Morning summary",exact=True)
    morning.wait_for(timeout=30000)
    evidence_rows=morning.get_by_role("list",name="Done",exact=True)
    file_link=evidence_rows.get_by_role("button",name=evidence_file.name,exact=True)
    file_title=file_link.get_attribute("title")
    commit_label=evidence_rows.get_by_role("button",name="Commit "+operation["head"][:8],exact=True).get_attribute("title")
    command_label=evidence_rows.locator(".nx-ns-ev.is-static").filter(has_text="your word")
    command_detail=command_label.get_attribute("title")
    evidence_ok=command_ok and file_title==str(evidence_file)+"\nSHA-256 "+hashlib.sha256(evidence_file.read_bytes()).hexdigest() and commit_label==operation["head"]+" · copy" and command_detail==command_body+"\nexit 0\n"+printed and all(r["refused"] for r in refusals)
    file_link.click();worker.page.get_by_label("File text",exact=True).wait_for(timeout=30000)
    evidence_ok=evidence_ok and worker.page.get_by_label("File text",exact=True).input_value()==evidence_file.read_text()
    worker.tool("neyvia.pane.show",{"kind":"mission","target":"nightshift"})
    pane.wait_for(timeout=30000)
    checks.append(_check("c8e.nightshift.real-file-commit-owner-command-evidence",evidence_ok,{"file":done_file,"commit":done_commit,"command":done_command,"actualTerminal":command,"freshCommandArtifact":command_read,"mountedFileTitle":file_title,"mountedCommitTitle":commit_label,"mountedCommandTitle":command_detail,"adverseRefusals":refusals},"rendered-user-action"))
    contracts.append(_contract("nightshift.evidenceView",False,{"actualProvedVariants":checks[-1],"missingCase":"Actual task-owned completed harness run and its canonical chat opening; no provider run was started or invented."}))
    create("missing",needs=["c8e-absent-prerequisite"])
    pane.locator('[data-ns-task="'+ids["missing"]+'"]').get_by_text("Missing: c8e-absent-prerequisite",exact=True).wait_for(timeout=30000)
    summary=ns("summary");rows=summary["tasks"];local=[r for r in rows if not r.get("missionId")]
    rendered_levels=pane.locator(".nx-ns-level").evaluate_all("es=>es.map(e=>[...e.querySelectorAll('[data-ns-task]')].map(c=>c.dataset.nsTask))")
    expected_first=[r["id"] for r in local if r["id"]!=ids["after"]]
    shape_ok=rendered_levels==[expected_first,[ids["after"]]] and pane.locator(".nx-ns-edges path").count()==1 and pane.get_by_text("Show 1 mission task too",exact=True).count()==1 and not pane.locator('[data-ns-task="c8e-hidden-mission:dormant"]').count()
    mission_toggle=pane.get_by_label("Show 1 mission task too",exact=True);mission_toggle.check()
    pane.locator('[data-ns-task="c8e-hidden-mission:dormant"]').wait_for(timeout=30000)
    mission_toggle.uncheck()
    worker.page.wait_for_timeout(250)
    checks.append(_check("c8e.nightshift.actual-graph-dependencies-mission-toggle",shape_ok,{"actualSummary":summary,"mountedLevels":rendered_levels,"mission":mission},"rendered-user-action"))
    contracts.append(_contract("nightshift.shapeBoard",shape_ok,checks[-1]))
    leaves=pane.locator(".nx-ns-tree .nx-ns-leaf").evaluate_all("es=>es.map(e=>({title:e.querySelector('title').textContent,transform:e.parentElement.getAttribute('transform'),scale:e.getAttribute('transform'),class:e.getAttribute('class')}))")
    expected_leaves=[];task_by_id={t["id"]:t for t in local}
    step=min(34,124/max(1,len(rendered_levels)))
    for level,identities in enumerate(rendered_levels):
        for side in (0,1):
            members=[identity for index,identity in enumerate(identities) if (index+level)%2==side]
            spacing=min(22,110/max(1,len(members)));sign=-1 if side==0 else 1
            for index,identity in enumerate(members):
                task=task_by_id[identity];x=140+sign*(18+spacing*index+spacing*.6)
                y=168-26-level*step+4-index*1.6-(x-140)*sign*.06
                angle=38 if task["status"]=="blocked" else -24 if task["status"]=="done" else -32
                words="waiting on you" if task["status"]=="waiting" and task["owner"]=="Paul" else task["status"]
                expected_leaves.append({"title":task["title"]+": "+words,"transform":f'translate({round(x,1):g} {round(y,1):g}) scale({sign} 1) rotate({angle})',"scale":"scale("+str(1 if task["status"]=="done" else .86 if task["status"]=="blocked" else .6)+")"})
    leaf_ok=len(leaves)==len(local) and all({k:actual[k] for k in expected}==expected for actual,expected in zip(leaves,expected_leaves))
    checks.append(_check("c8e.nightshift.measured-real-task-tree",leaf_ok,{"leaves":leaves,"expectedActualTaskGeometry":expected_leaves,"actualTasks":local},"rendered-user-action"))
    contracts.append(_contract("nightshift.treeLayout",leaf_ok,checks[-1]))
    morning=pane.get_by_role("region",name="Morning summary",exact=True)
    counts_ok=morning.get_by_text("3 done · 1 blocked · 1 waiting on you",exact=True).count()==1 and morning.get_by_role("list",name="Blocked",exact=True).get_by_text("Actual owned prerequisite remains unavailable",exact=True).count()==1 and morning.get_by_role("list",name="Waiting on you",exact=True).get_by_text("Actual paul task",exact=True).count()==1 and "0 tokens" in morning.inner_text()
    checks.append(_check("c8e.nightshift.actual-morning-counts-and-evidence",counts_ok,{"actualSummary":summary,"mountedText":morning.inner_text()},"rendered-user-action"))
    contracts.append(_contract("nightshift.morning",False,{"actualProvedCases":checks[-1],"missingCase":"Completed run with missing token report and evidence-link precedence over actual task-owned run; requires a genuine harness run."}))
    policy_checks,policy_contracts=_nightshift_budget(worker,pane,ns)
    checks.extend(policy_checks);contracts.extend(policy_contracts)
    final_summary=ns("summary")
    final_owned=[t for t in final_summary["tasks"] if t["id"] in ids.values()]
    final_by_id={t["id"]:t for t in final_owned}
    retained=all(not t.get("runId") and t["status"]!="running" for t in final_summary["tasks"]) and ns("resources")["paused"] is True and all(final_by_id[t["id"]]["evidence"]==t["evidence"] for t in (done_file,done_commit,done_command))
    checks.append(_check("c8e.nightshift.final-fresh-evidence-and-no-provider-dispatch",retained,{"finalActualSummary":final_summary,"freshPolicy":ns("resources"),"originalCompletions":[done_file,done_commit,done_command]},"production-state"))
    worker.observe()
    return checks,{"contractEffects":contracts,"rendered":{"witness":"nightshift-model-real","artifact":worker.screenshot("effect-nightshift-models")},"missingSourceCases":["nightshift.evidenceView: real own completed run/canonical chat","nightshift.morning: actual completed unreported run and run evidence precedence"]}


def _nightshift_budget(worker,pane,ns):
    checks=[];contracts=[]
    saved=ns("resources",{"paused":True,"maxConcurrent":2,"maxNightSeconds":5400,"maxTaskSeconds":90,"maxTaskTokens":400,"holdAtPlanPercent":70,"gpuReservedFor":"ASR","quietGpuHours":{"start":"08:00","end":"23:00","timeZone":"UTC"},"perHarnessBudgets":{"codex":{"maxTokens":1200,"maxSeconds":7200},"opencode":{"maxSeconds":3600}}})
    pane.get_by_role("button",name="Budget",exact=True).click()
    form=pane.get_by_role("form",name="Budget and quiet hours",exact=True);form.wait_for(timeout=30000)
    def field(label,scope=None):
        return (scope or form).locator("label").filter(has=worker.page.get_by_text(label,exact=True)).locator("input")
    for _ in range(100):
        if field("Hours per night").input_value()=="1.5":break
        worker.page.wait_for_timeout(100)
    fields={label:field(label).input_value() for label in ("Hours per night","Minutes per task","Tasks at once","Tokens per task","Codex tokens","Codex hours","OpenCode hours","Hold at","From","To")}
    form_ok=fields=={"Hours per night":"1.5","Minutes per task":"1.5","Tasks at once":"2","Tokens per task":"400","Codex tokens":"1200","Codex hours":"2","OpenCode hours":"1","Hold at":"70","From":"08:00","To":"23:00"} and field("OpenCode tokens").is_disabled()
    checks.append(_check("c8e.nightshift.saved-policy-converts-in-mounted-form",form_ok,{"saved":saved,"mountedFields":fields,"OpenCodeTokenInputDisabled":field("OpenCode tokens").is_disabled()},"rendered-user-action"))
    contracts.append(_contract("nightshift.policyForm",form_ok,checks[-1]))
    quiet=[]
    clock=form.locator("label").filter(has=worker.page.get_by_text("Clock",exact=True)).locator("select")
    def hh(mm):return f"{(mm%1440)//60:02}:{mm%60:02}"
    for zone in ("UTC","local"):
        clock.select_option(zone)
        def actual_minute():
            return worker.page.evaluate("()=>{const n=new Date();return {utc:n.getUTCHours()*60+n.getUTCMinutes(),local:n.getHours()*60+n.getMinutes()}} ")[zone.lower()]
        for label,start_offset,end_offset,wanted in (("equal-all-day",0,0,True),("inclusive-start",0,1,True),("exclusive-end",-1,0,False),("wrap-midnight",1,0,False)):
            attempts=[]
            for _ in range(3):
                now=actual_minute();start=now+start_offset;end=now+end_offset
                field("From").fill(hh(start));field("To").fill(hh(end));worker.page.wait_for_timeout(40)
                text=form.locator(".nx-ns-quiet-now").inner_text();after=actual_minute()
                attempts.append({"beforeMinute":now,"afterMinute":after,"mounted":text})
                if now==after:break
            quiet.append({"clock":zone,"case":label,"observedClockMinute":now,"start":hh(start),"end":hh(end),"mounted":text,"wanted":wanted,"realClockAttempts":attempts,"passed":now==after and text==("Quiet now" if wanted else "Not quiet now")})
    quiet_ok=all(c["passed"] for c in quiet)
    checks.append(_check("c8e.nightshift.real-clock-quiet-window-boundaries",quiet_ok,{"cases":quiet,"clockWasNotInjected":True},"rendered-user-action"))
    contracts.append(_contract("nightshift.quietNow",quiet_ok,checks[-1]))
    field("Hours per night").fill("-1")
    field("Tasks at once").fill("1.5")
    field("Hold at").fill("101")
    field("From").fill("")
    problems=form.locator(".nx-ns-problems").inner_text()
    invalid_ok=form.get_by_role("button",name="Save budget",exact=True).is_disabled() and all(s in problems for s in ("Hours per night must be more than 0","Tasks at once must be a whole number","The plan hold must be a whole number","Quiet hours need times like")) and ns("resources")==saved
    # This is an actual accepted owner policy, held by the engine because
    # OpenCode cannot report live token usage. Its real loaded disabled input
    # exercises the form's rejection without injecting React or DOM state.
    unsupported=ns("resources",{"perHarnessBudgets":{"codex":{"maxTokens":1200,"maxSeconds":7200},"opencode":{"maxTokens":250,"maxSeconds":3600}}})
    for _ in range(100):
        if field("OpenCode tokens").input_value()=="250":break
        worker.page.wait_for_timeout(100)
    unsupported_problem=form.locator(".nx-ns-problems").inner_text()
    opencode_ok=field("OpenCode tokens").input_value()=="250" and field("OpenCode tokens").is_disabled() and "OpenCode doesn't report tokens while it works yet" in unsupported_problem and form.get_by_role("button",name="Save budget",exact=True).is_disabled() and ns("resources")==unsupported
    ns("resources",saved)
    for _ in range(100):
        if field("Hours per night").input_value()=="1.5" and field("OpenCode tokens").input_value()=="":break
        worker.page.wait_for_timeout(100)
    field("Hours per night").fill("1,25")
    field("Tasks at once").fill("3")
    field("Hold at").fill("75")
    field("Minutes per task").fill("2,5")
    field("Codex tokens").fill("1_500")
    field("From").fill("00:00");field("To").fill("00:00")
    clock.select_option("local")
    form.get_by_role("button",name="Save budget",exact=True).click()
    fresh=None
    for _ in range(100):
        fresh=ns("resources")
        if fresh.get("maxConcurrent")==3:break
        worker.page.wait_for_timeout(100)
    patch_ok=invalid_ok and opencode_ok and fresh["paused"] is True and fresh["maxNightSeconds"]==4500 and fresh["maxTaskSeconds"]==150 and fresh["maxConcurrent"]==3 and fresh["holdAtPlanPercent"]==75 and fresh["perHarnessBudgets"]["codex"]["maxTokens"]==1500 and fresh["quietGpuHours"]=={"start":"00:00","end":"00:00","timeZone":"local"}
    form.get_by_role("button",name="Close",exact=True).click();pane.get_by_role("button",name="Budget",exact=True).click()
    reopened=pane.get_by_role("form",name="Budget and quiet hours",exact=True)
    for _ in range(100):
        if field("Hours per night",reopened).input_value()=="1.3" and field("Minutes per task",reopened).input_value()=="2.5":break
        worker.page.wait_for_timeout(100)
    persisted=field("Hours per night",reopened).input_value()=="1.3" and field("Minutes per task",reopened).input_value()=="2.5" and ns("resources")==fresh
    checks.append(_check("c8e.nightshift.invalid-policy-refused-real-save-persisted",patch_ok and persisted,{"before":saved,"visibleProblems":problems,"acceptedUnsupportedOwnerPolicy":unsupported,"mountedOpenCodeProblem":unsupported_problem,"unsupportedBudgetSaveBlocked":opencode_ok,"freshPolicy":fresh,"reopenedHours":field("Hours per night",reopened).input_value(),"dispatchPolicyRemainsPaused":fresh["paused"] is True},"rendered-user-action"))
    contracts.append(_contract("nightshift.policyPatch",patch_ok and persisted,checks[-1]))
    return checks,contracts


ADAPTER_CHAPTERS = {
    "git": ["adapters.git.objects","adapters.git.safety","adapters.git.readiness","adapters.git.artifact-registration"],
    "handoff": ["adapters.handoff.progress"],
    "html": ["adapters.html.scoring"],
    "ocr": ["adapters.ocr.boundaries"],
    "publication": ["adapters.workflow.publication"],
    "sync": ["adapters.sync.compatibility","adapters.sync.policy"],
    "release": ["adapters.release.selection","adapters.release.update","adapters.release.staging"],
}

def adapter_chapters(root, chapters):
    """Selected original owner actions; never claim the full adapter area.

    The production verifier writes its own partial receipt. These observations
    are generated by original owners, with their actual files and postconditions.
    """
    chapters=list(chapters)
    if not chapters or len(set(chapters))!=len(chapters) or set(chapters)-ADAPTER_CHAPTERS.keys():
        raise ValueError("Explicit unique supported adapter chapters are required")
    root=Path(root).resolve()
    root.relative_to(ROOT / ".agent_control/proofs/C8")
    root.mkdir(parents=True,exist_ok=True)
    checks=[]
    for chapter in chapters:
        folder=root/chapter
        folder.mkdir(exist_ok=True)
        checks.extend(globals()["_adapter_"+chapter](folder))
    rejections=[]
    for check in checks:
        for refusal in check.get("observed",{}).get("refusals",[]):
            if refusal.get("refused") is True:
                rejections.append({"contract":check["contract"],**refusal})
    return {"ok":all(c["ok"] for c in checks),"contracts":[c for chapter in chapters for c in ADAPTER_CHAPTERS[chapter]],
            "checks":checks,"rejections":rejections,"selectedChapters":chapters,"partial":True,
            "frontier":["Selected chapter owners only; native sync, provider execution and all undeclared adapter chapters remain unproved."]}

def _adapter_check(identity, passed, observed, invariant=None):
    return {"id":invariant or identity,"contract":identity,"ok":bool(passed),"observed":observed,"boundary":"production-state"}

def _adapter_handoff(root):
    from dataclasses import asdict
    from grant_agent.handoff import create_handoff_packet,save_handoff_packet
    from grant_agent.models import RunState,PromptStack,PersonaProfile
    from grant_agent.context_manager import ContextWindowManager
    from grant_agent.native_tools import NativeToolRegistry
    state=RunState(objective="Continue actual local artifact",plan_steps=["Inspect","Implement","Verify"],completed_steps=["Inspect"],acceptance_checks=["Read exact final artifact"],next_actions=["Implement"],changed_files=["artifact.txt"],decisions=["Preserve previous bytes"])
    stack=PromptStack(base_constitution="Read before editing",project_profile="Own disposable local artifact",persona=PersonaProfile(name="local-owner",tone="plain",risk_tolerance="low",creativity_level="low",coding_style="small",verbosity="short"),task_brief="Resume the remaining artifact steps",step_policy="Verify exact bytes")
    context=ContextWindowManager(max_tokens=200)
    context.record("user","Continue from the remaining steps")
    packet=create_handoff_packet("c8e-actual-session","c8e-parent","context_rollover",state,stack,context)
    saved=save_handoff_packet(packet,root,1)
    # Fresh independent consumer through the original filesystem tool owner.
    read=NativeToolRegistry(root).call("workspace.read",{"path":str(saved)})
    content=read.result if hasattr(read,"result") else read
    while isinstance(content,dict) and isinstance(content.get("result"),dict): content=content["result"]
    durable=json.loads(content["content"])
    expected={"session_id":"c8e-actual-session","parent_session_id":"c8e-parent","objective":state.objective,"prompt_stack":asdict(stack),"next_actions":state.next_actions,"changed_files":state.changed_files,"acceptance_checks":state.acceptance_checks}
    good=all(durable[k]==v for k,v in expected.items()) and durable["progress"]["completed_steps"]==["Inspect"] and durable["progress"]["remaining_steps"]==["Implement","Verify"] and durable==asdict(packet)
    observation={"producer":"grant_agent.handoff.create_handoff_packet/save_handoff_packet","consumer":"workspace.read","path":str(saved),"persisted":durable,"sha256":hashlib.sha256(saved.read_bytes()).hexdigest()}
    checks=[_adapter_check("adapters.handoff.progress",good,observation,"handoff.independent-durable-packet")]
    checks.extend(_adapter_check("adapters.handoff.progress",durable[key]==value,{**observation,"field":key,"expected":value},"handoff.retains-"+key) for key,value in expected.items())
    checks.append(_adapter_check("adapters.handoff.progress",durable["progress"]["completed_steps"]==["Inspect"] and durable["progress"]["remaining_steps"]==["Implement","Verify"],{**observation,"progress":durable["progress"]},"handoff.completed-and-remaining-steps"))
    return checks

def _adapter_ocr(root):
    from grant_agent.capability_adapters import CapabilityAdapterRegistry
    page="A real local report retains this complete documented paragraph and its final conclusion."
    table="<table><tr><td>Actual table boundary</td></tr></table>"
    formula="$$\nx = 1 + 2\n$$"
    specimens=[("renderer",page+"\n```markdown\n\n"+page[:48],page),("renderer","Different markdown\n```markdown\n\n| Genuine | table |",None),("table",table+"\nOutside markup",table),("table","<table><tr><td>unfinished",None),("formula",formula+"\n"+formula,formula),("formula",formula+"\n$$\nx = 4\n$$",None)]
    rows=[]
    for index,(kind,raw,expected) in enumerate(specimens):
        source=root/f"source-{index}.txt"; source.write_text(raw,encoding="utf-8",newline="\n")
        original=source.read_text(encoding="utf-8")
        fn=getattr(CapabilityAdapterRegistry,"_repair_glm_"+{"renderer":"renderer_duplicate","table":"table_boundary","formula":"formula_boundary"}[kind])
        result,evidence=fn(original)
        target=root/f"repaired-{index}.txt"; target.write_text(result,encoding="utf-8",newline="\n")
        durable=target.read_text(encoding="utf-8")
        rows.append({"kind":kind,"source":str(source),"output":str(target),"evidence":evidence,"input":original,"persistedOutput":durable,"passed":durable==(original if expected is None else expected) and (evidence is None)==(expected is None)})
    return [_adapter_check("adapters.ocr.boundaries",row["passed"],{"cases":[row],"boundary":"Original text-repair owner on actual files; no OCR runtime or image-reading claim"},"ocr."+row["kind"]+("-repair" if index%2==0 else "-preserve-unrelated-content")) for index,row in enumerate(rows)]

def _adapter_publication(root):
    from scripts.check_workflow_publication_integrity import audit_workflows,LEGACY_NATIVE_BRANCH
    actual=audit_workflows(ROOT)
    paths=sorted((ROOT/".github/workflows").glob("*.y*ml"))
    workflow_root=root/".github/workflows";workflow_root.mkdir(parents=True)
    candidate=workflow_root/"candidate.yml"
    cases=[("git-push","git push origin HEAD:main","contents: read"),("git-push","git \\\n            push origin HEAD:main","contents: read"),("write-api-call","gh api --method POST /repos/o/r/actions/runs/1/cancel","actions: write"),("pull-request-mutation","gh pr merge 45 --squash","contents: read"),("write-all-permissions","echo validation","write-all"),("legacy-self-mutating-branch","echo "+LEGACY_NATIVE_BRANCH,"contents: read")]
    observed=[]
    for index,(rule,body,permissions) in enumerate(cases):
        permission="permissions: write-all\n" if permissions=="write-all" else "permissions:\n  "+permissions+"\n"
        candidate.write_text("name: owned-policy-observation\non: workflow_dispatch\n"+permission+"jobs:\n  audit:\n    steps:\n      - run: |\n          "+body+"\n",encoding="utf-8")
        finding=audit_workflows(root)
        saved=root/f"refusal-source-{index}.txt";saved.write_bytes(candidate.read_bytes())
        observed.append({"case":rule+"-"+str(index),"expectedRule":rule,"findings":finding,"caseArtifact":str(saved),"caseSha256":hashlib.sha256(saved.read_bytes()).hexdigest(),"passed":rule in {r["rule"] for r in finding}})
    candidate.write_text("name: safe\non: pull_request\npermissions:\n  contents: read\njobs:\n  audit:\n    steps:\n      - run: python check.py\n",encoding="utf-8")
    safe=audit_workflows(root)
    result=[_adapter_check("adapters.workflow.publication",not actual and bool(paths) and not safe and all(r["passed"] for r in observed),{"actualRepository":str(ROOT),"actualWorkflowFiles":[{"path":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],"actualFindings":actual,"refusalCases":observed,"safeFindings":safe,"boundary":"Audits actual workflow bytes only; no publication/mutation command executed"},"publication.actual-repository-is-read-only")]
    result.extend(_adapter_check("adapters.workflow.publication",case["passed"],{"actualWorkflowFiles":[],"refusalCases":[case]},"publication.rejects-"+case["case"]) for case in observed)
    result.append(_adapter_check("adapters.workflow.publication",not safe,{"actualWorkflowFiles":[],"safeFindings":safe},"publication.accepts-safe-validation"))
    return result

def _adapter_html(root):
    from grant_agent.html_site_benchmark import grade_html,combine_score,FROZEN_PROMPT
    path=root/"index.html"
    path.write_text("<h1>Lumen Notes</h1>",encoding="utf-8")
    negative=grade_html(path)
    rejected=combine_score(negative,{"score":0})
    html="""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Lumen Notes</title><style>
    :root{color-scheme:light;--bg:#f4f1e9;--fg:#172627;--accent:#1b6055}*{box-sizing:border-box}body{background:var(--bg);color:var(--fg);margin:0;font-family:system-ui}body[data-theme=dark]{color-scheme:dark;--bg:#142627;--fg:#f4f1e9;--accent:#80c2a2}header,main,footer{max-width:1100px;margin:auto;padding:24px}nav{display:flex;gap:16px;align-items:center}.hero{padding:60px 0}.feature-grid,.notes{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}article{padding:24px;border:1px solid currentColor;border-radius:12px}button{background:var(--accent);color:var(--bg);padding:12px 18px;border:0;border-radius:8px;font:inherit;cursor:pointer}button:focus-visible{outline:3px solid currentColor;outline-offset:4px}[hidden]{display:none!important}.filters{display:flex;flex-wrap:wrap;gap:8px;margin:24px 0}footer{padding-top:50px}@media(max-width:600px){header,main,footer{padding:18px}.feature-grid,.notes{grid-template-columns:1fr}.hero{padding:24px 0}nav{flex-wrap:wrap}h1{font-size:2rem}}@media(prefers-reduced-motion:reduce){*{transition:none;animation:none;scroll-behavior:auto}}
    </style><header><nav aria-label="Primary"><strong>Lumen Notes</strong><a href="#demo">Try the notes</a><button type="button" aria-label="Switch to dark theme" id="theme">Theme</button></nav></header><main><section class="hero"><h1>Make space for your next idea.</h1><p>Give every thought a quiet place to grow. Lumen Notes puts a clear, simple surface between your busy day and the ideas that matter.</p><a href="#demo">Explore your notebook</a></section><section class="feature-grid"><article><h2>Capture clearly</h2><p>Write a thought while it is fresh, then return when you have room to develop it.</p></article><article><h2>Find the thread</h2><p>Separate ideas from tasks without losing their shared context.</p></article><article><h2>Keep your rhythm</h2><p>Use a quiet theme that fits the light and gives your attention space.</p></article></section><section id="demo"><h2>Your notebook, in view</h2><div class="filters" aria-label="Note filters"><button type="button" data-filter="all" aria-pressed="true">All</button><button type="button" data-filter="ideas" aria-pressed="false">Ideas</button><button type="button" data-filter="tasks" aria-pressed="false">Tasks</button></div><div class="notes"><article data-category="ideas"><h3>A neighborhood notebook</h3><p>Gather the small observations that make a street feel like home.</p></article><article data-category="tasks"><h3>Plan a quiet morning</h3><p>Set aside half an hour to review what is finished and choose the next useful step.</p></article><article data-category="ideas"><h3>A better reading ritual</h3><p>Keep a place for the sentence you want to remember and the question it leaves behind.</p></article></div></section></main><footer>Made for the ideas you want to keep.</footer><script>document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));document.querySelectorAll('[data-category]').forEach(note=>note.hidden=button.dataset.filter!=='all'&&note.dataset.category!==button.dataset.filter)}));document.querySelector('#theme').addEventListener('click',event=>{const dark=document.body.dataset.theme!=='dark';document.body.dataset.theme=dark?'dark':'light';event.currentTarget.setAttribute('aria-label',dark?'Switch to light theme':'Switch to dark theme')});</script></html>"""
    path.write_text(html,encoding="utf-8")
    static=grade_html(path)
    no_browser=combine_score(static,{"score":0})
    score_below=combine_score({"score":62},{"score":12})
    browser_below=combine_score({"score":80},{"score":11})
    gate=combine_score({"score":63},{"score":12})
    good=not rejected["passed"] and static["score"]==80 and not no_browser["passed"] and not score_below["passed"] and not browser_below["passed"] and gate["passed"] and all(s in FROZEN_PROMPT for s in ("index.html","no external","390px"))
    return [_adapter_check("adapters.html.scoring",good,{"artifact":str(path),"artifactSha256":hashlib.sha256(path.read_bytes()).hexdigest(),"negative":negative,"static":static,"zeroBrowserRejected":no_browser,"thresholdCases":{"score74":score_below,"browser11":browser_below,"exact75and12":gate},"boundary":"Static rubric and acceptance arithmetic only; separate mounted HTML effect required"})]

def _adapter_sync(root):
    from grant_agent.folder_sync import FolderSyncService
    installed=SYNCTHING_EXECUTABLE
    expected=SYNCTHING_EXECUTABLE_SHA256
    config=root/"compatibility.json"
    from c8_scope import fixture_port
    endpoint_port = fixture_port()
    config.write_text(json.dumps({"transport":{"endpoint":f"http://127.0.0.1:{endpoint_port}","apiKeyRef":""},"binary":{"version":"2.1.5","installPath":str(installed),"executableSha256":expected,"serviceState":"not-started"},"policy":{"allowedRoots":["${workspace}"],"folderTypes":["sendonly","receiveonly","sendreceive"],"versioningTypes":["trashcan","simple","staggered"],"inboundVersioningRequiredFor":["receiveonly","sendreceive"],"defaultVersioning":{"type":"staggered"}}}),encoding="utf-8")
    service=FolderSyncService(root,config_path=config)
    actual=service.compatibility_snapshot()
    good=installed.is_file() and actual["binary"]["installed"]==installed.is_file() and actual["binary"]["hashVerified"]==bool(installed.is_file() and hashlib.sha256(installed.read_bytes()).hexdigest()==expected) and actual["transport"]["credentialAvailable"] is False and actual["transport"]["credentialsExposed"] is False
    shared=root/"selected-folder";shared.mkdir()
    common={"folder_id":"docs","path":shared,"device_ids":["AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"]}
    refusals=[]
    for label,args in (("outside-configured-root",{**common,"path":root.parent}),("external-ignore-file",{**common,"ignore_patterns":["#include another.ignore"]}),("external-versioning-command",{**common,"folder_type":"sendreceive","versioning":{"type":"external","params":{"command":"untrusted"}}})):
        try:service.build_folder_plan(**args)
        except ValueError as error:refusals.append({"case":label,"refused":True,"reason":str(error)[:180]})
        else:refusals.append({"case":label,"refused":False})
    safe=service._allowed_folder_path(shared)==shared and service._validated_versioning("sendreceive",None)["type"]=="staggered" and service._validate_ignore_patterns([".git",".git"])==[".git"]
    result=[_adapter_check("adapters.sync.compatibility",good,{"actual":actual,"executable":str(installed),"expectedSha256":expected,"boundary":"Actual pinned portable executable hashing after its hidden version command; no service, device or synchronization claim"},"sync.pinned-portable-compatibility")]
    result.extend(_adapter_check("adapters.sync.policy",row["refused"],{"refusals":[row],"config":str(config),"providerRequestsMade":False},"sync.rejects-"+row["case"]) for row in refusals)
    result.append(_adapter_check("adapters.sync.policy",safe,{"config":str(config),"allowedPath":str(shared),"defaultInboundVersioning":service._validated_versioning("sendreceive",None),"deduplicatedIgnores":service._validate_ignore_patterns([".git",".git"]),"providerRequestsMade":False},"sync.safe-local-policy-preserved"))
    return result


def _adapter_release(root):
    from grant_agent import github_release_source as release
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    import threading
    package=root/"publisher-package.zip";package.write_bytes(b"C8e actual confined package bytes\n")
    digest=hashlib.sha256(package.read_bytes()).hexdigest()
    asset={"name":"package-windows-x64.zip","size":package.stat().st_size,"browser_download_url":package.as_uri()}
    stable={"tag_name":"v2.1.0","draft":False,"prerelease":False,"assets":[asset,{"name":asset["name"]+".sha256"}]}
    listing=root/"publisher-releases.json"
    listing.write_text(json.dumps([{"tag_name":"v3.0.0","draft":True},{"tag_name":"v2.2.0-rc1","prerelease":True},stable]),encoding="utf-8")
    reads=[]
    def local_manifest(_url,**_limits):
        reads.append(str(listing));return listing.read_bytes()
    references=[release.parse_github_ref(r).slug for r in ("publisher/tool","https://github.com/publisher/tool","https://github.com/publisher/tool.git","git@github.com:publisher/tool.git")]
    invalid=[release.parse_github_ref(r) for r in (None,"","not-a-ref","https://example.invalid/thing")]
    selected=release.select_release(json.loads(listing.read_text()))
    releases=json.loads(listing.read_text())
    normalized=[{"input":value,"actual":release.normalize_version(value),"expected":wanted} for value,wanted in (("v2.1.0","2.1.0"),("V2.1.0","2.1.0"),("local-build","local-build"),("vlocal","vlocal"),("",""))]
    beta=release.select_release(releases,channel="beta")
    specific=release.select_release(releases,version="v2.1.0")
    absent=release.select_release(releases,version="v9.0.0")
    selected_platform=release.select_platform_asset(stable,platform_tag="windows-x64")
    selection=references==["publisher/tool"]*4 and invalid==[None]*4 and all(r["actual"]==r["expected"] for r in normalized) and selected==stable and beta==releases[1] and specific==stable and absent is None and selected_platform==asset and release.find_checksum_for(stable,asset)["name"].endswith(".sha256") and release.select_platform_asset(stable,platform_tag="linux-arm64") is None
    states=[]
    for installed,platform,wanted in (("2.0.0","windows-x64","update_available"),("v2.1.0","windows-x64","current"),("2.3.0","windows-x64","current"),("local-build","windows-x64","unknown"),("2.0.0","linux-arm64","unknown")):
        observed=release.check_for_update(installed,release.GitHubSource("publisher","tool"),platform_tag=platform,fetch=local_manifest)
        states.append({"actual":observed,"expected":wanted,"passed":observed["state"]==wanted and observed["downloadedBytes"]==0})
    missing=release.check_for_update("2.0.0",release.GitHubSource("publisher","tool"),fetch=lambda _url,**_limits:(root/"absent.json").read_bytes())
    target=root/"staged-package.zip"
    staged=release.download_asset(asset,target,expected_sha256=digest)
    refusals=[]
    def refuse(fn,label):
        try:fn()
        except release.GitHubReleaseError as error:refusals.append({"case":label,"refused":True,"reason":str(error)[:180]});return True
        refusals.append({"case":label,"refused":False});return False
    refuse(lambda:release.download_asset(asset,target,expected_sha256="0"*64),"hash-replacement")
    bad=root/"rejected-package.zip"
    refuse(lambda:release.download_asset(asset,bad,expected_sha256="0"*64),"hash-new-package")
    unverified=release.download_asset({**asset,"size":999},root/"unverified-package.zip")
    class ProtocolFaults(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def do_GET(self):
            if self.path=="/rate-limited":
                self.send_response(429);self.send_header("Content-Length","0");self.end_headers()
            else:
                self.send_response(200);self.send_header("Content-Length","1024");self.end_headers();self.wfile.write(b"part");self.wfile.flush();self.close_connection=True
    from c8_scope import fixture_port
    server_port = fixture_port()
    server=ThreadingHTTPServer(("127.0.0.1",server_port),ProtocolFaults)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        limited=release.check_for_update("2.0.0",release.GitHubSource("publisher","tool"),fetch=lambda _url,**limits:release._default_fetch(f"http://127.0.0.1:{server_port}/rate-limited",**limits))
        refuse(lambda:release.download_asset({"name":"broken.zip","browser_download_url":f"http://127.0.0.1:{server_port}/premature-eof"},target),"premature-http-eof")
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
    update=all(s["passed"] for s in states) and missing["state"]=="unknown" and limited["state"]=="unknown" and "rate limit" in limited["detail"]
    staging=staged["verified"] and hashlib.sha256(target.read_bytes()).hexdigest()==digest and target.read_bytes()==package.read_bytes() and all(r["refused"] for r in refusals) and not bad.exists() and not list(root.glob("*.partial")) and not unverified["verified"] and "999" in unverified["warning"]
    boundary=f"Actual own local release files and HTTP 429/EOF on explicitly assigned C8 port {server_port}; no GitHub/account/signature/publication claim"
    checks=[_adapter_check("adapters.release.selection",selection,{"manifest":str(listing),"manifestSha256":hashlib.sha256(listing.read_bytes()).hexdigest(),"selected":selected,"beta":beta,"requestedVersion":specific,"missingVersion":absent,"normalizations":normalized,"selectedPlatform":selected_platform,"references":references,"boundary":boundary},"release.actual-manifest-selects-stable-platform-with-checksum"),_adapter_check("adapters.release.update",update,{"states":states,"unavailable":missing,"http429":limited,"manifestReads":len(reads),"boundary":boundary},"release.metadata-only-observation-and-http429-uncertainty"),_adapter_check("adapters.release.staging",staging,{"path":str(target),"sha256":digest,"source":str(package),"result":staged,"refusals":refusals,"unverified":unverified,"priorTargetPreserved":target.read_bytes()==package.read_bytes(),"boundary":boundary},"release.actual-staging-preserves-prior-after-hash-and-eof-refusal")]
    checks.extend(_adapter_check("adapters.release.update",case["passed"],case,"release.version-platform-state-"+str(index)) for index,case in enumerate(states))
    checks.extend(_adapter_check("adapters.release.staging",case["refused"],{"refusals":[case]},"release.rejects-"+case["case"]) for case in refusals)
    return checks

def _adapter_git(root):
    import os,shutil,subprocess
    from grant_agent.git_reference_adapter import GitReferenceAdapter,GitReferenceError
    from grant_agent.capability_service import CapabilityService
    from grant_agent.tool_manifest_registry import ToolManifest,ToolManifestRegistry
    from grant_agent.proofs_b_adapters import _fixture_root
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    git=shutil.which("git")
    if not git: raise RuntimeError("An already installed Git executable is required")
    repo=root/"repository";repo.mkdir()
    def command(*args):
        r=subprocess.run([git,"-c","core.hooksPath="+os.devnull,"-C",str(repo),*args],env=GitReferenceAdapter._env(),capture_output=True,text=True,timeout=15,**hidden_windows_subprocess_kwargs())
        if r.returncode:
            raise RuntimeError("Disposable Git setup refused: "+r.stderr[:700])
        return r.stdout.strip()
    command("init");command("config","user.name","C8e disposable owner");command("config","user.email","c8e@example.invalid")
    tracked=repo/"tracked.txt";tracked.write_text("first\n",encoding="utf-8")
    command("add","tracked.txt");command("commit","-m","first local object");first=command("rev-parse","HEAD")
    tracked.write_text("first\nsecond\n",encoding="utf-8");command("commit","-am","second local object");second=command("rev-parse","HEAD")
    adapter=GitReferenceAdapter(root,executable=git)
    results=[adapter.execute({"repository":"repository","operation":op,**args}) for op,args in (("repository.inspect",{}),("repository.history",{"maxCommits":2}),("repository.show",{"ref":"HEAD","paths":["tracked.txt"]}),("commit.ancestry-verify",{"ancestor":first,"descendant":second}))]
    receipts=[]
    for result in results:
        path=root/result["receipt"]["path"];raw=path.read_bytes();content=json.loads(raw)
        receipts.append({"path":str(path),"sha256":hashlib.sha256(raw).hexdigest(),"digestMatches":hashlib.sha256(raw).hexdigest()==result["receipt"]["sha256"],"lineageMatches":content["lineage"]["sources"][0]["head"]==result["head"] and content["resultHash"]==result["artifacts"][0]["derivedFrom"]})
    objects=results[0]["head"]==second and [r["commit"] for r in results[1]["commits"]]==[second,first] and "+second" in results[2]["content"] and results[3]["isAncestor"] and all(r["digestMatches"] and r["lineageMatches"] for r in receipts)
    unsafe=[]
    def refuse(fn, label, errors=(GitReferenceError,ValueError)):
        try: fn()
        except errors as error: unsafe.append({"case":label,"refused":True,"exception":type(error).__name__});return True
        unsafe.append({"case":label,"refused":False});return False
    for key,value in (("filter.unsafe.process","helper"),("diff.unsafe.command","helper"),("diff.unsafe.textconv","helper"),("protocol.file.allow","always"),("core.sshCommand","helper"),("remote.origin.promisor","true"),("remote.origin.partialCloneFilter","blob:none"),("include.path","../external-config")):
        command("config",key,value);refuse(lambda:adapter.execute({"repository":"repository","operation":"repository.inspect"}),key);command("config","--unset",key)
    for name in (".gitattributes","nested/.gitattributes",".git/info/attributes",".git/objects/info/alternates",".git/objects/info/http-alternates",".git/objects/pack/unsafe.promisor"):
        path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text("../external filter=unsafe\n",encoding="utf-8")
        refuse(lambda:adapter.execute({"repository":"repository","operation":"repository.inspect"}),name);path.rename(path.with_name(path.name+".refused"))
    linked=root/"linked-worktree";command("worktree","add","--detach",str(linked),"HEAD")
    refuse(lambda:adapter.execute({"repository":"linked-worktree","operation":"repository.inspect"}),"linked-worktree")
    safety=all(r["refused"] for r in unsafe) and all(r["networkAccessed"] is False and r["policy"]["network"]=="denied" and r["consistency"]["before"]==r["consistency"]["after"] for r in results)
    # Actual pinned Git readiness and artifact registration in the original service.
    current=CapabilityService(_fixture_root(root),catalog_path=ROOT/"config/capability_packs.json").tool_manifests.describe("tool.git")
    tool=next(t for t in json.loads((ROOT/"config/tool_suite_lock.json").read_text())["tools"] if t["toolId"]=="tool.git")
    pin=GitReferenceAdapter.probe_executable_identity(git)
    operations=[dict(operationId=i,name=i,description="Bounded actual object read",permissions=["workspace.read","workspace.write","artifact.write"],inputSchema={"type":"object","properties":{"repository":{"type":"string"}},"required":["repository"]},outputSchema={"type":"object","required":["ok","head","receipt"]},metadata={"adapterOperation":i}) for i in ("repository.inspect","repository.history","repository.show","commit.ancestry-verify")]
    tool.update(state="verified",workers=["windows"] if os.name=="nt" else ["container"],selectedVersion=pin["version"].removeprefix("git version "),installPath=str(Path(git).resolve()),packageSha256=pin["sha256"],health={"status":"healthy"},operations=operations,readiness={"productionValidated":True,"productionEvidence":"Actual local object receipts in this own disposable root","prerequisites":[]})
    config=root/"config";config.mkdir(exist_ok=True)
    (config/"tool_suite_lock.json").write_text(json.dumps({"schema":"neyvia.tool_suite_lock.v1","tools":[tool]}),encoding="utf-8")
    service=CapabilityService(_fixture_root(root),catalog_path=ROOT/"config/capability_packs.json")
    execution=service.execute_tool_operation({"toolId":"tool.git","operationId":"repository.inspect","arguments":{"repository":"repository"},"permissionMode":"workspace_safe"})
    registered=execution.get("artifactReceipt",{}).get("artifacts",[])
    prior=service.artifacts.snapshot();declaration=results[0]["artifacts"][0]
    invalid=[]
    for patch in ({"sha256":"0"*64},{"derivedFrom":"0"*64}):
        try: service._register_adapter_artifacts({"result":{"artifacts":[{**declaration,**patch}]}},capability_id="software.application-engineering",run_id="c8e-local-proof",adapter_id="code.git")
        except ValueError: invalid.append(True)
        else: invalid.append(False)
    registration=execution.get("ok") is True and execution["outputValidation"]["valid"] and execution["result"]["head"]==second and len(registered)==1 and registered[0]["metadata"]["role"]=="git-reference-receipt" and bool(registered[0]["metadata"]["declaredSha256"]) and bool(registered[0]["metadata"]["derivedFrom"]) and all(invalid) and service.artifacts.snapshot()==prior
    policy_tools=[{**tool,"toolId":"tool.ready"}]
    for kind in ("trust","service","device","worker"):
        policy_tools.append({**tool,"toolId":"tool.blocked-"+kind,"readiness":{**tool["readiness"],"prerequisites":[{"id":kind+"-required","kind":kind,"status":"unprovisioned","requiredFor":["execution","production"],"reason":"Actual readiness policy refusal","evidence":""}]}})
    policy_path=root/"readiness-policy.json";policy_path.write_text(json.dumps({"schema":"neyvia.tool_suite_lock.v1","tools":policy_tools}),encoding="utf-8")
    registry=ToolManifestRegistry(policy_path);unbound=registry.describe("tool.ready")
    registry.bind_adapters(service.adapters);ready=registry.describe("tool.ready")
    blocked=[registry.describe("tool.blocked-"+kind) for kind in ("trust","service","device","worker")]
    unprovisioned=ToolManifest.from_payload({**tool,"state":"planned","packageSha256":"","operations":[]})
    boolean_refused=False
    try:ToolManifest.from_payload({**tool,"readiness":{"productionValidated":"false"}})
    except ValueError:boolean_refused=True
    readiness=not unbound["executionReady"] and ready["agentReady"] and ready["executionReady"] and ready["productionReady"] and ready["readiness"]["runtimeEvidence"]["runtimeIdentityVerified"] and all(b["agentReady"] and not b["executionReady"] and not b["productionReady"] for b in blocked) and not unprovisioned.contract_ready and boolean_refused and [r["toolId"] for r in registry.search("",execution_ready_only=True)["results"]]==["tool.ready"] and len(registry.search("",agent_ready_only=True)["results"])==5 and current["executionReadinessEvaluated"] and not current["productionReady"]
    checks=[_adapter_check("adapters.git.objects",objects,{"operations":results,"independentReceipts":receipts}),_adapter_check("adapters.git.safety",safety,{"refusals":unsafe,"networkAccessed":False}),_adapter_check("adapters.git.readiness",readiness,{"actualPin":pin,"unbound":unbound,"ready":ready,"blocked":blocked,"repositoryManifest":current,"invalidBooleanRefused":boolean_refused}),_adapter_check("adapters.git.artifact-registration",registration,{"actualExecution":execution,"badHashAndLineageRefused":invalid,"graphUnchanged":service.artifacts.snapshot()==prior})]
    checks.extend(_adapter_check("adapters.git.safety",row["refused"],{"refusals":[row]},"git.rejects-"+row["case"]) for row in unsafe)
    return checks


def _adapter_witness(worker,binding,root):
    required=binding["c8eEffect"]["requiredContractIds"]
    report=worker.c8e_effect.get("producer",{})
    area=next((a for a in report.get("areas",[]) if a.get("area")=="proofs-b-adapters"),{})
    checks=[];contracts=[]
    for identity in required:
        producer_rows=[c for c in area.get("checks",[]) if c.get("contract")==identity]
        good=bool(producer_rows) and all(r.get("ok") is True for r in producer_rows)
        fresh=[]
        for row in producer_rows:
            observed=row.get("observed",{})
            if identity=="adapters.handoff.progress":
                raw=worker.tool("workspace.read",{"path":observed["path"]})
                content=json.loads(raw["content"])
                good=good and content==observed["persisted"] and raw["sha256"]==observed["sha256"]
                fresh.append({"actualReader":raw,"expected":observed["persisted"]})
            elif identity=="adapters.ocr.boundaries":
                for case in observed["cases"]:
                    before=worker.tool("workspace.read",{"path":case["source"]})
                    after=worker.tool("workspace.read",{"path":case["output"]})
                    good=good and before["content"]==case["input"] and after["content"]==case["persistedOutput"]
                    fresh.append({"actualInput":before,"actualOutput":after,"evidence":case["evidence"]})
            elif identity=="adapters.git.objects":
                for receipt in observed["independentReceipts"]:
                    read=worker.tool("workspace.read",{"path":receipt["path"]})
                    good=good and read["sha256"]==receipt["sha256"]
                    fresh.append(read)
            elif identity=="adapters.release.selection" and "manifest" in observed:
                read=worker.tool("workspace.read",{"path":observed["manifest"]})
                good=good and read["sha256"]==observed["manifestSha256"]
                fresh.append(read)
            elif identity=="adapters.release.staging" and "path" in observed:
                read=worker.tool("workspace.read",{"path":observed["path"]})
                path=Path(observed["path"]).resolve();path.relative_to(Path(root).resolve())
                actual=hashlib.sha256(path.read_bytes()).hexdigest()
                good=good and actual==observed["sha256"] and read.get("sha256")==actual
                fresh.append({"actualReader":read,"freshArtifactSha256":actual})
            elif identity=="adapters.workflow.publication":
                for receipt in observed["actualWorkflowFiles"]:
                    source=Path(receipt["path"]).resolve()
                    source.relative_to(ROOT/".github/workflows")
                    digest=hashlib.sha256(source.read_bytes()).hexdigest()
                    good=good and digest==receipt["sha256"]
                    fresh.append({"path":str(source),"actualSha256":digest,"boundary":"Independent read of the explicitly authorized repository workflow source; the native workspace reader correctly keeps its narrower scratch scope"})
                for case in observed.get("refusalCases",[]):
                    read=worker.tool("workspace.read",{"path":case["caseArtifact"]})
                    good=good and read["sha256"]==case["caseSha256"]
                    fresh.append({"actualAdverseSource":read,"actualAuditFindings":case["findings"]})
            elif identity=="adapters.sync.compatibility":
                source=Path(observed["executable"]).resolve()
                if source!=SYNCTHING_EXECUTABLE.resolve(): raise ValueError("Compatibility producer declared an unapproved executable")
                actual=hashlib.sha256(source.read_bytes()).hexdigest()
                good=good and actual==observed["expectedSha256"]
                fresh.append({"freshExecutableSha256":actual,"acquisition":json.loads((SYNCTHING_ROOT/"acquisition.json").read_text()),"boundary":"Pinned portable executable and actual version command, no service/device/synchronization"})
            elif identity=="adapters.html.scoring":
                rendered,render_observed=_html_browser_witness(worker,observed)
                good=good and rendered
                fresh.append(render_observed)
        check=_check("c8e.actual-owner-effect-"+identity,good,{"realProducer":producer_rows,"freshEffects":fresh},"rendered-user-action" if identity=="adapters.html.scoring" else "production-state")
        checks.append(check)
        contracts.append({"id":identity,"passed":good,"fresh":True,"boundary":check["boundary"],"observed":check["observed"]})
    return checks,{"contractEffects":contracts,"selectedChapters":area.get("selectedChapters"),"partial":True}

def _html_browser_witness(worker,observed):
    path=observed["artifact"]
    current=worker.tool("workspace.read",{"path":path})
    if current["sha256"]!=observed["artifactSha256"]: return False,{"artifactChanged":current}
    worker.tool("neyvia.pane.show",{"kind":"artifact","target":path})
    worker.page.locator(".nx-ap-frame").wait_for(timeout=30000)
    frame=worker.page.frame_locator(".nx-ap-frame")
    frame.get_by_role("heading",name="Make space for your next idea.",exact=True).wait_for(timeout=30000)
    samples=[]
    for label,wanted in (("All",3),("Ideas",2),("Tasks",1),("All",3)):
        button=frame.get_by_role("button",name=label,exact=True);button.click()
        samples.append({"label":label,"visibleNotes":frame.locator("[data-category]:visible").count(),"pressed":button.get_attribute("aria-pressed"),"pressedCount":frame.locator('[data-filter][aria-pressed="true"]').count(),"expected":wanted})
    theme=frame.get_by_role("button",name="Switch to dark theme",exact=True);theme.click()
    dark=frame.locator("body").get_attribute("data-theme")=="dark" and frame.get_by_role("button",name="Switch to light theme",exact=True).count()==1
    frame.get_by_role("button",name="Switch to light theme",exact=True).click()
    light=frame.locator("body").get_attribute("data-theme")=="light"
    focus=frame.get_by_role("button",name="Ideas",exact=True);focus.focus();focus.press("Tab")
    focused=frame.locator(":focus").evaluate("e=>({text:e.textContent,outline:getComputedStyle(e).outlineWidth})")
    mobile=[]
    for width in (390,1440):
        worker.page.set_viewport_size({"width":width,"height":1000})
        # Resize can temporarily collapse the mounted pane; observe after layout.
        frame.locator("html").wait_for(state="visible",timeout=30000)
        layout=frame.locator("html").evaluate("e=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve({viewport:innerWidth,scroll:e.scrollWidth,client:e.clientWidth}))))")
        layout["outerWidth"]=width
        layout["artifact"]=worker.screenshot("effect-b-html-"+str(width))
        mobile.append(layout)
    filter_ok=all(s["visibleNotes"]==s["expected"] and s["pressed"]=="true" and s["pressedCount"]==1 for s in samples)
    keyboard_ok=focused["text"]=="Tasks" and float(focused["outline"].removesuffix("px"))>0
    layout_ok=all(m["viewport"]>0 and 0<m["client"]<=m["outerWidth"] and m["scroll"]<=m["client"] for m in mobile)
    measured={"filter":filter_ok,"theme":dark and light,"keyboard":keyboard_ok,"responsive":layout_ok}
    # Browser points are earned only from the independent mounted observations.
    score=sum(5 for passed in measured.values() if passed)
    static=observed["static"]["score"]
    accepted=static+score>=75 and score>=12
    artifact=worker.screenshot("effect-b-html")
    worker.observe()
    return all(measured.values()) and accepted,{"actualArtifactSha256":current["sha256"],"mountedFilterObservations":samples,"dark":dark,"light":light,"actualFocus":focused,"actualViewportLayouts":mobile,"earnedBrowserChecks":measured,"earnedBrowserScore":score,"staticScore":static,"acceptedByFrozenThreshold":accepted,"artifact":artifact,"boundary":"Actual candidate artifact pane iframe; no synthetic frontend model or provider generation"}


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description="Exact task-owned NightShift command probe")
    parser.add_argument("--nightshift-command",required=True)
    args=parser.parse_args()
    nightshift_command(args.nightshift_command)
