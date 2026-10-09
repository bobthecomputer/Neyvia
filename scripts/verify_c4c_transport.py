"""Real Windows byte-lock contention and UTF-8 subprocess failure checks."""
import ast
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
import run_c4c
import c4c_quality

def main():
    root=REPO/'.agent_control/c4'/('c4c-transport-check-'+str(time.time_ns()))
    lock=root/'.agent_control/c4c-browser.lock';lock.parent.mkdir(parents=True);lock.write_bytes(b'0')
    code="import msvcrt,sys\nf=open(sys.argv[1],'r+b');msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)\nprint('READY',flush=True);sys.stdin.readline();f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1);f.close()"
    child=subprocess.Popen([c4c_quality.PYTHON,'-c',code,str(lock)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,**hidden_windows_subprocess_kwargs())
    assert child.stdout.readline().strip()=='READY'
    original=ast.parse((REPO/'.agent_control/c4/c4c-frozen-terminal/sources/scripts/run_c4c.py').read_text(encoding='utf-8'))
    function=next(n for n in original.body if isinstance(n,ast.FunctionDef) and n.name=='browser_lock')
    namespace={'contextmanager':contextmanager,'REPO':root,'time':time}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'original-frozen-browser-lock','exec'),namespace)
    old_failed=False
    try:
        with namespace['browser_lock']():pass
    except PermissionError:old_failed=True
    assert old_failed,'Expected the actual old byte-read failure'
    prior=run_c4c.REPO;run_c4c.REPO=root
    def release():child.stdin.write('\n');child.stdin.flush()
    timer=threading.Timer(.4,release);timer.start();started=time.monotonic()
    try:
        with run_c4c.browser_lock():elapsed=time.monotonic()-started
    finally:
        run_c4c.REPO=prior;timer.join();child.wait(timeout=10)
    assert elapsed>=.3 and lock.read_bytes()==b'0'
    output=c4c_quality._process("import sys\nprint('Actual UTF-8 é output')\nprint('Actual é failure',file=sys.stderr)\nraise SystemExit(7)",root)
    assert output['exitCode']==7 and not output['passed'] and 'é output' in output['stdout'] and 'é failure' in output['stderr']
    receipt={'passed':True,'scope':'Actual separate Windows processes, file locks and system-Python exit7; no model/native/window calls',
             'oldReadRefused':old_failed,'newLockWaitSeconds':elapsed,'lockBytesPreserved':True,'utf8FailedCommand':output}
    (REPO/'scripts/evidence/C4c-transport.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':main()
