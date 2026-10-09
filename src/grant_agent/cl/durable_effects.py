"""Fresh owner observations for retained projects, missions, and Night Shift.

The native result locates a subject. Completion reads the owner again and
compares the requested state, including prerequisites and evidence bytes.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path

from .effects import _call, _measure_file


SUPPORTED = {
    'neyvia.folder.create', 'neyvia.project.create',
    'neyvia.mission.create', 'neyvia.nightshift.create',
    'neyvia.nightshift.tick', 'neyvia.nightshift.resources',
    'neyvia.nightshift.import', 'neyvia.nightshift.block', 'neyvia.nightshift.begin',
}


def readonly(name, args):
    if name == 'neyvia.nightshift.resources':
        return not bool(args)
    return None


def _task(protocol, identity):
    return next((row for row in _call(protocol, 'neyvia.nightshift.tasks', {})['tasks']
                 if row['id'] == identity), None)


def _mission(protocol, identity):
    return next((row for row in _call(protocol, 'neyvia.mission.list', {})['missions']
                 if row['id'] == identity), None)


def _project_target(protocol, name, args):
    from ..neyvia_workspace_tools import workspace_for
    workspace = workspace_for(protocol.gateway.root)
    if name == 'neyvia.folder.create':
        return workspace.safe_path(workspace.safe_path(args['path']) / args['name'])
    return workspace.safe_path(args.get('path') or protocol.gateway.root / 'projects' / args['name'])


def _evidence_file(protocol, task, evidence):
    from ..neyvia_workspace_tools import workspace_for
    candidate = Path(evidence['path'])
    if not candidate.is_absolute():
        candidate = Path(task['folder']) / candidate
    path = workspace_for(protocol.gateway.root).safe_path(candidate)
    path.relative_to(Path(task['folder']).resolve())
    return _measure_file(path)


def _import_rows(protocol, args):
    from ..nightshift_import import parse_board
    if 'text' in args:
        content = args['text']
        source = None
    else:
        from ..neyvia_workspace_tools import workspace_for
        path = workspace_for(protocol.gateway.root).safe_path(args['path'])
        if path.suffix.lower() != '.md' or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Effect observer requires a bounded Markdown board')
        source = _measure_file(path)
        content = path.read_text(encoding='utf-8-sig')
    if not isinstance(content, str) or len(content.encode('utf-8')) > 2 * 1024 * 1024:
        raise ValueError('Effect observer requires bounded Markdown text')
    rows = parse_board(content)
    if not rows or len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Effect observer requires uniquely identified board rows')
    return rows, source


def snapshot_for(protocol, name, args):
    if name in {'neyvia.folder.create', 'neyvia.project.create'}:
        target = _project_target(protocol, name, args)
        # Existing contents must not be silently credited as newly created.
        return {'target': str(target), 'before': _measure_file(target),
                'registration': next((row for row in _call(protocol, 'neyvia.folder.list', {})['folders']
                                      if os.path.normcase(row['path']) == os.path.normcase(str(target))), None)}
    if name == 'neyvia.mission.create':
        return {'prior': _mission(protocol, args['id']) if args.get('id') else None}
    if name == 'neyvia.nightshift.create':
        return {'prior': _task(protocol, args['id']) if args.get('id') else None}
    if name == 'neyvia.nightshift.tick':
        task = _task(protocol, args['id'])
        if task is None:
            raise ValueError('Effect subject is not a saved Night Shift task')
        return {'task': task, 'evidence': _evidence_file(protocol, task, args['evidence'])}
    if name == 'neyvia.nightshift.block':
        return {'task': _task(protocol, args['id'])}
    if name == 'neyvia.nightshift.import':
        rows, source = _import_rows(protocol, args)
        return {'rows': rows, 'source': source,
                'prior': {row['id']: _task(protocol, row['id']) for row in rows}}
    if name == 'neyvia.nightshift.begin':
        return _call(protocol, 'neyvia.nightshift.summary', {})['night']
    if name == 'neyvia.nightshift.resources':
        return _call(protocol, name, {})
    return None


def _project_check(protocol, name, args, value, before):
    target = before['target']
    if os.path.normcase(value.get('path', '')) != os.path.normcase(target) or value.get('name') != args['name']:
        return False
    observed = _measure_file(Path(target))
    if observed.get('kind') != 'folder' or not observed.get('exists'):
        return False
    if before['before'].get('exists') and before['before'].get('kind') != 'folder':
        return False
    if before['before'].get('exists') and not (args.get('git') or args.get('template') == 'git'):
        if any(before['before'].get(key) != observed.get(key) for key in ('sha256', 'entries', 'bytes')):
            return False
    if not before['before'].get('exists') and (observed.get('entries') != (1 if args.get('git') or args.get('template') == 'git' else 0)):
        return False
    if args.get('git') or args.get('template') == 'git':
        if not (Path(target) / '.git').is_dir():
            return False
    registration = next((row for row in _call(protocol, 'neyvia.folder.list', {})['folders']
                         if os.path.normcase(row['path']) == os.path.normcase(target)), None)
    return bool(registration and registration.get('name') == args['name'] and
                os.path.normcase(registration.get('path', '')) == os.path.normcase(target))


def _mission_check(protocol, args, value, before):
    identity = args.get('id') or value.get('mission', {}).get('id')
    if not identity:
        return False
    fresh = _mission(protocol, identity)
    if not fresh:
        return False
    # Exact-ID retries are allowed only when the owner returned a replay.
    if before['prior'] and not value.get('replayed'):
        return False
    if not before['prior'] and value.get('replayed'):
        return False
    from ..neyvia_workspace_tools import workspace_for
    folder = str(workspace_for(protocol.gateway.root).safe_path(args['folder']))
    if any(fresh.get(key) != expected for key, expected in {
        'id': identity, 'goal': args['goal'], 'folder': folder,
        'acceptanceChecks': args['acceptanceChecks'], 'budget': args.get('budget') or {},
        'status': 'draft', 'executionStatus': 'waiting', 'acceptance': 'pending',
    }.items()):
        return False
    requested = {identity + ':' + row['id']: row for row in args['tasks']}
    saved = {row['id']: row for row in fresh['tasks']}
    if set(saved) != set(requested) or fresh.get('taskIds') != list(requested):
        return False
    for key, row in saved.items():
        source = requested[key]
        if row.get('prompt') != source['prompt'].strip() or row.get('needs') != [identity + ':' + item for item in source.get('needs', [])]:
            return False
        if row.get('status') != 'waiting' or row.get('armed') or row.get('runId') or row.get('evidence'):
            return False
    return True


def _create_check(protocol, args, value, before):
    identity = args.get('id') or value.get('id')
    fresh = _task(protocol, identity) if identity else None
    if before['prior'] or not fresh:
        return False
    from ..nightshift import nightshift_for
    service = nightshift_for(protocol.gateway.root, None)
    expected = service.prepare({**args, 'id': identity})
    return all(fresh.get(key) == item for key, item in expected.items()) and all(
        fresh.get(key) == item for key, item in {
            'status': 'waiting', 'armed': False, 'runId': None, 'evidence': None, 'reason': None,
        }.items())


def _tick_check(protocol, args, value, before):
    original = before['task']
    fresh = _task(protocol, args['id'])
    evidence = before['evidence']
    if not fresh or evidence.get('kind') != 'file' or not evidence.get('exists'):
        return False
    if fresh.get('status') != 'done' or fresh.get('armed') != original.get('armed'):
        return False
    if fresh.get('needs') != original.get('needs') or fresh.get('runId') != original.get('runId'):
        return False
    saved = fresh.get('evidence') or {}
    if saved != {'type': 'file', 'path': evidence['path'], 'sha256': evidence['sha256']}:
        return False
    return _evidence_file(protocol, fresh, args['evidence']) == evidence and all(
        _task(protocol, identity).get('status') == 'done' for identity in fresh['needs'])


def _block_check(protocol, args, value, before):
    prior = before['task']
    fresh = _task(protocol, args['id'])
    if not prior or not fresh or prior['status'] == 'done':
        return False
    if fresh.get('status') != 'blocked' or fresh.get('armed') or fresh.get('reason') != args['reason']:
        return False
    if any(fresh.get(key) != prior.get(key) for key in ('id', 'needs', 'prompt', 'evidence', 'runId')):
        return False
    from ..nightshift import nightshift_for
    service = nightshift_for(protocol.gateway.root, None)
    with service.connect() as db:
        lock = db.execute('SELECT 1 FROM locks WHERE task=?', (args['id'],)).fetchone()
    return lock is None


def _import_check(protocol, args, value, before):
    rows, source = _import_rows(protocol, args)
    if rows != before['rows'] or source != before['source']:
        return False
    expected_imported = [row['id'] for row in rows if before['prior'][row['id']] is None]
    expected_existing = [row['id'] for row in rows if before['prior'][row['id']] is not None]
    if value.get('imported') != expected_imported or value.get('existing') != expected_existing:
        return False
    from ..nightshift import nightshift_for
    service = nightshift_for(protocol.gateway.root, None)
    for row in rows:
        fresh = _task(protocol, row['id'])
        prior = before['prior'][row['id']]
        if prior:
            if fresh != prior:
                return False
            continue
        row = dict(row)
        row['folder'] = (args.get('folders') or {}).get(row['id']) or row['folder'] or args.get('folder') or service.root
        prepared = service.prepare({**(args.get('defaults') or {}), **row})
        if not fresh or any(fresh.get(key) != item for key, item in prepared.items()):
            return False
        if fresh.get('status') != 'waiting' or fresh.get('armed') or fresh.get('runId') or fresh.get('evidence'):
            return False
    return True


def checks_for(protocol, name, args):
    if name not in SUPPORTED or readonly(name, args):
        return []
    if name == 'neyvia.nightshift.tick' and (args.get('evidence') or {}).get('type') != 'file':
        return []
    observer = ('neyvia.folder.list' if name in {'neyvia.folder.create', 'neyvia.project.create'} else
                'neyvia.mission.list' if name == 'neyvia.mission.create' else
                'neyvia.nightshift.resources' if name == 'neyvia.nightshift.resources' else
                'neyvia.nightshift.summary' if name == 'neyvia.nightshift.begin' else
                'neyvia.nightshift.tasks')
    if protocol.scope is not None and observer not in protocol.scope:
        return []
    subject = {key: deepcopy(args[key]) for key in ('id', 'path', 'name', 'folder', 'evidence') if key in args}
    resource = (str(_project_target(protocol, name, args)) if name in {'neyvia.folder.create', 'neyvia.project.create'} else
                str(args.get('id') or 'new') if name != 'neyvia.nightshift.resources' else 'nightshift:resources')

    def verify(arguments, value, previous):
        if name in {'neyvia.folder.create', 'neyvia.project.create'}:
            return _project_check(protocol, name, arguments, value, previous)
        if name == 'neyvia.mission.create':
            return _mission_check(protocol, arguments, value, previous)
        if name == 'neyvia.nightshift.create':
            return _create_check(protocol, arguments, value, previous)
        if name == 'neyvia.nightshift.tick':
            return _tick_check(protocol, arguments, value, previous)
        if name == 'neyvia.nightshift.block':
            return _block_check(protocol, arguments, value, previous)
        if name == 'neyvia.nightshift.import':
            return _import_check(protocol, arguments, value, previous)
        if name == 'neyvia.nightshift.begin':
            current = _call(protocol, observer, {})['night']
            return bool(current['nightId'] != previous['nightId'] and
                        current['nightId'] == value.get('nightId') and
                        current['startedAt'] == value.get('startedAt'))
        from ..nightshift_resources import validate_policy
        return _call(protocol, name, {}) == validate_policy(previous, arguments)

    def bind_subject(arguments, value, previous):
        if name == 'neyvia.mission.create':
            return 'mission:' + str(arguments.get('id') or value['mission']['id'])
        if name == 'neyvia.nightshift.create':
            return 'nightshift:' + str(arguments.get('id') or value['id'])
        if name == 'neyvia.nightshift.tick':
            return 'nightshift:' + str(arguments['id'])
        if name == 'neyvia.nightshift.block':
            return 'nightshift:' + str(arguments['id'])
        if name == 'neyvia.nightshift.import':
            return 'nightshift:import:' + hashlib.sha256(str(arguments).encode()).hexdigest()
        if name == 'neyvia.nightshift.begin':
            return 'nightshift:period'
        return name + ':' + resource

    return [{'name': 'effect-' + name.removeprefix('neyvia.').replace('.', '-'),
             'observer': True, 'effect': True, 'subjectKey': name + ':' + resource,
             'bindSubject': bind_subject, 'observerTool': observer, 'subject': subject,
             'expectation': 'Fresh owner state matches the exact retained subject, task graph and evidence',
             'check': verify}]
