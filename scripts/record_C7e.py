"""Seal the exact C7c denominator and current generated family observations."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def reference(path):
    path = Path(path).resolve()
    path.relative_to(REPO)
    return {'path': path.relative_to(REPO).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error('Explicit assigned port required')
    source, target = args.input.resolve(), args.output.resolve()
    for path in (source, target):
        path.relative_to(REPO / 'scripts/evidence')
    raw = source.read_bytes()
    full = json.loads(raw)
    from grant_agent.proof_contracts import source_digest
    from grant_agent.edge_fixture_catalog import completed_receipts, BUILDERS
    if not full['ok'] or not full['sourceStable'] or full['explicitPort'] != args.port or full['failures']:
        raise ValueError('Campaign failed or source changed')
    for name, expected in full['sourceBindings'].items():
        if source_digest(REPO / name) != expected:
            raise ValueError('Stale campaign source: ' + name)
    counts = {key: dict(Counter(r['status'] for r in full[field])) for key, field in
              {'schema': 'schemaCases', 'postconditions': 'postconditionCases', 'journeys': 'journeys', 'semanticCoverage': 'semanticCoverage'}.items()}
    if counts != full['counts']:
        raise ValueError('Campaign counts differ')
    families = completed_receipts(Path(full['root']) / 'semantic-fixtures')
    if families != full['familyReceipts'] or {r['family'] for r in families} != set(BUILDERS):
        raise ValueError('A registered generated family is absent')
    family_counts = []
    native_recovery = None
    for entry in families:
        rows = json.loads(Path(entry['path']).read_bytes())['rows']
        tally = Counter(row['status'] for row in rows)
        family_counts.append({'family': entry['family'], 'generated': len(rows),
                              'passing': tally['passed'], 'failing': tally['failed'],
                              'blocked': tally['blocked'], 'notYetBuilt': 0,
                              'state': 'completed_source_current'})
        if entry['family'] == 'c7d-control-completion':
            recovery = [row for row in rows if 'adapters.sync.recovery' in row['contracts']]
            if len(recovery) != 8 or any(row['status'] != 'passed' for row in recovery):
                raise ValueError('All eight actual native recovery cases must pass')
            native_recovery = {'passing': 8, 'failing': 0, 'previousFailuresClosed': 6,
                               'caseIds': [row['id'] for row in recovery],
                               'familyReceiptSha256': entry['sha256'], 'sourceCurrent': True,
                               'boundary': 'Actual isolated Syncthing process and REST effects; no remote peer or NAS sync'}
    actual = {(r['contract'], r['category']): r for r in full['semanticCoverage']}
    if len(actual) != len(full['semanticCoverage']):
        raise ValueError('Duplicate matrix obligations')
    original = json.loads((REPO / 'scripts/evidence/C7.json').read_bytes())
    if any((r['contract'], r['category']) not in actual for r in original['semanticCoverage']):
        raise ValueError('Original obligation disappeared')
    previous = json.loads((REPO / 'scripts/evidence/C7c.json').read_bytes())
    previous_path = REPO / previous['fullMatrix']['path']
    if reference(previous_path)['sha256'] != previous['fullMatrix']['sha256']:
        raise ValueError('C7c baseline changed')
    previous_full = json.loads(gzip.decompress(previous_path.read_bytes()))
    pending = [r for r in previous_full['semanticCoverage'] if r['status'] == 'blocked' and r.get('blockerKind') in {'fixture_gap', 'fixture_not_implemented'}]
    if len(pending) != 4870:
        raise ValueError('Original 4,870 fixture denominator changed')
    closure = Counter(actual[(r['contract'], r['category'])]['status'] if actual[(r['contract'], r['category'])]['status'] != 'blocked' else actual[(r['contract'], r['category'])]['blockerKind'] for r in pending)
    blocked = [r for r in actual.values() if r['status'] == 'blocked']
    kinds = Counter(r['blockerKind'] for r in blocked)
    if set(kinds) - {'not_applicable', 'authority_boundary'}:
        raise ValueError('Applicable fixture/proof obligations remain: ' + str(kinds))
    authority = json.loads((REPO / 'scripts/evidence/C7d-authority.json').read_bytes())
    original_authority = authority['originalAuthorityBlockers']
    declared = original_authority + authority['additionalAuthorityBlockers']
    if len(original_authority) != 8 or {(r['contract'], r['category']) for r in blocked if r['blockerKind'] == 'authority_boundary'} != {(r['contract'], r['category']) for r in declared}:
        raise ValueError('Exact authority blocker inventory differs')
    authority_owners = {'a-cli.scheduler.capabilities': 'scheduler',
                        'control.chrome-live-action': 'c7d-control-completion'}
    for family in family_counts:
        pending_authority = [row for row in declared if authority_owners[row['contract']] == family['family']]
        family['notYetBuilt'] = len(pending_authority)
        family['unbuilt'] = len(pending_authority)
        family['casesTotal'] = family['generated'] + len(pending_authority)
        family['authorityBlocked'] = len(pending_authority)
        if pending_authority:
            family['state'] = 'allowed_cases_completed_authority_pending'
    host_path = REPO / full['hostProof']['path']
    if reference(host_path)['sha256'] != full['hostProof']['sha256']:
        raise ValueError('Host proof changed')
    host = json.loads(host_path.read_bytes())
    if not host['ok'] or not all(r['passed'] for r in host['manualChecks']):
        raise ValueError('Authored executable-manual observer checks did not pass')
    archive = target.with_name(target.stem + '-full.json.gz')
    archive.write_bytes(gzip.compress(raw, mtime=0))
    if gzip.decompress(archive.read_bytes()) != raw:
        raise ValueError('Compressed matrix differs')
    proof_names = ['C7e-aggregation.json', 'C7e-compiled.json', 'C7e-attached-manual.json', 'C7e-attached-compiled-current.json', 'C7e-dependency.json', 'C7e-recovery.json', 'C7e-recovered.zip',
                   'C7e-native-completion.json', 'C7e-vision-after.json', 'C7e-git-before.json', 'C7e-memory-before.json',
                   'C7e-browser-interrupted-before.json', 'C7e-browser-offline-after.json', 'C7e-authorization.json',
                   'C7e-stale-authorization-repair.json', 'C7e-engine-before.json', 'C7e-memory-reader-after.json', 'C7e-engine-concurrency-after.json', 'C7e-unlimited-before.json', 'C7e-unlimited-after.json',
                   'C7e-queued-probe-extended.json', 'C7e-queued-after.json', 'C7e-queued-boundaries-after.json', 'C7e-manual-compile.json',
                   'C7e-control-completion-before.json', 'C7e-bridge-after.json', 'C7e-bridge-shared-after.json', 'C7e-relay-edit-before.json', 'C7e-relay-after.json',
                   'C7e-family-aggregation.json', 'C7e-family-manual-compile.json',
                   'C7e-compiled-retention.json', 'C7e-pure-compiled-pre-freeze.json',
                   'C7e-worker-dependency-refusal.json',
                   'C7e-context-before.json', 'C7e-context-after.json', 'C7e-provider-unicode-before.json', 'C7e-compiled-reuse-before.json',
                   'C7e-typed-reference.json', 'C7e-frontend-preflight-refusal.json', 'C7e-ui-remaining-before.json',
                   'C7e-pure-compiled.json', 'C7e-frontend-compiled.json', 'C7e-preferences-skills-compiled.json', 'C7e-ui-remaining-compiled.json',
                   'C7e-sync-recovery-before.json', 'C7e-sync-idle-probe.json', 'C7e-sync-after-cleanup.json', 'C7e-sync-recovery-after.json',
                   'C7e-sync-recovery-current.json',
                   'C7e-checkpoint-retention.json', 'C7e-tokens.json',
                   'C7e-deadline-generator.json', 'C7e-parallel-generator.json',
                   'C7e-binding-before.json', 'C7e-binding-after.json',
                   'C7e-harness-gaps.md', 'C7d-authority.json', 'C7d-native-build.json']
    evidence = []
    proof_names += ['C7e-bugs.json', 'C7e-family-aggregation-ports.json', 'C7e-family-aggregation-tcp.json',
                    'C7e-capture-port-before.json', 'C7e-observer-port-before.json',
                    'C7e-offline-restart-before.json', 'C7e-offline-timeout-before.json', 'C7e-local-completion-port-before.json',
                    'C7e-rendered-new-block-refusal.json', 'C7e-worker-environment-before.json',
                    'C7e-frozen-heavy-pool-before.json', 'C7e-rendered-empty-diagnostic.json',
                    'C7e-rendered-huge-diagnostic.json', 'C7e-rendered-load-before.json',
                    'C7e-onboarding-concurrency-before.json', 'C7e-onboarding-concurrency-after.json',
                    'C7e-atomic-replace-before.json', 'C7e-atomic-replace-after.json',
                    'C7e-recovery-replay-before.json', 'C7e-vision-port-after.json',
                     'C7e-manual-marker-before.json', 'C7e-manual-marker-after.json',
                     'C7e-pool-publication-before.json', 'C7e-provider-trace.json',
                     'C7e-hook-startup-diagnostic.json']
    proof_names += [path.relative_to(REPO / 'scripts/evidence').as_posix()
                    for path in sorted((REPO / 'scripts/evidence/C7e-compiled-families').glob('*.json'))
                    if '-before-' not in path.name]
    proof_names += [path.relative_to(REPO / 'scripts/evidence').as_posix()
                    for path in sorted((REPO / 'scripts/evidence/C7e-sync-recovery').glob('*.json'))]
    for name in proof_names:
        path = REPO / 'scripts/evidence' / name
        entry = reference(path)
        if path.suffix == '.json':
            value = json.loads(path.read_bytes())
            source_bindings = value.get('sourceBindings', {})
            if source_bindings:
                entry['sourceCurrent'] = all(source_digest(REPO / k) == v for k, v in source_bindings.items())
                if not entry['sourceCurrent']:
                    entry['boundary'] = 'Historical or before-repair observation; final passing claims use current campaign family receipts'
        evidence.append(entry)
    report = {'schema': 'neyvia.c7e-receipt.v1', 'ok': True, 'complete': full['complete'], 'fixturesAccounted': True,
              'fixtureBuildComplete': set(closure) <= {'passed', 'not_applicable'},
              'explicitPort': args.port, 'sourceCurrent': True, 'sourceStable': True, 'inventory': full['inventory'], 'counts': counts,
              'baseline': full['baseline'], 'original4870FixtureClosure': dict(closure), 'blockedKinds': dict(kinds),
              'originalAuthorityBlockers': [{k: r[k] for k in ('contract', 'category', 'neededAuthority')} for r in original_authority],
              'additionalAuthorityBlockers': authority['additionalAuthorityBlockers'],
              'familyReceipts': families, 'familyCounts': family_counts, 'nativeRecovery': native_recovery,
              'bugs': {'receipt': reference(REPO / 'scripts/evidence/C7e-bugs.json'),
                       'counts': json.loads((REPO / 'scripts/evidence/C7e-bugs.json').read_bytes())['counts'],
                       'countingUnit': 'Dedicated root-cause repair commits since a6714b89; receipt bookkeeping is separate'},
              'familyCountBoundary': 'Passing/failing counts are executed generated cases; notYetBuilt counts exact invariant/category fixture slots still requiring authority. Matrix contract-pair counts retain their separate denominator.',
              'hostProof': full['hostProof'], 'sourceBindings': full['sourceBindings'],
              'fullMatrix': {**reference(archive), 'uncompressedBytes': len(raw), 'uncompressedSha256': hashlib.sha256(raw).hexdigest()},
              'evidenceReferences': evidence,
              'commitsBeforeReceipt': subprocess.run(['git', 'log', 'a6714b89..HEAD', '--format=%h %s'], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines(),
              'completionGate': 'Every applicable matched case must pass. Invariant-specific audited exclusions stay blocked/accounted. Synthetic models and receipt integrity do not supply rendered/device/provider observations.',
              'boundaries': ['Fresh native Neyvia browser observations were made inside the running campaign; stored nonces cannot supply future live proof.',
                             'Eight installed capability-doctor cases and eight legacy Chrome cases retain their exact authority requirements.',
                             'No credential reads, NAS sync, protected trees, public services, system install, push, merge or promotion.',
                             'Attached access-context automatically attempted port 8793 outside the assigned range and failed with URLError; this harness exception is recorded in C7e-harness-gaps.md and the tool was not called again.']}
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok': True, 'original4870FixtureClosure': dict(closure), 'blockedKinds': dict(kinds), 'archiveBytes': archive.stat().st_size}))


if __name__ == '__main__':
    main()
