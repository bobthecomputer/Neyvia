"""Author the bounded pinned environment CL procedures without editing the index."""
import json
from pathlib import Path
import sys
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.cl.environment_effects import SUPPORTED
from grant_agent.native_tools import NativeToolRegistry


def main():
    registry = NativeToolRegistry(REPO / '.agent_control/fixcl3-environment-manual-schema')
    schemas = {name: registry.describe(name)['inputSchema'] for name in sorted(SUPPORTED)}
    actions, procedures = {}, {}
    for name, schema in schemas.items():
        key = name.replace('.', '-')
        inputs = json.loads(json.dumps(schema)); inputs['required'] = list(schema['properties'])
        actions[key] = {'tool': name, 'schema': name, 'returns': {'type': 'object'},
            'pre': 'Explicit workspace execution grant, bounded pinned lock or scoped saved Python script and newly created output paths',
            'effect': 'Create and independently probe a pinned interpreter or run exact saved source and verify newly written declared file bytes', 'reversible': False}
        procedures['verify-' + key] = {'goal': registry.describe(name)['description'], 'inputs': inputs,
            'steps': [{'action': key, 'args': {k: {'$input': k} for k in schema['properties']}, 'save': 'saved'}]}
    data = {'schema': 'neyvia.manual.v1', 'id': 'local-environment', 'kind': 'workflow', 'schemas': schemas,
        'chapters': {'environment': {'title': 'Pinned local interpreters and declared task effects', 'state': {},
            'actions': actions, 'checks': {}, 'procedures': procedures, 'judge': {},
            'pitfalls': [{'failure': 'An old matching output or forged process receipt is mistaken for a new effect',
                         'recovery': 'Use a new declared output path and exact SHA256; completion rechecks bytes, script, argv and interpreter.'},
                         {'failure': 'The pinned lock or script changes after execution',
                          'recovery': 'Completion is refused; preserve the original run and use a new explicit environment or script.'}],
            'frontier': ['Only declared new workspace output files establish the run effect. Other side effects require their own observer.',
                         'Inline -c/-m execution, reused output files and absent declared output hashes remain CL frontier.',
                         'A Python dependency environment is not an OS sandbox. Offline empty-lock proof does not establish external dependency installation.'],
            'guidance': ['Use only already installed uv and Python. Respect network, installation and workspace authority.',
                         'The creation proof uses a real interpreter probe. Run receipts bind actual argv, source/interpreter hashes and declared outputs.']}}}
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError('Local-environment manual did not round trip')
    (REPO / 'manuals/local-environment.manual.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
    (REPO / 'manuals/cl/local-environment.cl').write_text(source, encoding='utf-8', newline='\n')
    print(json.dumps({'id': data['id'], 'actions': len(actions), 'roundTrip': True}))


if __name__ == '__main__':
    main()
