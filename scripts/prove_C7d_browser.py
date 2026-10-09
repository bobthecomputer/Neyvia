"""Drive production embedded controls through Neyvia's hidden WebView2 tools."""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
sys.path.insert(0, str(REPO / 'scripts'))


class PrivateDesktopProcess:
    """Start the owned native worker without switching the input desktop."""
    def __init__(self, executable, environment, arguments=()):
        class Startup(ctypes.Structure):
            _fields_ = [('cb',wintypes.DWORD),('lpReserved',wintypes.LPWSTR),('lpDesktop',wintypes.LPWSTR),('lpTitle',wintypes.LPWSTR),
                ('dwX',wintypes.DWORD),('dwY',wintypes.DWORD),('dwXSize',wintypes.DWORD),('dwYSize',wintypes.DWORD),
                ('dwXCountChars',wintypes.DWORD),('dwYCountChars',wintypes.DWORD),('dwFillAttribute',wintypes.DWORD),
                ('dwFlags',wintypes.DWORD),('wShowWindow',wintypes.WORD),('cbReserved2',wintypes.WORD),
                ('lpReserved2',ctypes.c_void_p),('hStdInput',wintypes.HANDLE),('hStdOutput',wintypes.HANDLE),('hStdError',wintypes.HANDLE)]
        class Information(ctypes.Structure):
            _fields_ = [('hProcess',wintypes.HANDLE),('hThread',wintypes.HANDLE),('dwProcessId',wintypes.DWORD),('dwThreadId',wintypes.DWORD)]
        user, kernel = ctypes.WinDLL('user32',use_last_error=True),ctypes.WinDLL('kernel32',use_last_error=True)
        user.CreateDesktopW.argtypes = [wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p]
        user.CreateDesktopW.restype = wintypes.HANDLE
        name = 'NeyviaBureauC7e-' + uuid.uuid4().hex
        self.desktop = user.CreateDesktopW(name,None,None,0,0x00cf,None)
        if not self.desktop: raise ctypes.WinError(ctypes.get_last_error())
        si = Startup();si.cb=ctypes.sizeof(si);si.lpDesktop='winsta0\\'+name;si.dwFlags=1;si.wShowWindow=4
        info = Information()
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(executable), *map(str, arguments)]))
        block = ctypes.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted(environment.items(),key=lambda kv:kv[0].upper()))+'\0\0')
        kernel.CreateProcessW.argtypes = [wintypes.LPCWSTR,wintypes.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,wintypes.BOOL,wintypes.DWORD,ctypes.c_void_p,wintypes.LPCWSTR,ctypes.POINTER(Startup),ctypes.POINTER(Information)]
        kernel.CreateProcessW.restype = wintypes.BOOL
        if not kernel.CreateProcessW(str(executable),command,None,None,False,0x08000404,block,str(REPO),ctypes.byref(si),ctypes.byref(info)):
            user.CloseDesktop(self.desktop)
            raise ctypes.WinError(ctypes.get_last_error())
        kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype=wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        kernel.TerminateJobObject.argtypes=[wintypes.HANDLE,wintypes.UINT]
        kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
        kernel.QueryInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
        kernel.ResumeThread.argtypes=[wintypes.HANDLE]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        self.job=kernel.CreateJobObjectW(None,None)
        if not self.job or not kernel.AssignProcessToJobObject(self.job,info.hProcess):
            kernel.TerminateProcess(info.hProcess,1)
            kernel.CloseHandle(info.hThread);kernel.CloseHandle(info.hProcess)
            if self.job: kernel.CloseHandle(self.job)
            user.CloseDesktop(self.desktop)
            raise ctypes.WinError(ctypes.get_last_error())
        kernel.ResumeThread(info.hThread)
        kernel.CloseHandle(info.hThread)
        self.pid,self.handle,self.kernel,self.user = info.dwProcessId,info.hProcess,kernel,user
        self.name=name
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
        user.CloseDesktop.argtypes=[wintypes.HANDLE]
    def poll(self):
        code=wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle,ctypes.byref(code)): raise ctypes.WinError(ctypes.get_last_error())
        return None if code.value==259 else code.value
    def pids(self):
        buffer=ctypes.create_string_buffer(8+ctypes.sizeof(ctypes.c_size_t)*512)
        if not self.kernel.QueryInformationJobObject(self.job,3,buffer,len(buffer),None):
            raise ctypes.WinError(ctypes.get_last_error())
        count=wintypes.DWORD.from_buffer(buffer,4).value
        return list((ctypes.c_size_t*count).from_buffer(buffer,8))
    def terminate(self): self.kernel.TerminateJobObject(self.job,1)
    def kill(self): self.terminate()
    def wait(self,timeout):
        end=time.monotonic()+timeout
        while self.poll() is None:
            if time.monotonic()>end: raise subprocess.TimeoutExpired('owned private desktop worker',timeout)
            time.sleep(.05)
        return self.poll()
    def close(self):
        self.kernel.CloseHandle(self.handle)
        self.kernel.CloseHandle(self.job)
        self.user.CloseDesktop(self.desktop)


def desktop():
    user = ctypes.windll.user32
    user.GetForegroundWindow.restype = wintypes.HWND
    point = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(point))
    rows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if user.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            rows.append([int(hwnd), pid.value])
        return True
    callback = callback_type(visit)
    user.EnumWindows(callback, 0)
    return {'foreground': int(user.GetForegroundWindow() or 0), 'cursor': [point.x, point.y], 'visible': rows}


