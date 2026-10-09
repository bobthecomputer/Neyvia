"""Verify claimed paper citations against primary DOI registration metadata."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

STOP = {'the', 'a', 'an', 'and', 'or', 'of', 'for', 'with', 'by', 'in', 'on', 'to', 'from', 'based', 'using'}


def words(text):
    return set(re.findall(r'[a-z0-9]+', text.lower())) - STOP


def verify_papers(candidates, cache, timeout=8):
    """Unknown network results remain undecided; a known wrong paper is a block."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    observations = []
    for candidate in candidates:
        if not candidate.get('used'):
            continue
        source = candidate.get('source', '')
        parsed = urllib.parse.urlsplit(source)
        if parsed.hostname not in {'doi.org', 'dx.doi.org'}:
            continue
        doi = urllib.parse.unquote(parsed.path).lstrip('/')
        path = cache / (hashlib.sha256(doi.encode()).hexdigest() + '.json')
        try:
            if path.exists():
                registered = json.loads(path.read_text(encoding='utf-8'))
            else:
                endpoint = 'https://api.crossref.org/works/' + urllib.parse.quote(doi, safe='')
                request = urllib.request.Request(endpoint, headers={'Accept': 'application/json', 'User-Agent': 'NeyviaC13/1.0 (Automation; citation verification)'})
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError('DOI metadata exceeds 1 MB bounded response')
                message = json.loads(raw)['message']
                registered = {'doi': message['DOI'], 'title': ' '.join(message.get('title', [])),
                              'authors': [row.get('family', '') for row in message.get('author', [])],
                              'publisher': message.get('publisher'), 'endpoint': endpoint}
                path.write_text(json.dumps(registered, ensure_ascii=False, indent=2), encoding='utf-8')
            claimed, actual = words(candidate['name']), words(registered['title'])
            overlap = len(claimed & actual) / max(1, min(len(claimed), len(actual)))
            observations.append({'name': candidate['name'], 'source': source, 'registered': registered,
                                 'matches': overlap >= .5, 'wordOverlap': overlap, 'metadataPath': str(path)})
        except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
            observations.append({'name': candidate['name'], 'source': source, 'matches': None,
                                 'reason': 'Primary registration metadata unavailable: ' + str(exc)[:160]})
    return observations
