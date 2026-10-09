"""Memory-only PNG frames for the desktop bridge's JSON transport."""
from __future__ import annotations

import base64
import http.cookiejar
import os
from pathlib import Path
from urllib.request import HTTPCookieProcessor, Request, build_opener, ProxyHandler
from urllib.parse import urlencode, urlsplit

MAX_FRAME_BYTES = 16 * 1024 * 1024


def forward_frame(root, payload):
    from .neyvia_remote import NoRedirect, RemoteError, _loopback, _proof_ports
    base = os.environ.get('NEYVIA_UI_BACKEND_URL', '').rstrip('/')
    address = urlsplit(base)
    if address.scheme != 'http' or not _loopback(address.hostname or '') or address.port not in _proof_ports():
        raise RemoteError('selected_loopback_backend_required')
    client = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with client.open(Request(base + '/api/auth/local-session', data=b'{}', headers={'Content-Type': 'application/json'}), timeout=30):
        pass
    query = urlencode({**{key: payload[key] for key in ('connectionId', 'windowId')},
                       '_expectedStateRoot': str(Path(root).resolve())})
    with client.open(base + '/api/ui/remote/frame?' + query, timeout=30) as response:
        raw = response.read(MAX_FRAME_BYTES + 1)
        if len(raw) > MAX_FRAME_BYTES or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RemoteError('invalid_frame', 502)
        return {'png': base64.b64encode(raw).decode('ascii'), 'captureId': response.headers.get('X-Capture-Id', ''),
                'seq': int(response.headers.get('X-Frame-Seq', '0')), 'sha': response.headers.get('X-CUA-Frame-SHA256', '')}