def main(argv=None, observed=None, captured=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-port', type=int, required=True)
    parser.add_argument('--vite-port', type=int, required=True)
    parser.add_argument('--native-exe', type=Path, required=True)
    parser.add_argument('--category',choices=('empty','huge','unicode','concurrency','interrupted','permissions','offline','stale'),default='unicode')
    parser.add_argument('--output',type=Path)
    args = parser.parse_args(argv)
    from grant_agent.proof_ports import c7_port_block
    assigned = c7_port_block(int(os.environ.get('NEYVIA_C7_PORT', str(args.backend_port))))
    if args.backend_port == args.vite_port or any(p not in assigned for p in (args.backend_port,args.vite_port)):
        parser.error('Two distinct assigned ports required')
    dom_port = 48745 if assigned[0] == 48741 else assigned[-3]
    if dom_port not in assigned or dom_port in {args.backend_port, args.vite_port}:
        parser.error('Distinct assigned DOM, backend, and Vite ports required')
    dom_origin = f'http://127.0.0.1:{dom_port}'
    native = args.native_exe.resolve()
    native.relative_to(REPO)
    root = REPO / '.agent_control/proofs' / ('c7d-browser-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    output=args.output.resolve() if args.output else REPO/'scripts/evidence/C7d-browser.json'
    output.relative_to(REPO)
    output.parent.mkdir(parents=True,exist_ok=True)
    for key in ('HOME','USERPROFILE','APPDATA','LOCALAPPDATA','CODEX_HOME'):
        p = root / 'home' / key.lower()
        p.mkdir(parents=True)
        os.environ[key] = str(p)
    os.environ.update(NEYVIA_NAS_ROOT=str(root), NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_WATCHDOG_AUTOSTART='0', NEYVIA_COORDINATOR_AUTOSTART='0')
    node = shutil.which('node')
    if not node: raise RuntimeError('Installed Node required; no download fallback')
    for key in list(os.environ):
        if any(word in key.upper() for word in ('API_KEY','TOKEN','SECRET','PASSWORD','CREDENTIAL')):
            os.environ.pop(key,None)
    os.environ['PATH'] = os.pathsep.join([str(Path(node).parent),str(Path(sys.executable).parent),r'C:\Windows\System32',r'C:\Windows'])
    os.environ['NEYVIA_MANAGED_RUNTIME_ROOT']=str(root/'home/runtimes')
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.neyvia_browser import BrowserService
    from grant_agent.proof_contracts import source_digest
    service = BrowserService(root)
    from grant_agent.web_backend import FluxioWebBackend
    from grant_agent.harness_jobs import HarnessJobStore
    harness_root=root/'harness'
    harness_root.mkdir()
    backend=FluxioWebBackend(harness_root,root)
    store=HarnessJobStore(harness_root)
    blocked=store.create({'harnessId':'neyvia-agent','runtime':'neyvia-agent','mode':'direct','message':'Review local blocked receipt 雪🙂','workspacePath':str(harness_root)},job_id='harness-job-browser-blocked')
    store.finish(blocked['id'],result={'status':'blocked','reason':'Local fixture has no selected execution route','detail':'Recoverable provider-free blocker','evidencePath':'scratch-local-receipt'})
    waiting=store.create({'harnessId':'neyvia-agent','runtime':'neyvia-agent','mode':'direct','message':'Saved request waiting for capacity','workspacePath':str(harness_root)},job_id='harness-job-browser-waiting')
    store.update(waiting['id'],waitingReason='execution-capacity',executionQueue={'schema':'neyvia.harness_execution_queue.v1','state':'waiting','maxRunningJobs':1})
    allowed_commands={'get_harness_catalog_command','list_harness_jobs_command','get_harness_job_command','cancel_harness_job_command','get_harness_comparison_command','get_html_site_benchmark_command','get_provider_auth_queue_command','list_harness_batches_command'}
    calls, guard, native_permissions = [], [], []
    capture_contexts=set()
    harness_offline=False
    process_guard=threading.RLock()
    category_checks=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin',f'http://127.0.0.1:{args.vite_port}')
            self.send_header('Access-Control-Allow-Headers','Content-Type')
            self.send_header('Access-Control-Allow-Methods','POST')
            self.end_headers()
        def do_POST(self):
            session_token=None
            logout=False
            try:
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path=='/api/auth/login':
                    session_token=backend.login(value,self)
                    if not session_token: raise ValueError('Owned account authentication refused')
                    result={'ok':True}
                elif self.path=='/api/auth/logout':
                    result={'ok':True}
                    logout=True
                elif self.path=='/api/ui/browser':
                    session=backend.authenticated_session(self)
                    if not session or session.get('username','').casefold()!=backend.username.casefold():
                        raise ValueError('Owned account session required')
                    result=service.request(value['op'],value.get('args',{}),owner=True)
                    if captured and value['op']=='action.get' and result.get('op')=='capture' and result.get('status')=='done':
                        tid=result['tabId']
                        state=service.request('state',{},owner=True)
                        row=next(t for t in state['tabs'] if t['id']==tid)
                        profile=next(p for p in state['profiles'] if p['id']==row['profileId'])
                        if profile['name'].startswith('capture-'):
                            from grant_agent.neyvia_browser import wait_observation
                            def read_capture():
                                return wait_observation(service,service.request('observe',{'tabId':tid},owner=True))
                            captured('native.worker.reuse',args.category,read_capture,runtime_guard)
                            capture_contexts.add(tid)
                            if len(capture_contexts)==2:
                                dom=service.request('dom',{'tabId':tid,'selector':'[data-neyvia-annotation-proof]','attributes':[],'limit':1},owner=True)
                                dom=service.request('wait',{'actionId':dom['actionId'],'timeoutMs':30000},owner=True)['result']
                                if dom['elements'] and dom['elements'][0]['visible']:
                                    captured('native.tools.annotation',args.category,read_capture,runtime_guard)
                elif self.path=='/api/c7d/harness':
                    if harness_offline: raise ValueError('Harness endpoint explicitly offline')
                    command=value['command']
                    if command not in allowed_commands: raise ValueError('Read/owned cleanup only; no execution/auth flow')
                    result=backend.dispatch(command,value.get('payload',{}))
                elif self.path=='/api/ui/browser/runtime':
                    result = service.runtime(value)
                else: raise ValueError('Owned runtime/harness routes only')
                if value.get('op')=='report' and value.get('event',{}).get('type')=='permission':
                    native_permissions.append(dict(value['event']))
                data = json.dumps(result).encode()
                self.send_response(200)
                if session_token: backend._set_session_cookie(self,session_token)
                if logout: backend.logout(self)
            except Exception as exc:
                data = json.dumps({'ok':False,'error':str(exc)}).encode()
                self.send_response(400)
            self.send_header('Content-Type','application/json')
            self.send_header('Access-Control-Allow-Origin',f'http://127.0.0.1:{args.vite_port}')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1',args.backend_port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    before = desktop()
    stop = threading.Event()
    process = None
    def runtime_guard():
        return process is not None and process.poll() is None and not any(any(pid in row['ownedPids'] for _,pid in row['visible']) for row in guard)
    def monitor():
        while not stop.wait(.05):
            with process_guard:
                guard.append({**desktop(),'ownedPids':process.pids() if process else []})
    threading.Thread(target=monitor,daemon=True).start()
    vite = process = None
    html_entry = REPO / 'web' / ('c7d-owned-' + root.name + '.html')
    harness_entry=REPO/'web'/('c7d-harness-'+root.name+'.html')
    sources = ['scripts/prove_C7d_browser.py','scripts/prove_C7d_native_capture.py','scripts/prove_C7d_livecontrol_failure.py','src/grant_agent/neyvia_browser_capture.py','src/grant_agent/native_tool_worker.py','src/grant_agent/native_tools.py','scripts/browser-probe/src/main.rs','src-tauri/src/browser_runtime.rs','src-tauri/src/browser_projection.js','src/grant_agent/neyvia_browser.py','web/src/neyvia/NeyviaEcosystemHost.jsx','web/src/neyvia/neyviaEmbeddedWorkspace.js','src/grant_agent/app_factory.py','src/grant_agent/proofs_a_capabilities.py','src/grant_agent/proofs_a_capability_evolution.py','src/grant_agent/capability_evolution.py','web/src/neyvia/HarnessesSurface.jsx','web/src/neyvia/proofsBViewContracts.js','src/grant_agent/harness_jobs.py','src/grant_agent/web_backend.py','src/grant_agent/neyvia_browser_dom.py','src/grant_agent/proofs_a_livecontrol.py','scripts/verify_authenticated_live_control.py','src/grant_agent/thunder_compute.py']
    bindings = {p:source_digest(REPO/p) for p in sources}
    try:
        fixture = (REPO/'scripts/evidence/C7b-embed-browser-fixture.jsx').read_text(encoding='utf-8')
        fixture = fixture.replace('requestEmbeddedWorkspace', 'openNeyviaEmbeddedWorkspace')
        fixture = fixture.replace("'/src/neyvia/", "'/@fs/"+(REPO/'web/src/neyvia').as_posix()+"/")
        fixture = fixture.replace('C7b','C7d').replace('c7bPermissionResult','c7dPermissionResult').replace('http://127.0.0.1:48747/.c7b-preview.html',f'http://127.0.0.1:{args.vite_port}/@fs/{(root/"preview.html").as_posix()}')
        (root/'journey.jsx').write_text(fixture,encoding='utf-8')
        css=''.join("import '/@fs/"+(REPO/'web/src/neyvia'/name).as_posix()+"';" for name in ('neyviaFonts.css','styles.css','neyviaProductMode.css','neyviaChips.css','neyviaRoleRoute.css','neyviaDividers.css','neyviaSessionWorkspaceRoot.css','neyviaProductFinish.css'))
        (root/'harness.jsx').write_text("import React from 'react';import {createRoot} from 'react-dom/client';"+css+"import {HarnessesSurface} from '/@fs/"+(REPO/'web/src/neyvia/HarnessesSurface.jsx').as_posix()+"';const callBackend=async(command,payload)=>{const r=await fetch('http://127.0.0.1:"+str(args.backend_port)+"/api/c7d/harness',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command,payload})});const value=await r.json();if(!r.ok)throw Error(value.error);return value};createRoot(document.getElementById('root')).render(<HarnessesSurface callBackend={callBackend} workspaceRoot="+json.dumps(str(harness_root))+" onSetSurface={()=>{}}/>);",encoding='utf-8')
        harness_entry.write_text('<!doctype html><meta charset="utf-8"><div id="root"></div><script type="module" src="/@fs/'+(root/'harness.jsx').as_posix()+'"></script>',encoding='utf-8')
        preview_html = '<!doctype html><h1>Owned C7d preview loaded</h1><p>Unicode receipt: 雪🙂é</p>'
        if args.category == 'stale':
            preview_html += '<button onclick="document.querySelector(\'h1\').textContent=\'Owned C7d preview updated\'">Change preview state</button>'
        (root/'preview.html').write_text(preview_html,encoding='utf-8')
        html_entry.write_text('<!doctype html><meta charset="utf-8"><title>C7d embedded host</title><div id="root"></div><script>addEventListener("error",e=>{document.getElementById("root").textContent="Page error: "+e.message})</script><script type="module" src="/@fs/'+(root/'journey.jsx').as_posix()+'"></script>',encoding='utf-8')
        config = root/'vite.config.mjs'
        config.write_text("import config from '"+(REPO/'vite.config.mjs').as_posix()+"';\nexport default env => ({...config(env),cacheDir:'"+(root/'vite-cache').as_posix()+"',optimizeDeps:{entries:"+json.dumps([html_entry.as_posix(),harness_entry.as_posix()])+"}});\n",encoding='utf-8')
        env = {**os.environ,'FLUXIO_WEB_BACKEND_URL':f'http://127.0.0.1:{args.backend_port}'}
        with (root/'vite.log').open('wb') as log:
            vite = subprocess.Popen(['node',str(REPO/'node_modules/vite/bin/vite.js'),'--config',str(config),'--configLoader','runner','--host','127.0.0.1','--port',str(args.vite_port),'--strictPort'],cwd=REPO,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        import urllib.request
        def stop_assets():
            vite.terminate();vite.wait(timeout=10)
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{args.vite_port}/',timeout=.5)
                raise AssertionError('Owned assets endpoint remained online')
            except urllib.error.URLError: pass
            category_checks.append({'category':'offline','assetsEndpointClosed':args.vite_port,'localMutationUsesCachedPage':True})
        def restart_assets():
            nonlocal vite
            with (root/'vite.log').open('ab') as log:
                vite=subprocess.Popen(['node',str(REPO/'node_modules/vite/bin/vite.js'),'--config',str(config),'--configLoader','runner','--host','127.0.0.1','--port',str(args.vite_port),'--strictPort'],cwd=REPO,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(120):
                try:
                    urllib.request.urlopen(f'http://127.0.0.1:{args.vite_port}/{html_entry.name}',timeout=.5).close();return
                except OSError: time.sleep(.1)
            raise AssertionError('Owned asset endpoint failed to restart')
        url = f'http://127.0.0.1:{args.vite_port}/{html_entry.name}'
        for _ in range(120):
            try:
                urllib.request.urlopen(url,timeout=.5).close()
                break
            except OSError:
                if vite.poll() is not None: raise RuntimeError('Vite startup failed')
                time.sleep(.25)
        attached = service.request('runtime.connect',{},owner=True)
        native_env = {**env,'NEYVIA_BROWSER_BASE':f'http://127.0.0.1:{args.backend_port}','NEYVIA_BROWSER_TOKEN':attached['token'],'NEYVIA_BROWSER_PROOF_SCOPE':'C7d'}
        process = PrivateDesktopProcess(native,native_env)
        def request(op, value=None):
            result = service.request(op,value or {},owner=True)
            if result.get('actionId'):
                if op == 'observe':
                    from grant_agent.neyvia_browser import wait_observation
                    result = wait_observation(service,result)
                else:
                    result = service.request('wait',{'actionId':result['actionId'],'timeoutMs':30000},owner=True)
            calls.append({'op':op,'args':value or {},'result':result})
            return result
        opened = request('tab.open',{'url':url,'engine':'webview2'})
        tab = opened['tabId']
        request('layout',{'tabs':[{'tabId':tab,'x':0,'y':0,'width':1200,'height':740,'visible':True}]})
        request('tab.grant',{'tabId':tab,'enabled':True})
        def observe():
            return request('observe',{'tabId':tab})
        def certify(identity,proof_scope='rendered'):
            if observed:
                observed(identity,args.category,observe,runtime_guard,proof_scope)
        def worker_controls(kind):
            nonlocal process,attached
            if kind=='runtime.offline':
                with process_guard:
                    process.terminate();process.wait(timeout=10);process.close();process=None
                    service.request('runtime.disconnect',{},owner=True)
                assert service.view()['runtime']['connected'] is False
            elif kind=='runtime.online':
                with process_guard:
                    attached=service.request('runtime.connect',{},owner=True)
                    native_env['NEYVIA_BROWSER_TOKEN']=attached['token']
                    process=PrivateDesktopProcess(native,native_env)
                request('tab.activate',{'tabId':tab})
                request('layout',{'tabs':[{'tabId':tab,'x':0,'y':0,'width':1200,'height':740,'visible':True}]})
                request('tab.navigate',{'tabId':tab,'url':f'http://127.0.0.1:{args.vite_port}/@fs/{(root/"preview.html").as_posix()}'})
                loaded()
            else:raise ValueError('Unknown owned runtime control')
        def loaded():
            deadline = time.monotonic()+60
            while time.monotonic()<deadline:
                state = service.request('state',{},owner=True)
                if not next(row for row in state['tabs'] if row['id']==tab)['loading']:
                    return
                # A navigation notification can precede page initialization.
                # Ask the actual native engine rather than relying on one callback.
                try:
                    current=observe()
                    if current.get('readyState')=='complete' and current.get('elements'):
                        return
                except Exception:
                    pass
                time.sleep(.2)
            raise AssertionError('Native page-load completion absent')
        loaded()
        def await_text(text):
            for _ in range(80):
                value = observe()
                if text in value['text']: return value
                time.sleep(.1)
            failure = {'expected':text,'observed':value,'calls':calls}
            (root/'failure.json').write_text(json.dumps(failure,indent=2),encoding='utf-8')
            try:
                request('capture',{'tabId':tab})
            except Exception:
                pass
            raise AssertionError('Rendered text absent: '+text+' '+value['url']+' '+value['text'][:800])
        def owned_action(name, action, value=None, role=None):
            from grant_agent.neyvia_browser import BrowserError
            request('tab.grant',{'tabId':tab,'enabled':True})
            # A changing SPA may invalidate an observation before authorization.
            # Three fresh observations bound this recovery; effects or uncertain
            # acknowledgements never enter this loop.
            for attempt in range(3):
                current = observe()
                element = next(e for e in current['elements'] if e['name'].strip()==name and action in e['actions'] and (role is None or e['role']==role))
                try:
                    result = request('action',{'tabId':tab,'element':element['id'],'revision':current['revision'],'action':action,**({'value':value} if value is not None else {})})
                    assert result.get('status')=='done', result
                    return result
                except BrowserError as error:
                    refusal = getattr(error,'no_effect_refusal',None)
                    safe = error.code=='stale_projection' or isinstance(refusal,dict) and refusal.get('code')=='stale_projection' and refusal.get('effectApplied') is False
                    if not safe or attempt==2: raise
                    category_checks.append({'category':args.category,'confirmedNoEffectStaleRefusal':refusal or {'code':error.code,'effectApplied':False},'freshObservationRetry':attempt+1})
        def click(name):
            return owned_action(name,'click',role='button')
        await_text('Attempt without permission')
        click('Attempt without permission')
        denied = await_text('Denied expansion and return preserved missing permission')
        denied_capture = request('capture',{'tabId':tab})
        click('Open approved preview')
        approved = await_text('Owned preview')
        approved_capture = request('capture',{'tabId':tab})
        observations = {'denied':denied,'approved':approved}
        from grant_agent.neyvia_browser_dom import NeyviaDOMPage
        from grant_agent.proofs_a_livecontrol import self_check as check_live_dom
        from grant_agent.neyvia_browser import BrowserError
        if args.category=='permissions':
            current=observe()
            button=next(e for e in current['elements'] if e['role']=='button')
            request('tab.grant',{'tabId':tab,'enabled':False})
            try:
                service.request('action',{'tabId':tab,'element':button['id'],'revision':current['revision'],'action':'click'},owner=True)
                raise AssertionError('Live-control action bypassed the actual owner grant')
            except BrowserError as error:assert error.code=='tab_not_granted',error.code
            assert observe()['revision']==current['revision']
            request('tab.grant',{'tabId':tab,'enabled':True})
            category_checks.append({'category':'permissions','liveControlOwnerRefusal':'tab_not_granted','unchangedNativeRevision':current['revision']})
        failed_target=request('tab.open',{'url':f'http://127.0.0.1:{args.vite_port}/@fs/{(root/"preview.html").as_posix()}','engine':'webview2'})['tabId']
        request('layout',{'tabs':[{'tabId':tab,'x':0,'y':0,'width':1200,'height':740,'visible':True},{'tabId':failed_target,'x':0,'y':0,'width':800,'height':600,'visible':True}]})
        request('observe',{'tabId':failed_target})
        request('tab.close',{'tabId':failed_target})
        assert failed_target not in {row['id'] for row in service.view()['tabs']}
        category_checks.append({'category':args.category,'actuallyOpenedAndClosedFailureTab':failed_target,'noImplicitReopen':True})
        dom_page=NeyviaDOMPage(lambda op,args:service.request(op,args,owner=True),tab,allowed_origin=dom_origin)
        live_dom=check_live_dom(root/'live-dom',page=dom_page,dom_port=dom_port,category=args.category)
        live_dom['observations']=dom_page.observations
        if args.category=='offline':
            try:
                urllib.request.urlopen(dom_origin+'/owned-2',timeout=.5)
                raise AssertionError('Owned DOM source did not go offline')
            except urllib.error.URLError:pass
            import importlib.util
            classifier_spec=importlib.util.spec_from_file_location('owned_live_dom_classifier',REPO/'scripts/verify_authenticated_live_control.py')
            classifier=importlib.util.module_from_spec(classifier_spec);classifier_spec.loader.exec_module(classifier)
            offline_classified=[*classifier._measure_provider_admission(dom_page,secrets=()),*classifier._measure_hermes_runtime_proof(dom_page,secrets=())]
            assert offline_classified==live_dom['classifications'][-1]['checks'],'Cached native classification changed after source shutdown'
            live_dom['offlineCachedClassification']=offline_classified
        for identity in ('livecontrol.provider-dom','livecontrol.hermes-dom','livecontrol.cli-browser-option'):certify(identity)
        from prove_C7d_livecontrol_failure import exercise_failure_truth
        failure_truth=exercise_failure_truth(backend_url=f'http://127.0.0.1:{args.backend_port}',username=backend.username,password=backend.generated_admin_password,failed_tab_id=failed_target,expected_origin=dom_origin,category=args.category)
        certify('livecontrol.browser-failure-truth','local_semantic')
        from prove_C7d_native_capture import exercise_worker
        from grant_agent.web_backend import SESSION_COOKIE_NAME
        worker_token=backend.login({'username':backend.username,'password':backend.generated_admin_password})
        try:
            worker_run=exercise_worker(root=root/'native-capture',port=args.backend_port,session_cookie=SESSION_COOKIE_NAME+'='+worker_token,url=f'http://127.0.0.1:{args.vite_port}/@fs/{(root/"preview.html").as_posix()}',category=args.category,controls=worker_controls)
        finally:
            backend.web_auth_sessions.revoke(worker_token)
        assert len(service.request('state',{},owner=True)['tabs'])==1,'Worker leaked owned native page contexts'
        request('layout',{'tabs':[{'tabId':tab,'x':0,'y':0,'width':1200,'height':740,'visible':True}]})
        from grant_agent.app_factory import AppFactory
        from grant_agent.proofs_a_capability_evolution import self_check as build_guided
        (root/'factory').mkdir()
        notes_job = AppFactory(root/'factory').create(name='Owned Notes',brief='Keep local notes and export portable JSON records',target='neyvia',template='notes',theme='paper')
        build_guided(root)
        factory_runs = {}
        def navigate(directory):
            request('tab.navigate',{'tabId':tab,'url':f'http://127.0.0.1:{args.vite_port}/@fs/{directory.as_posix()}/index.html'})
            time.sleep(.6)
            request('tab.grant',{'tabId':tab,'enabled':True})
        def element_action(name, action, value=None):
            return owned_action(name,action,value)
        def perturb(name):
            from grant_agent.neyvia_browser import BrowserError
            current=observe()
            element=next(e for e in current['elements'] if e['name'].strip()==name and 'fill' in e['actions'])
            payload={'tabId':tab,'element':element['id'],'revision':current['revision'],'action':'fill','value':'owned competing value'}
            if args.category=='huge':
                try:
                    service.request('action',{**payload,'value':'x'*20001},owner=True)
                    raise AssertionError('Browser tool accepted oversized value')
                except BrowserError as error: assert error.code=='invalid_value',error.code
                assert observe()['revision']==current['revision'],'Oversized admission changed rendered state'
            elif args.category=='permissions':
                request('tab.grant',{'tabId':tab,'enabled':False})
                try:
                    service.request('action',payload,owner=True)
                    raise AssertionError('Ungrant action mutated page')
                except BrowserError as error: assert error.code=='tab_not_granted',error.code
                assert observe()['revision']==current['revision'],'Permission refusal changed page'
                request('tab.grant',{'tabId':tab,'enabled':True})
            elif args.category in {'concurrency','stale'}:
                request('tab.grant',{'tabId':tab,'enabled':True})
                first=service.request('action',payload,owner=True)
                if args.category=='concurrency':
                    second=service.request('action',{**payload,'value':'losing competing value'},owner=True)
                    request('wait',{'actionId':first['actionId'],'timeoutMs':30000})
                    try:
                        request('wait',{'actionId':second['actionId'],'timeoutMs':30000})
                        raise AssertionError('Competing old revision succeeded twice')
                    except BrowserError as error: assert 'stale_projection' in str(error),str(error)
                else:
                    request('wait',{'actionId':first['actionId'],'timeoutMs':30000})
                    observe()
                    try:
                        service.request('action',{**payload,'value':'stale value'},owner=True)
                        raise AssertionError('Old observation was reused')
                    except BrowserError as error: assert error.code=='stale_projection',error.code
                actual=observe()
                assert next(e for e in actual['elements'] if e['name'].strip()==name)['value']=='owned competing value',actual
                element_action(name,'fill','')
            category_checks.append({'category':args.category,'field':name,'nativeRevision':observe()['revision']})
        def download(button):
            before_downloads = {row['id'] for row in request('downloads',{})['downloads']}
            click(button)
            for _ in range(200):
                downloads = request('downloads',{})['downloads']
                new = [row for row in downloads if row['id'] not in before_downloads and row['status']=='completed']
                if new:
                    path = Path(new[-1]['path'])
                    return json.loads(path.read_text(encoding='utf-8')),new[-1]
                time.sleep(.05)
            raise AssertionError('Native download did not complete: '+button)
        navigate(Path(notes_job['projectRoot'])/'dist')
        await_text('No notes yet')
        from grant_agent.thunder_compute import execute_neyvia_proposal
        request('tab.grant',{'tabId':tab,'enabled':True})
        current=observe()
        note_field=next(e for e in current['elements'] if e['name']=='Note')
        proposal={'action':{'revision':current['revision'],'element':note_field['id'],'action':'fill','value':'native typed proposal'}}
        proposal_run=execute_neyvia_proposal(service,tab,proposal)
        assert proposal_run['status']=='done' and proposal_run['verdict']=='verified' and proposal_run['nativeActionId'],proposal_run
        try:
            execute_neyvia_proposal(service,tab,proposal)
            raise AssertionError('Stale Neyvia proposal reused')
        except ValueError as error: assert getattr(error,'code','')=='stale_projection',str(error)
        current=observe()
        proposal['action'].update(revision=current['revision'],value='unverified expectation')
        unverified=execute_neyvia_proposal(service,tab,proposal,expect='missing native expectation marker')
        assert unverified['verdict']=='unverified' and unverified['expectationMet'] is False,unverified
        current=observe()
        proposal['action']['revision']=current['revision']
        request('tab.grant',{'tabId':tab,'enabled':False})
        try:
            execute_neyvia_proposal(service,tab,proposal)
            raise AssertionError('Ungrant native proposal succeeded')
        except ValueError as error: assert getattr(error,'code','')=='tab_not_granted',str(error)
        request('tab.grant',{'tabId':tab,'enabled':True})
        element_action('Note','fill','')
        if args.category=='offline': stop_assets()
        perturb('Note')
        certify('control.neyvia-live-action')
        if args.category=='empty':
            click('Save note')
            await_text('No notes yet')
        note_text='Field observation alpha '+('x'*18000 if args.category=='huge' else '雪🙂é')
        for text in [note_text,'Portable observation beta']:
            element_action('Note','fill',text)
            click('Save note')
            await_text(text)
        element_action('Search saved notes','fill','alpha')
        filtered = observe()
        assert 'Field observation alpha' in filtered['text'] and 'Portable observation beta' not in filtered['text'],filtered
        primary=next(e['name'].strip() for e in observe()['elements'] if e['name'].startswith('Mark Field observation alpha'))
        element_action(primary,'click')
        if args.category=='interrupted':
            with process_guard:
                process.terminate();process.wait(timeout=10);process.close();process=None
                attached=service.request('runtime.connect',{},owner=True)
                native_env['NEYVIA_BROWSER_TOKEN']=attached['token']
                process=PrivateDesktopProcess(native,native_env)
            request('tab.activate',{'tabId':tab})
            request('layout',{'tabs':[{'tabId':tab,'x':0,'y':0,'width':1200,'height':740,'visible':True}]})
            loaded()
            category_checks.append({'category':'interrupted','workerTerminated':True,'sameProfileReopened':True,'noImplicitReplay':True})
        if args.category=='offline': restart_assets()
        request('tab.reload',{'tabId':tab})
        time.sleep(.6)
        persisted = await_text('Portable observation beta')
        bundle,download_row = download('Export JSON')
        assert bundle['schema']=='neyvia.local-app-export/v1' and len(bundle['items'])==2 and sum(item['complete'] for item in bundle['items'])==1 and len({item['id'] for item in bundle['items']})==2 and any(item['text']==note_text for item in bundle['items']),bundle
        factory_runs['notes']={'observations':[filtered,persisted],'export':bundle,'download':download_row,'capture':request('capture',{'tabId':tab})}
        certify('a.factory-notes-ui')
        navigate(root/'evolution/apps/proof-renewed-workbench/dist')
        await_text('Start guided run')
        if args.category=='offline': stop_assets()
        perturb('What should this run accomplish?')
        if args.category=='empty':
            click('Start guided run')
            assert not [e for e in observe()['elements'] if e['name']=='Seal run receipt'],'Empty goal started a run'
        element_action('What should this run accomplish?','fill','PRIVATE BROWSER GOAL: verify local workflow 雪🙂é')
        click('Start guided run')
        click('Seal run receipt')
        incomplete = await_text('steps remain')
        checkboxes = [e['name'] for e in observe()['elements'] if e['checked'] is False and 'click' in e['actions']]
        assert len(checkboxes)==3,checkboxes
        for name in checkboxes: element_action(name,'click')
        click('Seal run receipt')
        missing_proof = await_text('Add a proof note')
        element_action('Proof note','fill','PRIVATE BROWSER PROOF: local controls pass')
        click('Seal run receipt')
        await_text('1 saved run')
        if args.category=='offline': restart_assets()
        request('tab.reload',{'tabId':tab})
        time.sleep(.6)
        persisted_run = await_text('1 saved run')
        guided_bundle,guided_download = download('Export proof bundle')
        run = guided_bundle['runs'][0]
        canonical = json.dumps({key:value for key,value in run.items() if key!='receiptDigest'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        assert guided_bundle['schema']=='neyvia.capability-run-bundle/v2' and run['receiptDigest']==hashlib.sha256(canonical).hexdigest() and all(step['complete'] for step in run['steps']) and len(run['steps'])==3 and not guided_bundle['candidateActivated'] and not guided_bundle['transcriptsIncluded'],guided_bundle
        from grant_agent.neyvia_browser import BrowserError
        try:
            service.request('tab.update',{'tabId':tab,'allowMultipleDownloads':True})
            raise AssertionError('Non-owner acquired the native download permission')
        except BrowserError as error:
            assert error.code=='owner_required',error.code
        request('tab.update',{'tabId':tab,'allowMultipleDownloads':True})
        returned,return_download = download('Return typed outcomes to Neyvia')
        assert returned['runs'][0]['receiptDigest']==run['receiptDigest']
        factory_runs['guided']={'observations':[incomplete,missing_proof,persisted_run],'export':guided_bundle,'download':guided_download,'returnedDownload':return_download,'capture':request('capture',{'tabId':tab})}
        certify('a.factory-guided-ui')
        navigate(Path(notes_job['projectRoot'])/'dist')
        await_text('Portable observation beta')
        assert not service.tab({'tabId':tab}).get('allowMultipleDownloads'), 'Navigation retained download grant'
        download('Export JSON')
        old_ids={row['id'] for row in request('downloads',{})['downloads']}
        permission_index=len(native_permissions)
        click('Export JSON')
        for _ in range(200):
            refused=[row for row in request('downloads',{})['downloads'] if row['id'] not in old_ids and row['status']=='cancelled']
            if refused:
                assert not Path(refused[0]['path']).exists(), 'Refused download created bytes'
                factory_runs['downloadGrant']={'ownerOnlyRefusal':True,'navigationRevoked':True,'nativeRefusal':refused[0]}
                break
            denied_permission=[event for event in native_permissions[permission_index:] if event.get('tabId')==tab and event.get('allowed') is False]
            if denied_permission:
                assert {row['id'] for row in request('downloads',{})['downloads']}==old_ids, 'Permission refusal produced a download'
                factory_runs['downloadGrant']={'ownerOnlyRefusal':True,'navigationRevoked':True,'nativePermissionRefusal':denied_permission[0]}
                break
            time.sleep(.05)
        else: raise AssertionError('Revoked native multiple-download grant did not refuse')
        old_navigation=service.tab({'tabId':tab})['nativeNavigationId']
        request('tab.reload',{'tabId':tab})
        loaded()
        await_text('Portable observation beta')
        stale=service.queue('download_grant',service.tab({'tabId':tab}),enabled=True,navigationId=old_navigation)
        try:
            request('wait',{'actionId':stale['actionId'],'timeoutMs':30000})
            raise AssertionError('Old navigation download grant succeeded')
        except BrowserError as error:
            assert error.code=='action_failed' and 'Stale native navigation' in str(error),str(error)
        stale_result=service.request('action.get',{'actionId':stale['actionId']},owner=True)
        factory_runs['downloadGrant']['staleNavigationRefusal']=stale_result
        request('tab.navigate',{'tabId':tab,'url':f'http://127.0.0.1:{args.vite_port}/{harness_entry.name}'})
        loaded()
        await_text('waiting for capacity')
        waiting_view=await_text('Saved request waiting for capacity')
        # Selecting the durable waiting job must expose the real capacity explanation.
        candidates=[e for e in observe()['elements'] if e['name']=='neyvia-agent: waiting for capacity' and 'click' in e['actions']]
        assert candidates,candidates
        element_action(candidates[0]['name'].strip(),'click')
        capacity=await_text('no execution slot is claimed yet')
        if args.category=='offline':
            harness_offline=True
            click('Refresh queue')
            await_text('Harness endpoint explicitly offline')
        certify('proofs-b.browser.capacity-label')
        certify('proofs-b.browser.capacity-explanation')
        candidates=[e for e in observe()['elements'] if e['name']=='neyvia-agent: needs attention' and 'click' in e['actions']]
        assert candidates,candidates
        element_action(candidates[0]['name'].strip(),'click')
        blocked_view=await_text('scratch-local-receipt')
        certify('proofs-b.browser.blocked-receipt')
        harness_offline=False
        original=store.job_path(blocked['id']).read_bytes()
        click('Prepare retry')
        assert store.job_path(blocked['id']).read_bytes()==original,'Retry preparation modified blocked receipt'
        retry_view=await_text('scratch-local-receipt')
        click('Cancel & clean up')
        cleaned=await_text('scratch-local-receipt')
        saved=store.load(blocked['id'],reconcile=False)
        assert saved['cancelOutcome']=='blocked-cleanup' and saved['result']['evidencePath']=='scratch-local-receipt',saved
        harness_run={'waiting':waiting_view,'capacity':capacity,'blocked':blocked_view,'retry':retry_view,'cleanup':cleaned,'saved':saved,'capture':request('capture',{'tabId':tab}),'boundary':'Production saved-state UI and owned cleanup; no provider execution or worker capacity scheduling'}
        captures = []
        for label, value in [('denied',denied_capture),('approved',approved_capture)]:
            p = Path(value['result']['path'])
            target = output.with_suffix('')/(label+'.png')
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,target)
            captures.append({'path':target.relative_to(REPO).as_posix(),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size})
        request('tab.close',{'tabId':tab})
        rows = [row for row in guard if any(pid in row['ownedPids'] for _,pid in row['visible'])]
        if rows: raise AssertionError('Owned browser created a visible desktop window')
        current = bindings == {p:source_digest(REPO/p) for p in bindings}
        if not current: raise AssertionError('Browser source changed during real run')
        report = {'schema':'neyvia.c7d-browser.v1','ok':True,'category':args.category,'categoryChecks':category_checks,'engine':'Neyvia Search/WebView2 production browser runtime','headlessHost':True,
            'root':str(root),'explicitPorts':[args.backend_port,args.vite_port],'calls':calls,'observations':observations,'captures':captures,
            'sourceBindings':bindings,'sourceStable':True,'nativeExeSha256':hashlib.sha256(native.read_bytes()).hexdigest(),'factoryRuns':factory_runs,'harnessRun':harness_run,'liveDom':live_dom,'liveControlFailureTruth':failure_truth,'nativeWorker':worker_run,'nativeProposalRuns':[proposal_run,unverified],'nativePermissionEvents':native_permissions,
            'desktopGuard':{'privateDesktop':process.name,'inputDesktopNeverSwitched':True,'samples':len(guard),'ownedVisibleWindows':0,'ownedTreePids':sorted({pid for row in guard for pid in row['ownedPids']}),'foregroundBefore':before['foreground'],'foregroundAfter':desktop()['foreground'],'cursorBefore':before['cursor'],'cursorAfter':desktop()['cursor']},
            'boundary':'Real rendered embedded host, generated apps and durable Harness UI through production browser tools; no physical device/provider execution proof'}
        output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'ok':True,'captures':captures,'guardSamples':len(guard)}))
        return report
    except Exception as exc:
        if process and process.poll() is None and 'tab' in locals():
            try:
                request('capture',{'tabId':tab})
                queued = service.request('observe',{'tabId':tab},owner=True)
                calls.append({'op':'failed-journey-debug-observe','result':service.request('wait',{'actionId':queued['actionId'],'timeoutMs':5000},owner=True)})
            except Exception as debug_exc:
                calls.append({'op':'failed-journey-debug','error':str(debug_exc)})
        (root/'failure.json').write_text(json.dumps({'error':str(exc),'nativeExit':process.poll() if process else None,'calls':calls,'state':service.request('state',{},owner=True),'actions':service.actions},indent=2),encoding='utf-8')
        raise
    finally:
        stop.set()
        for child in (process,vite):
            if child and child.poll() is None:
                child.terminate()
                try: child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill();child.wait(timeout=5)
        if process:
            process.close()
        server.shutdown()
        server.server_close()
        html_entry.unlink(missing_ok=True)
        harness_entry.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
