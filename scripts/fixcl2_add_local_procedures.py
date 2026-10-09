"""Append the FIXCL2 local procedures to the canonical JSON and CL manuals.

This keeps historical CL type identities stable while adding editable records.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cl.manuals import _source_lines, cl_to_manual  # noqa: E402


def schema(properties, required):
    return {'type': 'object', 'properties': dict(sorted(properties.items())), 'required': required,
            'additionalProperties': False}


S = {'type': 'string'}
B = {'type': 'boolean'}
PROCEDURES = {
    'projects': {
        'create-folder': {
            'goal': 'Create the selected local folder and register it after owner approval',
            'inputs': schema({'path': S, 'name': S}, ['path', 'name']),
            'steps': [{'action': 'folder.create', 'args': {'path': {'$input': 'path'}, 'name': {'$input': 'name'}}, 'save': 'created'}]},
        'create-default-project': {
            'goal': 'Create and register a named local project in the default projects folder after owner approval',
            'inputs': schema({'name': S}, ['name']),
            'steps': [{'action': 'project.create', 'args': {'name': {'$input': 'name'}}, 'save': 'created'}]},
    },
    'sessions': {
        'set-sidebar-policy': {
            'goal': 'Save a reviewed workspace cleanup policy and read it back from the owning store',
            'inputs': schema({'policy': {'type': 'object'}}, ['policy']),
            'steps': [{'action': 'sidebar.policy', 'args': {'policy': {'$input': 'policy'}}, 'save': 'saved'}]},
        'set-chat-pin': {
            'goal': 'Set the pin state of one selected existing chat',
            'inputs': schema({'id': S, 'pinned': B}, ['id', 'pinned']),
            'steps': [{'action': 'session.pin', 'args': {'id': {'$input': 'id'}, 'pinned': {'$input': 'pinned'}}, 'save': 'changed'}]},
        'set-chat-archive': {
            'goal': 'Archive or restore one selected chat after fresh active-work protection',
            'inputs': schema({'id': S, 'archived': B}, ['id', 'archived']),
            'steps': [{'action': 'session.archive', 'args': {'id': {'$input': 'id'}, 'archived': {'$input': 'archived'}}, 'save': 'changed'}]},
    },
}


def main():
    json_path = ROOT / 'manuals/neyvia.manual.json'
    cl_path = ROOT / 'manuals/cl/neyvia.cl'
    data = json.loads(json_path.read_text(encoding='utf-8'))
    text = cl_path.read_text(encoding='utf-8')
    if cl_to_manual(text) != data:
        raise ValueError('Existing CL and JSON manual differ')
    metadata = json.loads(text.splitlines()[2][len('-- @manual '):])['tool_metadata']
    for chapter_name, entries in PROCEDURES.items():
        chapter = data['chapters'][chapter_name]
        additions = []
        for key, row in entries.items():
            if key in chapter['procedures']:
                continue
            chapter['procedures'][key] = row
            additions.append('-- @record ' + json.dumps({'chapter': chapter_name, 'section': 'procedures',
                                                            'key': key, 'data': row}, sort_keys=True, separators=(',', ':'), ensure_ascii=False))
            additions.extend(_source_lines('procedures', key, row, chapter, data['schemas'], data['id'], metadata, version='1.1'))
        if additions:
            marker = '\nL neyvia.' + chapter_name + ' v1 -- '
            start = text.index(marker) + 1
            end = text.find('\nL neyvia.', start + len(marker))
            if end < 0:
                end = len(text)
            text = text[:end].rstrip('\n') + '\n' + '\n'.join(additions) + '\n' + text[end:].lstrip('\n')
    try:
        roundtrip = cl_to_manual(text)
    except Exception:
        (ROOT / '.agent_control/fixcl2-manual-debug.cl').write_text(text, encoding='utf-8')
        raise
    if roundtrip != data:
        raise ValueError('Added CL records do not round-trip to canonical JSON')
    line_ending = '\r\n' if b'\r\n' in cl_path.read_bytes() else '\n'
    cl_path.write_bytes(text.replace('\n', line_ending).encode('utf-8'))
    line_ending = '\r\n' if b'\r\n' in json_path.read_bytes() else '\n'
    json_path.write_bytes((json.dumps(data, indent=2, ensure_ascii=False) + '\n').replace('\n', line_ending).encode('utf-8'))
    print(json.dumps({'ok': True, 'procedures': list(PROCEDURES['projects']) + list(PROCEDURES['sessions'])}))


if __name__ == '__main__':
    main()
