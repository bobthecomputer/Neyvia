"""Resolve explicit public Wikipedia research dates through native web.fetch."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
import ipaddress
import json
import re
import unicodedata
import calendar
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit


def explicit_as_of(question):
    """Read an explicit as-of date; month/year precision uses period end."""
    match = re.search(r'\bas of\s+(\d{4}-\d{2}-\d{2})\b', question, re.I)
    if match:
        return date.fromisoformat(match[1]).isoformat()
    match = re.search(r'\bas of\s+([A-Za-z]+)\s+(?:(\d{1,2}),?\s+)?(\d{4})\b', question, re.I)
    if not match:
        year = re.search(r'\bas of\s+(\d{4})(?![-\d])\b', question, re.I)
        return date(int(year[1]), 12, 31).isoformat() if year else None
    month = datetime.strptime(match[1][:3].title(), '%b').month
    year = int(match[3])
    day = int(match[2]) if match[2] else calendar.monthrange(year, month)[1]
    return date(year, month, day).isoformat()


def _title(value):
    value = unicodedata.normalize('NFC', ' '.join(value.replace('_', ' ').split()))
    return value[:1].casefold() + value[1:]


def resolve_wikipedia(registry, url, as_of):
    """Never infer a date or substitute a revision absent verified API evidence."""
    result = {'url': url, 'originalUrl': url, 'asOf': as_of,
              'revisionId': None, 'revisionTimestamp': None, 'receiptPath': '',
              'status': 'not_applicable'}
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
        if (parsed.scheme not in {'http', 'https'} or not host or parsed.username or parsed.password
                or parsed.port not in {None, 80, 443}):
            raise ValueError('Public HTTP(S) source without credentials or private ports required')
        if host in {'localhost', 'localhost.localdomain'} or host.endswith(('.local', '.internal')):
            raise ValueError('Private source refused')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError('Private source refused')
        if not as_of or host not in {'en.wikipedia.org', 'en.m.wikipedia.org'}:
            return result
        if not isinstance(as_of, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', as_of):
            raise ValueError('asOf must be an explicit ISO YYYY-MM-DD')
        cutoff = datetime.combine(date.fromisoformat(as_of), time(23, 59, 59), timezone.utc)
        if parsed.path.startswith('/wiki/'):
            title = unquote(parsed.path[len('/wiki/'):])
        elif parsed.path == '/w/index.php':
            query = parse_qs(parsed.query)
            title = query.get('title', [''])[0]
            if not title and query.get('oldid'):
                revision_id = int(query['oldid'][0])
                if revision_id <= 0:
                    raise ValueError('Invalid explicit Wikipedia oldid')
                lookup = 'https://en.wikipedia.org/w/api.php?' + urlencode({'action': 'query', 'format': 'json',
                    'formatversion': '2', 'prop': 'revisions', 'revids': revision_id, 'rvprop': 'ids|timestamp'})
                fetched = registry.call('web.fetch', {'url': lookup, 'maxChars': 20000, 'refresh': True})
                if not fetched.get('ok') or fetched['result'].get('status') != 200 or fetched['result'].get('truncated') or fetched['result'].get('responseTruncated'):
                    raise ValueError('Explicit Wikipedia oldid lookup unavailable')
                final = urlsplit(fetched['result'].get('finalUrl', lookup))
                if final.scheme != 'https' or final.hostname != 'en.wikipedia.org' or final.path != '/w/api.php':
                    raise ValueError('Wikipedia oldid lookup redirected outside public API')
                pages = json.loads(fetched['result']['text']).get('query', {}).get('pages', [])
                if len(pages) != 1 or pages[0].get('revisions', [{}])[0].get('revid') != revision_id:
                    raise ValueError('Explicit Wikipedia oldid identity mismatch')
                title = pages[0].get('title', '')
                resolved = resolve_wikipedia(registry, 'https://en.wikipedia.org/wiki/' + quote(title.replace(' ', '_')), as_of)
                resolved.update(originalUrl=url, titleLookupReceipt=fetched.get('receipt_path', ''))
                return resolved
        else:
            return result
        if not title or len(title) > 500 or any(ord(char) < 32 for char in title):
            raise ValueError('Wikipedia article title missing or invalid')
        params = {'action': 'query', 'format': 'json', 'formatversion': '2', 'prop': 'revisions',
                  'titles': title, 'rvstart': cutoff.isoformat().replace('+00:00', 'Z'),
                  'rvdir': 'older', 'rvlimit': '1', 'rvprop': 'ids|timestamp'}
        api = 'https://en.wikipedia.org/w/api.php?' + urlencode(params)
        result['apiUrl'] = api
        fetched = registry.call('web.fetch', {'url': api, 'maxChars': 20000, 'refresh': True})
        result['receiptPath'] = fetched.get('receipt_path', '')
        if fetched.get('ok') is not True:
            raise ValueError('Native Wikipedia API fetch failed: ' + str(fetched.get('error', 'unavailable')))
        document = fetched['result']
        if document.get('status') != 200 or document.get('truncated') or document.get('responseTruncated'):
            raise ValueError('Wikipedia API response unavailable or exceeds bounded response')
        final = urlsplit(document.get('finalUrl', api))
        if final.scheme != 'https' or final.hostname != 'en.wikipedia.org' or final.path != '/w/api.php':
            raise ValueError('Wikipedia API redirected outside the expected public endpoint')
        payload = json.loads(document['text'])
        pages = payload.get('query', {}).get('pages', [])
        if payload.get('error') or len(pages) != 1:
            raise ValueError('Wikipedia API returned no unique article')
        page = pages[0]
        if page.get('missing') or page.get('invalid') or _title(page.get('title', '')) != _title(title):
            raise ValueError('Wikipedia API article identity mismatch or missing article')
        revisions = page.get('revisions', [])
        if len(revisions) != 1:
            raise ValueError('No Wikipedia revision exists at or before the explicit date')
        revision = revisions[0]
        revision_id = revision.get('revid')
        timestamp = revision.get('timestamp', '')
        if type(revision_id) is not int or revision_id <= 0:
            raise ValueError('Wikipedia API returned an invalid revision ID')
        instant = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if instant.tzinfo is None or instant > cutoff:
            raise ValueError('Wikipedia API revision timestamp exceeds explicit date')
        result.update(url=f'https://en.wikipedia.org/w/index.php?oldid={revision_id}',
                      revisionId=revision_id, revisionTimestamp=timestamp, title=page['title'], pageId=page['pageid'], status='resolved')
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as exc:
        result.update(status='unavailable', reason=str(exc)[:1200])
    return result
