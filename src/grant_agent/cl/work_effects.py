"""Exact persisted-state checks for one adaptive-work identity per CL action."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re


SUPPORTED = {'work.state', 'work.focus', 'work.problem', 'work.constraint', 'work.update_problem'}
_EVENT = {'work.focus': 'focus_changed', 'work.problem': 'problem_recorded',
          'work.constraint': 'constraint_recorded', 'work.update_problem': 'problem_updated'}
_MUTABLE = {'revision', 'updatedAt', 'integritySha256'}


def _paths(protocol, args):
    identity = args['workId']
    if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}', identity):
        raise ValueError('Adaptive work effect requires a safe work identity')
    base = Path(protocol.gateway.root) / '.agent_control' / 'adaptive_work'
    return identity, base / (identity + '.json'), base / (identity + '.events.jsonl')


def snapshot_for(protocol, name, args):
    identity, path, events_path = _paths(protocol, args)
    raw = path.read_bytes() if path.exists() else None
    events = events_path.read_text(encoding='utf-8') if events_path.exists() else ''
    state = json.loads(raw) if raw is not None else None
    if state is not None:
        from ..adaptive_work import SCHEMA, _hash
        if (state.get('schema') != SCHEMA or state.get('workId') != identity or
                state.get('integritySha256') != _hash({k: v for k, v in state.items()
                                                        if k != 'integritySha256'})):
            raise ValueError('Adaptive work effect source failed integrity check')
    return {'state': state, 'events': events, 'path': str(path),
            'fileSha256': hashlib.sha256(raw).hexdigest() if raw is not None else None}


def _base(identity):
    return {'schema': 'neyvia.adaptive_work.v1', 'workId': identity, 'revision': 0,
            'focus': {'text': '', 'source': '', 'changedAt': None},
            'problems': [], 'dependencies': [], 'evidence': [],
            'constraints': [], 'focusHistory': []}


def _verify(protocol, name, args, value, before):
    after = snapshot_for(protocol, name, args)
    state = after['state']
    if not state or value.get('state') != state or value.get('artifacts') != [after['path']]:
        return False
    prior = before['state'] or _base(args['workId'])
    if name == 'work.state':
        # This nominal read initializes an absent record. Initialization is an
        # explicit effect; an existing record and its event history are conserved.
        from ..adaptive_work import AdaptiveWorkStore
        expected = {**prior, 'integritySha256': state['integritySha256']}
        return (state == expected and after['events'] == before['events'] and
                value.get('nextAction') == AdaptiveWorkStore(protocol.gateway.root, args['workId']).next_action())
    if state.get('revision') != prior['revision'] + 1 or not state.get('updatedAt'):
        return False
    try:
        old_events = before['events'].splitlines()
        new_events = after['events'].splitlines()
        event = json.loads(new_events[-1])
    except (IndexError, ValueError):
        return False
    if (not after['events'].startswith(before['events']) or
            new_events[:-1] != old_events or event.get('schema') != state['schema'] or
            event.get('event') != _EVENT[name] or event.get('revision') != state['revision'] or
            event.get('createdAt') != state['updatedAt']):
        return False
    expected = deepcopy(prior)
    if name == 'work.focus':
        focus = state.get('focus', {})
        if (focus.get('text') != args['text'].strip() or focus.get('source') != 'agent_report' or
                not focus.get('changedAt') or
                state.get('focusHistory') != prior['focusHistory'] + [focus] or
                event.get('payload') != {'text': focus['text'], 'source': 'agent_report'}):
            return False
        expected.update(focus=focus, focusHistory=state['focusHistory'])
    elif name in {'work.problem', 'work.constraint'}:
        key, prefix = ('problems', 'problem-') if name == 'work.problem' else ('constraints', 'constraint-')
        rows = state.get(key, [])
        if len(rows) != len(prior[key]) + 1 or rows[:-1] != prior[key]:
            return False
        row = rows[-1]
        if (not re.fullmatch(prefix + r'[a-f0-9]{12}', str(row.get('id'))) or
                row.get('text') != args['text'].strip() or row.get('source') != 'agent_report' or
                not row.get('createdAt') or event.get('payload') != row):
            return False
        if name == 'work.problem' and (row.get('status') != 'open' or
                                       row.get('blocker') != str(args.get('blocker') or '')):
            return False
        expected[key] = rows
    else:
        old = next((row for row in prior['problems'] if row.get('id') == args['problemId']), None)
        rows = state.get('problems', [])
        if old is None or len(rows) != len(prior['problems']):
            return False
        expected_rows = [({**row, 'status': args['status'], 'need': args['need']}
                          if row.get('id') == args['problemId'] else row)
                         for row in prior['problems']]
        if rows != expected_rows or event.get('payload') != {
                'problemId': args['problemId'], 'status': args['status'], 'need': args['need']}:
            return False
        expected['problems'] = expected_rows
    for key, content in expected.items():
        if key not in _MUTABLE and state.get(key) != content:
            return False
    if set(state) != set(expected) | {'integritySha256', 'updatedAt'}:
        return False
    from ..adaptive_work import AdaptiveWorkStore
    return value.get('nextAction') == AdaptiveWorkStore(protocol.gateway.root, args['workId']).next_action()


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    return [{'name': 'effect-' + name.replace('.', '-').replace('_', '-'), 'observer': True, 'effect': True,
             'subjectKey': 'work:' + args['workId'],
             'bindSubject': lambda arguments, value, previous: 'work:' + value['state']['workId'],
             'observerTool': 'adaptive-work-durable-state', 'subject': {'workId': args['workId']},
             'expectation': 'Exact work revision and event persisted for this identity; other fields conserved',
             'check': lambda arguments, value, previous: _verify(protocol, name, arguments, value, previous)}]
