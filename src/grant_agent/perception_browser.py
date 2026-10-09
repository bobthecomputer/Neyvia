"""Owned browser sessions: real DOM/accessibility text and guarded actions.

All Playwright work stays on one worker thread. No connection to user tabs,
downloads or shared browser profiles; opening a URL grants only its origin.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from importlib.resources import files


DOM_SOURCE = files("grant_agent").joinpath("browser_dom.js").read_text(encoding="utf-8")
DOM = "options => {" + DOM_SOURCE + "\nreturn globalThis.__neyviaProjection.snapshot(options || {});}"


def origin(url):
    p = urlsplit(url)
    if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password:
        raise ValueError('An HTTP(S) URL without credentials is required')
    return p.scheme, p.hostname.lower(), p.port or (443 if p.scheme == 'https' else 80)


class BrowserSessions:
    def __init__(self, *, headless=None):
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='perception-browser')
        self.sessions = {}
        self.playwright = self.browser = None
        self.headless = headless
        self.closed = False
        atexit.register(self.close)

    def run(self, method, *args):
        return self.worker.submit(getattr(self, '_' + method), *args).result(timeout=45)

    def _open(self, url):
        if len(self.sessions) >= 8:
            raise RuntimeError('Close an owned browser session before opening another (limit 8)')
        granted = origin(url)
        if self.browser is None:
            from playwright.sync_api import sync_playwright
            self.playwright = sync_playwright().start()
            if self.headless is not None:
                if not self.headless.status().get('connected'):
                    raise RuntimeError('The configured Neyvia browser is unavailable')
                self.browser = self.playwright.chromium.connect_over_cdp(
                    self.headless.endpoint,
                    headers={'Authorization': 'Bearer ' + self.headless.token},
                    timeout=15000)
            else:
                self.browser = self.playwright.chromium.launch(headless=True)
        context = self.browser.new_context(accept_downloads=False, service_workers='block')
        def route(request):
            try:
                permitted = origin(request.request.url) == granted
            except ValueError:
                permitted = False
            request.continue_() if permitted else request.abort()
        context.route('**/*', route)
        page = context.new_page()
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            if origin(page.url) != granted:
                raise PermissionError('Navigation left the granted origin')
        except Exception:
            context.close()
            raise
        sid = uuid.uuid4().hex
        self.sessions[sid] = {'page': page, 'context': context, 'origin': granted, 'revision': None}
        return {'ok': True, 'browserId': sid, 'url': page.url}

    def _observe(self, sid):
        row = self.sessions[sid]
        page = row['page']
        value = page.evaluate(DOM)
        scene_source = files("grant_agent").joinpath("perception_scene.js").read_text(encoding="utf-8")
        value["scene"] = page.evaluate(scene_source, {"revision": value.get("revision")})
        # Use the same bounded, redacted semantic tree as the native engines,
        # including same-origin frames, rather than a second secret-bearing tree.
        value['accessibilityPasswordRedacted'] = any(e['secret'] for e in value['elements'])
        value['ariaTruncated'] = len(value['accessibility']) > 40000
        value['accessibility'] = value['accessibility'][:40000]
        for element in value['elements']:
            if element['role'] == 'combobox' and 'select' in element['actions']:
                element['actions'].append('fill')  # Retain the legacy perception action schema.
            element['actions'] = [action for action in element['actions'] if action in {'click', 'fill'}]
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        row['revision'] = digest
        return {**value, 'revision': digest, 'browserId': sid}

    def _action(self, sid, revision, element, action, value):
        row = self.sessions[sid]
        current = self._observe(sid)
        if revision != current['revision']:
            return {'ok': False, 'status': 'stale_projection', 'revision': current['revision']}
        selected = next((e for e in current['elements'] if e['id'] == element), None)
        if not selected or action not in selected['actions'] or not selected['enabled']:
            raise ValueError('Action unavailable for this observed element')
        row['page'].evaluate("a=>globalThis.__neyviaProjection.act(a)",
                             {'element': element, 'action': 'select' if action == 'fill' and selected['role'] == 'combobox' else action, 'value': value})
        return {'ok': True, 'browserId': sid, 'action': action, 'element': element,
                'observation': self._observe(sid)}

    def _close_one(self, sid):
        self.sessions.pop(sid)['context'].close()
        return {'ok': True, 'closed': sid}

    def _shutdown(self):
        for row in self.sessions.values():
            row['context'].close()
        self.sessions.clear()
        if self.browser:
            if self.headless is None:
                self.browser.close()
        if self.playwright:
            self.playwright.stop()
        self.browser = self.playwright = None

    def close(self):
        if not self.closed:
            self.run('shutdown')
            self.worker.shutdown(wait=True)
            self.closed = True
