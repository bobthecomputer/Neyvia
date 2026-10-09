"""Verify real provider usage/artifact bindings, compute CIs and seal C4c."""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import zipfile
REPO=Path(__file__).resolve().parents[1]
BOUND_SOURCES=('scripts/seal_c4c.py','scripts/report_c4c.py','scripts/verify_c4c_pressure.py',
               'scripts/judge_c4c.py','scripts/repair_c4c_collection.py','scripts/resume_c4c_transport.py',
               'scripts/verify_c4c_transport.py',
               'docs/manuals/efficient-context.md')
sys.path.insert(0,str(REPO/'src'))
from grant_agent.cl.provider11 import usage_counts
from run_c4c import cost,PRICES
import c4c_quality as r5
from repair_c4c_collection import patched

def digest(data):return hashlib.sha256(data).hexdigest()
def wilson(successes,n):
    if not n:return None
    z=1.959963984540054;p=successes/n;den=1+z*z/n
    center=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0,center-half),min(1,center+half)]
def mean_ci(values,lower=None,upper=None):
    if not values:return {'n':0,'mean':None,'ci95':None}
    mean=statistics.mean(values)
    if len(values)<2:return {'n':len(values),'mean':mean,'ci95':None}
    critical={1:12.706204736,2:4.30265273,3:3.182446305,4:2.776445105}.get(len(values)-1,1.9599639845)
    half=critical*statistics.stdev(values)/math.sqrt(len(values));lo,hi=mean-half,mean+half
    return {'n':len(values),'mean':mean,'ci95':[max(lower,lo) if lower is not None else lo,min(upper,hi) if upper is not None else hi],
            'method':'Student t; n=2 has 1 degree of freedom, very wide intervals; no population guarantee'}
def percentile(values,p):
    values=sorted(values);pos=p*(len(values)-1);low=int(pos);fraction=pos-low
    return values[low]*(1-fraction)+values[min(low+1,len(values)-1)]*fraction

