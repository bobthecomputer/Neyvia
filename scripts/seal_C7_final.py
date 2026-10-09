"""Seal a fresh complete C7 campaign and the three resumed compiled families."""
from collections import Counter
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def reference(path):
    path = Path(path).resolve()
    return {'path': path.relative_to(REPO).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def current(bindings):
    from grant_agent.proof_contracts import source_digest
    for name, digest in bindings.items():
        path = (REPO / name).resolve()
        path.relative_to(REPO)
        if not path.is_file() or source_digest(path) != digest:
            raise ValueError('Stale source: ' + name)


def compiled_proofs(evidence):
    proofs = []
    for family in ('models', 'c7d-desktop', 'c7d-rendered'):
        path = evidence / ('C7e-' + family + '-compiled.json')
        value = json.loads(path.read_bytes())
        status = value['finalStatus']
        if (not value['ok'] or value['explicitPort'] not in range(48731, 48750)
                or value['verifiedUncompiledRuns'] != 2
                or not all(row['passed'] for row in value['compiledReplayChecks'])
                or not all(status[key] for key in ('sourceCurrent', 'receiptIntact', 'allApplicableCasesPassed'))):
            raise ValueError('Incomplete compiled replay: ' + family)
        campaign = Path(status['receipt']).resolve()
        campaign.relative_to(REPO / '.agent_control/proofs/c7')
        current(json.loads(campaign.read_bytes())['sourceBindings'])
        proofs.append({'family': family, 'proof': reference(path), 'campaign': reference(campaign),
                       'cases': status['familyCases'], 'counts': status['familyCounts']})
    return proofs


def host_checks(campaign):
    """Execute the authored manual observers against the actual final receipt."""
    from grant_agent.edge_contracts import summary
    from grant_agent.durability import atomic_write_json
    from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
    from grant_agent.neyvia_manuals import unwrap, expect
    root = Path(campaign['root']).resolve()
    root.relative_to(REPO / '.agent_control/proofs/c7')
    path = root / 'final-campaign.json'
    atomic_write_json(path, campaign)
    atomic_write_json(root / '.agent_control/c7/latest.json', {
        **summary(campaign), 'sourceBindings': campaign['sourceBindings'],
        'receipt': str(path), 'receiptSha256': reference(path)['sha256']})
    server = CompactNeyviaMCPServer(root, read_only=True, session_id='c7-final-seal')
    calls = []
    def rpc(tool, arguments):
        answer = server.handle({'jsonrpc': '2.0', 'id': len(calls) + 1, 'method': 'tools/call',
                                'params': {'name': tool, 'arguments': arguments}})
        if answer.get('error'):
            raise ValueError(answer['error'])
        value = unwrap(answer['result']['structuredContent'])
        if value.get('ok') is False:
            raise ValueError(value)
        calls.append({'tool': tool, 'arguments': arguments, 'result': value})
        return value
    rpc('neyvia.manual.load', {'id': 'edge-contracts', 'chapter': 'campaign'})
    rpc('neyvia.manual.validate', {'id': 'edge-contracts'})
    rpc('neyvia.manual.observe', {'id': 'edge-contracts', 'chapter': 'campaign', 'state': 'latest'})
    status = rpc('neyvia.verify.edges.status', {})
    checks = json.loads((REPO / 'manuals/edge-contracts.manual.json').read_bytes())['chapters']['campaign']['checks']
    outcomes = [{'check': name, 'passed': expect(status, check['expect'], {}, {}, root)}
                for name, check in checks.items()]
    if not status['receiptIntact'] or not status['sourceCurrent'] or not all(row['passed'] for row in outcomes):
        raise ValueError('Authored final manual checks failed')
    proof = root / 'final-host-proof.json'
    atomic_write_json(proof, {'ok': True, 'transport': 'actual CompactNeyviaMCPServer JSON-RPC',
                             'manualChecks': outcomes, 'calls': calls})
    return reference(proof)


def retain_artifacts(entries, compiled, host, evidence):
    """Keep byte-verified raw receipts and native proof images in Git evidence."""
    paths = {Path(entry['path']).resolve() for entry in entries}
    paths.add(REPO / host['path'])
    for proof in compiled:
        path = REPO / proof['proof']['path']
        paths.add(path)
        value = json.loads(path.read_bytes())
        root = Path(value['root'])
        paths.add(root / '.neyvia/manual-scripts' / (value['compiledScriptId'] + '.json'))
        paths.update((root / '.neyvia/manual-runs').glob('*.json'))
    for entry in entries:
        if entry['family'] == 'c7d-rendered':
            root = Path(entry['path']).parent / 'c7d-rendered'
            paths.update(root.rglob('*.png'))
            paths.update(root.rglob('*.json'))
    archive = evidence / 'C7-final-artifacts.zip'
    manifest = [reference(path) for path in sorted(paths)]
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for row in manifest:
            output.write(REPO / row['path'], row['path'])
    with zipfile.ZipFile(archive) as output:
        for row in manifest:
            if hashlib.sha256(output.read(row['path'])).hexdigest() != row['sha256']:
                raise ValueError('Retained artifact differs: ' + row['path'])
    return {**reference(archive), 'artifacts': len(manifest), 'manifest': manifest}


def seal(path, port, *, proof_observer=None):
    from grant_agent.edge_live_observations import LiveObservations
    if not isinstance(proof_observer, LiveObservations):
        raise ValueError('Final seal requires the fresh campaign-local native observer; saved receipts cannot supply live witnesses')
    from grant_agent.edge_fixture_catalog import BUILDERS, completed_receipts
    from grant_agent.durability import atomic_write_json
    evidence = REPO / 'scripts/evidence'
    campaign = json.loads(path.read_bytes())
    if not campaign['ok'] or not campaign['sourceStable'] or campaign['failures'] or campaign['explicitPort'] != port:
        raise ValueError('Final campaign failed')
    current(campaign['sourceBindings'])
    entries = completed_receipts(Path(campaign['root']) / 'semantic-fixtures')
    if entries != campaign['familyReceipts'] or {row['family'] for row in entries} != set(BUILDERS):
        raise ValueError('Expected all 44 fresh families')
    families = []
    for entry in entries:
        rows = json.loads(Path(entry['path']).read_bytes())['rows']
        counts = dict(Counter(row['status'] for row in rows))
        if not rows or set(counts) != {'passed'}:
            raise ValueError('Incomplete family: ' + entry['family'])
        families.append({'family': entry['family'], 'cases': len(rows), 'counts': counts,
                         'receipt': reference(entry['path'])})
    coverage = campaign['semanticCoverage']
    from grant_agent.edge_contracts import inventory, matrix
    _, contracts = inventory()
    if coverage != matrix(contracts, campaign['journeys'], semantic_fixtures=True, proof_observer=proof_observer):
        raise ValueError('Final coverage differs from the actual campaign journeys')
    actual = {(row['contract'], row['category']): row for row in coverage}
    if len(actual) != len(coverage):
        raise ValueError('Duplicate matrix slots')
    kinds = Counter(row['blockerKind'] for row in coverage if row['status'] == 'blocked')
    if set(kinds) - {'not_applicable', 'authority_boundary'} or any(row['status'] == 'failed' for row in coverage):
        raise ValueError('Applicable final matrix gaps: ' + str(kinds))
    authority = json.loads((evidence / 'C7d-authority.json').read_bytes())
    declared = authority['originalAuthorityBlockers'] + authority['additionalAuthorityBlockers']
    if {(row['contract'], row['category']) for row in coverage if row.get('blockerKind') == 'authority_boundary'} != {(row['contract'], row['category']) for row in declared}:
        raise ValueError('Authority inventory changed')
    previous = json.loads((evidence / 'C7.json').read_bytes())
    replay_history = previous['compiledFamilyReplays']
    if replay_history['completedBeforeInterruption'] != 41 or set(replay_history['unfinished']) != {'models', 'c7d-desktop', 'c7d-rendered'}:
        raise ValueError('Recovered compiled family inventory differs')
    if any((row['contract'], row['category']) not in actual for row in previous['semanticCoverage']):
        raise ValueError('A previous obligation disappeared')
    gaps = previous['uncoveredContractCategories']
    closure = Counter(actual[(row['contract'], row['category'])]['status'] if actual[(row['contract'], row['category'])]['status'] != 'blocked'
                      else actual[(row['contract'], row['category'])]['blockerKind'] for row in gaps)
    if len(gaps) != 165 or set(closure) - {'passed', 'not_applicable'}:
        raise ValueError('Original 165-slot closure differs')
    compiled = compiled_proofs(evidence)
    from grant_agent.edge_fixture_c7d_local import _isolate
    _isolate(Path(campaign['root']), port)
    host = host_checks(campaign)
    retained = retain_artifacts(entries, compiled, host, evidence)
    raw = json.dumps(campaign, indent=2).encode() + b'\n'
    archive = evidence / 'C7-final-full.json.gz'
    archive.write_bytes(gzip.compress(raw, mtime=0))
    if gzip.decompress(archive.read_bytes()) != raw:
        raise ValueError('Archive readback differs')
    history = evidence / ('C7-before-final-' + reference(evidence / 'C7.json')['sha256'][:12] + '.json.gz')
    history.write_bytes(gzip.compress((evidence / 'C7.json').read_bytes(), mtime=0))
    result = {'schema': 'neyvia.c7-completion.v2', 'ok': True, 'complete': campaign['complete'],
              'allowedScopeComplete': True, 'sourceCurrent': True, 'explicitPort': port,
              'completedFamilies': len(families), 'familyCounts': families,
              'caseTotals': {'passing': sum(row['cases'] for row in families), 'failing': 0,
                             'authorityBlocked': len(declared),
                             'total': sum(row['cases'] for row in families) + len(declared)},
              'inventory': campaign['inventory'], 'counts': campaign['counts'], 'blockedKinds': dict(kinds),
              'missing165Closure': {'slots': len(gaps), 'outcomes': dict(closure), 'remaining': 0},
              'uncoveredContractCategories': [], 'compiledFamilies': {'completed': 44,
                   'historicalCompleted': replay_history['completedBeforeInterruption'], 'freshFinalReplays': compiled, 'remaining': []},
              'hostProof': host, 'fullMatrix': reference(archive), 'retainedArtifacts': retained, 'previousReceipt': reference(history),
              'semanticCoverage': [{key: row[key] for key in ('contract', 'category', 'status', 'blockerKind') if key in row} for row in coverage],
              'bugs': json.loads((evidence / 'C7e-bugs.json').read_bytes())['counts'],
              'authorityBlockers': declared,
              'knownLimits': ['Obscura painting 3D is blank in headless rendering; nonblocking per Paul.',
                              'Sixteen explicit authority slots remain outside this task. Historical compiled traces are not fresh live proof.'],
              'boundary': 'All 44 source-current families executed; fresh live observations inside final campaign. No stored nonce supplies live proof.'}
    atomic_write_json(evidence / 'C7.json', result)
    print(json.dumps({key: result[key] for key in ('completedFamilies', 'caseTotals', 'missing165Closure', 'counts')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48731, 48750):
        parser.error('Explicit assigned port required')
    args.input.resolve().relative_to(REPO)
    seal(args.input.resolve(), args.port)
