"""Frozen paired 18-task C4 ablation; no keys, native launches or public state."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from contextlib import contextmanager

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.efficient_runner import run
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
import c4_quality as r4
import c4c_quality as r5

R5 = Path('C:/Users/user/Projects/nx-c5-noslop/proof/r5-blind')
PRICES = json.loads((REPO / 'config/scroll-study-prices.json').read_text(encoding='utf-8'))['gpt-6-luna']
ARTIFACTS = {'t1-ui':['index.html'], 't2-bugfix':['answer.md'], 't3-notes':['answer.md'],
             't4-browse':['versions.md'], 't5-cua':['answer.md'], 't6-study':['pack.md'],
             't7-explain':['answer.md'], 't8-plan':['plan.md']}

def tasks():
    return [dict(row, round=1) for row in json.loads((r4.R4 / 'tasks.json').read_text(encoding='utf-8'))] + [
        dict(row, round=2) for row in json.loads((R5 / 'tasks.json').read_text(encoding='utf-8'))]

def cost(tokens):
    return (tokens.get('uncachedInput',0)*PRICES['input'] + tokens.get('cachedInput',0)*PRICES['cached'] +
            tokens.get('output',0)*PRICES['output']) / 1e6

@contextmanager
def browser_lock():
    import msvcrt
    path=REPO/'.agent_control/c4c-browser.lock'
    with path.open('a+b') as stream:
        stream.seek(0)
        if path.stat().st_size == 0: stream.write(b'0');stream.flush()
        while True:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                break
            except OSError: time.sleep(.2)
        try: yield
        finally:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def frozen(run_id):
    base = REPO / '.agent_control/c4' / run_id
    base.mkdir(parents=True, exist_ok=True)
    manifest = base / 'frozen.json'
    if not manifest.exists():
        source = [REPO / 'src/grant_agent/cl' / name for name in
                  ('efficient_runner.py','turn_context.py','host.py','benchmark_provider.py','protocol.py','parser.py',
                   'integration.py','terminal_receipts.py')]
        source += [Path(__file__), REPO / 'scripts/c4_quality.py', REPO / 'scripts/c4c_quality.py']
        source += [REPO/'scripts/c4c_browser.py',REPO/'config/c4c-rubric.json']
        for path in source:
            target=base/'sources'/path.relative_to(REPO)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(path.read_bytes())
        data = {'tasks':tasks(), 'repetitions':2, 'model':'gpt-6-luna', 'effort':'medium',
                'pricesUsdPerMillion':PRICES, 'seed':41729,
                'sourceSha256':{p.relative_to(REPO).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in source},
                'policy':{'native':'waiting for C11 agent desktop; zero calls', 'keys':'never opened',
                          'arms':'all five mechanisms enabled vs disabled; identical checks and turn limit',
                          'quality':'objective constraints/scorers plus frozen blinded judge; subjective validity separately disclosed',
                          'providerUsage':'actual events, list-price equivalent only; not invoice'}}
        manifest.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return base, json.loads(manifest.read_text(encoding='utf-8'))

def job(args):
    base, freeze = frozen(args.run_id)
    if (base/'cancel-queued').exists():
        print('Queued attempt cancelled before model/fixture action',flush=True)
        return 0
    task = next(t for t in freeze['tasks'] if t['id'] == args.task)
    directory = base / f'rep-{args.rep}' / args.arm / task['id']
    if (directory / 'result.json').exists():
        print(json.dumps({'retained':str(directory)}), flush=True)
        return 0
    if directory.exists():
        raise FileExistsError('Interrupted attempt retained; use a fresh run-id')
    directory.mkdir(parents=True)
    if task['id'] == 't5-cua':
        receipt = {'task':task['id'],'round':task['round'],'repetition':args.rep,'arm':args.arm,
                   'status':'waiting','reason':'C11 agent desktop required; no native/model call',
                   'run':{'passed':False,'tokens':{},'turns':[]},'costUsd':0,
                   'quality':{'passed':False,'scope':'unattempted native journey'}}
    else:
        root = directory / 'workspace'
        root.mkdir()
        checker = r4 if task['round']==1 else r5
        preparation = checker.prepare(task['id'], root)
        text = task['task']
        if task['id']=='t2-bugfix':
            text += '\nHost runs the requested regression workload and independent semantics at done(); repair its failure feedback.'
        if task['id']=='t3-notes':
            text += '\nCreate with notes.write, then notes.pin; notes.write-and-pin cannot create a missing note.'
        if task['id'] in r5.CODE:
            text += '\nHost-measured original baseline: ' + json.dumps(preparation['baseline']['metrics'])
            text += '\nKeep scorer/input files unchanged. Run the supplied workload with terminal.exec; iterate and record measured changes.'
        artifacts = task.get('files') or ARTIFACTS[task['id']]
        goals = [f'len(workspace.read(path={json.dumps(path)})["content"]) > 0' for path in artifacts]
        if task['id']=='t3-notes':
            goals += ['notes.read(path="Weekend plan.md")["pinned"] == true',
                      'notes.read(path="Ideas.md")["pinned"] == true',
                      '"Call grandma Sunday 11:00" in notes.read(path="Weekend plan.md")["body"]']
        layers = ['workspace']
        if task['id'] in r5.CODE or task['id']=='t2-bugfix': layers += ['terminal']
        if task['id']=='t3-notes': layers += ['notes']
        if task['id']=='t4-browse': layers += ['web']
        # terminal is a separate scoped layer even though its manual belongs to workspace.
        quality_number=0
        def acceptance(current):
            nonlocal quality_number
            quality_number+=1
            if task['id'] in {'t1-ui','ui1-run-card','ui2-cost-settings','t4-browse'}:
                import c4c_browser
                with browser_lock():
                    destination=directory/f'quality-{quality_number:02d}'
                    if task['id']=='t4-browse':
                        value=c4c_browser.browse(current/'versions.md',destination,48737)
                    else:
                        value=c4c_browser.check(task['id'],current,destination,48737)
                if task['round']==2:
                    structural=checker.check(task['id'],current)
                    value['checks'].update({'artifact_'+k:v for k,v in structural['checks'].items()})
                    value['passed']=value['passed'] and structural['passed']
                return {'passed':value['passed'],'checks':value.get('checks',{}),
                        'limits':value.get('limits',[]),'receipt':str(destination/'receipt.json'),
                        'blocker':value.get('blocker')}
            return checker.check(task['id'],current)
        result = None
        try:
            result = run(text,root,directory/'run',layers=layers,port=args.port,
                         token_budget=args.budget,max_turns=args.max_turns,
                         efficient=args.arm=='efficient', ablate_all=args.arm=='control',
                         goals=goals,quality_check=acceptance)
            quality = acceptance(root)
        except Exception as exc:
            from grant_agent.autopilot_model import _sanitize
            saved = directory/'run/receipt.json'
            if result is None and saved.is_file():
                result = json.loads(saved.read_text(encoding='utf-8'))
            if result is None:
                result = {'passed':False,'tokens':{},'turns':[], 'failure':_sanitize(str(exc))}
            result = {**result, 'collectorFailure':_sanitize(str(exc))}
            quality = {'passed':False,'error':_sanitize(str(exc))}
        receipt = {'task':task['id'],'round':task['round'],'repetition':args.rep,'arm':args.arm,
                   'taskSha256':hashlib.sha256(task['task'].encode()).hexdigest(), 'status':'attempted',
                   'preparation':preparation,'run':result,'quality':quality,'costUsd':cost(result['tokens']),
                   'costBasis':'Observed CLI usage at recorded list prices; not subscription invoice',
                   'passed':bool(result['passed'] and quality['passed'])}
    (directory/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:receipt.get(k) for k in ('task','arm','repetition','passed','status','costUsd')},ensure_ascii=False),flush=True)
    return 0

def panel(args):
    base, freeze = frozen(args.run_id)
    selected = args.tasks or [t['id'] for t in freeze['tasks']]
    slots = [(rep, task, arm) for rep in range(1,args.repetitions+1) for task in selected
             for arm in ('efficient','control')]
    random.Random(41729).shuffle(slots)  # interleave/cache order; two arms always fresh
    chunks = [slots[i::len(args.ports)] for i in range(len(args.ports))]
    log = base/'logs'; log.mkdir(exist_ok=True)
    def worker(index):
        for rep, task, arm in chunks[index]:
            cmd = [sys.executable,str(Path(__file__)), '--job','--run-id',args.run_id,'--task',task,
                   '--arm',arm,'--rep',str(rep),'--port',str(args.ports[index]),
                   '--budget',str(args.budget),'--max-turns',str(args.max_turns)]
            name=f'{rep}-{task}-{arm}'
            with (log/(name+'.out')).open('w',encoding='utf-8') as out, (log/(name+'.err')).open('w',encoding='utf-8') as err:
                done=subprocess.run(cmd,cwd=REPO,stdout=out,stderr=err,
                                    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},**hidden_windows_subprocess_kwargs())
            print(f'{name} transportExit={done.returncode}',flush=True)
    with ThreadPoolExecutor(max_workers=len(args.ports)) as pool:
        list(pool.map(worker, range(len(args.ports))))
    return 0

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-id',required=True); p.add_argument('--job',action='store_true')
    p.add_argument('--task');p.add_argument('--tasks',nargs='+')
    p.add_argument('--arm',choices=['efficient','control']);p.add_argument('--rep',type=int,default=1)
    p.add_argument('--repetitions',type=int,default=2);p.add_argument('--port',type=int)
    p.add_argument('--ports',type=int,nargs='+');p.add_argument('--budget',type=int,default=8000)
    p.add_argument('--max-turns',type=int,default=24)
    a=p.parse_args()
    ports=[a.port] if a.job else a.ports
    if not ports or len(set(ports))!=len(ports) or any(port is None or not 48731<=port<=48739 for port in ports):
        raise ValueError('Explicit distinct owned C4 ports required')
    if Path(a.run_id).name!=a.run_id or a.run_id in {'.','..'}: raise ValueError('Run-id must be one folder name')
    return job(a) if a.job else panel(a)

if __name__=='__main__': raise SystemExit(main())
