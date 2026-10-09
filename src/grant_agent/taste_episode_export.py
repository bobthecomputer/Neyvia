"""Append provenance-bound taste episodes for the independently owned LAYA store."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import msvcrt
import os

LABELS=Path('D:/NeyviaRuns/laya-labels/c13i.jsonl')

@contextmanager
def locked():
    LABELS.parent.mkdir(parents=True,exist_ok=True)
    with LABELS.with_suffix('.lock').open('a+b') as lock:
        if not lock.tell():lock.write(b'1');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_LOCK,1)
        try:yield
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

def episode(page_id, screenshots, label, layer, source, *, weight=1):
    if layer not in {'personal','corrective'}:raise ValueError('Unknown label layer')
    paths=[str(p) for p in screenshots if p]
    row={'domain':'taste','input':{'pageId':page_id,'screenshotPath':paths[-1] if paths else None,
        'screenshotPaths':paths,'evidenceKind':'screenshots' if paths else 'reason-only'},
        'label':label,'layer':layer,'source':source,'weight':weight}
    row['episodeId']=hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    row['at']=datetime.now(timezone.utc).isoformat()
    return row

def append(rows):
    """One UTF-8 JSON object per line; retries and resumed runs never duplicate it."""
    with locked():
        existing=[json.loads(line) for line in LABELS.read_text(encoding='utf-8').splitlines()] if LABELS.exists() else []
        ids={r.get('episodeId') for r in existing}
        added=[]
        for row in rows:
            if row['episodeId'] in ids:continue
            ids.add(row['episodeId']);added.append(row)
        if added:
            with LABELS.open('ab') as stream:
                if LABELS.stat().st_size:
                    with LABELS.open('rb') as prior:prior.seek(-1,2);last=prior.read(1)
                    if last!=b'\n':stream.write(b'\n')
                for row in added:stream.write((json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode())
                stream.flush();os.fsync(stream.fileno())
        return {'path':str(LABELS),'added':len(added),'total':len(existing)+len(added)}

def retention(row, arm, task):
    raw=Path(row['raw']);report=json.loads((raw/'render/report.json').read_bytes())
    if report['html_sha256']!=row['proposedArtifactSha256']:raise ValueError('Decision screenshot does not bind proposed source')
    shots=[s['path'] for s in report['screenshots'] if s['viewport']=='desktop' and s['theme']=='light']
    return episode('r12/'+arm+'/'+task+'/round-'+str(row['round']),shots,
        {'kind':'workflow-retention','keep':row['keep'],'paidCritic':row['paidCritic'],
         'gateRoute':(row.get('gate') or {}).get('route'),'proposedArtifactSha256':row['proposedArtifactSha256']},
        'corrective',{'path':str(raw),'round':row['round'],'model':row['model']},
        weight=1 if row['paidCritic'] else .5)

def destinations(case):
    report_path=Path(case['reportPath'])
    if hashlib.sha256(report_path.read_bytes()).hexdigest()!=case['reportSha256']:
        raise ValueError('Alternate-destination receipt changed')
    report=json.loads(report_path.read_bytes())
    return [episode('r12/'+case['arm']+'/T2/alternate/'+m['destination'],
        [s['path'] for s in report['screenshots'] if s['destination']==m['destination']],
        {'kind':'destination-preservation','passed':m['effect'],'destination':m['destination'],'sourceSha256':case['sourceSha256']},
        'corrective',{'path':case['reportPath'],'mode':'keyboard'}) for m in case['destinations']]
