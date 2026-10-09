"""Measure actual frozen LAYA on real page decisions; never tune on held-out."""
from pathlib import Path
import argparse
import json
import sys
import time
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.taste_fewshot import STATE, nearest, predict, calibrate, save, wilson, digest, episodic_prediction


def sample(cases, kind, split, limit):
    selected=[c for c in cases if c['kind']==kind and c['split']==split]
    if kind=='repair':selected=[c for c in selected if c.get('supported',True)]
    # Stable sampling, independent of outcome; no easy-case cherry picking.
    selected.sort(key=lambda c:digest(c['id']))
    return selected[:limit] if limit else selected


def measure(split,limit,only=None,episodes=False):
    corpus=json.loads((STATE/'real-pairs.json').read_bytes())
    personal=json.loads((STATE/'personal.json').read_bytes())['records']
    output=STATE/(split+'-decisions.json')
    old=json.loads(output.read_bytes()) if output.exists() else []
    results={r['id']:r for r in old}
    for kind in ('repair','failure','crop'):
        if only and kind!=only:continue
        training=[r for r in corpus['cases'] if r['split']=='train' and r['kind']==kind]
        for case in sample(corpus['cases'],kind,split,limit):
            if case['id'] in results:continue
            facts=case['facts'];query=json.dumps(facts)
            contextual=nearest(personal,query,count=2,exclude_groups=[case['group']])
            demonstration=nearest(training,query,count=3,exclude_groups=[case['group']])
            try:
                base=predict(kind,facts,contextual+demonstration)
                prediction=base | episodic_prediction(kind,facts,training) if episodes else base
                if episodes:prediction |= {'baseModelAnswer':base['answer'],'baseModelConfidence':base['confidence']}
            except Exception as exc:
                save(STATE/(split+'-error.json'),{'case':case['id'],'error':str(exc),'time':time.time()})
                raise
            results[case['id']]={'id':case['id'],'kind':kind,'group':case['group'],'expected':case['expected'],
                'criticExpected':case.get('criticExpected'),
                'prediction':prediction,'examples':contextual+demonstration,'source':case['source'],
                'factsSha256':digest(facts)}
            save(output,list(results.values()))
            print(json.dumps({'split':split,'kind':kind,'completed':len(results),'correct':prediction['answer']==case['expected'],
                             'confidence':prediction['confidence'],'ms':round(prediction['latencyMs'])}),flush=True)
    return list(results.values())


def freeze():
    rows=json.loads((STATE/'calibration-decisions.json').read_bytes())
    gates={kind:calibrate([r for r in rows if r['kind']==kind]) for kind in ['repair','failure','crop']}
    result={'schema':'neyvia.real-selective-gates.v1','gates':gates,'sourceSha256':digest(rows),
            'requirements':{'minCases':12,'calibrationAccuracy':.9,'wilsonLower95':.7},
            'statisticalScope':'Conditional empirical confidence on historical real page decisions; correlated page episodes, not universal 95% confidence.',
            'answerSource':rows[0]['prediction'].get('source','base frozen LAYA') if rows else 'unavailable',
            'headTrained':False,'frozenAt':time.time()}
    save(STATE/'calibration.json',result);print(json.dumps(result),flush=True)


def report():
    policy=json.loads((STATE/'calibration.json').read_bytes())
    rows=json.loads((STATE/'heldout-decisions.json').read_bytes())
    measures={}
    for kind in ['repair','failure','crop']:
        values=[r for r in rows if r['kind']==kind]
        threshold=policy['gates'][kind]['threshold']
        accepted=[r for r in values if threshold is not None and r['prediction']['confidence']>=threshold]
        correct=sum(r['prediction']['answer']==r['expected'] for r in accepted)
        allcorrect=sum(r['prediction']['answer']==r['expected'] for r in values)
        measures[kind]={'cases':len(values),'answered':len(accepted),'coverage':len(accepted)/len(values) if values else 0,
            'correct':correct,'selectiveAccuracy':correct/len(accepted) if accepted else None,
            'wilsonLower95':wilson(correct,len(accepted)), 'allAccuracy':allcorrect/len(values) if values else None,
            'falseAccepts':sum(r['prediction']['answer'] and not r['expected'] for r in accepted),
            'groups':sorted({r['group'] for r in values}),
            'majorityBaseline':max(sum(r['expected'] for r in values),sum(not r['expected'] for r in values))/len(values) if values else None}
        if kind=='repair':
            measures[kind]['criticAgreement']=sum(r['prediction']['answer']==r['criticExpected'] for r in accepted)/len(accepted) if accepted else None
    # A failed held-out validation deactivates that gate. It does not retune it.
    admitted={k:v['answered']>=12 and v['selectiveAccuracy']>=.9 and v['coverage']>=.5 for k,v in measures.items()}
    result={'schema':'neyvia.real-heldout.v1','metrics':measures,'admitted':admitted,
            'policySha256':digest(policy),'decisionsSha256':digest(rows),'headTrained':False,
            'usage':{'inputTokens':sum(r['prediction']['usage']['input_tokens'] for r in rows),
                     'latencyMs':sum(r['prediction']['latencyMs'] for r in rows)},
            'limitations': ['R11 is held out by run/arm/task with exact pixel overlap removed, not a new unseen task distribution.',
                           'Repair accuracy measures retention without observed regressions, not subjective quality. Independent critic agreement is reported separately.',
                           'Failure labels are recorded check outcomes; crop labels are actual critic region selections.',
                           'Only qualified and independently validated modes may skip paid calls.']}
    save(STATE/'heldout-report.json',result);print(json.dumps(result),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['calibration','freeze','heldout','report'],required=True)
    parser.add_argument('--limit',type=int,default=60);parser.add_argument('--kind',choices=['repair','failure','crop']);parser.add_argument('--episodes',action='store_true');args=parser.parse_args()
    if args.phase in ['calibration','heldout']:measure(args.phase,args.limit,args.kind,args.episodes)
    elif args.phase=='freeze':freeze()
    else:report()


if __name__=='__main__':main()
