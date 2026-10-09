"""Bounded transport repairs; preserve raw trials and repeat interrupted pairs."""
from pathlib import Path
import hashlib
import json
import os
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
PATCHES={
 'scripts/c4c_quality.py':[(
  'text=True, encoding="utf-8", timeout=timeout, **kwargs)',
  'text=True, encoding="utf-8", errors="replace", timeout=timeout,\n                                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **kwargs)')],
 'scripts/run_c4c.py':[(
  "if not stream.read(1): stream.write(b'0');stream.flush()",
  "if path.stat().st_size == 0: stream.write(b'0');stream.flush()"),(
  '        try:\n            result = run(text,root,directory/\'run\'',
  '        result = None\n        try:\n            result = run(text,root,directory/\'run\''),(
  "            result = {'passed':False,'tokens':{},'turns':[], 'failure':_sanitize(str(exc))}",
  "            saved = directory/'run/receipt.json'\n            if result is None and saved.is_file():\n                result = json.loads(saved.read_text(encoding='utf-8'))\n            if result is None:\n                result = {'passed':False,'tokens':{},'turns':[], 'failure':_sanitize(str(exc))}\n            result = {**result, 'collectorFailure':_sanitize(str(exc))}")]
}
def patched(name,data):
    if name not in PATCHES:return None
    newline='\r\n' if b'\r\n' in data else '\n'
    text=data.decode('utf-8')
    for old,new in PATCHES[name]:
        old=old.replace('\n',newline);new=new.replace('\n',newline)
        assert text.count(old)==1,(name,old)
        text=text.replace(old,new)
    return text.encode('utf-8')
def digest(data):return hashlib.sha256(data).hexdigest()

def main():
    base=REPO/'.agent_control/c4/c4c-frozen-terminal'
    assert len(list(base.glob('rep-*/*/*/result.json')))==72,'Wait for original matrix'
    freeze=json.loads((base/'frozen.json').read_text(encoding='utf-8'))
    fixes={}
    for name in PATCHES:
        old=(base/'sources'/name).read_bytes();new=patched(name,old);current=(REPO/name).read_bytes()
        assert digest(old)==freeze['sourceSha256'][name]
        assert current in (old,new),'Unexpected dirty source'
        if current==old:(REPO/name).write_bytes(new)
        fixes[name]={'frozenSha256':digest(old),'fixedSha256':digest(new),'scope':'IO/lock/metadata transport only; task/workload/check semantics unchanged'}
    (base/'post-collection-fixes.json').write_text(json.dumps(fixes,indent=2),encoding='utf-8')
    import c4c_quality as r5
    import c4c_browser as browser
    from run_c4c import browser_lock,cost
    recovered=[]
    os.environ['PYTHONIOENCODING']='utf-8'
    for path in base.glob('rep-*/*/*/result.json'):
        original=json.loads(path.read_text(encoding='utf-8'))
        if original['status']!='attempted' or 'mechanisms' in original['run']:continue
        saved=json.loads((path.parent/'run/receipt.json').read_text(encoding='utf-8'))
        backup=path.with_name('result-before-collector-repair.json')
        assert not backup.exists(),'Collection recovery already performed'
        backup.write_bytes(path.read_bytes())
        dest=path.parent/'quality-collector-recovery'
        if original['task']=='hc2-dates':quality=r5.check(original['task'],path.parent/'workspace')
        else:
            with browser_lock():
                quality=browser.browse(path.parent/'workspace/versions.md',dest,48737) if original['task']=='t4-browse' else browser.check(original['task'],path.parent/'workspace',dest,48737)
            quality={**quality,'receipt':str(dest/'receipt.json')}
        row={**original,'run':saved,'quality':quality,'costUsd':cost(saved['tokens']),
             'passed':bool(saved['passed'] and quality['passed']),
             'collectionRepair':{'original':backup.relative_to(REPO).as_posix(),'originalSha256':digest(backup.read_bytes()),
                 'reason':original['quality'].get('error'),'modelCallsAdded':0,'sameChecks':True}}
        path.write_text(json.dumps(row,indent=2,ensure_ascii=False),encoding='utf-8')
        recovered.append({'task':row['task'],'repetition':row['repetition'],'arm':row['arm'],
                          'modelFailure':saved.get('failure'),'passed':row['passed'],'tokens':saved['tokens']})
    (base/'collection-recovery.json').write_text(json.dumps(recovered,indent=2),encoding='utf-8')
    print(json.dumps({'fixes':fixes,'recovered':recovered},indent=2))
if __name__=='__main__':main()
