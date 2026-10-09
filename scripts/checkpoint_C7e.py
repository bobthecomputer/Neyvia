"""Record current completed C7 contract families without claiming full coverage."""
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
    parser.add_argument('--root', type=Path, action='append', required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error('Explicit assigned port required')
    from grant_agent.edge_fixture_catalog import BUILDERS, completed_receipts
    rows, entries, seen = [], [], set()
    for value in args.root:
        root = value.resolve()
        root.relative_to(REPO / '.agent_control/proofs/c7')
        for entry in completed_receipts(root / 'semantic-fixtures'):
            if entry['family'] in seen:
                raise ValueError('Duplicate completed family')
            seen.add(entry['family'])
            cases = json.loads(Path(entry['path']).read_bytes())['rows']
            rows.extend(cases)
            entries.append({**entry, 'cases':len(cases), 'counts':dict(Counter(r['status'] for r in cases))})
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate observed contract case')
    authority_path = REPO / 'scripts/evidence/C7d-authority.json'
    authority = json.loads(authority_path.read_bytes())
    target = REPO / 'scripts/evidence/C7e.json'
    if target.exists() and json.loads(target.read_bytes()).get('fixturesAccounted'):
        raise ValueError('Do not replace the sealed campaign with a checkpoint')
    report = {'schema':'neyvia.c7e-progress.v1', 'ok':not any(r['status']=='failed' for r in rows),
              'complete':False, 'fixturesAccounted':False, 'fixtureBuildComplete':False,
              'explicitPort':args.port, 'sourceCurrent':True, 'completedFamilies':len(entries),
              'counts':{'completedFamilyCases':dict(Counter(r['status'] for r in rows))},
              'familyReceipts':entries, 'pendingFamilies':[f for f in BUILDERS if f not in seen],
              'originalAuthorityBlockers':[{k:r[k] for k in ('contract','category','neededAuthority')} for r in authority['originalAuthorityBlockers']],
              'additionalAuthorityBlockers':authority['additionalAuthorityBlockers'],
              'authorityReceipt':{'path':'scripts/evidence/C7d-authority.json','sha256':hashlib.sha256(authority_path.read_bytes()).hexdigest()},
              'boundary':'Incomplete checkpoint: only completed current-source family receipts. No full matrix closure, fresh rendered proof, or all-family manual completion is claimed.'}
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'ok':report['ok'], 'complete':False, 'completedFamilies':len(entries), 'counts':report['counts']}))


if __name__ == '__main__':
    main()
