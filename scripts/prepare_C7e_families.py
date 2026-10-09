"""Integrate generated family manuals once before freezing their replay source."""
import hashlib
import json
from pathlib import Path
from generate_C7e_family import generate, REPO
from grant_agent.edge_fixture_catalog import BUILDERS


def main():
    progress = REPO / 'scripts/evidence/C7e.json'
    before = REPO / 'scripts/evidence/C7e-before-port-blocks.json'
    if progress.exists() and not before.exists():
        before.write_bytes(progress.read_bytes())
    if progress.exists():
        value = json.loads(progress.read_bytes())
        value.update(sourceCurrent=False, boundary='Historical checkpoint before new CL registrations and disjoint port blocks; fresh replay required')
        progress.write_text(json.dumps(value, indent=2) + '\n', encoding='utf8')
    failed = REPO / '.agent_control/proofs/c7/d9f27394db9e48e3867ea64302b4fbd7/semantic-fixtures/c7d-adapters.receipt.json'
    if failed.exists():
        report = json.loads(failed.read_bytes())
        out = {'schema': 'neyvia.c7e-adapter-failures.v1', 'historical': True,
               'receipt': {'path': str(failed), 'sha256': hashlib.sha256(failed.read_bytes()).hexdigest()},
               'failures': [row for row in report['rows'] if row['status'] == 'failed'],
               'diagnosis': '15-second request deadlines expired during concurrent Git capture; resource contention versus product defect remains unclassified'}
        (REPO / 'scripts/evidence/C7e-adapters-before.json').write_text(json.dumps(out, indent=2) + '\n', encoding='utf8')
    index_path = REPO / 'config/neyvia_manuals.json'
    index = json.loads(index_path.read_bytes())
    indexed = {row['id'] for row in index['manuals']}
    for family in BUILDERS:
        # Keep the pure author as the single canonical template. All other
        # generators share it instead of duplicating the executable contract.
        if family == 'pure':
            from generate_C7e_pure import main as pure
            pure()
        else:
            wrapper = REPO / 'scripts' / ('generate_C7e_' + family.replace('-', '_') + '.py')
            wrapper.write_text('"""Compile the ' + family + ' Connected Language contract."""\nfrom generate_C7e_family import generate\n\nif __name__ == "__main__":\n    generate(' + repr(family) + ')\n', encoding='utf8', newline='\n')
            generate(family)
        identity = 'C7e-' + family
        if identity not in indexed:
            index['manuals'].append({'id': identity, 'path': 'manuals/' + identity + '.manual.json',
                                     'clSource': 'manuals/cl/' + identity + '.cl',
                                     'description': 'Generated ' + family + ' cases with strict family pass, source freshness and receipt integrity'})
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + '\n', encoding='utf8', newline='\n')
    print(json.dumps({'integratedFamilies': len(BUILDERS), 'registryManuals': len(index['manuals'])}))


if __name__ == '__main__':
    main()
