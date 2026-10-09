"""Real Luna continuation under a small host budget, with independent R4 checks."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO / 'src'))
from grant_agent.cl.efficient_runner import run
from c4_quality import prepare,check

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--budget',type=int,default=2400)
    parser.add_argument('--max-turns',type=int,default=20)
    parser.add_argument('--task',choices=['bugfix','source-inspection'],default='bugfix')
    args=parser.parse_args()
    if not 48731<=args.port<=48739 or Path(args.run_id).name!=args.run_id or args.run_id in {'.','..'}:
        raise ValueError('Explicit owned port and fresh folder name required')
    directory=REPO / '.agent_control/c4' / args.run_id
    directory.mkdir(parents=True,exist_ok=False)
    root=directory / 'workspace'
    root.mkdir()
    if args.task=='bugfix':
        prepare('t2-bugfix',root)
        tasks=json.loads(Path('C:/Users/user/Projects/nx-r4-blind/proof/r4-blind-20261004/tasks.json').read_text(encoding='utf-8'))
        task=next(row['task'] for row in tasks if row['id']=='t2-bugfix')
        task+='\nThe host runs the requested regression checks and independent semantic acceptance at done(). Use the reported failure feedback to repair any defect. Host history is paged with context.read; state fields are paged with project.'
        layers,artifact=['workspace','terminal'],'answer.md'
        acceptance=lambda current:check('t2-bugfix',current)
    else:
        source=(REPO / 'src/grant_agent/cl/host.py').read_bytes()
        (root / 'host-source.py').write_bytes(source)
        task=('Inspect the actual CL host source in host-source.py. Your FIRST proposal must be exactly one '
              'workspace.read(path="host-source.py",maxChars=100000) call, alone, before writing anything. '
              'After observing it, use bounded source searches or projections to find the project action. '
              'The action is dispatched in _execute_one by action.name, rather than a method named project; '
              'search for the dispatch or its project-requires error message and inspect that bounded range. '
              'Write answer.json with exactly four fields: minStart, minCount, maxCount, staleRefsRefused. '
              'Use the actual accepted page bounds and say whether project applies the live-reference guard. '
              'Read back the JSON and finish. Do not run or modify the source file.')
        layers,artifact=['workspace'],'answer.json'
        def acceptance(current):
            try: actual=json.loads((current / artifact).read_text(encoding='utf-8'))
            except (OSError,ValueError): actual=None
            expected={'minStart':0,'minCount':1,'maxCount':4000,'staleRefsRefused':True}
            return {'passed':actual==expected and (current / 'host-source.py').read_bytes()==source,
                    'expected':expected,'actual':actual,'inputSha256':hashlib.sha256(source).hexdigest()}
    result=run(task,root,directory / 'run',layers=layers,port=args.port,
               token_budget=args.budget,max_turns=args.max_turns,goals=[f'len(workspace.read(path="{artifact}")["content"]) > 0'],
               quality_check=acceptance)
    quality=acceptance(root)
    accepted=result['passed'] and quality['passed'] and result['contextMetrics']['compactions']>0
    receipt={'passed':accepted,'run':result,'quality':quality,'budget':args.budget,'task':args.task,
             'scope':'Actual exact Luna route and production gateway; compaction must occur and task acceptance must pass',
             'sourceSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    output=REPO / 'scripts/evidence/C4b-compaction.json'
    output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    archive=REPO / 'scripts/evidence/C4b' / (args.run_id+'.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(directory.rglob('*')):
            if path.is_file() and not any(part in {'.agent_control','.neyvia','__pycache__'} for part in path.relative_to(directory).parts):
                bundle.write(path,path.relative_to(directory).as_posix())
    print(json.dumps({'passed':accepted,'completion':result['completion']['status'],'contextMetrics':result['contextMetrics'],
                      'tokens':result['tokens'],'failure':result['failure'],'archiveBytes':archive.stat().st_size}),flush=True)
    return 0 if accepted else 1

if __name__=='__main__':raise SystemExit(main())
