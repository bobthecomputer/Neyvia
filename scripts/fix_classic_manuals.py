"""Maintain FIX navigation contracts in authored CL, then compile normally."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl


def main():
    source = ROOT / 'manuals/cl/neyvia.cl'
    data = cl_to_manual(source.read_text(encoding='utf-8'))
    pane = data['schemas']['neyvia.pane.show']
    for kind in ('outputs', 'perception'):
        if kind not in pane['properties']['kind']['enum']:
            pane['properties']['kind']['enum'].append(kind)
    source.write_text(manual_to_cl(data), encoding='utf-8', newline='\n')
    def refresh_kinds(value):
        if isinstance(value, dict):
            if value.get('enum') == pane['properties']['kind']['enum'][:-2]:
                value['enum'] = deepcopy(pane['properties']['kind']['enum'])
            for item in value.values():
                refresh_kinds(item)
        elif isinstance(value, list):
            for item in value:
                refresh_kinds(item)
    for other in sorted((ROOT / 'manuals/cl').glob('*.cl')):
        contents = other.read_text(encoding='utf-8')
        compiled = cl_to_manual(contents)
        if 'neyvia.pane.show' in compiled['schemas']:
            previous = deepcopy(compiled)
            compiled['schemas']['neyvia.pane.show'] = deepcopy(pane)
            refresh_kinds(compiled)
            if previous != compiled:
                other.write_text(manual_to_cl(compiled), encoding='utf-8', newline='\n')
    for identity, kind in [('outputs', 'outputs'), ('perception', 'perception')]:
        source = ROOT / f'manuals/cl/{identity}.cl'
        data = cl_to_manual(source.read_text(encoding='utf-8'))
        data['schemas']['neyvia.pane.show'] = deepcopy(pane)
        data['schemas']['neyvia.state'] = {'type': 'object', 'properties': {}, 'required': []}
        chapter = data['chapters'].setdefault('navigation', {
            'title': 'Shared pane navigation', 'state': {}, 'actions': {}, 'checks': {},
            'procedures': {}, 'judge': {}, 'pitfalls': [], 'frontier': [], 'guidance': [],
        })
        chapter['actions']['pane.show'] = {
            'tool': 'neyvia.pane.show', 'schema': 'neyvia.pane.show',
            'pre': 'Selected workspace; typed target belongs to the requested pane',
            'effect': 'Persist a shared UI bus request. UI acknowledgement proves rendered opening.',
            'returns': {'type': 'object'}, 'reversible': True,
        }
        chapter['checks']['pane-request-saved'] = {
            'tool': 'neyvia.state', 'args': {}, 'expect': {'op': 'eq', 'path': 'pane',
                'value': {'kind': kind, 'target': {'$input': 'target'}}},
        }
        chapter['procedures']['request-pane'] = {
            'goal': f'Persist and independently observe the {kind} pane request',
            'inputs': {'type': 'object', 'properties': {'target': {'type': 'string'}}, 'required': ['target']},
            'steps': [{'action': 'pane.show', 'args': {'kind': kind, 'target': {'$input': 'target'}},
                       'save': 'requested', 'check': 'pane-request-saved'}],
        }
        if 'A persisted bus request does not prove the UI rendered the pane.' not in chapter['frontier']:
            chapter['frontier'].append('A persisted bus request does not prove the UI rendered the pane.')
        source.write_text(manual_to_cl(data), encoding='utf-8', newline='\n')
    # These two sources have no other FIX edits. Preserve their authored type
    # layout rather than churning aliases through a full serialization.
    before = r'\"preview\"]'
    after = r'\"preview\",\"outputs\",\"perception\"]'
    for identity in ('neyvia', 'design'):
        path = ROOT / f'manuals/cl/{identity}.cl'
        original = subprocess.check_output(['git', 'show', f'HEAD:manuals/cl/{identity}.cl'], cwd=ROOT).decode('utf-8')
        minimal = original.replace(before, after)
        if cl_to_manual(minimal) == cl_to_manual(path.read_text(encoding='utf-8')):
            path.write_text(minimal, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
