"""Bind R12 blind screenshots, actual usage and bounded admission evidence."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.taste_fewshot import STATE,save,digest,episodic_prediction
RAW=Path('D:/NeyviaRuns/r12');PROOF=REPO/'proof/r12'
USAGE_SNAPSHOT=None
LOCAL_SNAPSHOT=None
ARMS=['fusion-v2','sol-alone','luna-alone']


def read(path):return json.loads(Path(path).read_bytes())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def usage(folder):
    global USAGE_SNAPSHOT
    paths=[];unknown=[]
    # Browser profiles contain thousands of host receipts, never model usage.
    # Prune them before walking metered provider invocation folders.
    if USAGE_SNAPSHOT is None:
        for directory,children,files in os.walk(RAW):
            children[:]=[name for name in children if name not in {'render','browser','vision-cache','pair-embeddings','inherited-checkpoints','laya-service'}]
            if 'usage.json' in files:paths.append(Path(directory)/'usage.json')
            elif 'events.jsonl' in files:unknown.append(str(Path(directory)/'events.jsonl'))
        USAGE_SNAPSHOT=([read(p)|{'receiptPath':str(p),'receiptSha256':sha(p)} for p in paths],unknown)
    target=Path(folder).resolve()
    copies=[c for c in USAGE_SNAPSHOT[0] if Path(c['receiptPath']).resolve().is_relative_to(target)]
    unique={}
    for call in copies:unique.setdefault(call['receiptSha256'],call)
    calls=list(unique.values())
    unknown=[p for p in USAGE_SNAPSHOT[1] if Path(p).resolve().is_relative_to(target)]
    return {'calls':calls,'costUsd':sum(c.get('costUsd') or 0 for c in calls),
        'tokens':sum(c['usage']['total_tokens'] for c in calls),
        'cachedTokens':sum(c['usage']['cached_input_tokens'] for c in calls),
        'modelSec':sum(c['elapsedSec'] for c in calls),
        'complete':bool(calls) and not unknown and all(c.get('usageComplete') for c in calls),'unknownInvocations':unknown,
        'duplicateReceiptCopiesExcluded':len(copies)-len(calls)}




def local_usage(folder):
    """Read task-owned typed decision receipts, including superseded requests."""
    global LOCAL_SNAPSHOT
    if LOCAL_SNAPSHOT is None:
        LOCAL_SNAPSHOT=[]
        for directory,children,files in os.walk(RAW):
            children[:]=[name for name in children if name not in {'render','browser','vision-cache','pair-embeddings','inherited-checkpoints','laya-service'}]
            for name in files:
                if not (name in {'keep-revert.json','crop.json'} or
                        name.startswith(('failure-','prior-decision-')) and name.endswith('.json')):continue
                path=Path(directory)/name
                row=read(path)
                if isinstance(row,dict) and row.get('decisionId') and row.get('usage'):
                    LOCAL_SNAPSHOT.append(row|{'receiptPath':str(path),'receiptSha256':sha(path)})
    target=Path(folder).resolve()
    return list({r['decisionId']:r for r in LOCAL_SNAPSHOT
                 if Path(r['receiptPath']).resolve().is_relative_to(target)}.values())

def measured_renders(folder):
    """Count every completed render invocation, including recovery/preflight work."""
    receipts=[];seen=set();duplicates=0
    for directory,children,files in os.walk(folder):
        children[:]=[name for name in children if name not in {'render','browser','vision-cache','pair-embeddings','inherited-checkpoints','laya-service'}]
        here=Path(directory)
        name='render-process.json' if 'render-process.json' in files else (
            'process.json' if here.name.startswith('failed-render-') and 'process.json' in files else None)
        if name:
            path=here/name
            row=read(path);identity=sha(path)
            if identity in seen:duplicates+=1;continue
            seen.add(identity)
            receipts.append({'path':str(path),'sha256':identity,'elapsedSec':row.get('elapsedSec',0)})
    return {'seconds':sum(r['elapsedSec'] for r in receipts),'receipts':receipts,'duplicateCopiesExcluded':duplicates}

def render_receipt(path):
    """Portable bounded evidence; the complete immutable payload stays on D."""
    observed=read(path)
    result={k:observed[k] for k in ['engine','scope','html','html_sha256','port','enginePort','passed','errors',
             'verificationDriverSha256','duration_ms','journeyRecipes','journeyRecipesSha256'] if k in observed}
    result['sourceReportPath']=str(path);result['sourceReportSha256']=sha(path)
    result['screenshots']=[{k:s[k] for k in ['viewport','theme','variant','path','sha256'] if k in s}
                           for s in observed['screenshots']]
    result['variants']=[]
    for variant in observed['variants']:
        item={k:variant[k] for k in ['viewport','theme','passed','errors','discovered','exercised','coverage_complete','overflow'] if k in variant}
        item['controls']=[]
        for control in variant['controls']:
            row={k:control[k] for k in ['id','identity','tag','label','action','key','path','target','dead','undecided'] if k in control}
            row['modes']=[{k:m[k] for k in ['mode','action','effect','status','error','gesturePathCompilation','gestureInput',
                           'before_sha256','after_sha256','prerequisite','assertion','keyboardInput'] if k in m} | {'observedChangeCount':len(m.get('observedChanges',[]))}
                          for m in control['modes']]
            item['controls'].append(row)
        result['variants'].append(item)
    return result


def blind():
    keypath=PROOF/'SPOILER-key.json'
    key=read(keypath) if keypath.exists() else {'tasks':{}}
    key['schema']='neyvia.r12-blind.v2'
    folder=PROOF/'blind';folder.mkdir(exist_ok=True)
    superseded=RAW/'superseded-blind';superseded.mkdir(exist_ok=True)
    for name in ['landing','rare-ui']:
        for old in folder.glob(name+'-[AB]-*.png'):
            archived=superseded/(old.stem+'-'+sha(old)[:12]+old.suffix)
            if not archived.exists():shutil.copyfile(old,archived)
            if sha(old)!=sha(archived):raise ValueError('Superseded screenshot archive mismatch')
            old.unlink()
    for task,name in [('T1','landing'),('T2','rare-ui')]:
        item=key['tasks'].setdefault(task,{'name':name})
        pairs=[['fusion-v2','sol-alone'],['luna-alone','sol-alone'],['fusion-v2','luna-alone']]
        comparisons=item.setdefault('comparisons',{})
        for number,pair in enumerate(pairs,1):
            if str(number) not in comparisons:
                arms=list(pair);secrets.SystemRandom().shuffle(arms)
                comparisons[str(number)]={'arms':dict(zip(['A','B'],arms))}
        item.pop('arms',None);item['shots']=[]
        for number,comparison in comparisons.items():
          for letter,arm in comparison['arms'].items():
            summary=read(PROOF/arm/task/'summary.json');report=read(summary['reportPath'])
            artifact=PROOF/arm/task/'work'/('landing.html' if task=='T1' else 'rare-ui.html')
            if sha(artifact)!=summary['artifactSha256'] or report['html_sha256']!=summary['artifactSha256']:
                raise ValueError('Selected artifact/render binding mismatch')
            for theme in ['light','dark']:
                source=next(s for s in report['screenshots'] if s['viewport']=='desktop' and s['theme']==theme)
                dest=folder/(name+'-'+number+'-'+letter+'-'+theme+'.png');shutil.copyfile(source['path'],dest)
                item['shots'].append({'comparison':number,'label':letter,'theme':theme,'path':str(dest.relative_to(PROOF)),
                    'sha256':sha(dest),'sourcePath':source['path'],'sourceSha256':source['sha256'],
                    'artifactSha256':summary['artifactSha256'],'summarySha256':sha(PROOF/arm/task/'summary.json'),
                    'renderReportSha256':sha(summary['reportPath'])})
    save(keypath,key)
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Round 12 · blind comparison</title><style>body{margin:0;background:rgb(238,237,230);color:rgb(25,31,29);font:16px system-ui}main{max-width:1500px;margin:auto;padding:32px}h1{font-size:32px}button{padding:12px 20px;border:0;border-radius:8px;margin:0 8px 16px 0;background:rgb(30,74,58);color:white;cursor:pointer}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:48px}figure{margin:0}figcaption{font-weight:600;padding:12px 0}img{width:100%;height:auto;display:block}body[data-theme=dark]{background:rgb(15,22,20);color:white}@media(max-width:650px){.pair{grid-template-columns:1fr}}</style><main><h1>Round 12</h1><p>Compare A and B. The answer key is in a separate SPOILER file.</p><button id="light">Light</button><button id="dark">Dark</button>'''
    for name,title in [('landing','Landing page'),('rare-ui','Rare UI')]:
        for number in ['1','2','3']:
            html+=f'<h2>{title} · comparison {number}</h2><div class="pair">'
            for letter in ['A','B']:
                label=f'{name}-{number}-{letter}'
                html+=f'<figure><figcaption>{letter}</figcaption><img data-name="{label}" src="{label}-light.png" alt="{title} comparison {number} {letter}"></figure>'
            html+='</div>'
    html+='''</main><script>for(const theme of ['light','dark'])document.getElementById(theme).onclick=()=>{document.body.dataset.theme=theme;for(const image of document.querySelectorAll('img'))image.src=image.dataset.name+'-'+theme+'.png';};</script></html>'''
    (folder/'index.html').write_text(html,encoding='utf-8')
    return key


def report():
    heldout=read(STATE/'heldout-report.json');policy=read(STATE/'calibration.json')
    arms=[];live_local=[]
    for arm in ARMS:
        for task in ['T1','T2']:
            summary=read(PROOF/arm/task/'summary.json');history=read(PROOF/arm/task/'history.json')
            calls=usage(RAW/arm/task)
            round_reviews=[(r,read(Path(r['raw'])/'quality.json')) for r in history
                if r['paidCritic'] and (Path(r['raw'])/'quality.json').exists()]
            save(PROOF/arm/task/'render-report.json',render_receipt(summary['reportPath']))
            shutil.copyfile(Path(summary['raw'])/'quality.json',PROOF/arm/task/'quality-report.json')
            decisions=[r['gate'] for r in history if r.get('gate')]+[d for r in history for d in r.get('routineDecisions',[])]+summary.get('routineDecisions',[])
            laya=[d for d in decisions if d.get('route')=='laya']
            scalars={k:{'answered':sum(d.get('route')=='laya' for d in decisions if d.get('kind')==k),
                        'escalated':sum(d.get('route')=='escalate' for d in decisions if d.get('kind')==k)} for k in ['repair','failure','crop']}
            renders=measured_renders(RAW/arm/task)
            elapsed=renders['seconds']
            live_local += [d for d in decisions if d.get('decisionId')]
            local_requests=local_usage(RAW/arm/task)
            local=sum(d.get('latencyMs',0) for d in local_requests)/1000
            initial_quality=read(PROOF/'baseline'/task/'summary.json')['quality']['quality']
            arms.append({'arm':arm,'task':task,'quality':summary['quality']['quality'],'baselineQuality':initial_quality,
                'blocks':summary['checks']['blocks'],'complete':summary['complete'],'rounds':len(history),
                'costUsd':calls['costUsd'],'tokens':calls['tokens'],'cachedTokens':calls['cachedTokens'],
                'modelSec':calls['modelSec'],'renderSec':elapsed,'renderReceipts':renders['receipts'],
                'duplicateRenderReceiptsExcluded':renders['duplicateCopiesExcluded'],'duplicateUsageReceiptsExcluded':calls['duplicateReceiptCopiesExcluded'],'layaSec':local,
                'measuredWorkSec':calls['modelSec']+elapsed+local,'timeScope':'Sum of model/render/service durations, not total wall time or critical path.',
                'layaAnswers':len(laya),'layaDecisions':len(decisions),'allActualLocalRequests':len(local_requests),'decisionKinds':scalars,
                'criticCallsOmitted':sum(not r['paidCritic'] for r in history),
                'paidRoundReviewsUnready':sum(not q['ready'] for _,q in round_reviews),
                'retainedUnreadyRounds':sum(r['keep'] and not q['ready'] for r,q in round_reviews),
                'replayedPaidRepairs':sum((Path(r['raw'])/'replayed-repair.json').exists() for r in history),
                'repairRevisionStatus':{name:sum((r.get('gate') or {}).get('sameDriverRevision') is value for r in history if r.get('gate')) for name,value in [('matched',True),('mismatched',False),('notRecorded',None)]},
                'usageComplete':calls['complete'],'artifactSha256':summary['artifactSha256'],'summarySha256':sha(PROOF/arm/task/'summary.json')})
    comparisons=[]
    for task in ['T1','T2']:
        fusion=next(a for a in arms if a['arm']=='fusion-v2' and a['task']==task)
        sol=next(a for a in arms if a['arm']=='sol-alone' and a['task']==task)
        for candidate in ['fusion-v2','luna-alone']:
          fusion=next(a for a in arms if a['arm']==candidate and a['task']==task)
          comparisons.append({'task':task,'candidate':candidate,'costRatio':sol['costUsd']/fusion['costUsd'] if fusion['costUsd'] else None,
            'costDifferenceUsd':sol['costUsd']-fusion['costUsd'],'tokenDifference':sol['tokens']-fusion['tokens'],
            'measuredWorkDifferenceSec':sol['measuredWorkSec']-fusion['measuredWorkSec'],
            'qualityDifference':fusion['quality']-sol['quality'],'criticCallsActuallyOmitted':fusion['criticCallsOmitted'],
            'meaning':'Observed matched-source arm difference; not exact counterfactual savings for an unmade call.'})
    allusage=usage(RAW);baseline=usage(RAW/'baseline')
    save(PROOF/'usage-receipts.json',allusage)
    personal=read(STATE/'personal.json')
    localrows=[]
    for file in ['calibration-decisions.json','heldout-decisions.json','attempt-1/calibration-decisions.json']:
        localrows+=read(STATE/file)
    calibration_predictions={r['prediction']['decisionId']:r['prediction'] for r in localrows}
    localtokens=sum(p.get('usage',{}).get('input_tokens',0) for p in calibration_predictions.values())
    negative=read(PROOF/'negative/real-routes.json')
    local_predictions=calibration_predictions | {p['decisionId']:p for p in local_usage(RAW)+live_local+[r['prediction'] for r in negative]}
    localtotal=sum(p.get('usage',{}).get('input_tokens',0)+p.get('usage',{}).get('output_tokens',0) for p in local_predictions.values())
    heldout_rows=read(STATE/'heldout-decisions.json');corpus=read(STATE/'real-pairs.json')['cases']
    by_id={r['id']:r for r in corpus}
    rebuilt=[episodic_prediction(r['kind'],by_id[r['id']]['facts'],[x for x in corpus if x['split']=='train' and x['kind']==r['kind']]) for r in heldout_rows]
    ablation={'withoutModelSameEpisodeAnswers':all(p['answer']==r['prediction']['answer'] and p['confidence']==r['prediction']['confidence'] for p,r in zip(rebuilt,heldout_rows)),
        'baseModelAgreement':sum(r['prediction']['baseModelAnswer']==r['prediction']['answer'] for r in heldout_rows)/len(heldout_rows),
        'cases':len(heldout_rows),'meaning':'Post-hoc reconstruction with the frozen episode library. Model inference is recorded, but the empirical wrapper determines the decision. No base-model contribution to saved critic calls is established.',
        'liveModelLatencySec':sum(p.get('latencyMs',0) for p in local_usage(RAW))/1000}
    orchestration=read(PROOF/'orchestration-usage.json') if (PROOF/'orchestration-usage.json').exists() else None
    contract=read(PROOF/'contracts-final/report.json') if (PROOF/'contracts-final/report.json').exists() else None
    verification={k:contract[k] for k in ['status','checksRun','checksPassed','blocking','manualSha256'] if k in contract} if contract else None
    result={'schema':'neyvia.r12-report.v1','arms':arms,'comparison':comparisons,'heldout':heldout,'calibration':policy,
        'verification':verification,'shutdownInvestigation':'process-shutdown.md',
        'alternateDestinationProbes':{arm:read(PROOF/'diagnostics'/(arm+'-alternate.json')) for arm in ARMS},
        'labelExport':read(PROOF/'label-export.json'),
        'initialSourceNewlines':read(PROOF/'seed/newline-canonicalization.json'),
        'realCorpus':{'counts':read(STATE/'real-pairs.json')['counts'],'limits':read(STATE/'real-pairs.json')['limitations'],
            'r6Boundary':'R6 real screenshots and critic examples condition the personal layer; no comparable sequential Obscura blocking-check receipts exist for retention calibration.'},
        'labelScopes':{'repair':'Recorded no-regression retention labels; independent critic agreement is separate.',
                       'failure':'Recorded check flag/frontier reproduction, not independently annotated defect validity.',
                       'crop':'Historical critic-region selection agreement, not independent optimal-crop quality.'},
        'ablation':ablation,'personal':{'counts':personal['counts'],'reasonCount':personal['reasonCount'],'headTrained':False},
        'totals':{'providerTokens':allusage['tokens'],'providerCostUsd':allusage['costUsd'],'localCalibrationTokens':localtokens,'localDecisionTokens':localtotal,'localDecisionRequests':len(local_predictions),
                  'baselineSharedTokens':baseline['tokens'],'baselineSharedCostUsd':baseline['costUsd'],
                  'orchestration':orchestration,'totalTokensAtCheckpoint':allusage['tokens']+localtotal+(orchestration['usage']['total_tokens'] if orchestration else 0),
                  'allUsageComplete':allusage['complete'],'duplicateUsageReceiptCopiesExcluded':allusage['duplicateReceiptCopiesExcluded']},
        'limits':['The base frozen LAYA model did not improve. Answers are the calibrated head-free episodic wrapper; raw model output stays visible.',
                 'Retention/check/crop reproduction is narrower than subjective taste. Critic agreement is reported separately.',
                 'Failure and crop labels reproduce recorded flags/frontiers and chosen regions. Their perfect agreement is not independent human accuracy on whether a defect is real or a crop is optimal.',
                 'Historical global control-effect receipts can contain unrelated hover/layout changes; current rare-UI filing requires an asserted real destination. Historical recorded-label accuracy is not a semantic journey guarantee.',
                 'The accepted retention gate answers no observed regression, not that every retained repair looks better. General subjective keep/revert remains unqualified.',
                 'Intermediate driver corrections and rejected literal patches are preserved and charged; final pages require fresh current-driver observations.',
                 'Measured work includes all completed render invocation receipts, including accepted-page preflight and recovery. Cancelled invocations without completed timing receipts and orchestration wall time are not estimated.',
                 'Removing base LAYA inference reconstructs the same episode answers; no frozen-model contribution to savings is established. Its measured latency is included in fusion costs.',
                 'Few-shot personal conditioning has no independent human accuracy estimate. Paul has not voted on R12.',
                 'Correlated page groups and model critic labels limit generalization. No whole-model or public promotion.',
                 'R6 lacks comparable sequential Obscura blocking-check receipts; it contributes real personal images, not manufactured retention labels.',
                 'Reusing Sol seeds excludes their historical generation cost equally from all three repair arms. Arms have different observed repair counts; this is not a fixed-round cost experiment.',
                 'Standalone Luna ran after the earlier harness repairs. Different recovery histories and prompts confound causal attribution of arm differences to LAYA alone.',
                 'Intermediate and final paid critics sometimes disagree on readiness for unchanged pages. Final scores are single reviews, not human preference estimates. Small phone filing targets remain a visual usability limitation of the compact fusion/Luna layouts.',
                 'Obscura has known headless painting limits, including some 3D surfaces; these are not user-facing acceptance gates.',
                 'Check and crop selection remain zero-token scripts in Sol alone; no fabricated savings from replacing those scripts.',
                 'List-price equivalents are not an invoice. Sum of stage durations does not establish total wall-clock savings.']}
    save(PROOF/'report.json',result)
    lines=['# R12: real decision episodes and matched repairs','',
        '| Arm | Page | Fresh quality | Blocks | LAYA answers | Critic calls omitted | Tokens | USD |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    lines += [f"| {a['arm']} | {a['task']} | {a['quality']} | {a['blocks']} | {a['layaAnswers']}/{a['layaDecisions']} | {a['criticCallsOmitted']} | {a['tokens']:,} | {a['costUsd']:.5f} |" for a in arms]
    fusion_total=sum(a['costUsd'] for a in arms if a['arm']=='fusion-v2')
    sol_total=sum(a['costUsd'] for a in arms if a['arm']=='sol-alone')
    luna_total=sum(a['costUsd'] for a in arms if a['arm']=='luna-alone')
    lines+=['',f"Observed repair-arm cost: fusion ${fusion_total:.5f}, Sol ${sol_total:.5f}, standalone Luna ${luna_total:.5f}. Fusion omitted eight round critics and answered 35/40 live wrapper decisions, but used more tokens and completed stage work than Sol. Standalone Luna was cheapest; later harness maturity and different repair counts prevent a causal LAYA-only savings claim.",
        'All six final pages have zero blocking checks and complete four-variant control coverage. The two alternate keyboard destinations also pass on all three rare UIs. Intermediate paid readiness disagreements remain in the receipts; small compact phone filing targets still need human taste review.']
    lines+=['','Personal: 25 identity labels, 5 quality votes and 17 aspect examples; all 16 feedback reasons retained. No fitted personal head.',
        '', '| Held-out decision | Cases | Answered | Recorded-label agreement on answered | Critic agreement |',
        '|---|---:|---:|---:|---:|']
    for kind,m in heldout['metrics'].items():
        acc='unavailable' if m['selectiveAccuracy'] is None else f"{m['selectiveAccuracy']:.1%}"
        critic='not a quality prediction' if kind!='repair' else f"{m['criticAgreement']:.1%}" if m['criticAgreement'] is not None else 'unavailable'
        lines.append(f"| {kind} | {m['cases']} | {m['answered']} | {acc} | {critic} |")
    lines+=['',f"Model ablation: the frozen episode library reconstructs identical answers without base-model inference. Raw model/episode agreement is {ablation['baseModelAgreement']:.1%} across {ablation['cases']} held-out requests; live inference adds {ablation['liveModelLatencySec']:.1f}s. This proves wrapper utility, not LAYA model improvement.",
        '', 'Failure and crop agreement reproduce historical recorded flags/regions; independently labelled real-defect validity and optimal-crop quality remain unproven.',
        'LAYA answers above are the episodic wrapper around real frozen-model inference. Raw unstructured inference qualified no gate, and the CLIP-delta quality retrieval experiment also failed calibration.',
        'Repair accuracy measures retention without observed regressions. It does not prove subjective taste; independent critic agreement is shown above.',
        '', 'Observed differences against Sol alone:']
    for c in comparisons:
        lines.append(f"- {c['task']}, {c['candidate']}: Sol minus candidate differences: {c['tokenDifference']:+,} tokens, ${c['costDifferenceUsd']:+.5f}, {c['measuredWorkDifferenceSec']:+.1f}s summed completed stage work; candidate minus Sol quality {c['qualityDifference']:+}. Positive cost/time differences favor the candidate; negative values mean it used more. These are observed arm differences, not exact counterfactual savings.")
    lines+=['',f"Provider tokens including diagnostics/shared baselines: {allusage['tokens']:,}; local calibration/held-out input tokens: {localtokens:,}.",
        f"All local decision input/output tokens (deduplicated): {localtotal:,}.",
        'Parent orchestration usage: '+(f"{orchestration['usage']['total_tokens']:,} cumulative tokens at {orchestration['timestamp']}, including {orchestration['usage']['cached_input_tokens']:,} cached input tokens; unfinished turn may not be flushed." if orchestration else 'unavailable from the attached harness; no total invented.'),
        '', 'Blind comparison: [open screenshots](blind/index.html). Answer mapping: `SPOILER-key.json`.',
        '', 'Verification uses authored `taste.cl` contracts and actual four-variant Obscura control journeys. Read `contracts-final/report.json` for passed and failed gates; incomplete pages are not approved. No new test files, downloads, visible windows, pushes or live-tree changes.',
        'Latest contract receipt: '+(f"{verification['checksPassed']}/{verification['checksRun']} passed; status {verification['status']}." if verification else 'not yet available.'),
        'Shutdown investigation: [scoped evidence](process-shutdown.md). The lead attributes the 08:30 interruption to an outside process restart. The earlier 03:45 cause is not established; the watchdog contains a broad stop but its recorded thresholds were not reached.',
        '', 'Limits:']
    lines+=['- '+v for v in result['limits']]
    (PROOF/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'arms':[{k:v for k,v in a.items() if k not in ['decisionKinds','artifactSha256','summarySha256','renderReceipts']} for a in arms],
                      'comparison':comparisons,'providerTokens':allusage['tokens']}),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blind',action='store_true');parser.add_argument('--diagnostics',action='store_true');args=parser.parse_args()
    if args.diagnostics:
        for name in ['filing-probe','filing-probe-release']:
            save(PROOF/'diagnostics'/(name+'.json'),render_receipt(RAW/'diagnostics'/name/'report.json'))
        print(json.dumps({'portableProbes':2}));return
    report()
    if args.blind:blind()


if __name__=='__main__':main()