def provider_totals(directory):
    totals={k:0 for k in usage_counts(None)};completed=0;incomplete=[]
    for path in directory.rglob('events.jsonl'):
        events=[]
        for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
            try:events.append(json.loads(line))
            except ValueError:pass
        ends=[e for e in events if e.get('type')=='turn.completed']
        if not ends:incomplete.append(path.relative_to(REPO).as_posix())
        for event in ends:
            for key,value in usage_counts(event.get('usage')).items():totals[key]+=value
            completed+=1
    return {'tokens':totals,'costUsd':cost(totals),'completedProviderEvents':completed,
            'incompleteUsagePaths':incomplete,'scope':'Observed completed provider events; interrupted usage is a lower bound'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--append',action='store_true');a=p.parse_args()
    if Path(a.run_id).name!=a.run_id:raise ValueError('One folder name required')
    base=REPO/'.agent_control/c4'/a.run_id;freeze=json.loads((base/'frozen.json').read_text(encoding='utf-8'))
    assert freeze['pricesUsdPerMillion']==PRICES, 'Price record drift'
    fixes=json.loads((base/'post-collection-fixes.json').read_text(encoding='utf-8')) if (base/'post-collection-fixes.json').exists() else {}
    for name,expected in freeze['sourceSha256'].items():
        frozen_bytes=(base/'sources'/name).read_bytes()
        assert digest(frozen_bytes)==expected, name
        current=(REPO/name).read_bytes()
        if digest(current)!=expected:
            assert name in fixes and current==patched(name,frozen_bytes), 'Unexpected source drift: '+name
            assert digest(current)==fixes[name]['fixedSha256']
    replacements=json.loads((base/'pair-replacements.json').read_text(encoding='utf-8')) if (base/'pair-replacements.json').exists() else {}
    rows=[];indexes={}
    for task in freeze['tasks']:
        for rep in (1,2):
            for arm in ('efficient','control'):
                original_path=base/f'rep-{rep}'/arm/task['id']/'result.json'
                path=REPO/replacements['trials'][task['id']+'/'+str(rep)][arm] if task['id']+'/'+str(rep) in replacements.get('trials',{}) else original_path
                assert path.is_file(), 'Missing required trial: '+str(path)
                row=json.loads(path.read_text(encoding='utf-8'))
                assert (row['task'],row['repetition'],row['arm'])==(task['id'],rep,arm)
                if row['status']=='attempted':
                    assert row['taskSha256']==digest(task['task'].encode()), 'Task drift'
                    usage=provider_totals(path.parent/'run')['tokens']
                    assert usage==row['run']['tokens'], 'Provider usage mismatch: '+str(path)
                    assert abs(cost(usage)-row['costUsd'])<1e-12
                    for name,expected in row['run'].get('sourceSha256',{}).items():
                        assert digest((REPO/name).read_bytes())==expected, 'Run source drift: '+name
                    expected_flags={'procedures':arm=='efficient','diffs':arm=='efficient','compaction':arm=='efficient',
                                    'batching':arm=='efficient','shortStablePrefix':arm=='efficient'}
                    assert row['run']['mechanisms']==expected_flags
                    if arm=='efficient':
                        assert all(t['hostPromptTokens']<=row['run']['hostBudgetTokens'] for t in row['run']['turns'])
                    for quality in row['run'].get('qualityRuns',[]):
                        if quality.get('receipt'):
                            receipt=Path(quality['receipt']);assert receipt.is_file()
                else:
                    assert task['id']=='t5-cua' and not row['run']['tokens'] and not row['run']['turns']
                row['receipt']=path.relative_to(REPO).as_posix();row['receiptSha256']=digest(path.read_bytes())
                rows.append(row);indexes[(task['id'],rep,arm)]=row
    judges={};judge_usage=provider_totals(base/'judges')
    judge_paths=list((base/'judges').glob('*/result.json'))
    judge_paths=[REPO/replacements['reviews'].get(p.parent.name,p.relative_to(REPO).as_posix()) for p in judge_paths] if replacements.get('reviews') else judge_paths
    for path in judge_paths:
        r=json.loads(path.read_text(encoding='utf-8'));judges[(r['task'],r['repetition'])]=r
        assert r['tokens']==provider_totals(path.parent)['tokens'], 'Judge usage mismatch'
        assert r['rubricSha256']==freeze['sourceSha256']['config/c4c-rubric.json']
    assert len(judges)==34, 'Need the 34 non-native paired reviews'
    selected_usage={key:sum(r['tokens'][key] for r in judges.values()) for key in usage_counts(None)}
    judge_usage={'tokens':selected_usage,'costUsd':cost(selected_usage),'scope':'34 selected reviews; replaced reviews remain charged in wholeObservedWork'}
    per_task=[]
    for task in freeze['tasks']:
        entry={'task':task['id'],'round':task['round'],'arms':{}}
        for arm in ('efficient','control'):
            group=[indexes[(task['id'],rep,arm)] for rep in (1,2)]
            attempted=[r for r in group if r['status']=='attempted']
            scores=[]
            for rep in (1,2):
                judge=judges.get((task['id'],rep))
                if judge and judge['passed']:
                    label=next(k for k,v in judge['labelArms'].items() if v==arm)
                    scores.append(statistics.mean(judge['review'][label].values()))
            successes=sum(bool(r.get('passed')) for r in attempted)
            fractions=[sum(bool(v) for v in r['quality'].get('checks',{}).values())/max(1,len(r['quality'].get('checks',{}))) for r in attempted]
            metrics={key:mean_ci([r['run']['tokens'].get(key,0) for r in attempted],lower=0) for key in ('total','cachedInput','input','output')}
            entry['arms'][arm]={'attempts':len(attempted),'waiting':len(group)-len(attempted),'successes':successes,
                'successRate':successes/len(attempted) if attempted else None,'successCi95':wilson(successes,len(attempted)),
                'tokenTotals':{k:sum(r['run']['tokens'].get(k,0) for r in attempted) for k in ('total','cachedInput','input','output')},
                'tokensPerRun':metrics,'totalCostUsd':sum(r['costUsd'] for r in attempted),
                'costPerRun':mean_ci([r['costUsd'] for r in attempted],lower=0),
                'objectiveCheckFraction':mean_ci(fractions,lower=0,upper=1),'blindedQuality0to4':mean_ci(scores,lower=0,upper=4),
                'qualityScope':'Objective constraints/workloads plus uncalibrated blinded Luna review; human preference/taste equivalence unproven'}
        if task['id']!='t5-cua':
            entry['pairedTotalTokenDifference']=mean_ci([indexes[(task['id'],rep,'efficient')]['run']['tokens']['total']-indexes[(task['id'],rep,'control')]['run']['tokens']['total'] for rep in (1,2)])
        per_task.append(entry)
    totals={}
    for arm in ('efficient','control'):
        group=[r for r in rows if r['arm']==arm and r['status']=='attempted'];successes=sum(bool(r['passed']) for r in group)
        totals[arm]={'attempts':len(group),'successes':successes,'successCi95':wilson(successes,len(group)),
                     'tokens':{k:sum(r['run']['tokens'].get(k,0) for r in group) for k in usage_counts(None)},
                     'costUsd':sum(r['costUsd'] for r in group)}
    usable=[e for e in per_task if e['task']!='t5-cua'];rng=random.Random(41729);samples={'totalTokenSavingsPercent':[],'costSavingsPercent':[],'successDifference':[],
        'objectiveCheckFractionDifference':[],'blindedQualityDifference0to4':[]}
    for _ in range(10000):
        drawn=[rng.choice(usable) for _ in usable]
        et=sum(e['arms']['efficient']['tokenTotals']['total'] for e in drawn);ct=sum(e['arms']['control']['tokenTotals']['total'] for e in drawn)
        ec=sum(e['arms']['efficient']['totalCostUsd'] for e in drawn);cc=sum(e['arms']['control']['totalCostUsd'] for e in drawn)
        samples['totalTokenSavingsPercent'].append(100*(1-et/ct) if ct else 0)
        samples['costSavingsPercent'].append(100*(1-ec/cc) if cc else 0)
        samples['successDifference'].append(statistics.mean(e['arms']['efficient']['successRate']-e['arms']['control']['successRate'] for e in drawn))
        samples['objectiveCheckFractionDifference'].append(statistics.mean(e['arms']['efficient']['objectiveCheckFraction']['mean']-e['arms']['control']['objectiveCheckFraction']['mean'] for e in drawn))
        rated=[e for e in drawn if all(e['arms'][arm]['blindedQuality0to4']['mean'] is not None for arm in ('efficient','control'))]
        if rated:samples['blindedQualityDifference0to4'].append(statistics.mean(e['arms']['efficient']['blindedQuality0to4']['mean']-e['arms']['control']['blindedQuality0to4']['mean'] for e in rated))
    confidence={key:[percentile(values,.025),percentile(values,.975)] if values else None for key,values in samples.items()}
    pressure=[]
    for budget in (2000,2200):
        d=REPO/'.agent_control/c4'/f'c4c-pressure-guided-{budget}'
        for path in d.glob('rep-*/*/*/result.json'):
            r=json.loads(path.read_text(encoding='utf-8'));assert r['run']['tokens']==provider_totals(path.parent/'run')['tokens']
            pressure.append({'budget':budget,'repetition':r['repetition'],'passed':r['passed'],'tokens':r['run']['tokens'],
                             'contextMetrics':r['run']['contextMetrics'],'costUsd':r['costUsd'],'receipt':path.relative_to(REPO).as_posix(),
                             'procedureSha256':r['procedureSha256'],'scope':r['scope']})
    assert len(pressure)==4, 'Need two repetitions at each small budget'
    overhead_dirs=[d for d in (REPO/'.agent_control/c4').iterdir() if d.is_dir() and d.name.startswith('c4c-') and d!=base]
    observed_overhead={d.name:provider_totals(d) for d in overhead_dirs}
    # C4b is outside this study; account only for the selected final matrix and C4c attempts.
    accounted=[provider_totals(base),*observed_overhead.values()]
    whole_work={'tokens':{k:sum(r['tokens'][k] for r in accounted) for k in usage_counts(None)},
                'costUsd':sum(r['costUsd'] for r in accounted),
                'completedProviderEvents':sum(r['completedProviderEvents'] for r in accounted),
                'incompleteUsagePaths':[p for r in accounted for p in r['incompleteUsagePaths']],
                'scope':'Final matrix, blinded reviews, failed/invalid studies and low-budget diagnostics; excludes unavailable lead/sub-agent usage'}
    output=REPO/'scripts/evidence/C4c';output.mkdir(exist_ok=True)
    bundle_path=output/'runs.zip';manifest=[]
    for directory in [base,*overhead_dirs]:
        for path in directory.rglob('*'):
            if path.is_file() and '__pycache__' not in path.relative_to(directory).parts:
                manifest.append({'name':directory.name+'/'+path.relative_to(directory).as_posix(),'path':path,'sha256':digest(path.read_bytes()),'bytes':path.stat().st_size})
    # Preserve the original supplied scorers/inputs and out-of-scope baseline records.
    # Read only exact fixture filenames already recorded at preparation; never a key/holdout.
    extras={}
    for row in rows:
        for name,expected in row['run'].get('sourceSha256',{}).items():
            source=REPO/name
            assert source.resolve().is_relative_to(REPO) and digest(source.read_bytes())==expected
            extras['source-bindings/'+name]=source
    for name in BOUND_SOURCES:
        extras['source-bindings/'+name]=REPO/name
    trial_paths=[REPO/r['receipt'] for r in rows]
    trial_paths += [p for d in overhead_dirs for p in d.glob('rep-*/*/*/result.json')]
    for trial_path in trial_paths:
        trial=json.loads(trial_path.read_text(encoding='utf-8'))
        if trial.get('round')!=2 or trial.get('status')!='attempted' or (trial_path.parent/'.review-only').exists():continue
        preparation=trial.get('preparation',{})
        trusted=r5._trusted_state((trial_path.parent/'workspace').resolve())
        assert json.loads(trusted.read_text(encoding='utf-8'))==preparation, 'Trusted baseline drift'
        extras['trusted-baselines/'+trusted.name]=trusted
        for name,expected in preparation.get('sources',{}).items():
            assert Path(name).name==name and not any(s in name.lower() for s in ('holdout','answer','spoiler'))
            source=r5.FIXTURES/trial['task']/name
            assert digest(source.read_bytes())==expected, 'Original fixture drift'
            extras['r5-inputs/'+trial['task']+'/'+name]=source
    extras['prices/scroll-study-prices.json']=REPO/'config/scroll-study-prices.json'
    for name,path in extras.items():
        manifest.append({'name':name,'path':path,'sha256':digest(path.read_bytes()),'bytes':path.stat().st_size})
    with zipfile.ZipFile(bundle_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for item in sorted(manifest,key=lambda r:r['name']):archive.write(item['path'],item['name'])
    with zipfile.ZipFile(bundle_path) as archive:
        assert len(archive.namelist())==len(manifest)
        for item in manifest:assert digest(archive.read(item['name']))==item['sha256']
    manifest=[{k:v for k,v in row.items() if k!='path'} for row in manifest]
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (output/'per-task.json').write_text(json.dumps(per_task,indent=2),encoding='utf-8')
    report={'schema':'neyvia.c4c.v1','timestamp':datetime.now(timezone.utc).isoformat(),'runId':a.run_id,
        'sourceSha256':freeze['sourceSha256'],'matrix':{'tasks':18,'repetitions':2,'arms':2,'rows':len(rows),'nativeWaitingRows':4},
        'totals':totals,'totalTokenSavingsPercent':100*(1-totals['efficient']['tokens']['total']/totals['control']['tokens']['total']),
        'costSavingsPercent':100*(1-totals['efficient']['costUsd']/totals['control']['costUsd']),
        'ci95':confidence,'ciMethod':'10000 paired task-cluster bootstrap resamples; 17 independent task clusters, repetitions kept together',
        'perTask':per_task,'pressure':pressure,'pressureSuccessCi95':wilson(sum(r['passed'] for r in pressure),4),
        'judgeUsage':judge_usage,'judgePairs':len(judges),'judgeSuccessfulPairs':sum(r['passed'] for r in judges.values()),
        'observedOverhead':observed_overhead,'wholeObservedWork':whole_work,
        'pricesUsdPerMillion':freeze['pricesUsdPerMillion'],
        'postCollectionTransportFixes':fixes,'pairReplacements':replacements,
        'collectorRecoveries':json.loads((base/'collection-recovery.json').read_text(encoding='utf-8')) if (base/'collection-recovery.json').exists() else [],
        'finalSourceSha256':{name:digest((REPO/name).read_bytes()) for name in BOUND_SOURCES},
        'mechanismTelemetry':{arm:{'turns':sum(len(r['run']['turns']) for r in rows if r['arm']==arm),
             'compactions':sum(r['run'].get('contextMetrics',{}).get('compactions',0) for r in rows if r['arm']==arm),
             'procedures':sum(r['run'].get('hostMetrics',{}).get('procedures',0) for r in rows if r['arm']==arm),
             'maxHostPromptTokens':max((t['hostPromptTokens'] for r in rows if r['arm']==arm for t in r['run']['turns']),default=0)} for arm in ('efficient','control')},
        'archive':{'path':bundle_path.relative_to(REPO).as_posix(),'sha256':digest(bundle_path.read_bytes()),'bytes':bundle_path.stat().st_size,'entries':len(manifest)},
        'limits':['Native task waiting for C11; no native launch/input or request for Paul to open apps.',
                  'All invalid/frontier/deadline/diagnostic attempts retained as overhead; no cherry-picked continuations.',
                  'OS automatic dark-mode emulation unsupported; exact authored dark CSS activated in disposable DOM and rendered.',
                  'Lead screenshot inspection observes Obscura rendering the range control as a basic white input; native widget appearance is unverified.',
                  'Live-table checking uses an explicitly recorded same-CDP selector adapter because Obscura table.rows is not iterable.',
                  'Blinded Luna rubric is uncalibrated; human creative/visual quality equivalence is not established.',
                  'Date-rule checks do not read the withheld answer file; original hidden 40-case quality remains unverified.',
                  'Recorded list-price equivalents, not invoice; host caps exclude hidden provider instructions/reasoning.',
                  'Guided 4-run bug repair uses a workspace-only procedure; its zero compactions do not prove long-run recovery or universal reliability.',
                  'Overhead excludes unavailable lead/sub-agent session usage; interrupted usage is a lower bound.']}
    (REPO/'scripts/evidence/C4c.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if a.append:
        ledger=REPO/'docs/research/results.jsonl'
        existing=[json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines() if line.strip()]
        assert not any(r.get('runId')==a.run_id and r.get('schema')=='neyvia.c4c.v1' for r in existing)
        entry={k:report[k] for k in ('schema','timestamp','runId','matrix','totals','ci95','ciMethod','totalTokenSavingsPercent','costSavingsPercent','perTask','pressure','pressureSuccessCi95','wholeObservedWork','mechanismTelemetry','limits')}
        entry['receipt']='scripts/evidence/C4c.json';entry['receiptSha256']=digest((REPO/entry['receipt']).read_bytes())
        with ledger.open('a',encoding='utf-8',newline='\n') as stream:stream.write(json.dumps(entry,ensure_ascii=False,separators=(',',':'))+'\n')
    print(json.dumps({'rows':len(rows),'totals':totals,'ci95':confidence,'pressurePassed':sum(r['passed'] for r in pressure),'archiveBytes':bundle_path.stat().st_size}))
if __name__=='__main__':main()
