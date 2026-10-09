"""Seal observed Scroll Study artifacts and emit A4's receipt-backed result specs."""
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.neyvia_scroll import load, stats
from grant_agent.scroll_cost import derive_stats

ROOT=REPO/'.agent_control/a3b/runtime'
EVIDENCE=REPO/'scripts/evidence'
RAW=EVIDENCE/'A3B-runs/raw'
RAW.mkdir(parents=True,exist_ok=True)

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def copy(source,name=None):
    source=Path(source);target=RAW/(name or source.name);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);return target

row=load(ROOT,'learning-notes')
raw_log=copy(ROOT/'.neyvia/scroll/learning-notes/generation.jsonl')
rows=[json.loads(line) for line in raw_log.read_text(encoding='utf-8').splitlines()]
pack=copy(ROOT/'.neyvia/scroll/learning-notes/pack.json')
archive=copy(ROOT/'.neyvia/scroll/learning-notes/learning-notes.scrollpack')
notes=copy(ROOT/'study-notes.md')
manual=read(EVIDENCE/'A3B-manual.json')
copy(manual['compiled']['path'],'manual/compiled-validator.json')
copy(ROOT/'.neyvia/manual-runs.jsonl','manual/manual-runs.jsonl')
for run in manual['checks']:
    copy(ROOT/'.neyvia/manual-runs'/ (run['runId']+'.json'),'manual/'+run['runId']+'.json')
write(RAW/'review.json',row['review'])
write(RAW/'sources.json',row['sources'])
source=sqlite3.connect(ROOT/'.neyvia/scroll/state.sqlite3')
dest=sqlite3.connect(RAW/'scroll-state.sqlite3')
try:
    source.backup(dest)
finally:
    dest.close()
    source.close()

provider_receipts=[]
for event in rows:
    if event['tier'] not in {'small','big'}:continue
    path=Path(event['receiptPath']).resolve()
    assert path.is_relative_to(ROOT/'.neyvia/autopilot-model'),path
    receipt=read(path)
    assert receipt['model']==event['model'],(receipt['model'],event['model'])
    assert receipt['tokens']['input']==event['inTokens']
    assert receipt['tokens']['output']==event['outTokens']
    assert receipt['tokens']['cachedInput']==event['cachedTokens']
    target=copy(path,'providers/'+path.name)
    provider_receipts.append({'path':str(target.relative_to(REPO)),'sha256':sha(target),'original':str(path)})

prices=read(REPO/'config/scroll-study-prices.json')
current=stats(ROOT,row)
warm_id='a3b-learning-verified-warm'
warm_rows=[r for r in rows if r['run']==warm_id]
assert warm_rows and not any(r['tier'] in {'small','big'} for r in warm_rows)
warm=derive_stats(warm_rows,row['value']['cards'],row['review'],prices)
assert warm['totalUsd']==0 and warm['perCard']['tokens']==0
write(RAW/'approved-cards.json',row['value']['cards'])
write(RAW/'warm-events.json',warm_rows)
copy(REPO/'.agent_control/scroll-study/validator-proof.json','validator-proof.json')

limitations=[
    'One tuned development chapter; no held-out generalization, learning outcome, or Paul acceptance claim. Codex approved the development pack and edited one flagged causal answer.',
    'Cumulative costs include all failed generation/repair attempts. API standard list-price equivalence of actual CLI usage is not a subscription invoice. Operator time is unmetered.',
    'Study-hour cost is 3600 / sum(new-card seconds), not measured learner time. Local FSRS reviews cost zero provider tokens. Warm result is exact replay only.',
    'Text/Markdown imports only: PDF/photo OCR adapter, signed native Android/iOS and physical-phone transfer remain unproved. QR uses localhost in this isolated run; a reachable explicit URL is needed for a physical phone.',
    'Actual headless T18 player and Mobile token page were observed; the full Neyvia shell and native Tauri GUI were not exercised. A1 device-local bridge conventions are specialized to this app.',
    'Sparse or early-miss sessions can end when exposure, lag, adjacency and new-concept budget leave no legal card. The receipt retains the observed early-miss case rather than inventing exposure.',
    'Independent model solves cover flashcard/why/cloze/mcq/truefalse. Order/faded worked cards derive from the reviewed worked example; mathematical/media player coverage is not established by this prose study.',
    'Completed job identity survives backend restart; automatic resumption after a killed generation worker is not implemented. A failed provider/validation job requires inspection and a new request ID.'
    ,'Cumulative development big-model calls per card exceed the 0.05 target; exact replay is not a cold-pack efficiency claim.'
]

def selector(receipt,pointer='',field=None,where=None):
    out={'receipt':receipt,'pointer':pointer}
    if field is not None:out['field']=field
    if where is not None:out['where']=where
    return out
def op(name,*args):return {'op':name,'args':list(args)}
def event_sum(key,tier=None):return op('sum',selector('events',field='/'+key,where={'/tier':tier} if tier else None))
def money(tier,model):
    p=prices[model]
    return op('divide',op('sum',op('multiply',op('subtract',event_sum('inTokens',tier),event_sum('cachedTokens',tier)),p['input']),op('multiply',event_sum('cachedTokens',tier),p['cached']),op('multiply',event_sum('outTokens',tier),p['output'])),1000000)
