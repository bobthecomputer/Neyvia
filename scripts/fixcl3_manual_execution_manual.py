"""Add current typed entry procedures to the existing manuals-next owner."""
from __future__ import annotations
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
    from grant_agent.native_tools import NativeToolRegistry
    from grant_agent.cl.manual_execution_effects import SUPPORTED
    registry = NativeToolRegistry(REPO / '.agent_control/fixcl3-manual-schema')
    path = REPO / 'manuals/manuals-next.manual.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    for name in sorted(SUPPORTED):
        chapter_name = 'versions' if name.endswith(('.recover', '.bind')) else 'scripts'
        chapter = data['chapters'][chapter_name]
        action_key = name.removeprefix('neyvia.manual.')
        schema = registry.describe(name)['inputSchema']
        data['schemas'][name] = schema
        inputs = json.loads(json.dumps(schema))
        inputs['required'] = list(inputs['properties'])
        chapter['procedures']['verified-' + action_key.replace('.', '-')] = {
            'goal': 'Retain exact grounded ' + action_key + ' artifact with fresh owner effect checks',
            'inputs': inputs,
            'steps': [{'action': action_key, 'args': {key: {'$input': key} for key in inputs['properties']}, 'save': 'artifact'}]}
    data['chapters']['scripts']['guidance'].append('CL execution completion requires authored verifiers on every nested mutation; compiled cohorts and model-free reruns retain exact original evidence.')
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError('Manual execution pair did not round trip')
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
    (REPO / 'manuals/cl/manuals-next.cl').write_text(source, encoding='utf-8', newline='\n')
    print(json.dumps({'manual': data['id'], 'actions': len(SUPPORTED), 'roundTrip': True}))


if __name__ == '__main__':
    main()
