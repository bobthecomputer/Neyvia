"""Capture contexts in the selected Neyvia runtime, without browser substitution."""
from __future__ import annotations
import json
import math
import os
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from .proof_ports import c7_worker_ports


class NeyviaCaptureRuntime:
    engine = 'neyvia-native'

    def __init__(self, request, *, initial_url):
        parsed=urlsplit(initial_url)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.port not in c7_worker_ports():
            raise ValueError('Capture contexts require an explicit owned initial URL and port')
        self.request = request
        self.initial_url = initial_url
        self.browser_starts = 0
        self.contexts_created = 0
        self._runtime_identity = None
        self._tabs = set()

    def completed(self, op, args):
        value = self.request(op, args)
        deadline = time.monotonic() + 30
        action_id=value.get('actionId')
        while action_id and value.get('status') not in {'done', 'failed'}:
            if time.monotonic() >= deadline:
                raise TimeoutError('Native browser completion unavailable; operation is never replayed')
            time.sleep(.025)
            value = self.request('action.get', {'actionId': action_id})
        if value.get('ok') is False or value.get('status') == 'failed':
            raise RuntimeError('Native browser operation refused: ' + str(value.get('error', 'unavailable'))[:300])
        result=value.get('result', value)
        if isinstance(result,dict) and value.get('tabId'):
            result={**result,'tabId':value['tabId']}
        return result

    @contextmanager
    def page(self, *, width, height):
        state = self.request('state', {})
        if not state.get('runtime',{}).get('connected'):
            raise RuntimeError('Explicit Neyvia native runtime is disconnected')
        runtime_identity = state.get('runtime',{}).get('epoch')
        if not runtime_identity:
            raise RuntimeError('Neyvia runtime has no current connection identity')
        reused = self._runtime_identity == runtime_identity
        if not reused:
            self.browser_starts += 1
            self._runtime_identity = runtime_identity
        profile = self.request('profile.create', {'name': 'capture-' + uuid.uuid4().hex})
        space = self.request('space.create', {'name': 'capture-' + uuid.uuid4().hex, 'profileId': profile['id']})
        opened = self.completed('tab.open', {'url': self.initial_url, 'spaceId': space['id'], 'engine': 'webview2'})
        tab_id = opened.get('tabId')
        if not tab_id:
            raise RuntimeError('Native page context has no selected tab')
        self._tabs.add(tab_id)
        self.contexts_created += 1
        page = NeyviaCapturePage(self, tab_id, width, height)
        try:
            self.completed('layout', {'tabs': [{'tabId': tab_id, 'x': 0, 'y': 0, 'width': width, 'height': height, 'visible': True}]})
            self.request('tab.grant', {'tabId': tab_id, 'enabled': True})
            yield page, reused
        finally:
            self.completed('tab.close', {'tabId': tab_id})
            self._tabs.discard(tab_id)

    def snapshot(self, *, reused):
        return {'kind': 'persistent-neyvia-native', 'browserReused': reused,
                'browserStarts': self.browser_starts, 'contextsCreated': self.contexts_created}

    def close(self):
        for tab_id in tuple(self._tabs):
            self.completed('tab.close', {'tabId': tab_id})
            self._tabs.discard(tab_id)


