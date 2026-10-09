"""Subject-bound effect observers for CL actions.

An action receipt is evidence to locate its subject, never the postcondition.
Every predicate rereads the owning store or guarded file. Unmapped effects have
no predicate and are refused by the host before dispatch.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path


SUPPORTED = {
    'workspace.write', 'workspace.patch',
    'neyvia.notes.write', 'neyvia.notes.pin', 'neyvia.notes.folder',
    'neyvia.files.mkdir', 'neyvia.files.move', 'neyvia.files.trash', 'neyvia.files.undo',
    'neyvia.image.open', 'neyvia.image.crop', 'neyvia.image.resize',
    'neyvia.image.composite', 'neyvia.image.export', 'neyvia.artifact.publish',
    'neyvia.settings.propose',
    'neyvia.app_sdk.new', 'neyvia.app_sdk.build', 'neyvia.app_sdk.action',
    'neyvia.timer.start', 'neyvia.timer.lap',
    'neyvia.timer.stop', 'neyvia.schedule.create', 'neyvia.schedule.after',
    'neyvia.schedule.cancel', 'neyvia.watch.create', 'neyvia.watch.cancel',
    'neyvia.work.claim', 'neyvia.work.release', 'neyvia.plan.update',
    'neyvia.view.theme', 'neyvia.view.layout', 'neyvia.view.transparency', 'neyvia.view.ambient',
}


def supported(name, args=None):
    if name in SUPPORTED:
        return True
    from .frontier_effects import supported as frontier_supported
    return frontier_supported(name, args)


def inventory(protocol):
    """Account for every registered action without claiming unexecuted coverage."""
    rows = []
    for name in sorted(protocol.gateway.native._specs):
        if name in {'neyvia.cl', 'neyvia.cl.describe'}:
            continue
        mutation = protocol._mutating(name, {})
        admitted = supported(name)
        rows.append({'tool': name, 'family': name.removeprefix('neyvia.').split('.')[0],
                     'effectStatus': 'grounded_adapter' if admitted else 'read_only' if not mutation else 'frontier',
                     'reason': '' if admitted or not mutation else 'No subject-bound effect observer admitted; host refuses before dispatch',
                     'provedByThisInventory': False})
    return rows


def _call(protocol, name, args):
    from .protocol import unwrap
    if protocol.scope is not None and name not in protocol.scope:
        raise ValueError('Effect observer is outside this adapter scope: ' + name)
    return unwrap(protocol.gateway.call_native(name, args))


def _bus(protocol):
    from ..ui_command_bus import bus_for
    return bus_for(protocol.gateway.root)


def _same_path(left, right):
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def _file(protocol, raw):
    """Fresh bounded file/tree observation, using the Files owner's path guard."""
    from ..neyvia_files_tools import guard
    candidate = Path(raw)
    path = guard(protocol.gateway.root, str(candidate if candidate.is_absolute() else protocol.gateway.root / candidate))
    return _measure_file(path)


def _measure_file(path):
    """Internal byte observer; callers must first admit a path through its owner."""
    if not path.exists():
        return {'path': str(path), 'exists': False}
    if path.is_symlink() or path.is_junction():
        raise ValueError('Effect observation refuses symlink/junction subjects')
    digest = hashlib.sha256()
    if path.is_file():
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('Effect byte observer bound is 32 MiB')
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return {'path': str(path), 'exists': True, 'kind': 'file', 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}
    # Admit each entry before descending. Materializing rglob first would walk
    # an unbounded tree, including Windows junctions, before enforcing limits.
    entries, pending = [], [path]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as children:
            for child in children:
                item = Path(child.path)
                if len(entries) >= 2000 or item.is_symlink() or item.is_junction():
                    raise ValueError('Effect tree observer exceeds 2000 entries or contains links')
                entries.append(item)
                if child.is_dir(follow_symlinks=False):
                    pending.append(item)
    total = 0
    for item in sorted(entries):
        relative = item.relative_to(path).as_posix()
        digest.update(('d:' if item.is_dir() else 'f:').encode() + relative.encode() + b'\0')
        if item.is_file():
            total += item.stat().st_size
            if total > 32 * 1024 * 1024:
                raise ValueError('Effect tree byte observer bound is 32 MiB')
            with item.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
    return {'path': str(path), 'exists': True, 'kind': 'folder', 'sha256': digest.hexdigest(), 'entries': len(entries), 'bytes': total}


