"""One model-language observation contract across layers, reusing T5 handles.

Native observation is exclusively T16's CUA service; values are never re-read
from pixels. Source content is untrusted data, not model/tool authority.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
from pathlib import Path

from . import manual_state
from .durability import atomic_write_json

TEXT = {'type': 'string'}
LAYERS = ['os', 'window', 'browser', 'app', 'image', 'video', 'file']
SOURCE = {'type': 'object', 'properties': {
    'sessionId': TEXT, 'window_id': {'type': 'integer'}, 'browserId': TEXT, 'tabId': TEXT,
    'path': TEXT, 'frame': {'type': 'integer', 'minimum': 0},
    'tool': TEXT, 'arguments': {'type': 'object'}}, 'additionalProperties': False}
DEFINITIONS = [
    ('perception.observe', 'Read a layer as untrusted structured text; first handle/snapshot, then T5 JSON Patch diffs. No pixels returned.',
     {'layer': {'enum': LAYERS}, 'source': SOURCE, 'stream': TEXT, 'previousHandle': TEXT, 'reset': {'type': 'boolean'}}, ['layer', 'source']),
    ('perception.project', 'Read a bounded JSON Pointer projection from an immutable perception handle.',
     {'handle': TEXT, 'path': TEXT, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}, ['handle']),
    ('perception.check', 'Check an observed handle, not unobserved live state; refresh first for postconditions.',
     {'handle': TEXT, 'path': TEXT, 'equals': {}}, ['handle', 'path', 'equals']),
    ('perception.browser.open', 'Open a private browser session for exactly this origin; no user profile or downloads.', {'url': TEXT}, ['url']),
    ('perception.browser.observe', 'Read the current DOM of the sole owned private browser session; refuse an ambiguous selection.', {'browserId': TEXT}, []),
    ('perception.browser.action', 'Act on a fresh DOM projection; stale revisions fail before any effect. Caller must authorize the action.',
     {'browserId': TEXT, 'revision': TEXT, 'element': TEXT, 'action': {'enum': ['fill', 'click']}, 'value': TEXT}, ['browserId', 'revision', 'element', 'action']),
    ('perception.browser.close', 'Close this owned browser session.', {'browserId': TEXT}, ['browserId']),
]

_LOCK = threading.RLock()


def confined(root, raw):
    path = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    path.relative_to(root.resolve())
    if not path.exists():
        raise FileNotFoundError('Source does not exist in this workspace')
    return path


def native(workspace, op, source):
    try:
        from .neyvia_cua import service_for
    except ImportError as exc:
        raise RuntimeError('T16 CUA provider is not present; merge its backend before native observation') from exc
    return service_for(workspace.bus.root).request(op, source)


def window_projection(raw):
    if 'elements' not in raw:
        raise ValueError('T16 did not return an accessibility tree')
    fields = ('element_index', 'element_token', 'parent_index', 'depth', 'role', 'label', 'value', 'enabled', 'selected', 'actions', 'frame')
    return {'elements': [{k: e[k] for k in fields if k in e} for e in raw['elements']],
            'source': 'T16.UIA', 'window_id': raw.get('window_id'),
            'textTree': raw.get('tree_markdown'), 'elementsComplete': raw.get('elements_complete'),
            'truncated': raw.get('truncated'),
            'frontier': ['Only elements returned by T16 were observed; custom-drawn controls may require explicit image observation.']}


def file_projection(path):
    if path.is_dir():
        children = sorted(path.iterdir(), key=lambda p: p.name)
        return {'kind': 'directory', 'entries': [{'name': p.name, 'directory': p.is_dir(),
                 'bytes': p.stat().st_size if p.is_file() else None} for p in children[:500]],
                'total': len(children), 'truncated': len(children) > 500}
    if path.stat().st_size > 20_000_000:
        raise ValueError('Source exceeds 20 MB observation limit')
    with path.open('rb') as stream:
        raw = stream.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError('Source grew beyond the 20 MB observation limit')
    meta = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'name': path.name}
    if path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = []
        for i, page in enumerate(reader.pages[:20]):
            text = page.extract_text() or ''
            pages.append({'page': i + 1, 'text': text[:20000], 'textTruncated': len(text) > 20000})
        return {**meta, 'kind': 'pdf', 'pages': pages, 'totalPages': len(reader.pages),
                'truncated': len(reader.pages) > 20,
                'frontier': ['PDF text extraction does not OCR scanned pages; empty text is not proof of an empty page.']}
    text = raw.decode('utf-8')  # Binary/unknown encoding fails explicitly.
    if path.suffix.lower() == '.json':
        return {**meta, 'kind': 'json', 'data': json.loads(text)}
    if path.suffix.lower() == '.csv':
        rows, total = [], 0
        for row in csv.reader(io.StringIO(text)):
            total += 1
            if len(rows) < 500:
                rows.append(row)
        return {**meta, 'kind': 'table', 'rows': rows, 'totalRows': total, 'truncated': total > 500}
    return {**meta, 'kind': 'text', 'text': text[:80000], 'truncated': len(text) > 80000}


def browsers(workspace):
    with _LOCK:
        if not hasattr(workspace, '_perception_browser') or workspace._perception_browser.closed:
            from .perception_browser import BrowserSessions
            from .neyvia_browser import service_for
            workspace._perception_browser = BrowserSessions(headless=service_for(workspace.bus.root).headless)
        return workspace._perception_browser


def image_projection(path, scratch, frame):
    """Reuse an explicitly identified, integrity-checked transcription."""
    from .perception_visual import extract, VISUAL_SCHEMA, MODEL
    if path.stat().st_size > 20_000_000:
        raise ValueError('Image exceeds 20 MB observation limit')
    with path.open('rb') as stream:
        raw = stream.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError('Image grew beyond the 20 MB observation limit')
    source_hash = hashlib.sha256(raw).hexdigest()
    key = hashlib.sha256(raw + manual_state.encoded({'frame': frame, 'model': MODEL, 'schema': VISUAL_SCHEMA}).encode()).hexdigest()
    cache = scratch / 'cache' / (key + '.json')
    if cache.exists():
        row = json.loads(cache.read_text(encoding='utf-8'))
        if hashlib.sha256(manual_state.encoded(row['value']).encode()).hexdigest() != row['sha256']:
            raise ValueError('Visual transcription cache integrity failed')
        value = row['value']
        value['provenance']['cacheHit'] = True
        value['provenance']['currentUsage'] = {'input_tokens': 0, 'output_tokens': 0}
        return value
    value = extract(path, scratch, frame=frame)
    if value['source']['sha256'] != source_hash:
        raise ValueError('Image changed during transcription; no cache or projection retained')
    value['provenance']['cacheHit'] = False
    value['provenance']['currentUsage'] = value['provenance']['usage']
    atomic_write_json(cache, {'value': value, 'sha256': hashlib.sha256(manual_state.encoded(value).encode()).hexdigest()})
    return value


def observe(workspace, args):
    layer, source = args['layer'], args['source']
    from jsonschema import Draft202012Validator
    Draft202012Validator(SOURCE).validate(source)
    required = {'os': {'sessionId'}, 'window': {'sessionId', 'window_id'}, 'browser': {'browserId'},
                'app': set(), 'image': {'path'}, 'video': {'path'}, 'file': {'path'}}
    if layer not in required:
        raise ValueError('Unknown perception layer')
    if layer == 'browser' and 'tabId' in source:
        required = {**required, 'browser': {'tabId'}}
    allowed = required[layer] | ({'frame'} if layer in {'image', 'video'} else set())
    if layer == 'app':
        allowed = {'tool', 'arguments'}
    if not required[layer] <= source.keys() or source.keys() - allowed:
        raise ValueError('Source must match the selected perception layer')
    root = workspace.bus.root
    if layer == 'os':
        value = native(workspace, 'windows', source)
    elif layer == 'window':
        value = window_projection(native(workspace, 'inspect', source))
    elif layer == 'browser':
        if 'tabId' in source:
            from .neyvia_browser import call as browser_call
            value = browser_call(workspace, 'browser.observe', {'tabId': source['tabId']})
        else:
            value = browsers(workspace).run('observe', source['browserId'])
    elif layer == 'app':
        if source.get('tool'):
            tool = source['tool']
            if not tool.startswith('neyvia.') or tool.startswith(('neyvia.perception.', 'neyvia.manual.')):
                raise ValueError('Choose a registered observational app tool; recursive perception/manual calls are refused')
            from .native_tools import NativeToolRegistry
            from .neyvia_manuals import unwrap
            registry = NativeToolRegistry(root)
            if registry.describe(tool)['mutability_class'] != 'read':
                raise PermissionError('App perception only calls read-only app tools')
            value = {'observer': tool, 'observation': unwrap(registry.call(tool, source.get('arguments', {})))}
        elif source:
            raise ValueError('App arguments require an observational tool')
        else:
            value = workspace.call('state', {})
    elif layer in {'image', 'video'}:
        path = confined(root, source['path'])
        if layer == 'video' and path.suffix.lower() not in {'.gif', '.png', '.webp', '.tiff'}:
            from .perception_video import extract_frame
            frame_path, video = extract_frame(path, root / '.neyvia/perception-video', source.get('frame', 0))
            value = image_projection(frame_path, root / '.neyvia/perception-visual', 0)
            value['video'] = video
        else:
            value = image_projection(path, root / '.neyvia/perception-visual', source.get('frame', 0))
    elif layer == 'file':
        value = file_projection(confined(root, source['path']))
    else:
        raise ValueError('Unknown perception layer')
    if not isinstance(value, dict) or value.get('ok') is False:
        raise RuntimeError('Source observation failed: ' + json.dumps(value)[:500])
    # Cost/time belong to receipts, not semantic state; unchanged images have no
    # diff solely because their extraction timing or usage changed.
    receipt = value.pop('provenance', None) if layer in {'image', 'video'} else None
    if receipt:
        value['interpretation'] = {'provider': receipt['provider'], 'model': receipt['model'],
                                   'policy': 'Model transcription; certainty is reported legibility, not an exact numeric source.'}
    if layer in {'browser', 'app', 'window', 'image'}:
        from .scene_core import transcribe
        value['scene'] = transcribe('ui', value)
    state = {'layer': layer, 'source': source, 'trust': 'untrusted-data', 'state': value}
    state_dir = root / '.neyvia/perception'
    with _LOCK:
        result = manual_state.observe(state_dir, {'observer': 'perception.' + layer, 'notation': 'neyvia.layer.v1'},
                                      state, {**args, 'inputs': source})
    result['layer'] = layer
    if receipt:
        result['extraction'] = receipt
    return result


def call(workspace, name, args):
    root = workspace.bus.root / '.neyvia/perception'
    if name == 'perception.observe':
        return observe(workspace, args)
    if name == 'perception.project':
        return manual_state.project(root, args)
    if name == 'perception.check':
        row = manual_state.read(root, args['handle'])
        value = manual_state.pointer(row['value'], args['path'])
        return {'ok': True, 'passed': value == args['equals'],
                **({'observed': value} if len(manual_state.encoded(value)) <= 4000 else {'observedOmitted': True}),
                'path': args['path'],
                'handle': args['handle'], 'valueSha256': row['valueSha256'], 'boundary': 'immutable observation'}
    if name == 'perception.browser.open':
        return browsers(workspace).run('open', args['url'])
    if name == 'perception.browser.observe':
        sessions = getattr(workspace, '_perception_browser', None)
        if sessions is None or sessions.closed:
            return {'sessions': [], 'count': 0}
        sid = args.get('browserId')
        if sid is None:
            if len(sessions.sessions) != 1:
                raise ValueError('Observe exactly one owned private browser session before acting')
            sid = next(iter(sessions.sessions))
        return sessions.run('observe', sid)
    if name == 'perception.browser.action':
        return browsers(workspace).run('action', args['browserId'], args['revision'], args['element'], args['action'], args.get('value', ''))
    if name == 'perception.browser.close':
        return browsers(workspace).run('close_one', args['browserId'])
    raise ValueError('Unknown perception tool')
