"""Generated apps with a shared state bridge and observer-backed CL 1.1 goals.

No installer, provider substitution or source-only completion path. Development
may explicitly select a read-only CL source checkout before that track merges.
"""
from __future__ import annotations

import hashlib
import html
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from .durability import atomic_write_json
from .subprocess_utils import hidden_windows_subprocess_kwargs

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = REPO / 'config/app_sdk'
DETAILS_MANIFEST = REPO / 'web/src/neyvia/next/details/details.manifest.json'
KINDS = {'web', 'pwa', 'expo', 'desktop'}
_LOCK = threading.RLock()


@contextmanager
def app_lock(project):
    """Bounded cross-process CAS lock, automatically released on host death."""
    directory=Path(project)/'.neyvia';directory.mkdir(parents=True,exist_ok=True)
    with _LOCK, (directory/'state.lock').open('a+b') as handle:
        handle.seek(0,2)
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            deadline=time.monotonic()+5
            while True:
                try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:
                    if time.monotonic()>deadline:raise TimeoutError('App state is busy; observe and retry')
                    time.sleep(.02)
            try:yield
            finally:handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def confined(root, raw):
    base = Path(root).resolve()
    path = (base / raw).resolve()
    path.relative_to(base)
    if any(part in {'.git', 'node_modules'} for part in path.relative_to(base).parts):
        raise ValueError('App projects cannot reside in Git metadata or dependencies')
    return path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def descriptor(project):
    value = read(project / 'neyvia.app.json')
    if value.get('standard') != 'CL-1.1' or value.get('kind') not in KINDS:
        raise ValueError('Not a CL 1.1 SDK project')
    return value


