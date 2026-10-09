"""Freeze exact Git ref source bytes inside INT3 for matched isolated tests."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import os

REPO = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--working', action='store_true')
    args = parser.parse_args()
    if not args.label.replace('-', '').replace('_', '').isalnum():
        parser.error('simple label required')
    sha = subprocess.check_output(['git', 'rev-parse', args.ref], cwd=REPO, text=True).strip()
    target = REPO / '.agent_control/int3' / (args.label + '-src')
    if target.exists():
        parser.error('snapshot exists; use a new label')
    target.mkdir(parents=True)
    names = subprocess.check_output(['git', 'ls-files'] if args.working else ['git', 'ls-tree', '-r', '--name-only', sha], cwd=REPO, text=True).splitlines()
    hashes, excluded = {}, []
    batch = None if args.working else subprocess.Popen(['git', 'cat-file', '--batch'], cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    for name in names:
        lower = name.lower()
        if lower.startswith(('.agent_control/', 'scripts/evidence/int3/')) or lower == 'scripts/evidence/int3.json' or any(word in lower for word in ('nas_access_runbook', 'nas_codex2_', 'auth.json', 'credentials.json', 'admin_password')):
            excluded.append(name)
            continue
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if args.working:
            source = REPO / name
            if not source.is_file():
                continue
            if lower.startswith('scripts/evidence/'):
                os.link(source, destination)
                body = source.read_bytes()
            else:
                body = source.read_bytes()
                destination.write_bytes(body)
        else:
            batch.stdin.write(f'{sha}:{name}\n'.encode())
            batch.stdin.flush()
            header = batch.stdout.readline().decode().strip().split()
            if len(header) != 3:
                raise RuntimeError('missing Git object: ' + name)
            body = batch.stdout.read(int(header[2]))
            if batch.stdout.read(1) != b'\n':
                raise RuntimeError('invalid Git object boundary')
            destination.write_bytes(body)
        hashes[name] = hashlib.sha256(body).hexdigest()
    if batch:
        batch.stdin.close()
        batch.wait()
    manifest = {'ref': args.ref, 'head': sha, 'snapshot': str(target), 'files': len(hashes), 'hashes': hashes, 'excluded': excluded,
                'workingBytes': args.working,
                'archivalExclusionBoundary': 'INT3 new receipts, scratch/private file names excluded identically. Historical evidence retained; working archive evidence uses hardlinks and source integrity checked after tests.'}
    (target.parent / (args.label + '-snapshot.json')).write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'snapshot': str(target), 'files': len(hashes), 'excluded': len(excluded), 'ref': sha}))

if __name__ == '__main__':
    main()
