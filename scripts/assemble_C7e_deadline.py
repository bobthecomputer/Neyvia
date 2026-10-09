"""Select latest intact source-current family receipts for an honest deadline seal."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def select_roots():
    from grant_agent.edge_fixture_catalog import BUILDERS
    from grant_agent.proof_contracts import source_digest
    cache, selected, roots = {}, set(), []
    base = REPO / '.agent_control/proofs/c7'
    indexes = sorted(base.glob('*/semantic-fixtures/families.json'),
                     key=lambda path: path.stat().st_mtime_ns, reverse=True)
    for index in indexes:
        entries = json.loads(index.read_bytes())
        names = {entry['family'] for entry in entries}
        if not names or names & selected or not names <= set(BUILDERS):
            continue
        valid = True
        for entry in entries:
            path = Path(entry['path']).resolve()
            path.relative_to(index.parent)
            raw = path.read_bytes()
            value = json.loads(raw)
            if (hashlib.sha256(raw).hexdigest() != entry['sha256']
                    or not entry['sourceStable'] or not value['sourceStable']
                    or value['family'] != entry['family'] or not value['sourceBindings']):
                valid = False
                break
            for name, expected in value['sourceBindings'].items():
                source = (REPO / name).resolve()
                source.relative_to(REPO)
                if name not in cache:
                    cache[name] = source_digest(source) if source.is_file() else None
                if cache[name] != expected:
                    valid = False
                    break
            if not valid:
                break
        if valid:
            roots.append(index.parent.parent)
            selected.update(names)
    if not roots:
        raise ValueError('No intact source-current completed family receipts')
    return roots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, default=REPO / 'scripts/evidence/C7e-deadline-preview.json')
    args = parser.parse_args()
    # The existing seal validates all source bindings, exact inventory case IDs,
    # conflicting roots and receipt hashes again; selection earns no proof.
    roots = select_roots()
    command = [sys.executable, str(REPO / 'scripts/seal_C7e_deadline.py'),
               '--port', str(args.port), '--output', str(args.output)]
    for root in roots:
        command.extend(['--root', str(root)])
    subprocess.run(command, cwd=REPO, check=True)


if __name__ == '__main__':
    main()
