"""Export reviewable real-run receipts; keep private runtime/auth state ignored."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
REPO=Path(__file__).resolve().parents[1]
E=REPO/'scripts/evidence'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def sanitize(value,target,counter):
    if isinstance(value,dict):
        if value.get('type')=='image' and isinstance(value.get('data'),str):
            raw=base64.b64decode(value['data'])
            counter[0]+=1
            image=target/f'image-{counter[0]}.png'
            image.write_bytes(raw)
            return {'type':'image','mimeType':value.get('mimeType'),'bytes':len(raw),
                    'sha256':hashlib.sha256(raw).hexdigest(),'artifact':str(image.relative_to(REPO))}
        return {k:sanitize(v,target,counter) for k,v in value.items()}
    if isinstance(value,list):return [sanitize(v,target,counter) for v in value]
    return value


report=read(E/'T18.json')
reports=[report]+[read(p) for p in E.glob('T18-iteration-*.json')]+[read(E/p) for p in ['T18-blocked-mcp.json','T18-initial-contract-failures.json']]
seen=set()
for document in reports:
    for run in document.get('evaluations',[]):
        if not run.get('root') or run['root'] in seen:continue
        seen.add(run['root'])
        root=REPO/Path(run['root'])
        target=E/'T18-runs'/root.name
        target.mkdir(parents=True,exist_ok=True)
        for filename in ['calls.jsonl','final-state.json','answer.txt','initial.png','config.json','model.stderr']:
            if (root/filename).is_file():shutil.copy2(root/filename,target/filename)
        counter=[0]
        if (root/'model.jsonl').is_file():
            with (target/'model.jsonl').open('w',encoding='utf-8') as output:
                for line in (root/'model.jsonl').read_text(encoding='utf-8').splitlines():
                    output.write(json.dumps(sanitize(json.loads(line),target,counter),ensure_ascii=False)+'\n')
        write(target/'result.json',run)
        run['evidenceRoot']=str(target.relative_to(REPO))
sources=E/'T18-sources'
sources.mkdir(exist_ok=True)
shutil.copy2(E/'.t18-runtime/chart.png',sources/'chart.png')
visual=report['visualExtraction']
for key,filename in [('evidence','image-extractor.jsonl'),('response','image-transcription.json')]:
    shutil.copy2(Path(visual[key]),sources/filename)
    visual['committed'+key.title()]=str((sources/filename).relative_to(REPO))
shutil.copy2(E/'.t18-layers/sample.webm',sources/'sample.webm')
layers=read(E/'T18-layers.json')
video=next(r['details'] for r in layers['gates'] if r['name']=='real-recorded-video-frame')
for key,filename in [('evidence','video-extractor.jsonl'),('response','video-transcription.json')]:
    shutil.copy2(Path(video['extraction'][key]),sources/filename)
    video['extraction']['committed'+key.title()]=str((sources/filename).relative_to(REPO))
shutil.copy2(Path(video['extraction']['response']).parent/'frame.png',sources/'video-frame.png')
write(E/'T18-layers.json',layers)
http=read(E/'T18-http.json')
report['integration']={'http':{'receipt':'scripts/evidence/T18-http.json','passed':sum(r['passed'] for r in http['gates']),'total':len(http['gates'])},
                       'layers':{'receipt':'scripts/evidence/T18-layers.json','passed':sum(r['passed'] for r in layers['gates']),'total':len(layers['gates'])}}
for name in ['frontier','app','final']:
    path=E/f'T18-{name}.json'
    if path.exists():
        receipt=read(path)
        report['integration'][name]={'receipt':str(path.relative_to(REPO)),'passed':receipt.get('passed',receipt.get('allPassed',False))}
summary={}
for lane in ['text','screenshot']:
    runs=[r for r in report['evaluations'] if r['lane']==lane]
    summary[lane]={'successes':sum(r['passed'] for r in runs),'tasks':len(runs),
        'inputTokens':sum(r['usage'].get('input_tokens',0) for r in runs),
        'outputTokens':sum(r['usage'].get('output_tokens',0) for r in runs),
        'cachedInputTokens':sum(r['usage'].get('cached_input_tokens',0) for r in runs),
        'agentSeconds':round(sum(r['seconds'] for r in runs),3),'agentImageBlocks':sum(r['imageBlocks'] for r in runs)}
    if lane=='text':
        summary[lane]['imageExtractionInputTokens']=visual['usage']['input_tokens']
        summary[lane]['imageExtractionOutputTokens']=visual['usage']['output_tokens']
        summary[lane]['extractionSeconds']=visual['elapsed_seconds']
    summary[lane]['totalTokensIncludingExtraction']=summary[lane]['inputTokens']+summary[lane]['outputTokens']+summary[lane].get('imageExtractionInputTokens',0)+summary[lane].get('imageExtractionOutputTokens',0)
    summary[lane]['totalSecondsIncludingExtraction']=round(summary[lane]['agentSeconds']+summary[lane].get('extractionSeconds',0),3)
summary['interpretation']='One matched native/web/chart panel after repairs; earlier failures retained. Total input counts include cache. No general superiority claim; image text lane pays an extra vision pass.'
report['comparison']=summary
report['earlierFailures']=['scripts/evidence/T18-blocked-mcp.json','scripts/evidence/T18-initial-contract-failures.json','scripts/evidence/T18-password-aria-failure.json']+report.get('history',[])
report['receiptPolicy']='Only disposable synthetic app/page/chart data is exported; runtime authentication stores remain ignored. MCP image bytes are exported as hashed artifacts rather than inline base64.'
write(E/'T18.json',report)
for path in E.glob('T18-iteration-*.json'):
    document=read(path)
    for run in document['evaluations']:
        if run.get('root'):run['evidenceRoot']=str((E/'T18-runs'/Path(run['root']).name).relative_to(REPO))
    write(path,document)
files=[p for parent in [E/'T18-runs',sources] for p in parent.rglob('*') if p.is_file()]
manifest=[{'path':str(p.relative_to(REPO)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]
write(E/'T18-artifacts.json',{'artifacts':manifest,'totalBytes':sum(p['bytes'] for p in manifest)})
print(json.dumps(summary,indent=2))