class NeyviaCapturePage:
    def __init__(self, runtime, tab_id, width, height):
        self.runtime, self.tab_id = runtime, tab_id
        self.width, self.height = width, height

    def _call(self, op, **args):
        return self.runtime.completed(op, {'tabId': self.tab_id, **args})

    def goto(self, url, *, wait_until='domcontentloaded', timeout=30000):
        self._call('tab.navigate', url=url)
        deadline = time.monotonic() + min(30, timeout / 1000)
        while time.monotonic() < deadline:
            value = self._call('observe').get('observation', {})
            if value.get('url') == url and value.get('readyState') == 'complete':
                # Navigation revokes grants. This adapter owns only the fresh
                # context it created with its explicit owner transport.
                self.runtime.request('tab.grant',{'tabId':self.tab_id,'enabled':True})
                return
            time.sleep(.05)
        raise TimeoutError('Native navigation did not return its completed document')

    def wait_for_timeout(self, delay):
        if not 0 <= delay <= 10000:
            raise ValueError('Capture delay exceeds bound')
        time.sleep(delay / 1000)

    def wait_for_selector(self, selector, *, state='visible', timeout=15000):
        deadline = time.monotonic() + min(30, timeout / 1000)
        while time.monotonic() < deadline:
            value = self._call('dom', selector=selector, attributes=[], limit=100)
            if any(row['visible'] for row in value['elements']):
                return
            time.sleep(.05)
        raise TimeoutError('Native selector is not visible')

    def screenshot(self, *, path, full_page=False, clip=None):
        if full_page:
            raise ValueError('Native capture currently supports the actual viewport only; full-page capture is unavailable')
        value = self._call('capture')
        source = Path(value['path'])
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if clip is None:
            shutil.copyfile(source, destination)
        else:
            values = [clip[k] for k in ('x', 'y', 'width', 'height')]
            if any(type(v) not in {int, float} or not math.isfinite(v) for v in values):
                raise ValueError('Crop geometry must be finite')
            x, y, w, h = values
            header=source.read_bytes()[:24]
            if header[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Native capture is not PNG: '+header.hex()+' bytes='+str(source.stat().st_size))
            actual_width,actual_height=int.from_bytes(header[16:20],'big'),int.from_bytes(header[20:24],'big')
            if x < 0 or y < 0 or w < 1 or h < 1 or x+w > actual_width or y+h > actual_height:
                raise ValueError('Crop rectangle exceeds the actual native pixels')
            crop_native_png(source,destination,(round(x),round(y),round(x+w)-round(x),round(y+h)-round(y)))

    def annotate(self, *, rectangle, comment):
        observed = self._call('observe')['observation']
        return self._call('annotate', revision=observed['revision'], rectangle=rectangle, comment=comment)


def authenticated_request(port, session_cookie):
    """Explicit loopback owner session supplied in memory by the launching host."""
    import urllib.request
    import urllib.error
    if type(port) is not int or port not in c7_worker_ports() or not session_cookie or '\n' in session_cookie or '\r' in session_cookie:
        raise ValueError('Explicit task port and memory-only owner cookie required')
    def request(op, args):
        raw = json.dumps({'op': op, 'args': args}).encode()
        req = urllib.request.Request(f'http://127.0.0.1:{port}/api/ui/browser', data=raw,
                                     headers={'Content-Type': 'application/json', 'Cookie': session_cookie})
        try:
            with urllib.request.urlopen(req, timeout=35) as response:
                return json.loads(response.read(2*1024*1024))
        except urllib.error.HTTPError as error:
            value=json.loads(error.read(2048))
            raise RuntimeError('Neyvia '+op+' refused: '+str(value.get('error',error.code))[:500]) from None
    return request


def crop_native_png(source,destination,rectangle):
    """Crop actual PNG pixels using the installed Windows imaging library."""
    if os.name!='nt':raise RuntimeError('Native PNG crop requires Windows System.Drawing on this transport')
    program=r'''$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
$value=[Console]::In.ReadToEnd() | ConvertFrom-Json
$image=[System.Drawing.Image]::FromFile($value.source)
try {
  $r=[System.Drawing.Rectangle]::new($value.rectangle[0],$value.rectangle[1],$value.rectangle[2],$value.rectangle[3])
  $cropped=([System.Drawing.Bitmap]$image).Clone($r,$image.PixelFormat)
  try {$cropped.Save($value.destination,[System.Drawing.Imaging.ImageFormat]::Png)} finally {$cropped.Dispose()}
} finally {$image.Dispose()}
'''
    import base64
    command=base64.b64encode(program.encode('utf-16-le')).decode('ascii')
    result=subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',command],input=json.dumps({'source':str(source),'destination':str(destination),'rectangle':rectangle}),text=True,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or not destination.is_file():
        raise RuntimeError('Native PNG crop failed: '+result.stderr[-500:])
