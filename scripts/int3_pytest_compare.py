"""Compare matched INT3 runs, preserving exact failure and finished-ID sets."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTROL = REPO / '.agent_control/int3'

def read(label):
    outcome = json.loads((CONTROL / (label + '.outcomes.json')).read_text())
    invocation = json.loads((CONTROL / (label + '.invocation.json')).read_text())
    selected = set(outcome['selected_ids'])
    completed = {row['nodeid'] for row in outcome['reports'] if row['phase'] == 'teardown'}
    return outcome, invocation, selected, completed

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--after', required=True)
    args = parser.parse_args()
    old, before, old_ids, old_finished = read(args.baseline)
    new, after, new_ids, new_finished = read(args.after)
    parity = ('guardSha256', 'deadlineClass', 'deadlineSeconds', 'deadlineBoundary', 'noUserSite', 'explicitUserPackages', 'explicitSocketpairPorts', 'allowedLocalhostPorts', 'gitCeilingDirectories', 'gitMutationBoundary', 'tokenizerCacheDirectory')
    matched = all(before.get(key) == after.get(key) for key in parity)
    new_failures = sorted(set(new['failed_ids']) - set(old['failed_ids']))
    # Deliberately deleted tests are shown separately; contract proof is the integrator's gate.
    removed = sorted(old_ids - new_ids)
    unfinished = sorted(new_ids - new_finished)
    old_unfinished = sorted(old_ids - old_finished)
    integrity = []
    for label, invocation in ((args.baseline, before), (args.after, after)):
        source = Path(invocation['source'])
        manifest = json.loads((source.parent / (source.name.removesuffix('-src') + '-snapshot.json')).read_text())
        mismatch = [name for name, sha in manifest['hashes'].items() if not (source / name).is_file() or hashlib.sha256((source / name).read_bytes()).hexdigest() != sha]
        integrity.append({'label': label, 'mismatches': mismatch})
    result = {'schema': 'neyvia.int3.pytest-comparison.v1', 'matchedEnvironment': matched,
              'baseline': {'label': args.baseline, 'wallSeconds': before.get('wallSeconds'), 'collected': len(old['collected_ids']), 'selected': len(old_ids), 'finished': len(old_finished), 'failedIDs': old['failed_ids'], 'unfinishedIDs': old_unfinished},
              'after': {'label': args.after, 'wallSeconds': after.get('wallSeconds'), 'collected': len(new['collected_ids']), 'selected': len(new_ids), 'finished': len(new_finished), 'failedIDs': new['failed_ids'], 'unfinishedIDs': unfinished},
              'newFailures': new_failures, 'removedIDsRequiringContractProof': removed, 'snapshotIntegrity': integrity,
              'noNewFailures': matched and not new_failures and not unfinished and not old_unfinished and all(not row['mismatches'] for row in integrity),
              'coverageBoundary': 'Exact collected/selected/setup/teardown IDs plus stdlib executed source-line tracing; excludes subprocess execution and imports preceding sessionstart.'}
    result['lineCoverage'] = {}
    for label in (args.baseline, args.after):
        coverage = json.loads((CONTROL / (label + '.outcomes.json.coverage.json')).read_text())
        result['lineCoverage'][label] = {key: coverage[key] for key in ('method', 'executable', 'executed', 'percent')}
    destination = REPO / 'scripts/evidence/int3/pytest/comparison.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('matchedEnvironment', 'noNewFailures', 'newFailures')}))
    return int(not result['noNewFailures'])

if __name__ == '__main__':
    raise SystemExit(main())
