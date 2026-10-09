"""Verify retained live C2c receipts, recompute metrics and append scoped results."""
import argparse, hashlib, json, os, re, statistics
from pathlib import Path
from efficiency_log import validate, ledger_lock, read_ledger

ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
def save(path,value):(ROOT/path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def quantile(values,p):
    values=sorted(values)
    if not values:return None
    pos=(len(values)-1)*p;lo=int(pos)
    return values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(pos-lo)
def timing(values):return {'p50':statistics.median(values) if values else None,'p95':quantile(values,.95),'samples':len(values),'method':'linear-interpolated quantile'}

def verify():
    tasks=read('scripts/evidence/C2-webvoyager-tasks.json')
    run=read('scripts/evidence/C2c-webvoyager.json')
    grades=read('scripts/evidence/C2c-webvoyager-grades.json')
    gate=read('scripts/evidence/C2c-gate-audit.json')
    laya=read('scripts/evidence/C2c-laya.json')
    repair=read('scripts/evidence/C2c-fill-repair.json')
    cleanup=read('scripts/evidence/C2c-browser-cleanup.json')
    assert len(tasks['tasks'])==len(run['tasks'])==len(grades['grades'])==36
    assert grades['run']['sha256AtFinalFreeze']==sha('scripts/evidence/C2c-webvoyager.json')
    assert len({t['site'] for t in tasks['tasks']})==12
    assert run['taskSetSha256']==sha('scripts/evidence/C2-webvoyager-tasks.json')
    original={t['id']:t for t in tasks['tasks']};scored={t['id']:t for t in grades['grades']}
    snapshots=0;results=[]
    for task in run['tasks']:
        assert task['status'] in ('answered','failed','skipped')
        assert task['startUrl']==original[task['id']]['startUrl'] and task['goal']==original[task['id']]['goal']
        assert task['steps']==sum(t['kind']=='action' for t in task['trace'])
        assert task['steps']<=original[task['id']]['maxActions']
        observed={o['path'] for o in task['observations']}
        for obs in task['observations']:
            assert sha(obs['path'])==obs['sha256'];snapshots+=1
        grade=scored[task['id']]
        if grade['success']:
            assert task['status']=='answered' and task['steps']>=2
            assert grade['clauses'] and all(c['met'] and c['evidence'] for c in grade['clauses'])
            for clause in grade['clauses']:
                for evidence in clause['evidence']:
                    assert evidence['path'] in observed
                    if evidence.get('sha256'):assert sha(evidence['path'])==evidence['sha256']
                    source=read(evidence['path'])
                    field=evidence.get('field','text')
                    value=source[field] if field in source else json.dumps(source,ensure_ascii=False)
                    if not isinstance(value,str):value=json.dumps(value,ensure_ascii=False,separators=(',',':'))
                    if evidence.get('whitespaceNormalized'):value=re.sub(r'\s+',' ',value).strip()
                    assert evidence['quote'] in value,(task['id'],field,evidence['quote'])
        response_calls=[run['calls'][i] for i in task['calls']]
        results.append({'id':task['id'],'site':task['site'],'startUrl':task['startUrl'],'goal':task['goal'],'success':bool(grade['success']),'status':'success' if grade['success'] else 'skipped' if task['status']=='skipped' else 'failed','operatorStatus':task['status'],'reason':grade.get('reason') or task.get('reason'),'steps':task['steps'],'elapsedMs':task['elapsedMs'],'recordedResponseApiCalls':len(response_calls),'recordedApiServiceMs':sum(c['ms'] for c in response_calls),'providerCostUSD':task['providerCostUSD'],'paidApiCalls':task['paidApiCalls']})
    assert run['stealth'] is tasks['stealth'] is False
    assert gate['precision']>=.95 and gate['coverage']>.221
    for path,expected in laya['source_and_gate_sha256'].items():assert sha(path)==expected,path
    assert cleanup['ports48721Through48728Clear'] is True
    assert read('scripts/evidence/C2c-laya-cleanup.json')['no_owned_port_listeners'] is True
    assert repair['finishedAt'] and repair['cleanup']['headlessStopRequested']
    # That initial harness checked exitCode only; a signal exit has null
    # exitCode. The independently checked listener cleanup is authoritative.
    fill_trace=repair['tasks'][0]['trace']
    assert any(r.get('action',{}).get('action')=='fill' and r.get('response',{}).get('verification',{}).get('verified') for r in fill_trace)
    assert any(r.get('action',{}).get('expect') and 'effect_unconfirmed' in r.get('error','') for r in fill_trace)
    success=sum(t['success'] for t in results);skip=sum(t['status']=='skipped' for t in results)
    observations=[c['ms'] for c in run['calls'] if c['op']=='observe' and c['status']==200]
    actions=[c['ms'] for c in run['calls'] if c['op']=='action' and c['response'].get('verification',{}).get('verified')]
    limitations=[
        'Lead inspected upstream references before its 18 tasks; worker executor did not. Independent post-answer grading does not repair operator blinding. Descriptive live panel, not an official fully blinded WebVoyager score.',
        'Live runs use Codex/operator reasoning over CL controls, with manual scheduling and intervening work. Task wall time includes that time and receipt serialization; this is not an unattended autonomous benchmark.',
        'Original harness did not persist API calls on transport exceptions. Reported response API counts and summed service times exclude such exceptions; exact total attempted API calls is unknown.',
        'Codex subscription/model-tool usage and local compute cost are unmetered; per-task cost is null, not zero. No API-key provider requests were made.',
        'C2c explicit-intent coverage uses a different panel from C2b. General planning, search/value/fill decisions and general computer-use confidence remain unproven.',
        'Original unsafe/unknown-profile live tests saw an unavailable service. Scope guards were independently checked by recorded-response replay; live stale revisions were denied twice.',
        'Paired Claude/browser-use/frontier arms pending. Frozen identical tasks and rubric are ready; no comparative quality, latency or cost claim.',
        'Chrome plugin exposed no browser surfaces; no new rendered native/window or screenshot proof. Real production headless calls and page evidence are retained.',
        'The fill setter crash was repaired after the frozen first panel; separate live rerun verifies fill and false-postcondition refusal, but Wolfram calculation remains failed. First-panel scores are unchanged.'
        ,'Supplemental harness backendExited was falsely recorded as false for a signal exit (null exitCode). Independent process-session completion and all-owned-listener cleanup confirm it stopped; harness now also checks signalCode.'
    ]
    metrics={'tasks':36,'sites':12,'success':success,'failed':36-success-skip,'skipped':skip,'successOverAll':success/36,'successOverUnskipped':success/(36-skip),'steps':timing([t['steps'] for t in results]),'taskLatencyMs':timing([t['elapsedMs'] for t in results]),'recordedApiServicePerTaskMs':timing([t['recordedApiServiceMs'] for t in results]),'pageToCLMs':timing(observations),'actionToVerifiedMs':timing(actions),'providerCostPerTaskUSD':None,'paidApiCalls':sum(t['paidApiCalls'] for t in results),'totalAttemptedApiCalls':None,'recordedResponseApiCalls':sum(t['recordedResponseApiCalls'] for t in results)}
    panel={'schema':'neyvia.C2c.scored-panel@1','taskSetSha256':run['taskSetSha256'],'runSha256':sha('scripts/evidence/C2c-webvoyager.json'),'gradingSha256':sha('scripts/evidence/C2c-webvoyager-grades.json'),'metrics':metrics,'tasks':results,'limitations':limitations}
    save('scripts/evidence/C2c-scored-panel.json',panel)
    paths=['scripts/evidence/C2-webvoyager-tasks.json','scripts/evidence/C2-webvoyager-references.json','scripts/evidence/C2c-webvoyager.json','scripts/evidence/C2c-webvoyager-grades.json','scripts/evidence/C2c-scored-panel.json','scripts/evidence/C2c-laya.json','scripts/evidence/C2c-laya-calibration.json','scripts/evidence/C2c-laya-threshold-freeze.json','scripts/evidence/C2c-gate-audit.json','scripts/evidence/C2c-fill-repair.json','scripts/evidence/C2c-browser-cleanup.json','scripts/evidence/C2c-laya-cleanup.json']
    source=['src/grant_agent/browser_dom.js','src/grant_agent/laya_client/browser_client.py','scripts/c2c_webvoyager.cjs','scripts/c2c_operator.cjs','scripts/c2c_control.cjs','scripts/c2c_fill_proof.cjs','scripts/c2c_gate_audit.py','scripts/seal_c2c.py','manuals/cl/browser.cl','manuals/browser.manual.json']
    summary={'schema':'neyvia.C2c-verification@1','C2_C3_complete':False,'verified_recorded_boundary':True,'task_freeze_commit':'170bc7b3','gates':{'public36tasks12sitesExecuted':True,'independentFrozenRubricGrading':True,'fullyBlindedBenchmark':False,'LAYA_precision95coverageAbove22':True,'LAYA_realSelectedActionEffects':True,'measuredCostPerTask':False,'pageToCL300msP50':metrics['pageToCLMs']['p50']<300,'actionToVerified400msP50':metrics['actionToVerifiedMs']['p50']<400,'pairedComparators':False,'newRenderedNativeProof':False},'browser':metrics,'LAYA':{'heldout':laya['heldout'],'byType':laya['by_type'],'determinism':laya['determinism'],'latencyMs':laya['latency_ms'],'realEffects':gate['real_navigation_effects'],'acceptedScope':'Opt-in explicit named safe link/button click, two candidates; exact frozen identity/client/profile/host binding.'},'snapshotsHashChecked':snapshots,'receipts':{p:sha(p) for p in paths},'finalSourceHashes':{p:sha(p) for p in source},'checks':{'manuals':52,'chapters':189,'manualValidation':'scripts/build_grounded_manuals.py --check --root .agent_control/C2c/manual-check: exit0','nodeSyntax':True,'productionGateRescore':True,'fillVerifiedAndFalsePostconditionDenied':True},'limitations':limitations,'needsPaul':['Run the Claude comparison arm against the frozen task file when its browser route is available; no login/bot-wall bypass.','Provide metered model usage/cost if an actual per-task cost comparison is required.']}
    save('scripts/evidence/C2c.json',summary)
    return summary

def rows(summary):
    ci={'method':'not-estimable','reason':'Descriptive purposively selected correlated public page panel; not a population or blinded comparative estimate.'}
    def row(suffix,study,path,method,metrics,models):
        return {'schema':'neyvia.efficiency-result.v1','id':'C2c-'+suffix,'study':study,'method':method,'models':models,'tasks':{'description':study,'repetitions':3 if suffix=='laya' else 1,'independent_unit':'page/task group'},'limitations':summary['limitations'],'receipts':[{'id':'run','path':path,'sha256':sha(path),'kind':'raw'}],'metrics':[{'name':name,'unit':unit,'calculation':{'receipt':'run','pointer':pointer},'ci_request':ci} for name,unit,pointer in metrics],'evidence_status':'raw-verified'}
    yield row('laya','C2c frozen CPU explicit named-control selection','scripts/evidence/C2c-laya.json','Threshold fitted on earlier disjoint page groups before heldout capture; 515 decisions with 132 unsupported escalations. Model precision measured before selected-control postcheck. Two actual accepted navigation effects; three inference repeats per eligible decision.',[('accepted_precision','fraction','/heldout/precision'),('heldout_coverage','fraction','/heldout/coverage'),('accepted_correct','count','/heldout/accepted_correct'),('http_p50','ms','/latency_ms/http/p50'),('http_p95','ms','/latency_ms/http/p95'),('deterministic_cases','count','/determinism/identical')],['laya/g3-c2 frozen resident CPU head; no memory/base cache'])
    yield row('public','C2c 36 homepage-start public WebVoyager tasks across12sites','scripts/evidence/C2c-scored-panel.json','Live observed-control runs without supplied answer URLs; separately graded per frozen goal clauses and upstream references. Lead reference exposure and unmetered costs disclosed. Original failed attempts remain; repair rerun excluded.',[('tasks','count','/metrics/tasks'),('sites','count','/metrics/sites'),('success','count','/metrics/success'),('skipped','count','/metrics/skipped'),('success_over_all','fraction','/metrics/successOverAll'),('steps_p50','steps','/metrics/steps/p50'),('task_latency_p50','ms','/metrics/taskLatencyMs/p50'),('task_latency_p95','ms','/metrics/taskLatencyMs/p95'),('page_to_CL_p50','ms','/metrics/pageToCLMs/p50'),('action_to_verified_p50','ms','/metrics/actionToVerifiedMs/p50')],['Codex lead + delegated GPT-6.1 Sol reasoning over production Obscura CL; independently graded GPT-6.1 Sol'])

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--append',action='store_true');args=parser.parse_args()
    summary=verify()
    if args.append:
        ledger=ROOT/'docs/research/results.jsonl'
        with ledger_lock(ledger):
            old={r['id']:r for r in read_ledger(ledger)}
            prepared=[validate(r,ROOT,prepare=True) for r in rows(summary)]
            for row in prepared:
                if row['id'] in old:assert row==old[row['id']],'Existing C2c result differs'
            with ledger.open('a',encoding='utf-8',newline='\n') as stream:
                for row in prepared:
                    if row['id'] not in old:stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
                stream.flush();os.fsync(stream.fileno())
    print(json.dumps({'browser':summary['browser'],'LAYA':summary['LAYA']['heldout'],'complete':summary['C2_C3_complete']},indent=2))

if __name__=='__main__':main()
