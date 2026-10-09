"""Fitting-only compact explicit-intent representation probe; never reads holdout."""
import argparse, json, pathlib, statistics, urllib.request

def request(port, state, question):
    data=json.dumps({'state':state,'questions':{'decision':question},'memory':False,'base_cache':False}).encode()
    with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}/v1/decide',data,{'Content-Type':'application/json'}),timeout=10) as r: return json.load(r)

def main():
    p=argparse.ArgumentParser(); p.add_argument('--port',required=True,type=int); a=p.parse_args()
    if not 48727<=a.port<=48729: p.error('Assigned LAYA ports only')
    repo=pathlib.Path(__file__).resolve().parents[1]
    fitting=[json.loads(l) for l in (repo/'scripts/evidence/C2b-decisions-attempt1.jsonl').read_text(encoding='utf-8').splitlines() if l and json.loads(l)['split']=='calibration' and json.loads(l).get('family')=='grounded_action']
    rows=[]
    for case in fitting:
        obs=json.loads((repo/case['provenance']['observation_path']).read_text(encoding='utf-8'))
        elements={e['id']:e for e in obs['elements']}; chk=case['expected_check']
        target=elements[chk['element']]; other=elements[chk['alternative']]
        norm=lambda x:' '.join(x.split())
        if not norm(target['name']) or norm(target['name'])==norm(other['name']): continue
        criteria={key:'Click '+elements[chk['element'] if key==case['gold'] else chk['alternative']]['role']+' "'+norm(elements[chk['element'] if key==case['gold'] else chk['alternative']]['name'])+'".' for key in case['question']['criteria']}
        goal=criteria[case['gold']]
        for profile,view in [('intent',['goal']),('intent_current',['goal','current'])]:
            state={'goal':goal,'current':{'title':obs['title'],'readyState':obs['readyState']}}
            q={'type':'choice','instructions':"Choose the candidate that advances the user's goal using only observed page evidence. Do not assume pending actions succeeded. Goal: "+goal,'criteria':criteria,'view':view}
            value=request(a.port,state,q); ans=value['answers']['decision']
            rows.append({'id':case['id'],'group':case['group'],'profile':profile,'goal':goal,'criteria':criteria,'gold':case['gold'],'prediction':ans['answer'],'confidence':ans['top_probability'],'correct':ans['answer']==case['gold'],'response':value})
    summary={}
    for profile in ['intent','intent_current']:
        ds=[r for r in rows if r['profile']==profile]; gates=[]
        for threshold in sorted({r['confidence'] for r in ds}):
            selected=[r for r in ds if r['confidence']>=threshold]
            if len(selected)>=20 and statistics.mean(r['correct'] for r in selected)>=.95: gates.append({'threshold':threshold,'count':len(selected),'correct':sum(r['correct'] for r in selected)})
        summary[profile]={'count':len(ds),'accuracy':statistics.mean(r['correct'] for r in ds),'best':max(gates,key=lambda x:x['count'],default=None)}
    result={'schema':'neyvia.C2c-laya-fit@1','fitting_only':True,'heldout_read':False,'summary':summary,'rows':rows}
    (repo/'scripts/evidence/C2c-laya-fit.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(summary))

if __name__=='__main__':main()
