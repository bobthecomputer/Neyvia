"""Import the bounded A4 historical corpus without executing benchmarks or services.

Archives exact selected receipts, retains source paths, deduplicates copied studies,
and builds a reproducible projection. Re-running refuses to overwrite the ledger.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil

from efficiency_log import ROOT, SCHEMA, LEDGER, atomic_write, digest, read_json, render, validate

PROJECTS = Path("C:/Users/user/Projects")
LAYA = Path("C:/Users/user/Documents/Codex/2026-09-30/the-ai-was-a-massive-improvement")
ARCHIVE = ROOT / "scripts/evidence/A4-receipts"
NO_CI = {"method":"not-estimable", "reason":"Development pilot; no independent deployment repeats or held-out population CI."}
ROWS = []
SOURCES = {}


def ref(name, path="", field=None, where=None):
    x={"receipt":name,"pointer":path}
    if field is not None: x["field"]=field
    if where is not None: x["where"]=where
    return x


def op(name,*args): return {"op":name,"args":list(args)}


def archive(path, name="raw", kind="raw"):
    path=Path(path)
    if any(re.search(r"credential|nas|password|secret|auth\.json",part,re.I) for part in path.parts):
        raise ValueError(f"Excluded protected source path: {path.name}")
    sha=digest(path)
    target=ARCHIVE/(sha+path.suffix)
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists(): shutil.copyfile(path,target)
    if digest(target)!=sha: raise ValueError("Archived bytes changed")
    SOURCES[path.resolve().as_posix()]=sha
    return {"id":name,"path":target.relative_to(ROOT).as_posix(),"source_path":path.resolve().as_posix(),"sha256":sha,"kind":kind}


def row(id,study,method,models,description,repetitions,unit,receipts,limitations,status="raw-verified"):
    return {"schema":SCHEMA,"id":id,"study":study,"evidence_status":status,"method":method,"models":models,
            "tasks":{"description":description,"repetitions":repetitions,"independent_unit":unit},
            "receipts":receipts,"metrics":[],"limitations":limitations}


def metric(r,name,expr,unit="count",ci=None):
    r["metrics"].append({"name":name,"unit":unit,"calculation":expr,"ci_request":ci or NO_CI})


def finish(r):
    validate(r,prepare=True);ROWS.append(r)


def model_cases(only_development=False):
    """CL 1.0 development history and both frozen CL 1.1 cohorts, per-case raw files."""
    cl=PROJECTS/"nx-cl"
    cohorts=[]
    for base in ([] if only_development else sorted((cl/".agent_control/cl/benchmark").iterdir())):
        if base.is_dir() and (base/"summary.json").exists():
            cohorts.append(("cl10-"+base.name,base,list(base.glob("*/result.json")),False))
    for name in ([] if only_development else ["scored-1","scored-2"])+[p.name for p in sorted((cl/'scripts/evidence/cl11').glob('dev-*'))]:
        base=cl/"scripts/evidence/cl11"/name
        cohorts.append(("cl11-"+name,base,list(base.glob("task-*/*/*/rep-*/result.json")),True))
    for cohort,base,paths,new in cohorts:
        groups={}
        for path in sorted(paths):
            data=read_json(path)
            model=data.get("model",data.get("requestedModel"))
            groups.setdefault((model,data["arm"]),[]).append((path,data))
        for (model,arm),cases in sorted(groups.items()):
            valid=[(p,d) for p,d in cases if d.get("valid",True)]
            receipts=[archive(p,f"case{i}") for i,(p,d) in enumerate(cases)]
            validids=[f"case{i}" for i,(p,d) in enumerate(cases) if d.get("valid",True)]
            def fields(path): return [ref(i,path) for i in validids]
            r=row(f"{cohort}-{model}-{arm}",f"CL {'1.1' if new else '1.0'} · {cohort} · {model}/{arm}",
                "Fresh isolated fixtures and explicit CLI routes. Arms a=JSON+manual, b=CL+manual, c=JSON without manual. CL1.1 has fixed paired seeds/randomized arm order; native baselines have different tool surfaces. Counts include failures; invalid trials are shown separately. Cached input is part of input and is counted once.",
                [model],"Notes, Files, native, web and chart fixture tasks; exact task/seed and outcome in every case receipt",
                "three per task/arm for scored CL1.1; development pilots have source-specific partial repetitions", "task (repetitions clustered)",receipts,
                ["Model routes do not attest deployed weights; concurrent local load affects latency.",
                 "Development fixtures were inspected and repaired; the small-beats-large gate and full native comparison failed.",
                 "CL1.1 original reports use run-level bootstraps; A4 uses task-cluster mean CIs, conditional on this panel. Cold supplied o200k context is not total provider context."])
            metric(r,"attempted",op("count",[ref(q["id"],"/arm") for q in receipts]))
            if not valid:
                r["evidence_status"]="unverified";r["limitations"].append("No valid observations in this arm.");finish(r);continue
            successes=fields("/success" if new else "/passed")
            clusters=fields("/task")
            metric(r,"valid",op("count",clusters))
            metric(r,"invalid",op("subtract",op("count",[ref(q["id"],"/arm") for q in receipts]),op("count",clusters)))
            metric(r,"successes",op("sum",successes))
            ci={"method":"cluster-bootstrap-mean","values":successes,"clusters":clusters,"resamples":2000,"seed":417,"level":.95} if len({d['task'] for _,d in valid})>1 else NO_CI
            metric(r,"success_rate",op("mean",successes),"fraction",ci)
            fieldmap={"provider_tokens":"/tokens/total","cold_context":"/context/cold","first_touch_context":"/context/firstTouch","amortized_context":"/context/amortized","latency_ms":"/latencyMs","fresh_task_tokens":"/freshTaskTokens","actions":"/actionCount"} if new else {"provider_tokens":"/providerTotalTokens","cold_context":"/startContext/o200k_tokens","latency_ms":"/latencyMs"}
            for key,path in fieldmap.items():
                # Early pilots have fewer accounting fields; missing means unmeasured, not zero.
                try:
                    from efficiency_log import pointer
                    for _,d in valid:pointer(d,path)
                except KeyError:
                    r["limitations"].append(f"{key} not present in this pilot.");continue
                values=fields(path)
                ci={"method":"cluster-bootstrap-mean","values":values,"clusters":clusters,"resamples":2000,"seed":417,"level":.95} if len({d['task'] for _,d in valid})>1 else NO_CI
                metric(r,key+"_mean",op("mean",values),"ms" if key=="latency_ms" else "o200k supplied-text tokens" if "context" in key else "actions" if key=="actions" else "input+output tokens",ci)
                if key=="provider_tokens":metric(r,key+"_total",op("sum",values),"input+output tokens")
            finish(r)


def comparisons():
    from efficiency_log import evaluate
    for baseline in list(ROWS):
        if not baseline['id'].startswith('cl') or not baseline['id'].endswith('-a'):continue
        candidate=next((r for r in ROWS if r['id']==baseline['id'][:-1]+'b'),None)
        if not candidate:continue
        receipts=[];names={}
        for prefix,arm in (('a',baseline),('b',candidate)):
            for receipt in arm['receipts']:
                name=prefix+'-'+receipt['id'];names[(prefix,receipt['id'])]=name
                receipts.append({**receipt,'id':name})
        def remap(expr,prefix):
            if isinstance(expr,list):return [remap(x,prefix) for x in expr]
            if isinstance(expr,dict):return {k:names[(prefix,v)] if k=='receipt' else remap(v,prefix) for k,v in expr.items()}
            return expr
        r=row(baseline['id'][:-2]+'-b-vs-a','CL comparison · '+baseline['id'][:-2],
              'Same model within the same cohort: CL+manual b versus JSON+manual a. Cost reductions use all valid attempts including failures; success differences are paired by task/repetition/seed.',
              baseline['models'],baseline['tasks']['description'],baseline['tasks']['repetitions'],'task',receipts,
              baseline['limitations']+['Ratios have no independent deployment CI; costs and success must be considered together. Invalid source observations are excluded and reported in arm rows.'])
        for name in ('cold_context_mean','first_touch_context_mean','provider_tokens_mean','latency_ms_mean'):
            a=next((m for m in baseline['metrics'] if m['name']==name),None)
            b=next((m for m in candidate['metrics'] if m['name']==name),None)
            if a and b:metric(r,name+'_reduction',op('reduction_percent',remap(a['calculation'],'a'),remap(b['calculation'],'b')),'percent')
        keys={}
        for prefix,arm in (('a',baseline),('b',candidate)):
            for receipt in arm['receipts']:
                data=read_json(ROOT/receipt['path'])
                if data.get('valid',True):keys.setdefault((data['task'],data.get('repetition',1),data.get('seed')), {})[prefix]=names[(prefix,receipt['id'])]
        paired=[v for k,v in sorted(keys.items(),key=lambda x:str(x[0])) if len(v)==2]
        if paired:
            field='/success' if baseline['id'].startswith('cl11') else '/passed'
            values=[op('subtract',ref(p['b'],field),ref(p['a'],field)) for p in paired]
            clusters=[ref(p['a'],'/task') for p in paired]
            ci={'method':'cluster-bootstrap-mean','values':values,'clusters':clusters,'seed':417,'resamples':2000,'level':.95} if len({k[0] for k,v in keys.items() if len(v)==2})>1 else NO_CI
            metric(r,'paired_success_difference',op('mean',values),'fraction points',ci)
        finish(r)


def pilots():
    p=PROJECTS/"nx-r-backend/scripts/evidence/manual-recovery.json"
    data=read_json(p)
    r=row("manual-recovery","Manual recovery: protocol and cost",data["protocol"] if isinstance(data["protocol"],str) else "Six fixed handoff tasks; actual tool effects and protocol checks; same Haiku route; baseline logs reused after typed-manual repair.",
          ["claude-haiku-4-5-20251001","none during deterministic procedure execution"],"approved staging, pending-review stop, stale-write reconciliation, collision hold, duplicate capture, selected-draft restore",2,"six authored tasks",[archive(p)],
          ["Protocol success differs from semantic task success.","Typed manual was repaired on the same tasks; no held-out generalization. Deterministic execution excludes authoring and judgement choices."])
    for arm in sorted({x['arm'] for x in data['modelRuns']}):
        for f in ("successes","semanticSuccesses","totalTokens","latencyMs"):
            metric(r,arm+"_"+f,op("sum",ref("raw","/modelRuns","/"+f,{"/arm":arm})),"tokens" if f=="totalTokens" else "ms" if f=="latencyMs" else "count")
    for f in ("successes","modelTokens"):metric(r,"deterministic_"+f,op("sum",ref("raw","/deterministicRuns","/"+f)))
    metric(r,'typed_manual_token_increase',op('multiply',100,op('subtract',op('divide',op('sum',ref('raw','/modelRuns','/totalTokens',{'/arm':'manual-v2'})),op('sum',ref('raw','/modelRuns','/totalTokens',{'/arm':'baseline'}))),1)),'percent')
    finish(r)
    p=PROJECTS/"nx-t5-manuals/scripts/evidence/T5-compiler.json";d=read_json(p)
    r=row("t5-compiled","T5 compiled procedures","Three successful repeated grounded runs specialize exact inputs; compiled run checks real written bytes; changed observations/input/manual hashes exercise rejection and JUDGE recovery.",
          ["none for successful specialized execution"],"one exact-input compiled write plus changed-input/state/version adverse branches","three training runs; one successful specialized replay","procedure",[archive(p)],
          ["Zero model calls applies only during specialized execution. Training/authoring and resumed judgement are excluded."])
    for i,x in enumerate(d['receipts']):
        if x.get('tool')=='neyvia.manual.script.run' and x.get('result',{}).get('status')=='completed':
            for f in ('modelCalls','zeroToken'):metric(r,f+f"_receipt{i}",ref("raw",f"/receipts/{i}/result/{f}"))
    finish(r)
    p=PROJECTS/"nx-t5-manuals/scripts/evidence/T5-models.json";d=read_json(p)
    extra=[]
    for i,t in enumerate(d['trials']):
        for f in ('streamReceipt','toolReceipt'):
            q=Path(t[f]);q=q if q.is_absolute() else PROJECTS/'nx-t5-manuals'/q
            if q.exists():extra.append(archive(q,f"{f}{i}"))
    r=row("t5-models","T5 small/large manual comparison",d['protocol'],["claude-haiku-4-5-20251001","claude-opus-5-5"],"two Notes append/tag/pin and replace/pin tasks",1,"task",[archive(p)]+extra,
          ["Model and manual availability changed together; direct tools were used after loading the manual. No isolated manual causal effect."])
    for manual in (True,False):
        metric(r,f"manual_{manual}_tokens",op("sum",ref("raw","/trials","/totalTokensIncludingCache",{"/manual":manual})),"input+cache-write+output tokens")
        metric(r,f"manual_{manual}_successes",op("sum",ref("raw","/trials","/success",{"/manual":manual})))
    metric(r,"small_manual_token_reduction",op("reduction_percent",op("sum",ref("raw","/trials","/totalTokensIncludingCache",{"/manual":False})),op("sum",ref("raw","/trials","/totalTokensIncludingCache",{"/manual":True}))),"percent")
    finish(r)
    p=PROJECTS/"nx-t14-cascade/scripts/evidence/T14.json";d=read_json(p)
    r=row("t14-cascade","T14 cascade: all cold/warm/script paths","Three exact-field JSON tasks; direct Luna/Sol, cascade cold, warm exact-key replay and compiled script. Independent output readbacks. Quantiles use linear interpolation, distinct from the original nearest-rank n=3 report.",
          ["gpt-6-luna","gpt-6.1-sol","none on warm/script"],"three JSON extraction fixtures",1,"task",[archive(p)],
          ["Warm is an exact request replay in the same workspace. Cold did not materially save tokens. No novel-request or population latency guarantee."])
    for path in sorted({x['path'] for x in d['extractions']}):
        for field in ('tokens','success'):
            metric(r,path+'_'+field,op('sum',ref('raw','/extractions','/'+field,{'/path':path})),"tokens" if field=='tokens' else 'count')
        for q in (.5,.95):metric(r,path+f'_p{int(q*100)}',op('quantile',ref('raw','/extractions','/elapsedMs',{'/path':path}),q),'ms')
    for path in sorted({x['path'] for x in d['autopilot']}):
        for field in ('tokens','success','elapsedMs'):metric(r,'autopilot_'+path+'_'+field,op('sum',ref('raw','/autopilot','/'+field,{'/path':path})),'ms' if field=='elapsedMs' else 'tokens' if field=='tokens' else 'count')
    finish(r)
    p=PROJECTS/"nx-t17-autopilot/scripts/evidence/T17.json";d=read_json(p)
    r=row("t17-autopilot","T17 Autopilot","Three matched multi-ask scratch tasks versus normal Luna; scripts learned in nine model-free warmups; all CLI input+output counted. Actual read/write/runtime effects and item checks recorded.",["gpt-6-luna"],"read-search, edit-confirm, brief-runtime",1,"task",[archive(p)],
          ["Three development tasks; no new-intent guarantee. Edit-confirm was slower with Autopilot. No rendered chat proof. Warmup/authoring costs excluded from task token comparison."])
    for arm in ('autopilot','normal'):
        for field in ('tokens/total','elapsedMs'):metric(r,arm+'_'+field.replace('/','_'),op('sum',ref('raw','/journeys','/'+arm+'/'+field)),'tokens' if field.startswith('tokens') else 'ms')
    metric(r,'token_reduction',op('reduction_percent',op('sum',ref('raw','/journeys','/normal/tokens/total')),op('sum',ref('raw','/journeys','/autopilot/tokens/total'))),'percent')
    metric(r,'human_checkins',op('sum',ref('raw','/journeys','/humanCheckins')))
    finish(r)


def cl_skill():
    base=PROJECTS/'nx-t23-skills/docs/standard/proof/cl-skill-luna'
    paths=[('plain',base/'plain-summary.json'),('cl-final',base/'cl-summary.json')]
    for p in (base/'run1-cl').glob('*summary*.json'):paths.append(('cl-initial',p))
    # The original revision's summary is archived alongside its detailed report.
    if not any(a=='cl-initial' for a,p in paths):
        for p in (base/'run1-cl').glob('*.json'):
            d=read_json(p)
            if 'usage' in d: paths.append(('cl-initial',p))
    receipts=[]
    for arm,p in paths:receipts.append(archive(p,arm,'raw' if 'usage' in read_json(p) else 'aggregate'))
    for arm,folder in [('plain','plain'),('cl-final','cl'),('cl-initial','run1-cl')]:
        p=base/folder/'report.json'
        if p.exists():receipts.append(archive(p,arm+'-checks'))
    r=row('cl-skill','CL-Skill approval-card pilot','One plain approval-card build and final CL-Skill build at medium effort, with the failed initial CL revision retained. Static/check harness outcomes are task checks, not independent task repetitions.',
          ['gpt-6-luna (medium)'],'one approval-card specimen',1,'specimen',receipts,
          ['The final comparison excludes correction cost; the initial CL revision failed blocking checks. No held-out or general visual quality conclusion.'])
    def tokens(arm):return op('sum',ref(arm,'/usage','/input_tokens'),ref(arm,'/usage','/output_tokens'))
    for arm,p in paths:
        metric(r,arm+'_tokens',tokens(arm),'input+output tokens');metric(r,arm+'_seconds',ref(arm,'/seconds'),'s')
    for item in receipts:
        if item['id'].endswith('-checks'):
            for f in ('checksRun','checksPassed','blocking'):
                d=read_json(ROOT/item['path'])
                if isinstance(d.get(f),(int,float)):metric(r,item['id']+'_'+f,ref(item['id'],'/'+f))
    metric(r,'final_token_reduction',op('reduction_percent',tokens('plain'),tokens('cl-final')),'percent')
    finish(r)


def laya():
    audit=read_json(ROOT/'scripts/evidence/A4-source-catalogs/laya.json')
    for entry in audit['rows']:
        receipts=[archive(entry['raw_path']),archive(entry['summary_path'],'summary','aggregate')]
        latency_id='raw'
        if entry.get('source_raw_path'):
            receipts.append(archive(entry['source_raw_path'],'latency-source'))
            latency_id='latency-source'
        r=row(entry['id'],'LAYA · '+entry['id'],audit['method']+' '+entry['kind'],[entry['model']],
              'public easy/standard/hard typed decision tasks; exact IDs, tiers, probabilities and correctness in JSONL',1,'public task',receipts,
              [entry['not_shown'],'Repeated tuning on the public panel; no private/sealed result, population latency CI or fresh deployment repeats. Analytic replay reuses latency from its measured source.'])
        metric(r,'tasks',op('count',ref('raw','', '/id')))
        metric(r,'correct',op('sum',ref('raw','', '/correct')))
        metric(r,'accuracy',op('mean',ref('raw','', '/correct')),'fraction')
        for q in (.5,.95):metric(r,f'p{int(q*100)}_latency',op('multiply',1000,op('quantile',ref(latency_id,'','/latency_s'),q)),'ms')
        summary=read_json(entry['summary_path'])
        for key,calc in [('public_intelligence','public_chance_intelligence'),('brier_mean_valid','multiclass_brier'),('ece','top_label_ece')]:
            metric(r,key,op(calc,ref('raw'),ref(latency_id)), 'public diagnostic score' if key=='public_intelligence' else 'score')
        from efficiency_log import evaluate
        loaded={x['id']:read_json(ROOT/x['path']) for x in receipts}
        for m in r['metrics']:
            if m['name'] in ('public_intelligence','brier_mean_valid','ece'):
                expected=summary['ece']['ece'] if m['name']=='ece' else summary[m['name']]
                import math
                if not math.isclose(evaluate(m['calculation'],loaded),expected,rel_tol=1e-10,abs_tol=1e-10):raise ValueError('LAYA score mismatch: '+entry['id']+'/'+m['name'])
        r['limitations'].append('Chance-corrected score renormalizes public tier weights easy .14/standard .28/hard .30; judge/private/sealed/cost axis unavailable. Calibration uses valid distributions only.')
        finish(r)


def dictation():
    base=PROJECTS/'dictation-phonon2/runs/phonon2/engine-bench'
    for p in sorted(base.glob('*.json')):
        d=read_json(p)
        r=row('dictation-engine-'+p.stem,'Dictation engine · '+p.stem,
              'Archived Phonon-2 engine finish-to-answer benchmark; cached real voice audio streamed at real-time pace, GPU fp16. Read raw samples rather than rounded Markdown. Linear-interpolated latency quantiles. '+str(d['summary'].get('label','')),
              ['Phonon-2'],'short real-voice clips and long concatenations of the same clips; repeated release delays remain the same utterance', 'one pass, or three release delays per clip (48 records)','original utterance; long samples overlap short ones',[archive(p)],
              ['Not physical microphone end-to-end latency. GPU activity during speech changes the warm clock state. No independent speech population CI. Tuning reused the same clips; WER references are authored.'])
        if d['clips']:
            metric(r,'short_samples',op('count',ref('raw','/clips','/id')))
            metric(r,'short_mean_wer',op('mean',ref('raw','/clips','/wer')),'fraction')
            for q in (.5,.95):metric(r,f'short_p{int(q*100)}',op('quantile',ref('raw','/clips','/release_to_final_ms'),q),'ms')
        if isinstance(d['summary'].get('long'),dict):
            for f in ('wer','release_to_final_ms'):
                metric(r,'long_'+f,ref('raw','/summary/long/'+f),'ms' if f.endswith('_ms') else 'fraction')
        elif d['summary'].get('long'):
            metric(r,'long_samples',op('count',ref('raw','/summary/long','/wer')))
            metric(r,'long_p50',op('median',ref('raw','/summary/long','/release_to_final_ms')),'ms')
            metric(r,'long_max',op('max',ref('raw','/summary/long','/release_to_final_ms')),'ms')
            if all('ref_words' in x for x in d['summary']['long']):
                terms=[op('multiply',ref('raw',f'/summary/long/{i}/wer'),ref('raw',f'/summary/long/{i}/ref_words')) for i,x in enumerate(d['summary']['long'])]
                metric(r,'long_corpus_wer',op('divide',op('sum',terms),op('sum',ref('raw','/summary/long','/ref_words'))),'fraction')
        if r['metrics']:finish(r)
    p=PROJECTS/'nx-t1-dictation/scripts/evidence/T1.json';d=read_json(p)
    r=row('t1-dictation','T1 prompt dictation backend journey','Real recorded clips streamed through the backend engine; release to backend final response, not screen insertion.', ['Phonon-2'], 'two natural voice recordings',1,'utterance',[archive(p)],
          ['Physical microphone quality and cold startup remain unmeasured/failed. French/mixed recognizer missing. Different path and clocks from engine-only measurements.'])
    for i,c in enumerate(d['clips']):metric(r,'clip'+str(i)+'_release_to_text',ref('raw',f'/clips/{i}/releaseToTextMs'),'ms')
    finish(r)


def perception():
    base=PROJECTS/'nx-t18-perception'
    p=base/'scripts/evidence/T18.json';d=read_json(p)
    raw=[]
    for i,e in enumerate(d['evaluations']):
        q=base/e['evidenceRoot']/'result.json'
        if q.exists():raw.append(archive(q,f'case{i}'))
    r=row('t18-perception','T18 text versus screenshots','Three matched native/web/chart tasks after repairs; Luna routes; text image lane pays an extra vision extraction pass. Cached input counted once in total input.',
          ['gpt-6-luna'],'native, web and chart',1,'task',raw+[archive(p,'summary','aggregate')],
          ['Narrow repaired panel; screenshot and text both succeed. Text used fewer tokens but was slower when extraction is included. Earlier adverse attempts remain in the source receipt.'],status='aggregate-only')
    # Compound extraction is recorded by the final source receipt; keep its boundary explicit.
    for lane in ('text','screenshot'):
        for f in ('successes','tasks','totalTokensIncludingExtraction','totalSecondsIncludingExtraction'):
            metric(r,lane+'_'+f,ref('summary','/comparison/'+lane+'/'+f),'tokens' if 'Tokens' in f else 's' if 'Seconds' in f else 'count')
    finish(r)
    for p in sorted((base/'scripts/evidence/T18-runs').glob('*/result.json')):
        if p.resolve().as_posix() in SOURCES:continue
        data=read_json(p)
        r=row('t18-attempt-'+p.parent.name,'T18 earlier attempt · '+p.parent.name,
              'Original retained task result before the final repaired panel; counts include failed outcomes. CLI usage input includes cached input once. No image-extraction charge is added to this agent-only receipt.',
              [data['model']],data['task']+' / '+data['lane'],1,'task',[archive(p)],
              ['Development attempt, not an independent replication of the final panel. Image extraction/setup and earlier repair costs excluded here; no causal efficiency/generalization claim.'])
        metric(r,'success',ref('raw','/passed'))
        metric(r,'agent_tokens',op('sum',ref('raw','/usage/input_tokens'),ref('raw','/usage/output_tokens')),'input+output tokens')
        metric(r,'agent_seconds',ref('raw','/seconds'),'s')
        finish(r)


def evolver():
    p=PROJECTS/'nx-t13-evolver/scripts/evidence/T13-runs/state.json'
    data=read_json(p)
    groups=sorted({(x['domain'],x['genome'],x['panel']) for x in data['observations']})
    for domain,genome,panel in groups:
        r=row('t13-'+domain+'-'+genome[:12]+'-'+panel,'T13 frozen Evolver cases · '+domain+'/'+panel+'/'+genome[:12],
              'Original retained per-case observations from the owned Evolver snapshot; exact genome/panel/item/seed and model/judge receipt in each observation. Frozen panel and sequential trial lineage in state. Model and compiled/pure-procedure candidates may use different mechanisms.',
              ['gpt-6-luna or deterministic compiled procedure; exact route in case receipt'],
              'frozen Notes/manual or CL-Skill fixture panel; IDs and judges in archived state','one seed-bound retained observation per case; cache reuse is not an independent run','frozen case',[archive(p)],
              ['Local domain promotion is not production promotion. Discovery and held-out panels stay separate. Multiple tuning trials and familywise gates are in original state; no fresh deployment population CI. Dictation replay domain was not evaluated in this source snapshot.'])
        selected=ref('raw','/observations','/result',{'/domain':domain,'/genome':genome,'/panel':panel})
        metric(r,'observations',op('count',selected))
        for f in ('tokens','success','fitness'):
            metric(r,f+'_mean',op('mean',op('decode_field',selected,'/objectives/'+f)),'tokens' if f=='tokens' else 'fraction' if f=='success' else 'source fitness')
        finish(r)


def numeric_leaves(value,path=''):
    """Supplementary published metrics, not fixtures/data or fabricated sample zeros."""
    if isinstance(value,dict):
        for key,item in value.items():
            if re.search(r'nas|credential|secret|password|auth',key,re.I):continue
            here=path+'/'+key.replace('~','~0').replace('/','~1')
            if isinstance(item,(int,float)) and not isinstance(item,bool) and re.search(r'token|latency|_ms$|seconds|accuracy|correct|_wer|p50|p95|fit_ms|adherence|quality|improvement',key,re.I):yield here,item
            elif isinstance(item,dict):yield from numeric_leaves(item,here)


def supplementary():
    """Keep other published result summaries visible with an honest aggregate boundary."""
    selected=[]
    for folder in LAYA.glob('evidence/*'):
        if not folder.is_dir() or re.search(r'nas|source-backup|source-final|asset-project',folder.name,re.I):continue
        for name in ('execution-summary.json','summary.json','result.json','acceptance.json'):
            p=folder/name
            if p.exists() and folder.name not in ('jevbench','r2'):selected.append(p)
    for name in ('baseline-evidence.json','system1-acceptance.json','hook-cache-acceptance.json','browser-baseline.json','browser-after-correction.json','browser-choice-rerank.json','browser-score-rerank.json','live-tasks.json'):
        if (LAYA/'evidence'/name).exists():selected.append(LAYA/'evidence'/name)
    audit=read_json(ROOT/'scripts/evidence/A4-source-catalogs/laya.json')
    for x in audit.get('other_receipts',[]):selected.append(Path(x['path']))
    extended={x['summary_path']:x for x in audit.get('extended_studies',[])}
    selected += [Path(p) for p in extended]
    for name in ('manual_first_before.json','manual_first_after.json','manual_first_agent_usage.json'):
        selected.append(PROJECTS/'nx-manual-first/docs/evidence'/name)
    selected.append(PROJECTS/'nx-t13-evolver/scripts/evidence/T13.json')
    for p in sorted(set(selected)):
        if not p.exists():continue
        d=read_json(p);numbers=list(numeric_leaves(d))
        entry=extended.get(str(p))
        if not numbers and not entry:continue
        relative=p.relative_to(LAYA/'evidence') if p.is_relative_to(LAYA/'evidence') else p.relative_to(PROJECTS)
        id='supplement-'+relative.with_suffix('').as_posix().replace('/','-')
        extra=[archive(q,'support'+str(i)) for i,q in enumerate(entry.get('raw_paths',[]))] if entry else []
        r=row(id,'Supplementary published result · '+relative.as_posix(),
              (entry['method'] if entry else 'Author-generated result summary; original experimental details in archived source.')+' A4 verifies stored bytes and pointers; supplementary summary metrics have no independent per-case regrade.',
              [str(d.get('model','LAYA / deterministic host' if str(p).startswith(str(LAYA)) else 'see source receipt'))],
              'source-specific pilot; original scope in archived receipt', 'one pilot unless recorded otherwise in source','source-specific; independence not established',[archive(p,'summary','aggregate')]+extra,
              [entry['limitations'] if entry else 'No deployment or general 50 ms/visual-quality/transfer conclusion.', 'Aggregate-only: supplementary metrics are stored reported values, not independently rescored from samples.'],status='aggregate-only' if numbers else 'unverified')
        for path,value in numbers:metric(r,path,ref('summary',path),'source unit (field name)')
        finish(r)
    # CPU has raw case samples, so its accuracy/latency also get a separate raw-verified row.
    cpu=next((x for x in audit.get('extended_studies',[]) if x['id']=='laya-cpu-fp32-public'),None)
    if cpu:
        p=Path(cpu['raw_paths'][0]);d=read_json(p)
        r=row(cpu['id'],'LAYA CPU FP32 public decisions',cpu['method'],['LAYA CPU FP32, four threads'],
              'same public typed-decision corpus',1,'task',[archive(p)],[cpu['limitations']])
        metric(r,'tasks',op('count',ref('raw','','/correct')))
        metric(r,'correct',op('sum',ref('raw','','/correct')))
        key=next(k for k in ('latency_ms','elapsed_ms','latency_s') if k in d[0])
        for q in (.5,.95):metric(r,f'p{int(q*100)}',op('multiply',1000 if key.endswith('_s') else 1,op('quantile',ref('raw','','/'+key),q)),'ms')
        finish(r)


def discover():
    """Metadata-only whole-corpus inventory, with protected paths and junctions excluded."""
    roots=[]
    for tree in sorted(PROJECTS.glob('nx-*')):
        if not tree.is_dir():continue
        for sub in ('scripts/evidence','docs/evidence','docs/standard/proof','docs/research'):
            p=tree/sub
            if p.exists():roots.append(p)
    roots += [PROJECTS/'plans/logs',LAYA/'evidence']
    counts=[]; candidates={}; exclusions=[]
    for root in roots:
        files=0
        for current,dirs,names in os.walk(root,followlinks=False):
            dirs[:]=[n for n in dirs if not re.search(r'nas|credential|secret|\.git|node_modules|A4-receipts|source-backup|source-final',n,re.I) and not Path(current,n).is_junction() and not Path(current,n).is_symlink()]
            for name in names:
                p=Path(current,name)
                if p.suffix not in ('.json','.jsonl','.md','.log','.txt'):continue
                if re.search(r'credential|nas|password|secret|A4-codex-run|^A4',name,re.I):continue
                files+=1
                # Root summaries and benchmark summaries are candidates; case/turn files are dependencies.
                rel=p.relative_to(root).as_posix()
                if name in ('summary.json','execution-summary.json','result.json') and not re.search(r'task-|rep-|turn-|T18-runs|T14-runs|cl11/|cl/',rel):
                    candidates.setdefault(rel,[]).append(p.as_posix())
                elif p.parent==root and re.search(r'manual|CL|T1[3478]|T5|dictation|efficien|revolution|benchmark',name,re.I):
                    candidates.setdefault(rel,[]).append(p.as_posix())
        counts.append({'root':root.as_posix(),'evidence_files':files})
    return {'schema':'neyvia.efficiency-coverage.v1','roots':counts,'candidates':candidates,
            'policy':'Metadata inventory scans all listed evidence roots and plans logs; imported studies use exact local raw paths, deduplicated by hash. Model/service startup, secrets, NAS records, runtime state databases and junctions excluded.',
            'limitations':['Logs are leads, not measurements. Summaries without raw samples remain aggregate-only; historical prose-only numbers are unverified.',
                           'Corpus is a point-in-time snapshot. New benchmark results append through the CLI; rerunning discovery is required to discover later studies.'],
            'imported_source_hashes':SOURCES,'result_ids':[r['id'] for r in ROWS]}


def prose_claims():
    """Retain claims found in plan handoffs without treating prose as raw samples."""
    logs=PROJECTS/'plans/logs'
    paths=list(logs.glob('*-last.txt'))+list(logs.glob('*.md'))
    for p in sorted(paths):
        if re.search(r'nas|credential|password|secret|A4',p.name,re.I):continue
        text=p.read_text(encoding='utf-8-sig',errors='replace')
        # Runtime/tool counts alone are functional proof, not efficiency experiments.
        if not re.search(r'\d[^\n]{0,80}(tokens|WER|latency|context)|(?:tokens|WER|latency|context)[^\n]{0,80}\d',text,re.I):continue
        r=row('prose-'+p.stem,'Historical handoff claim · '+p.name,
              'Historical prose retained as a discovery lead. Any matching verified study above is authoritative; no numeric result is manufactured from the handoff.',
              ['see original handoff; not independently attested'],'handoff-specific; may overlap a logged study','not independently specified','unknown',[archive(p,'handoff','prose')],
              ['Unverified prose source: rounded or incomplete comparisons are not raw receipts. This is not an additional independent benchmark or a new result.'],status='unverified')
        finish(r)
    p=LAYA/'LAYA-INSTANT-LEARNING-PLAN.md'
    r=row('laya-old-visual-missing-raw','LAYA older structured-visual claim',
          'The LAYA plan quotes a historical 120-image visual p50/p95 of 13.11/40.00 ms. The referenced original raw latency receipt is absent from the supplied LAYA project; these are unverified quotes, not A4 measurements.',
          ['historical LAYA structured visual; exact runtime unverified'],'historical image panel','unverified','unverified',[archive(p,'plan','prose')],
          ['No raw receipt found in supplied corpus; cannot verify the quoted latency, repetitions, timing boundary, or general 50 ms behavior.'],status='unverified')
    finish(r)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger',type=Path,default=LEDGER)
    args=parser.parse_args()
    if args.ledger.exists():parser.error('Existing ledger preserved; import to a new path')
    for fn in (model_cases,comparisons,pilots,cl_skill,laya,dictation,perception,evolver,supplementary,prose_claims):
        fn();print(json.dumps({'imported':fn.__name__,'results':len(ROWS)}),flush=True)
    coverage=discover()
    atomic_write(ROOT/'docs/research/coverage.json',json.dumps(coverage,ensure_ascii=False,indent=2)+'\n')
    atomic_write(args.ledger,''.join(json.dumps(r,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n' for r in ROWS))
    atomic_write(ROOT/'docs/research/efficiency-log.md',render(ROWS))
    print(json.dumps({'ok':True,'results':len(ROWS),'archived_receipts':len(set(SOURCES.values())),'metric_count':sum(len(r['metrics']) for r in ROWS)}))


if __name__=='__main__':main()