count=op('count',selector('cards',field='/id'))
seconds=op('sum',selector('cards',field='/seconds'))
total=op('sum',money('small','gpt-6-luna'),money('big','gpt-6.1-sol'))
for arm,events,cost in [('development-with-repairs',raw_log,total),('exact-warm-replay',RAW/'warm-events.json',op('multiply',event_sum('inTokens'),0))]:
    def metric(name,unit,expr):return {'name':name,'unit':unit,'calculation':expr,'ci_request':{'method':'not-estimable','reason':'One tuned source chapter, without independent deployment repetitions'}}
    receipts=[{'id':rid,'path':str(p),'sha256':sha(p),'kind':'raw'} for rid,p in [('events',events),('cards',RAW/'approved-cards.json')]]
    receipts.append({'id':'prices','path':str(REPO/'config/scroll-study-prices.json'),'sha256':sha(REPO/'config/scroll-study-prices.json'),'kind':'raw'})
    spec={'schema':'neyvia.efficiency-result.v1','id':'A3B-scroll-study-2026-10-04-'+arm,
          'study':'A3B source-bound Scroll Study backend','method':arm+'; real Markdown notes, T14 exact cascade, compiled current-pack validation, observed CLI tokens including cached input once',
          'models':['gpt-6-luna','gpt-6.1-sol','deterministic scripts / compiled validation'],
          'tasks':{'description':'Repository learning-science notes -> 92 reviewed generated cards -> actual player', 'repetitions':1,'independent_unit':'one tuned source chapter'},
          'evidence_status':'raw-verified','receipts':receipts,
          'metrics':[metric('total_tokens','tokens',op('sum',event_sum('inTokens'),event_sum('outTokens'))),metric('cached_input_tokens','tokens',event_sum('cachedTokens')),metric('total_list_price_equivalent','USD',cost),metric('cost_per_card','USD/card',op('divide',cost,count)),metric('cost_per_new_study_hour','USD/hour',op('multiply',cost,op('divide',3600,seconds)))],
          'limitations':limitations}
    specification=EVIDENCE/('A3B-A4-'+arm+'.json')
    if not specification.exists():write(specification,spec)

proofs=['A3B-http.json','A3B-player.json','A3B-boundaries.json','A3B-desktop.json','A3B-manual.json']
for name in proofs:assert read(EVIDENCE/name).get('ok',True),name
player=read(EVIDENCE/'A3B-player.json')
http=read(EVIDENCE/'A3B-http.json')
project=Path(http['preview']['project'])
for relative,digest in player['sourceHashes'].items():assert sha(project/relative)==digest,relative
for path in (REPO/'apps/scroll-study/www').rglob('*'):
    if path.is_file() and '__pycache__' not in path.parts:
        assert sha(path)==sha(project/'www'/path.relative_to(REPO/'apps/scroll-study/www')),path
source_files=[*list((REPO/'apps/scroll-study').rglob('*')), *list((REPO/'scripts/scroll_vendor').rglob('*')),
    *list((REPO/'config').glob('scroll-study*')),REPO/'config/neyvia_manuals.json',REPO/'manuals/scroll-generator.manual.json',
    *[REPO/'src/grant_agent'/n for n in ['scroll_pack.py','scroll_generation.py','scroll_cost.py','neyvia_scroll.py','neyvia_workspace_tools.py','neyvia_ui_api.py','web_backend.py','desktop_bridge.py']],
    REPO/'plugins/neyvia/mcp/neyvia_mcp.py',*list((REPO/'scripts').glob('*scroll*')),REPO/'scripts/seal_A3B.py']
source_hashes={str(p.relative_to(REPO)):sha(p) for p in source_files if p.is_file() and '__pycache__' not in p.parts}
artifact_hashes={str(p.relative_to(REPO)):sha(p) for p in EVIDENCE.glob('A3B*') if p.is_file() and p.name!='A3B.json'}
artifact_hashes.update({str(p.relative_to(REPO)):sha(p) for p in (EVIDENCE/'A3B-runs').rglob('*') if p.is_file()})
write(EVIDENCE/'A3B.json',{'schema':'neyvia.A3B.v1','ok':True,'sealedAt':datetime.now(timezone.utc).isoformat(),
    'scope':{'branch':'track/a3-backend','ports':[48591,48592],'protectedTreesTouched':False,'credentialsRead':False,'nasSync':False,'published':False},
    'source':{'studyNotes':str(notes.relative_to(REPO)),'sha256':sha(notes),'origin':'docs/research/scroll-study-learning.md sections 2.1-2.5, retitled for one learning chapter'},
    'mechanism':{'cards':len(row['value']['cards']),'concepts':len(row['value']['concepts']),'answerChecks':row['value']['generation']['answerChecks'],'compiledValidation':read(EVIDENCE/'A3B-manual.json')['compiled']['scriptId'],'warmRun':warm_id,'sdkCommit':'0e4aab00'},
    'cost':{'developmentIncludingFailures':current,'exactWarmReplay':warm,'billing':prices['_provenance'],'targets':{'smallCallsPerCardMax':0.6,'bigCallsPerCardMax':0.05,'developmentSmallPassed':current['smallCallsPerCard']<=0.6,'developmentBigPassed':current['bigCallsPerCard']<=0.05}},
    'gates':{'validator':read(RAW/'validator-proof.json'),'property':read(REPO/'apps/scroll-study/scripts/property-results.json'),'proofs':proofs},
    'providerReceipts':provider_receipts,'sourceHashes':source_hashes,'artifactHashes':artifact_hashes,'limitations':limitations})
print(json.dumps({'ok':True,'cards':current['cards'],'costPerCard':current['perCard'],'costPerStudyHour':current['costPerStudyHour'],'warm':warm['totalUsd'],'providerReceipts':len(provider_receipts)}))