def _equal_bytes(before, after):
    return bool(before and after and before.get('exists') and after.get('exists')
                and all(before.get(k) == after.get(k) for k in ('kind', 'sha256', 'bytes', 'entries')))


def _find_page(protocol, tool, field, identity):
    """An absent item on a truncated page is never evidence of absence."""
    offset = 0
    for _ in range(20):
        observed = _call(protocol, tool, {'offset': offset, 'limit': 100})
        row = next((row for row in observed.get(field, []) if row.get('id') == identity), None)
        if row is not None:
            return row
        offset = observed.get('nextOffset')
        if offset is None:
            return None
    raise ValueError('Effect inventory exceeds 2000 entries; narrow the observer')


def snapshot_for(protocol, name, args):
    """Capture only data needed to prove conservation or the expected transition."""
    if name not in SUPPORTED:
        from .frontier_effects import snapshot_for as frontier_snapshot
        return frontier_snapshot(protocol, name, args)
    if name == 'workspace.patch':
        row = _call(protocol, 'workspace.read', {'path': args['path'], 'maxChars': 100000})
        if row.get('truncated'):
            raise ValueError('Patch effect observer requires a complete <=100000-character snapshot')
        return row
    if name == 'workspace.write':
        return _file(protocol, args['path'])
    if name == 'neyvia.notes.write':
        if not args.get('path'):
            return None
        from ..neyvia_notes_tools import _note_path
        _, path = _note_path(protocol.gateway.root, args['path'])
        if not path.exists():
            return None
        return _call(protocol, 'neyvia.notes.read', {'path': args['path']})
    if name == 'neyvia.notes.pin':
        return _call(protocol, 'neyvia.notes.read', {'path': args['path']})
    if name == 'neyvia.notes.folder':
        return _call(protocol, 'neyvia.notes.folder', {})
    if name == 'neyvia.files.move':
        source = _file(protocol, args['from'])
        target = Path(args['to'])
        if target.is_dir():
            target /= Path(args['from']).name
        return {'source': source, 'target': _file(protocol, str(target))}
    if name in {'neyvia.files.mkdir', 'neyvia.files.trash'}:
        return _file(protocol, args['path'])
    if name == 'neyvia.files.undo':
        last = deepcopy(_bus(protocol).get('files:last'))
        if not last:
            return {'action': None}
        path = last.get('to') if last['op'] == 'move' else last['path']
        capture = {'action': last, 'item': _file(protocol, path)}
        if last['op'] == 'trash':
            from ..neyvia_files_tools import bin_records
            rows = bin_records(Path(last['path']))
            capture['item'] = _measure_file(rows[0]['data']) if rows else None
        return capture
    if name.startswith('neyvia.image.'):
        state = _call(protocol, 'neyvia.image.state', {})
        asset = state.get('requested')
        if name == 'neyvia.image.open':
            return {'source': _file(protocol, args['source'])}
        return {'asset': deepcopy(asset), 'source': _file(protocol, asset['path']) if asset else None}
    if name == 'neyvia.settings.propose':
        return _call(protocol, 'neyvia.settings.get', {})
    if name == 'neyvia.app_sdk.action':
        return _call(protocol, 'neyvia.app_sdk.state', {'project': args['project']})
    if name.startswith('neyvia.app_sdk.'):
        project = args.get('project') or args.get('path')
        if not (protocol.gateway.root / project).exists():
            return None
        return _call(protocol, 'neyvia.app_sdk.describe', {'project': project})
    if name.startswith('neyvia.timer.'):
        # Start may observe an absent timer; an existing unreadable timer is a
        # real observer failure and must not masquerade as absence.
        if name == 'neyvia.timer.start' and _bus(protocol).get('timer:' + args['id']) is None:
            return None
        return _call(protocol, 'neyvia.timer.read', {'id': args['id'], 'limit': 100})
    if name.startswith('neyvia.schedule.'):
        return _call(protocol, 'neyvia.schedule.list', {})
    if name.startswith('neyvia.watch.'):
        return _call(protocol, 'neyvia.watch.list', {'limit': 100})
    if name.startswith('neyvia.work.'):
        return _call(protocol, 'neyvia.work.list', {})
    if name == 'neyvia.plan.update':
        return {'sessionId': args.get('sessionId') or 'unscoped',
                'plan': _bus(protocol).get('plan:' + (args.get('sessionId') or 'unscoped'), {})}
    if name.startswith('neyvia.view.'):
        if name == 'neyvia.view.transparency':
            return _call(protocol, 'neyvia.view.transparency.state', {})
        if name == 'neyvia.view.ambient':
            return {'ambient': _bus(protocol).get('ambient')}
        return _call(protocol, 'neyvia.settings.get', {})
    if name == 'neyvia.artifact.publish':
        return _call(protocol, 'neyvia.artifact.list', {'limit': 200})
    from .frontier_effects import snapshot_for as frontier_snapshot
    return frontier_snapshot(protocol, name, args)


