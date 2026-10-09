"""Select a head-free nearest-real-repair gate on calibration pages only."""
from pathlib import Path
import itertools
import json
import sys
import time
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent import taste_vision as vision
from grant_agent.taste_fewshot import STATE,save,similarity,routine_embedding,calibrate,digest


def vector(case):
    cache=STATE/'pair-embeddings'/ (case['id']+'.json')
    if cache.exists():return json.loads(cache.read_bytes())
    old=vision.STATE
    try:
        vision.STATE=STATE/'vision-cache'
        values=[vision.embedding(i['path']).tolist() for i in case['images'][:2]]
    finally:vision.STATE=old
    a,b=values
    delta=[y-x for x,y in zip(a,b)];norm=sum(x*x for x in delta)**.5 or 1
    result={'before':a,'after':b,'delta':[x/norm for x in delta],
            'signature':routine_embedding('repair',case['facts']),'caseSha256':digest(case),
            'modelSha256':vision.encoder_digest(((vision.ASSETS/'clip/vision.onnx').stat().st_size,(vision.ASSETS/'clip/vision.onnx').stat().st_mtime_ns))}
    save(cache,result);return result


def predict(case,training,vectors,config):
    q=vectors[case['id']];rank=[]
    for row in training:
        v=vectors[row['id']]
        distance=sum((a-b)**2 for a,b in zip(q['signature'],v['signature']))/100
        score=config['style']*similarity(q['before'],v['before'])+(1-config['style'])*similarity(q['delta'],v['delta'])-config['checkWeight']*distance
        rank.append((score,row))
    rank.sort(key=lambda r:(-r[0],r[1]['id']))
    rows=rank[:config['k']]
    weight=lambda score:__import__('math').exp(min(20,score*6))
    yes=sum(weight(score) for score,row in rows if row['expected']);no=sum(weight(score) for score,row in rows if not row['expected'])
    answer=yes>=no;confidence=max(yes,no)/(yes+no) if yes+no else 0
    return {'answer':answer,'confidence':confidence,'nearest':[{'id':r['id'],'label':r['expected'],'score':s} for s,r in rows]}


def main():
    cases=json.loads((STATE/'real-pairs.json').read_bytes())['cases']
    train=[c for c in cases if c['kind']=='repair' and c['split']=='train']
    calibration=[c for c in cases if c['kind']=='repair' and c['split']=='calibration']
    vectors={c['id']:vector(c) for c in train+calibration}
    trials=[]
    for k,style,weight in itertools.product([1,3,5,7],[0,.5,1],[0,.1,1,5]):
        config={'k':k,'style':style,'checkWeight':weight}
        for row in train:row['expected']=row.get('criticExpected',row['expected'])
        rows=[{'expected':c.get('criticExpected',c['expected']),'prediction':predict(c,train,vectors,config),'id':c['id']} for c in calibration]
        gate=calibrate(rows)
        trials.append({'config':config,'gate':gate,'rawCorrect':sum(r['prediction']['answer']==r['expected'] for r in rows),'rows':rows})
    best=max(trials,key=lambda r:(r['gate']['cases'],r['gate'].get('wilsonLower95',0)))
    save(STATE/'pixel-calibration.json',{'schema':'neyvia.head-free-repair-calibration.v1','config':best['config'],'gate':best['gate'],
        'trainingIds':[c['id'] for c in train],'calibrationIds':[c['id'] for c in calibration],
        'rows':best['rows'],'trials':[{k:v for k,v in t.items() if k!='rows'} for t in trials],
        'selectedUsing':'calibration only; held-out never opened','headTrained':False,'time':time.time()})
    print(json.dumps({k:v for k,v in best.items() if k!='rows'}),flush=True)


if __name__=='__main__':main()
