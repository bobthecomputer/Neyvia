"""Fresh owner checks for local task contracts and reported attention trials.

These checks prove exactly which proposal or caller-reported observation was
saved. They do not verify a model response, route, quality, or user preference.
"""
from __future__ import annotations

import copy
from pathlib import Path

from .effects import _measure_file


SUPPORTED = {'situation.define', 'attention.create', 'attention.observe'}


def readonly(name, args):
    return None


def _identity(value):
    from ..creative_tools import CreativeToolRuntime
    return CreativeToolRuntime.identity(value)


def _owned(protocol, path):
    root = Path(protocol.gateway.root).resolve()
    if not path.resolve().is_relative_to(root):
        raise ValueError('Creative record must remain inside the selected workspace')
    current = path
    while current != root:
        if current.is_symlink() or current.is_junction():
            raise ValueError('Creative record observers refuse linked subjects')
        current = current.parent
    _measure_file(path)  # Bound any existing owner file before deserializing it.
    return path


def _situation(protocol, args):
    from ..situation_interface import SituationStore, digest
    root = Path(protocol.gateway.root).resolve()
    identity = _identity(args['workId'])
    _owned(protocol, root / '.agent_control/situations' / digest(identity)[:24] / 'state.json')
    return SituationStore(root, identity)


def _ledger(protocol, args):
    from ..behavioral_experiments import BehavioralExperimentLedger
    root = Path(protocol.gateway.root).resolve()
    path = _owned(protocol, root / '.agent_control' / 'contextual_learning' /
                  (_identity(args['workId']) + '-attention.json'))
    return BehavioralExperimentLedger(path)


def snapshot_for(protocol, name, args):
    if name not in SUPPORTED:
        return None
    if name == 'situation.define':
        store = _situation(protocol, args)
        return {'state': copy.deepcopy(store._read()), 'file': _measure_file(store.path)}
    ledger = _ledger(protocol, args)
    return {'state': copy.deepcopy(ledger._read()), 'file': _measure_file(ledger.path)}


def _situation_check(protocol, args, value, previous):
    store = _situation(protocol, args)
    state = store._read()  # Verifies the owner's integrity digest.
    prior = previous['state']
    expected_revision = args.get('expectedRevision', 0)
    expected_contract = {'task': args['task'], 'constraints': args.get('constraints') or [],
                         'acceptance': args.get('acceptance') or [], 'source': 'agent_proposal'}
    return bool(prior['revision'] == expected_revision and state['workId'] == args['workId'] and
                state['revision'] == prior['revision'] + 1 and state['contract'] == expected_contract and
                all(state.get(key) == prior.get(key) for key in ('latestFrame', 'journeys', 'journeyRuns')) and
                value == state and _measure_file(store.path).get('kind') == 'file')


def _attention_create_check(protocol, args, value, previous):
    from ..behavioral_experiments import _hash
    ledger = _ledger(protocol, args)
    prior = previous['state']['experiments']
    current = ledger._read()['experiments']  # Validates definition/observation hashes.
    payload = args['arguments']
    identity = payload['experiment_id']
    if identity in prior or set(current) != set(prior) | {identity}:
        return False
    if any(current[key] != row for key, row in prior.items()):
        return False
    definition = current[identity]['definition']
    expected = {'experimentId': identity, 'baselineInput': payload['baseline_input'],
                'variantInput': payload['variant_input'], 'acceptance': payload['acceptance'],
                'requestedRoute': payload['requested_route'], 'budget': payload['budget'],
                'seed': payload.get('seed')}
    return bool(all(definition.get(key) == item for key, item in expected.items()) and
                isinstance(definition.get('createdAt'), str) and current[identity]['definitionHash'] == _hash(definition) and
                current[identity]['observations'] == [] and value.get('result') == definition and
                value.get('workId') == args['workId'] and _measure_file(ledger.path).get('kind') == 'file')


def _attention_observe_check(protocol, args, value, previous):
    ledger = _ledger(protocol, args)
    prior = previous['state']['experiments']
    current = ledger._read()['experiments']
    payload = args['arguments']
    identity = payload['experiment_id']
    if identity not in prior or set(current) != set(prior):
        return False
    if any(current[key] != row for key, row in prior.items() if key != identity):
        return False
    before = prior[identity]
    after = current[identity]
    if after['definition'] != before['definition'] or after['definitionHash'] != before['definitionHash']:
        return False
    old_rows, new_rows = before['observations'], after['observations']
    if len(new_rows) != len(old_rows) + 1 or new_rows[:-1] != old_rows:
        return False
    row = new_rows[-1]
    reported = value.get('result')
    expected = {'variant': payload['variant'], 'response': payload['response'],
                'actualRoute': payload['actual_route'], 'latencyMs': payload.get('latency_ms'),
                'cost': payload.get('cost')}
    return bool(isinstance(reported, dict) and all(row.get(key) == item for key, item in expected.items()) and
                all(reported.get(key) == item for key, item in expected.items()) and
                {key: item for key, item in row.items() if key != 'evidenceHash'} == reported and
                row.get('status') == 'observed' and row.get('evidenceVerified') is False and
                value.get('workId') == args['workId'] and _measure_file(ledger.path).get('kind') == 'file')


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    observer = 'situation.recall' if name == 'situation.define' else 'attention.select'
    if protocol.scope is not None and observer not in protocol.scope:
        return []
    work_id = _identity(args['workId'])
    subject = {'workId': work_id}
    if name.startswith('attention.'):
        subject['experimentId'] = args['arguments']['experiment_id']

    def verify(arguments, value, previous):
        if not isinstance(value, dict) or not isinstance(previous, dict):
            return False
        try:
            if name == 'situation.define':
                return _situation_check(protocol, arguments, value, previous)
            if name == 'attention.create':
                return _attention_create_check(protocol, arguments, value, previous)
            return _attention_observe_check(protocol, arguments, value, previous)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return False

    def bind_subject(arguments, value, previous):
        if name == 'situation.define':
            return 'situation:' + work_id
        return 'attention:' + work_id + ':' + arguments['arguments']['experiment_id']

    return [{'name': 'effect-' + name.replace('.', '-'), 'observer': True, 'effect': True,
             'subjectKey': name + ':' + work_id, 'bindSubject': bind_subject,
             'observerTool': observer, 'subject': subject,
             'expectation': 'Fresh scoped owner state retains the exact proposal or caller-reported observation and conserves other records',
             'check': verify}]
