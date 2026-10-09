"""CLI generation, portable host and static phone-export real runs."""
from pathlib import Path
import functools
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
sys.dont_write_bytecode=True
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent import app_sdk as sdk
from grant_agent.durability import atomic_write_json
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
from prove_A1 import wait

def main():
    root=REPO/'.agent_control/a1-exports'/uuid.uuid4().hex;root.mkdir(parents=True)
    result={'root':str(root),'ports':[48547,48548]};process=server=browser=None
    try:
        app=root/'generated'
        command=['node',str(REPO/'scripts/fluxio-cli.mjs'),'app','new','pwa','--path',str(app),'--name','Portable A1']
        raw=subprocess.run(command,cwd=REPO,capture_output=True,text=True,timeout=30,**hidden_windows_subprocess_kwargs())
        result['cli']={'exitCode':raw.returncode,'result':json.loads(raw.stdout)}
        if raw.returncode:raise RuntimeError('Canonical neyvia CLI app creation failed')
        moved=root/'moved';shutil.copytree(app,moved)
        process=subprocess.Popen([sys.executable,str(moved/'server.py'),'--port','48547'],cwd=moved,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**hidden_windows_subprocess_kwargs())
        url='http://127.0.0.1:48547/';wait(url,process)
        result['movedHost']=sdk.verify_app(REPO,{'project':str(moved),'url':url,'clSource':'C:/Users/user/Projects/nx-integrate-cl'})
        if not result['movedHost']['ok']:raise RuntimeError(result['movedHost'].get('error','Relocated app failed'))
        class Static(SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
        handler=functools.partial(Static,directory=str(moved/'www'))
        server=ThreadingHTTPServer(('127.0.0.1',48548),handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        browser=sdk.AppBrowser('http://127.0.0.1:48548/')
        result['deviceInitial']=browser.sdk('state')
        browser.click('increment');browser.sdk('wait',{'count':1})
        result['deviceUserState']=browser.sdk('state')
        result['deviceAgentAction']=browser.sdk('act',{'name':'increment'})
        result['deviceAgentObservation']=browser.sdk('wait',{'count':2})
        browser.sdk('reload');result['deviceReloadState']=browser.sdk('state')
        if result['deviceReloadState']['count']!=2:raise ValueError('Device-local shared state did not persist')
        result['deviceScreenshot']='scripts/evidence/A1-device-export.png'
        browser.sdk('screenshot',{'path':str(REPO/result['deviceScreenshot'])})
        result['expo']=sdk.new_app(REPO,{'path':str(root/'expo'),'kind':'expo','name':'A1 Expo'})
        result['expoBuild']=sdk.build_app(REPO,{'project':str(root/'expo'),'platform':'expo'})
        result['expoNativeProven']=False
        result['limitation']='Expo native runtime and physical iOS/Android devices are not present; static device export is distinct from native device proof'
        result['ok']=True
    except Exception as error:result.update(ok=False,error=str(error))
    finally:
        if browser:browser.close()
        if server:server.shutdown();server.server_close()
        if process and process.poll() is None:process.terminate();process.wait(timeout=10)
        atomic_write_json(REPO/'scripts/evidence/A1-exports.json',result)
    print(json.dumps({'ok':result.get('ok'),'error':result.get('error'),'expoNative':result.get('expoNativeProven')},indent=2))
    return 0 if result.get('ok') else 1

if __name__=='__main__':raise SystemExit(main())