def _notes(protocol, name, args, value, before):
    if name == 'neyvia.notes.folder':
        fresh = _call(protocol, 'neyvia.notes.folder', {})
        return _same_path(fresh['folder'], args['folder']) and _file(protocol, args['folder']).get('kind') == 'folder'
    observed = _call(protocol, 'neyvia.notes.read', {'path': args.get('path') or value['path']})
    if name == 'neyvia.notes.pin':
        return observed.get('pinned') is args.get('pinned', True)
    expected = args['body']
    if not args.get('path') and str(args.get('title') or '').strip():
        from ..neyvia_notes_tools import HEADING
        title = str(args['title']).strip()
        first = next((line.strip() for line in expected.splitlines() if line.strip()), '')
        if not HEADING.match(first):
            expected = f'# {title}\n\n{expected}' if expected.strip() else f'# {title}\n\n'
    if args.get('mode') == 'append':
        old = (before or {}).get('body', '')
        expected = old + ('' if not old or old.endswith('\n\n') else '\n' if old.endswith('\n') else '\n\n') + expected
    actual_file = _file(protocol, observed['file'])
    return observed.get('body') == expected and actual_file.get('sha256') == hashlib.sha256(expected.encode()).hexdigest()


def _files(protocol, name, args, value, before):
    if name == 'neyvia.files.mkdir':
        row = _call(protocol, 'neyvia.files.stat', {'path': args['path']})
        fresh = _file(protocol, args['path'])
        return not before.get('exists') and row.get('kind') == 'folder' and fresh.get('entries') == 0
    if name == 'neyvia.files.move':
        target = before['target']['path']
        fresh = _file(protocol, target)
        row = _call(protocol, 'neyvia.files.stat', {'path': target})
        # Case-only renames can still resolve at the old spelling on Windows.
        same = _same_path(before['source']['path'], target)
        vacated = same or not _file(protocol, args['from']).get('exists')
        return vacated and row.get('name') == Path(target).name and _equal_bytes(before['source'], fresh)
    if name == 'neyvia.files.trash':
        from ..neyvia_files_tools import bin_records
        rows = bin_records(Path(before['path']))
        return not _file(protocol, args['path']).get('exists') and any(
            _equal_bytes(before, _measure_file(row['data'])) for row in rows)
    if not before or not before.get('action'):
        return False
    last = before['action']
    if _bus(protocol).get('files:last') is not None:
        return False
    if last['op'] == 'mkdir':
        return not _file(protocol, last['path']).get('exists')
    target = last['from'] if last['op'] == 'move' else last['path']
    _call(protocol, 'neyvia.files.stat', {'path': target})
    return _equal_bytes(before['item'], _file(protocol, target)) and (
        last['op'] != 'move' or _same_path(target, last['to']) or not _file(protocol, last['to']).get('exists'))


