"""Reconcile completed local C7 contract families after an interrupted worker."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--partial-root', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error('Explicit assigned port required')
    partial = args.partial_root.resolve()
    partial.relative_to(REPO / '.agent_control/proofs/c7')
    source, output = args.input.resolve(), args.output.resolve()
    for path in (source, output):
        path.relative_to(REPO / 'scripts/evidence')
    from grant_agent.edge_fixture_catalog import completed_receipts, BUILDERS, summarize
    from grant_agent.edge_contracts import inventory, matrix, proof_boundary
    from grant_agent.proof_contracts import source_digest
    report = json.loads(source.read_bytes())
    if not report['ok'] or not report['sourceStable'] or report['failures'] or report['explicitPort'] != args.port:
        raise ValueError('Remaining-family campaign did not pass')
    bindings = dict(report['sourceBindings'])
    if any(source_digest(REPO / name) != expected for name, expected in bindings.items()):
        raise ValueError('Remaining-family source changed')
    root = Path(report['root']).resolve()
    root.relative_to(REPO / '.agent_control/proofs/c7')
    index = completed_receipts(root / 'semantic-fixtures')
    if index != report['familyReceipts']:
        raise ValueError('Remaining-family receipts differ')
    old = completed_receipts(partial / 'semantic-fixtures')
    expected_missing = set(BUILDERS) - {'c7d-rendered'} - {r['family'] for r in index}
    if {r['family'] for r in old} != expected_missing or not expected_missing:
        raise ValueError('Completed families do not exactly fill missing local families')
    _, contracts = inventory()
    added = []
    reused = []
    for entry in old:
        path = Path(entry['path'])
        raw = path.read_bytes()
        receipt = json.loads(raw)
        for name, expected in receipt['sourceBindings'].items():
            if name in bindings and bindings[name] != expected:
                raise ValueError('Source lineage differs: ' + name)
            bindings[name] = expected
        for row in receipt['rows']:
            if row['status'] == 'failed' or row.get('proofScope') in {'rendered', 'device', 'provider'} or row.get('liveObservation') or row.get('liveObservationNonce') or any(proof_boundary(contracts[c]) in {'rendered', 'device', 'provider'} for c in row['contracts']):
                raise ValueError('Cannot reuse failed or real-boundary case: ' + row['id'])
        destination = root / 'semantic-fixtures' / (entry['family'] + '.receipt.json')
        if destination.exists():
            raise ValueError('Destination already exists')
        destination.write_bytes(raw)
        index.append({**entry, 'path':str(destination), 'observationOrigin':entry['path']})
        reused.append({'family':entry['family'], 'origin':entry['path'], 'sha256':entry['sha256'], 'cases':len(receipt['rows'])})
        added.extend(receipt['rows'])
    bindings[Path(__file__).relative_to(REPO).as_posix()] = source_digest(Path(__file__))
    if any(source_digest(REPO / name) != expected for name, expected in bindings.items()):
        raise ValueError('Completed local source changed')
    (root / 'semantic-fixtures/families.json').write_text(json.dumps(index, indent=2) + '\n', encoding='utf8')
    if completed_receipts(root / 'semantic-fixtures') != index:
        raise ValueError('Copied family receipt differs')
    journeys = report['journeys'] + added
    if len({r['id'] for r in journeys}) != len(journeys):
        raise ValueError('Duplicate contract cases')
    coverage = matrix(contracts, journeys, semantic_fixtures=True)
    report.update(journeys=journeys, semanticCoverage=coverage, familyReceipts=index, sourceBindings=bindings,
                  semanticSummary=summarize(coverage), sourceStable=True,
                  resumedLocalFamilies={'families':reused, 'realBoundaryReuse':False, 'unchangedSourceRequired':True,
                                       'durationBoundary':'durationMs includes the completed remaining worker only; interrupted worker duration was not recorded'})
    report['failures'] = [r for r in report['schemaCases'] + report['postconditionCases'] + journeys if r['status'] == 'failed']
    report['ok'] = not report['failures']
    report['complete'] = report['ok'] and not report['schemaFrontier'] and not report['postconditionFrontier'] and all(r['status'] == 'passed' for r in coverage)
    report['counts'] = {name:dict(Counter(r['status'] for r in report[field])) for name, field in
                        {'schema':'schemaCases', 'postconditions':'postconditionCases', 'journeys':'journeys', 'semanticCoverage':'semanticCoverage'}.items()}
    baseline = json.loads((REPO / 'scripts/evidence/C7.json').read_bytes())
    actual = {(r['contract'], r['category']):r for r in coverage}
    report['baseline']['formerlyBlocked'] = dict(Counter(actual[(r['contract'], r['category'])]['status'] for r in baseline['semanticCoverage'] if r['status'] == 'blocked'))
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok':report['ok'], 'localFamilies':len(index), 'counts':report['counts']}))
    return int(not report['ok'])


if __name__ == '__main__':
    raise SystemExit(main())
