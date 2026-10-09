"""Hidden owned R12 compiled jobs, with detached capture and durable PIDs."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
RAW=Path('D:/NeyviaRuns/r12')
PYTHON=Path('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('job',choices=['calibration-crop','calibration-episodes','heldout','pixel','baseline-T1','baseline-T2',
        'fusion-T1','fusion-T2','sol-T1','sol-T2','luna-T1','luna-T2']);parser.add_argument('--rounds',type=int,default=3);parser.add_argument('--limit',type=int,default=60)
    parser.add_argument('--port',type=int);parser.add_argument('--engine-port',type=int);parser.add_argument('--stop',action='store_true')
    parser.add_argument('--replay-repair');args=parser.parse_args()
    if args.stop:
        receipt=json.loads((RAW/(args.job+'-job.json')).read_bytes())
        if receipt['cwd']!=str(REPO) or 'scripts/c13i_run.py' not in receipt['command']:
            raise ValueError('Only this task\'s page-loop process may be stopped')
        queried=subprocess.run(['powershell','-NoProfile','-Command',f"Get-CimInstance Win32_Process -Filter 'ProcessId={int(receipt['pid'])}' | Select-Object CommandLine,CreationDate | ConvertTo-Json -Compress"],
            capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        if queried.stdout.strip():
            identity=json.loads(queried.stdout)
            if 'c13i_run.py' not in identity['CommandLine'] or receipt['command'][receipt['command'].index('--task')+1] not in identity['CommandLine']:
                raise ValueError('PID no longer belongs to the recorded task')
            stopped=subprocess.run(['taskkill','/PID',str(receipt['pid']),'/T','/F'],capture_output=True,text=True,encoding='utf-8',errors='replace',**hidden_windows_subprocess_kwargs())
            receipt['stopExitCode']=stopped.returncode
        receipt['cancelledAt']=time.time();receipt['reason']='Superseded this owned page-loop job; durable source ledgers and paid receipts retained.'
        (RAW/(args.job+'-cancelled-job.json')).write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print(json.dumps({'job':args.job,'stoppedOwnedPid':receipt['pid'],'reason':receipt['reason']}));return
    if args.job=='calibration-crop':command=['scripts/c13i_calibrate.py','--phase','calibration','--episodes','--kind','crop','--limit',str(args.limit)]
    elif args.job=='calibration-episodes':command=['scripts/c13i_calibrate.py','--phase','calibration','--episodes','--limit',str(args.limit)]
    elif args.job=='heldout':command=['scripts/c13i_calibrate.py','--phase','heldout','--episodes','--limit',str(args.limit)]
    elif args.job=='pixel':command=['scripts/c13i_pixel_gate.py']
    else:
        phase='baseline' if args.job.startswith('baseline') else 'loop'
        command=['scripts/c13i_run.py','--phase',phase,'--task',args.job[-2:]]
        if phase=='loop':
            command+=['--arm','fusion-v2' if args.job.startswith('fusion') else 'luna-alone' if args.job.startswith('luna') else 'sol-alone','--rounds',str(args.rounds)]
        if bool(args.port)!=bool(args.engine_port):raise ValueError('Supply both assigned ports together')
        web_port=args.port or (48805 if args.job.startswith('fusion') else 48801)
        engine_port=args.engine_port or (48806 if args.job.startswith('fusion') else 48802)
        if web_port not in range(48801,48810) or engine_port not in range(48801,48810) or web_port==engine_port:
            raise ValueError('Two distinct C13 ports required')
        command+=['--port',str(web_port),'--engine-port',str(engine_port)]
        if args.replay_repair:command+=['--replay-repair',args.replay_repair]
    RAW.mkdir(parents=True,exist_ok=True)
    # Logs from earlier invocations are never overwritten.
    stem=args.job+'-'+str(time.time_ns())
    with (RAW/(stem+'.log')).open('wb') as stdout,(RAW/(stem+'.err')).open('wb') as stderr:
        process=subprocess.Popen([str(PYTHON),*command],cwd=REPO,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
             close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    receipt={'pid':process.pid,'job':args.job,'command':command,'cwd':str(REPO),'visible':False,'startedAt':time.time(),
             'stdout':str(RAW/(stem+'.log')),'stderr':str(RAW/(stem+'.err')),'completion':'pending; inspect output receipts'}
    (RAW/(args.job+'-job.json')).write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':main()
