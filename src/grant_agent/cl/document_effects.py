"""Fetched documents, PDF and Scroll Study effects over fresh owning observers."""
from __future__ import annotations

import hashlib
import html
from email.message import Message

from . import pdf_effects, scroll_effects

SUPPORTED = pdf_effects.SUPPORTED | scroll_effects.SUPPORTED | {'web.fetch'}

_READ_ONLY = {'neyvia.pdf.extract_text', 'neyvia.scroll.job', 'neyvia.scroll.stats',
              'web.passages', 'web.cite'}


def readonly(name, args):
    """Pure owner reads; fetched documents and video digests write state."""
    if name == 'neyvia.pdf.search':
        return False  # Search emits a visible renderer command.
    return True if name in _READ_ONLY else None


def snapshot_for(protocol, name, args):
    if name == 'web.fetch':
        from ..web_documents import WebDocuments
        owner = WebDocuments(protocol.gateway.root)
        with owner.connect() as db:
            return {'documents':{row['id']:dict(row) for row in db.execute('SELECT * FROM documents WHERE url=?',(args['url'].strip(),))}}
    family = pdf_effects if name in pdf_effects.SUPPORTED else scroll_effects
    return family.snapshot_for(protocol, name, args) if name in SUPPORTED else None


def checks_for(protocol, name, args):
    if name == 'web.fetch':
        def check(arguments, value, previous):
            try:
                return _fetched(protocol, arguments, value, previous)
            except (OSError, KeyError, TypeError, ValueError, LookupError):
                return False
        return [{'name':'effect-web-fetch','observer':True,'effect':True,
            'subjectKey':'web:'+args['url'].strip(),
            'bindSubject':lambda arguments,value,previous:'web:'+arguments['url'].strip(),
            'observerTool':'web-document-owner+original-http-bytes','subject':dict(args),
            'expectation':'Fresh immutable owner bytes and exact parsed text bind this URL, document and returned range',
            'check':check}]
    family = pdf_effects if name in pdf_effects.SUPPORTED else scroll_effects
    return family.checks_for(protocol, name, args) if name in SUPPORTED else []


def _fetched(protocol, args, value, before):
    from ..web_documents import WebDocuments
    from ..native_tools import _ReadableHtmlParser
    if not isinstance(value,dict) or not isinstance(before,dict):
        return False
    owner = WebDocuments(protocol.gateway.root)
    identity = value['document']
    text, metadata = owner.get(identity)
    body = owner.body(identity)
    content_hash = hashlib.sha256(body).hexdigest()
    text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    url = args['url'].strip()
    expected_id = 'doc_'+hashlib.sha256((url+'\0'+content_hash+'\0'+text_hash).encode()).hexdigest()
    header = Message()
    header['Content-Type'] = metadata['contentType']
    decoded = body.decode(header.get_content_charset() or 'utf-8',errors='replace')
    if 'html' in metadata['contentType'].lower() or '<html' in decoded[:500].lower():
        parser = _ReadableHtmlParser()
        parser.feed(decoded)
        parsed, title = parser.readable_text(), html.unescape(parser.title)
    else:
        parsed, title = decoded.strip(), ''
    maximum = max(200,min(int(args.get('maxChars') or 20000),100000))
    expected = owner.read({'document':identity,'maxChars':maximum})
    with owner.connect() as db:
        row = db.execute('SELECT * FROM documents WHERE id=?',(identity,)).fetchone()
        previous = before['documents'].get(identity)
        older = {r['id']:dict(r) for r in db.execute('SELECT * FROM documents WHERE url=?',(url,)) if r['id']!=identity}
    prior_older = {key:r for key,r in before['documents'].items() if key != identity}
    immutable = not previous or all(dict(row)[key] == previous[key] for key in ('id','url','text','metadata'))
    return (value == {**expected,'cacheHit':value.get('cacheHit')} and
        isinstance(value.get('cacheHit'),bool) and (not args.get('refresh') or value['cacheHit'] is False) and
        expected_id == identity and row['url'] == url and metadata['url'] == url and
        metadata['contentSha256'] == content_hash and metadata['textSha256'] == text_hash and
        metadata['characters'] == len(text) and parsed == text and metadata['title'] == title and
        metadata['responseTruncated'] == (len(body) >= owner.MAX_RESPONSE_BYTES) and
        200 <= metadata['status'] < 400 and bool(metadata['finalUrl']) and immutable and older == prior_older)
