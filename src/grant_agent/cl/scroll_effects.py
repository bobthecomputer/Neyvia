"""Fresh Scroll Study store, archive and preview predicates."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from zipfile import BadZipFile

SUPPORTED = {'neyvia.scroll.import', 'neyvia.scroll.review', 'neyvia.scroll.pack',
             'neyvia.scroll.preview', 'neyvia.scroll.send'}

def _source(protocol, raw):
    from ..neyvia_workspace_tools import workspace_for

    path = workspace_for(protocol.gateway.root).safe_path(raw)
    if path.suffix.lower() not in {'.md', '.markdown', '.txt'} or any(
        re.search(r'credential|password|secret|nas_access_runbook', part, re.I) for part in path.parts
    ):
        raise ValueError('Effect observer accepts study Markdown/text only')
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('Effect observer needs an existing study source <=1 MiB')
    raw_bytes = path.read_bytes()
    text = raw_bytes.decode('utf-8-sig')
    digest = hashlib.sha256(raw_bytes).hexdigest()
    return {'path': str(path), 'sha256': digest, 'id': 'source-' + digest[:16],
            'textSha256': hashlib.sha256(text.encode()).hexdigest()}

def _scroll_row(protocol, pack, *, absent_ok=False):
    from ..neyvia_scroll import identity, load, store

    pack = identity(pack)
    if absent_ok:
        with store(protocol.gateway.root) as (db, _):
            if db.execute('SELECT 1 FROM packs WHERE id=?', (pack,)).fetchone() is None:
                return None
    return load(protocol.gateway.root, pack)

def _archive(protocol, pack):
    from ..neyvia_scroll import identity

    path = Path(protocol.gateway.root) / '.neyvia' / 'scroll' / identity(pack) / (pack + '.scrollpack')
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Scroll archive observer requires a regular <=32 MiB file')
    body = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}

def _scroll_check(protocol, name, args, value, before):
    from ..neyvia_scroll import load, store, validate
    from ..scroll_pack import read_scrollpack

    root = protocol.gateway.root
    if name == 'neyvia.scroll.import':
        pack = value.get('pack', {})
        pack_id = pack.get('meta', {}).get('id')
        if not pack_id or (args.get('packId') and pack_id != args['packId']):
            return False
        row = load(root, pack_id)
        old = before['pack']
        sources = {record['id']: record for record in row['sources']['records']}
        added = {item['id'] for item in before['sources']} - (set(old['sources']['source_texts']) if old else set())
        if not old and not added or old and added and row['revision'] != old['revision'] + 1:
            return False
        if old and not added and (row['revision'] != old['revision'] or not value.get('replayed')):
            return False
        for item in before['sources']:
            record = sources.get(item['id'])
            if not record or any(record.get(key) != item[key] for key in ('path', 'sha256', 'textSha256')):
                return False
            if _source(protocol, item['path']) != item:
                return False
        expected_status = old['value'].get('status') if old and not added else 'draft'
        return (row['value'].get('status') == expected_status and
                row['value']['sources'] == row['sources']['records'] and
                (not old or row['review'] == old['review']))
    previous = before['row']
    row = load(root, args['pack'])
    if name == 'neyvia.scroll.review':
        old_cards = {card['id']: card for card in previous['value']['cards']}
        new_cards = {card['id']: card for card in row['value']['cards']}
        if set(old_cards) != set(new_cards) or row['revision'] != previous['revision'] + 1:
            return False
        decisions = args.get('decisions') or [{'cardId': card['id'], 'action': 'approve'}
            for card in previous['value']['cards'] if card['chapter'] == args.get('chapter') and
            previous['review'].get(card['id'], {}).get('status') not in {'flagged', 'dropped'}]
        touched = {decision['cardId'] for decision in decisions}
        if not touched or not touched <= set(old_cards):
            return False
        for decision in decisions:
            key, action = decision['cardId'], decision['action']
            expected = 'dropped' if action == 'drop' else 'approved'
            if row['review'].get(key, {}).get('status') != expected or not row['review'][key].get('reviewedAt'):
                return False
            if action == 'edit':
                if new_cards[key] != decision.get('card') or not row['review'][key].get('edited'):
                    return False
            elif new_cards[key] != old_cards[key]:
                return False
        return (all(row['review'].get(key) == previous['review'].get(key) for key in set(old_cards) - touched)
                and row['sources'] == previous['sources'])
    if row['revision'] != previous['revision'] + 1 or row['value'].get('status') != 'ready' or not validate(root, row).get('ok'):
        return False
    archive = _archive(protocol, args['pack'])
    if not archive or any(archive[key] != value.get('archive', value).get(key)
                          for key in ('path', 'sha256', 'bytes') if key in value.get('archive', value)):
        return False
    with store(root) as (_, directory):
        folder = directory / args['pack']
        pack_json = folder / 'pack.json'
        if not pack_json.is_file():
            return False
        import json
        published = json.loads(pack_json.read_text(encoding='utf-8'))
    approved = {key for key, item in row['review'].items() if item.get('status') == 'approved'}
    if {card['id'] for card in published['cards']} != approved or row['sources'] != previous['sources']:
        return False
    try:
        unpacked, source_texts = read_scrollpack(Path(archive['path']))
    except (BadZipFile, KeyError, ValueError):
        return False
    if unpacked != published or source_texts != row['sources']['source_texts']:
        return False
    if name == 'neyvia.scroll.pack':
        return archive['sha256'] == value.get('sha256') and archive['bytes'] == value.get('bytes')
    if name == 'neyvia.scroll.preview':
        from ..neyvia_mobile_studio import state as mobile_state
        from ..neyvia_workspace_tools import workspace_for
        project = Path(value.get('project', ''))
        if project != folder / 'phone' or not value.get('preview') or \
                mobile_state(workspace_for(root)).get('project') != str(project):
            return False
        generated = project / 'www' / 'generated-pack.json'
        return (generated.is_file() and generated.read_bytes() == pack_json.read_bytes() and
                (project / 'www' / 'generated-sources.json').is_file() and
                json.loads((project / 'www' / 'generated-sources.json').read_text(encoding='utf-8'))
                == row['sources']['source_texts'])
    if name == 'neyvia.scroll.send':
        url = urlsplit(value.get('url', ''))
        token = url.path.rsplit('/', 1)[-1]
        if url.port is None or not url.path.startswith('/api/ui/scroll/download/') or \
                not re.fullmatch(r'[A-Za-z0-9_-]{20,}', token):
            return False
        with store(root) as (db, _):
            link = db.execute('SELECT * FROM links WHERE token=?', (token,)).fetchone()
        return bool(link and link['path'] == archive['path'] and link['sha256'] == archive['sha256']
                    and link['consumed'] == 0 and 0 < link['expires'] - time.time() <= 901)
    return False


def snapshot_for(protocol, name, args):
    if name == 'neyvia.scroll.import':
        sources = [_source(protocol, raw) for raw in args['paths']]
        pack = args.get('packId')
        return {'sources': sources, 'pack': _scroll_row(protocol, pack, absent_ok=True) if pack else None}
    row = _scroll_row(protocol, args['pack'])
    return {'row': row, 'archive': _archive(protocol, args['pack'])}


def checks_for(protocol, name, args):
    if name not in SUPPORTED or protocol.scope is not None and 'neyvia.scroll.state' not in protocol.scope:
        return []
    subject = {key: deepcopy(args[key]) for key in ('pack', 'packId', 'paths', 'decisions') if key in args}
    resource = 'scroll:' + str(args.get('pack') or args.get('packId') or 'new')
    def check(arguments, value, previous):
        return _scroll_check(protocol, name, arguments, value, previous)
    def bind(arguments, value, previous):
        return 'scroll:' + value['pack']['meta']['id'] if name == 'neyvia.scroll.import' else resource
    return [{'name': 'effect-' + name.removeprefix('neyvia.').replace('.', '-'),
             'observer': True, 'effect': True, 'subjectKey': resource,
             'bindSubject': bind, 'observerTool': 'neyvia.scroll.state', 'subject': subject,
             'expectation': 'Fresh owner source, review, validation, archive and preview state match',
             'check': check}]
