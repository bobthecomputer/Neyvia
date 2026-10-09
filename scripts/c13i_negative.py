"""Exercise failure and abstention routes using recorded real-page cases."""
from pathlib import Path
import json
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.taste_fewshot import STATE, gate, save, digest


def main():
    corpus=json.loads((STATE/'real-pairs.json').read_bytes())['cases']
    bad=next(r for r in corpus if r['split']=='heldout' and r['kind']=='repair'
             and not r['expected'] and r['facts'].get('newBlockingChecks'))
    unknown=next(r for r in corpus if r['kind']=='repair' and not r.get('supported',False))
    rows=[]
    for name,row in [('measured-regression',bad),('missing-observations',unknown)]:
        destination=REPO/'proof/r12/negative'/('decision-'+name+'.json')
        prediction=json.loads(destination.read_bytes()) if destination.exists() else gate(
            'repair',row['facts'],images=[s['path'] for s in row['images'][:1]],
            group=row['group'],output=destination)
        rows.append({'caseId':row['id'],'caseSha256':digest(row),'group':row['group'],
                     'scenario':name,'source':row['source'],'facts':row['facts'],'prediction':prediction})
    save(REPO/'proof/r12/negative/real-routes.json',rows)
    print(json.dumps([{'scenario':r['scenario'],'route':r['prediction']['route'],
                       'answer':r['prediction']['answer']} for r in rows]))


if __name__=='__main__':main()
