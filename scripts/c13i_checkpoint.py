"""Preserve the inherited taste work; keep large runtime proof outside Git."""
from pathlib import Path
import datetime
import fnmatch
import hashlib
import json
import shutil
import subprocess

REPO=Path(__file__).resolve().parents[1]
PATTERNS=['scripts/evidence/c13-runtime/**','**/browser/**','**/service/**',
    '**/host-state.json','**/evidence/rounds.json','**/events.jsonl','**/reasoning.txt','**/prompt.txt',
    'proof/**/render/**','proof/r12/learning/vision-cache/**','proof/r12/learning/pair-embeddings/**',
    '.neyvia/lessons/**','scripts/evidence/**/tests/**','scripts/evidence/**/*.test.mjs']

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):h.update(part)
    return h.hexdigest()

def names(args):
    return [p for p in subprocess.check_output(['git',*args,'-z'],cwd=REPO).decode('utf-8').split('\0') if p]

def main():
    pending=names(['ls-files','--others','--exclude-standard'])
    modified=names(['diff','--name-only'])
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target=Path('D:/NeyviaRuns/r12/inherited-checkpoints')/stamp
    target.mkdir(parents=True,exist_ok=False)
    raw=[];portable=[];extra=[]
    for relative in pending:
        source=REPO/relative
        if not source.is_file():continue
        if not source.resolve().is_relative_to(REPO.resolve()):raise ValueError('Outside worktree: '+relative)
        large=source.stat().st_size>1024*1024
        is_raw=large or any(fnmatch.fnmatch(relative,p) for p in PATTERNS) or source.suffix.lower() in {'.exe','.zip','.sqlite','.db','.lock'}
        if not is_raw:
            portable.append(relative);continue
        destination=target/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,destination)
        digest=sha(source)
        if sha(destination)!=digest:raise ValueError('Archive readback mismatch')
        raw.append({'path':relative,'archived':str(destination),'bytes':source.stat().st_size,'sha256':digest})
        if not any(fnmatch.fnmatch(relative,p) for p in PATTERNS):extra.append('/'+relative)
    # Tracked historical aggregates stay compatible and are also preserved on D.
    for relative in modified:
        source=REPO/relative
        if source.is_file() and source.stat().st_size>1024*1024:
            destination=target/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,destination)
            digest=sha(source)
            if sha(destination)!=digest:raise ValueError('Tracked archive mismatch')
            raw.append({'path':relative,'archived':str(destination),'bytes':source.stat().st_size,'sha256':digest,'tracked':True})
    ignore=REPO/'.gitignore'
    current=ignore.read_text(encoding='utf-8')
    patterns=['/'+p for p in PATTERNS]+extra
    missing=[p for p in patterns if p not in current.splitlines()]
    if missing:ignore.write_text(current.rstrip()+'\n\n# C13 raw evidence is hash-preserved on D; portable receipts remain in Git.\n'+'\n'.join(missing)+'\n',encoding='utf-8')
    receipt={'schema':'neyvia.c13i.inherited-checkpoint.v1','at':stamp,'rawRoot':str(target),
        'rawFiles':raw,'portableFiles':portable,'trackedModified':modified,
        'scope':'Original files remain available for existing historical hash-bound readers; raw untracked copies are excluded from Git.'}
    evidence=REPO/'proof/r12/inherited-checkpoint.json'
    evidence.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    candidates=sorted(set(portable+modified+['.gitignore','scripts/c13i_checkpoint.py','proof/r12/inherited-checkpoint.json']))
    groups={'historical':[p for p in candidates if not p.startswith('proof/r12/')],
            'r12':[p for p in candidates if p.startswith('proof/r12/')]}
    for group,paths in groups.items():
        paths=[p for p in paths if (REPO/p).is_file()]
        for p in paths:
            file=REPO/p
            if file.suffix=='.json':json.loads(file.read_text(encoding='utf-8-sig'))
            if file.suffix=='.zip' and file.stat().st_size>50*1024*1024:raise ValueError('Large zip cannot enter Git')
        index=target/(group+'-paths.nul');index.write_bytes(b'\0'.join(p.encode() for p in paths)+b'\0')
        if paths:subprocess.run(['git','add','--pathspec-from-file',str(index),'--pathspec-file-nul'],cwd=REPO,check=True)
        subprocess.run(['git','commit','-m','Preserve '+group+' taste work and portable proof after interrupted sessions',
            '-m','Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>'],cwd=REPO,check=True)
    print(json.dumps({'rawFiles':len(raw),'rawBytes':sum(r['bytes'] for r in raw),'portableFiles':len(portable),'receipt':str(evidence)}))

if __name__=='__main__':main()
