"""Frozen CPU replay only: JevBench, retained decisions and retained layout head."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

from laya_train_session import load, save

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
DATASET_HASH='dc3995d8ae1e2fc8e81ce38431add509eb8bb39b85aadfd0c7c32079382dde51'


def browser_route(port, root):
    """Actual owned HTTP inference through the browser attachment; finite page input."""
    import threading
    import uuid
    from grant_agent import laya_service
    from grant_agent.laya_client.browser_client import BrowserClient
    endpoint=f'http://127.0.0.1:{port}'
    def post(route,payload):
        request=urllib.request.Request(endpoint+route,json.dumps(payload).encode(),{'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
    with urllib.request.urlopen(endpoint+'/v1/health',timeout=30) as response:health=json.load(response)
    assert health['identity']['model']=='laya/laya-english' and health['identity']['weights_frozen']
    assert laya_service._browser_model_allowed(health['browser_identity'])
    evidence='GATEFIX verified receipt '+uuid.uuid4().hex
    observation={'tabId':'owned-fixture','revision':1,'readyState':'complete','url':endpoint+'/finite-page',
                 'title':'Owned outcome page','text':evidence,'elements':[],'tables':[]}
    class Page:
        lock=threading.RLock()
        laya_provider=None
        laya_client=None
        laya_health_timeout=30
        def __init__(self):self.root=root
        def tab(self,args):assert args['tabId']==observation['tabId']
        def projection(self,tab):assert tab==observation['tabId'];return dict(observation)
        def request(self,action,args,**kwargs):
            self.tab(args)
            if action=='observe':return dict(observation)
            assert action=='decide'
            return {'ok':True,'available':True,'decision':self.laya_provider(dict(observation),args['question'])}
    page=Page();page.laya_client=BrowserClient(page,endpoint,timeout_s=30).attach()
    args={'tabId':observation['tabId'],'question':'page_done','context':{'goal':evidence,'evidence':evidence,
          'action_receipts':[{'status':'completed','summary':evidence}]}}
    first=laya_service.browser_decide(page,args,owner=True)['decision']
    assert laya_service._browser_model_allowed(first['identity'])
    first_answer=first['answers']['page_done']
    if first_answer['source']=='laya':
        assert first_answer['confidence_kind']=='base_model' and first_answer['policy']=='escalate'
    else:
        assert first_answer['source'] in {'m0','m1'} and first_answer['confidence_kind'] in {
            'verified_exact_match_not_calibrated','verified_abstract_match_not_calibrated'}
    # Independent literal observation/receipt comparison supplies the label.
    assert args['context']['goal']==observation['text']==args['context']['action_receipts'][0]['summary']
    receipt=root/'browser-visible-receipt.json';save(receipt,{'observation':observation,'context':args['context'],'passed':True})
    learned=post('/v1/outcome',{'decision_id':first['decision_id'],'question':'page_done','correct':'true',
                 'kind':'verified_effect','evidence':{'receipt':str(receipt),'verifier':'gate-literal-page-and-action-receipt','passed':True}})
    assert learned['durable']
    replay=laya_service.browser_decide(page,args,owner=True)['decision'];answer=replay['answers']['page_done']
    assert laya_service._browser_model_allowed(replay['identity'])
    assert answer['source']=='m0' and answer['confidence_kind']=='verified_exact_match_not_calibrated',json.dumps(answer)
    assert answer['answer']=='true' and answer['top_probability']==1 and answer['evidence']
    rejected=post('/v1/decide',{'set':'neyvia.learned@2','questions':['page_done'],
             'state':{'goal':evidence,'page':{},'current':{'text':''},'action_receipts':[],
                      'evidence':evidence,'receipt_summary':''},'scope':{'domain':'CL-State'},'client':'t20-laya-hook'})
    rejected_answer=rejected['answers']['page_done']
    assert laya_service._browser_model_allowed(rejected['identity'])
    assert rejected_answer['source']!='laya' or rejected_answer['policy']=='escalate'
    typed=post('/v1/decide',{'questions':{'default-route':{'type':'noul','instructions':'Is evidence visible?'}},
               'state':{'text':evidence},'scope':{'domain':'gate-default-route'},'client':'gate-default-route','base_cache':False})
    assert typed['identity']==health['identity'] and not laya_service._browser_model_allowed(typed['identity'])
    report={'ok':True,'defaultIdentity':health['identity'],'browserIdentity':replay['identity'],
            'confidenceKind':answer['confidence_kind'],'unverifiedLearnedPolicy':rejected_answer['policy'],
            'boundary':'Actual production browser attachment and service inference; deterministic finite page observation, no native browser claim'}
    save(root/'browser-routing.json',report)
    return report


def admission(report):
    """Frozen release gates; a runner completing is not a floor pass."""
    bench=report.get('jevbench',{})
    layout=report.get('layout',{})
    return {
        'jevbench': bench.get('dataset_hash')==DATASET_HASH and
                    bench.get('n')==231 and bench.get('n_valid')==231 and
                    bench.get('failures')==0 and bench.get('correct',0)>=138,
        'retained': report.get('existingCases')==93 and
                    report.get('changedDecisionIds')==[] and
                    not report.get('missingDecisionIds') and not report.get('duplicateDecisionIds'),
        'layout': layout.get('correct')==48 and layout.get('cases')==48,
        'browser': report.get('browserRouting',{}).get('ok') is True,
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['before','after'])
    parser.add_argument('--root',type=Path,default=Path('D:/NeyviaRuns/laya3d'))
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--port',type=int,help='owned frozen-service port (default 49103 before, 49104 after)')
    parser.add_argument('--resource-home',type=Path,help='Explicit read-only public model/tool home when proof runtime homes are isolated')
    parser.add_argument('--check-report',type=Path,help='check a saved receipt without loading a model')
    args=parser.parse_args()
    if args.check_report:
        gates=admission(json.loads(args.check_report.read_text(encoding='utf-8')))
        print(json.dumps({'gates':gates,'passed':all(gates.values())}),flush=True)
        return 0 if all(gates.values()) else 1
    root=args.root/args.phase; root.mkdir(parents=True,exist_ok=True)
    from grant_agent.laya_host import LayaHost,load_config
    gates=load(REPO/'scripts/laya_regression_gate.py','mesh_regression')
    port=args.port or (49103 if args.phase=='before' else 49104)
    report={'phase':args.phase,'port':port,'training':False,'started':time.time()}
    state=args.root/'.agent_control/laya3d'/('model-'+args.phase)
    config={**load_config(state),'port':port,'device':'cpu'}
    if args.resource_home:
        home=args.resource_home.resolve()
        config.update(python=str(home/'miniforge3/envs/whisper/python.exe'),
                      project=str(home/'Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement'),
                      model=str(home/'Documents/Codex/2026-09-20/laya-c-est-l-alternative-open/work/models/laya-english'))
    host=LayaHost(state,config).start()
    try:
        if not gates.wait_ready(port): raise RuntimeError('Frozen CPU service did not become ready')
        report['browserRouting']=browser_route(port,root)
        runner=load(gates.LAYA_PROJECT/'scripts/run_jevbench.py','mesh_jevbench')
        runner.ROOT=args.root
        sys.argv=['jevbench','--endpoint',f'http://127.0.0.1:{port}/ai/run','--name','LAYA3D-'+args.phase,
                  '--output',str(root/'jevbench.json'),'--timeout','180']
        if not args.resume: runner.main()
        report['jevbench']=json.loads((root/'jevbench.json').read_text())
        from grant_agent import laya_hooks
        observations=[]
        for area in ('page_done','taste_triage'):
            for line in (REPO/'tools/laya/corpora'/f'{area}.jsonl').read_text(encoding='utf-8').splitlines():
                row=json.loads(line)
                if row.get('split')=='train': continue
                body={'set':laya_hooks.SET,'questions':[area],'state':row['state'],'scope':laya_hooks.SCOPES[area],'base_cache':False}
                req=urllib.request.Request(f'http://127.0.0.1:{port}/v1/decide',json.dumps(body).encode(),{'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=180) as response: answer=json.load(response)['answers'][area]
                observations.append({'area':area,'id':row['id'],'answer':answer})
                save(root/'existing-sets.json',observations)
        report['existingCases']=len(observations)
        prior=json.loads(Path('D:/NeyviaRuns/laya-train/after/existing-sets.json').read_text(encoding='utf-8'))
        lookup={(r['area'],r['id']):r['answer'] for r in prior}
        keys=[(r['area'],r['id']) for r in observations]
        report['missingDecisionIds']=[qid for area,qid in lookup.keys()-set(keys)]
        report['duplicateDecisionIds']=[qid for area,qid in set(keys) if keys.count((area,qid))>1]
        report['changedDecisionIds']=[r['id'] for r in observations if
            (r['area'],r['id']) not in lookup or any(r['answer'].get(k)!=lookup[r['area'],r['id']].get(k) for k in ('value','p'))]
        os.environ['NEYVIA_TASTE_ASSETS']='C:/Users/user/Projects/nx-c13-taste/.agent_control/c13h-assets'
        os.environ['NEYVIA_TASTE_DEPS']='C:/Users/user/Projects/nx-c13-taste/.agent_control/c13h-deps'
        os.environ['NEYVIA_TASTE_STATE']=str(args.root/'layout-state')
        from grant_agent import taste_vision
        rows=json.loads(Path('D:/NeyviaRuns/laya-train/vision/corrective-cases.json').read_text(encoding='utf-8'))
        outcomes=[]
        for row in rows:
            if row.get('excludedFromTraining') or row['split']!='heldout': continue
            result=taste_vision.compare(row['before'],row['after'],head_path=REPO/'tools/laya/capabilities/layout-head.json')
            outcomes.append((1 if result.get('score',0)>0 else -1)==row['preferred'])
        report['layout']={'correct':sum(outcomes),'cases':len(outcomes)}
    finally:
        host.stop(); report['finished']=time.time()
        report['gates']=admission(report); report['passed']=all(report['gates'].values())
        save(root/'regression.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='jevbench'}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__': sys.exit(main())
