"""Publish bounded evidence summaries from actual receipts; no evaluation rerun."""
import json
from pathlib import Path
import sys
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.laya_instant import store,latest_episodes
E=ROOT/'scripts/evidence'
read=lambda name:json.loads((E/name).read_text(encoding='utf-8'))
write=lambda name,value:(E/name).write_text(json.dumps(value,indent=2),encoding='utf-8')
dom=read('LAYAG-dom-contracts.json')
counts={}
for c in dom['cases']:
    bucket=counts.setdefault(c['type'],Counter())
    bucket[('T' if c['detected']==c['expected'] else 'F')+('P' if c['detected'] else 'N')]+=1
per={k:{**v,'precision':v['TP']/(v['TP']+v['FP']) if v['TP']+v['FP'] else None,'recall':v['TP']/(v['TP']+v['FN']) if v['TP']+v['FN'] else None} for k,v in counts.items()}
write('LAYAG-per-type.json',{'boundary':'Focused target predicates on 72 controlled real DOM/canvas cases; NOT product screenshot precision/recall','perType':per,'productPerType':None,'reason':'Review findings have representative screenshots, not exhaustive node/type ground truth'})
local=store(str(ROOT));local.refresh()
rows=[r for r in latest_episodes(local.rows) if r['domain']=='ui-glance']
write('LAYAG-ingest.json',{'activeEpisodes':len(rows),'findings':sum(r['source'].startswith('LAYAG:part-') for r in rows),'after':sum(r['source'].startswith('LAYAG:after:') for r in rows),'claimedFindings':213,'parsedDetailedFindings':194,'discrepancy':'194 detailed P1/P2/P3 bullets; top-ten summaries repeat findings. No invented 19 examples.','training':'none','storage':'.neyvia/laya/instant.sqlite and content-addressed glance-images','historicalCorrection':'32 build assets tombstoned; five changed after images corrected; stable screenshot bytes frozen'})
write('LAYAG-corpus.json',{'boundary':'Active episode manifest after excluding build assets and freezing pixels','episodes':[{'source':r['source'],'label':r['label'],'input':r['input'],'evidence':r['evidence'],'split':r['split']} for r in rows]})
held=read('LAYAG-heldout.json'); live=read('LAYAG-live.json'); cl=read('LAYAG-cl-contracts.json')
summary={'heldout':{k:v for k,v in held.items() if k!='cases'},'dom':{k:v for k,v in dom.items() if k!='cases'},'cl':{k:v for k,v in cl.items() if k!='receipts'},'sdk':read('LAYAG-sdk.json'),'live':{'errors':live['errors'],'observations':[{'surface':r['surface'],'ms':r['transcribeAndJudgeMs'],'bugs':len(r['verdict']['findings'])} for r in live['observations']]}}
print(json.dumps(summary,default=str))
