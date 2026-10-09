"""CL memory mutations require exact fresh scoped owner postconditions."""
from __future__ import annotations
from ..cue_memory import CueMemoryStore, claim_fields, fingerprint, require_context

SUPPORTED = {'neyvia.memory.remember', 'neyvia.memory.correct', 'neyvia.memory.forget'}


def readonly(name, args):
    if name in {'neyvia.memory.list', 'neyvia.memory.inspect', 'neyvia.memory.recall'}:
        return True
    return False if name in SUPPORTED else None


def owner(protocol):
    return CueMemoryStore(require_context(getattr(protocol.gateway, 'memory_context', None)))


def snapshot_for(protocol, name, args):
    if name not in SUPPORTED:
        return None
    store = owner(protocol)
    previous = store.inspect(args['id']) if 'id' in args else None
    if name.endswith('.forget') and previous:
        previous = {key: previous[key] for key in ('id', 'revision', 'status')}
    return {'generation': store.generation(), 'previous': previous}


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    def check(arguments, value, before):
        if not isinstance(value, dict) or not isinstance(value.get('memory'), dict):
            return False
        store = owner(protocol)
        reported = value['memory']
        fresh = store.inspect(reported['id'])
        if fresh != reported or store.generation() != value['generation']:
            return False
        if value.get('replayed'):
            return fresh['status'] == 'deleted' if name.endswith('.forget') else fresh['status'] != 'deleted'
        if value['generation'] != before['generation'] + 1:
            return False
        if name.endswith('.forget'):
            return fresh['id'] == arguments['id'] and fresh['revision'] == arguments['expectedRevision'] + 1 and set(fresh) == {'id', 'revision', 'status', 'updatedAt'} and fresh['status'] == 'deleted'
        fields = claim_fields(arguments)
        if any(fresh.get(key) != val for key, val in fields.items()):
            return False
        if name.endswith('.correct'):
            return fresh['id'] == arguments['id'] and fresh['revision'] == arguments['expectedRevision'] + 1 and fresh['supersedes']['hash'] == fingerprint(before['previous'])
        return fresh['revision'] == 1 and fresh['status'] == ('active' if store.context.explicit_write else 'pending')
    return [{'name': 'effect-' + name.replace('.', '-'), 'observer': True, 'effect': True,
             'subjectKey': 'memory:' + str(args.get('id') or args.get('requestId')), 'observerTool': 'fresh-scoped-memory-store',
             'bindSubject': lambda arguments, value, before: 'memory:' + value['memory']['id'],
             'subject': {'id': args.get('id'), 'requestId': args.get('requestId')},
             'expectation': 'Exact persisted revision and claims, or content-free deletion', 'check': check}]
