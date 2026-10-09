"""Fresh managed-process observations and explicit plugin byte postconditions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.parse

from .effects import _file

SUPPORTED = {'host.launch', 'host.launch_file', 'host.stop', 'host.inspect_preview', 'codex.plugins.call'}


def process_identity(pid):
    """PID plus kernel creation time and executable, without launching a shell."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name != 'nt':
        try:
            stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            if stat[0] == 'Z':
                return None
            return {'pid': pid, 'created': stat[19], 'executable': str(Path(f'/proc/{pid}/exe').resolve())}
        except OSError:
            return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return None
        created, exited, cpu, user = (wintypes.FILETIME() for _ in range(4))
        size = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(cpu), ctypes.byref(user)):
            return None
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            return None
        return {'pid': pid, 'created': (created.dwHighDateTime << 32) | created.dwLowDateTime, 'executable': str(Path(image.value).resolve())}
    finally:
        kernel.CloseHandle(handle)


def _owner(protocol):
    from ..installed_programs import InstalledPrograms
    return InstalledPrograms(protocol.gateway.root)


def _sessions(owner):
    paths = list((owner.base / 'sessions').glob('*/session.json'))
    if len(paths) > 2000:
        raise ValueError('Managed session observation exceeds 2000 records')
    return {path.parent.name: json.loads(path.read_bytes()) for path in paths}


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot_for(protocol, name, args):
    if name == 'codex.plugins.call':
        effect = args.get('effect')
        if not isinstance(effect, dict) or set(effect) != {'path', 'sha256'}:
            raise ValueError('CL plugin mutation requires an explicit guarded file path and expected sha256')
        return {'file': _file(protocol, effect['path']), 'effect': dict(effect)}
    owner = _owner(protocol)
    before = {'sessions': _sessions(owner)}
    if name in {'host.launch', 'host.launch_file'}:
        recipe = owner.prepare_file(args['path']) if name == 'host.launch_file' else {'executable': args['executable'], 'arguments': []}
        before['executableSha256'] = _digest(recipe['executable'])
        before['recipe'] = recipe
    else:
        saved = owner.status(args['sessionId'])
        before['session'] = saved
        before['process'] = process_identity(saved.get('pid'))
        if name == 'host.inspect_preview' and before['process'] is None:
            raise ValueError('Preview subject must have a currently live owned process')
    return before


def _fresh_preview(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.port is None or parsed.username or parsed.password:
        raise ValueError('Explicit loopback preview URL required')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('Preview observation refuses redirects')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=4) as response:
        raw = response.read(1048577)
        if len(raw) > 1048576:
            raise ValueError('Full preview effect observation is bounded to 1 MiB')
        return response.status, hashlib.sha256(raw).hexdigest()


def _verify(protocol, name, args, value, before):
    if name == 'codex.plugins.call':
        fresh = _file(protocol, args['effect']['path'])
        return (args['effect'] == before['effect'] and fresh.get('kind') == 'file'
                and fresh.get('sha256') == args['effect']['sha256']
                and value.get('ok') is not False and value.get('isError') is not True)
    owner = _owner(protocol)
    identity = value.get('session', {}).get('sessionId') if name in {'host.launch', 'host.launch_file'} else args['sessionId']
    if not identity:
        return False
    deadline = time.monotonic() + 12
    while True:
        current = owner.status(identity)
        if name == 'host.stop' and current.get('status') not in {'queued', 'starting', 'running'}:
            break
        if name != 'host.stop' and current.get('status') not in {'queued', 'starting'} and not (
                name in {'host.launch', 'host.launch_file'} and current.get('status') == 'running'
                and process_identity(current.get('pid')) is None):
            break
        if time.monotonic() >= deadline:
            return False
        time.sleep(.05)
    fresh_sessions = _sessions(owner)
    if any(fresh_sessions.get(key) != row for key, row in before['sessions'].items() if key != identity):
        return False
    if name == 'host.stop':
        stop = owner._session(identity) / 'stop.json'
        return (current.get('status') == 'stopped' and stop.is_file()
                and process_identity(current.get('pid')) is None
                and current.get('control') == before['session'].get('control'))
    if name == 'host.inspect_preview':
        saved = json.loads((owner._session(identity) / 'preview.json').read_bytes())
        code, digest = _fresh_preview(args['url'])
        return (process_identity(current.get('pid')) == before['process']
                and saved == value.get('preview') and saved.get('httpStatus') == code
                and saved.get('contentSha256') == digest and saved.get('sessionId') == identity
                and saved.get('url') == args['url'] and saved.get('truncated') is False)
    if identity in before['sessions'] or current.get('executableSha256') != before['executableSha256']:
        return False
    recipe = before['recipe']
    expected_args = recipe['arguments'] + args.get('arguments', [])
    if Path(current['executable']).resolve() != Path(recipe['executable']).resolve() or current.get('arguments') != expected_args:
        return False
    if _digest(current['executable']) != before['executableSha256']:
        return False
    if name == 'host.launch_file' and (owner.prepare_file(args['path']) != recipe or current.get('sourceRecipe') != recipe):
        return False
    kernel = process_identity(current.get('pid'))
    if current.get('status') == 'running' and kernel:
        value.setdefault('observedProcess', kernel)
        return kernel == value['observedProcess'] and Path(kernel['executable']).resolve() == Path(current['executable']).resolve()
    return (current.get('status') == 'completed' and current.get('exitCode') == 0
            and current.get('logsComplete') is True and current.get('outputTruncated') is False)


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    return [{'name': 'effect-' + name.replace('.', '-'), 'observer': True, 'effect': True,
             'subjectKey': name + ':' + str(args.get('sessionId', args.get('path', args.get('server', 'new')))),
             'observerTool': 'fresh-managed-owner-kernel-and-artifact-bytes', 'subject': dict(args),
             'expectation': 'Exact owned process identity/state or explicit plugin file bytes are freshly observed; preview endpoint process ownership remains unverified',
             'check': lambda arguments, value, before: _verify(protocol, name, arguments, value, before)}]
