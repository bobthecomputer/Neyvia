"""Real hidden-first Bureau launches; never selects a desktop or sends input."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cua_desktop import AgentDesktop
from grant_agent.cua_bureau import BureauDesktop
from grant_agent.cua_guard import ZeroDisturbanceGuard
from grant_agent.cua_parked import parked_hook_path
from run_c11_cohort import write_receipt


def run(exe='C:/Windows/System32/charmap.exe', app='Character Map', hidden_only=False):
    token = uuid.uuid4().hex
    target = ROOT / '.agent_control/c11f-bureau' / token
    target.mkdir(parents=True)
    guard = ZeroDisturbanceGuard().start()
    desktop = AgentDesktop()
    result = {'app': app, 'token': token, 'target': str(target), 'ok': False,
              'sources': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in [ROOT/'src/grant_agent/cua_bureau.py', ROOT/'src/grant_agent/cua_desktop.py',
                                    ROOT/'tools/cua-driver-win/parked-hook.cpp', Path(__file__)]}}
    try:
        hook=parked_hook_path(desktop.profile_root)
        result['nativeHook']={'path':str(hook),'sha256':hashlib.sha256(hook.read_bytes()).hexdigest()}
        bureau = BureauDesktop(desktop, guard, hook)
        desktop.parked = bureau
        result['desktopBefore'] = bureau.library.status()
        launch=[exe]
        if app=='Notepad':
            document=target/(token+'.txt');document.write_text('Disposable note '+token+'\n',encoding='utf-8')
            launch.append(str(document))
        if app in {'Paint','Photos','Snipping Tool'}:
            from PIL import Image
            document=target/(token+'.png');Image.new('RGB',(640,480),'white').save(document)
            launch.append(str(document))
        result['launch']=launch
        process = desktop._launch(launch, target, parked=True)
        deadline = time.monotonic()+10
        window = None
        while time.monotonic() < deadline:
            # Enumerate all HWNDs, including hidden windows; EnumWindows omits
            # some newly constructed windows until their desktop is bound.
            rows = []
            visit_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
            @visit_type
            def visit(h, unused):
                pid=W.DWORD(); desktop.u.GetWindowThreadProcessId(h,C.byref(pid))
                if desktop.owns_pid(pid.value):
                    title=C.create_unicode_buffer(1024); desktop.u.GetWindowTextW(h,title,len(title))
                    cls=C.create_unicode_buffer(256);desktop.u.GetClassNameW(h,cls,len(cls))
                    rect=W.RECT();desktop.u.GetWindowRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
                    desktop.u.GetWindowRect(h,C.byref(rect))
                    fixture_ready=(app not in {'Notepad','Paint'} or token in title.value)
                    if title.value and fixture_ready and rect.right-rect.left>250 and rect.bottom-rect.top>150 and cls.value not in {'IME','MSCTFIME UI'}:
                        rows.append({'hwnd':int(h),'title':title.value,'class':cls.value,'width':rect.right-rect.left,'height':rect.bottom-rect.top})
                return True
            desktop.u.EnumDesktopWindows.argtypes=[W.HANDLE,visit_type,W.LPARAM]
            desktop.u.EnumDesktopWindows(bureau.handle,visit,0)
            if rows:
                result['candidates']=rows
                window=max(rows,key=lambda r:r['width']*r['height'])['hwnd']; break
            time.sleep(.05)
        result['exitCode']=process.poll()
        result['nativeCounters']=bureau.counters()
        if not window: raise RuntimeError('No job-owned top-level window returned')
        result['hwnd']=window
        result['newHwnd']=window not in bureau._windows_before
        result['newJobOwnedProcess']=desktop.owns_pid(process.pid)
        if hidden_only:
            result['hiddenLaunchVerified']=not bool(desktop.u.IsWindowVisible(window))
            result['ok']=result['hiddenLaunchVerified']
            return result
        result['assignment']=bureau.verify_window(window)
        result['fixtureOwnership']=desktop.register_fixture(window,target,token)
        result['membershipVerified']=bureau.library.dll.GetWindowDesktopNumber(window)==bureau.library.index()
        result['ok']=result['membershipVerified']
    except Exception as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        if desktop.parked:
            result['assignmentDiagnostics']=desktop.parked.library.last_assignment
            result['nativeCounters']=desktop.parked.counters()
            result['registrationDiagnostics']=getattr(desktop.parked,'last_registration_failure',None)
    finally:
        if desktop.parked:
            result['finalNativeCounters']=desktop.parked.counters()
        result['cleanup']=desktop.close()
        if 'bureau' in locals():
            result['bureauCleanup']=bureau.library.cleanup
        result['guard']=guard.close()
        result['ok']=result['ok'] and result['guard']['ok']
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',default='C:/Windows/System32/charmap.exe')
    parser.add_argument('--app',default='Character Map')
    parser.add_argument('--hidden-only',action='store_true')
    parser.add_argument('--receipt',type=Path,default=ROOT/'scripts/evidence/C11f-bureau.json')
    args=parser.parse_args()
    result=run(args.exe,args.app,args.hidden_only)
    write_receipt(args.receipt,result)
    print(json.dumps({k:result.get(k) for k in ['app','ok','hwnd','candidates','error','nativeCounters','assignmentDiagnostics']}))
    raise SystemExit(0 if result['ok'] else 2)
