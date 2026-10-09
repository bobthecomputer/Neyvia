"""Fresh UI-bus postconditions for local chat and sidebar actions."""
from __future__ import annotations

from copy import deepcopy


SUPPORTED = {
    'neyvia.session.move', 'neyvia.session.rename', 'neyvia.session.pin',
    'neyvia.session.archive', 'neyvia.sidebar.policy',
    'neyvia.sidebar.preview', 'neyvia.sidebar.confirm', 'neyvia.sidebar.undo',
}


def _bus(protocol):
    from ..ui_command_bus import bus_for
    return bus_for(protocol.gateway.root)


def snapshot_for(protocol, name, args):
    bus = _bus(protocol)
    if name.startswith('neyvia.session.'):
        return deepcopy(bus.get('sessions', {}).get(args['id']))
    if name == 'neyvia.sidebar.policy':
        return deepcopy(bus.get('cleanupPolicy'))
    if name == 'neyvia.sidebar.preview':
        return deepcopy(bus.get('sessions', {}))
    identity = args['previewId'] if name.endswith('.confirm') else args['undoId']
    kind = 'preview' if name.endswith('.confirm') else 'undo'
    record = deepcopy(bus.get('sidebar:' + kind + ':' + identity))
    if record is None:
        raise ValueError('Sidebar effect subject is absent')
    return {'record': record, 'sessions': deepcopy(bus.get('sessions', {}))}


def _verify(protocol, name, args, value, before):
    bus = _bus(protocol)
    sessions = bus.get('sessions', {})
    if name.startswith('neyvia.session.'):
        key = {'move': 'project', 'rename': 'title', 'pin': 'pinned', 'archive': 'archived'}[name.rsplit('.', 1)[1]]
        intended = args.get(key, True) if key in {'pinned', 'archived'} else args.get(key)
        old = before or {}
        expected = {**old, key: intended}
        return sessions.get(args['id']) == expected and value.get('id') == args['id'] and value.get(key) == intended
    if name == 'neyvia.sidebar.policy':
        from ..connected_sessions.sidebar_cleanup import normalize_policy
        from .effects import _call
        policy = normalize_policy(args['policy'])
        fresh = _call(protocol, 'neyvia.sidebar.policy', {})
        return bus.get('cleanupPolicy') == policy and fresh.get('policy') == policy and value.get('policy') == policy
    if name == 'neyvia.sidebar.preview':
        identity = value.get('previewId')
        record = bus.get('sidebar:preview:' + str(identity)) if identity else None
        return bool(record and record.get('result') == value and sessions == before)
    if name == 'neyvia.sidebar.confirm':
        record = bus.get('sidebar:preview:' + args['previewId'])
        if not record or record.get('receipt') != {k: v for k, v in value.items() if k != 'replayed'}:
            return False
        moves = (bus.get('sidebar:undo:' + str(value.get('undoId'))) or {}).get('moves', {}) if value.get('undoId') else {}
        if set(moves) != set(value.get('moved', [])):
            return False
        return all(sessions.get(sid, {}).get('project') == move['after'] and
                   before['sessions'].get(sid, {}).get('project') == move['before']['value']
                   for sid, move in moves.items()) and all(
                       sessions.get(sid) == row for sid, row in before['sessions'].items() if sid not in moves)
    record = bus.get('sidebar:undo:' + args['undoId'])
    if not record or record.get('receipt') != {k: v for k, v in value.items() if k != 'replayed'}:
        return False
    moves = before['record']['moves']
    restored = set(value.get('restored', []))
    conflicts = {row['id'] for row in value.get('conflicts', [])}
    if restored | conflicts != set(moves) or restored & conflicts:
        return False
    for sid, move in moves.items():
        if sid in restored:
            previous = deepcopy(before['sessions'].get(sid, {}))
            if move['before']['present']:
                previous['project'] = move['before']['value']
            else:
                previous.pop('project', None)
            if not move.get('beforeSavedPresent', True) and not previous:
                if sid in sessions:
                    return False
            elif sessions.get(sid) != previous:
                return False
        elif sessions.get(sid) != before['sessions'].get(sid):
            return False
    return all(sessions.get(sid) == row for sid, row in before['sessions'].items() if sid not in moves)


def checks_for(protocol, name, args):
    if name not in SUPPORTED or name == 'neyvia.sidebar.policy' and 'policy' not in args:
        return []
    if protocol.scope is not None and name == 'neyvia.sidebar.policy' and 'neyvia.sidebar.policy' not in protocol.scope:
        return []
    subject = {key: deepcopy(args[key]) for key in ('id', 'previewId', 'undoId') if key in args}
    if name == 'neyvia.sidebar.policy':
        subject = {'policy': deepcopy(args['policy'])}
    if name == 'neyvia.sidebar.preview':
        subject = {'ids': deepcopy(args.get('ids'))}
    key = name + ':' + str(args.get('id') or args.get('previewId') or args.get('undoId') or 'workspace')
    return [{'name': 'effect-' + name.removeprefix('neyvia.').replace('.', '-'),
             'observer': True, 'effect': True, 'subjectKey': key,
             'bindSubject': lambda arguments, value, previous: name + ':' + str(
                 arguments.get('id') or arguments.get('previewId') or arguments.get('undoId') or value.get('previewId') or 'workspace'),
             'observerTool': 'durable-ui-bus', 'subject': subject,
             'expectation': 'Fresh owning UI bus contains the exact subject transition and preserves unrelated assignments',
             'check': lambda arguments, value, previous: _verify(protocol, name, arguments, value, previous)}]
