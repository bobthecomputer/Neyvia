"""Seal observed C13f evidence; never infer quality or usage from artifact existence."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import shutil

WT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(WT/'src'))
from grant_agent.taste_model import rejected_before_inference

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def bound(path):return {'path':str(Path(path).relative_to(WT)).replace('\\','/'),'sha256':sha(path)}
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def seal():
    runs=[]
    for arm,model in [('arm-luna','gpt-6-luna'),('arm-sol','gpt-6.1-sol')]:
        for task,name,ceiling in [('T1','landing.html',.45),('T2','rare-ui.html',1.10)]:
            root=WT/'proof/r8'/arm/('final/T1' if task=='T1' else task)
            calls=[]
            for path in sorted(root.rglob('usage.json')):
                receipt=read(path);events=path.parent/'events.jsonl'
                if not receipt.get('usageComplete') and events.exists() and rejected_before_inference(events.read_text(encoding='utf-8')):
                    receipt={**receipt,'usageComplete':True,'costUsd':0,'rejectedBeforeInference':True}
                calls.append({'receipt':bound(path),'phase':str(path.parent.relative_to(root)).replace('\\','/'),
                    **{k:receipt.get(k) for k in ('model','usage','usageComplete','costUsd','elapsedSec','exitCode','timedOut','searchEnabled','rejectedBeforeInference','inputBreakdown')}})
            rounds_path=root/'evidence/rounds.json'
            rows=next(iter(read(rounds_path).values()),[]) if rounds_path.exists() else []
            last=rows[-1] if rows else None
            result_path=root/'result.json'
            failure_path=root/'failure.json'
            result=read(result_path) if result_path.exists() else read(failure_path) if failure_path.exists() else {}
            output=root/'work'/name
            total={k:sum(c.get('usage',{}).get(k,0) for c in calls) for k in ('input_tokens','cached_input_tokens','output_tokens')}
            total['total_tokens']=total['input_tokens']+total['output_tokens']
            cost=sum(c['costUsd'] or 0 for c in calls)
            usage_known=bool(calls) and all(c['usageComplete'] for c in calls)
            quality=last['critique']['quality'] if last else None
            screenshots=[bound(s['path'])|{k:s[k] for k in ('viewport','theme')} for s in last['interaction']['screenshots']] if last else []
            high=[d for d in last['critique']['differences'] if d['gap']>=2] if last else None
            attempted=sum(1 for c in calls if c['phase'].split('/')[-1]=='attempt-1' or c['phase'].split('/')[-1].startswith('attempt-1-resume-'))
            admissions=root/'review-admissions.json'
            if admissions.exists():attempted=max(attempted,len(read(admissions)))
            run={'arm':arm,'task':task,'model':model,'freshTaskSha256':sha(WT/'proof/r6-blind/tasks.md'),
                'doneOk':bool(result.get('doneOk')),'qualityProven':bool(result.get('doneOk') and last and last['interaction']['passed'] and last['fidelity']['passed'] and not high),
                'tokens':total,'usageComplete':usage_known,'knownCostUsd':cost,'costUsd':cost if usage_known else None,
                'priceCeilingUsd':ceiling,'withinPriceCeiling':usage_known and cost<=ceiling,
                'modelElapsedSec':sum(c['elapsedSec'] or 0 for c in calls),'rounds':len(rows),'attemptedReviewRounds':attempted,'roundCeiling':6,
                'withinRoundCeiling':attempted<=6,'rubricScore':quality,
                'qualityByRound':[r['critique']['quality'] for r in rows],'highSeverityDifferences':high,
                'driverPass':last['interaction']['passed'] if last else None,'fidelity':last['fidelity'] if last else None,
                'anchorVerdict':last['critique']['anchorVerdict'] if last else None,
                'rubricByRound':[r['critique']['rubric'] for r in rows],
                'screenshots':screenshots,'calls':calls,'error':result.get('error')}
            if calls:
                began=min((WT/c['receipt']['path']).stat().st_mtime-(c['elapsedSec'] or 0) for c in calls)
                finished=result_path.stat().st_mtime if result_path.exists() else failure_path.stat().st_mtime if failure_path.exists() else time.time()
                run['wallElapsedSec']=max(0,finished-began)
            if output.exists():
                delivery=WT/'proof/r8'/arm/name
                shutil.copyfile(output,delivery)
                run['output']=bound(output);run['delivery']=bound(delivery)
            if task=='T1':
                preflight_root=WT/'proof/r8'/arm/'T1'
                preflight=[{'receipt':bound(p),**read(p)} for p in preflight_root.rglob('usage.json')]
                run['preservedPreflight']={'root':str(preflight_root.relative_to(WT)).replace('\\','/'),
                    'reason':'Incorrect shared rare-task prompt overburdened landing. Corrected fresh landing executions are explicitly under final/T1; no paid evidence discarded.',
                    'knownCostUsd':sum(p.get('costUsd') or 0 for p in preflight),'calls':preflight}
            if result_path.exists():run['result']=bound(result_path)
            if failure_path.exists():run['failure']=bound(failure_path)
            if rounds_path.exists():run['roundEvidence']=bound(rounds_path)
            runs.append(run)
    failure=WT/'scripts/evidence/C13f-failure/render/report.json'
    failed=read(failure) if failure.exists() else None
    source_files=['scripts/c13_run.py','scripts/c13_render.mjs','scripts/c13f_seal.py','src/grant_agent/taste_budget.py',
        'src/grant_agent/taste_context.py','src/grant_agent/taste_model.py','src/grant_agent/taste_gate.py','src/grant_agent/cl/turn_context.py',
        'docs/manuals/taste-efficiency.md','tests/c13-budget.test.mjs','tests/c13-context.test.mjs']
    prices=read(WT/'config/scroll-study-prices.json')
    report={'schema':'neyvia.C13f.v1','createdAtUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'scope':'Four fresh R6 task executions; production CL host and Neyvia Obscura, no visible browser or provider substitution',
        'allTargetsProven':all(r['qualityProven'] and r['withinPriceCeiling'] and r['withinRoundCeiling'] for r in runs),
        'knownBenchmarkCostUsd':sum(r['knownCostUsd'] for r in runs),
        'knownPreflightCostUsd':sum(r.get('preservedPreflight',{}).get('knownCostUsd',0) for r in runs),
        'runs':runs,'prices':prices,'priceVerification':{'date':'2026-10-05','sources':prices['_provenance']['sources']},
        'mechanism':{'cachedConceptAndResearch':True,'targetedHashCheckedPatches':True,'context':'C4 TurnContext with exact o200k measured admission and durable archives',
            'sectionImages':'Actual changed-region Obscura crops, maximum 640x640; untouched open defects retained; fresh global completion verification',
            'earlyStop':'All ten rubric scores >=3, image critic tie/win, no gap>=2, interaction and fidelity passes; done verifies hashes',
            'budget':'Hard round and next-call admission; post-turn measured totals include cached input; exact provider in-flight cap unavailable'},
        'failurePath':{'report':bound(failure),'passed':failed['passed'],'variants':[{'viewport':v['viewport'],'theme':v['theme'],'passed':v['passed'],
            'failedModes':[m['mode'] for c in v['controls'] for m in c['modes'] if not m.get('effect')]} for v in failed['variants']]} if failed else None,
        'sourceFiles':[bound(WT/p) for p in source_files],
        'C4Reuse':{'branch':'track/c4-tokens','path':'src/grant_agent/cl/turn_context.py','verifiedGitBlob':'72748f2b98afc64b1cf4cdc099d5c301d2c9294f','mergeRequired':False},
        'limitations':['Installed codex exec emits usage after turn completion; a call may overshoot its reservation. This is not an exact provider token cap.',
            'C13f section was absent from the requested 15-complete-everything.md; user message supplied scope.',
            'No public promotion, push, merge, NAS synchronization or forbidden service access.']}
    checks=WT/'scripts/evidence/C13f-checks.log'
    if checks.exists():report['checks']=bound(checks)
    (WT/'scripts/evidence/C13f.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'allTargetsProven':report['allTargetsProven'],'runs':[{k:r[k] for k in ('arm','task','doneOk','rounds','rubricScore','costUsd')} for r in runs]}))

if __name__=='__main__':seal()
