"""Try Shell membership of a real new utility under previsibility containment."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys,time,uuid
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--app',choices=('Character Map','Google Chrome'),default='Character Map')
app=parser.parse_args().app
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.cua_desktop import AgentDesktop
from grant_agent.cua_bureau import BureauDesktop
from grant_agent.cua_guard import ZeroDisturbanceGuard
token=uuid.uuid4().hex
target=ROOT/'.agent_control/c11e'/token
target.mkdir(parents=True)
(target/'task.txt').write_text(token+'\nDisposable character composition task.\n',encoding='utf-8')
guard=ZeroDisturbanceGuard().start()
desktop=AgentDesktop()
result={'app':app,'token':token,'target':str(target.relative_to(ROOT)),'ok':False}
try:
    bureau=BureauDesktop(desktop,guard,ROOT/'.agent_control/c11-parked/parked-hook.dll',registration_probe=True)
    desktop.parked=bureau
    launch=['C:/Windows/System32/charmap.exe']
    if app=='Google Chrome':
        profile=target/'profile';profile.mkdir()
        page=target/(token+'.html');page.write_text('<title>'+token+'</title><label>Note<input></label>',encoding='utf-8')
        launch=['C:/Program Files/Google/Chrome/Application/chrome.exe','--user-data-dir='+str(profile),
            '--no-first-run','--no-default-browser-check','--disable-gpu',page.as_uri()]
    process=desktop._launch(launch,target,parked=True)
    deadline=time.monotonic()+8
    rows=[]
    visit_type=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    @visit_type
    def visit(h,unused):
        pid=W.DWORD();desktop.u.GetWindowThreadProcessId(h,C.byref(pid))
        if desktop.owns_pid(pid.value):
            title=C.create_unicode_buffer(1024);desktop.u.GetWindowTextW(h,title,len(title))
            if title.value and (app!='Google Chrome' or token in title.value):rows.append(int(h))
        return True
    desktop.u.EnumWindows.argtypes=[visit_type,W.LPARAM]
    while time.monotonic()<deadline:
        desktop.u.EnumWindows(visit,0)
        if rows:break
        time.sleep(.03)
    if not rows:
        result['launchExitCode']=process.poll()
        result['nativeCounters']=bureau.counters()
        raise RuntimeError('No new job-owned utility window')
    hwnd=rows[0]
    desktop.u.SetWindowTextW.argtypes=[W.HWND,W.LPCWSTR]
    desktop.u.SetWindowTextW(hwnd,'C11 Character Map '+token)
    result['assignment']=bureau.verify_window(hwnd)
    result['fixtureOwnership']=desktop.register_fixture(hwnd,target,token)
    result['membershipVerified']=bureau.library.dll.GetWindowDesktopNumber(hwnd)==bureau.library.index()
    result['ok']=bool(result['membershipVerified'])
except Exception as exc:
    result['error']=type(exc).__name__+': '+str(exc)
    if desktop.parked:result['assignmentDiagnostics']=desktop.parked.library.last_assignment
finally:
    result['cleanup']=desktop.close()
    result['guard']=guard.close()
    result['ok']=result['ok'] and result['guard']['ok']
(ROOT/('scripts/evidence/C11e-bureau-app-'+('chrome' if app=='Google Chrome' else 'charmap')+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:result.get(k) for k in ['app','ok','error','assignmentDiagnostics']}))
print(json.dumps({'zeroDisturbance':result['guard']['ok']}))
raise SystemExit(0 if result['ok'] else 2)
