"""Restore only the isolated frozen CPU service used by R12; no watchdog."""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import time
REPO=Path(__file__).resolve().parents[1]
RAW=Path('D:/NeyviaRuns/r12/laya-service')

def main():
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',48809))==0:
            raise ValueError('Port 48809 is occupied; do not adopt or stop it')
    model=Path.home()/'Documents/Codex/2026-09-20/laya-c-est-l-alternative-open/work/models/laya-english'
    if not (model/'model.safetensors').is_file():raise ValueError('Existing model unavailable; no download')
    RAW.mkdir(parents=True,exist_ok=True)
    # Reuse installed pure-Python packages from the earlier compatible runtime.
    # Binary dependencies still come from system Python 3.13; nothing is installed.
    compat=RAW/'compat-links';compat.mkdir(exist_ok=True)
    installed=Path.home()/'miniforge3/envs/whisper/Lib/site-packages'
    for package in ['transformers','huggingface_hub']:
        targets=[installed/package,*installed.glob(package.replace('_','-')+'-*.dist-info'),*installed.glob(package+'-*.dist-info')]
        for target in dict.fromkeys(targets):
            destination=compat/target.name
            if not destination.exists():
                subprocess.run(['powershell','-NoProfile','-Command',
                    f"New-Item -ItemType Junction -Path '{destination}' -Target '{target}' | Out-Null"],
                    check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    env=os.environ|{'PYTHONPATH':str(REPO/'tools/laya')+os.pathsep+str(compat),'LAYA_SOURCE':str(REPO/'tools/laya'),
        'LAYA_CPU_THREADS':'4','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','USE_TF':'0','PYTHONDONTWRITEBYTECODE':'1'}
    command=[sys.executable,'-m','laya_system1.service','--model',str(model),'--device','cpu','--port','48809',
        '--database',str(RAW/'isolated.sqlite'),'--question-sets',str(REPO/'tools/laya/question_sets'),
        '--calibration',str(REPO/'tools/laya/calibration-base.json'),'--max-len','512']
    with (RAW/'stdout.log').open('ab') as out,(RAW/'stderr.log').open('ab') as err:
        p=subprocess.Popen(command,cwd=REPO/'tools/laya',env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
            close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    receipt={'pid':p.pid,'command':command,'cwd':str(REPO/'tools/laya'),'startedAt':time.time(),
             'visible':False,'device':'cpu','scope':'R12 isolated frozen inference; no training or promotion'}
    (RAW/'job.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt))
if __name__=='__main__':main()
