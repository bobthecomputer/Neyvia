"""Bounded two-worker cohort; subprocesses isolate environment and notes roots."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run-id',required=True)
    p.add_argument('--tasks',nargs='+',required=True)
    p.add_argument('--arms',nargs='+',choices=['efficient','control'],default=['efficient','control'])
    p.add_argument('--ports', nargs=2, type=int, required=True)
    p.add_argument('--ui-port', type=int, required=True)
    args=p.parse_args()
    if len(set(args.ports + [args.ui_port])) != 3 or any(not 48731 <= port <= 48739 for port in args.ports + [args.ui_port]):
        raise ValueError('Three distinct explicit owned C4b ports required')
    if not args.run_id or Path(args.run_id).name != args.run_id or args.run_id in {'.','..'}:
        raise ValueError('run-id must be one folder name')
    log=REPO / '.agent_control/c4' / args.run_id / 'cohort-logs'
    log.mkdir(parents=True,exist_ok=True)
    def job(slot):
        task,arm,ordinal=slot
        command=[sys.executable,str(REPO / 'scripts/verify_c4.py'),'--task',task,'--arm',arm,
                 '--run-id',args.run_id,'--port',str(args.ports[ordinal%2]),'--ui-port',str(args.ui_port),'--max-turns','10']
        with (log / f'{arm}-{task}.stdout').open('w',encoding='utf-8') as out, (log / f'{arm}-{task}.stderr').open('w',encoding='utf-8') as err:
            result=subprocess.run(command,cwd=REPO,stdout=out,stderr=err,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},
                                  **hidden_windows_subprocess_kwargs())
        print(f'{task} {arm}: exit {result.returncode}',flush=True)
        return result.returncode
    slots=[(task,arm,i*len(args.arms)+j) for i,task in enumerate(args.tasks) for j,arm in enumerate(args.arms)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(job,slots))
    return 0 if all(code==0 for code in outcomes) else 1

if __name__=='__main__': raise SystemExit(main())
