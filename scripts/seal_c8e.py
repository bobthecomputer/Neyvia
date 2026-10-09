"""Add a source-bound C8e review without changing immutable journey outcomes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from run_c8_inception import REPO, write


def reference(path):
    path = Path(path).resolve()
    path.relative_to(REPO)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    path = Path(args.report).resolve()
    path.relative_to(REPO / 'scripts/evidence')
    report = json.loads(path.read_text(encoding='utf-8'))
    run_id = report['provenance']['runId']
    raw_root = REPO / 'scripts/evidence/C8-runs' / run_id
    rows = {row['id']: row for row in report['rows']}
    if len(rows) != 206 or report['counts']['attempted'] != 206 or report['counts']['uncovered']:
        raise ValueError('Review requires all 206 distinct fresh attempts')
    for row in rows.values():
        result = row['result']
        actual = Path(result['workerReceipt']).resolve()
        actual.relative_to(raw_root)
        if json.loads(actual.read_text(encoding='utf-8')) != result:
            raise ValueError('Immutable worker result changed: ' + row['id'])
    hashes = report['provenance']['candidateSourceHashes']
    for name, digest in hashes.items():
        if hashlib.sha256((REPO / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen source changed: ' + name)
    baseline_path = REPO / 'scripts/evidence/C8d-final-adjudications.json'
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    prerequisites_path = REPO / 'config/inception_c8e_prerequisites.json'
    ledger = json.loads(prerequisites_path.read_text(encoding='utf-8'))['prerequisites']
    if len(ledger) != 41 or len({entry['id'] for entry in ledger}) != 41:
        raise ValueError('Exactly the original 41 prerequisites required')
    resolutions = []
    for entry in ledger:
        row = rows[entry['id']]
        result = row['result']
        effects = result.get('effectEvidence') or {}
        actual_checks = [check for check in result.get('checks', []) if check.get('passed') is True]
        resolution = 'resolved' if row['webStatus'] == 'passed' else (
            'waiting-for-C11' if result['status'] == 'waiting' else 'blocked')
        resolutions.append({**entry, 'status': resolution, 'currentWebStatus': row['webStatus'],
            'currentFailureClassification': result.get('failureClassification'),
            'currentReason': result.get('error'), 'freshReceipt': reference(result['workerReceipt']),
            'freshGoalChecks': result.get('goals', []), 'actualPassedChecks': actual_checks,
            'partialPrerequisiteEvidence': result.get('prerequisiteEvidence'),
            'partialEffectEvidence': effects,
            'resolutionMeaning': 'Resolved only when the entire fresh defining journey passes; partial local evidence never upgrades a blocked journey.'})
    aliases = {'host-runtime/@manual': 'host-runtime/overview/verify-host-runtime',
               'nearby-send-runtime/@manual': 'nearby-send-runtime/overview/verify-nearby-send-runtime',
               'neyvia-core/@manual': 'neyvia-core/overview/verify-neyvia-core',
               'runtime-provider/@manual': 'runtime-provider/overview/verify-runtime-provider'}
    bugs = []
    for identity, finding in baseline['classifications'].items():
        if finding['category'] != 'journey bug':
            continue
        replacement = aliases.get(identity, identity)
        if replacement not in rows:
            # The compiled procedure is the single non-orphan row of this manual.
            candidates = [r for r in rows.values() if r['manual'] == identity.split('/')[0] and '/@' not in r['id']]
            if len(candidates) != 1:
                raise ValueError('Ambiguous repaired journey: ' + identity)
            replacement = candidates[0]['id']
        row = rows[replacement]
        bugs.append({'originalId': identity, 'originalReason': finding['rationale'],
                     'replacementId': replacement, 'status': row['webStatus'],
                     'freshReceipt': reference(row['result']['workerReceipt'])})
    if len(bugs) != 5:
        raise ValueError('Exactly five original bugs required')
    effect_ids = set(baseline['missingProofObservations'])
    if len(effect_ids) != 36:
        raise ValueError('Exactly 36 original shallow passes required')
    policies = {}
    for name in ('effects', 'extra_effects', 'ui_effects', 'host_effects', 'state_effects'):
        overlay = json.loads((REPO / ('config/inception_c8e_' + name + '.json')).read_text(encoding='utf-8'))
        for identity, additions in overlay['bindings'].items():
            policies.setdefault(identity, {}).update(additions.get('c8eEffect', {}))
    effect_review = []
    for identity in sorted(effect_ids):
        row = rows[identity]
        result = row['result']
        evidence = result.get('effectEvidence') or {}
        contracts = evidence.get('contractEffects', [])
        required = policies.get(identity, {}).get('requiredContractIds', [])
        proved = {c['id'] for c in contracts if c.get('passed') is True}
        effect_review.append({'id': identity, 'status': row['webStatus'],
            'freshReceipt': reference(result['workerReceipt']),
            'requiredContractIds': required,
            'unprovedRequiredContractIds': sorted(set(required) - proved),
            'passedContractIds': [c['id'] for c in contracts if c.get('passed') is True],
            'unprovedContracts': [c for c in contracts if c.get('passed') is not True],
            'definingEffect': evidence, 'currentReason': result.get('error')})
    report['c8eReview'] = {'schema': 'neyvia.inception.c8e-review/v1',
        'baseline': reference(baseline_path), 'prerequisitePolicy': reference(prerequisites_path),
        'prerequisites': resolutions, 'originalJourneyBugs': bugs,
        'originalStatusReadPasses': effect_review,
        'counts': {'originalPrerequisites': 41,
            'resolvedPrerequisites': sum(e['status'] == 'resolved' for e in resolutions),
            'originalBugs': 5, 'freshRepairedPasses': sum(b['status'] == 'passed' for b in bugs),
            'originalStatusReads': 36, 'freshDefiningEffectPasses': sum(e['status'] == 'passed' for e in effect_review)},
        'needsPaul': [e for e in resolutions if e.get('needsPaul') and e['status'] != 'resolved'],
        'authorityBoundary': 'Missing isolated provider routing is not evidence of a missing outside account. Native journeys wait for C11. No saved credentials, public service, NAS or promotion was used.',
        'rawRun': reference(raw_root / 'raw.json')}
    write(path, report)
    print(json.dumps({'counts': report['counts'], 'reviewCounts': report['c8eReview']['counts'],
                      'errors': report['errors'], 'releaseGate': report['releaseGate']}))


if __name__ == '__main__':
    main()
