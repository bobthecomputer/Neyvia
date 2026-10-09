"""Actual loopback remote manuals against an owned private native window."""
import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.request import Request, build_opener, HTTPCookieProcessor, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]


def probe(scratch, request, call, sid, wid, state):
    from grant_agent.web_backend import FluxioWebBackend, make_handler, _HandshakeSafeThreadingHTTPServer
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.neyvia_remote import service_for
    from grant_agent import neyvia_manuals as manuals
    from grant_agent.native_tools import NativeToolRegistry
    relay_root = scratch / 'remote-relay'
    relay_root.mkdir()
    prepare_broker_fixture(relay_root)
    from c8_scope import assigned_ports, fixture_port
    relay_port = fixture_port()
    remote_port = fixture_port(exclude=(relay_port,))
    os.environ.update(NEYVIA_REMOTE_PROOF_LOOPBACK='1',
        NEYVIA_REMOTE_PROOF_PORTS=','.join(map(str, sorted(assigned_ports()))))
    server = _HandshakeSafeThreadingHTTPServer(('127.0.0.1', relay_port),
        make_handler(FluxioWebBackend(relay_root, scratch / 'rendered-preview/dist')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
    def relay(path, body):
        with opener.open(Request(f'http://127.0.0.1:{relay_port}' + path, data=json.dumps(body).encode(),
                headers={'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{relay_port}'}), timeout=30) as response:
            value = json.load(response)
        if not value.get('ok'):
            raise RuntimeError('Owned remote request refused: ' + str(value.get('error')))
        return value.get('data', value)
    remote = lambda op, args: relay('/api/ui/remote', {'op': op, 'args': args})
    registry = None
    connection = None
    rows = []
    host = service_for(scratch)
    try:
        relay('/api/auth/local-session', {})
        # This owner grant covers one disposable window only; no tailnet,
        # operator windows, live account or remote PC is used.
        with request('/api/ui/remote', {'op': 'enable', 'args': {'windowIds': [wid], 'minutes': 1}}) as response:
            enabled = json.load(response)['data']
        connection = remote('connect', {'url': f'http://127.0.0.1:{remote_port}', 'invite': enabled['invite']})['connection']['id']
        registry = NativeToolRegistry(relay_root)
        manual_host = SimpleNamespace(bus=SimpleNamespace(root=relay_root))
        for chapter in ('overview', 'user-side'):
            _, digest, _ = manuals.get_manual('remote')
            def dispatch(tool, args, action_id=''):
                return remote(tool.rsplit('.', 1)[1], args)
            executed = manuals.run(manual_host, {'id': 'remote', 'chapter': chapter,
                'procedure': 'observe-allowed-window', 'inputs': {'connectionId': connection, 'windowId': wid}}, registry, dispatch)
            observed = remote('snapshot', {'connectionId': connection, 'windowId': wid})
            field = next(e for e in observed['elements'] if e['label'] == 'Task input')
            from prove_c11_preview import observe_controls
            independent = observe_controls(call, sid, wid, ['Task input'])
            expected = next(e for e in independent['elements'] if e['label'] == 'Task input')['value']
            rows.append({'id': 'remote/' + chapter + '/observe-allowed-window',
                'passed': executed.get('ok') is True and field.get('value') == expected,
                'manualLoaded': True, 'manualSourceHash': digest, 'result': executed,
                'independentFieldReadback': expected, 'remoteFieldReadback': field.get('value'),
                'windowId': wid, 'boundary': 'Real owner-enabled loopback relay and private native window; no remote-PC claim'})
        granted = next(g for g in host.grants.values() if g['id'] == enabled['session']['id'])
        indicator_pid = granted['indicator'].proc.pid
        # Independent per-desktop enumeration: the real owner indicator must
        # live on this pinned host's private desktop, never Default.
        from c8h_conpty import windows
        own = windows(owned_pids=(indicator_pid,))
        found = [w for w in own['windows'] if w['pid'] == indicator_pid]
        indicator = {'pid': indicator_pid, 'windows': found,
            'private': bool(found) and all(w['desktop'] == own['threadDesktop']
                and w['desktop'] != own['inputDesktop'] for w in found)}
        remote('disconnect', {'connectionId': connection})
        connection = None
        return {'rows': rows, 'passed': all(r['passed'] for r in rows) and indicator['private'],
            'indicator': indicator, 'sourceSha256': {'scripts/c8h_remote.py': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    finally:
        if connection:
            remote('disconnect', {'connectionId': connection})
        host.close()
        service_for(relay_root).close()
        server.shutdown()
        server.server_close()


def contract():
    evidence = ROOT / 'scripts/evidence/C8h-remote.json'
    from c8_scope import fixture_ports
    ports = fixture_ports()
    if len(ports) < 2:
        raise RuntimeError('C8 remote probe requires two free assigned task ports')
    env = {**os.environ, 'NEYVIA_C8H_NATIVE_PROBE': 'remote'}
    subprocess.run([sys.executable, str(ROOT / 'scripts/c8g_native.py'), '--port', str(ports[0]),
        '--debug-port', str(ports[1]), '--receipt', str(evidence)], cwd=ROOT, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=240, check=False)
    result = json.loads(evidence.read_text())
    journey = result.get('additionalJourneys', {}).get('remote', {})
    passed = bool(journey.get('passed') and result.get('guard', {}).get('ok')
        and result.get('hostGuard', {}).get('ok') and result.get('externalGuardLog', {}).get('unchanged'))
    Path('remote-contract.json').write_text(json.dumps({'passed': passed, 'journey': journey,
        'receipt': str(evidence.relative_to(ROOT)), 'fullNativeRunPassed': result.get('ok')}, indent=2))
    if not passed:
        raise RuntimeError('Real private remote manuals or containment did not pass')
