"""Real stdio-worker capture with invariant-specific native adverse events."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor


def exercise_worker(*, root, port, session_cookie, url, category, controls=None):
    """controls(kind) owns runtime.offline/runtime.online in the launching host."""
    from grant_agent.neyvia_browser_capture import authenticated_request
    from grant_agent.native_tools import NativeToolRegistry
    repo = Path(__file__).resolve().parents[1]
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if category not in {'empty','huge','unicode','concurrency','interrupted','permissions','offline','stale'}:
        raise ValueError('Explicit capture category required')
    if category == 'offline' and controls is None:
        raise ValueError('Real runtime offline/online controls required')
    request = authenticated_request(port, session_cookie)
    env = {**os.environ, 'PYTHONPATH': str(repo/'src'), 'NEYVIA_BROWSER_OWNER_COOKIE': session_cookie,
           'NEYVIA_BROWSER_CONTEXT_URL': url, 'NEYVIA_COORDINATOR_AUTOSTART': '0',
           'FLUXIO_WATCHDOG_AUTOSTART': '0', 'NEYVIA_NAS_TRANSFER_ROOT': str(root/'explicit-unavailable-local-root')}
    geometry = {'x':10,'y':20,'width':30,'height':40}
    comment = '' if category == 'empty' else 'Unicode 雪🙂 é' if category == 'unicode' else 'H'*4000 if category == 'huge' else 'Actual native annotation'
    screenshot = {'url':url,'width':800,'height':600,'fullPage':False,'delayMs':0}
    annotation = {'url':url,'viewport':{'width':800,'height':600},'rectangle':geometry,'comment':comment,'delayMs':0}
    results, artifacts, checks, processes = [], [], [], []

    def require(condition, detail):
        if not condition:
            raise AssertionError(detail)

    def completed(op, args):
        value = request(op,args)
        aid = value.get('actionId')
        deadline = time.monotonic()+35
        while aid and value.get('status') not in {'done','failed'}:
            require(time.monotonic()<deadline,'Native completion deadline')
            time.sleep(.025)
            value = request('action.get',{'actionId':aid})
        require(value.get('ok') is not False and value.get('status') != 'failed',value)
        return value.get('result',value)

    class Worker:
        def __init__(self, selected_root):
            self.responses, self.errors, self.write_lock = queue.Queue(), [], threading.Lock()
            self.child = subprocess.Popen([sys.executable,'-m','grant_agent.native_tool_worker','--root',str(selected_root),
                '--browser-transport','neyvia','--browser-port',str(port)],cwd=repo,env=env,
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
            processes.append(self)
            def read():
                for line in self.child.stdout:
                    try:
                        self.responses.put(json.loads(line))
                    except Exception as error:
                        self.responses.put({'parseError':str(error),'line':line[:300]})
                self.responses.put({'eof':True})
            def read_errors():
                for line in self.child.stderr:
                    self.errors.append(line[-500:])
                    self.errors[:] = self.errors[-8:]
            self.reader = threading.Thread(target=read,daemon=True)
            self.reader.start()
            threading.Thread(target=read_errors,daemon=True).start()

        def send(self, identity, tool=None, arguments=None):
            value = {'id':identity,'tool':tool,'arguments':arguments} if tool else {'id':identity,'command':'shutdown'}
            with self.write_lock:
                self.child.stdin.write(json.dumps(value,ensure_ascii=True)+'\n')
                self.child.stdin.flush()

        def receive(self, identity=None):
            try:
                value = self.responses.get(timeout=180)
            except queue.Empty:
                raise AssertionError({'missingWorkerResponse':identity,'stderr':self.errors}) from None
            require(not value.get('eof') and not value.get('parseError'),value)
            require(identity is None or value.get('id') == identity,value)
            return value

        def stop(self):
            if self.child.poll() is None:
                self.send('shutdown')
                value = self.receive('shutdown')
                require(value.get('ok') and value['data'].get('shutdown'),value)
                self.child.wait(timeout=15)
            require(self.child.returncode == 0,{'exit':self.child.returncode,'stderr':self.errors})

    def success(value, contexts, *, reused, expected_comment=None):
        require(value.get('ok') and isinstance(value.get('data'),dict),value)
        data = value['data']
        require(data.get('ok') and data.get('status') == 'completed',data)
        worker, observed = data['worker'],data['result']['browserRuntime']
        require(worker['browserStarts'] == observed['browserStarts'] == 1
            and worker['contextsCreated'] == observed['contextsCreated'] == contexts
            and observed['browserReused'] is reused,'Native engine/context counters differ')
        require(data['result']['engine'] == 'neyvia-native','Capture substituted another browser')
        if expected_comment is not None:
            actual = data['result']['annotation']
            require(actual['geometry'] == {'type':'RECTANGLE','unit':'percent',**{k:float(v) for k,v in geometry.items()}}
                and actual['body']['value'] == expected_comment,'Persisted W3C geometry/comment differs')
            paths = data['result']['paths']
            require(NativeToolRegistry._png_dimensions(Path(paths['region'])) == (240,240),'Native crop dimensions differ')
            require(Path(paths['preview']).read_bytes() != Path(paths['annotated']).read_bytes(),'Annotation did not change real pixels')
        for item in data['result']['artifacts']:
            path = Path(item).resolve()
            path.relative_to(root)
            require(path.is_file() and path.stat().st_size,'Native artifact missing')
            artifacts.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
        results.append(data)
        return data

    def refusal(value, needles):
        data = value.get('data') or {}
        error = str(data.get('error') or value.get('error') or '')
        require(not value.get('ok') or (data.get('ok') is False and data.get('status') == 'failed'),'Refusal reported completed capture')
        require(any(needle.lower() in error.lower() for needle in needles),{'expectedRefusal':needles,'actual':value})
        require(not (data.get('result') or {}).get('browserRuntime'),'Failure invented successful capture counters')
        checks.append({'kind':'actual-worker-refusal','requestId':value['id'],'error':error[:500],'worker':data.get('worker')})
        return data

    def capture_tab(before):
        deadline = time.monotonic()+35
        while time.monotonic()<deadline:
            state = request('state',{})
            profiles = {p['id'] for p in state['profiles'] if p['name'].startswith('capture-')}
            candidates = [t for t in state['tabs'] if t['id'] not in before and t['profileId'] in profiles
                and t['live'] and not t['loading'] and t['agentGranted'] and t['url'] == url
                and sum(h['tabId'] == t['id'] and h['url'] == url for h in state['history']) >= 2]
            if len(candidates) == 1:
                return candidates[0]
            time.sleep(.05)
        raise AssertionError('Actual delayed capture context did not become ready')

    active, offline = Worker(root), False
    try:
        active.send('capture','preview.screenshot',screenshot)
        first = success(active.receive('capture'),1,reused=False)
        active.send('annotation','preview.annotate',annotation)
        second = success(active.receive('annotation'),2,reused=True,expected_comment=comment or 'Selected UI region')
        require(first['worker']['pid'] == second['worker']['pid'] == active.child.pid,'Baseline persistent worker identity changed')
        baseline = list(artifacts)
        epoch = request('state',{})['runtime']['epoch']
        if category == 'concurrency':
            before = {p['id'] for p in request('state',{})['profiles']}
            barrier = threading.Barrier(8)
            def enqueue(index):
                barrier.wait(timeout=10)
                active.send('competing-'+str(index),'preview.annotate',{**annotation,'comment':'Concurrent actual annotation '+str(index)})
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(enqueue,range(8)))
            values = [active.receive() for _ in range(8)]
            require({v['id'] for v in values} == {'competing-'+str(i) for i in range(8)},'Competing requests lost or duplicated')
            for index,value in enumerate(values,3):
                success(value,index,reused=True,expected_comment='Concurrent actual annotation '+value['id'].split('-')[-1])
                require(value['data']['worker']['pid'] == first['worker']['pid'],'Concurrent request replaced worker')
            fresh = [p for p in request('state',{})['profiles'] if p['id'] not in before and p['name'].startswith('capture-')]
            require(len(fresh) == len({p['id'] for p in fresh}) == 8,'Concurrent requests shared native contexts')
            checks.append({'kind':'eight-competing-stdio-calls','requests':8,'distinctNativeProfiles':8,'sameWorkerPid':first['worker']['pid'],'contextsCreated':10})
        elif category in {'permissions','interrupted','stale'}:
            before = {t['id'] for t in request('state',{})['tabs']}
            output = root/('adverse-'+category)
            active.send('adverse','preview.annotate',{**annotation,'delayMs':10000,'outputDir':str(output)})
            tab = capture_tab(before)
            if category == 'permissions':
                request('tab.grant',{'tabId':tab['id'],'enabled':False})
                current = next(t for t in request('state',{})['tabs'] if t['id'] == tab['id'])
                require(not current['agentGranted'],'Owner grant revocation did not persist')
                denied = refusal(active.receive('adverse'),['grant'])
                require(denied['worker']['browserStarts'] == 1 and denied['worker']['contextsCreated'] == 3,'Refusal changed native context history')
                require(not (output/'annotation.json').exists() and not (output/'annotated.png').exists(),'Denied annotation published completed artifacts')
                active.send('recovery','preview.annotate',annotation)
                success(active.receive('recovery'),4,reused=True,expected_comment=comment)
                checks.append({'kind':'actual-tab-grant-revocation','tabId':tab['id'],'sameWorkerRecovery':True})
            elif category == 'interrupted':
                active.child.terminate()
                active.child.wait(timeout=15)
                active.reader.join(timeout=2)
                require(active.child.returncode != 0 and not (output/'annotation.json').exists(),'Terminated producer claimed completion')
                received = []
                while not active.responses.empty():
                    value = active.responses.get_nowait()
                    if not value.get('eof'):
                        received.append(value)
                require(not received,{'unexpectedInterruptedCompletion':received})
                completed('tab.close',{'tabId':tab['id']})
                require(not any(t['id'] == tab['id'] for t in request('state',{})['tabs']),'Owned orphan context remained')
                killed_pid = active.child.pid
                active = Worker(root/'recovery')
                active.send('recovery-capture','preview.screenshot',screenshot)
                recovered = success(active.receive('recovery-capture'),1,reused=False)
                active.send('recovery-annotation','preview.annotate',annotation)
                success(active.receive('recovery-annotation'),2,reused=True,expected_comment=comment)
                require(recovered['worker']['pid'] != killed_pid and request('state',{})['runtime']['epoch'] == epoch,'Producer recovery changed native epoch')
                checks.append({'kind':'terminated-admitted-stdio-producer','killedPid':killed_pid,'closedOrphanTab':tab['id'],'nativeEpochUnchanged':True,'recoveryPid':recovered['worker']['pid']})
            else:
                observed = completed('observe',{'tabId':tab['id']})['observation']
                # Annotation overlays live outside body and preserve the target
                # projection. Change visible app state through a real native
                # action before testing refusal of the previous revision.
                button = next(element for element in observed['elements']
                              if element['role'] == 'button' and element['name'] == 'Change preview state')
                completed('action',{'tabId':tab['id'],'revision':observed['revision'],
                                    'element':button['id'],'action':'click'})
                fresh = completed('observe',{'tabId':tab['id']})['observation']
                require('Owned C7d preview updated' in fresh['text'],'Native action did not update visible app state')
                require(fresh['revision'] != observed['revision'],'Native mutation did not change revision')
                try:
                    request('annotate',{'tabId':tab['id'],'revision':observed['revision'],'rectangle':geometry,'comment':'Stale annotation must be refused'})
                except RuntimeError as error:
                    require('Refresh this tab before annotation' in str(error) or 'stale_projection' in str(error),error)
                    checks.append({'kind':'actual-stale-native-revision-refused','beforeRevision':observed['revision'],'currentRevision':fresh['revision'],'error':str(error)[:500]})
                else:
                    raise AssertionError('Stale native annotation was admitted')
                success(active.receive('adverse'),3,reused=True,expected_comment=comment)
        elif category == 'offline':
            controls('runtime.offline')
            offline = True
            require(not request('state',{})['runtime']['connected'],'Native runtime remained online')
            active.send('offline','preview.annotate',annotation)
            denied = refusal(active.receive('offline'),['disconnected'])
            require(denied['worker']['browserStarts'] == 1 and denied['worker']['contextsCreated'] == 2,'Offline refusal invented native context')
            active.stop()
            controls('runtime.online')
            offline = False
            state = request('state',{})
            require(state['runtime']['connected'] and state['runtime']['epoch'] != epoch,'Native restart lacks fresh epoch')
            active = Worker(root/'online-recovery')
            active.send('online-capture','preview.screenshot',screenshot)
            success(active.receive('online-capture'),1,reused=False)
            active.send('online-annotation','preview.annotate',annotation)
            success(active.receive('online-annotation'),2,reused=True,expected_comment=comment)
            checks.append({'kind':'actual-native-runtime-offline-and-recovery','beforeEpoch':epoch,'afterEpoch':state['runtime']['epoch'],'noOfflineContextCreated':True})
        elif category == 'huge':
            active.send('oversized-comment','preview.annotate',{**annotation,'comment':'H'*4001})
            denied = refusal(active.receive('oversized-comment'),['4000','bounded comment'])
            require(denied['worker']['browserStarts'] == 1,'Oversized comment invented engine restart')
            checks.append({'kind':'exact-annotation-comment-bound','acceptedCharacters':4000,'refusedCharacters':4001})
        else:
            checks.append({'kind':'actual-persisted-comment','characters':len(comment),'emptyDefault':category == 'empty','unicodePreserved':category == 'unicode'})
        for artifact in baseline:
            require(hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest() == artifact['sha256'],'Adverse event changed prior durable pixels')
        active.stop()
        return {'ok':True,'category':category,'workerExit':active.child.returncode,'workerPid':first['worker']['pid'],
                'observations':[first['worker'],second['worker']],'results':results,'artifacts':artifacts,'categoryChecks':checks,
                'ownedWorkerExits':[{'pid':w.child.pid,'exit':w.child.returncode} for w in processes],
                'boundary':'Actual persistent stdio worker and Neyvia native captures/annotation with category-specific effects; no Chrome, replayed operation or fabricated pixels'}
    finally:
        if offline:
            controls('runtime.online')
        for worker in processes:
            if worker.child.poll() is None:
                worker.child.kill()
                worker.child.wait(timeout=15)
