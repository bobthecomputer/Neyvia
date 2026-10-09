"""Real local adapter bytes, object history and publication policy observations."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IDS = {'adapters.git.objects','adapters.git.safety','adapters.git.readiness','adapters.git.artifact-registration','adapters.handoff.progress','adapters.html.scoring','adapters.release.staging','adapters.release.update','adapters.workflow.publication'}
TEXT = {'empty':'','huge':'owned bounded text '*4096,'unicode':'雪 café e\u0301 العربية'}


def require(value, detail):
    if not value:
        raise AssertionError(detail)


def rejected(action):
    try:
        action()
    except Exception as error:
        return type(error).__name__
    raise AssertionError('Unsafe/unavailable adapter action unexpectedly accepted')


def _release(root, category, identity):
    from . import github_release_source as owner
    from .edge_fixture_models import _deny_read
    text=TEXT.get(category,'owned local artifact')
    package=root/'publisher.bin';package.write_bytes(text.encode())
    target=root/'staged.bin';target.write_bytes(b'keeper')
    asset={'name':'owned-windows-x64.bin','browser_download_url':package.as_uri(),'size':len(package.read_bytes())}
    if category=='interrupted':
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        class FramingFault(BaseHTTPRequestHandler):
            def log_message(self,*_args):pass
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Length','1024');self.end_headers();self.wfile.write(b'part');self.wfile.flush();self.close_connection=True
        from .proof_ports import c7_port_block
        assigned = c7_port_block(int(os.environ['NEYVIA_C7_PORT']))
        port=int(os.environ.get('NEYVIA_C7_ADAPTER_PORT',str(assigned[-1])));require(port in assigned,'Owned adapter HTTP port escaped assigned block')
        server=ThreadingHTTPServer(('127.0.0.1',port),FramingFault);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{port}/premature-eof'
            if identity=='adapters.release.staging':
                rejected(lambda:owner.download_asset({**asset,'browser_download_url':url},target,timeout=2));require(target.read_bytes()==b'keeper','Actual premature HTTP EOF replaced valid staged target')
            else:
                result=owner.check_for_update('2.0.0',owner.GitHubSource('owned','local'),fetch=lambda _url,**limits:owner._default_fetch(url,**limits))
                require(result['state']=='unknown','Actual incomplete HTTP metadata claimed current/update available')
            return {'actualHttpPrematureEof':True,'priorTargetPreserved':True,'port':port,'actualGitHubObserved':False}
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5);require(not thread.is_alive(),'Owned HTTP fault server survived cleanup')
    if identity=='adapters.release.update':
        listing=root/'publisher.json';listing.write_text(json.dumps([{'tag_name':'v2.1.0','name':text,'draft':False,'prerelease':False,'assets':[asset]}]),encoding='utf-8')
        def fetch(_url,**_limits):
            return listing.read_bytes()
        source=owner.GitHubSource('owned','local')
        if category=='permissions':
            with _deny_read(listing):
                require(owner.check_for_update('2.0.0',source,fetch=fetch)['state']=='unknown','Denied actual metadata file read claimed current')
        elif category=='offline':
            listing.rename(root/'unavailable.json')
            require(owner.check_for_update('2.0.0',source,fetch=fetch)['state']=='unknown','Missing actual selected metadata file claimed current')
        else:
            states=[owner.check_for_update(version,source,platform_tag=platform,fetch=fetch)['state'] for version,platform in [('2.0.0','windows-x64'),('2.1.0','windows-x64'),('3.0.0','windows-x64'),('local-build','windows-x64'),('2.0.0','linux')]]
            require(states==['update_available','current','current','unknown','unknown'],'Actual selected metadata invented update order/platform authority')
            if category=='stale':
                listing.write_text('[]');require(owner.check_for_update('2.0.0',source,fetch=fetch)['state']=='unknown','Actual replaced metadata retained previous release observation')
        require(target.read_bytes()==b'keeper','Metadata observation downloaded or staged package bytes')
        return {'actualSelectedMetadataFile':True,'packageDownloaded':False,'actualGitHubObserved':False}
    digest=hashlib.sha256(package.read_bytes()).hexdigest()
    if category=='permissions':
        with _deny_read(target):
            rejected(lambda:owner.download_asset(asset,target,expected_sha256=digest))
        require(target.read_bytes()==b'keeper','Denied actual replacement damaged keeper')
    elif category=='offline':
        package.rename(root/'unavailable.bin');rejected(lambda:owner.download_asset(asset,target));require(target.read_bytes()==b'keeper','Missing actual file source replaced keeper')
    else:
        rejected(lambda:owner.download_asset(asset,target,expected_sha256='0'*64));require(target.read_bytes()==b'keeper','Bad publisher checksum replaced valid keeper')
        if category=='concurrency':
            with ThreadPoolExecutor(max_workers=8) as pool:
                values=list(pool.map(lambda _:owner.download_asset(asset,target,expected_sha256=digest),range(8)))
        else:
            values=[owner.download_asset(asset,target,expected_sha256=digest)]
        require(target.read_bytes()==package.read_bytes() and all(v['sha256']==digest and v['bytes']==len(package.read_bytes()) and v['verified'] for v in values),'Actual staged bytes/digest/readback differed')
        unverified=owner.download_asset({**asset,'size':999999},root/'unverified.bin')
        require(not unverified['verified'] and unverified['warning'],'No publisher checksum gained verification or declared-size mismatch lost warning')
    require(not list(root.glob('.*.partial')),'Rejected/completed file staging retained partial artifact')
    return {'actualFileTransport':True,'actualPublisherChecksumBytes':True,'actualGitHubObserved':False}


def _handoff(root, category):
    from .handoff import create_handoff_packet,save_handoff_packet
    from .models import RunState,PromptStack,PersonaProfile
    from .context_manager import ContextWindowManager
    from .edge_fixture_models import _deny_read
    text=TEXT.get(category,'owned handoff')
    state=RunState(objective=text,plan_steps=['done','remaining'],completed_steps=['done'],acceptance_checks=['actual bytes'],next_actions=['remaining'])
    stack=PromptStack(text,text,PersonaProfile('owned','plain','low','low','small','short'),text,text)
    packet=create_handoff_packet('owned','parent','context_rollover',state,stack,ContextWindowManager(100))
    path=save_handoff_packet(packet,root,1)
    if category=='permissions':
        keeper=path.read_bytes()
        with _deny_read(path):
            rejected(lambda:save_handoff_packet(packet,root,1))
        require(path.read_bytes()==keeper,'Denied actual handoff write damaged keeper')
    elif category=='concurrency':
        import threading
        barrier=threading.Barrier(8)
        packets=[replace(packet,objective=('owned '+str(i)+' ')*(4096 if i%2 else 1)) for i in range(8)]
        def save(i):
            barrier.wait(timeout=10)
            return save_handoff_packet(packets[i],root,1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            paths=list(pool.map(save,range(8)))
        observed=json.loads(path.read_bytes())
        require(all(p==path for p in paths) and observed in [asdict(p) for p in packets],'Same-target concurrent handoff writes corrupted complete packet serialization')
        packet=next(p for p in packets if asdict(p)==observed)
    elif category=='stale':
        state.completed_steps.append('remaining');current=create_handoff_packet('owned','parent','updated',state,stack,ContextWindowManager(100));save_handoff_packet(current,root,1)
        require(json.loads(path.read_bytes())['progress']['remaining_steps']==[],'Current handoff retained previous remaining plan')
        packet=current
    require(json.loads(path.read_bytes())==asdict(packet),'Actual handoff JSON lost lineage/progress/prompt authority')
    return {'actualHandoffFile':True,'remainingSteps':asdict(packet)['progress']['remaining_steps'],'resumableModelExecuted':False}


def _html(root,category):
    from .html_site_benchmark import grade_html,combine_score
    from .edge_fixture_models import _deny_read
    source=TEXT.get(category,'owned')
    path=root/'index.html';path.write_text(source,encoding='utf-8')
    if category=='permissions':
        with _deny_read(path):
            rejected(lambda:grade_html(path))
    else:
        static=grade_html(path)
        require(static['score']==sum(r['maximum'] for r in static['checks'] if r['passed']) and static['maximum']==80,'Actual static rubric awarded unearned points')
        require(not combine_score(static,{'score':0,'observed':False})['passed'],'Static HTML bypassed unobserved browser gate')
        for total,browser,expected in [(80,0,False),(63,11,False),(63,12,True),(62,12,False)]:
            require(combine_score({'score':total},{'score':browser,'suppliedGateInput':True})['passed']==expected,'Exact supplied score gate threshold changed')
    return {'actualSourceFileRubric':True,'renderedProof':False,'syntheticBrowserScoreOnlyGateInput':True}


def _workflow(root,category):
    path=REPO/'scripts/check_workflow_publication_integrity.py'
    spec=importlib.util.spec_from_file_location('c7d_owned_publication',path);owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    folder=root/'.github/workflows';folder.mkdir(parents=True);file=folder/'owned.yml'
    text=TEXT.get(category,'owned')
    file.write_text('name: '+json.dumps(text)+'\npermissions: read-all\njobs:\n  inspect:\n    steps:\n      - run: git status --short\n',encoding='utf-8')
    require(not owner.audit_workflows(root),'Read-only actual workflow acquired mutation finding')
    bad=['git push','git \\\n  push','gh pr merge 3','gh api /owned -X POST','permissions: write-all',owner.LEGACY_NATIVE_BRANCH]
    for command in bad:
        file.write_text(command+'\n' if command.startswith('permissions:') else 'permissions: read-all\nsteps:\n  - run: '+command+'\n',encoding='utf-8')
        require(owner.audit_workflows(root),'Actual workflow mutation escaped audit: '+command)
    if category=='permissions':
        from .edge_fixture_models import _deny_read
        with _deny_read(file):rejected(lambda:owner.audit_workflows(root))
    return {'actualWorkflowFilesAudited':True,'mutationCases':len(bad),'publicationExecuted':False}


def _git(root,category,identity):
    from .git_reference_adapter import GitReferenceAdapter
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    from .edge_fixture_models import _deny_read
    git=shutil.which('git');require(git,'Actual installed Git required')
    repository=root/'repository';repository.mkdir()
    def command(*args):
        value=subprocess.run([git,'-c','core.hooksPath='+os.devnull,'-C',str(repository),*args],env=GitReferenceAdapter._env(),capture_output=True,encoding='utf-8',errors='replace',timeout=15,check=True,**hidden_windows_subprocess_kwargs())
        return value.stdout.strip()
    command('init');command('config','user.name','Owned proof');command('config','user.email','owned@example.invalid')
    text=TEXT.get(category,'owned Git bytes');tracked=repository/'tracked.txt';tracked.write_text(text+'\n',encoding='utf-8');command('add','tracked.txt');command('commit','-m','owned first');first=command('rev-parse','HEAD')
    tracked.write_text(text+'\nsecond\n',encoding='utf-8');command('commit','-am','owned second');second=command('rev-parse','HEAD')
    pin=GitReferenceAdapter.probe_executable_identity(git);adapter=GitReferenceAdapter(root,executable=git,expected_sha256=pin['sha256'],expected_version=pin['version'].removeprefix('git version '))
    args={'repository':'repository','operation':'repository.inspect'}
    if identity in {'adapters.git.objects','adapters.git.safety'}:
        if category=='permissions':
            with _deny_read(repository/'.git/config'):rejected(lambda:adapter.execute(args))
        else:
            ops=[('repository.inspect',{}),('repository.history',{'maxCommits':999999}),('repository.show',{'ref':'HEAD','paths':['tracked.txt']}),('commit.ancestry-verify',{'ancestor':first,'descendant':second})]
            def action(entry):
                operation,options=entry;v=adapter.execute({**args,'operation':operation,**options});raw=(root/v['receipt']['path']).read_bytes();receipt=json.loads(raw)
                require(hashlib.sha256(raw).hexdigest()==v['receipt']['sha256'] and receipt['lineage']['sources'][0]['head']==second and receipt['resultHash']==v['artifacts'][0]['derivedFrom'] and not v['networkAccessed'],'Actual native Git receipt bytes/head/output lineage differed')
                return v
            if category=='concurrency':
                with ThreadPoolExecutor(max_workers=4) as pool:values=list(pool.map(action,ops*2))
            else:values=[action(op) for op in ops]
            require(values[0]['head']==second and values[1]['commits'][0]['commit']==second and values[3]['isAncestor'],'Actual committed Git object history differed')
            if category=='huge':rejected(lambda:adapter.execute({**args,'operation':'repository.show','maxBytes':64}));rejected(lambda:adapter.execute({**args,'operation':'repository.show','paths':['tracked.txt']*65}))
            if category=='empty':rejected(lambda:adapter.execute({**args,'repository':''}))
            if category=='stale':
                tracked.write_text('fresh\n');command('commit','-am','fresh');require(adapter.execute(args)['head']==command('rev-parse','HEAD')!=second,'Actual new HEAD reused stale object observation')
            if identity=='adapters.git.safety':
                for key,value in [('filter.owned.process','never-start'),('protocol.file.allow','always'),('include.path','../outside')]:
                    command('config',key,value);rejected(lambda:adapter.execute(args));command('config','--unset',key)
                attributes=repository/'.gitattributes';attributes.write_text('tracked.txt filter=owned\n');rejected(lambda:adapter.execute(args))
        return {'actualNativeGitObjects':True,'hashPinned':True,'networkAccessed':False}
    from .tool_manifest_registry import ToolManifest,ToolManifestRegistry
    from .capability_service import CapabilityService
    from .proofs_b_adapters import _fixture_root
    template=next(row for row in json.loads((REPO/'config/tool_suite_lock.json').read_text(encoding='utf-8'))['tools'] if row['toolId']=='tool.git')
    operations=[dict(operationId='repository.inspect',name='inspect',description='Owned bounded object inspection',permissions=['workspace.read','workspace.write','artifact.write'],inputSchema={'type':'object','properties':{'repository':{'type':'string'}},'required':['repository']},outputSchema={'type':'object','required':['ok','head','receipt']},metadata={'adapterOperation':'repository.inspect'})]
    tool={**template,'state':'verified','workers':['windows'],'selectedVersion':pin['version'].removeprefix('git version '),'installPath':str(Path(git).resolve()),'packageSha256':pin['sha256'],'health':{'status':'healthy'},'operations':operations,'readiness':{'productionValidated':False,'productionEvidence':'','prerequisites':[]}}
    config=root/'config';config.mkdir(exist_ok=True);lock=config/'tool_suite_lock.json';lock.write_text(json.dumps({'schema':'neyvia.tool_suite_lock.v1','tools':[tool]}))
    service=CapabilityService(_fixture_root(root),catalog_path=REPO/'config/capability_packs.json')
    if identity=='adapters.git.readiness':
        description=service.tool_manifests.describe('tool.git');require(description['executionReady'] and not description['productionReady'],'Actual pinned scratch adapter readiness invented production evidence')
        rejected(lambda:ToolManifest.from_payload({**tool,'readiness':{'productionValidated':'false'}}))
        blocked={**tool,'readiness':{'productionValidated':False,'prerequisites':[{'id':'owned-trust','kind':'trust','status':'unprovisioned','requiredFor':['execution','production'],'reason':'Owned boundary','evidence':''}]}}
        manifest=ToolManifest.from_payload(blocked);require(not manifest.readiness_as_dict(runtime_readiness={'evaluated':True,'ready':True})['executionReady'],'Unprovisioned actual supplied trust prerequisite bypassed runtime admission')
        return {'actualNativeGitPinReadiness':True,'productionValidated':False}
    payload={'toolId':'tool.git','operationId':'repository.inspect','arguments':{'repository':'repository'},'permissionMode':'workspace_safe'}
    execution=service.execute_tool_operation(payload);require(execution['ok'] and execution['result']['head']==second,'Actual typed pinned Git operation did not execute')
    declared=execution['result']['artifacts'][0];before=service.artifacts.snapshot()
    if category=='permissions':
        graph_path=service.artifacts.state_path
        with _deny_read(graph_path):
            rejected(lambda:service._register_adapter_artifacts({'result':{'artifacts':[declared]}},capability_id='software.application-engineering',run_id='owned',adapter_id='code.git'))
        require(service.artifacts.snapshot()==before,'Actual denied graph store read/write changed prior graph')
    for patch in [{'sha256':'0'*64},{'derivedFrom':'0'*64}]:
        rejected(lambda:service._register_adapter_artifacts({'result':{'artifacts':[{**declared,**patch}]}},capability_id='software.application-engineering',run_id='owned',adapter_id='code.git'))
        require(service.artifacts.snapshot()==before,'Rejected artifact digest/output lineage mutated graph')
    return {'actualTypedGitExecution':True,'independentArtifactReadback':True,'invalidDeclarationsPreserveGraph':True}


def blocker(contract,category):
    identity=contract.get('id','')
    if identity not in IDS:return None
    if category=='interrupted' and identity not in {'adapters.release.staging','adapters.release.update'}:
        return {'kind':'not_applicable','reason':f'Exact {identity} returns one synchronous local observation/serialized value; no resumable worker or interrupted-completion guarantee is admitted. Completed file bytes and refused staging preserve prior target; no killed task result is counted.'}
    if category=='offline' and identity not in {'adapters.release.staging','adapters.release.update'}:
        return {'kind':'not_applicable','reason':f'Exact {identity} reads explicitly selected local files/objects or projects an explicit readiness declaration. It makes no endpoint request; availability of a remote provider or network is not a precondition for this invariant.'}
    if category in {'concurrency','stale','permissions'} and identity=='adapters.git.readiness':
        return {'kind':'not_applicable','reason':'Exact manifest readiness is a projection of one validated supplied pin and prerequisite declaration, with live installed-binary identity verification. It writes no shared revision/CAS, accepts no caller permission grant and starts no worker; no account/device/native action admission is claimed.'}
    if category in {'concurrency','stale'} and identity in {'adapters.html.scoring','adapters.workflow.publication','adapters.release.update','adapters.git.artifact-registration'} and not(identity=='adapters.release.update' and category=='stale'):
        return {'kind':'not_applicable','reason':f'Exact {identity} deterministically observes one selected source snapshot/operation result and has no revision/CAS claim or concurrent mutation admission. Publication/network/provider effects are not executed; graph rejection preservation is independently read back for every registration fixture.'}
    return None


def run(root,contracts,categories):
    rows=[]
    for identity in sorted(IDS & contracts.keys()):
        for category in categories:
            if blocker(contracts[identity],category):continue
            area=Path(root)/(identity.replace('.','-')+'-'+category+'-'+uuid.uuid4().hex[:8]);area.mkdir(parents=True)
            row={'id':'c7d-adapters.'+identity+'.'+category,'contracts':[identity],'category':category,'boundary':'Actual selected local files/native Git/policy projections; no provider, publication, remote sync or rendered proof'}
            try:
                if identity.startswith('adapters.git.'):detail=_git(area,category,identity)
                elif identity.startswith('adapters.release.'):detail=_release(area,category,identity)
                elif identity=='adapters.handoff.progress':detail=_handoff(area,category)
                elif identity=='adapters.html.scoring':detail=_html(area,category)
                else:detail=_workflow(area,category)
                row.update(status='passed',detail=detail)
            except Exception as error:
                row.update(status='failed',detail={'type':type(error).__name__,'error':str(error),'traceback':traceback.format_exc()[-2500:]})
            rows.append(row)
    return rows
