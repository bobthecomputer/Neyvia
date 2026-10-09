"""Fork sealed task source, sharing only integrity-checked historical evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTROL = REPO / '.agent_control/int3'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--patch', action='append', default=[])
    parser.add_argument('--defer-archive-check', action='store_true',
                        help='Reuse the sealed parent archive hashes; final comparator must rehash every file')
    args = parser.parse_args()
    if any(not value.replace('-', '').replace('_', '').isalnum() for value in (args.parent, args.label)):
        parser.error('simple snapshot labels required')
    source = CONTROL / (args.parent + '-src')
    target = CONTROL / (args.label + '-src')
    manifest_path = CONTROL / (args.label + '-snapshot.json')
    if manifest_path.exists() or (target / 'src').exists():
        parser.error('fork source already exists')
    archive = target / 'scripts/evidence'
    if not archive.exists() or archive.resolve() != (source / 'scripts/evidence').resolve():
        parser.error('prepare a task-local historical-evidence junction to the parent archive')
    manifest = json.loads((CONTROL / (args.parent + '-snapshot.json')).read_text())
    patches = set(args.patch)
    if not patches <= manifest['hashes'].keys() or any(name.startswith('scripts/evidence/') for name in patches):
        parser.error('patch only existing mutable source; historical evidence is immutable')
    hashes = {}
    for name, expected in manifest['hashes'].items():
        if args.defer_archive_check and name.startswith('scripts/evidence/'):
            hashes[name] = expected
            continue
        body = (source / name).read_bytes()
        if hashlib.sha256(body).hexdigest() != expected:
            raise ValueError('Parent snapshot changed: ' + name)
        if name in patches:
            body = (REPO / name).read_bytes()
        destination = target / name
        if not name.startswith('scripts/evidence/'):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body)
        hashes[name] = hashlib.sha256(body).hexdigest()
    manifest.update(snapshot=str(target), hashes=hashes, parentSnapshot=args.parent,
                    workingBytes=True, preExecutionPatches=sorted(patches),
                    archivalExclusionBoundary='Mutable source copied independently; historical evidence shared through a task-local parent archive junction and checked byte-for-byte before and after execution.')
    if args.defer_archive_check:
        manifest['archivalExclusionBoundary'] = ('Mutable source copied and checked independently. Sealed parent archive hashes retained without another pre-execution rehash; mandatory final comparator checks every archived byte after execution.')
        manifest['archiveRehashDeferredToFinalComparator'] = True
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'snapshot': str(target), 'files': len(hashes), 'patched': len(patches)}))


if __name__ == '__main__':
    main()
