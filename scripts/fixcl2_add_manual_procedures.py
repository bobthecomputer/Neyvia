"""Add exact quarantined manual-edit procedures to the canonical CL pair."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cl.manuals import _source_lines, cl_to_manual  # noqa: E402


def inputs(properties, required):
    return {'type': 'object', 'properties': dict(sorted(properties.items())), 'required': required,
            'additionalProperties': False}


S = {'type': 'string'}
NOTE = {'type': 'string', 'minLength': 1, 'maxLength': 4000}
PROCEDURES = {
    'promote-reviewed-patch': {
        'goal': 'Apply one explicitly reviewed quarantined patch to this workspace with current base hash and evidence',
        'inputs': inputs({'id': S, 'patchId': S, 'expectedSha256': S, 'reviewer': S,
                          'evidence': {'type': 'array', 'items': S, 'minItems': 1}},
                         ['id', 'patchId', 'expectedSha256', 'reviewer', 'evidence']),
        'steps': [{'action': 'versions', 'args': {'id': {'$input': 'id'}}, 'save': 'before'},
                  {'judge': 'patch-review'},
                  {'action': 'patch.apply', 'args': {'id': {'$input': 'id'}, 'patchId': {'$input': 'patchId'},
                                                     'expectedSha256': {'$input': 'expectedSha256'},
                                                     'approved': True, 'reviewer': {'$input': 'reviewer'},
                                                     'evidence': {'$input': 'evidence'}}, 'save': 'promoted',
                   'when': {'judge': 'patch-review', 'option': 'approve'}}]},
    'quarantine-observation': {
        'goal': 'Save one observed manual frontier as a quarantined patch without changing the active version',
        'inputs': inputs({'id': S, 'note': NOTE, 'observed': {'type': 'object'}}, ['id', 'note', 'observed']),
        'steps': [{'action': 'versions', 'args': {'id': {'$input': 'id'}}, 'save': 'before'},
                  {'action': 'frontier', 'args': {'id': {'$input': 'id'}, 'note': {'$input': 'note'},
                                                 'observed': {'$input': 'observed'}}, 'save': 'patch'}]},
    'quarantine-demotion': {
        'goal': 'Quarantine removal of one named obsolete procedure while keeping the current manual active',
        'inputs': inputs({'id': S, 'chapter': S, 'procedure': S, 'reason': S}, ['id', 'chapter', 'procedure', 'reason']),
        'steps': [{'action': 'versions', 'args': {'id': {'$input': 'id'}}, 'save': 'before'},
                  {'action': 'demote', 'args': {'id': {'$input': 'id'}, 'chapter': {'$input': 'chapter'},
                                               'procedure': {'$input': 'procedure'}, 'reason': {'$input': 'reason'}}, 'save': 'patch'}]},
}


def main():
    canonical = ROOT / 'manuals/manuals-next.manual.json'
    authored = ROOT / 'manuals/cl/manuals-next.cl'
    data = json.loads(canonical.read_text(encoding='utf-8'))
    text = authored.read_text(encoding='utf-8')
    if cl_to_manual(text) != data:
        raise ValueError('Existing CL and JSON manual differ')
    chapter = data['chapters']['versions']
    metadata = json.loads(text.splitlines()[2][len('-- @manual '):])['tool_metadata']
    additions = []
    for key, row in PROCEDURES.items():
        if key in chapter['procedures']:
            if chapter['procedures'][key] != row:
                old_visible = '\n'.join(_source_lines('procedures', key, chapter['procedures'][key],
                                                      chapter, data['schemas'], data['id'], metadata,
                                                      version='1.1'))
                new_visible = '\n'.join(_source_lines('procedures', key, row, chapter, data['schemas'],
                                                      data['id'], metadata, version='1.1'))
                old = '-- @record ' + json.dumps({'chapter': 'versions', 'section': 'procedures',
                                                  'key': key, 'data': chapter['procedures'][key]},
                                                 sort_keys=True, separators=(',', ':'), ensure_ascii=False)
                new = '-- @record ' + json.dumps({'chapter': 'versions', 'section': 'procedures',
                                                  'key': key, 'data': row}, sort_keys=True,
                                                 separators=(',', ':'), ensure_ascii=False)
                if text.count(old) != 1 or text.count(old_visible) != 1:
                    raise ValueError('Existing procedure record cannot be replaced exactly: ' + key)
                text = text.replace(old, new)
                text = text.replace(old_visible, new_visible)
                chapter['procedures'][key] = row
            continue
        chapter['procedures'][key] = row
        additions.append('-- @record ' + json.dumps({'chapter': 'versions', 'section': 'procedures',
                                                      'key': key, 'data': row}, sort_keys=True,
                                                     separators=(',', ':'), ensure_ascii=False))
        additions.extend(_source_lines('procedures', key, row, chapter, data['schemas'], data['id'], metadata, version='1.1'))
    if additions:
        marker = '\nL manuals-next.versions v1 -- '
        start = text.index(marker) + 1
        end = text.find('\nL manuals-next.', start + len(marker))
        if end < 0:
            end = len(text)
        text = text[:end].rstrip('\n') + '\n' + '\n'.join(additions) + '\n' + text[end:].lstrip('\n')
    if cl_to_manual(text) != data:
        raise ValueError('Added CL records do not round-trip')
    authored.write_bytes(text.replace('\n', '\r\n' if b'\r\n' in authored.read_bytes() else '\n').encode('utf-8'))
    canonical.write_bytes((json.dumps(data, indent=2, ensure_ascii=False) + '\n').replace(
        '\n', '\r\n' if b'\r\n' in canonical.read_bytes() else '\n').encode('utf-8'))
    print(json.dumps({'ok': True, 'procedures': list(PROCEDURES)}))


if __name__ == '__main__':
    main()
