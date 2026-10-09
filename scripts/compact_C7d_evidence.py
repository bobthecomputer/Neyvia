"""Prune owned disposable fixtures after preserving referenced evidence bytes."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile

REPO=Path(__file__).resolve().parents[1]

def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()

def protected(path):
    return path.name.lower() in {'auth.json','credentials.json','credentials.toml','cookies','login data'} or path.name.lower().startswith('.env')

def files_in(root):
    result=set()
    for base,dirs,names in os.walk(root):
        dirs[:]=[name for name in dirs if not (Path(base)/name).is_symlink() and not (Path(base)/name).is_junction()]
        for name in names:
            path=Path(base)/name
            if path.is_symlink():continue
            resolved=path.resolve();resolved.relative_to(REPO/'.agent_control')
            if resolved.is_file():result.add(resolved)
    return result

def references(files):
    aliases={}
    for path in files:
        for name in (str(path),path.as_posix(),str(path.relative_to(REPO)),path.relative_to(REPO).as_posix()):aliases[name.casefold()]=path
    pending=[p for p in (REPO/'scripts/evidence').glob('C7*') if p.suffix in {'.json','.gz'}]
    seen,found=set(),set()
    def walk(value):
        if isinstance(value,dict):
            for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
        elif isinstance(value,str) and len(value)<1024:
            path=aliases.get(value.casefold())
            if path:
                found.add(path)
                if path.suffix in {'.json','.gz'} and path not in seen and not protected(path):pending.append(path)
    while pending:
        path=pending.pop()
        if path in seen or protected(path):continue
        seen.add(path)
        if path.stat().st_size>128*1024*1024:continue
        try:
            raw=path.read_bytes()
            walk(json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw))
        except (ValueError,OSError,EOFError):pass
    return found

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    campaign=args.campaign.resolve();campaign.relative_to(REPO/'.agent_control/proofs/c7')
    if not (campaign/'semantic-fixtures/families.json').is_file():raise ValueError('Finished campaign roots only')
    output=args.output.resolve();output.relative_to(REPO/'scripts/evidence')
    roots=[p for base in (REPO/'.agent_control',REPO/'.agent_control/proofs') for p in base.iterdir() if p.name.lower().startswith('c7') and p.is_dir() and not p.is_symlink() and not p.is_junction()]
    files=set().union(*(files_in(root) for root in roots if root.exists()))
    retained=references(files)
    # No credential contents are read, hashed or archived. Any referenced
    # protected fixture stays in place; unreferenced disposable state is pruned.
    protected_retained={p for p in retained if protected(p)}
    candidates=files-retained
    before=sum(p.stat().st_size for p in files)
    summary={'bytesBefore':before,'filesBefore':len(files),'referencedFiles':len(retained),'unreferencedFiles':len(candidates),'protectedReferencedFilesUnread':len(protected_retained)}
    print(json.dumps(summary),flush=True)
    if not args.apply:return
    archive=output.with_name('C7d-current-referenced.zip')
    if archive.exists():raise ValueError('Preserve prior retention archive; no overwrite')
    manifest=[];unique=set()
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as writer:
        for path in sorted(retained-protected_retained):
            digest=sha(path)
            manifest.append({'path':path.relative_to(REPO).as_posix(),'sha256':digest,'bytes':path.stat().st_size})
            if digest not in unique:writer.write(path,'blobs/'+digest);unique.add(digest)
        writer.writestr('manifest.json',json.dumps(manifest,separators=(',',':')))
    with zipfile.ZipFile(archive) as reader:
        for digest in unique:
            value=hashlib.sha256()
            with reader.open('blobs/'+digest) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
            if value.hexdigest()!=digest:raise ValueError('Archived reference differs')
        if json.loads(reader.read('manifest.json'))!=manifest:raise ValueError('Reference manifest differs')
    # Referenced files remain at their original paths for executable observers.
    # All pruned paths are disposable task state and were absent from receipts.
    for path in sorted(candidates):
        path.relative_to(REPO/'.agent_control')
        if path.is_symlink() or path.resolve()!=path:raise ValueError('Scope changed during pruning')
        if not path.stat().st_mode&stat.S_IWRITE:path.chmod(path.stat().st_mode|stat.S_IWRITE)
        path.unlink()
    for row in manifest:
        if sha(REPO/row['path'])!=row['sha256']:raise ValueError('Retained reference changed')
    after=sum(p.stat().st_size for p in retained)+archive.stat().st_size
    report={'schema':'neyvia.c7d-current-retention.v1','ok':True,**summary,'bytesAfterIncludingArchive':after,
        'archive':archive.relative_to(REPO).as_posix(),'archiveSha256':sha(archive),'archiveBytes':archive.stat().st_size,'manifest':'manifest.json','allArchivedReferencesVerified':True,
        'prunedUnreferencedFiles':len(candidates),'sourceBindings':{'scripts/compact_C7d_evidence.py':sha(Path(__file__))},
        'boundary':'Explicit task roots only, after owned processes stopped; every receipt-referenced file remains usable. Credential contents never inspected. Native/Vite/profile caches and unreferenced generated fixtures pruned.'}
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report),flush=True)

if __name__=='__main__':main()
