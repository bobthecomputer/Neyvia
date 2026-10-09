"""Close the initial task-owned guardian; its kill-on-close job owns descendants."""
import importlib.util
import json
from pathlib import Path
import time
import psutil

repo=Path(__file__).resolve().parents[1]
directory=repo/'.agent_control/C2g/private-native-48721'
initial=json.loads((directory/'launch.json').read_text(encoding='utf-8'))
source=Path(r'C:\Users\user\Projects\nx-c1-cua\src\grant_agent\cua_guard.py')
spec=importlib.util.spec_from_file_location('c2g_final_native_guard',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
native=psutil.Process(initial['pid']);controller=native.parent()
if 'c2g_launch_native.py' not in ' '.join(controller.cmdline()):raise RuntimeError('Refuse stopping a process not owned by this task launcher')
if not any(arg=='48721' for arg in controller.cmdline()):raise RuntimeError('Refuse stopping another track controller')
guard=module.ZeroDisturbanceGuard().start();guard.register_pid(native.pid);guard.register_pid(controller.pid)
try:
    time.sleep(1)
    before=guard.check()
    if not before['ok']:raise RuntimeError('Final independent guard unavailable')
    controller.terminate();controller.wait(10)
    time.sleep(1)
    stopped=not psutil.pid_exists(initial['pid']) or psutil.Process(initial['pid']).status()==psutil.STATUS_ZOMBIE
finally:after=guard.close()
report={'schema':'neyvia.C2g.initial-native-close@1','initial':initial,'controllerPid':controller.pid,'closeMethod':'Terminate owned guardian; OS closes private desktop kill-on-close job','before':before,'after':after,'nativeStopped':stopped,'boundary':'Final guarded closure interval, initial guard retained; no claim of a full-duration receipt'}
(repo/'scripts/evidence/C2g-native-initial-close.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
(directory/'launch-initial.json').write_text(json.dumps(initial,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'nativeStopped':stopped,'guardOk':after['ok'],'controllerPid':controller.pid}))
