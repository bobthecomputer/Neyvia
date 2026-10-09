"""Bounded coverage replay; retains detailed module obligations in its receipt."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.contract_gate import git, select, exact_renames

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since',required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--replay',type=Path)
    args=parser.parse_args()
    changed=json.loads(args.replay.read_text(encoding='utf-8'))['changedFiles'] if args.replay else git('diff','--name-only',args.since).splitlines()
    started=time.perf_counter(); plan=select(changed,renames=exact_renames(args.since))
    plan.pop('contracts'); plan.pop('manifests')
    plan.update(changedFiles=changed, since=args.since, durationMs=round((time.perf_counter()-started)*1000))
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    args.receipt.write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'changed':len(changed),'classes':plan['pathPolicyCounts'],
        'uncovered':len(plan['uncovered']),'uncoveredByCategory':plan['uncoveredByCategory'],
        'unbound':plan['unboundContracts'],'moduleGroups':len(plan['uncoveredByModule']),
        'largestGroups':Counter({key:len(rows) for key,rows in plan['uncoveredByModule'].items()}).most_common(15),
        'durationMs':plan['durationMs'],'receipt':str(args.receipt)}))

if __name__=='__main__': main()
