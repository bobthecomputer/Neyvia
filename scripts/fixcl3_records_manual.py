"""Build the focused local-records executable manual without editing its index."""
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.cl.record_effects import SUPPORTED
from grant_agent.native_tools import NativeToolRegistry


def main():
    registry = NativeToolRegistry(REPO / '.agent_control/fixcl3-records-manual-schema')
    schemas = {name: registry.describe(name)['inputSchema'] for name in sorted(SUPPORTED)}
    actions, procedures = {}, {}
    for name, schema in schemas.items():
        key = name.replace('.', '-')
        actions[key] = {'tool': name, 'schema': name, 'returns': {'type': 'object'},
                        'pre': 'Exact scoped identity and intact local owner/source artifacts',
                        'effect': 'Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy',
                        'reversible': False}
        # All optional fields are bound too, so a caller cannot silently lose a
        # trace reference, cost, recipe or explicit output path in the procedure.
        procedure_schema = json.loads(json.dumps(schema))
        procedure_schema['required'] = list(schema['properties'])
        procedures['record-' + key] = {'goal': registry.describe(name)['description'], 'inputs': procedure_schema,
            'steps': [{'action': key, 'args': {field: {'$input': field} for field in schema['properties']}, 'save': 'saved'}]}
    data = {'schema': 'neyvia.manual.v1', 'id': 'local-records', 'kind': 'workflow', 'schemas': schemas,
        'chapters': {'records': {'title': 'Exact local records and declared artifact criteria', 'state': {},
            'actions': actions, 'checks': {}, 'procedures': procedures, 'judge': {},
            'pitfalls': [{'failure': 'A reported observation is mistaken for actual provider/model quality',
                         'recovery': 'Keep evidenceVerified false and use a separately authorized real provider journey.'},
                         {'failure': 'A frozen source, instrument or saved record changes',
                          'recovery': 'Completion is refused; inspect the owning source and create a new explicit trial.'}],
            'frontier': ['No provider model is invoked. No general quality, operator taste or skill improvement is established.',
                         'Dependency provisioning, host rehearsal and skill mutation require their own fresh execution witness.'],
            'guidance': ['Enable applicable collaboration preferences through the operator seam before a trial.',
                         'Instrument criteria establish exactly the measured local artifact property. Preserve failed measurements.']}}}
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError('Local-records manual did not round trip')
    (REPO / 'manuals/local-records.manual.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
    (REPO / 'manuals/cl/local-records.cl').write_text(source, encoding='utf-8', newline='\n')
    print(json.dumps({'id': 'local-records', 'actions': len(actions), 'roundTrip': True}))


if __name__ == '__main__':
    main()
