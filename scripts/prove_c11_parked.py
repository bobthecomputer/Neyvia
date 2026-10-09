"""Real safety journey: hidden probe attempts show, move, activate and focus.

Build its x64 hook and hidden executable with build_c11_parked.ps1 first.
The show attempt is dispatched only after previsibility containment is checked.
"""
from pathlib import Path
import argparse, hashlib, json, sys, time
root=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(root/'src'))
parser=argparse.ArgumentParser()
parser.add_argument('--receipt', type=Path, default=root/'scripts/evidence/C11b-parked.json')
output=parser.parse_args().receipt.resolve()
if not output.is_relative_to(root/'scripts/evidence'): parser.error('Receipt must remain in task evidence')
from grant_agent.cua_desktop import AgentDesktop
from grant_agent.cua_guard import ZeroDisturbanceGuard
area=root/'.agent_control/c11-parked'; stamp=area/('run-'+str(time.time_ns()))
receipt={'route':'parked-hidden','fixture':'native x64 hidden task-local probe','success':False}
receipt['sourceSha256']={str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
 for p in [Path(__file__),*(root/'src/grant_agent').glob('cua_*.py'),root/'tools/cua-driver-win/parked-hook.cpp',root/'tools/cua-driver-win/parked-probe.cpp']}
receipt['nativeSha256']={str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
 for p in [area/'parked-hook.dll',area/'parked-probe.exe']}
guard=ZeroDisturbanceGuard().start()
try:
 baseline=guard.snapshot()
 assert all(baseline.get(key) for key in ('ok','input_hooks_installed','input_desktop_bound')), 'Input attribution unavailable'
 with AgentDesktop(profile_root=root/'.agent_control') as desktop:
  process=desktop.launch_parked([str(area/'parked-probe.exe'),str(stamp)],guard=guard,dll_path=area/'parked-hook.dll')
  deadline=time.monotonic()+8
  while not Path(str(stamp)+'.hwnd').exists() and time.monotonic()<deadline:
   if process.poll() is not None: raise RuntimeError('probe exited '+str(process.returncode))
   time.sleep(.03)
  hwnd=int(Path(str(stamp)+'.hwnd').read_text())
  receipt['preAttempt']=desktop.parked.verify_window(hwnd)
  assert desktop.owns(hwnd)
  assert desktop.u.PostMessageW(hwnd,0x8000,0,0)
  deadline=time.monotonic()+5
  while not Path(str(stamp)+'.result').exists() and time.monotonic()<deadline: time.sleep(.01)
  receipt['result']=Path(str(stamp)+'.result').read_text()
  receipt['postAttempt']=desktop.parked.verify_window(hwnd)
  receipt['hookCounters']=desktop.parked.counters()
  assert receipt['result']=='hidden'
  assert receipt['hookCounters']['positionEnforcements']>0
  receipt['brokerGate']=desktop.launch_policy(['C:/Windows/System32/calc.exe'])
  assert receipt['brokerGate']['status']=='needs-permission'
  receipt['success']=True
except Exception as exc: receipt['error']=str(exc)
finally: receipt['guard']=guard.close()
receipt['success']=receipt['success'] and receipt['guard']['ok']
output.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'success':receipt['success'],'error':receipt.get('error'),'hookCounters':receipt.get('hookCounters'),
                 'zeroDisturbance':receipt['guard']['ok'],'violations':receipt['guard']['violations']}))
raise SystemExit(0 if receipt['success'] and receipt['guard']['ok'] else 1)