def _image(protocol, name, args, value, before):
    from PIL import Image, ImageChops
    from ..neyvia_image_tools import inside
    from ..neyvia_workspace_tools import workspace_for
    service = workspace_for(protocol.gateway.root)
    state = _call(protocol, 'neyvia.image.state', {})
    asset = state.get('requested') or {}
    if not asset and name != 'neyvia.image.export':
        return False
    source = before['source']
    if not source or not _equal_bytes(source, _file(protocol, source['path'])):
        return False
    if name == 'neyvia.image.export':
        return _equal_bytes(source, _file(protocol, args['path']))
    output = _file(protocol, asset.get('path', ''))
    if output.get('sha256') != asset.get('sha256'):
        return False
    if name == 'neyvia.image.open':
        return _same_path(asset['path'], args['source']) and _equal_bytes(source, output)
    if asset.get('parentSha256') != source['sha256']:
        return False
    with Image.open(inside(service, source['path'])) as original, Image.open(inside(service, output['path'])) as actual:
        actual = actual.convert('RGBA')
        if name == 'neyvia.image.resize':
            # Preserve the source mode until after the production resampling
            # rule: Pillow resizes palette/1-bit sources differently from RGBA.
            expected = original.resize((args['width'], args['height']), Image.Resampling.LANCZOS).convert('RGBA')
        else:
            original = original.convert('RGBA')
            r = args['region']; box = (r['x'], r['y'], r['x'] + r['width'], r['y'] + r['height'])
            if name == 'neyvia.image.crop':
                expected = original.crop(box)
            else:
                # Match the production alpha-paste rule without writing another artifact.
                with Image.open(inside(service, args['edit'])) as edit:
                    edit = edit.convert('RGBA')
                    if edit.width < box[2] or edit.height < box[3]:
                        return False
                    expected = original.copy()
                    expected.paste(edit.crop(box), box)
        return actual.size == expected.size and ImageChops.difference(actual, expected).getbbox(alpha_only=False) is None


def _settings(protocol, name, args, value, before):
    fresh = _call(protocol, 'neyvia.settings.get', {})
    from ..neyvia_settings import validate
    expected = validate(before['settings'], args['patch'])
    return fresh['revision'] > args['expectedRevision'] and fresh['settings'] == expected


def _sdk(protocol, name, args, value, before):
    project = args.get('project') or args['path']
    fresh = _call(protocol, 'neyvia.app_sdk.describe', {'project': project})
    if name == 'neyvia.app_sdk.new':
        state = _call(protocol, 'neyvia.app_sdk.state', {'project': project})['state']
        return fresh['app'].get('name') == args['name'] and fresh['app'].get('kind') == args['kind'] and bool(fresh['sourceHashes']) and fresh['sourceHashes'] == value.get('sourceHashes') and bool(fresh['manual']) and state == {'count': 0, 'revision': 0}
    if name == 'neyvia.app_sdk.build':
        receipt = fresh.get('receipts', {}).get('build', {})
        artifact = _file(protocol, receipt.get('artifact', ''))
        matches = receipt.get('platform') == args['platform'] and receipt.get('sourceHashes') == fresh['sourceHashes'] and artifact.get('sha256') == receipt.get('artifactSha256')
        if args['platform'] in {'web', 'pwa'}:
            matches = matches and _equal_bytes(_file(protocol, str(protocol.gateway.root / project / 'www/index.html')), artifact)
        return matches
    state = _call(protocol, 'neyvia.app_sdk.state', {'project': project})['state']
    previous = before['state']
    expected = deepcopy(previous)
    if args['name'] == 'increment':
        expected['count'] += 1
    elif args['name'] == 'decrement':
        expected['count'] = max(0, expected['count'] - 1)
    elif args['name'] == 'reset':
        expected['count'] = 0
    else:
        return False
    expected['revision'] += 1
    return state == expected


