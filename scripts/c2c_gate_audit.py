"""Rescore retained real model replies and production gates without a service."""
import copy, hashlib, json, statistics, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.laya_client.browser_client import explicit_intent_safe
from grant_agent.laya_client.calibration import BrowserCalibration
from grant_agent.laya_client.contracts import digest

def main():
    read=lambda p:json.loads((ROOT/p).read_text(encoding='utf-8'))
    run=read('scripts/evidence/C2c-laya.json')
    freeze=read('scripts/evidence/C2c-laya-threshold-freeze.json')
    calibration=BrowserCalibration(ROOT/'scripts/evidence/C2c-laya-calibration.json')
    accepted=correct=checked=0
    for row in run['rows']:
        if row['type']=='unsupported_semantic':
            assert not row['accepted'];continue
        raw=(ROOT/row['provenance']['observation_path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==row['provenance']['observation_sha256']
        obs=json.loads(raw);ctx=row['context']
        assert explicit_intent_safe(obs,ctx)
        gold=next(o['id'] for o in ctx['options'] if o['description']==ctx['goal'])
        assert gold==row['gold']
        for response in row['responses']:
            assert digest(response['identity'])==freeze['identity_digest']
            answer=response['answers']['decision']
            assert answer['answer']==row['prediction']
            value=calibration.confidence(response,answer,decision_profile=ctx['decision_profile'],url=obs['url'])
            assert value is not None and (value>=freeze['threshold'])==row['accepted']
            checked+=1
        accepted+=row['accepted'];correct+=row['accepted'] and row['prediction']==gold
    assert accepted==correct==339 and len(run['rows'])==515
    sample=next(r for r in run['rows'] if r['accepted'])
    obs=read(sample['provenance']['observation_path'])
    unsafe=copy.deepcopy(sample['context']);unsafe['options'][0]['description']='Click button "Delete account".'
    assert not explicit_intent_safe(obs,unsafe)
    assert calibration.confidence(sample['responses'][0],sample['responses'][0]['answers']['decision'],decision_profile='unknown_profile',url=obs['url']) is None
    effects=[e for e in run['effects'] if e.get('verified_url_changed')]
    assert len(effects)==2 and all(e['action_receipt']['verification']['verified'] and e['before_url']!=e['after_url'] for e in effects)
    stale=[r for r in run['adverse'] if r['kind']=='stale_revision']
    assert len(stale)==2 and all('stale_projection' in r['reason'] for r in stale)
    result={'schema':'neyvia.C2c.gate-audit@1','raw_model_replies_checked':checked,'heldout':len(run['rows']),'accepted':accepted,'accepted_correct':correct,'coverage':accepted/len(run['rows']),'precision':correct/accepted,'real_navigation_effects':len(effects),'live_stale_replays_denied':len(stale),'recorded_response_gate_replay':{'unsafe_description_denied':True,'unknown_profile_denied':True},'limitations':['Original live unknown-profile/unsafe-description attempts escalated because service was unavailable; those attempts do not prove scope guards. Production scope guards checked here by replaying retained actual model replies, without a live service.','C2c explicit-intent panel differs from C2b advisory/action panel; coverage is not a matched before/after task improvement.']}
    (ROOT/'scripts/evidence/C2c-gate-audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
