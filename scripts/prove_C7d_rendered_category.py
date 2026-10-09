"""Invoke the same fresh native family for one explicit adverse category."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,required=True)
    p.add_argument('--category',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    from grant_agent.edge_contracts import CATEGORIES,inventory,matrix
    from grant_agent.edge_fixture_c7d_rendered import IDS,run_observed
    from grant_agent.edge_live_observations import LiveObservations
    if a.port not in range(48741,48750) or a.category not in CATEGORIES:p.error('Explicit assigned port/category required')
    os.environ['NEYVIA_C7_PORT']=str(a.port)
    root=REPO/'.agent_control/proofs'/('c7d-rendered-category-'+uuid.uuid4().hex)
    root.mkdir(parents=True)
    _,all_contracts=inventory()
    contracts={k:all_contracts[k] for k in IDS}
    observations=LiveObservations()
    rows=run_observed(root,contracts,(a.category,),observations)
    result=[r for r in matrix(contracts,rows,semantic_fixtures=True,proof_observer=observations) if r['category']==a.category]
    if len(result)!=len(IDS) or not all(r['status']=='passed' for r in result):raise AssertionError(result)
    target=a.output.resolve();target.relative_to(REPO)
    target.write_text(json.dumps({'schema':'neyvia.c7d-rendered-category.v1','ok':True,'category':a.category,'explicitPort':a.port,'rows':rows,'semanticCoverage':result,'rawNativeRun':str(root/(a.category+'.json')),'boundary':'Fresh production family plus current in-memory native witnesses; not a complete campaign or replayable observation'},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'ok':True,'category':a.category,'actualApplicablePassed':len(result)}))

if __name__=='__main__':main()
