"""Selected release outcomes, using production observers and confined transports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def agentview(root, area):
    from .neyvia_agentview_checks import self_check
    result = self_check(root, area)
    require(result['ok'] and result['checks'], str(result))
    return result


def models(root):
    from .subprocess_utils import capture_bounded_process
    repo = Path(__file__).resolve().parents[2]
    result = capture_bounded_process(['node', str(repo/'scripts/p22_release_models.mjs')],
        cwd=repo, env=dict(os.environ), input_text=None, timeout=15)
    require(result['returncode'] == 0 and not result['timedOut'], result['stderr'])
    return json.loads(result['stdout'])


def image(root):
    from . import neyvia_image_generate as image
    from . import web_backend
    missing = image.codex_cli_status({'PATH': str(root/'no-executable')})
    require(not missing['ready'] and missing['reason'] == 'codex_cli_missing', str(missing))
    image._write_job(root, 'interrupted', status='running', backendPid=-1, startedAtEpoch=time.time())
    require(image.sweep_stale_jobs(root) == ['interrupted'], 'interrupted image job was left running')
    require(image.list_jobs(root)[0]['status'] == 'failed', 'interrupted image failure was not persisted')
    # The transport is a real owned sleeping Python process. No provider runs.
    popen = subprocess.Popen
    killed = []
    terminate = web_backend._terminate_process_tree
    def child(command, *args, **kwargs):
        if command[:2] == [sys.executable, 'exec']:
            command=[sys.executable, '-I', '-c', 'import time; time.sleep(10)']
        return popen(command, *args, **kwargs)
    def stop(process):
        terminate(process)
        process.wait(timeout=5)
        killed.append(process.returncode is not None)
    with patch.object(image, 'codex_cli_status', return_value={'ready': True, 'path': sys.executable}), \
         patch.object(image.subprocess, 'Popen', side_effect=child), \
         patch.object(web_backend, '_terminate_process_tree', side_effect=stop):
        result = image.generate_image(root=root, request_id='deadline', prompt_text='owned transport',
            size='1x1', out_path=root/'never-created.png', timeout=0.1)
    require(result['reason'] == 'generation_timeout' and killed == [True], 'deadline left its child alive')
    record = next(row for row in image.list_jobs(root) if row['requestId'] == 'deadline')
    require(record['status'] == 'failed' and not image._generation_lock.locked(), 'deadline left a running job or lock')
    require(not (root/'never-created.png').exists(), 'failed generation invented an artifact')
    return {'missingCliRefused': True, 'interruptedJobFailed': True, 'deadlineChildStopped': True}


def sources(root):
    from .connected_sessions.broker import source_problem
    from .connected_sessions.codex_rpc import ConnectionLost, CodexError
    from .connected_sessions.registry import ConnectedError
    rows = [source_problem('codex', ConnectionLost()),
        source_problem('codex', CodexError('app_server_backoff', 'app-server restarting')),
        source_problem('claude-code', ConnectedError('adapter_busy', 'earlier request', 503))]
    require([row['state'] for row in rows] == ['offline', 'offline', 'loading'], str(rows))
    require(all('app-server' not in row['reason'] and 'earlier request' not in row['reason'] for row in rows), str(rows))
    return rows


def folders(root):
    from .connected_sessions import folders as c
    # This is the production candidate builder's direct-query regression,
    # imported from the host's existing checked scratch procedure below.
    from .proofs_a_sessions import check_candidates
    recent, local = [], []
    target = root/'Outside projects'/'Real folder'; target.mkdir(parents=True)
    with patch.object(c, 'projects_root', return_value=root/'projects'):
        result = c.candidates(recent=recent, query=str(target))
    check_candidates(recent, local, str(target), result, root/'projects')
    require(result['direct']['path'] == str(target), 'direct folder query was omitted')
    return result


def cua(root):
    from . import cua_upstream as cua
    with patch.dict(os.environ, {'LOCALAPPDATA': str(root)}, clear=False):
        with patch.dict(os.environ, {}, clear=False):
            previous = os.environ.pop('NEYVIA_CUA_DRIVER_DIR', None)
            try:
                require(cua.runtime_candidates()[0].is_relative_to(root), 'shared helper path escaped synthetic user home')
                status = cua.runtime_status(root/'missing-helper')
                require(not status['available'] and status['code'] == 'missing', str(status))
                require(all(word not in status['reason'] for word in ['cua-driver.exe','install_cua_driver','T16','--source']), str(status))
                try:
                    cua.install_runtime(target=root/'target', fetch=lambda: b'not a verified release')
                except RuntimeError as error:
                    require('SHA256' in str(error), str(error))
                else:
                    raise AssertionError('unverified helper was installed')
                require(not (root/'target/cua-driver.exe').exists(), 'failed helper verification left an executable')
            finally:
                if previous is not None: os.environ['NEYVIA_CUA_DRIVER_DIR'] = previous
    return {'sharedHome': True, 'missingReasonPlain': True, 'badReleaseRefused': True}


def boundary(root):
    from .proof_contracts import before_action, after_action, ContractViolation
    from .proof_credential_guard import check_access
    from .edge_fixture_host_runtime import _native
    from .proof_verifier import _local_arguments, _scratch
    from .proof_credential_guard import install
    install(root)
    confined=_scratch(root)
    native=_native(confined)
    rows=before_action('workspace.read', {'path':'input.txt'})
    require(bool(rows), 'workspace input schema was omitted')
    for action in [lambda: before_action('workspace.read',{'path':7}), lambda: after_action(rows,{'ok':True})]:
        try: action()
        except ContractViolation: pass
        else: raise AssertionError('invalid grounded input or output was delivered')
    result=native.call('neyvia.onboarding.save',{'interests':[],'completed':True})
    require(result['ok'], 'valid schema did not reach the native owner')
    refused=native.call('neyvia.onboarding.save',{'interests':7})
    require(not refused['ok'] and refused['proofs']['phase']=='validation', 'invalid input reached the native owner')
    require(confined.is_relative_to(root/'.agent_control/proofs'), 'proof state escaped its owner')
    for action, error in [(lambda: _local_arguments({'path':'../outside'},confined),ValueError),
                          (lambda: check_access(Path(__file__).parents[2]/'never-opened/auth.json'),PermissionError)]:
        try: action()
        except error: pass
        else: raise AssertionError('escaped path or saved credential was admitted')
    return {'invalidArgumentsRefused':True,'invalidOutputRefused':True,'nativeOwnerReached':True,
            'credentialAccessRefused':True,'scratchEscapeRefused':True}


def coverage(root):
    from . import proof_coverage as c
    from .proof_contracts import file_digest, source_binding_digest
    from .neyvia_agent import NeyviaAgentConfig
    require(NeyviaAgentConfig(root=root,session_id='coverage-owner',permission_mode='read-only').validated().allow_mutations is False,
            'the fresh guarded owner observation failed')
    identity='p22.permission-validation'
    production=Path(__file__).parents[2]
    manifest=json.loads((production/'config/proofs/fast-contracts.json').read_text(encoding='utf-8'))
    row=next(row for row in manifest['contracts'] if row['id']==identity)
    sources={'src/grant_agent/neyvia_agent.py':file_digest(production/'src/grant_agent/neyvia_agent.py')}
    result={'sourceStable':True,'sourceBindings':sources,'areas':[{'area':'owned','ok':True,
        'contracts':[identity],'procedures':[{'id':'fresh-authority','status':'passed'}]}]}
    (root/'receipt.json').write_text(json.dumps(result),encoding='utf-8')
    (root/'manifest.json').write_text(json.dumps({'area':'owned','contracts':[row]}),encoding='utf-8')
    original=root/'original.txt';original.write_text('original retiring case',encoding='utf-8')
    case={'id':'owned-case','name':'owned-case','contract_ids':[identity],'checked_at':row['checkedAt'],
        'source_binding_sha256':source_binding_digest(sources),'self_checks':['receipt.json#areas/owned/procedures/fresh-authority'],
        'manifest':'manifest.json','receipt_sha256':file_digest(root/'receipt.json'),
        'manifest_sha256':file_digest(root/'manifest.json'),'mapping_schema':'neyvia.proofs.coverage.v2'}
    config=root/'config/proofs';config.mkdir(parents=True)
    (config/'test-inventory.json').write_text(json.dumps({'files':[{'path':'original.txt','cases':[case],
        'disposition':'covered','sha256':file_digest(original)}]}),encoding='utf-8')
    with patch.object(c,'REPO',root),patch.object(c,'REVALIDATION',root/'renewal.json'), \
         patch.object(c,'declarations',return_value={identity:row}),patch.object(c,'source_bindings',return_value=sources):
        require(c.coverage_source_current(case,current_sources=sources), 'fresh exact owner observation was refused')
        require(c.retirement_gate(['original.txt'])==[original.resolve()], 'complete unchanged case was not admitted')
        original.write_text('changed case',encoding='utf-8')
        try: c.retirement_gate(['original.txt'])
        except ValueError: pass
        else: raise AssertionError('changed original case was retired')
        bad={**case,'receipt_sha256':'0'*64}
        require(not c.coverage_source_current(bad,current_sources=sources), 'tampered witness was admitted')
        (root/'receipt.json').write_text(json.dumps({**result,'sourceStable':False}),encoding='utf-8')
        try: c.revalidate_existing(root/'receipt.json')
        except ValueError: pass
        else: raise AssertionError('stale witness renewed source authority')
    return {'freshCaseAdmitted':True,'changedOriginalRefused':True,'tamperedWitnessRefused':True,'staleRenewalRefused':True}


def failure(root):
    from .proof_verifier import worker_failure_message
    result = worker_failure_message({'returncode': 0xC0000005, 'stdout': '', 'stderr': ''}, root)
    require('exit code -1073741819' in result and 'no stderr' in result and str(root) in result, result)
    return {'message': result}


def readiness(root):
    from . import proof_readiness as r
    from .proofs_e_host import check_startup_readiness
    # A bounded impact runner supplies fresh pass/partial/fail observations;
    # the real startup owner must turn those into durable readiness correctly.
    for complete in [True, False]:
        report = {'contractsOk': complete, 'since': 'fixture-base', 'commit': 'fixture-head',
            'selectedContracts': ['owned-outcome'], 'uncovered': [], 'unboundContracts': [], 'steps': []}
        with patch('grant_agent.contract_gate.run', return_value=report) as runner:
            result = r.run_now(root, since='fixture-base')
        require(runner.call_args.kwargs['build'] is False, 'startup launched a release build')
        require(r.status(root)['state'] == ('passed' if complete else 'failed'), 'startup did not persist fresh completeness')
        check_startup_readiness({'contractsOk': complete, 'complete': complete}, result)
    return {'completePassed': True, 'partialFailed': True, 'startupBuild': False}


def mod_lifecycle(root):
    from types import SimpleNamespace
    from .source_marketplace import SourceMarketplace
    from .module_plugins import dispatch
    repo=Path(__file__).parents[2]
    market=SourceMarketplace(root)
    installed=market.install(str(repo/'apps/hello-module'))
    require(installed['item']['state']=='disabled', 'new source mod activated without review')
    service=SimpleNamespace(bus=SimpleNamespace(root=root))
    def refused():
        try: dispatch(service,'mod.hello.greet',{'name':'Paul'})
        except ValueError: return True
        return False
    require(refused(), 'disabled mod executed')
    market.set_enabled('hello-module',True)
    answer=dispatch(service,'mod.hello.greet',{'name':' Paul '})
    require(answer['greeting']=='Hello, Paul!', 'active mod did not produce the requested greeting')
    market.set_enabled('hello-module',False)
    require(refused(), 'persisted disable did not close mod dispatch')
    return {'newSourceDisabled':True,'reviewedGreetingExecuted':True,'disabledDispatchRefused':True}


def cl_roundtrip(root):
    from .proof_credential_guard import install, prepare_broker_fixture
    from .neyvia_gateway import NeyviaToolGateway
    from .cl.protocol import Protocol
    install(root)
    work=root/'.agent_control/proofs/compiled-command';work.mkdir(parents=True)
    prepare_broker_fixture(work)
    phrase='P22 persisted 雪 and café'
    gateway=NeyviaToolGateway(work,allow_mutations=True,allowed_mutation_tools={'workspace.write'},managed_capabilities=False)
    protocol=Protocol(gateway,lazy_manuals=True)
    protocol.run('help("workspace")')
    goal='G persisted: workspace.read(path="cl-outcome.txt")["content"] == '+json.dumps(phrase)+'\n'
    result=protocol.run(goal+'workspace.write(path="cl-outcome.txt", content='+json.dumps(phrase)+')')
    target=work/'cl-outcome.txt'
    require(target.is_file(), 'compiled command did not reach its owner: '+json.dumps(result)[:2000])
    require(target.read_text(encoding='utf-8')==phrase,'compiled command failed to persist its exact text')
    readonly=Protocol(NeyviaToolGateway(work,allow_mutations=False,managed_capabilities=False),lazy_manuals=True)
    readonly.run('help("workspace")')
    try: readonly.run(goal+'workspace.write(path="cl-outcome.txt", content="forbidden")')
    except (PermissionError,ValueError): pass
    require(target.read_text(encoding='utf-8')==phrase,'read-only compiled command changed user state')
    try: protocol.run('workspace.write(path="../escape.txt", content="forbidden")')
    except (PermissionError,ValueError): pass
    require(not (work.parent/'escape.txt').exists(),'compiled command escaped the selected workspace')
    return {'compiledActionPersistedExactText':True,'readOnlyMutationRefused':True,'workspaceEscapeRefused':True}


def desktop_asset_path(root):
    from .subprocess_utils import capture_bounded_process
    source=Path(__file__).parents[2]/'src-tauri/build_frontend_guard.rs'
    program=root/'frontend_guard.rs'
    program.write_text('include!('+json.dumps(str(source))+');\nfn main() {\n'
        'for value in [r"C:\\owned\\assets", "D:/owned/assets", "file:///C:/owned/assets", "FILE:///D:/assets"] '
        '{ assert!(invalid_local_frontend_url(value), "{value}"); }\n'
        'for value in ["../web/dist", "./assets", "../owned-render"] '
        '{ assert!(!invalid_local_frontend_url(value), "{value}"); }\n'
        'println!("frontend directory admission passed");\n}',encoding='utf-8')
    binary=root/'frontend_guard.exe'
    compiled=capture_bounded_process([os.environ.get('NEYVIA_GATE_RUSTC','rustc'),'--crate-name','p22_frontend_guard',str(program),'-o',str(binary)],
        cwd=root,env=dict(os.environ),input_text=None,timeout=25)
    require(compiled['returncode']==0 and not compiled['timedOut'],compiled['stderr'])
    observed=capture_bounded_process([str(binary)],cwd=root,env=dict(os.environ),input_text=None,timeout=5)
    require(observed['returncode']==0 and observed['stdout'].strip()=='frontend directory admission passed',observed['stderr'])
    return {'nativeDirectoryAccepted':True,'driveAndFileURLsRefused':True,'downloads':False}


def sdk(root):
    import threading
    import urllib.request
    import urllib.error
    from http.server import ThreadingHTTPServer
    from . import app_sdk,app_sdk_server
    from . import neyvia_app_sdk
    from types import SimpleNamespace
    from .subprocess_utils import capture_bounded_process
    from .proof_ports import proof_port
    app_sdk.new_app(root,{'path':'counter','name':'P22 <owned>','kind':'web'})
    project=root/'counter'; port=proof_port(48461)
    ready=threading.Event(); servers=[]; errors=[]
    def factory(*args,**kwargs):
        server=ThreadingHTTPServer(*args,**kwargs);servers.append(server);ready.set();return server
    def serve():
        try:
            with patch.object(app_sdk_server,'ThreadingHTTPServer',side_effect=factory):app_sdk_server.serve(project,port)
        except Exception as error:errors.append(str(error));ready.set()
    thread=threading.Thread(target=serve,daemon=True);thread.start()
    require(ready.wait(5) and servers, str(errors))
    url=f'http://127.0.0.1:{port}'
    def get(path):
        with urllib.request.urlopen(url+path,timeout=3) as response:return json.load(response)
    def commit(body,headers):
        request=urllib.request.Request(url+'/__neyvia/commit',data=json.dumps(body).encode(),
            headers={'Content-Type':'application/json',**headers},method='POST')
        with urllib.request.urlopen(request,timeout=3) as response:return json.load(response)
    try:
        require(get('/__neyvia/state')=={'count':0,'revision':0}, 'generated app began with the wrong shared state')
        body={'expectedRevision':0,'state':{'count':1},'actionId':'owned-once','fingerprint':'increment'}
        headers={'X-Neyvia-App':'1','Origin':url}
        first=commit(body,headers)
        require(first['after']=={'count':1,'revision':1} and commit(body,headers)==first,
                'SDK state commit or exact replay was not durable')
        require(app_sdk.state_api(project)==get('/__neyvia/state')=={'count':1,'revision':1},
                'host and running app observed different shared state')
        service=SimpleNamespace(bus=SimpleNamespace(root=root),safe_path=lambda path:app_sdk.confined(root,str(path)))
        require(neyvia_app_sdk.call(service,'app_sdk.state',{'project':'counter'})['state']=={'count':1,'revision':1},
                'native SDK transport observed different state')
        cli=capture_bounded_process([sys.executable,str(Path(__file__).parents[2]/'scripts/app_sdk.py'),
            'state','--project','counter'],cwd=root,env=dict(os.environ),input_text=None,timeout=10)
        require(cli['returncode']==0 and json.loads(cli['stdout'])['state']=={'count':1,'revision':1},
                'SDK CLI observed different state: '+cli['stderr'])
        for payload,header in [(body,{}),({**body,'actionId':'stale'},headers),
                               ({**body,'expectedRevision':1,'state':{'count':-1},'actionId':'bad'},headers),
                               ({**body,'actionId':'foreign'}, {'X-Neyvia-App':'1','Origin':'https://outside.invalid'})]:
            try:commit(payload,header)
            except urllib.error.HTTPError as error:require(error.code in {403,409}, str(error))
            else:raise AssertionError('unauthorized, stale or invalid SDK commit reached shared state')
        require(get('/__neyvia/state')=={'count':1,'revision':1}, 'refused SDK mutations changed state')
    finally:
        servers[0].shutdown();thread.join(timeout=5)
        require(not thread.is_alive(), 'owned SDK server was left running')
    return {'generatedAppServed':True,'sharedStateDurable':True,'onceOnlyReplay':True,
            'missingAuthorityRefused':True,'staleAndNegativeCountRefused':True,'foreignOriginRefused':True}


def sdk_clients(root):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from .proof_ports import proof_port
    from .subprocess_utils import capture_bounded_process
    from neyvia_sdk import NeyviaClient, NeyviaError
    class TransportHost(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            denied=body.get('command')=='deny'
            answer={'ok':False,'error':'Sign in'} if denied else {'ok':True,'data':{'body':body,'app':self.headers.get('X-Neyvia-App',''),'path':self.path}}
            encoded=json.dumps(answer).encode()
            self.send_response(401 if denied else 200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)))
            self.end_headers();self.wfile.write(encoded)
    server=ThreadingHTTPServer(('127.0.0.1',proof_port(48461)),TransportHost)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        sdk=NeyviaClient(origin,timeout=3)
        sent=sdk.remember(key='cue',content='雪🙂',request_id='once',session_id='session')
        require(sent['path']=='/api/backend' and sent['body']=={'command':'memory_remember_command','payload':{
            'key':'cue','content':'雪🙂','requestId':'once','kind':'fact','cues':{},'exportPolicy':'local','sessionId':'session'}},
            'Python SDK changed Unicode, local export policy, request identity or routing')
        require(sdk.manual(layer='notes',chapter='overview',level=2)['body']=={
            'tool':'neyvia.cl.describe','arguments':{'layer':'notes','chapter':'overview','level':2}}, 'SDK manual arguments changed')
        try:sdk.command('deny')
        except NeyviaError as error:require(error.code=='login_required' and error.status==401, 'SDK lost the typed owner denial')
        else:raise AssertionError('SDK admitted a refused transport response')
        for url in ['https://outside.invalid','http://127.0.0.1:49081/outside','http://user:password@127.0.0.1:49081']:
            try:NeyviaClient(url)
            except ValueError:pass
            else:raise AssertionError('Python SDK accepted an unowned authority URL')
        result=capture_bounded_process(['node',str(Path(__file__).parents[2]/'scripts/p22_release_models.mjs'),'sdk-client',origin],
            cwd=Path(__file__).parents[2],env=dict(os.environ),input_text=None,timeout=10)
        require(result['returncode']==0 and json.loads(result['stdout'])['ok'], result['stderr'])
    finally:
        server.shutdown();server.server_close();thread.join(5)
        require(not thread.is_alive(),'SDK transport host was left running')
    return {'pythonAndBrowserSdkDeliveredExactRequests':True,'unicodeAndLocalExportPreserved':True,
            'typedOwnerDenials':True,'unownedUrlsRefused':True,'boundary':'Actual clients and owned HTTP transport; no live provider or host authentication claim'}


def laya_scene(root):
    from .proof_ports import proof_port
    from .laya_glance_contracts import observe
    with patch.dict(os.environ, {'NEYVIA_LAYAG_PORT':str(proof_port(48461))}):
        result=observe()
    require(result.get('passed') is True and result.get('count',0)>0,
            'LAYA missed a controlled before/after DOM predicate: '+str(result))
    return result


def laya_pixels(root):
    from .laya_glance_proof import run
    result=run()
    require(result.get('passed') is True, 'LAYA pixel before/after proof failed: '+str(result))
    return result


def language_copy(root):
    from .neyvia_language import check
    repo=Path(__file__).resolve().parents[2]
    clean=root/'clean.html';bad=root/'bad.html'
    clean.write_text('<button>Open settings</button><style>.owned{font-family:"Open — settings"}</style>',encoding='utf-8')
    bad.write_text('<button>Open — settings</button>',encoding='utf-8')
    for skill in ['manuals/skills/no-slop.cl','config/cl_skills/no-slop.cl']:
        accepted=check(files=[clean],kind='ui',skill_path=repo/skill)
        refused=check(files=[bad],kind='ui',skill_path=repo/skill)
        require(accepted['blockingHits']==0 and refused['blockingHits']>0,
                'Language skill missed bad label copy or treated stylesheet source as a label: '+skill)
        require(any(row.get('evidence') for row in refused['results'] if row['status']=='fail'),
                'Language refusal lost the exact label evidence')
    return {'visibleLabelRefused':True,'cleanLabelAccepted':True,'stylesheetSourceIgnored':True,'bothSkillSourcesExercised':True}


def watch_pages(root):
    from types import SimpleNamespace
    from .ui_command_bus import UICommandBus
    from .neyvia_run_watches import call
    service=SimpleNamespace(bus=UICommandBus(root))
    with service.bus.connect() as db:
        db.executemany('INSERT INTO state(key,value) VALUES (?,?)',
            [('watch:'+str(i),json.dumps({'id':str(i),'status':'armed'})) for i in range(45)])
    seen=[]
    for offset,expected_next in [(0,20),(20,40),(40,None)]:
        page=call(service,'watch.list',{'offset':offset,'limit':20})
        require(page['nextOffset']==expected_next, 'Watch pagination lost its continuation after the first page')
        seen.extend(row['id'] for row in page['watches'])
    require(seen==[str(i) for i in range(45)], 'Paged watches skipped, duplicated or reordered saved watches')
    return {'allSavedWatchesReachable':True,'secondPageContinuationPreserved':True,'lastPageStops':True}


def timers(root):
    from types import SimpleNamespace
    from .ui_command_bus import UICommandBus
    from . import neyvia_time_tools as timer
    service=SimpleNamespace(bus=UICommandBus(root))
    with patch.object(timer.time,'monotonic',return_value=10):
        timer.call(service,'timer.start',{'id':'owned','label':'Execution'})
    with patch.object(timer.time,'monotonic',return_value=13):
        lap=timer.call(service,'timer.lap',{'id':'owned','lapId':'checkpoint','label':'First'})['lap']
        replay=timer.call(service,'timer.lap',{'id':'owned','lapId':'checkpoint','label':'First'})
    require(lap['elapsedSeconds']==3 and replay['replayed'] and replay['lap']==lap, 'Timer checkpoint replay changed elapsed time or duplicated a lap')
    with patch.object(timer.time,'monotonic',return_value=20):
        timer.call(service,'timer.stop',{'id':'owned'})
    service.bus=UICommandBus(root)
    with patch.object(timer.time,'monotonic',return_value=1000):
        saved=timer.call(service,'timer.read',{'id':'owned'})['timer']
    require(saved['status']=='stopped' and saved['elapsedSeconds']==10 and saved['lapCount']==1,
            'Reopened stopped timer advanced or lost its exact checkpoint')
    try:timer.call(service,'timer.start',{'id':'owned','label':'Changed intent'})
    except ValueError:pass
    else:raise AssertionError('A retained timer ID accepted a different intent')
    return {'lapOnceOnly':True,'stoppedElapsedDurable':True,'changedIntentRefused':True}


def cl_history(root):
    from .cl.turn_context import TurnContext, ContextBudgetError
    context=TurnContext('Keep the exact request 雪','Owned prefix',archive_dir=root/'history')
    text='First line 雪🙂\nSecond line with literal \\n'
    handle=context.append('user',text)
    reopened=TurnContext(context.task,context.prefix,archive_dir=root/'history')
    page=json.loads(reopened.read(handle,count=11))
    next_page=json.loads(reopened.read(handle,start=page['nextStart']))
    require(page['text']+next_page['text']==text and reopened.task==context.task,
            'Reopened CL history lost exact Unicode text, offsets or immutable task')
    try:TurnContext('A different task',context.prefix,archive_dir=root/'history')
    except ValueError:pass
    else:raise AssertionError('A different task reused the retained history archive')
    try:TurnContext('A request too large for one token','',token_budget=1,archive_dir=root/'small')
    except ContextBudgetError:pass
    else:raise AssertionError('A tiny prompt budget truncated the immutable task')
    path=root/'history'/(handle+'.json')
    record=json.loads(path.read_text(encoding='utf-8'));record['record']['content']='altered'
    path.write_text(json.dumps(record),encoding='utf-8')
    try:reopened.read(handle)
    except ValueError:pass
    else:raise AssertionError('History retrieval returned tampered content')
    return {'pagedUnicodeExact':True,'taskReuseRefused':True,'taskNeverTruncated':True,'tamperedReadRefused':True}


def context_replay(root):
    from copy import deepcopy
    from .chat_context import LEGACY_DESCRIPTIONS, WORKSPACE_DESCRIPTION, normalize_replay_context
    from .context_window import bounded_history
    legacy = next(text for text in LEGACY_DESCRIPTIONS if text != WORKSPACE_DESCRIPTION)
    quoted = 'Workflow intent: ' + legacy
    envelope = ('Current request 雪\n\nCurrent workspace context:\nWorkspace: owned\nWorkspace path: owned\n'
                + quoted + '\n\nRecent conversation:\n' + quoted)
    history = [{'role':'user','content':quoted}, {'role':'user','content':envelope},
               {'role':'assistant','content':quoted}]
    frozen = deepcopy(history)
    repaired = normalize_replay_context(history)
    require(repaired[0] == frozen[0] and repaired[2] == frozen[2], 'User or assistant prose was rewritten')
    require('Workflow intent: ' + WORKSPACE_DESCRIPTION in repaired[1]['content'] and
            repaired[1]['content'].endswith(quoted), 'Generated metadata repair changed quoted history')
    require(history == frozen, 'Replay repair changed the durable input records')
    exchanges = [{'role':'user','content':'old request'}, {'role':'assistant','content':'old response'},
                 {'role':'user','content':'current request'},
                 {'role':'assistant','tool_calls':[{'id':'owned-call','function':{'name':'read'}}]},
                 {'role':'tool','tool_call_id':'owned-call','content':'雪 result'},
                 {'role':'assistant','content':'current response'}]
    frozen = deepcopy(exchanges)
    replay, omitted = bounded_history(exchanges, character_budget=1, item_budget=1)
    require(omitted == 2 and replay[1:] == exchanges[2:], 'Context limit split the current tool exchange')
    require('remain saved' in replay[0]['content'] and exchanges == frozen, 'Compaction lost continuity or modified the archive')
    require(bounded_history(exchanges)[0] is exchanges, 'Unbounded replay unexpectedly rewrote history')
    return {'userAndQuotedHistoryPreserved':True,'generatedMetadataRepaired':True,
            'currentToolExchangeIntact':True,'sourceHistoryUnchanged':True}


def context_admission(root):
    from .compaction_policy import resolve_policy, ContextMeter, estimate_tokens
    cache = root/'.agent_control/provider_model_catalog.modelsdev.json'
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({'catalog':{'owned':{'models':{'local':{
        'limit':{'context':100000,'output':10000}, 'cost':{'input':1,'tiers':[
            {'tier':{'type':'context','size':20000},'input':2}]}}}}}}),encoding='utf-8')
    with patch.dict(os.environ, {'NEYVIA_CONTEXT_CATALOG_ROOT':str(root)}):
        ordinary = resolve_policy(root,'owned','local')
        require(ordinary.trigger == 85000, 'Pricing silently imposed a stop budget')
        (root/'config').mkdir()
        policy = root/'config/neyvia_context_policy.json'
        policy.write_text(json.dumps({'mode':'avoid-price-increase'}),encoding='utf-8')
        require(resolve_policy(root,'owned','local').trigger == 18000, 'Explicit price admission was ignored')
        try:resolve_policy(root,'owned','local',max_output_tokens=100000)
        except ValueError:pass
        else:raise AssertionError('Impossible output reservation was admitted')
    meter = ContextMeter('owned instructions',[])
    prefix=[{'role':'user','content':'雪🙂 preserved'}]
    meter.sent(prefix);meter.observe(731)
    require(meter.measure(prefix)==731, 'Measured usage did not replace the unchanged prefix estimate')
    require(meter.measure(prefix+[{'role':'user','content':'next'}]) > 731, 'New input inherited zero token cost')
    changed=[{'role':'user','content':'changed'}]
    require(meter.measure(changed)!=731 and estimate_tokens('雪🙂')>estimate_tokens('ab'), 'Changed or Unicode input inherited stale usage')
    return {'capacityDefault':True,'explicitPricePolicyHonoured':True,'impossibleReservationRefused':True,
            'providerUsageBoundToUnchangedPrefix':True,'unicodeCounted':True}


def compiled_maps(root):
    from .compiled_tool_maps import CompiledToolMapStore
    store = CompiledToolMapStore()
    original = {'callMap':{'workspace.act':{'callTarget':'workspace.read','boundArguments':{'path':'first.txt'},'provenance':{'source':'owned'}}}}
    first = store.retain(original)
    original['callMap']['workspace.act']['callTarget']='unexpected'
    second = store.retain({'callMap':{'workspace.act':{'callTarget':'workspace.write','boundArguments':{'path':'second.txt'},'provenance':{'source':'owned'}}}})
    require(store.resolve('workspace.act@'+first, {})['callTarget']=='workspace.read', 'An old map changed meaning')
    resolved = store.resolve('workspace.act@'+second, {'content':'雪'})
    require(resolved['callTarget']=='workspace.write' and resolved['arguments']=={'path':'second.txt','content':'雪'}, 'New map lost its exact target or supplied arguments')
    for selection in ['workspace.act','other.act@'+first,'workspace.act@missing']:
        try:store.resolve(selection,{})
        except (KeyError,ValueError):pass
        else:raise AssertionError('An ambiguous or absent provider call fell back to another map')
    return {'retainedMeaningImmutable':True,'exactVersionExecuted':True,'ambiguousAndUnknownCallsRefused':True}


def app_registry(root):
    from .app_factory_semantics import register_app_factory_job, _load_registry
    project=root/'app';project.mkdir();(project/'main.js').write_text('export const title="First";',encoding='utf-8')
    registry=root/'applications.json'
    job={'spec':{'appId':'owned-app','target':'web'},'projectRoot':str(project),'jobId':'first',
         'permissions':[{'kind':'read','scope':'owned'}]}
    first=register_app_factory_job(job,persist_path=registry)
    require(first.health['deployment']=='not attempted' and first.health['state']=='unknown', 'Local registration invented publication or verification')
    (project/'main.js').write_text('export const title="Second";',encoding='utf-8')
    job['jobId']='second'
    updated=register_app_factory_job(job,persist_path=registry)
    reopened=_load_registry(registry).get('owned-app')
    require(reopened.source['jobId']=='second' and reopened.permissions==job['permissions'], 'Reopened registry lost the source job or permissions')
    revisions=[row for row in updated.history if row.get('event')=='app_factory_revision']
    require(len(revisions)==2 and updated.rollback['previousRevision']==first.source['revision'] and
            not updated.rollback['available'], 'Source change lost lineage or advertised an unavailable rollback')
    registry.write_text('{broken',encoding='utf-8')
    try:register_app_factory_job(job,persist_path=registry)
    except ValueError:pass
    else:raise AssertionError('An unreadable registry was silently replaced')
    require(registry.read_text(encoding='utf-8')=='{broken', 'Refused registration overwrote damaged state')
    return {'persistedSourceAndPermission':True,'upgradeLineagePreserved':True,'publicationNotInvented':True,
            'damagedRegistryPreserved':True}


def lesson_preferences(root):
    from .lesson_evolver import LessonService, FrozenJudge, LearnedJudge, digest, _preference_pairs
    import hashlib
    manifest = {'task': 'Read input.txt and write result.md', 'inputs': {'input.txt': 'Public replay fixture'},
                'outputs': ['result.md'], 'validator': None}
    service = LessonService(root)
    identity = service.freeze_suite([manifest])
    saved = json.loads((root / '.neyvia/lessons/suite.json').read_text(encoding='utf-8'))
    require(identity == digest(saved) and saved['manifests'] == [manifest]
            and saved['pairsSha256'] == hashlib.sha256(_preference_pairs()[0]).hexdigest(),
            'Objective suite lost its exact replay or calibration-source binding')
    refused = []
    for judge in (FrozenJudge, LearnedJudge):
        try:
            judge(root).calibrate()
        except ValueError as error:
            require('nonempty reviewed preference comparisons' in str(error), str(error))
            refused.append(judge.__name__)
        else:
            raise AssertionError('Unlabelled public seed admitted taste calibration')
    require(not (root / '.neyvia/lessons/judge.json').exists()
            and not (root / '.neyvia/lessons/preference-judge.json').exists(),
            'Refused calibration saved a successful judge')
    return {'suiteHash': identity, 'uncalibratedJudgesRefused': refused}


GROUPS = [
    ('lesson-preferences', ['p29.lesson-public-calibration'], lesson_preferences),
    ('sdk-clients', ['p22.sdk-clients'], sdk_clients),
    ('laya-scene', ['layag.scene-predicates'], laya_scene),
    ('laya-pixels', ['layag.pixel-before-after'], laya_pixels),
    ('language-copy', ['p22.language-copy'], language_copy),
    ('watch-pages', ['p22.watch-pages'], watch_pages),
    ('timers', ['p22.timer-durable'], timers),
    ('cl-history', ['p22.cl-history'], cl_history),
    ('context-replay', ['p22.context-replay'], context_replay),
    ('context-admission', ['p22.context-admission'], context_admission),
    ('compiled-maps', ['p22.compiled-maps'], compiled_maps),
    ('app-registry', ['p22.app-registry'], app_registry),
    ('desktop-asset-path', ['p22.desktop-asset-path'], desktop_asset_path),
    ('compiled-command', ['p22.compiled-command'], cl_roundtrip),
    ('mod-lifecycle', ['p22.mod-lifecycle'], mod_lifecycle),
    ('sdk', ['p22.sdk-state'], sdk),
    ('agentview-stream', ['agentview.delta','agentview.demand'], lambda root: agentview(root,'stream')),
    ('agentview-timeline', ['agentview.bounds'], lambda root: agentview(root,'timeline')),
    ('agentview-feedback', ['agentview.feedback'], lambda root: agentview(root,'feedback')),
    ('models', ['agentview.poll','agentview.applyFrame','agentview.feedbackPayload','gamedev.sessionLabel',
                'image.queue.failed-timeline'], models),
    ('image', ['image.generate.deadline','image.generate.preflight','image.generate.job-settled'], image),
    ('sources', ['sessions.sources-calm'], sources),
    ('folders', ['sessions.folders.direct'], folders),
    ('helper', ['cua.helper-resolution'], cua),
    ('proof-boundary', ['proofs.manual-input','proofs.manual-output','proofs.scratch-isolation','proofs.saved-credential-boundary'], boundary),
    ('proof-coverage', ['proofs.retirement-coverage','proofs.source-revalidation'], coverage),
    ('worker-failure', ['proofs.worker-failure-report'], failure),
    ('startup', ['proofs.background-readiness'], readiness),
]


def self_check(root):
    from .contract_gate import wants
    root=Path(root); root.mkdir(parents=True, exist_ok=True)
    cases=[]; started=time.perf_counter()
    for name, identities, action in GROUPS:
        if not wants(identities): continue
        scratch=root/name; scratch.mkdir()
        case_started=time.perf_counter()
        try:
            result=action(scratch)
            cases.append({'id':name, 'contracts':identities, 'ok':True, 'observed':result})
        except Exception as error:
            import traceback
            cases.append({'id':name, 'contracts':identities, 'ok':False, 'error':str(error), 'traceback':traceback.format_exc()[-3000:]})
        cases[-1]['durationMs']=round((time.perf_counter()-case_started)*1000)
    return {'ok':bool(cases) and all(row['ok'] for row in cases), 'cases':cases,
            'durationMs':round((time.perf_counter()-started)*1000)}
