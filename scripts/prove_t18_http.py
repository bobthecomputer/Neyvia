"""Actual authenticated HTTP/native registry/desktop perception round-trip."""
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
REPO = Path(__file__).resolve().parents[1]
PYTHON = r'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe'
ROOT = REPO / 'scripts/evidence/.t18-http'
BASE = 'http://127.0.0.1:48201'
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / 'exact.json').write_text('{"id":"000739","date":"2026-10-02","value":42}', encoding='utf-8')
env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(REPO/'src'),
       'NEYVIA_COORDINATOR_AUTOSTART': '0', 'FLUXIO_WATCHDOG_AUTOSTART': '0',
       'NEYVIA_UI_BACKEND_URL': BASE}
rows = []


def request(opener, path, payload=None):
    req = urllib.request.Request(BASE+path, data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={'Content-Type':'application/json'})
    try:
        with opener.open(req, timeout=90) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def gate(name, passed, details):
    rows.append({'name':name,'passed':bool(passed),'details':details})


process = subprocess.Popen([PYTHON, str(REPO/'scripts/run_web_backend.py'), '--host','127.0.0.1','--port','48201','--root',str(ROOT),'--skip-runtime-auto-update'],
    env=env, cwd=REPO, stdout=(ROOT/'backend.stdout').open('wb'),stderr=(ROOT/'backend.stderr').open('wb'), creationflags=subprocess.CREATE_NO_WINDOW)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
try:
    deadline = time.monotonic()+45
    while time.monotonic()<deadline:
        try:
            status, answer=request(opener,'/api/ui/tools')
            break
        except urllib.error.URLError:
            if process.poll() is not None:
                raise RuntimeError('Scratch backend exited before serving')
            time.sleep(.2)
    else:
        raise RuntimeError('Scratch backend readiness timeout')
    gate('http-auth-required',status==401,answer)
    status,answer=request(opener,'/api/auth/local-session',{})
    gate('owner-local-session',status==200,{'status':status})
    status,catalog=request(opener,'/api/ui/tools')
    names=[r['name'] for r in catalog.get('data',{}).get('tools',[]) if r['name'].startswith('neyvia.perception.')]
    gate('six-http-tool-schemas',len(names)==6, names)
    payload={'tool':'neyvia.perception.observe','arguments':{'layer':'file','source':{'path':'exact.json'},'reset':True}}
    status,observation=request(opener,'/api/ui/tools/call',payload)
    result=observation.get('data',{}).get('result',{})
    gate('http-live-file-projection',status==200 and bool(result.get('handle')),observation)
    status,mismatch=request(opener,'/api/ui/tools/call',{**payload,'_expectedStateRoot':str(ROOT/'wrong')})
    gate('http-cross-workspace-refused',status==409,mismatch)
    command=[PYTHON,'-m','grant_agent.desktop_bridge','--root',str(ROOT)]
    bridge=subprocess.run(command,input=json.dumps({'command':'call_native_tool_command','payload':{'tool':'neyvia.perception.project','arguments':{'handle':result['handle'],'path':'/state/data/id'}}}),
        text=True,encoding='utf-8',capture_output=True,env=env,cwd=REPO,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
    desktop=json.loads(bridge.stdout)
    gate('desktop-same-handle-round-trip',desktop.get('data',{}).get('value')=='000739',desktop)
    status,manual=request(opener,'/api/ui/tools/call',{'tool':'neyvia.manual.run','arguments':{'id':'perception','chapter':'file','procedure':'read-layer','inputs':{'source':{'path':'exact.json'}}}})
    gate('http-executable-manual',manual.get('data',{}).get('result',{}).get('status')=='completed',manual)
finally:
    process.terminate()
    process.wait(timeout=15)
    (REPO/'scripts/evidence/T18-http.json').write_text(json.dumps({'ports':[48201],'gates':rows,'allPassed':bool(rows) and all(r['passed'] for r in rows)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'passed':sum(r['passed'] for r in rows),'total':len(rows)}))
raise SystemExit(0 if rows and all(r['passed'] for r in rows) else 1)
