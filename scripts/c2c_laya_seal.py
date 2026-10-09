"""Independently rescore frozen choices and bind the final real receipt."""
import argparse,hashlib,json,urllib.request
from c2c_laya_run import REPO,digest,explicit_intent_safe,canonical,metrics,save

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',required=True,type=int);a=p.parse_args()
    if a.port!=48727:p.error('Explicit resident48727 only')
    report=json.loads((REPO/'scripts/evidence/C2c-laya.json').read_text(encoding='utf-8'))
    freeze=json.loads((REPO/'scripts/evidence/C2c-laya-threshold-freeze.json').read_text(encoding='utf-8'))
    fit=json.loads((REPO/'scripts/evidence/C2c-laya-fit.json').read_text(encoding='utf-8'))
    spec=json.loads((REPO/'scripts/evidence/C2c-laya-calibration.json').read_text(encoding='utf-8'))
    with urllib.request.urlopen(f'http://127.0.0.1:{a.port}/v1/health',timeout=10) as r:health=json.load(r)
    actions=[r for r in report['rows'] if r['type']!='unsupported_semantic']
    fitting=[r for r in fit['rows'] if r['profile']=='intent_current']
    assert digest(fitting)==freeze['fit_prediction_digest']
    assert not {r['group'] for r in actions}&set(freeze['fit_groups'])
    source_cases={r['id']:r for r in [json.loads(l) for l in (REPO/'scripts/evidence/C2b-decisions-attempt1.jsonl').read_text(encoding='utf-8').splitlines() if l] if r['split']=='calibration'}
    fit_states=set()
    for row in fitting:
        original=source_cases[row['id']];raw=(REPO/original['provenance']['observation_path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==original['provenance']['observation_sha256']
        obs=json.loads(raw);target=next(e for e in obs['elements'] if e['id']==original['expected_check']['element'])
        assert row['goal']==canonical(target)
        fit_states.add(digest({'goal':row['goal'],'current':{'title':obs['title'],'readyState':obs['readyState']}}))
    assert not {digest(r['state']) for r in actions}&fit_states
    for row in actions:
        raw=(REPO/row['provenance']['observation_path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==row['provenance']['observation_sha256']
        obs=json.loads(raw);ctx=row['context'];assert explicit_intent_safe(obs,ctx)
        gold=next(o['id'] for o in ctx['options'] if o['description']==ctx['goal'])
        assert row['gold']==gold
        assert row['correct']==(row['prediction']==gold)
        assert row['accepted']==(row['confidence']>=freeze['threshold'])
        for reply in row['responses']:
            assert digest(reply['identity'])==freeze['identity_digest']==digest(health['identity'])
            assert reply['memory_enabled'] is False and reply['runtime']['execution']=='cpu-only-r5'
        row['gold_check']={'criterion_matches_explicit_intent':True,'safe_unique_native_control':True,'native_snapshot_sha256_checked':True}
    for effect in report['effects']:
        if not effect.get('verified_url_changed'):continue
        assert effect['action_receipt'].get('verification',{}).get('verified') is True
        assert effect['before_url']!=effect['after_url']
        assert effect['decision']['selected_action'] is not None
        assert effect['decision']['browser_policy']['policy']=='answer+postcheck'
    inherited={k:v for k,v in spec.items() if k.startswith('advisory_') or k.startswith('supported_advisory')}
    selected_keys=['schema','family','temperature','decision_scope','identity_digest','calibration_count','heldout_count','acceptance_threshold','validated','supported_option_counts','supported_option_id_sequences','supported_decision_profiles','browser_client_sha256','evaluated_hosts','method','scope_limit']
    cleaned={**inherited,**{k:spec[k] for k in selected_keys}}
    cleaned.update(action_calibration={'count':len(fitting),'accepted':freeze['fit_accepted'],'accepted_correct':freeze['fit_correct'],'precision':freeze['fit_correct']/freeze['fit_accepted']},heldout=metrics(report['rows']),action_heldout=metrics(actions),advisory_prior_evidence='scripts/evidence/C2b-laya-calibration.json; unchanged advisory projection; inherited advisory statistics are prior evidence only')
    save('C2c-laya-calibration.json',cleaned)
    report.update(independent_rescore={'group_disjoint':True,'immutable_fit_digest':True,'native_snapshots_checked':len(actions),'frozen_identity_replies_checked':len(actions)*3,'accepted_before_selected_control_postcheck':sum(r['accepted'] for r in actions),'accepted_correct_before_selected_control_postcheck':sum(r['accepted'] and r['correct'] for r in actions),'verified_live_effects':sum(bool(e.get('verified_url_changed')) for e in report['effects']),'adverse_all_denied':all(r['denied'] for r in report['adverse'])},health_after=health)
    paths=['src/grant_agent/laya_client/browser_client.py','src/grant_agent/laya_client/calibration.py','src/grant_agent/laya_client/fast_cpu.py','scripts/c2c_laya_fit.py','scripts/c2c_laya_run.py','scripts/c2c_laya_effects.py','scripts/c2c_laya_seal.py','scripts/evidence/C2c-laya-fit.json','scripts/evidence/C2c-laya-threshold-freeze.json','scripts/evidence/C2c-laya-calibration.json']
    report['source_and_gate_sha256']={path:hashlib.sha256((REPO/path).read_bytes()).hexdigest() for path in paths}
    assert report['source_and_gate_sha256']['src/grant_agent/laya_client/browser_client.py']==cleaned['browser_client_sha256']
    save('C2c-laya.json',report);print(json.dumps(report['independent_rescore']))

if __name__=='__main__':main()
