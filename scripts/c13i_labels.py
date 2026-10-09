"""Export all used Paul records and real retention decisions without training."""
from pathlib import Path
import json
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.taste_fewshot import STATE,save
from grant_agent.taste_episode_export import episode,append,retention,destinations

def collect():
    read=lambda p:json.loads(Path(p).read_bytes())
    records=[]
    personal=read(STATE/'personal.json')['records']
    for row in personal:
        records.append(episode(row.get('pairId',row['id']),[s['path'] for s in row['images']],
            {'kind':row['labelKind'],'value':row['label'],'reason':row['reason'],'aspects':row['aspects']},
            'personal',{'path':row['source'],'recordId':row['id'],'group':row['group']}))
    cases=[r for r in read(STATE/'real-pairs.json')['cases'] if r['kind']=='repair']
    for row in cases:
        records.append(episode(row['group']+'/'+row['id'],[s['path'] for s in row['images']],
            {'kind':row['labelKind'],'keep':row['expected'],'criticKeep':row.get('criticExpected'),
             'reason':row['reason'],'aspects':row['aspects']},'corrective',row['source']))
    workflow=0
    for arm in ['fusion-v2','sol-alone','luna-alone']:
        for task in ['T1','T2']:
            path=REPO/'proof/r12'/arm/task/'history.json'
            if path.exists():
                for row in read(path):records.append(retention(row,arm,task));workflow+=1
    verifiers=[]
    for path in (REPO/'proof/r12/diagnostics').glob('*alternate*.json'):
        case=read(path)
        if 'destinations' in case:verifiers.extend(destinations(case))
    verifiers=list({r['episodeId']:r for r in verifiers}.values())
    records+=verifiers
    return records,{'personal':len(personal),'historicalRetention':len(cases),'workflowRetention':workflow,'alternateVerifier':len(verifiers),
        'reasonOnlyPersonal':sum(not r['images'] for r in personal)}

def main():
    records,counts=collect();receipt=append(records)
    receipt|={'schema':'neyvia.c13i.label-export.v1','counts':counts,
        'episodeIds':[r['episodeId'] for r in records],
        'limits':['Author identity is labelled identity, never a quality preference.',
                  'Reason-only historical records have a null screenshotPath; no missing image is invented.',
                  'Wrapper-retained repairs are weak workflow labels, not independent human taste judgments.',
                  'This proves export for ingestion; the separately built episode store is not invoked or promoted here.']}
    save(REPO/'proof/r12/label-export.json',receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k not in {'episodeIds','limits'}}))

if __name__=='__main__':main()
