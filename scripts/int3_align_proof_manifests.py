"""Regenerate enforcement sites from authoritative CL-compiled contracts."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.proof_contracts import declarations


def main():
    live = declarations()
    rows = []
    for path in sorted((ROOT / 'config/proofs').glob('*.json')):
        body = path.read_bytes()
        manifest = json.loads(body)
        prior_mapping = json.dumps(manifest.get('coverage', []), sort_keys=True)
        changes = []
        for contract in manifest.get('contracts', []):
            current = live[contract['id']]
            for key in ('id', 'phase', 'claim', 'impact'):
                if contract.get(key) != current.get(key):
                    raise ValueError('Non-site contract difference needs review: ' + contract['id'])
            if contract.get('checkedAt') != current.get('checkedAt'):
                changes.append({'contract': contract['id'], 'before': contract['checkedAt'],
                                'after': current['checkedAt']})
                contract['checkedAt'] = current['checkedAt']
        if not changes:
            continue
        assert json.dumps(manifest.get('coverage', []), sort_keys=True) == prior_mapping
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
                        encoding='utf-8', newline='\n')
        rows.append({'path': path.relative_to(ROOT).as_posix(),
                     'beforeSha256': hashlib.sha256(body).hexdigest(),
                     'afterSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                     'coverageMappingUnchanged': True, 'changes': changes})
    output = ROOT / 'scripts/evidence/int3/manifest-cl-alignment.json'
    output.write_text(json.dumps({'authority': 'CL-compiled manual contracts', 'manifests': rows},
                                indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'manifests': len(rows), 'contracts': sum(len(row['changes']) for row in rows)}))


if __name__ == '__main__':
    main()
