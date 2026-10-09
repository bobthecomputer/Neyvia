"""Add typed observation/projection entry procedures to the existing owner."""
from __future__ import annotations
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    from grant_agent.native_tools import NativeToolRegistry
    from grant_agent.cl.manuals import manual_to_cl, cl_to_manual
    registry = NativeToolRegistry(REPO / '.agent_control/fixcl3-projection-schema')
    path = REPO / 'manuals/manuals-next.manual.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    chapter = data['chapters']['state']
    for name in ('neyvia.manual.observe', 'neyvia.manual.project'):
        key = name.rsplit('.', 1)[-1]
        schema = registry.describe(name)['inputSchema']
        data['schemas'][name] = schema
        inputs = json.loads(json.dumps(schema))
        inputs['required'] = list(inputs['properties'])
        chapter['procedures']['verified-' + key] = {'goal': 'Read exact ' + key + ' state with independent source/artifact verification',
            'inputs': inputs, 'steps': [{'action': key, 'args': {field: {'$input': field} for field in inputs['properties']}, 'save': 'state'}]}
        if key == 'project':
            chapter['checks']['selected-projection-handle'] = {
                'tool': name, 'args': {field: {'$input': field} for field in inputs['properties']},
                'expect': {'path': 'handle', 'op': 'eq', 'value': {'$input': 'handle'}}}
            chapter['procedures']['verified-project']['steps'][0]['check'] = 'selected-projection-handle'
    guidance = 'Observe persists a fresh source-bound handle and stream/diff; project reads an existing immutable handle. Source drift invalidates observation completion while old handles remain immutable.'
    if guidance not in chapter['guidance']:
        chapter['guidance'].append(guidance)
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError('Projection manual did not round trip')
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
    (REPO / 'manuals/cl/manuals-next.cl').write_text(source, encoding='utf-8', newline='\n')
    print(json.dumps({'id': data['id'], 'actions': 2, 'roundTrip': True}))


if __name__ == '__main__':
    main()
