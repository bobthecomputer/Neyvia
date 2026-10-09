"""Author exact frozen-lab and context compaction procedures, index owned by lead."""
import json
from pathlib import Path
import sys
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.cl.lab_context_effects import SUPPORTED
from grant_agent.native_tools import NativeToolRegistry


def main():
    registry = NativeToolRegistry(REPO / '.agent_control/fixcl3-mechanisms-manual-schema')
    schemas = {name: registry.describe(name)['inputSchema'] for name in sorted(SUPPORTED)}
    actions, procedures = {}, {}
    for name, schema in schemas.items():
        key = name.replace('.', '-')
        actions[key] = {'tool': name, 'schema': name, 'returns': {'type': 'object'},
            'pre': 'Intact local source, frozen instruments and active durable context; selected work preferences enabled',
            'effect': 'Freeze isolated candidates, measure all candidates against identical criteria, or archive older context without losing original evidence',
            'reversible': False}
        inputs = json.loads(json.dumps(schema)); inputs['required'] = list(schema['properties'])
        procedures['verify-' + key] = {'goal': registry.describe(name)['description'], 'inputs': inputs,
            'steps': [{'action': key, 'args': {field: {'$input': field} for field in schema['properties']}, 'save': 'saved'}]}
    data = {'schema': 'neyvia.manual.v1', 'id': 'local-mechanisms', 'kind': 'workflow', 'schemas': schemas,
        'chapters': {'mechanisms': {'title': 'Frozen artifact competition and lossless context compaction',
            'state': {}, 'actions': actions, 'checks': {}, 'procedures': procedures, 'judge': {},
            'pitfalls': [{'failure': 'One failed candidate is omitted from a comparison',
                         'recovery': 'Measure every candidate named by the frozen contract and retain failed criteria.'},
                         {'failure': 'A compacted receipt hides lost instructions or original messages',
                          'recovery': 'Freshly compare every old ledger row; protected content stays active and archived content stays retrievable.'}],
            'frontier': ['A frozen local artifact measurement proves its declared criterion, not general model improvement.',
                         'Candidate promotion and provider/model execution require their own authority and real journey.'],
            'guidance': ['Use new competition identities; isolated byte snapshots preserve the original source.',
                         'Compaction needs an active bounded ledger. An empty ledger is refused rather than credited as an effect.']}}}
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError('Local-mechanisms manual did not round trip')
    (REPO / 'manuals/local-mechanisms.manual.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
    (REPO / 'manuals/cl/local-mechanisms.cl').write_text(source, encoding='utf-8', newline='\n')
    print(json.dumps({'id': data['id'], 'actions': len(actions), 'roundTrip': True}))


if __name__ == '__main__':
    main()
