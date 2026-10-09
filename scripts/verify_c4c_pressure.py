"""Real bounded bug-fix procedure; requested workloads execute at done()."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'src'))
from grant_agent.cl.efficient_runner import run
from c4_quality import prepare,check,R4
from run_c4c import cost

PROCEDURE=('Procedure: use workspace.read for the module and tests. Submit the module/test edits with '
           'replace-and-read, then create-and-read answer.md (3-5 lines). P ok +G includes exact readback; '
           'do not reread/page verified edits. Then call done() immediately: the host runs the exact requested '
           'regression workload and independent semantics. Repair only its reported failed checks. '
           'Terminal inspection is unnecessary; this scope supplies workspace tools and host acceptance.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--budget',type=int,choices=[2000,2200],required=True)
    p.add_argument('--rep',type=int,choices=[1,2],required=True);p.add_argument('--port',type=int,required=True);a=p.parse_args()
    if not 48731<=a.port<=48739:raise ValueError('Explicit owned port required')
    base=REPO/'.agent_control/c4'/f'c4c-pressure-guided-{a.budget}'/f'rep-{a.rep}'/'efficient/t2-bugfix'
    base.mkdir(parents=True,exist_ok=False);root=base/'workspace';root.mkdir()
    prep=prepare('t2-bugfix',root)
    original=next(t['task'] for t in json.loads((R4/'tasks.json').read_text()) if t['id']=='t2-bugfix')
    result=run(original+'\n'+PROCEDURE,root,base/'run',layers=['workspace'],port=a.port,
               token_budget=a.budget,max_turns=16,goals=['len(workspace.read(path="answer.md")["content"]) > 0'],
               quality_check=lambda current:check('t2-bugfix',current))
    quality=check('t2-bugfix',root)
    receipt={'task':'t2-bugfix','repetition':a.rep,'arm':'efficient','status':'attempted',
             'budget':a.budget,'passed':result['passed'] and quality['passed'],'run':result,'quality':quality,
             'preparation':prep,'procedure':PROCEDURE,'procedureSha256':hashlib.sha256(PROCEDURE.encode()).hexdigest(),
             'originalTaskSha256':hashlib.sha256(original.encode()).hexdigest(),'costUsd':cost(result['tokens']),
             'scope':'Same real bug/module/regressions/independent checks; workspace-only procedure scope, no terminal model actions'}
    (base/'result.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({'passed':receipt['passed'],'budget':a.budget,'rep':a.rep,
                      'turns':len(result['turns']),'compactions':result['contextMetrics']['compactions'],'tokens':result['tokens']}),flush=True)
if __name__=='__main__':main()
