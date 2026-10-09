"""Actual authenticated native-app calls across independent HTTP handler threads."""
import argparse
import hashlib
from http.cookiejar import CookieJar
import json
import os
import secrets
from pathlib import Path
import sys
import threading
import traceback
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from run_c11_cohort import write_receipt


def run(port):
    scratch = ROOT / '.agent_control/c11g-native-http' / uuid.uuid4().hex
    scratch.mkdir(parents=True)
    for name in ('NEYVIA_COORDINATOR_AUTOSTART', 'NEYVIA_TOOL_AUTO_UPDATE', 'FLUXIO_WATCHDOG_AUTOSTART', 'FLUXIO_RUNTIME_AUTO_UPDATE'):
        os.environ[name] = '0'
    os.environ.update(FLUXIO_WORKSPACE_ROOT=str(scratch), NEYVIA_UI_STATE_ROOT=str(scratch), NEYVIA_PROOF_CREDENTIAL_GUARD='1')
    os.environ['SYNTELOS_ACCOUNT_USER'] = 'c11g-proof-owner'
    os.environ['SYNTELOS_ACCOUNT_PASSWORD'] = secrets.token_urlsafe(40)
    from grant_agent.proof_credential_guard import install
    install(scratch)
    from grant_agent.cua_guard import ZeroDisturbanceGuard
    from grant_agent.cua_native_procedures import hosted_native_applications
    from grant_agent.web_backend import FluxioWebBackend, make_handler, _HandshakeSafeThreadingHTTPServer
    from grant_agent.neyvia_manuals import unwrap
    guard = ZeroDisturbanceGuard().start()
    result = {'schema': 'neyvia.c11g.native-http.v1', 'port': port, 'ok': False,
        'boundary': 'Real authenticated backend creates a fresh registry on each HTTP call; app state and COM affinity survive these calls',
        'calls': [], 'sourceSha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            'src/grant_agent/cua_native_procedures.py', 'src/grant_agent/native_tools.py', 'src/grant_agent/cua_guard.py',
            'src/grant_agent/web_backend.py', 'src/grant_agent/web_backend_http.py', 'scripts/prove_c11g_native_http.py')}}
    server = None
    identity = None
    base = 'http://127.0.0.1:' + str(port)
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    def request(path, data):
        with opener.open(Request(base + path, data=json.dumps(data).encode(),
            headers={'Origin': base, 'Content-Type': 'application/json'}), timeout=90) as response:
            return json.load(response)
    def call(operation, args):
        response = request('/api/backend', {'command': 'call_native_tool_command', 'payload': {
            'tool': 'neyvia.nativeapp.' + operation, 'arguments': args}})
        if not response['ok']:
            raise RuntimeError('Backend command failed')
        record = response['data']
        result['calls'].append(record)
        if not record.get('ok'):
            raise RuntimeError('Registered native tool failed: ' + str(record.get('error')))
        return unwrap(record)
    try:
        backend = FluxioWebBackend(scratch, scratch)
        server = _HandshakeSafeThreadingHTTPServer(('127.0.0.1', port), make_handler(backend))
        threading.Thread(target=server.serve_forever, daemon=True, name='c11g-native-http').start()
        try:
            request('/api/backend', {'command': 'call_native_tool_command', 'payload': {
                'tool': 'neyvia.nativeapp.open', 'arguments': {'app': 'Command Prompt'}}})
            raise RuntimeError('Unauthenticated app opening was admitted')
        except HTTPError as exc:
            result['unauthenticatedRefused'] = exc.code == 401
            if not result['unauthenticatedRefused']:
                raise
        if not request('/api/auth/local-session', {}).get('ok'):
            raise RuntimeError('Local owner authentication failed')
        result['authentication'] = 'Real local owner cookie; cookie never saved in receipt'
        result['apps'] = []
        for app in ('Command Prompt', 'Microsoft Word'):
            identity = call('open', {'app': app})['sessionId']
            marker = 'HTTP owned memo ' + identity
            call('edit', {'sessionId': identity, 'value': marker})
            call('persist', {'sessionId': identity})
            check = call('observe', {'sessionId': identity, 'expected': marker, 'persisted': True})
            if not check.get('ok'):
                raise RuntimeError('Independent HTTP saved-state check failed')
            result['apps'].append({'app': app, 'independentFinalCheck': check})
            call('close', {'sessionId': identity})
            identity = None
        result['ok'] = result['unauthenticatedRefused'] and len(result['calls']) == 10
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)[:300]
        result['sourceFrames'] = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
            for f in traceback.extract_tb(exc.__traceback__)[-8:]]
    finally:
        if identity:
            hosted_native_applications(scratch).close({'sessionId': identity})
        hosted_native_applications(scratch).shutdown()
        if server:
            server.shutdown()
            server.server_close()
        result['guard'] = guard.close()
        result['ok'] = result['ok'] and result['guard']['ok']
        write_receipt(ROOT / 'scripts/evidence/C11g-apps-native-http.json', result)
    print(json.dumps({'ok': result['ok'], 'error': result.get('error'), 'registeredCalls': len(result['calls'])}))
    return result['ok']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, type=int, choices=range(48701, 48710))
    args = parser.parse_args()
    raise SystemExit(0 if run(args.port) else 2)
