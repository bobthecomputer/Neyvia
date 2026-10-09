"""CL comments actions are checked against fresh immutable store events."""
from __future__ import annotations

from copy import deepcopy

from ..neyvia_comments import Store

SUPPORTED = {'neyvia.comments.add', 'neyvia.comments.resolve', 'neyvia.comments.send'}


def readonly(name, args):
    return True if name == 'neyvia.comments.list' else None


def snapshot_for(protocol, name, args):
    store = Store(protocol.gateway.root)
    with store.connect() as db:
        if name == 'neyvia.comments.add':
            return {'priorIds': [r['id'] for r in store.rows(db)]}
        if name == 'neyvia.comments.resolve':
            return store.get(db, args['id'])
        prior = store.delivery(db, args['requestId'])
        return {'priorDelivery': dict(prior) if prior else None}


def verify(protocol, name, args, value, before):
    store = Store(protocol.gateway.root)
    with store.connect() as db:
        if name == 'neyvia.comments.send':
            event = store.delivery(db, args['requestId'])
            if not event or event['state'] != 'sent':
                return False
            import json
            saved = json.loads(event['payload'])
            return saved['messageId'] == value['messageId'] and bool(saved['commentIds']) and all(
                db.execute("SELECT 1 FROM events WHERE id=? AND op='send' AND json_extract(payload,'$.delivery.messageId')=?",
                           (identity, saved['messageId'])).fetchone() for identity in saved['commentIds'])
        row = store.get(db, value['comment']['id'])
        if name == 'neyvia.comments.add':
            return row['id'] not in before['priorIds'] and row['target'] == args['target'].strip() and row['text'] == args['text'].strip() and row['anchor'] == args['anchor']
        return row['id'] == args['id'] and row['status'] == 'resolved' and row['revision'] > before['revision']


def checks_for(protocol, name, args):
    if name not in SUPPORTED or (protocol.scope is not None and 'neyvia.comments.list' not in protocol.scope):
        return []
    return [{'name': 'effect-' + name.replace('.', '-'), 'observer': True, 'effect': True,
             'subjectKey': name + ':' + str(args.get('id') or args.get('target') or args.get('requestId')),
             'bindSubject': lambda arguments, value, previous: name + ':' + str(value.get('comment', {}).get('id') or value.get('messageId')),
             'observerTool': 'neyvia.comments.list', 'subject': deepcopy(args),
             'expectation': 'Fresh comments store events match the exact comment or durable delivered message',
             'check': lambda arguments, value, previous: verify(protocol, name, arguments, value, previous)}]
