"""Compile and run only the authored R12 Connected Language contracts."""
from pathlib import Path
import json
import re
import subprocess
import sys
REPO=Path(__file__).resolve().parents[1]
MANUAL=REPO/'manuals/cl/taste.cl'


def main():
    out=REPO/'proof/r12/contracts-final'
    names=re.findall(r'^C\s+\S+\s+(r12-[\w-]+):',MANUAL.read_text(encoding='utf-8'),re.M)
    compile_call=subprocess.run([sys.executable,str(REPO/'scripts/cl_compile_manuals.py'),
        '--source-file',str(MANUAL),'--check','--receipt',str(REPO/'proof/r12/compile-final.json')],cwd=REPO)
    if compile_call.returncode:return compile_call.returncode
    call=subprocess.run([sys.executable,str(REPO/'scripts/c13_contracts.py'),'--check','--manual',str(MANUAL),
        '--out',str(out),'--only',','.join(names)],cwd=REPO,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    if call.returncode:
        print(call.stdout[-10000:]);print(call.stderr[-3000:]);return call.returncode
    receipt=json.loads((out/'report.json').read_bytes())
    print(json.dumps({'status':receipt['status'],'checks':len(names),'receipt':str(out/'report.json'),
                      'manualSha256':receipt['manualSha256']}))
    return 0


if __name__=='__main__':raise SystemExit(main())