def source_hashes(project):
    paths = [project / name for name in ('neyvia.app.json','manual.cl','host-contract.json','server.py','package.json','app.json')]
    paths += sorted((project / 'www').rglob('*'))
    paths += [project / name for name in ('App.js', 'native.cs') if (project / name).exists()]
    paths += sorted((project / 'neyvia_sdk').rglob('*.py'))
    return {str(path.relative_to(project)).replace('\\','/'): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


def install_details(project):
    """Ship A2's original, framework-free kit with its declared files and credit."""
    manifest = read(DETAILS_MANIFEST)
    kit = manifest['kit']
    assets = []
    for entry in kit['copy']:
        source = confined(REPO, entry['from'])
        target = confined(project / 'www', entry['to'])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        assets.append(entry['to'])
    credits = project / 'www/details/CREDITS.md'
    shutil.copy2(REPO / 'docs/design/details-library.md', credits)
    assets.append('details/CREDITS.md')
    atomic_write_json(project / 'www/details/manifest.json', manifest)
    assets.append('details/manifest.json')
    credit = html.escape(kit['credit'])
    credit = credit.replace('https://rareui.com', '<a href="https://rareui.com" target="_blank" rel="noopener noreferrer">https://rareui.com</a>')
    credit = credit.replace('docs/design/details-library.md', '<a href="./details/CREDITS.md">details credits</a>')
    return {'version':manifest['version'], 'assets':assets, 'credit':kit['credit']}, credit


def new_app(root, payload):
    kind = payload.get('kind')
    if kind not in KINDS:
        raise ValueError('kind is web, pwa, expo or desktop')
    name = str(payload.get('name') or '').strip()
    if not name or len(name) > 100 or any(ord(char) < 32 for char in name):
        raise ValueError('Provide an app name of 1..100 characters')
    project = confined(root, payload['path'])
    if project.exists():
        raise FileExistsError('Creation requires a new path; existing work is preserved')
    project.parent.mkdir(parents=True, exist_ok=True)
    staging = project.with_name(project.name + '.creating-' + uuid.uuid4().hex)
    staging.mkdir()
    try:
        shutil.copytree(TEMPLATES / 'web', staging / 'www')
        for path in (staging / 'www').iterdir():
            path.write_text(path.read_text(encoding='utf-8').replace('__NAME__', html.escape(name)).replace('__BUILD__',uuid.uuid4().hex),encoding='utf-8')
        details, credit = install_details(staging)
        bundle_runtime(staging)
        index = staging / 'www/index.html'
        index.write_text(index.read_text(encoding='utf-8').replace('__DETAILS_CREDIT__', credit), encoding='utf-8')
        worker = staging / 'www/sw.js'
        worker.write_text(worker.read_text(encoding='utf-8').replace('__DETAILS_ASSETS__', ','.join(json.dumps('./'+asset) for asset in details['assets'])), encoding='utf-8')
        bundle = 'com.neyvia.' + re.sub('[^a-z0-9]','',project.name.lower())[:40]
        atomic_write_json(staging / 'www/manifest.webmanifest', {'name':name,'short_name':name[:20],'start_url':'./','display':'standalone','background_color':'#153530','theme_color':'#153530'})
        package = {'name':re.sub('[^a-z0-9-]','-',project.name.lower()),'private':True,'type':'module','scripts':{'start':'python server.py','build':'python server.py --build'}}
        if kind == 'expo':
            (staging / 'App.js').write_text((TEMPLATES/'expo/App.js').read_text().replace('__NAME__',name.replace('"','')),encoding='utf-8')
            package.update(main='node_modules/expo/AppEntry.js',dependencies={'expo':'~55.0.0','react':'19.2.0','react-dom':'19.2.0','react-native':'0.83.2','react-native-web':'^0.21.0','@react-native-async-storage/async-storage':'2.2.0'})
        if kind == 'desktop':
            (staging / 'native.cs').write_text((TEMPLATES/'desktop/native.cs').read_text().replace('__NAME__',name.replace('\\','\\\\').replace('"','\\"')),encoding='utf-8')
        atomic_write_json(staging / 'package.json',package)
        atomic_write_json(staging / 'app.json',{'expo':{'name':name,'slug':package['name'],'ios':{'bundleIdentifier':bundle},'android':{'package':bundle},'web':{'output':'static'}}})
        instance=uuid.uuid4().hex
        atomic_write_json(staging / 'neyvia.app.json',{'sdk':1,'requires':{'neyviaApi':'>=1.0 <2','sdk':'>=1 <2'},'standard':'CL-1.1','instance':instance,'kind':kind,'name':name,'webRoot':'www','manual':'manual.cl','contract':'host-contract.json','stateApi':'./__neyvia/state','commitApi':'./__neyvia/commit','details':details})
        atomic_write_json(staging / 'www/identity.json',{'instance':instance,'standard':'CL-1.1'})
        native = kind == 'desktop'
        text_observer = 'win.text()' if native else 'web.text()'
        goals = 'app.state().count == 1 and "Count: 1" in ' + text_observer
        contract = {'version':'1.1','initial':{'count':0,'revision':0},'invariants':['count is a nonnegative integer'],'goal':goals,'journey':[
            {'via':'api','action':'reset','expect':0}, {'via':'ui','action':'increment','expect':1},
            {'via':'ui','action':'increment','expect':2}, {'via':'api','action':'decrement','expect':1},
            *([] if native else [{'via':'reload','expect':1}])],
            'actions':{'increment':{'pre':'app.state().count >= 0','post':'app.state().count == before.count + 1'},'decrement':{'post':'app.state().count >= 0'},'reset':{'post':'app.state().count == 0'}},
            'impact':{'resources':['shared-state','rendered-controls','persistent-storage'],'undo':'reset'},
            'procedure':{'name':'app.counter','steps':'journey','goal':goals}}
        atomic_write_json(staging/'host-contract.json',contract)
        (staging/'manual.cl').write_text('L app v1 -- '+name+'\nP app.counter() G: '+goals+'\nG complete: '+goals+'\nA app.state() -> state[count revision]\nA app.act(name: "increment"|"decrement"|"reset", arguments?: dict) ~\nA '+text_observer+' -> text\nX stale-write -> observe fresh state; retry with new host stamp\nX failed-goal -> inspect rendered state and reducer; repair before done\nF native-device execution requires installed runtime and real device observation\n',encoding='utf-8')
        # Standalone server uses this SDK's installed source; portable web assets
        # and native exe remain ordinary exportable app artifacts.
        # Bundle the exact stdlib host runtime: generated apps can move without
        # depending on this checkout's absolute path.
        runtime=staging/'neyvia_sdk/grant_agent';runtime.mkdir(parents=True)
        (runtime/'__init__.py').write_text('',encoding='utf-8')
        for module in ('app_sdk.py','app_sdk_server.py','durability.py','subprocess_utils.py'):
            shutil.copy2(Path(__file__).parent/module,runtime/module)
        (staging/'server.py').write_text('from pathlib import Path\nimport sys\nroot=Path(__file__).resolve().parent\nsys.path.insert(0,str(root/"neyvia_sdk"))\nfrom grant_agent.app_sdk_server import main\nmain(root)\n',encoding='utf-8')
        (staging/'README.md').write_text('# '+name+'\nMade with Neyvia.\n\nRun: `python server.py --port <explicit-port>`. Verify via `neyvia app verify --project <path> --url <running-url>`.\nThe CL manual is the model view; host-contract.json carries executable journeys and goals.\nThe web/PWA includes A2 details: rolling count, reset confirmation, copy feedback, and press feedback. All kit functions are available in www/details/details.js; sources and credit are bundled in www/details/CREDITS.md.\nExpo native export requires installed Expo dependencies. Desktop builds offline with the installed Windows compiler.\n',encoding='utf-8')
        os.replace(staging, project)
    except Exception:
        # Preserve failed generation for recovery; never delete user data.
        raise
    return {'ok':True,'status':'created','project':str(project),'kind':kind,'manual':str(project/'manual.cl'),'sourceHashes':source_hashes(project)}


def bundle_runtime(project):
    """Build the actual editable modules into a classic embedded entrypoint."""
    inputs = {p.relative_to(project).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (Path(project) / 'www').rglob('*.js') if p.name not in {'app.bundle.js', 'sw.js'}}
    manifest = Path(project) / 'www/app.bundle.source.json'
    bundle = Path(project) / 'www/app.bundle.js'
    if manifest.is_file() and bundle.is_file() and read(manifest) == {
            'sources': inputs, 'bundleSha256': hashlib.sha256(bundle.read_bytes()).hexdigest()}:
        return
    node = shutil.which('node')
    if not node:
        raise RuntimeError('SDK generation requires the installed Node runtime')
    result = subprocess.run([node, str(REPO / 'scripts/build_app_sdk_runtime.mjs'), str(project)],
        cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=30,
        **hidden_windows_subprocess_kwargs())
    if result.returncode:
        raise RuntimeError('SDK runtime bundle failed: ' + result.stderr[-2000:])
    atomic_write_json(manifest, {'sources': inputs, 'bundleSha256': hashlib.sha256(bundle.read_bytes()).hexdigest()})


def state_api(project):
    project = Path(project)
    with app_lock(project):
        descriptor(project)
        path = project / '.neyvia/state-ledger.json'
        return read(path)['state'] if path.exists() else read(project/'host-contract.json')['initial']


def commit_api(project, payload):
    project = Path(project)
    with app_lock(project):
        descriptor(project)
        ledger_path = project / '.neyvia/state-ledger.json'
        ledger = read(ledger_path) if ledger_path.exists() else {'state':read(project/'host-contract.json')['initial'],'identities':{}}
        before = ledger['state']
        identities = ledger['identities']
        identity = payload.get('actionId')
        if identity and identity in identities:
            prior = identities[identity]
            if prior['fingerprint'] != payload.get('fingerprint'):
                raise ValueError('Action identity conflict')
            return prior['receipt']
        if type(payload.get('expectedRevision')) is not int or payload['expectedRevision'] != before['revision']:
            raise ValueError('State changed; observe again')
        candidate = payload.get('state')
        if not isinstance(candidate,dict) or type(candidate.get('count')) is not int or candidate['count'] < 0:
            raise ValueError('Count invariant failed')
        after = {**candidate,'revision':before['revision']+1}
        receipt = {'ok':True,'before':before,'after':after,'checks':['nonnegative','CAS','persisted'],'impact':['state','render','storage']}
        if identity:
            identities[identity] = {'fingerprint':payload.get('fingerprint'),'receipt':receipt}
        atomic_write_json(ledger_path,{'state':after,'identities':dict(list(identities.items())[-256:])})
        return receipt


def describe_app(root,payload):
    project = confined(root,payload['project'])
    receipts={name:read(project/'.neyvia'/('latest-'+name+'.json')) for name in ('build','verification') if (project/'.neyvia'/('latest-'+name+'.json')).exists()}
    return {'ok':True,'project':str(project),'app':descriptor(project),'manual':(project/'manual.cl').read_text(encoding='utf-8'),'contract':read(project/'host-contract.json'),'sourceHashes':source_hashes(project),'receipts':receipts}


def state_app(root,payload):
    project=confined(root,payload['project'])
    if descriptor(project)['kind']=='desktop' and (project/'.neyvia/latest-build.json').exists():
        built=read(project/'.neyvia/latest-build.json')
        path=Path(built['artifact']).parent/'native-state.json'
        if path.exists():return {'ok':True,'state':read(path),'source':'native-build-store'}
    return {'ok':True,'state':state_api(project),'source':'web-shared-store'}


def local_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1','localhost'} or not parsed.port or parsed.username or parsed.password:
        raise ValueError('Use an explicit loopback HTTP port for the owned running app')
    return value


def cl_modules(source=None):
    if source:
        source = Path(source).resolve()
        trusted=Path(os.environ.get('NEYVIA_CL_SOURCE',str(REPO.parent/'nx-integrate-cl'))).resolve()
        if source!=trusted:
            raise PermissionError('Development CL source must be the owner-selected integration checkout')
        import grant_agent
        directory = source / 'src/grant_agent'
        if not (directory/'cl/goals.py').is_file():
            raise ValueError('Explicit CL source lacks the 1.1 runtime')
        if str(directory) not in grant_agent.__path__:
            grant_agent.__path__.append(str(directory))
    try:
        goals = importlib.import_module('grant_agent.cl.goals')
        parser = importlib.import_module('grant_agent.cl.parser')
    except ModuleNotFoundError as exc:
        raise RuntimeError('CL 1.1 integration is required; development may explicitly pass clSource') from exc
    directory = Path(goals.__file__).parent
    if source and directory.resolve()!=(source/'src/grant_agent/cl').resolve():
        raise RuntimeError('Requested CL source differs from the loaded runtime; use a fresh process')
    return goals,parser,{'source':str(directory),'hashes':{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.glob('*.py')}}


class AppBrowser:
    """Use T18's owned DOM/action session; only the named SDK bridge is invoked."""
    def __init__(self,url,root=None):
        from .perception_browser import BrowserSessions
        class SDKSession(BrowserSessions):
            def _sdk(self,sid,name,args):
                page=self.sessions[sid]['page']
                page.wait_for_function('!!window.neyviaApp',timeout=10000)
                if name == 'state': return page.evaluate('() => window.neyviaApp.state()')
                if name == 'identity': return page.evaluate('() => window.neyviaApp.describe().instance')
                if name == 'act': return page.evaluate('p => window.neyviaApp.act(p.name,p.arguments||{},p.options||{})',args)
                if name == 'reload': page.reload(wait_until='domcontentloaded');page.wait_for_function('!!window.neyviaApp');return self._observe(sid)
                if name == 'screenshot': page.screenshot(path=args['path'],full_page=True);return {'path':args['path']}
                if name == 'wait': page.wait_for_function('v => window.neyviaApp.state().count === v',arg=args['count'],timeout=2500);return self._observe(sid)
                raise ValueError('Unknown SDK bridge operation')
        headless=None
        if root is not None:
            from .neyvia_browser import service_for
            headless=service_for(root).headless
        self.browser=SDKSession(headless=headless)
        try:self.sid=self.browser.run('open',local_url(url))['browserId']
        except Exception:self.browser.close();raise

    def observe(self): return self.browser.run('observe',self.sid)
    def sdk(self,name,args=None): return self.browser.run('sdk',self.sid,name,args or {})
    def click(self,name):
        value=self.observe()
        row=next((row for row in value['elements'] if row['role']=='button' and row['name'].lower()==name.lower()),None)
        if not row:raise ValueError('Missing rendered action: '+name)
        return self.browser.run('action',self.sid,value['revision'],row['id'],'click','')
    def close(self):self.browser.close()


def action_app(root,payload):
    project=confined(root,payload['project']);descriptor(project)
    if payload.get('native'):
        from .cua_native import NativeWorker
        worker=NativeWorker()
        try:
            raw=worker.request('inspect',{'windowId':str(payload['native']['window_id'])})
            built=read(project/'.neyvia/latest-build.json')
            if Path(raw['window']['exe']).resolve()!=Path(built['artifact']).resolve():raise ValueError('Native target is not this SDK app')
            req=Request(urljoin(local_url(payload['url']),'/__neyvia/act'),data=json.dumps({'name':payload['name']}).encode(),headers={'X-Neyvia-App':'1','Content-Type':'application/json'})
            with urlopen(req,timeout=5) as response:value=json.load(response)
            return {'ok':value.get('ok') is True,'result':value,'observation':worker.request('inspect',{'windowId':str(payload['native']['window_id'])}),'state':state_app(root,payload)['state']}
        finally:worker.close()
    browser=AppBrowser(payload['url'],root=root)
    try:
        if browser.sdk('identity')!=descriptor(project).get('instance'):
            raise ValueError('Running app identity differs from selected project')
        result=browser.sdk('act',{'name':payload['name'],'arguments':payload.get('arguments',{}),'options':{'actionId':payload.get('actionId') or uuid.uuid4().hex}})
        return {'ok':True,'result':result,'observation':browser.observe(),'state':browser.sdk('state')}
    finally:browser.close()


def build_app(root,payload):
    project=confined(root,payload['project']);info=descriptor(project)
    platform=payload.get('platform','web')
    if platform in {'web', 'pwa'}: bundle_runtime(project)
    hashes=source_hashes(project)
    destination=project/'.neyvia/builds'/uuid.uuid4().hex
    destination.mkdir(parents=True)
    if platform in {'web','pwa'}:
        shutil.copytree(project/'www',destination/'www')
        for name in ('neyvia.app.json','manual.cl','host-contract.json'):shutil.copy2(project/name,destination/name)
        artifact=destination/'www/index.html'
    elif platform=='desktop' and info['kind']=='desktop' and os.name=='nt':
        framework=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319'
        artifact=destination/'app.exe'
        args=[str(framework/'csc.exe'),'/nologo','/target:winexe','/out:'+str(artifact),str(project/'native.cs')]
        args+=['/reference:'+str(framework/(name+'.dll')) for name in ('System.Windows.Forms','System.Drawing','System.Web.Extensions')]
        value=subprocess.run(args,capture_output=True,text=True,timeout=45,**hidden_windows_subprocess_kwargs())
        if value.returncode:raise RuntimeError('Desktop compile failed: '+value.stdout[-2000:])
    elif platform=='expo' and info['kind']=='expo':
        entry=project/'node_modules/expo/bin/cli'
        node=shutil.which('node')
        if not entry.is_file() or not node:
            return {'ok':False,'status':'blocked','needsPaul':True,'platform':platform,'error':'The generated app has no installed local Expo CLI or Node; App SDK never installs dependencies','missing':['local Expo CLI']}
        env={**os.environ,'EXPO_OFFLINE':'1','EXPO_NO_TELEMETRY':'1','CI':'1'}
        value=subprocess.run([node,str(entry),'export','--platform','web','--output-dir',str(destination/'www')],cwd=project,env=env,capture_output=True,text=True,timeout=180,**hidden_windows_subprocess_kwargs())
        if value.returncode:raise RuntimeError('Offline Expo export failed: '+value.stderr[-2000:])
        artifact=destination/'www/index.html'
        if not artifact.is_file():raise RuntimeError('Expo did not produce a web entry')
    else:
        return {'ok':False,'status':'blocked','needsPaul':True,'error':'Use the installed Mobile Studio native toolchain or installed Expo export; no dependencies are downloaded by App SDK','platform':platform}
    receipt={'ok':True,'status':'built','platform':platform,'project':str(project),'build':str(destination),'artifact':str(artifact),'artifactSha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'sourceHashes':hashes,'verified':False}
    atomic_write_json(destination/'build.json',receipt)
    atomic_write_json(project/'.neyvia/latest-build.json',receipt)
    return receipt


def verify_app(root,payload):
    project=confined(root,payload['project']);info=descriptor(project)
    contract=read(project/'host-contract.json')
    receipt={'ok':False,'status':'unverified','project':str(project),'url':local_url(payload['url']),'sourceHashes':source_hashes(project),'journey':[],'checks':[],'startedAt':time.time()}
    browser=worker=None
    try:
        goals,parser,dependency=cl_modules(payload.get('clSource'))
        receipt['clDependency']=dependency
        # CL 1.1 model views are distinct from the inherited archival grammar.
        # Validate the actual G using the normative observer evaluator below;
        # actions are parsed by the 1.1 call parser when a model emits them.
        view=(project/'manual.cl').read_text(encoding='utf-8')
        if not any(line.startswith('G ') and line.split(':',1)[-1].strip()==contract['goal'] for line in view.splitlines()):
            raise ValueError('Model-view G and executable host goal disagree')
        native=payload.get('native')
        if native:
            from .cua_native import NativeWorker
            worker=NativeWorker()
            window=str(native['window_id'])
            owned=worker.request('inspect',{'windowId':window})
            built=read(project/'.neyvia/latest-build.json')
            if Path(owned['window']['exe']).resolve()!=Path(built['artifact']).resolve() or built['sourceHashes']!=receipt['sourceHashes']:
                raise ValueError('Native window must run this app\'s current recorded build')
            if hashlib.sha256(Path(built['artifact']).read_bytes()).hexdigest()!=built['artifactSha256']:
                raise ValueError('Native executable changed after build')
            def request(path,body=None):
                req=Request(urljoin(payload['url'],path),data=json.dumps(body).encode() if body is not None else None,headers={'X-Neyvia-App':'1','Content-Type':'application/json'})
                with urlopen(req,timeout=5) as response:return json.load(response)
            def observe(name,pos,kwargs):
                if name=='app.state':return request('/__neyvia/state')
                if name=='win.text':
                    raw=worker.request('inspect',{'windowId':window})
                    receipt['nativeObservation']=raw
                    return json.dumps(raw,ensure_ascii=False)
                raise ValueError('Unknown native observer')
        else:
            browser=AppBrowser(payload['url'],root=root)
            browser.sdk('state')
            if browser.sdk('identity')!=info.get('instance'):
                raise ValueError('Running app identity differs from selected project')
            def observe(name,pos,kwargs):
                if name=='app.state':return browser.sdk('state')
                if name=='web.text':return browser.observe()['text']
                raise ValueError('Unknown web observer')
        readonly=lambda name:name in {'app.state','web.text','win.text'}
        # Caller may add steps but cannot replace the host's mandated journey.
        steps=contract['journey']+payload.get('steps',[])
        for step in steps:
            if native:
                if step['via']=='ui':
                    raw=worker.request('inspect',{'windowId':window})
                    rows=raw.get('tree',[])
                    row=next((r for r in rows if str(r.get('name',r.get('label',''))).lower()==step['action'].lower()),None)
                    if not row:raise ValueError('Missing native UI action: '+step['action'])
                    target={'windowId':window,'elementId':row['id'],'action':'invoke'}
                    try:delivery=worker.request('action',target)
                    except ValueError as error:
                        # T16's explicit target-only WindowsForms BM_CLICK route
                        # handles the known background InvokePattern refusal.
                        if not row.get('className','').startswith('WindowsForms10.BUTTON'):raise
                        delivery=worker.request('action',{**target,'action':'buttonClick'})
                        delivery['invokeRefusal']=str(error)
                    receipt.setdefault('nativeDeliveries',[]).append(delivery)
                elif step['via']=='api':request('/__neyvia/act',{'name':step['action']})
                else:raise ValueError('Unsupported native journey step')
            elif step['via']=='api':browser.sdk('act',{'name':step['action'],'arguments':step.get('arguments',{})})
            elif step['via']=='ui':
                browser.click(step['action'])
                try:browser.sdk('wait',{'count':step['expect']})
                except Exception as error:
                    # Preserve the adverse observation and evaluate -G below,
                    # rather than replacing a failed goal with a timeout label.
                    receipt.setdefault('waitErrors',[]).append(str(error))
            elif step['via']=='reload':browser.sdk('reload')
            else:raise ValueError('Unsupported journey step')
            check=goals.evaluate_goal('app.state().count == '+str(step['expect'])+' and '+json.dumps('Count: '+str(step['expect']))+' in '+('win.text()' if native else 'web.text()'),observe,readonly)
            receipt['journey'].append({'step':step,'goal':check})
            if not check['passed']:raise ValueError('Running-app step failed: '+json.dumps(step))
        final=goals.evaluate_goal(contract['goal'],observe,readonly)
        receipt['checks'].append({'name':'G','result':final})
        if browser:
            # Bind success to the served implementation, including preview URLs.
            served={}
            for relative,digest in receipt['sourceHashes'].items():
                if relative.startswith('www/') and relative.endswith(('.js','.webmanifest')):
                    with urlopen(urljoin(payload['url'],relative[4:]),timeout=5) as response:
                        served[relative]=hashlib.sha256(response.read(2_000_001)).hexdigest()
                    if served[relative]!=digest:raise ValueError('Running asset differs from selected source: '+relative)
            receipt['servedHashes']=served
        receipt['ok']=final['passed'] and receipt['sourceHashes']==source_hashes(project)
        receipt['status']='verified' if receipt['ok'] else 'refused'
        receipt['completion']='R done ok +G' if receipt['ok'] else 'R done refused -G'
        if browser:
            receipt['renderedObservation']=browser.observe()
            image=project/'.neyvia/verification'/('screen-'+uuid.uuid4().hex+'.png');image.parent.mkdir(parents=True,exist_ok=True)
            browser.sdk('screenshot',{'path':str(image)});receipt['screenshot']=str(image)
    except Exception as error:
        receipt.update(status='refused',completion='R done refused -G',error=str(error))
        if browser:
            try:receipt['renderedObservation']=browser.observe();receipt['observedState']=browser.sdk('state')
            except Exception:pass
    finally:
        if browser:browser.close()
        if worker:worker.close()
    receipt['elapsedMs']=round((time.time()-receipt['startedAt'])*1000)
    path=project/'.neyvia/verification'/(uuid.uuid4().hex+'.json')
    receipt['receipt']=str(path)
    atomic_write_json(path,receipt)
    atomic_write_json(project/'.neyvia/latest-verification.json',receipt)
    return receipt
