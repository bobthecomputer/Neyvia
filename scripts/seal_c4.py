"""Seal real C4 receipts, recalculate provider usage, and append the research ledger."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO / 'src'))
from grant_agent.cl.provider11 import usage_counts
from c4_quality import check
from efficiency_log import validate,ledger_lock
R4=Path('C:/Users/user/Projects/nx-r4-blind/proof/r4-blind-20261004')
KEYS=('input','cachedInput','cacheCreation','uncachedInput','output','total')
PRICES=json.loads((REPO / 'config/scroll-study-prices.json').read_text(encoding='utf-8'))['gpt-6-luna']
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sum_tokens(rows): return {k:sum(row.get(k,0) for row in rows) for k in KEYS}
def price(t): return (t['uncachedInput']*PRICES['input']+t['cachedInput']*PRICES['cached']+t['output']*PRICES['output'])/1e6
def summary(path):
    d=read(path);run=d['run'];total=sum_tokens([usage_counts(read(p).get('usage')) for p in sorted((path.parent / 'run').glob('turn-*/receipt.json'))])
    if {k:run.get('tokens',{}).get(k,0) for k in KEYS}!=total:
        raise ValueError('Provider/run usage mismatch: '+str(path))
    # Verify the model wrapper counts against the last actual completed event.
    for p in sorted((path.parent / 'run').glob('turn-*/receipt.json')):
        events=[json.loads(x) for x in (p.parent / 'events.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
        completed=[e['usage'] for e in events if e.get('type')=='turn.completed']
        if completed and completed[-1]!=read(p)['usage']: raise ValueError('Raw usage mismatch: '+str(p))
    return {'task':d['task'],'arm':d['arm'],'run':path.parent.parent.parent.name,
            'hostDone':run['passed'],'qualityPassed':d['quality']['passed'],
            'accepted':run['passed'] and d['quality']['passed'],'failure':run['failure'],
            'tokens':total,'costUsd':price(total),'seconds':run['elapsedSeconds'],
            'turns':len(run['turns']),'hostPromptTokens':[t['hostPromptTokens'] for t in run['turns']],
            'contextMetrics':run.get('contextMetrics',{}),'hostMetrics':run.get('hostMetrics',{}),
            'sourceSha256':run.get('sourceSha256',{}),'quality':d['quality'],
            'receipt':str(path.relative_to(REPO)).replace('\\','/'),'receiptSha256':digest(path)}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--panel',required=True)
    parser.add_argument('--append-ledger',action='store_true');args=parser.parse_args()
    root=REPO / '.agent_control/c4';panel=root / args.panel
    tasks=json.loads((R4 / 'tasks.json').read_text(encoding='utf-8'))
    paths=[panel / arm / task['id'] / 'result.json' for task in tasks for arm in ('efficient','control')]
    if any(not p.is_file() for p in paths): raise ValueError('Panel is incomplete; do not seal partial results as final')
    target=REPO / 'scripts/evidence/C4';target.mkdir(parents=True,exist_ok=True)
    rows=[]
    for path in paths:
        row=summary(path)
        if row['task'] in {'t2-bugfix','t3-notes','t6-study','t7-explain','t8-plan'}:
            current=check(row['task'],path.parent / 'workspace')
            row['independentRecheck']=current
            row['qualityPassed']=current['passed'];row['accepted']=row['hostDone'] and current['passed']
        if row['task']!='t5-cua':
            sources=row['sourceSha256']
            if not isinstance(sources,dict) or any(digest(REPO / p)!=value for p,value in sources.items()):
                raise ValueError('Frozen production source mismatch: '+str(path))
        destination=target / 'final' / row['arm'] / row['task']
        destination.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,destination / 'result.json')
        for p in (path.parent / 'workspace').rglob('*'):
            relative=p.relative_to(path.parent / 'workspace')
            if p.is_file() and not any(part.startswith('.') for part in relative.parts):
                out=destination / 'workspace' / relative;out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,out)
        if (path.parent / 'external-quality').is_dir():
            shutil.copytree(path.parent / 'external-quality',destination / 'external-quality',dirs_exist_ok=True)
        row['sealedReceipt']=str((destination / 'result.json').relative_to(REPO)).replace('\\','/')
        rows.append(row)
    arms={}
    for arm in ('efficient','control'):
        selected=[r for r in rows if r['arm']==arm]
        tokens=sum_tokens([r['tokens'] for r in selected])
        arms[arm]={'tokens':tokens,'costUsd':price(tokens),'accepted':sum(r['accepted'] for r in selected),
                   'turns':sum(r['turns'] for r in selected),'secondsSum':sum(r['seconds'] for r in selected)}
    historical=[];inclusive=[]
    for task in tasks:
        source=R4 / 'receipts' / ('L-'+task['id']+'.jsonl')
        events=[json.loads(x) for x in source.read_text(encoding='utf-8').splitlines() if x.strip()]
        usages=[usage_counts(e['usage']) for e in events if e.get('type')=='turn.completed']
        if not usages: raise ValueError('No R4 raw usage: '+str(source))
        dest=target / 'r4-baseline' / source.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
        historical.append({'task':task['id'],'tokens':usages[-1],'sourceSha256':digest(source),'receipt':str(dest.relative_to(REPO)).replace('\\','/')})
        inclusive.extend(usages)
    baseline=sum_tokens([r['tokens'] for r in historical]);comparable=sum_tokens([r['tokens'] for r in historical if r['task']!='t5-cua'])
    attempts=[summary(p) for p in sorted(root.glob('*/*/*/result.json')) if not p.is_relative_to(panel)]
    raw_files=[]
    for p in sorted(root.rglob('*')):
        relative=p.relative_to(root)
        if not p.is_file() or p.suffix not in {'.json','.jsonl','.txt','.md','.html','.png','.stdout','.stderr'}: continue
        if '.agent_control' in relative.parts or '.neyvia' in relative.parts: continue
        raw_files.append(p)
    archive=target / 'raw-runs.zip';manifest=[]
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for p in raw_files:
            name=p.relative_to(root).as_posix();bundle.write(p,name)
            manifest.append({'path':name,'bytes':p.stat().st_size,'sha256':digest(p)})
    write(target / 'archive-manifest.json',manifest)
    limits=['One unseeded trial per task and arm; no population or blind aesthetic quality claim',
            'Historical R4 used different harness/effort and sparse checks; historical reduction is not controlled quality equivalence',
            't5 is blocked by the absent existing Character Map target; native token fixtures are not desktop proof',
            'CLI hidden system context is outside the 8000 host-token budget; list-price equivalents are not invoices',
            'Earlier interrupted invocations have incomplete usage; exploratory totals are observed lower bounds',
            'No deployment or public chat-default change; Chrome plugin unavailable, UI proved in actual isolated Chromium']
    a,b=arms['efficient'],arms['control']
    receipt={'schema':'neyvia.c4-evidence.v1','panel':args.panel,'model':'gpt-6-luna','effort':'medium',
             'mechanismVerified':read(REPO / 'scripts/evidence/C4-host.json')['ok'] and read(REPO / 'scripts/evidence/C4-production.json')['passed'],
             'taskPanelComplete':all(r['accepted'] for r in rows),'rows':rows,'arms':arms,
             'matchedTokenReductionPercent':100*(1-a['tokens']['total']/b['tokens']['total']),
             'matchedCachedTokenReductionPercent':100*(1-a['tokens']['cachedInput']/b['tokens']['cachedInput']),
             'matchedCostReductionPercent':100*(1-a['costUsd']/b['costUsd']),
             'historicalR4':{'successfulInvocationTokens':baseline,'inclusiveReportedTokens':sum_tokens(inclusive),
                             'costUsd':price(baseline),'comparableSevenTokens':comparable,'rows':historical,
                             'qualityNote':'t5 blank; original format/existence checks did not establish comprehensive correctness'},
             'exploratoryAttempts':attempts,'exploratoryObservedTokens':sum_tokens([r['tokens'] for r in attempts]),
             'rawArchive':{'path':str(archive.relative_to(REPO)).replace('\\','/'),'sha256':digest(archive),'files':len(manifest),'bytes':archive.stat().st_size},
             'hostReceipt':'scripts/evidence/C4-host.json','productionReceipt':'scripts/evidence/C4-production.json',
             'nativeReceipt':'scripts/evidence/C4-native.json','limits':limits,'pricesUsdPerMillion':PRICES}
    write(REPO / 'scripts/evidence/C4.json',receipt)
    write(target / 'final-rows.json',rows)
    appendix='\nObserved frozen panel ('+args.panel+'):\n\n| Task | Candidate accepted | Control accepted | Candidate tokens | Control tokens |\n|---|---:|---:|---:|---:|\n'
    for task in tasks:
        x,y=[next(r for r in rows if r['task']==task['id'] and r['arm']==arm) for arm in ('efficient','control')]
        appendix+=f"| {task['id']} | {x['accepted']} | {y['accepted']} | {x['tokens']['total']:,} | {y['tokens']['total']:,} |\n"
    appendix+=f"\nCandidate {a['tokens']['total']:,} total / {a['tokens']['cachedInput']:,} cached tokens, ${a['costUsd']:.8f}; control {b['tokens']['total']:,} total / {b['tokens']['cachedInput']:,} cached, ${b['costUsd']:.8f}. Matched reduction: {receipt['matchedTokenReductionPercent']:.2f}% tokens, {receipt['matchedCostReductionPercent']:.2f}% cost.\n"
    doc=REPO / 'docs/research/C4.md';text=doc.read_text(encoding='utf-8').split('\nObserved frozen panel (')[0];doc.write_text(text+appendix,encoding='utf-8')
    if args.append_ledger:
        rawpath=target / 'final-rows.json'
        spec={'schema':'neyvia.efficiency-result.v1','id':'C4-frozen-'+args.panel,'study':'C4 bounded Luna CL on R4',
              'evidence_status':'raw-verified','method':'Frozen paired production-gateway runs; identical selected tools, procedures, goals, fixtures, effort and quality checks. Candidate acknowledged diffs and bounded history; control full history/state. Includes failures and the blocked native task.',
              'models':['gpt-6-luna via exact Codex CLI route, medium effort'],
              'tasks':{'description':'Eight R4 tasks, native target absent','repetitions':1,'independent_unit':'task'},
              'receipts':[{'id':'runs','path':str(rawpath.relative_to(REPO)).replace('\\','/'),'sha256':digest(rawpath),'kind':'raw'}],
              'metrics':[],'limitations':limits}
        for arm in ('efficient','control'):
            for field,unit in (('/tokens/total','tokens'),('/tokens/cachedInput','tokens'),('/costUsd','USD equivalent'),('/accepted','count')):
                spec['metrics'].append({'name':arm+'_'+field.rsplit('/',1)[-1],'unit':unit,
                    'calculation':{'op':'sum','args':[{'receipt':'runs','where':{'/arm':arm},'field':field}]},
                    'ci_request':{'method':'not-estimable','reason':'One unseeded run per fixed task; no population inference'}})
        validate(spec,prepare=True)
        ledger=REPO / 'docs/research/results.jsonl'
        with ledger_lock(ledger):
            before=ledger.read_bytes()
            if any(json.loads(line)['id']==spec['id'] for line in before.decode('utf-8').splitlines()): raise ValueError('Ledger ID already exists')
            with ledger.open('ab') as stream: stream.write((('' if before.endswith(b'\n') else '\n')+json.dumps(spec,ensure_ascii=False)+'\n').encode('utf-8'))
            if not ledger.read_bytes().startswith(before): raise ValueError('Ledger prior rows changed')
        validate(spec)
        write(target / 'ledger-validation.json',{'passed':True,'id':spec['id'],'priorBytes':len(before),'priorSha256':hashlib.sha256(before).hexdigest(),'metrics':len(spec['metrics'])})
    print(json.dumps({'arms':arms,'tokenReductionPercent':receipt['matchedTokenReductionPercent'],'costReductionPercent':receipt['matchedCostReductionPercent'],'archiveBytes':archive.stat().st_size}),flush=True)
if __name__=='__main__':main()
