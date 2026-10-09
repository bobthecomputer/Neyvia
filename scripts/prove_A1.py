"""Reproducible A1 real-run acceptance, no test suite and no downloads."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import base64
from urllib.request import urlopen

sys.dont_write_bytecode=True
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent import app_sdk as sdk
from grant_agent.durability import atomic_write_json
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs

CL=Path('C:/Users/user/Projects/nx-integrate-cl')

def wait(url,process):
    until=time.monotonic()+15
    while time.monotonic()<until:
        if process.poll() is not None:raise RuntimeError('Owned app host exited')
        try:
            with urlopen(url,timeout=1) as response:
                if response.status==200:return
        except OSError:time.sleep(.1)
    raise TimeoutError('Owned host did not start')


def cl_done(app,url,goal):
    from grant_agent.cl.host import HostContext
    browser=sdk.AppBrowser(url)
    tools=[{'name':name,'annotations':{'readOnlyHint':True},'inputSchema':{'type':'object','properties':{},'additionalProperties':False}} for name in ('app.state','web.text')]
    def dispatch(name,args,action_id=''):
        return browser.sdk('state') if name=='app.state' else browser.observe()['text']
    try:
        host=HostContext(tools,dispatch,goals=[goal],root=app)
        return host.execute('done("Runtime feature complete")')
    finally:browser.close()

def main():
    if '--resume-native' in sys.argv:
        return resume_native()
    run=REPO/'scripts/evidence/A1-runs'/uuid.uuid4().hex
    run.mkdir(parents=True)
    scratch=REPO/'.agent_control/a1'/run.name
    scratch.mkdir(parents=True)
    app=scratch/'counter';native=scratch/'desktop'
    result={'version':1,'run':str(run.relative_to(REPO)),'requestedModel':'gpt-6-luna','ports':[48545,48546],'limitations':[]}
    processes=[]
    try:
        result['generated']=sdk.new_app(REPO,{'path':str(app),'kind':'pwa','name':'A1 Feature Counter'})
        command=[sys.executable,str(app/'server.py'),'--port','48545']
        process=subprocess.Popen(command,cwd=REPO,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**hidden_windows_subprocess_kwargs());processes.append(process)
        url='http://127.0.0.1:48545/'
        wait(url,process)
        result['baseline']=sdk.verify_app(REPO,{'project':str(app),'url':url,'clSource':str(CL)})
        if not result['baseline']['ok']:raise RuntimeError('Baseline journey refused: '+result['baseline'].get('error',''))
        _,parser,_=sdk.cl_modules(str(CL))
        provider=__import__('grant_agent.cl.benchmark_provider',fromlist=['propose'])
        model=(app/'www/model.js').read_text()
        prompt=('Task: extend the real generated app with a Double button which doubles count. The UI creates buttons from actions. '
                'Use the manual. Add "double" to actions and implement it in reducer without changing existing behavior. '
                'The host owns the goal and will verify reset/increment/double/decrement/reload against the running app. '
                'Return exactly one CL 1.1 sdk.write(path="www/model.js", body="FULL REPLACEMENT CONTENT") call. No shell or CLI tools. '
                'The external host fills CAS stamps, writes the file and verifies its bytes.\n'
                + (CL/'docs/standard/1.1/primer.md').read_text()+'\n'
                + (app/'manual.cl').read_text()+'\nA sdk.write(path, body) ~\nG: "Double" in web.text() and app.state().count == 1\n'
                +'Current www/model.js:\n'+model)
        if '--reuse-luna' in sys.argv:
            previous=Path(sys.argv[sys.argv.index('--reuse-luna')+1]).resolve()
            answer=sdk.read(previous/'receipt.json')
            shutil.copytree(previous,run/'luna')
            result['replayedModelProposal']=str(previous.relative_to(REPO))
        else:answer=provider.propose(prompt,'gpt-6-luna',run/'luna',timeout=180)
        result['luna']=answer
        if not answer['passed']:raise RuntimeError('Requested Luna route failed; no substitute used')
        calls=[]
        for line in parser.logical_lines(answer['answer']):
            try:calls.append(parser.parse_action(line))
            except Exception:continue
        calls=[call for call in calls if call.name=='sdk.write']
        if len(calls)!=1:raise ValueError('Luna must author exactly one sdk.write')
        call=calls[0]
        if call.arguments.get('path')!='www/model.js' or set(call.arguments)!={'path','body'}:raise ValueError('Model write left the assigned feature source')
        before=sdk.source_hashes(app)
        (app/'www/model.js').write_text(call.arguments['body'],encoding='utf-8')
        if (app/'www/model.js').read_text()!=call.arguments['body']:raise ValueError('Source write readback failed')
        # Task-author contract: a feature must demonstrate its behavior, not
        # persuade the model to weaken the original goal.
        contract=sdk.read(app/'host-contract.json')
        contract['journey'] += [{'via':'api','action':'reset','expect':0},{'via':'ui','action':'increment','expect':1},{'via':'ui','action':'double','expect':2},{'via':'api','action':'decrement','expect':1},{'via':'reload','expect':1}]
        contract['goal']='app.state().count == 1 and "Count: 1" in web.text() and "Double" in web.text()'
        atomic_write_json(app/'host-contract.json',contract)
        view=(app/'manual.cl').read_text().replace('"reset",','"reset"|"double",')
        view='\n'.join(('G complete: '+contract['goal']) if line.startswith('G complete:') else ('P app.counter() G: '+contract['goal']) if line.startswith('P app.counter') else line for line in view.splitlines())+'\n'
        (app/'manual.cl').write_text(view,encoding='utf-8')
        result['modelEdit']={'call':answer['answer'],'beforeHashes':before,'afterHashes':sdk.source_hashes(app),'readback':True}
        result['featureBuild']=sdk.build_app(REPO,{'project':str(app),'platform':'pwa'})
        result['feature']=sdk.verify_app(REPO,{'project':str(app),'url':url,'clSource':str(CL)})
        if not result['feature']['ok']:raise RuntimeError('Luna feature failed runtime gate: '+result['feature'].get('error',''))
        image=run/'feature.png';shutil.copy2(result['feature']['screenshot'],image);result['featureScreenshot']=str(image.relative_to(REPO))
        good=(app/'www/model.js').read_text()
        broken=good.replace('state.count+1','state.count+0').replace('state.count + 1','state.count + 0')
        if good==broken:raise ValueError('Mutation did not break increment')
        (app/'www/model.js').write_text(broken)
        result['brokenBuild']=sdk.build_app(REPO,{'project':str(app),'platform':'pwa'})
        result['broken']=sdk.verify_app(REPO,{'project':str(app),'url':url,'clSource':str(CL)})
        result['clDoneBroken']=cl_done(app,url,contract['goal'])
        if result['clDoneBroken']['ok']:raise ValueError('CL1.1 host admitted broken app as done')
        if result['broken']['ok'] or result['broken']['completion']!='R done refused -G':raise ValueError('Broken app incorrectly completed')
        (app/'www/model.js').write_text(good)
        result['repaired']=sdk.verify_app(REPO,{'project':str(app),'url':url,'clSource':str(CL)})
        if not result['repaired']['ok']:raise RuntimeError('Repaired feature did not pass')
        result['clDoneRepaired']=cl_done(app,url,contract['goal'])
        if not result['clDoneRepaired']['ok']:raise RuntimeError('CL1.1 host refused repaired app')
        # Separate agent context must drive the exact state shown to the user.
        user=sdk.AppBrowser(url)
        try:
            result['botAction']=sdk.action_app(REPO,{'project':str(app),'url':url,'name':'increment'})
            result['sharedUserObservation']=user.sdk('wait',{'count':2})
            result['sharedState']=sdk.state_app(REPO,{'project':str(app)})
            if result['sharedState']['state']['count']!=2:raise ValueError('User and agent state diverged')
        finally:user.close()
        result['nativeGenerated']=sdk.new_app(REPO,{'path':str(native),'kind':'desktop','name':'A1 Native Counter'})
        result['nativeBuild']=sdk.build_app(REPO,{'project':str(native),'platform':'desktop'})
        startup=subprocess.STARTUPINFO();startup.dwFlags=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=4
        process=subprocess.Popen([result['nativeBuild']['artifact'],'48546'],cwd=native,startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW);processes.append(process)
        from grant_agent.cua_native import NativeWorker
        worker=NativeWorker()
        try:
            until=time.monotonic()+15;owned=None
            while time.monotonic()<until:
                owned=next((row for row in worker.request('windows') if row['pid']==process.pid),None)
                if owned:break
                time.sleep(.1)
            if not owned:raise RuntimeError('Generated desktop window did not open')
            result['native']=sdk.verify_app(REPO,{'project':str(native),'url':'http://127.0.0.1:48546/','clSource':str(CL),'native':{'window_id':owned['windowId'],'pid':process.pid}})
            if not result['native']['ok']:raise RuntimeError('Native journey failed: '+result['native'].get('error',''))
            capture=worker.request('capture',{'windowId':owned['windowId']})
            image=run/'native.png';image.write_bytes(base64.b64decode(capture.pop('pngBase64')))
            result['nativeCapture']={**capture,'path':str(image.relative_to(REPO))}
            result['nativeStateTool']=sdk.state_app(REPO,{'project':str(native)})
            if result['nativeStateTool']['state']['count']!=1:raise ValueError('Native state tool differs from rendered goal')
        finally:worker.close()
        # Preserve model-authored first-commit-ready app source and contracts.
        shutil.copytree(app,run/'generated-app',ignore=shutil.ignore_patterns('.neyvia'))
        shutil.copytree(native,run/'generated-desktop',ignore=shutil.ignore_patterns('.neyvia'))
        result['ok']=True
    except Exception as error:result.update(ok=False,error=str(error))
    finally:
        for process in reversed(processes):
            if process.poll() is None:process.terminate();process.wait(timeout=10)
        result['finishedAt']=time.time()
        atomic_write_json(run/'receipt.json',result)
        atomic_write_json(REPO/'scripts/evidence/A1.json',result)
    print(json.dumps({'ok':result.get('ok'),'error':result.get('error'),'run':str(run),'lunaTokens':result.get('luna',{}).get('usage'),'native':result.get('native',{}).get('ok'),'brokenRefused':result.get('broken',{}).get('completion')},indent=2))
    return 0 if result.get('ok') else 1


def resume_native():
    result=sdk.read(REPO/'scripts/evidence/A1.json')
    run=REPO/result['run'];native=Path(result['nativeGenerated']['project']);app=Path(result['generated']['project'])
    result.setdefault('recoveries',[]).append({'error':result.pop('error',None),'cause':'Hidden startup-info suppressed the owned WinForms window; show without activation'})
    worker=process=None
    try:
        startup=subprocess.STARTUPINFO();startup.dwFlags=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=4
        process=subprocess.Popen([result['nativeBuild']['artifact'],'48546'],cwd=native,startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW)
        from grant_agent.cua_native import NativeWorker
        worker=NativeWorker();until=time.monotonic()+15;owned=None
        while time.monotonic()<until:
            owned=next((row for row in worker.request('windows') if row['pid']==process.pid),None)
            if owned:break
            if process.poll() is not None:raise RuntimeError('Native host exited: '+str(process.returncode))
            time.sleep(.1)
        if not owned:raise RuntimeError('Native window remains unavailable')
        result['native']=sdk.verify_app(REPO,{'project':str(native),'url':'http://127.0.0.1:48546/','clSource':str(CL),'native':{'window_id':owned['windowId'],'pid':process.pid}})
        if not result['native']['ok']:raise RuntimeError(result['native'].get('error','Native goal failed'))
        shutil.copytree(app,run/'generated-app',ignore=shutil.ignore_patterns('.neyvia'),dirs_exist_ok=True)
        shutil.copytree(native,run/'generated-desktop',ignore=shutil.ignore_patterns('.neyvia'),dirs_exist_ok=True)
        result['ok']=True
    except Exception as error:result.update(ok=False,error=str(error))
    finally:
        if worker:worker.close()
        if process and process.poll() is None:process.terminate();process.wait(timeout=10)
        atomic_write_json(run/'receipt.json',result);atomic_write_json(REPO/'scripts/evidence/A1.json',result)
    print(json.dumps({'ok':result['ok'],'error':result.get('error'),'native':result.get('native',{}).get('ok')},indent=2))
    return 0 if result['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
