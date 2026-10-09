"""Create the focused adaptive-work CL manual and its executable JSON artifact."""
from __future__ import annotations

import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl  # noqa: E402
from grant_agent.native_tools import NativeToolRegistry  # noqa: E402


def manual():
    registry = NativeToolRegistry(REPO / '.agent_control' / 'fixcl2-work-manual-schema')
    names = ('work.focus', 'work.problem', 'work.constraint', 'work.update_problem')
    schemas = {name: registry.describe(name)['inputSchema'] for name in names}
    actions = {name.removeprefix('work.'): {
        'tool': name, 'schema': name, 'returns': {'type': 'object'},
        'pre': 'Safe work identity and exact selected input; persisted state must be intact',
        'effect': 'Persist one revision and matching event for this work identity; conserve other fields',
        'reversible': False,
    } for name in names}
    goals = {
        'focus': 'Set the current focus while preserving all earlier problems and constraints',
        'problem': 'Record one unresolved problem and its blocker without claiming resolution',
        'constraint': 'Preserve one explicit constraint across focus changes',
        'update_problem': 'Change the selected existing problem status and next need',
    }
    procedures = {}
    for key, goal in goals.items():
        tool = 'work.' + key
        schema = json.loads(json.dumps(schemas[tool]))
        if key == 'problem':
            schema['required'] = ['workId', 'text', 'blocker']
        args = {name: {'$input': name} for name in schema['required']}
        procedures['record-' + key.replace('_', '-')] = {
            'goal': goal, 'inputs': schema,
            'steps': [{'action': key, 'args': args, 'save': 'changed'}],
        }
    return {
        'schema': 'neyvia.manual.v1', 'id': 'adaptive-work', 'kind': 'workflow',
        'schemas': schemas,
        'chapters': {'work': {
            'title': 'Adaptive work: focus, open problems, and protected constraints',
            'state': {}, 'actions': actions, 'checks': {}, 'procedures': procedures,
            'judge': {},
            'pitfalls': [
                {'failure': 'A problem ID is absent or belongs to another work identity',
                 'recovery': 'Inspect that work identity and choose an existing problem ID before updating.'},
                {'failure': 'The saved state has an integrity mismatch',
                 'recovery': 'Stop; inspect the corrupt file before any new write or recovery.'},
            ],
            'frontier': [
                'work.state initializes an absent JSON store, so it is not a pure CL observer.',
                'The state records reported work; a saved focus or problem does not prove task quality.',
            ],
            'guidance': [
                'Use the same workId for related turns. The effect check binds to its JSON revision and event.',
                'Keep constraints even when focus changes; resolve problems only by exact problem ID.',
            ],
        }},
    }


def main():
    data = manual()
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError('Adaptive-work CL source did not round-trip')
    json_path = REPO / 'manuals/adaptive-work.manual.json'
    cl_path = REPO / 'manuals/cl/adaptive-work.cl'
    artifact = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    for path, content in ((json_path, artifact), (cl_path, source)):
        if path.exists():
            if path.read_text(encoding='utf-8') != content:
                raise ValueError('Refusing to overwrite edited manual: ' + str(path))
        else:
            path.write_text(content, encoding='utf-8', newline='\n')
    index_path = REPO / 'config/neyvia_manuals.json'
    raw = index_path.read_bytes()
    index = json.loads(raw)
    row = {'id': data['id'], 'path': 'manuals/adaptive-work.manual.json',
           'description': 'Persist focus, problems and constraints under one work identity with exact revision checks',
           'clSource': 'manuals/cl/adaptive-work.cl'}
    present = next((item for item in index['manuals'] if item['id'] == data['id']), None)
    if present and present != row:
        raise ValueError('Adaptive-work manual index differs')
    if not present:
        index['manuals'].append(row)
        newline = '\r\n' if b'\r\n' in raw else '\n'
        index_path.write_bytes((json.dumps(index, ensure_ascii=False, indent=2) + '\n').replace(
            '\n', newline).encode('utf-8'))
    print(json.dumps({'ok': True, 'id': data['id'], 'procedures': list(data['chapters']['work']['procedures'])}))


if __name__ == '__main__':
    main()
