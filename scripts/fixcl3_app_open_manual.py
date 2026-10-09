"""Author exact acknowledged app/text-publication opening procedures."""
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
from grant_agent.cl.app_open_effects import SUPPORTED
from grant_agent.native_tools import NativeToolRegistry


def main():
    registry = NativeToolRegistry(REPO / '.agent_control/fixcl3-app-open-manual-schema')
    schemas = {name: registry.describe(name)['inputSchema'] for name in sorted(SUPPORTED)}
    actions, procedures = {}, {}
    for name, schema in schemas.items():
        key = name.replace('.', '-')
        inputs = json.loads(json.dumps(schema))
        inputs['required'] = list(schema['properties'])
        actions[key] = {'tool': name, 'schema': name, 'returns': {'type': 'object'},
            'pre': 'A displayable guarded text file; app must resolve to file pane, artifact must have exact available published bytes',
            'effect': 'Fresh mounted visible editor or artifact preview reports the exact text hash for this requested pane and runtime', 'reversible': True}
        procedures['open-' + key] = {'goal': 'Show the exact file or text publication in the owned Neyvia pane',
            'inputs': inputs, 'steps': [{'action': key, 'args': {key: {'$input': key} for key in schema['properties']}, 'save': 'opened'}]}
    data = {'schema': 'neyvia.manual.v1', 'id': 'local-app-open', 'kind': 'workflow', 'schemas': schemas,
        'chapters': {'apps': {'title': 'Acknowledged text opening', 'state': {},
            'actions': actions, 'checks': {}, 'procedures': procedures, 'judge': {},
            'pitfalls': [{'failure': 'A queued event is mistaken for content displayed on screen',
                         'recovery': 'Wait for the real mounted pane observation; absent renderer, stale heartbeat, hidden/replaced runtime or byte drift refuses completion.'}],
            'frontier': ['app.open admits only aliases resolving to file panes with an existing displayable text target.',
                         'artifact.open admits only published plain text using the artifact preview; markdown and binary previews remain frontier.',
                         'notes.open, onboarding.open and app_sdk.preview currently route to standalone apps/overlays without pane mounted-content acknowledgements.'],
            'guidance': ['Use Neyvia own renderer. Never substitute queue delivery or fabricate a renderer report.',
                         'A fresh completion conserves publication metadata, exact text bytes, pane identity and runtime identity.']}}}
    source = manual_to_cl(data)
    if cl_to_manual(source) != data:
        raise ValueError('App-open manual failed round trip')
    (REPO / 'manuals/local-app-open.manual.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
    (REPO / 'manuals/cl/local-app-open.cl').write_text(source, encoding='utf-8', newline='\n')
    print(json.dumps({'id': data['id'], 'actions': len(actions), 'roundTrip': True}))


if __name__ == '__main__':
    main()
