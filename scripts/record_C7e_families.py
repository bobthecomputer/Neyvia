"""Commit compact proofs only for completed, current generated families."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    root.relative_to(REPO / '.agent_control/proofs/c7')
    if args.port not in range(48741, 48750):
        parser.error('Explicit assigned port required')
    from grant_agent.edge_fixture_catalog import completed_receipts
    entries = completed_receipts(root / 'semantic-fixtures')
    directory = REPO / 'scripts/evidence/C7e-families'
    directory.mkdir(exist_ok=True)
    for entry in entries:
        target = directory / (entry['family'] + '.json')
        if target.exists():
            if json.loads(target.read_bytes())['retainedReceipt']['sha256'] != entry['sha256']:
                raise ValueError('Preserve the previous family before replacing it')
            continue
        path = Path(entry['path'])
        receipt = json.loads(path.read_bytes())
        rows = receipt['rows']
        if any(r['status'] == 'failed' for r in rows):
            print(json.dumps({'family': entry['family'], 'failed': [{'id': r['id'], 'detail': r.get('detail')} for r in rows if r['status'] == 'failed']}))
            continue
        value = {'schema': 'neyvia.c7e-family-proof.v1', 'ok': True, 'explicitPort': args.port,
                 'family': entry['family'], 'generatedCases': len(rows), 'counts': dict(Counter(r['status'] for r in rows)), 'categories': dict(Counter(r['category'] for r in rows)),
                 'observedContractPairs': len({(identity, r['category']) for r in rows for identity in r['contracts']}),
                 'retainedReceipt': {'path': path.relative_to(REPO).as_posix(), 'sha256': entry['sha256'], 'bytes': path.stat().st_size},
                 'sourceStable': True, 'sourceBindingsSha256': hashlib.sha256(json.dumps(receipt['sourceBindings'], sort_keys=True).encode()).hexdigest(),
                 'proofScopes': dict(Counter(r.get('proofScope', 'declared feature boundary') for r in rows)),
                 'boundary': 'Only the exact case bindings and observations in the retained family receipt are proved; this family does not discharge unmatched matrix obligations or turn model/hash observations into rendered proof.'}
        target.write_text(json.dumps(value, indent=2) + '\n', encoding='utf8')
        subprocess.run(['git', 'add', str(target.relative_to(REPO))], cwd=REPO, check=True, capture_output=True)
        result = subprocess.run(['git', 'commit', '-m', 'Verify C7e ' + entry['family'] + ' generated cases', '-m', 'Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>'], cwd=REPO, capture_output=True, text=True, check=True)
        print(result.stdout.splitlines()[0], flush=True)


if __name__ == '__main__':
    main()
