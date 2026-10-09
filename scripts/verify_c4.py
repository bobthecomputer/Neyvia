"""Fresh R4 runs and independent artifacts; never reads the blind answer key."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import subprocess
from contextlib import contextmanager

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.efficient_runner import run
from c4_quality import prepare, check

R4 = Path('C:/Users/user/Projects/nx-r4-blind/proof/r4-blind-20261004')
PRICES = json.loads((REPO / 'config/scroll-study-prices.json').read_text(encoding='utf-8'))['gpt-6-luna']

def cost(tokens):
    return (tokens['uncachedInput']*PRICES['input'] + tokens['cachedInput']*PRICES['cached']
            + tokens['output']*PRICES['output']) / 1e6

@contextmanager
def native_lock(enabled):
    if not enabled:
        yield
        return
    import msvcrt
    lock=REPO / '.agent_control/c4/native-task.lock'
    with lock.open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1): stream.write(b'0'); stream.flush()
        while True:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                break
            except OSError: time.sleep(.2)
        try: yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', required=True)
    parser.add_argument('--arm', choices=['efficient','control'], default='efficient')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--ui-port', type=int, required=True)
    parser.add_argument('--max-turns', type=int, default=12)
    args = parser.parse_args()
    if any(not 48731 <= port <= 48739 for port in (args.port,args.ui_port)) or args.port == args.ui_port:
        raise ValueError('Distinct explicit owned C4b ports required')
    if not args.run_id or Path(args.run_id).name != args.run_id or args.run_id in {'.','..'}:
        raise ValueError('run-id must be one folder name')
    tasks = json.loads((R4 / 'tasks.json').read_text(encoding='utf-8'))
    task = next(row for row in tasks if row['id']==args.task)
    execution_task = task['task']
    if task['id']=='t3-notes':
        execution_task += ('\nnotes.write-and-pin reviews an existing note and cannot create the missing note. '
                           'For creation use notes.write(path="Weekend plan.md",body=...), then notes.pin(path="Weekend plan.md",pinned=true). '
                           'The caller already supplies final acceptance goals. Do not add intermediate body equality goals that the later append intentionally changes. '
                           'Read back before appending; the host supplies the current modification stamp. Finish with the final readback and done().')
    def acceptance(root):
        if task['id'] in {'t1-ui','t4-browse'}:
            from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
            destination=directory / 'external-quality'
            if task['id']=='t1-ui':
                relative=root.relative_to(REPO / '.agent_control/c4').as_posix()
                command=['node',str(REPO / 'scripts/verify_c4_ui.cjs'),
                         f'http://127.0.0.1:{args.ui_port}/{relative}/index.html',str(destination)]
            else:
                command=[sys.executable,str(REPO / 'scripts/verify_c4_browse.py'),str(root / 'versions.md'),str(destination)]
            done=subprocess.run(command,cwd=REPO,capture_output=True,text=True,encoding='utf-8',timeout=120,
                                **hidden_windows_subprocess_kwargs())
            path=destination / 'receipt.json'
            value=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'passed':False,'error':done.stderr[-2000:]}
            # Full verifier receipts stay on disk; the repair loop needs a bounded verdict.
            return {'task':task['id'],'passed':value['passed'],'checks':value.get('checks',
                    [row['checks'] for row in value.get('rows',[])]),'receipt':str(path),
                    'error':value.get('error')}
        return check(task['id'],root)
    if task['id']=='t2-bugfix':
        execution_task += ('\nThe host runs the exact requested unittest command and independent semantic checks at done(). '
                           'Add the regression tests and summary, then call done and repair any reported failures. '
                           'You do not need to propose a redundant terminal test command.')
    directory = REPO / '.agent_control/c4' / args.run_id / args.arm / task['id']
    if directory.exists(): raise ValueError('Select a fresh run-id; retained attempts are immutable')
    root = directory / 'workspace'
    root.mkdir(parents=True)
    preparation = prepare(task['id'],root)
    layers = ['workspace']
    if task['id']=='t2-bugfix': layers += ['terminal']
    if task['id']=='t3-notes': layers += ['notes']
    if task['id']=='t4-browse': layers += ['web']
    if task['id']=='t5-cua': layers += ['cua']
    artifact = {'t1-ui':'index.html','t2-bugfix':'answer.md','t3-notes':'answer.md',
                't4-browse':'versions.md','t5-cua':'answer.md','t6-study':'pack.md',
                't7-explain':'answer.md','t8-plan':'plan.md'}[task['id']]
    goals = [f"len(workspace.read(path={json.dumps(artifact)})['content']) > 0"]
    if task['id']=='t3-notes':
        goals += ['notes.read(path="Weekend plan.md")["pinned"] == true',
                  'notes.read(path="Ideas.md")["pinned"] == true',
                  '"Call grandma Sunday 11:00" in notes.read(path="Weekend plan.md")["body"]']
    try:
        with native_lock(task['id']=='t5-cua'):
            result = run(execution_task,root,directory / 'run',layers=layers,port=args.port,
                         efficient=args.arm=='efficient',max_turns=args.max_turns,allow_native=task['id']=='t5-cua', goals=goals,
                         quality_check=acceptance if task['id']!='t5-cua' else None)
    except Exception as exc:
        from grant_agent.autopilot_model import _sanitize
        result={'passed':False,'tokens':dict(input=0,cachedInput=0,uncachedInput=0,output=0,total=0),
                'elapsedSeconds':0,'failure':_sanitize(f'{type(exc).__name__}: {exc}'),
                'providerCalled':False,'turns':[],'actions':[]}
    quality = acceptance(root) if task['id'] in {'t1-ui','t4-browse'} and result['passed'] else check(task['id'],root)
    receipt = {'task':task['id'],'arm':args.arm,'taskSha256':hashlib.sha256(task['task'].encode()).hexdigest(),
               'preparation':preparation, 'quality':quality, 'run':result,
               'costUsd':cost(result['tokens']),
               'costBasis':'Recorded R4 list-price equivalent; Codex subscription, not invoice',
               'pricesUsdPerMillion':PRICES}
    (directory / 'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'task':task['id'],'arm':args.arm,'hostDone':result['passed'],
                      'quality':quality,'tokens':result['tokens'],'costUsd':receipt['costUsd'],
                      'seconds':result['elapsedSeconds'],'failure':result['failure']},ensure_ascii=False),flush=True)
    return 0 if result['passed'] and quality['passed'] else 1

if __name__=='__main__': raise SystemExit(main())
