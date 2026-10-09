"""Measure held-out surface episodes without changing labels or admission thresholds."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.laya_instant import store,latest_episodes,input_key
from grant_agent.laya_glance import DOMAIN

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    local=store(str(args.root));local.refresh()
    rows=[r for r in latest_episodes(local.rows) if r['domain']==DOMAIN]
    # A build directory named build-after contains app icons, not screenshots.
    excluded=[]
    for row in rows:
        if row['source'].startswith('LAYAG:after:'):
            parts=row['source'].split('LAYAG:after:',1)[1].replace(chr(92),'/').split('/')
            top=parts[1] if len(parts)>1 else ''
            if not (top.startswith('after-') or top in {'after','img-after'}):
                excluded.append(row['source'])
    for source in excluded:local.forget(source)
    local.refresh()
    rows=[r for r in latest_episodes(local.rows) if r['domain']==DOMAIN]
    # Upgrade this task's initial volatile references to immutable local bytes.
    # Changed negatives are corrected explicitly; stable rows retain their vectors.
    import hashlib
    from grant_agent.laya_glance import learn
    migrated=corrected=0
    stable=[]
    for row in rows:
        old=Path(row['input']['image'])
        if old.parent.name=='glance-images':continue
        raw=old.read_bytes()
        frozen=args.root/'.neyvia/laya/glance-images'/(hashlib.sha256(raw).hexdigest()+'.png')
        frozen.parent.mkdir(parents=True,exist_ok=True)
        if not frozen.exists():frozen.write_bytes(raw)
        new_input={'image':str(frozen.resolve())}
        if input_key(new_input)!=row['key']:
            local.forget(row['source'])
            learn(args.root,str(frozen),row['label'],row['evidence']['reason'],row['source'],
                  surface=row['evidence']['surface'],split=row['split'])
            corrected+=1
        else:
            stable.append({**{k:v for k,v in row.items() if k not in {'id','_vectorKey','_nonzero'}},
                           'input':new_input,'evidence':{**row['evidence'],'sourceScreenshot':str(old)}})
            migrated+=1
    if stable:
        with local.import_batch():
            for row in stable:local.append(row)
    local.refresh()
    rows=[r for r in latest_episodes(local.rows) if r['domain']==DOMAIN]
    # Union whole surfaces sharing identical pixels before evaluating any answer.
    # This is split repair, never a label change or threshold adjustment.
    import hashlib
    parent={r['evidence']['surface']:r['evidence']['surface'] for r in rows}
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]]
            x=parent[x]
        return x
    pixel_groups={}
    drift=[r['source'] for r in rows if input_key(r['input'])!=r['key']]
    if drift:
        raise ValueError('Screenshot bytes changed since episode write: '+str(drift[:5]))
    for row in rows:
        key=hashlib.sha256(Path(row['input']['image']).read_bytes()).hexdigest()
        group=row['evidence']['surface']
        if key in pixel_groups:
            roots=sorted([find(group),find(pixel_groups[key])])
            parent[roots[1]]=roots[0]
        pixel_groups[key]=group
    changed=0
    with local.import_batch():
        for row in rows:
            partition='holdout' if int(hashlib.sha256(find(row['evidence']['surface']).encode()).hexdigest()[:8],16)%4==0 else 'train'
            if row['split']!=partition:
                local.learn(DOMAIN,row['input'],row['label'],row['source'],evidence=row['evidence'],split=partition)
                changed+=1
    local.refresh()
    rows=[r for r in latest_episodes(local.rows) if r['domain']==DOMAIN]
    train=[r for r in rows if r['split']!='holdout']
    held=[r for r in rows if r['split']=='holdout']
    train_surfaces={r['evidence'].get('surface') for r in train}
    held_surfaces={r['evidence'].get('surface') for r in held}
    # Pixel identity, not filename, guards accidental duplicate-image leakage.
    import hashlib
    pixels=lambda r:hashlib.sha256(Path(r['input']['image']).read_bytes()).hexdigest()
    overlap={pixels(r) for r in train}&{pixels(r) for r in held}
    if overlap or train_surfaces&held_surfaces:
        raise ValueError('Heldout leakage; do not publish accuracy')
    cases=[]
    seen=set()
    for row in held:
        key=(pixels(row),row['label'])
        if key in seen:continue
        seen.add(key)
        started=time.perf_counter()
        result=local.query(DOMAIN,row['input'],labels=['broken','fine'])
        elapsed=(time.perf_counter()-started)*1000
        cases.append({'surface':row['evidence']['surface'],'image':row['input']['image'],'expected':row['label'],
                      'answer':result['answer'],'admitted':not result['escalate'],'ms':elapsed,
                      'reason':result.get('reason'),'confidenceKind':result.get('confidenceKind')})
    answered=[c for c in cases if c['admitted']]
    latency=sorted(c['ms'] for c in cases)
    metrics={'excludedNonScreenshotAssets':len(excluded),'episodes':len(rows),'heldoutScreenshots':len(cases),'heldoutSurfaces':sorted(held_surfaces),
             'classCounts':dict(Counter(c['expected'] for c in cases)),
             'accuracy':sum(c['answer']==c['expected'] for c in answered)/len(answered) if answered else None,
             'answerRate':len(answered)/len(cases) if cases else 0,
             'correctOverAll':sum(c['answer']==c['expected'] for c in cases)/len(cases) if cases else 0,
             'latencyMs':{'median':statistics.median(latency) if latency else None,'p95':latency[min(len(latency)-1,int(.95*len(latency)))] if latency else None},
             'frozenReferences':migrated,'changedNegativesCorrected':corrected,'splitMetadataCorrections':changed,'pixelLeakage':False,'surfaceLeakage':False,'training':'none; episode writes and frozen CLIP only',
             'claim':'Label-conditioned screenshot retrieval, not a scene-predicate precision/recall estimate',
             'cases':cases}
    metrics['gate']=bool(metrics['accuracy'] is not None and metrics['accuracy']>=.95 and metrics['answerRate']>=.95)
    (ROOT/'scripts/evidence/LAYAG-heldout.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in metrics.items() if k!='cases'}))

if __name__=='__main__':main()
