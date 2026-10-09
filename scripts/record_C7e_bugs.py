"""Separate source repair commits from fixture, receipt and resource repairs."""
import argparse
import json
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True, encoding='utf8').splitlines()


def product(path):
    return path == 'config/neyvia_remote.json' or (path.startswith(('src/grant_agent/', 'src-tauri/src/', 'web/src/'))
            and not path.startswith(('src/grant_agent/edge_', 'src/grant_agent/proof'))
            and path != 'src/grant_agent/cl/measured_context.py')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='a6714b89')
    args = parser.parse_args()
    groups = {'product': [], 'verificationHarness': [], 'fixtureHarness': []}
    for line in git('log', '--format=%H%x09%s', args.base + '..HEAD'):
        commit, subject = line.split('\t', 1)
        if not re.search(r'(^fix\b|\bfix(?:ed)?\b|\brepair\b|\bserialize\b|\bserializ(?:e|es)\b|\bcausal\b)', subject, re.I):
            continue
        # Proof-only titles do not add a newly discovered product defect.
        if re.match(r'(Prove|Verify|Replay|Retain|Preserve|Refresh|Bind|Seal|Record|Account|Report)', subject, re.I):
            continue
        paths = git('diff-tree', '--no-commit-id', '--name-only', '-r', commit)
        changed = [path for path in paths if product(path)]
        if changed:
            category = 'product'
        elif any(path.startswith(('src/grant_agent/proof', 'src/grant_agent/edge_contracts'))
                 or path == 'scripts/seal_C7_final.py' for path in paths):
            category = 'verificationHarness'
        elif any(path.startswith(('src/grant_agent/edge_fixture', 'scripts/')) for path in paths):
            category = 'fixtureHarness'
        else:
            continue
        groups[category].append({'commit': commit, 'rootCause': subject, 'changedSources': changed or paths})
    report = {'schema': 'neyvia.c7e-bugs.v1', 'baseCommit': args.base,
              'countingUnit': 'One dedicated root-cause repair commit; passing case rows and receipt-only commits are not product bugs',
              'counts': {name: {'found': len(rows), 'fixed': len(rows)} for name, rows in groups.items()},
              'repairs': groups,
              'resourceFailures': [
                  {'item': 'Six native sync recovery cases', 'cause': 'Disk free space below actual native 1% floor', 'productBug': False, 'latestCurrentProofRequired': True},
                  {'item': 'Two Git concurrency timeouts', 'cause': '15-second request deadline under load; isolated exact probes passed', 'productBug': False, 'classification': 'resource contention inferred, full family replay still required'}],
              'receiptBookkeeping': 'Registry/context regeneration, evidence references, source freshness, compact ledgers, archival and pruning are counted separately and are not product bug discoveries',
              'boundary': 'Commit-level repair inventory since the requested baseline. Dedicated repairs only; it does not infer fresh behavior from a commit title. Actual before/after observations and the final current-source family replay establish behavior.'}
    target = REPO / 'scripts/evidence/C7e-bugs.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps(report['counts']))


if __name__ == '__main__':
    main()
