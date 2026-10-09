"""Fresh PDF renderer state and source conservation predicates."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import time

SUPPORTED = {'neyvia.pdf.open', 'neyvia.pdf.goto', 'neyvia.pdf.search',
             'neyvia.pdf.highlight', 'neyvia.pdf.zoom'}

def _pdf_file(protocol, source):
    from ..neyvia_pdf_tools import safe_pdf

    path = safe_pdf(protocol.gateway.root, source)
    if path.is_symlink() or path.is_junction() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('PDF effect observer requires a regular <=32 MiB source')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest()}

def _pdf_state(protocol):
    from ..ui_command_bus import bus_for

    return deepcopy(bus_for(protocol.gateway.root).get('app:pdf'))

def _pdf_check(protocol, name, args, value, before):
    from ..ui_command_bus import bus_for

    if not before or not before['source']:
        return False
    source = before['source']
    requested = bus_for(protocol.gateway.root).get('pdf:requested') or {}
    if name.endswith('.open') and (os.path.normcase(requested.get('source', '')) != os.path.normcase(source['path'])
                                    or requested.get('pages') != value.get('pages')):
        return False
    baseline = (before['observed'] or {}).get('observedAt', '')
    # First mount loads and parses the bounded document asynchronously. Retain
    # the same fresh owner predicates while allowing that observed cold path.
    deadline = time.monotonic() + (8 if name.endswith('.open') else 4)
    while True:
        fresh = _pdf_state(protocol) or {}
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(fresh['observedAt'])).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = float('inf')
        if 0 <= age <= 30 and fresh.get('observedAt', '') > baseline and fresh.get('status') == 'ready' and \
                os.path.normcase(fresh.get('source', '')) == os.path.normcase(source['path']):
            expected_page = args.get('page')
            if name.endswith('.open') or name.endswith('.goto'):
                matched = fresh.get('page') == (expected_page or 1) and fresh.get('pages', 0) >= (expected_page or 1)
            elif name.endswith('.zoom'):
                matched = fresh.get('fitWidth') is True if args['scale'] == 'fit-width' else (
                    fresh.get('fitWidth') is False and fresh.get('scale') == round(args['scale'], 2))
            elif name.endswith('.search'):
                search = fresh.get('search') or {}
                hits = value.get('hits') or []
                matched = (search.get('query') == args.get('query', '') and
                           (search.get('hits', -1) >= len(hits) if value.get('truncated') else
                            search.get('hits') == len(hits)))
            else:
                old_ids = {mark.get('id') for mark in (before['observed'] or {}).get('highlights', [])}
                matched = any(mark.get('id') not in old_ids and mark.get('by') == 'model' and
                              mark.get('page') == expected_page and mark.get('text', '') == args.get('text', '') and
                              mark.get('note', '') == args.get('note', '')
                              and (args.get('rects') is None or mark.get('rects') == args['rects'])
                              for mark in fresh.get('highlights', []))
            rendered = (fresh.get('renderedPages') or {}).get(str(fresh.get('page'))) or {}
            outcome = rendered.get('outcome') or {}
            drawn = (outcome.get('nonBlank') is True and outcome.get('textLayerPresent') is True
                     and rendered.get('textReady') is True and rendered.get('visible') is True and not rendered.get('error')
                     and rendered.get('width', 0) > 0 and rendered.get('height', 0) > 0
                     and rendered.get('sourceSha256') == source['sha256']
                     and isinstance(rendered.get('pixelSha256'), str) and len(rendered['pixelSha256']) == 64
                     and round(rendered.get('cssScale', -1), 2) == fresh.get('scale'))
            if matched and drawn:
                return _pdf_file(protocol, source['path'])['sha256'] == source['sha256']
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def snapshot_for(protocol, name, args):
    from ..ui_command_bus import bus_for
    requested = deepcopy(bus_for(protocol.gateway.root).get('pdf:requested') or {})
    source = args['source'] if name.endswith('.open') else ((_pdf_state(protocol) or {}).get('source') or requested.get('source'))
    return {'observed': _pdf_state(protocol), 'requested': requested,
            'source': _pdf_file(protocol, source) if source else None}


def checks_for(protocol, name, args):
    if name not in SUPPORTED or protocol.scope is not None and 'neyvia.pdf.state' not in protocol.scope:
        return []
    subject = {key: deepcopy(args[key]) for key in ('source', 'page', 'scale', 'query', 'maxHits') if key in args}
    field = 'zoom' if name.endswith('.zoom') else 'search' if name.endswith('.search') else 'highlight' if name.endswith('.highlight') else 'page'
    resource = 'pdf:' + str(args.get('source') or 'opened') + ':' + field
    def check(arguments, value, previous):
        return _pdf_check(protocol, name, arguments, value, previous)
    def bind(arguments, value, previous):
        resource = 'pdf:' + previous['source']['path']
        if name.endswith('.highlight'):
            return resource + ':highlight:' + str(value.get('event', {}).get('ts', 'missing-event'))
        return resource + (':zoom' if name.endswith('.zoom') else ':search' if name.endswith('.search') else ':page')
    return [{'name': 'effect-' + name.removeprefix('neyvia.').replace('.', '-'),
             'observer': True, 'effect': True, 'subjectKey': resource,
             'bindSubject': bind, 'observerTool': 'neyvia.pdf.state', 'subject': subject,
             'expectation': 'Fresh ready renderer state and conserved guarded PDF source bytes',
             'check': check}]
