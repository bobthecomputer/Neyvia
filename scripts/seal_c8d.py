"""Derive the reviewed C8 release report without changing any raw run receipt."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from run_c8_inception import REPO, write


def reference(path):
    path = Path(path).resolve()
    path.relative_to(REPO / 'scripts/evidence')
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--adjudications', required=True)
    parser.add_argument('--baseline', nargs='+', required=True)
    args = parser.parse_args()
    path = Path(args.report).resolve()
    path.relative_to(REPO / 'scripts/evidence')
    original = json.loads(path.read_text(encoding='utf-8'))
    review_path = Path(args.adjudications).resolve()
    review = json.loads(review_path.read_text(encoding='utf-8'))
    if review['runId'] != original['provenance']['runId']:
        raise ValueError('Review must describe the exact final run')
    classifications = review['classifications']
    results = [row['result'] for row in original['rows'] if row.get('result')]
    if len(results) != 206 or len({row['id'] for row in results}) != 206:
        raise ValueError('All 206 distinct actual journey results required')
    nonpassing = {row['id'] for row in results if row['status'] != 'passed'}
    if set(classifications) != nonpassing:
        raise ValueError('Every nonpassing result needs one explicit reviewed classification')
    for result in results:
        actual = Path(result.get('workerReceipt') or (REPO / 'scripts/evidence/C8-runs' / review['runId'] /
                      result['id'].replace('/', '__').replace('@', '_') / 'result.json'))
        actual.relative_to(REPO / 'scripts/evidence/C8-runs' / review['runId'])
        if json.loads(actual.read_text(encoding='utf-8')) != result:
            raise ValueError('Report result differs from immutable worker receipt: ' + result['id'])
        if result['id'] not in classifications:
            continue
        finding = classifications[result['id']]
        if reference(finding['rawReceipt'])['sha256'] != finding['rawReceiptSha256']:
            raise ValueError('Reviewed raw receipt changed: ' + result['id'])
        if finding['category'] not in {'product bug', 'journey bug', 'environment'} or not finding['rationale']:
            raise ValueError('Explicit failure category and rationale required')
        decisive = finding.get('decisiveCall')
        if decisive and reference(decisive['receipt'])['sha256'] != decisive['sha256']:
            raise ValueError('Reviewed decisive call changed: ' + result['id'])
        result['rawFailureClassification'] = result.get('failureClassification')
        result['failureClassification'] = finding['category']
        result['adjudication'] = finding
    sys.path.insert(0, str(REPO / 'src'))
    from grant_agent.neyvia_inception import aggregate, inventory
    report = aggregate(inventory(), results, original['provenance'])
    if report['counts']['attempted'] != 206 or report['counts']['uncovered'] or report['counts']['unbound']:
        raise ValueError('Incomplete run cannot be sealed')
    report['batches'] = original['batches']
    report['executionBoundary'] = original['executionBoundary']
    report['adjudications'] = {**reference(review_path), 'counts': review.get('classificationCounts', review['counts'])}
    limitations = review.get('missingProofObservations', {})
    report['evidenceLimitations'] = ([{'id': identity, **finding} for identity, finding in limitations.items()]
                                     if isinstance(limitations, dict) else limitations)
    for finding in report['evidenceLimitations']:
        if reference(finding['rawReceipt'])['sha256'] != finding['rawReceiptSha256']:
            raise ValueError('Missing-proof observation raw receipt changed')
        for observation in finding['observations']:
            if reference(observation['callReceipt'])['sha256'] != observation['callReceiptSha256']:
                raise ValueError('Missing-proof observation call receipt changed')
    report['coverageMeaning'] = ('Web pass means the declared manual actions and fresh checks passed. '
        'A status read returning unavailable/incomplete does not prove the corresponding feature. '
        'Every native T16 replay remains blocked on C11; exact native-only steps are recorded.')
    report['history'] = []
    for name in args.baseline:
        previous = Path(name).resolve()
        data = json.loads(previous.read_text(encoding='utf-8'))
        report['history'].append({**reference(previous), 'runId': data['provenance']['runId'],
                                  'counts': data['counts'], 'errors': data['errors'],
                                  'desktopGuardPassed': data['provenance']['desktopGuard']['passed']})
    for limitation in report['evidenceLimitations']:
        identity = limitation.get('id') or limitation.get('journey')
        if identity:
            manual = next(row['manual'] for row in report['rows'] if row['id'] == identity)
            report['perManual'][manual].setdefault('evidenceLimitations', []).append(limitation)
    report['productRepairs'] = [
        {'commit': 'd8a63996', 'change': 'Native-only efficiency avoids managed-provider credentials'},
        {'commit': '2973222e', 'change': 'Autopilot get/list/stop avoid provider initialization'},
        {'commit': '8552d425', 'change': 'Page and cleanup errors refuse an Inception pass'},
        {'commit': '66772347', 'change': 'SDK service-worker SecurityError is handled in sandboxed previews; Playwright injection failure is separately repaired in the harness'},
        {'commit': 'f9c8cce1', 'change': 'Serve PDF JavaScript worker .mjs with JavaScript MIME and module cache policy'}]
    report['rawRun'] = reference(REPO / 'scripts/evidence/C8-runs' / original['provenance']['runId'] / 'raw.json')
    write(path, report)
    print(json.dumps({'counts': report['counts'], 'errors': report['errors'], 'releaseGate': report['releaseGate']}))


if __name__ == '__main__':
    main()
