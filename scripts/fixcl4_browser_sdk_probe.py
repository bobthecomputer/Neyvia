"""Real private Neyvia browser sessions, SDK goals and frozen LAYA advice.

Every port is explicit. LAYA uses existing frozen weights on CPU and a new
task-local database; training, calibration and saved services are untouched.
"""
from __future__ import annotations
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.parse import urlsplit

from fixcl_verify import REPO, environment, bind_fixture_broker


def setup(args):
    ports={args.port,args.browser_port,args.ipc_port,args.laya_port}
    if len(ports)!=4 or not ports.issubset(set(range(48821,48830))):
        raise ValueError('Four distinct explicitly assigned FIXCL ports required')
    root=REPO/'.agent_control/proofs'/('FIXCL4-browser-sdk-'+str(time.time_ns()));root.mkdir(parents=True)
    environment(root,args.port)
    os.environ.update(NEYVIA_OBSCURA_EXE=str(args.obscura),NEYVIA_BROWSER_PROOF_PORTS=','.join(map(str,ports)),
                      NEYVIA_LAYA_URL=f'http://127.0.0.1:{args.laya_port}',LAYA_CPU_THREADS='1',
                      HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from grant_agent.proof_credential_guard import install,prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(root);install_hidden_subprocess_default();prepare_broker_fixture(root);bind_fixture_broker(root)
    def guard(event,values):
        if event in {'socket.bind','socket.connect'}:
            address=values[1]
            if isinstance(address,tuple) and (address[0] not in {'127.0.0.1','localhost','::1'} or address[1] not in ports):
                raise PermissionError('Browser/SDK proof confines sockets to assigned loopback ports')
    sys.addaudithook(guard)
    if sys.platform=='win32':
        def assigned_pair(family=socket.AF_INET,type=socket.SOCK_STREAM,proto=0):
            listener=socket.socket(family,type,proto);client=socket.socket(family,type,proto)
            try:
                listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                listener.bind(('127.0.0.1',args.ipc_port));listener.listen(1)
                client.connect(('127.0.0.1',args.ipc_port));accepted,_=listener.accept();return accepted,client
            except BaseException:
                client.close();raise
            finally:listener.close()
        socket.socketpair=assigned_pair
    return root


def run(args):
    root=setup(args)
    source_paths=[Path(__file__),*(REPO/'src/grant_agent/cl').glob('*.py')]
    source_paths += [REPO/'src/grant_agent'/name for name in ('perception_browser.py','app_sdk.py','neyvia_browser.py','neyvia_perception.py','neyvia_workspace_tools.py')]
    source_paths += [REPO/'manuals/cl/local-browser-sdk.cl',REPO/'manuals/local-browser-sdk.manual.json',REPO/'config/neyvia_manuals.json',REPO/'config/fixcl_manual_cache.json']
    source_start={str(path.relative_to(REPO)):hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.neyvia_workspace_tools import workspace_for
    from grant_agent.neyvia_browser import service_for
    from grant_agent.neyvia_perception import browsers
    from grant_agent.neyvia_mobile_studio import serve_preview,PREVIEW_PREFIX
    from grant_agent.app_sdk import new_app
    result={'schema':'neyvia.FIXCL4.browser-sdk.v1','root':str(root),'checks':{},'journeys':{},
            'boundary':'Actual explicit non-stealth Neyvia Obscura contexts, fresh DOM actions, current SDK shared state and running goals; actual frozen LAYA CPU advice has no execution authority.'}
    service=workspace_for(root)
    page=b'<!doctype html><html><head><title>Actual browser SDK witness</title></head><body><h1>Fresh private DOM</h1><label>Name<input id="name" aria-label="Name"></label><button onclick="document.querySelector(\'#result\').textContent=\'clicked actual DOM\'">Act</button><p id="result">Ready</p></body></html>'
    class Handler(BaseHTTPRequestHandler):
        def route(self,method):
            parsed=urlsplit(self.path)
            if parsed.path.startswith(PREVIEW_PREFIX):serve_preview(root,self,parsed,method);return
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(page)));self.end_headers();self.wfile.write(page)
        def do_GET(self):self.route('GET')
        def do_POST(self):self.route('POST')
        def do_OPTIONS(self):self.route('OPTIONS')
        def log_message(self,*values):pass
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    browser=service_for(root);browser.request('headless.start',{'port':args.browser_port,'allowLocalFixtures':True},owner=True)
    gateway=NeyviaToolGateway(root,allow_mutations=True,action_scope='FIXCL4-browser-sdk',permission_mode='workspace')
    def action(key,name,payload,goal='time.now()["unixSeconds"] > 0', protocol=None):
        p=protocol or Protocol(gateway,lazy_manuals=True)
        if name in {'neyvia.perception.browser.action','neyvia.perception.browser.close'} and protocol is None:
            p.run('perception.browser.observe()')
        source='G: '+goal+'\nrun local-browser-sdk.'+name.removeprefix('neyvia.').replace('.','-')+'('+','.join(k+'='+json.dumps(v) for k,v in payload.items())+')\ndone()'
        observed=p.run(source,action_id=key)
        result['journeys'][key]={'source':source,'run':observed}
        result['checks'][key+'.positiveCL']=observed.get('ok') is True and p.completion()['status']=='completed'
        return p
    def completion_drift(key,p,change,restore):
        change();result['checks'][key+'.driftRefused']=p.completion()['status']=='incomplete'
        restore();observed=p.run('done()',action_id=key+'-restore')
        result['checks'][key+'.restorationRevalidates']=observed.get('ok') is True and p.completion()['status']=='completed'
    laya_server=laya_engine=None
    try:
        url=f'http://127.0.0.1:{args.port}/'
        opened=action('perception-open','neyvia.perception.browser.open',{'url':url})
        sessions=browsers(service)
        sid=next(iter(sessions.sessions)) if sessions.sessions else None
        if sid:
            if result['checks']['perception-open.positiveCL']:
                def navigate(target):sessions.worker.submit(lambda:sessions.sessions[sid]['page'].goto(target,wait_until='domcontentloaded')).result(timeout=20)
                completion_drift('perception-open',opened,lambda:navigate(url+'#actual-drift'),lambda:navigate(url))
            observed=sessions.run('observe',sid);target=next(e for e in observed['elements'] if e['name']=='Name')
            applied=action('perception-fill','neyvia.perception.browser.action',{'element':target['id'],'action':'fill','value':'actual owner value'})
            def setvalue(value):sessions.worker.submit(lambda:sessions.sessions[sid]['page'].locator('#name').fill(value)).result(timeout=10)
            if result['checks']['perception-fill.positiveCL']:
                completion_drift('perception-fill',applied,lambda:setvalue('changed actual owner'),lambda:setvalue('actual owner value'))
            # Drift the actual page after the host's observation. Host-owned
            # stamps stay internal; the action must refuse the stale state.
            setvalue('independent actual drift')
            stale=action('perception-stale','neyvia.perception.browser.action',{'element':target['id'],'action':'fill','value':'must not apply'},protocol=applied)
            current=sessions.run('observe',sid)
            result['checks']['perception-stale.positiveCL']=not result['journeys']['perception-stale']['run'].get('ok') and next(e for e in current['elements'] if e['id']==target['id'])['value']=='independent actual drift'
            setvalue('actual owner value')
            closed=action('perception-close','neyvia.perception.browser.close',{})
            result['checks']['perception-close.actualContextGone']=sid not in sessions.sessions and browser.headless.status()['connected']
            if result['checks']['perception-close.positiveCL']:
                extra=sessions.run('open',url)['browserId']
                result['checks']['perception-close.newActualSessionRefusesDone']=closed.completion()['status']=='incomplete'
                sessions.run('close_one',extra)
                result['checks']['perception-close.restoreConservationRevalidates']=closed.run('done()',action_id='perception-close-restored').get('ok') is True
        app=root/'sdk-app'
        new_app(root,{'path':str(app),'name':'Actual Browser SDK','kind':'web'})
        from grant_agent.neyvia_mobile_studio import preview_token
        token=preview_token(service,app);appurl=f'http://127.0.0.1:{args.port}{PREVIEW_PREFIX}{token}/'
        verified=action('sdk-verify','neyvia.app_sdk.verify',{'project':str(app),'url':appurl,'clSource':'','native':{},'steps':[]})
        if result['checks']['sdk-verify.positiveCL']:
            retained=json.loads((app/'.neyvia/latest-verification.json').read_bytes());image=Path(retained['screenshot']);raw=image.read_bytes()
            completion_drift('sdk-verify',verified,lambda:image.write_bytes(raw+b'actual drift'),lambda:image.write_bytes(raw))
            file=app/'www/sdk.js';raw=file.read_bytes()
            completion_drift('sdk-source',verified,lambda:file.write_bytes(raw+b'\n// actual source drift'),lambda:file.write_bytes(raw))
        # The attached local service is the real installed frozen transformer.
        if not args.skip_laya:
            sys.path.insert(0,str(args.laya_source))
            # Transformers 5 moved this exact initialization context. Adapt
            # only the import in this owned process; keep the runtime and
            # checkpoint unchanged, and record the actual helper provenance.
            import transformers.modeling_utils as modeling_utils
            if not hasattr(modeling_utils,'no_init_weights'):
                from transformers.initialization import no_init_weights
                modeling_utils.no_init_weights=no_init_weights
                import inspect
                helper=Path(inspect.getsourcefile(no_init_weights))
                result['runtimeImportCompatibility']={'from':'transformers.initialization.no_init_weights',
                    'target':'transformers.modeling_utils.no_init_weights','helperSha256':hashlib.sha256(helper.read_bytes()).hexdigest(),
                    'scope':'This task process only; no package or saved service changes'}
            import importlib.util
            original_runtime=args.laya_source/'laya_system1/runtime.py'
            original=original_runtime.read_text(encoding='utf-8')
            anchor='                if name != "inv_freq" or not hasattr(module, "rope_init_fn"):'
            if original.count(anchor)!=1:raise RuntimeError('Frozen LAYA buffer compatibility anchor changed')
            # Transformers 5 retains the actual rotary function but now keeps
            # separate full/local non-checkpoint frequency buffers. Restore
            # them with that installed function, preserving strict weights.
            adaptation='''                if name.endswith("_inv_freq") and hasattr(module, "compute_default_rope_parameters"):
                    layer = name.removesuffix("_inv_freq").removesuffix("_original")
                    if module.rope_type[layer] != "default":
                        raise ValueError("Unsupported non-default rotary compatibility")
                    frequencies, scaling = module.compute_default_rope_parameters(module.config, agent.device, layer_type=layer)
                    module.register_buffer(name, frequencies, persistent=False)
                    setattr(module, layer + "_attention_scaling", scaling)
                    continue
'''
            compatible=root/'frozen_laya_runtime_compat.py';compatible.write_text(original.replace(anchor,adaptation+anchor),encoding='utf-8')
            spec=importlib.util.spec_from_file_location('fixcl4_frozen_laya_runtime',compatible)
            installed=importlib.util.module_from_spec(spec);sys.modules[spec.name]=installed;spec.loader.exec_module(installed)
            Runtime=installed.Runtime
            result['runtimeImportCompatibility'].update(originalRuntimeSha256=hashlib.sha256(original_runtime.read_bytes()).hexdigest(),
                compatibleRuntimeSha256=hashlib.sha256(compatible.read_bytes()).hexdigest(),
                bufferCompatibility='Installed ModernBERT full/local rotary frequency reconstruction only; strict checkpoint assignment preserved')
            from laya_system1.service import Engine,create_server
            runtime=Runtime(args.laya_model,device='cpu',encoding='prepared')
            laya_engine=Engine(runtime,root/'laya.sqlite',str(args.laya_source/'question_sets'))
            laya_server=create_server(laya_engine,port=args.laya_port)
            threading.Thread(target=laya_server.serve_forever,daemon=True).start()
            from grant_agent.laya_service import attach_browser
            if browser.laya_client is None:
                attach_browser(browser)
            elif browser.laya_client.hook.endpoint != f'http://127.0.0.1:{args.laya_port}':
                raise ValueError('Existing browser advice route differs from the selected owned LAYA service')
            # CPU advice may take longer than the production service default;
            # this owned run advertises its explicit bounded 20-second age.
            browser.laya_client.hook.timeout_s=20;browser.laya_client.hook.max_age_ms=20000
            tab=browser.request('tab.open',{'url':url,'engine':'obscura'},owner=True)['tabId']
            decided=action('browser-decide','neyvia.browser.decide',{'tabId':tab,'question':'page_done','context':{'goal':'Read the ready page; advice only'}})
            result['modelIdentity']=runtime.identity
            if result['checks']['browser-decide.positiveCL']:
                path=next((browser.directory/'decisions').glob('*.json'));raw=path.read_bytes()
                completion_drift('browser-decide',decided,lambda:path.write_bytes(raw+b'\nactual drift'),lambda:path.write_bytes(raw))
                worker=browser.headless.profiles[browser.tab({'tabId':tab})['profileId']]
                def actual_text(value):worker.executor.submit(lambda:worker.pages[tab]['page'].locator('#result').evaluate('(el,value)=>el.textContent=value',value)).result(timeout=10)
                completion_drift('browser-decide-dom',decided,lambda:actual_text('real page changed after inference'),lambda:actual_text('Ready'))
            # Keep the headless page intact when forbidden visible promotion is
            # refused; no simulated WebView2 runtime is connected or ACKed.
            prior=browser.projection(tab)
            try:browser.request('promote',{'tabId':tab},owner=True);denied=False
            except Exception as exc:
                denied=getattr(exc,'code',None)=='runtime_unavailable'
                result['promotionBoundary']={'needs':'Owner-authorized actual WebView2 runtime on an allowed desktop; visible windows are prohibited by this task','proof':'Export cookies/storage/non-secret form state, actual native import/open ACK plus fresh native DOM of the same tab and values; preserve headless page on import failure','observedError':str(exc)}
            result['checks']['browser-promotion.forbiddenRuntimeRefusedConservesPage']=denied and browser.projection(tab)==prior and browser.headless.status()['connected']
        result['manualReceipts']=[row['payload'] for row in service.bus.since(0) if row['action']=='cl.manual.use']
        expected={'neyvia.perception.browser.open','neyvia.perception.browser.action','neyvia.perception.browser.close','neyvia.app_sdk.verify'}
        if not args.skip_laya:expected.add('neyvia.browser.decide')
        result['checks']['everyAdapterCurrentManualEffectReceipt']=all(any(row.get('tool')==name and row.get('status')=='admitted' and row.get('effectChecks') for row in result['manualReceipts']) for name in expected)
    finally:
        if laya_server:laya_server.shutdown();laya_server.server_close()
        if laya_engine:laya_engine.close()
        if hasattr(service,'_perception_browser'):service._perception_browser.close()
        browser.request('headless.stop',{},owner=True)
        server.shutdown();server.server_close()
    result['sourceHashesAtStart']=source_start
    result['sourceHashesAtEnd']={str(path.relative_to(REPO)):hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    result['checks']['sourceUnchanged']=result['sourceHashesAtStart']==result['sourceHashesAtEnd']
    result['ok']=all(result['checks'].values())
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('port','browser-port','ipc-port','laya-port'):parser.add_argument('--'+name,type=int,required=True)
    parser.add_argument('--obscura',type=Path,required=True)
    parser.add_argument('--laya-source',type=Path,required=True)
    parser.add_argument('--laya-model',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--skip-laya',action='store_true')
    args=parser.parse_args();result=run(args)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'ok':result['ok'],'checks':result['checks']}));raise SystemExit(0 if result['ok'] else 1)
