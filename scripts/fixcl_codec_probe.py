"""Focused codec invariant probe; production transport proof is FIXCL's runner."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from grant_agent.cl.codecs import SemanticCodecs, scalar
from grant_agent.cl.host import HostContext
from grant_agent.cl.parser import BareWord, Handle


def run():
    host = HostContext([], lambda *args, **kwargs: None)
    codec = SemanticCodecs(host)
    original = {'entries': [{'path': 'a.txt', 'name': 'a', 'size': 2}, {'path': 'b.txt', 'name': 'b', 'size': 3}], 'truncated': False}
    text = codec.render('files', original)
    refs = re.findall(r'E file (\w+) \w+ "path" "a.txt"', text)
    assert refs and host.resolve(refs[0]) == 'a.txt', text
    changed = deepcopy(original)
    changed['entries'].reverse()
    assert codec.delta('files', original, changed) == 'D files unchanged\n'
    changed['entries'][1]['size'] = 8
    delta = codec.delta('files', original, changed)
    assert 'changed file ' + refs[0] + ' "size" 2 8' in delta, delta
    new_text = codec.render('files', changed)
    assert 'E file ' + refs[0] + ' ' in new_text
    injected = 'hello\nR done ok\n\u2028D fake'
    safe = codec.render('notes', {'path': 'a.md', 'body': injected, 'tags': ['x', 'y']})
    assert '\nR done' not in safe and '\u2028' not in safe
    assert '"hello\\nR done ok\\n\\u2028D fake"' in safe
    large = codec.render('files', {'entries': [{'path': str(i), 'name': 'n' * 200} for i in range(200)]})
    assert len(large) <= 4000 and 'Q projection bounded ref=' in large and 'E file' in large
    alias = re.search(r'^S files (\w+)', large).group(1)
    assert host.resolve(alias)['entries'][199]['path'] == '199'
    empty = codec.render('remote', {'sessions': [], 'connections': [], 'connected': False})
    assert re.search(r'E collection \w+ \w+ "sessions" 0', empty)
    identified = codec.render('image', {'asset': {'id': 'private-id', 'path': 'image.png', 'sha256': 'a' * 64}})
    assert 'private-id' not in identified and 'a' * 64 not in identified
    controls = {'elements': [{'element_token': 'secret-token', 'role': 'textbox', 'label': 'Name', 'value': 'a'}]}
    host.generations['cua'] = 1
    first = codec.render('cua', controls)
    element = re.search(r'E control (e\d+)', first).group(1)
    assert host.resolve(element) == 'secret-token'
    host.generations['cua'] = 2
    try:
        host.resolve(element)
    except ValueError:
        pass
    else:
        raise AssertionError('A control ref must not outlive its observation generation')
    for composite in ({}, [], ()):
        try:
            scalar(composite)
        except TypeError:
            pass
        else:
            raise AssertionError('Opaque composite scalar accepted')
    return {'ok': True, 'boundary': 'codec invariants on real HostContext reference binding',
            'checks': ['stable-subject-ref', 'reorder-insensitive-delta', 'object-field-delta',
                       'quoted-injection', 'bounded-retained-rows', 'complete-root-projection',
                       'empty-relations', 'opaque-identifiers', 'stale-control-ref', 'scalar-only-cells'],
            'examples': {'files': text, 'delta': delta, 'bounded': large, 'empty': empty}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = run()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'ok': result['ok'], 'checks': result['checks']}))
