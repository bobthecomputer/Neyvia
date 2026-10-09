"""Author the focused local creative-records manual from current native schemas."""
from __future__ import annotations

import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl  # noqa: E402
from grant_agent.native_tools import NativeToolRegistry  # noqa: E402


def manual():
    registry = NativeToolRegistry(REPO / '.agent_control' / 'fixcl2-creative-manual-schema')
    names = ('situation.define', 'attention.create', 'attention.observe')
    schemas = {name: registry.describe(name)['inputSchema'] for name in names}
    goals = {
        'situation.define': 'Save an exact task proposal, constraints and acceptance criteria under one work identity',
        'attention.create': 'Freeze a bounded local representation experiment; no model call occurs',
        'attention.observe': 'Append one caller-reported API observation without claiming it was independently verified',
    }
    actions, procedures = {}, {}
    for name in names:
        key = name.replace('.', '-').replace('_', '-')
        input_schema = json.loads(json.dumps(schemas[name]))
        if name == 'situation.define':
            input_schema['required'] = ['workId', 'task', 'constraints', 'acceptance', 'expectedRevision']
        args = {field: {'$input': field} for field in input_schema['required']}
        actions[key] = {
            'tool': name, 'schema': name, 'returns': {'type': 'object'},
            'pre': 'Selected work identity and exact requested record fields; local owner state must be intact',
            'effect': 'Persist the exact scoped proposal or unverified observation and conserve unrelated records',
            'reversible': False,
        }
        procedures['record-' + key] = {
            'goal': goals[name], 'inputs': input_schema,
            'steps': [{'action': key, 'args': args, 'save': 'saved'}],
        }
    return {
        'schema': 'neyvia.manual.v1', 'id': 'creative-records', 'kind': 'workflow',
        'schemas': schemas,
        'chapters': {'local-records': {
            'title': 'Task proposals and reported representation experiments',
            'state': {}, 'actions': actions, 'checks': {}, 'procedures': procedures,
            'judge': {},
            'pitfalls': [
                {'failure': 'A caller-reported route or response is mistaken for independently verified model evidence',
                 'recovery': 'Treat attention observations as unverified data; run and cite a separate authorized provider evaluation.'},
                {'failure': 'A situation revision or attention experiment ID is stale',
                 'recovery': 'Read the selected owner state and retry with the current revision or a fresh experiment ID.'},
            ],
            'frontier': [
                'These records do not launch a provider, prove model improvement, or verify API responses.',
                'Browser action, operator preference, and public promotion need separate authority and observation.',
            ],
            'guidance': [
                'Use one workId consistently. Keep task contracts explicit and budget representation experiments.',
                'Preserve failed, missing, or route-mismatched observations rather than promoting a preferred variant.',
            ],
        }},
    }


def main():
    data = manual()
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError('Creative-records source did not round-trip')
    for path, content in ((REPO / 'manuals/creative-records.manual.json',
                           json.dumps(data, ensure_ascii=False, indent=2) + '\n'),
                          (REPO / 'manuals/cl/creative-records.cl', source)):
        if path.exists():
            if path.read_text(encoding='utf-8') != content:
                raise ValueError('Refusing to overwrite edited manual: ' + str(path))
        else:
            path.write_text(content, encoding='utf-8', newline='\n')
    index_path = REPO / 'config/neyvia_manuals.json'
    raw = index_path.read_bytes()
    index = json.loads(raw)
    row = {'id': data['id'], 'path': 'manuals/creative-records.manual.json',
           'description': 'Exact local task proposals and bounded caller-reported attention experiment records',
           'clSource': 'manuals/cl/creative-records.cl'}
    present = next((item for item in index['manuals'] if item['id'] == data['id']), None)
    if present and present != row:
        raise ValueError('Creative-records manual index differs')
    if not present:
        index['manuals'].append(row)
        newline = '\r\n' if b'\r\n' in raw else '\n'
        index_path.write_bytes((json.dumps(index, ensure_ascii=False, indent=2) + '\n').replace(
            '\n', newline).encode('utf-8'))
    print(json.dumps({'ok': True, 'id': data['id'],
                      'procedures': list(data['chapters']['local-records']['procedures'])}))


if __name__ == '__main__':
    main()
