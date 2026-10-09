"""Independently verify and retain selected actual compiled family traces."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def ref(path):
    return {'path': path.relative_to(REPO).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--family', action='append')
    parser.add_argument('--output', type=Path, default=REPO / 'scripts/evidence/C7e-compiled-retention.json')
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error('Explicit assigned port required')
    from grant_agent.edge_fixture_catalog import completed_receipts
    from grant_agent.proof_contracts import source_digest
    retained = []
    families = args.family or ('pure', 'frontend', 'preferences-skills', 'ui-remaining')
    if len(set(families)) != len(families):
        parser.error('Family selection must be unique')
    for family in families:
        evidence = REPO / 'scripts/evidence' / ('C7e-' + family + '-compiled.json')
        proof = json.loads(evidence.read_bytes())
        status = proof['finalStatus']
        if (not proof['ok'] or proof['verifiedUncompiledRuns'] != 2 or proof['family'] != family
                or not all(c['passed'] for c in proof['compiledReplayChecks'])
                or not all(status[k] for k in ('sourceCurrent', 'receiptIntact', 'allApplicableCasesPassed'))):
            raise ValueError('Compiled family did not pass: ' + family)
        receipt = Path(status['receipt']).resolve()
        receipt.relative_to(REPO / '.agent_control/proofs/c7')
        campaign = json.loads(receipt.read_bytes())
        if not campaign['ok'] or any(source_digest(REPO / p) != d for p, d in campaign['sourceBindings'].items()):
            raise ValueError('Compiled family source changed: ' + family)
        entries = completed_receipts(Path(campaign['root']) / 'semantic-fixtures')
        if len(entries) != 1 or entries[0]['family'] != family:
            raise ValueError('Compiled family selection differs')
        rows = json.loads(Path(entries[0]['path']).read_bytes())['rows']
        if (not rows or any(r['status'] != 'passed' for r in rows) or len(rows) != status['familyCases']
                or dict(Counter(r['status'] for r in rows)) != status['familyCounts']):
            raise ValueError('Compiled family counts differ')
        root = Path(proof['root']).resolve()
        root.relative_to(REPO / '.agent_control/proofs/c7e-compiled')
        script_path = root / '.neyvia/manual-scripts' / (proof['compiledScriptId'] + '.json')
        script = json.loads(script_path.read_bytes())
        if script['scriptId'] != proof['compiledScriptId'] or script['minRuns'] != 2 or not script['zeroToken']:
            raise ValueError('Compiled script admission differs')
        runs = sorted((root / '.neyvia/manual-runs').glob('*.json'))
        if len(runs) < 3:
            raise ValueError('Expected two training traces and one compiled replay')
        journal = root / '.neyvia/manual-runs.jsonl'
        raw_journal = journal.read_bytes()
        snapshot = root / '.neyvia/manual-event-snapshots' / (hashlib.sha256(raw_journal).hexdigest() + '.jsonl')
        snapshot.parent.mkdir(exist_ok=True)
        if snapshot.exists() and snapshot.read_bytes() != raw_journal:
            raise ValueError('Immutable manual journal differs')
        snapshot.write_bytes(raw_journal)
        retained.append({'family': family, 'cases': len(rows), 'counts': status['familyCounts'],
                         'evidence': ref(evidence), 'campaign': ref(receipt), 'compiledScript': ref(script_path),
                         'manualRuns': [ref(path) for path in runs],
                         'manualEventJournal': ref(snapshot), 'sourceCurrent': True,
                         'boundary': 'Actual checked compiled procedure execution. Serialized receipts are historical observations; rendered/device/provider claims require fresh live observers in the final campaign.'})
        from grant_agent.edge_fixture_catalog import BUILDERS
        if set(families) == set(BUILDERS):
            retained[-1]['replayRuntimeJournal'] = ref(journal)
    output = args.output.resolve()
    output.relative_to(REPO / 'scripts/evidence')
    output.write_text(json.dumps({'schema': 'neyvia.c7e-compiled-retention.v1', 'ok': True,
                                 'explicitPort': args.port, 'families': retained, 'sourceStable': True,
                                 'sourceBindings': {'scripts/retain_C7e_compiled.py': source_digest(Path(__file__))}}, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok': True, 'families': [{'family': r['family'], 'cases': r['cases']} for r in retained]}))


if __name__ == '__main__':
    main()
