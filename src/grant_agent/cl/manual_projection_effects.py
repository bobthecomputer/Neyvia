"""Exact immutable projections and fresh source-bound observation artifacts."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from .creative_effects import _owned
from .effects import _call, _measure_file

SUPPORTED = {'neyvia.manual.observe', 'neyvia.manual.project'}


def readonly(name, args):
    if name in SUPPORTED:
        return name.endswith('.project')
    return None


def _root(protocol):
    return Path(protocol.gateway.root) / '.neyvia'


def _path(protocol, folder, identity, width):
    if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{' + str(width) + '}', identity):
        raise ValueError('Invalid immutable state identity')
    return _owned(protocol, _root(protocol) / folder / (identity + '.json'))


def _read(path):
    _measure_file(path)
    raw = path.read_bytes()
    row = json.loads(raw)
    if raw != (json.dumps(row, ensure_ascii=False, indent=2) + '\n').encode('utf-8'):
        raise ValueError('Immutable state artifact differs from canonical owner bytes')
    return row


def _digest(value):
    from ..manual_state import encoded
    return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def _handle(protocol, identity):
    row = _read(_path(protocol, 'manual-state', identity, 32))
    if row.get('valueSha256') != _digest(row['value']):
        raise ValueError('Immutable state value digest does not match its bytes')
    return row


def _source(protocol, args):
    from ..neyvia_manuals import get_manual, chapter_entry, resolve, validate
    _, digest, data = get_manual(args['id'], _root(protocol))
    if data['id'] == 'remote':
        raise ValueError('Volatile remote observations have no retained local handle contract')
    validate(data, protocol.gateway.native)
    chapter, _, observer = chapter_entry(data, args.get('chapter'), 'state', args['state'])
    inputs = args.get('inputs') or {}
    Draft202012Validator(observer['inputs']).validate(inputs)
    arguments = resolve(observer['args'], inputs, {}, protocol.gateway.root)
    if protocol._mutating(observer['tool'], arguments):
        raise ValueError('Observation source must be an independently readable pure observer')
    if 'scopeTools' in args:
        if not isinstance(args['scopeTools'], list) or observer['tool'] not in args['scopeTools']:
            raise PermissionError('Observation source exceeds the original nested-tool restriction')
    if protocol.scope is not None and observer['tool'] not in protocol.scope:
        raise PermissionError('Observation source exceeds this CL adapter scope')
    metadata = {'id': data['id'], 'chapter': chapter, 'state': args['state'], 'sha256': digest}
    stream = {**metadata, 'inputs': inputs, 'scopeTools': args.get('scopeTools'), 'stream': args.get('stream', 'default')}
    return metadata, observer, arguments, _digest(stream)


def snapshot_for(protocol, name, args):
    if name == 'neyvia.manual.project':
        return None
    metadata, _, _, stream_key = _source(protocol, args)
    latest = _path(protocol, 'manual-state-streams', stream_key, 64)
    previous = args.get('previousHandle')
    if not previous and latest.exists() and not args.get('reset'):
        previous = _read(latest)['handle']
    baseline = _handle(protocol, previous) if previous else None
    if baseline and baseline.get('streamKey') != stream_key:
        raise ValueError('Previous observation belongs to another source/input/scope/stream')
    return {'metadata': metadata, 'streamKey': stream_key, 'previousHandle': previous,
            'baseline': deepcopy(baseline), 'handles': [p.stem for p in (_root(protocol) / 'manual-state').glob('*.json')]}


def _projection(protocol, args):
    from ..manual_state import encoded
    row = _handle(protocol, args['handle'])
    value = row['value']
    path = args.get('path', '')
    if path:
        if not path.startswith('/'):
            raise ValueError('Projection requires a JSON Pointer')
        for key in path[1:].split('/'):
            key = key.replace('~1', '/').replace('~0', '~')
            value = value[int(key)] if isinstance(value, list) else value[key]
    offset, limit = args.get('offset', 0), args.get('limit', 20)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid bounded projection page')
    total = len(value) if isinstance(value, (dict, list, str)) else 1
    if isinstance(value, dict):
        selected = {key: value[key] for key in list(value)[offset:offset + limit]}
    elif isinstance(value, (list, str)):
        selected = value[offset:offset + limit]
    else:
        selected = value if offset == 0 else None
    result = {'ok': True, 'handle': args['handle'], 'path': path, 'total': total}
    if len(encoded(selected)) > 8000:
        return {**result, 'tooLarge': True, 'hint': 'Choose a deeper path or smaller limit; no value was pasted.'}
    end = min(total, offset + limit)
    return {**result, 'value': selected, 'offset': offset, 'nextOffset': end if end < total else None,
            'valueSha256': row['valueSha256']}


def _observation(protocol, args, value, previous):
    from ..manual_state import encoded, changes
    metadata, observer, arguments, stream_key = _source(protocol, args)
    if metadata != previous['metadata'] or stream_key != previous['streamKey']:
        return False
    handle = value.get('handle')
    if handle in previous['handles']:
        return False
    row = _handle(protocol, handle)
    fresh = _call(protocol, observer['tool'], arguments)
    Draft202012Validator(observer['shape']).validate(fresh)
    expected_row = {**metadata, 'streamKey': stream_key, 'value': fresh, 'valueSha256': _digest(fresh)}
    if row != expected_row or _read(_path(protocol, 'manual-state-streams', stream_key, 64)) != {'handle': handle}:
        return False
    if previous['previousHandle'] and _handle(protocol, previous['previousHandle']) != previous['baseline']:
        return False
    expected = {'ok': True, **metadata, 'handle': handle, 'valueSha256': row['valueSha256'], 'characters': len(encoded(fresh))}
    if previous['baseline']:
        delta = changes(previous['baseline']['value'], fresh)
        expected.update(mode='diff', previousHandle=previous['previousHandle'])
        if len(encoded(delta)) <= 8000:
            expected['diff'] = delta
        else:
            diff_handle = value.get('diffHandle')
            if diff_handle in previous['handles'] or diff_handle == handle:
                return False
            if _handle(protocol, diff_handle) != {**metadata, 'streamKey': stream_key, 'value': delta, 'valueSha256': _digest(delta)}:
                return False
            expected.update(diffHandle=diff_handle, changes=len(delta))
    elif len(encoded(fresh)) <= 4000:
        expected.update(mode='snapshot', observed=fresh)
    else:
        expected.update(mode='handle', hint='Use manual.project(handle,path,offset,limit) for selected state.')
    return value == expected


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    def check(arguments, value, previous):
        try:
            return value == _projection(protocol, arguments) if name.endswith('.project') else _observation(protocol, arguments, value, previous)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return False
    return [{'name': 'effect-manual-' + name.rsplit('.', 1)[-1], 'observer': True, 'effect': True,
             'subjectKey': 'manual-state:' + name,
             'bindSubject': lambda arguments, value, previous: ('manual-state-handle:' + arguments['handle']
                if name.endswith('.project') else 'manual-state-stream:' + previous['streamKey']),
             'observerTool': 'immutable-manual-state-bytes' if name.endswith('.project') else 'current-authored-source-observer',
             'subject': deepcopy(args),
             'expectation': 'Fresh exact immutable state bytes match the bounded projection or current pure source plus stream/delta',
             'check': check}]
