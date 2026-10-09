"""Record explicit pre-execution repairs to an existing working source snapshot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--reason', required=True)
    parser.add_argument('paths', nargs='+')
    args = parser.parse_args()
    control = ROOT / '.agent_control/int3'
    if not args.label.replace('-', '').isalnum():
        parser.error('simple label required')
    if any((control / (args.label + suffix)).exists()
           for suffix in ('.invocation.json', '.outcomes.json')):
        parser.error('executed snapshots are immutable; create a new snapshot')
    manifest_path = control / (args.label + '-snapshot.json')
    manifest = json.loads(manifest_path.read_text())
    if not manifest.get('workingBytes'):
        parser.error('baseline Git snapshots cannot be refreshed')
    target = Path(manifest['snapshot']).resolve()
    if not target.is_relative_to(control):
        parser.error('snapshot outside INT3')
    changes = []
    for name in args.paths:
        source = (ROOT / name).resolve()
        if not source.is_relative_to(ROOT) or not source.is_file():
            parser.error('invalid source path: ' + name)
        name = source.relative_to(ROOT).as_posix()
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        body = source.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if not destination.exists() or not os.path.samefile(source, destination):
            destination.write_bytes(body)
        changes.append({'path': name, 'before': manifest['hashes'].get(name), 'after': digest})
        manifest['hashes'][name] = digest
    manifest['files'] = len(manifest['hashes'])
    manifest.setdefault('preExecutionRepairs', []).append({'reason': args.reason, 'changes': changes})
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'label': args.label, 'refreshedBeforeExecution': len(changes)}))


if __name__ == '__main__':
    main()
