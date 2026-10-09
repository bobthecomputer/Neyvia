"""Complete live effect checks after the frozen holdout; never refits a gate."""
import argparse,json,time
from c2c_laya_run import REPO,Runtime,canonical,save
from grant_agent.laya_client.browser_client import explicit_intent_safe

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',required=True,type=int);a=p.parse_args()
    if a.port!=48727:p.error('Explicit resident48727, backend48728, engine48726 only')
    report=json.loads((REPO/'scripts/evidence/C2c-laya.json').read_text(encoding='utf-8'))
    previous=report.pop('effects')
    report.setdefault('effect_attempts',[]).extend(e for e in previous if not e.get('verified_url_changed'))
    report['effects']=[e for e in previous if e.get('verified_url_changed')]
    runtime=Runtime()
    try:
        runtime.start()
        for url in ['https://arxiv.org/']:
            tab=None
            try:
                tab=runtime.call('tab.open',{'url':url,'engine':'obscura'})['tabId'];runtime.call('tab.grant',{'tabId':tab,'enabled':True})
                originals=[r for r in report['rows'] if r.get('provenance',{}).get('url')==url and r['accepted'] and r['correct'] and r['type']=='named_link_click']
                desired='Search' if 'arxiv.org' in url else 'fractions — Rational numbers' if 'docs.python.org' in url else 'HTML: Markup language'
                chosen=next((r for r in originals if f'"{desired}"' in r['context']['goal']),None)
                if chosen is None:
                    initial=runtime.call('observe',{'tabId':tab})
                    target=next(e for e in initial['elements'] if e.get('role')=='link' and ' '.join(e.get('name','').split())==desired)
                    other_name='Donate' if 'arxiv.org' in url else 'cmath — Mathematical functions for complex numbers'
                    alternative=next(e for e in initial['elements'] if e.get('role')=='link' and ' '.join(e.get('name','').split())==other_name)
                    opts=[{'id':'a','description':canonical(target),'args':{'element':target['id'],'action':'click'}},{'id':'b','description':canonical(alternative),'args':{'element':alternative['id'],'action':'click'}}]
                    chosen={'context':{'goal':canonical(target),'options':opts,'decision_profile':'public_explicit_intent@1'},'separate_effect_case':True}
                retries=[];decision=None
                for attempt in range(3):
                    obs=runtime.call('observe',{'tabId':tab});options=[]
                    for o in chosen['context']['options']:
                        control=next(e for e in obs['elements'] if e.get('role')=='link' and canonical(e)==o['description'])
                        options.append({**o,'args':{'element':control['id'],'action':'click'}})
                    context={**chosen['context'],'options':options}
                    if not explicit_intent_safe(obs,context):raise ValueError('Fresh scope admission failed')
                    try:
                        decision=runtime.call('decide',{'tabId':tab,'question':'grounded_action','context':context})
                        if not decision.get('selected_action'):raise ValueError('No accepted fresh action: '+str(decision))
                        selected=decision['selected_action'];before=obs['url']
                        report.setdefault('effect_dispatch_attempts',[]).append({'url':url,'attempt':attempt,'decision':decision,'context':context})
                        save('C2c-laya.json',report)
                        act=runtime.call('action',selected);break
                    except ValueError as e:
                        retries.append(str(e))
                        if '409' not in str(e):raise
                        time.sleep(.3)
                if not decision or not decision.get('selected_action'):raise ValueError('No accepted fresh action: '+str(decision))
                after=runtime.call('observe',{'tabId':tab})
                report['effects'].append({'url':url,'context':context,'decision':decision,'action_receipt':act,'before_url':before,'after_url':after['url'],'verified_url_changed':after['url']!=before,'after_title':after['title'],'refresh_retries':retries,'grant_explicit':True,'separate_effect_case':chosen.get('separate_effect_case',False)})
                try:value=runtime.call('action',selected);report['adverse'].append({'kind':'stale_revision','denied':False,'response':value})
                except ValueError as e:report['adverse'].append({'kind':'stale_revision','denied':'stale_projection' in str(e),'reason':str(e)})
            except Exception as e:report['effects'].append({'url':url,'error':str(e)})
            finally:
                if tab:
                    try:runtime.call('tab.close',{'tabId':tab})
                    except Exception:pass
                save('C2c-laya.json',report)
        report['effect_calls']=runtime.calls
    finally:
        runtime.stop();report['owned_backend_stopped']=runtime.proc is None or runtime.proc.poll() is not None;report['effect_finished_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());save('C2c-laya.json',report)
    print(json.dumps({'effects':[{k:e.get(k) for k in ['url','verified_url_changed','error','after_url']} for e in report['effects']],'adverse':[{k:r.get(k) for k in ['kind','denied','reason']} for r in report['adverse']]}),flush=True)

if __name__=='__main__':main()
