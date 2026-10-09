"""Keep the six native recovery failures and their actual closure commits separate."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def ref(path):
    return {'path': path.relative_to(REPO).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error('Explicit assigned port required')
    source = args.input.resolve()
    source.relative_to(REPO / 'scripts/evidence')
    after = json.loads(source.read_bytes())
    from grant_agent.edge_fixture_catalog import completed_receipts
    from grant_agent.edge_contracts import CATEGORIES
    if not after['ok'] or after['family'] != 'c7d-control-completion' or after['explicitPort'] != args.port:
        raise ValueError('Actual selected native recovery campaign required')
    entries = completed_receipts(Path(after['root']) / 'semantic-fixtures')
    if entries != after['familyReceipts']:
        raise ValueError('Native family receipt differs')
    rows = after['rows']
    if len(entries) != 1 or json.loads(Path(entries[0]['path']).read_bytes())['rows'] != rows:
        raise ValueError('Projected native case rows differ from the intact observed family')
    if (len(rows) != len(CATEGORIES) or {r['category'] for r in rows} != set(CATEGORIES)
            or any(r['status'] != 'passed' or r['contracts'] != ['adapters.sync.recovery'] for r in rows)):
        raise ValueError('Every actual recovery category must pass')
    before_path = REPO / 'scripts/evidence/C7e-sync-recovery-before.json'
    before = json.loads(before_path.read_bytes())['failedCases']
    if len(before) != 6 or {r['category'] for r in before} != {'empty', 'huge', 'unicode', 'concurrency', 'interrupted', 'stale'}:
        raise ValueError('The exact six native recovery failures are required')
    directory = REPO / 'scripts/evidence/C7e-sync-recovery'
    directory.mkdir(exist_ok=True)
    for failed in before:
        actual = next(r for r in rows if r['id'] == failed['id'])
        detail = actual['detail']
        if not detail.get('actualNativePid') or detail.get('remoteDevices') != 0 or detail.get('generatedCredentialFilesRead') is not False:
            raise ValueError('Actual isolated native process observation required')
        target = directory / (actual['category'] + '.json')
        value = {'schema': 'neyvia.c7e-sync-recovery-closure.v1', 'ok': True, 'explicitPort': args.port,
                 'case': actual, 'priorStatus': failed['status'], 'beforeEvidence': ref(before_path), 'afterEvidence': ref(source),
                 'sourceCurrent': True, 'cause': 'Owned scratch reduced; actual native database free-space floor is satisfied.',
                 'boundary': 'Actual pinned native process and REST recovery in disposable owned state; original deadlines and disk threshold unchanged. No NAS or remote peers.'}
        if target.exists() and json.loads(target.read_bytes()) != value:
            raise ValueError('Preserve a previous closure before replacement')
        if not target.exists():
            target.write_text(json.dumps(value, indent=2) + '\n', encoding='utf8')
            subprocess.run(['git', 'add', str(target.relative_to(REPO))], cwd=REPO, check=True, capture_output=True)
            result = subprocess.run(['git', 'commit', '-m', 'Verify native sync recovery ' + actual['category'] + ' after owned scratch cleanup',
                                     '-m', 'Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>'], cwd=REPO, check=True, capture_output=True, text=True)
            print(result.stdout.splitlines()[0], flush=True)


if __name__ == '__main__':
    main()
