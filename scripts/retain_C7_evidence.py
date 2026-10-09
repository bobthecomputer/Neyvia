"""Deduplicate historical C7 scratch while preserving receipt-referenced files.

Only task-local historical C7 directories are eligible. Each archived byte is
verified before its redundant loose copy is removed; the manifest restores paths.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import zipfile
import uuid
import stat

REPO = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def scope():
    control = (REPO / '.agent_control').resolve()
    roots = [p for p in control.iterdir() if p.name.lower().startswith('c7') and not p.name.lower().startswith('c7d')]
    proofs = control / 'proofs'
    roots += [p for p in proofs.iterdir() if p.name.lower().startswith('c7') and not p.name.lower().startswith('c7d')]
    files = set()
    for root in roots:
        candidates = root.rglob('*') if root.is_dir() else [root]
        for p in candidates:
            resolved = p.resolve()
            resolved.relative_to(control)
            if p.is_file() and not p.is_symlink():
                files.add(resolved)
    return files


def references(files):
    seeds = [p for p in (REPO / 'scripts/evidence').glob('C7*') if p.is_file() and p.suffix in {'.json', '.gz'}]
    found, visited, pending = set(), set(), seeds[:]
    aliases = {}
    for p in files:
        for name in (str(p), p.as_posix(), str(p.relative_to(REPO)), p.relative_to(REPO).as_posix()):
            aliases[name.casefold()] = p
    def walk(value):
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif (isinstance(value, str) and len(value) < 1024
              and (value.startswith('.agent_control/') or value.startswith('.agent_control\\')
                   or value.lower().startswith(str(REPO).lower())
                   or value.lower().startswith(REPO.as_posix().lower()))):
            try:
                p = aliases.get(value.casefold())
                if p is not None:
                    found.add(p)
                    if p.suffix in {'.json', '.gz'} and p not in visited:
                        pending.append(p)
            except (ValueError, OSError):
                pass
    while pending:
        p = pending.pop()
        if p in visited:
            continue
        visited.add(p)
        try:
            raw = gzip.decompress(p.read_bytes()) if p.suffix == '.gz' else p.read_bytes()
            walk(json.loads(raw))
        except (ValueError, OSError, EOFError):
            continue
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', type=Path, help='Resume pruning after a verified historical archive was written')
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(REPO / 'scripts/evidence')
    files = scope()
    print(json.dumps({'stage':'inventory','files':len(files)}),flush=True)
    retained = references(files)
    print(json.dumps({'stage':'references','files':len(retained)}),flush=True)
    candidates = sorted(files - retained)
    archive = REPO / '.agent_control/C7d' / ('historical-evidence-' + uuid.uuid4().hex + '.zip')
    if args.resume:
        archive = args.resume.resolve()
        archive.relative_to(REPO / '.agent_control/C7d')
    before = sum(p.stat().st_size for p in files)
    if not args.apply:
        print(json.dumps({'bytesBefore': before, 'files': len(files), 'receiptReferencedFiles': len(retained), 'archiveCandidates': len(candidates)}))
        return
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists() and not args.resume:
        raise ValueError('Do not overwrite a retained historical archive')
    manifest, seen = [], set()
    if args.resume:
        with zipfile.ZipFile(archive) as reader:
            manifest = json.loads(reader.read('manifest.json'))
            seen = {row['sha256'] for row in manifest}
            before = sum(row['bytes'] for row in manifest) + sum(p.stat().st_size for p in retained)
    else:
        with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as writer:
            for p in candidates:
                data = p.read_bytes()
                sha = digest(data)
                manifest.append({'path': p.relative_to(REPO).as_posix(), 'sha256': sha, 'bytes': len(data)})
                if sha not in seen:
                    writer.writestr('blobs/' + sha, data)
                    seen.add(sha)
                if len(manifest) % 1000 == 0:
                    print(json.dumps({'stage':'archive','paths':len(manifest)}),flush=True)
            writer.writestr('manifest.json', json.dumps(manifest, separators=(',', ':')))
    with zipfile.ZipFile(archive) as reader:
        for sha in seen:
            if digest(reader.read('blobs/' + sha)) != sha:
                raise ValueError('Compressed byte verification failed')
        if json.loads(reader.read('manifest.json')) != manifest:
            raise ValueError('Compressed path manifest differs')
    # Mutation starts only after the complete recoverable archive has passed.
    for row in manifest:
        p = (REPO / row['path']).resolve()
        p.relative_to(REPO / '.agent_control')
        if args.resume and not p.exists():
            continue
        if p not in files or p in retained or digest(p.read_bytes()) != row['sha256']:
            raise ValueError('Scratch file changed during retention: ' + row['path'])
        try:
            p.unlink()
        except PermissionError:
            if not p.stat().st_mode & stat.S_IWRITE:
                p.chmod(stat.S_IWRITE)
                p.unlink()
            else:
                raise
    after = sum(p.stat().st_size for p in scope()) + archive.stat().st_size
    receipt = {'schema': 'neyvia.c7-retention.v1', 'ok': True,
        'bytesBefore': before, 'bytesAfterIncludingArchive': after,
        'receiptReferencedFilesPreserved': len(retained), 'archivedPaths': len(manifest),
        'uniqueBlobs': len(seen), 'archive': archive.relative_to(REPO).as_posix(),
        'archiveSha256': digest(archive.read_bytes()), 'archiveBytes': archive.stat().st_size,
        'allArchivedBytesVerified': True, 'manifest': 'manifest.json',
        'boundary': 'Historical C7 scratch only; C7d working roots and all tracked evidence stay untouched'}
    output.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