def _durable(protocol, name, args, value, before):
    if name in {'neyvia.view.theme', 'neyvia.view.layout'}:
        observed = _call(protocol, 'neyvia.settings.get', {})['settings']
        if name.endswith('.theme'):
            from ..neyvia_settings import THEMES
            return THEMES[observed['theme']] == args['theme']
        return observed['density'] == args['level']
    if name == 'neyvia.view.transparency':
        return _call(protocol, 'neyvia.view.transparency.state', {})['transparency'] == args['level']
    if name == 'neyvia.view.ambient':
        return _bus(protocol).get('ambient') is args['on']
    if name.startswith('neyvia.timer.'):
        observed = _call(protocol, 'neyvia.timer.read', {'id': args['id'], 'limit': 100, 'offset': 0})['timer']
        if name == 'neyvia.timer.start':
            return all(observed.get(k) == v for k, v in {'label': args['label'], 'phase': args.get('phase', 'execution'), 'status': 'running', 'targetSeconds': args.get('targetSeconds')}.items()) and observed.get('elapsedSeconds', -1) >= 0
        if name == 'neyvia.timer.stop':
            return observed.get('status') == 'stopped' and bool(observed.get('stoppedAt')) and observed.get('elapsedSeconds') == value.get('timer', {}).get('elapsedSeconds')
        for offset in range(0, 1000, 100):
            timer = _call(protocol, 'neyvia.timer.read', {'id': args['id'], 'limit': 100, 'offset': offset})['timer']
            lap = next((row for row in timer.get('laps', []) if row.get('id') == args['lapId']), None)
            if lap:
                return lap.get('label') == args['label'] and lap.get('phase') == args.get('phase', observed.get('phase')) and lap.get('elapsedSeconds') == value.get('lap', {}).get('elapsedSeconds')
            if timer.get('nextOffset') is None:
                return False
        return False
    if name.startswith('neyvia.schedule.'):
        identity = args.get('requestId') or args['id']
        observed = _call(protocol, 'neyvia.schedule.list', {})
        row = next((row for row in observed['schedules'] if row.get('id') == identity), None)
        if not row:
            return False
        if name == 'neyvia.schedule.cancel':
            return row['status'] == 'cancelled'
        expected = {k: args[k] for k in ('prompt', 'scope')}
        expected['when' if name == 'neyvia.schedule.create' else 'relativeSeconds'] = args['when' if name == 'neyvia.schedule.create' else 'seconds']
        return all(row.get(k) == v for k, v in expected.items()) and row.get('status') in {'waiting', 'fired'}
    if name.startswith('neyvia.watch.'):
        identity = args.get('requestId') or args['id']
        row = _find_page(protocol, 'neyvia.watch.list', 'watches', identity)
        if name == 'neyvia.watch.cancel':
            return bool(row and row.get('status') == 'cancelled')
        from ..neyvia_run_watches import STATES
        expected = {k: args[k] for k in ('runId', 'message')}
        expected.update(states=sorted(set(args.get('states', STATES[:4]))), followup=args.get('followup'))
        return bool(row and all(row.get(k) == v for k, v in expected.items()) and row.get('status') in {'armed', 'fired'})
    if name.startswith('neyvia.work.'):
        observed = _call(protocol, 'neyvia.work.list', {})
        if name == 'neyvia.work.release':
            return not any(row['id'] == args['id'] for row in observed['claims']) and any(row['id'] == args['id'] for row in observed['recentlyReleased'])
        from ..neyvia_awareness import _norm
        files = list(dict.fromkeys(_norm(item) for item in args['files']))
        row = next((row for row in observed['claims'] if row['id'] == value['claim']['id']), {})
        return row.get('files') == files and row.get('intent') == ' '.join(args['intent'].split()) and row.get('agent') == (' '.join(args.get('agent', '').split())[:80] or 'agent')
    session = args.get('sessionId') or 'unscoped'
    fresh = _bus(protocol).get('plan:' + session, {})
    intended = [{'text': row['step'], 'status': row['status']} for row in args['plan']]
    return [{'text': row['text'], 'status': row['status']} for row in fresh.get('items', [])] == intended


def checks_for(protocol, name, args):
    if not supported(name, args):
        return []
    if name not in SUPPORTED:
        from .frontier_effects import checks_for as frontier_checks
        return frontier_checks(protocol, name, args)
    # Generated apps currently expose these exact reducer operations. Unknown
    # actions cannot gain authority from the generic action schema.
    if name == 'neyvia.app_sdk.action' and args.get('name') not in {'increment', 'decrement', 'reset'}:
        return []
    observers = {
        'notes': 'neyvia.notes.read', 'files': 'neyvia.files.stat', 'image': 'neyvia.image.state',
        'settings': 'neyvia.settings.get', 'app_sdk': 'neyvia.app_sdk.describe',
        'timer': 'neyvia.timer.read', 'schedule': 'neyvia.schedule.list',
        'watch': 'neyvia.watch.list', 'work': 'neyvia.work.list', 'plan': 'durable-plan-store',
        'artifact': 'neyvia.artifact.get', 'workspace': 'workspace.read',
        'view': 'neyvia.settings.get',
    }
    family = name.removeprefix('neyvia.').split('.')[0]
    observer = observers[family]
    if name == 'neyvia.notes.folder':
        observer = 'neyvia.notes.folder'
    elif name == 'neyvia.view.transparency':
        observer = 'neyvia.view.transparency.state'
    elif name == 'neyvia.view.ambient':
        observer = 'durable-view-store'
    if protocol.scope is not None and observer not in protocol.scope and not observer.startswith('durable-'):
        return []
    def verify(arguments, value, previous):
        if name in {'workspace.write', 'workspace.patch'}:
            if name == 'workspace.write':
                expected = arguments['content']
            else:
                from ..workspace_patches import patched_text
                expected = patched_text(previous['content'], arguments['edits'])
            fresh = _call(protocol, 'workspace.read', {'path': arguments['path'], 'maxChars': 100000})
            return fresh['sha256'] == hashlib.sha256(expected.encode()).hexdigest() and fresh['characters'] == len(expected)
        if family == 'notes':
            return _notes(protocol, name, arguments, value, previous)
        if family == 'files':
            return _files(protocol, name, arguments, value, previous)
        if family == 'image':
            return _image(protocol, name, arguments, value, previous)
        if family == 'settings':
            return _settings(protocol, name, arguments, value, previous)
        if family == 'app_sdk':
            return _sdk(protocol, name, arguments, value, previous)
        if family == 'artifact':
            fresh = _call(protocol, observer, {'id': value['artifact']['id']})
            row = fresh.get('artifact', {})
            return _same_path(row['path'], str(protocol.gateway.root / arguments['path'])) and fresh.get('availability') == 'available' and fresh.get('currentSha256') == row.get('sha256') and all(row.get(k) == arguments[k] for k in ('kind', 'title', 'sessionId', 'runId') if k in arguments)
        return _durable(protocol, name, arguments, value, previous)
    subject = {k: deepcopy(args[k]) for k in ('path', 'from', 'to', 'source', 'id', 'requestId', 'project', 'sessionId', 'folder') if k in args}
    resource = family + ':' + str(args.get('path') or args.get('id') or args.get('requestId') or args.get('project') or args.get('folder') or args.get('source') or args.get('from') or args.get('sessionId') or 'unscoped')
    if family == 'notes':
        resource += ':pin' if name.endswith('.pin') else ':body' if name.endswith('.write') else ':folder'
    if family == 'image':
        resource = 'image:requested' if name != 'neyvia.image.export' else 'image:export:' + str(args['path'])
    if name == 'neyvia.files.undo':
        last = _bus(protocol).get('files:last') or {}
        resource = 'files:' + str(last.get('from') or last.get('path') or 'missing')
    if family in {'settings', 'view'}:
        resource = name  # A later full configuration transition supersedes its earlier snapshot.
    def bind_subject(arguments, value, previous):
        if family == 'notes':
            if name.endswith('.folder'):
                return 'notes:folder'
            from ..neyvia_notes_tools import _note_path
            _, path = _note_path(protocol.gateway.root, arguments.get('path') or value['path'])
            return 'notes:' + os.path.normcase(str(path.resolve())) + (':pin' if name.endswith('.pin') else ':body')
        if family == 'work':
            return 'work:' + str(arguments['id'] if name.endswith('.release') else value['claim']['id'])
        if family == 'artifact':
            return 'artifact:' + str(value['artifact']['id'])
        return resource
    checks = [{'name': 'effect-' + name.removeprefix('neyvia.').replace('.', '-'), 'observer': True, 'effect': True,
             'subjectKey': resource,
             'bindSubject':bind_subject,
             'observerTool': observer, 'subject': subject,
             'expectation': 'Fresh owning observer matches the requested effect, with exact content and conservation where applicable',
             'check': verify}]
    if name == 'neyvia.view.theme':
        from .fixcl4_render_effects import checks_for as mounted_checks
        checks.extend(mounted_checks(protocol, name, args))
    return checks
