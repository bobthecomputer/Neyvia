"""Fixture and scoped normal CLI bootstrap for the real sidebar UI proof."""
from pathlib import Path
import argparse
import os
import runpy
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
sys.path.insert(0, str(REPO / 'scripts'))
parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['fixture', 'prepare', 'serve'])
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--port', type=int, required=True)
parser.add_argument('--static-root', type=Path, required=True)
args = parser.parse_args()
assert args.port == 48668
os.environ.update(NEYVIA_CONNECTED_SERVICE_PORT=str(args.port), NEYVIA_WEB_PORT=str(args.port),
                  NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{args.port}',
                  NEYVIA_PROOF_ALLOWED_PORTS=os.environ.get('NEYVIA_PROOF_ALLOWED_PORTS', '[48668]'))
from grant_agent.proof_credential_guard import install
install(args.root)
if args.mode == 'prepare':
    import http.cookiejar
    import json
    import threading
    import urllib.request
    from grant_agent.web_backend import FluxioWebBackend, _HandshakeSafeThreadingHTTPServer, make_handler
    backend = FluxioWebBackend(args.root, args.static_root)
    server = _HandshakeSafeThreadingHTTPServer(('127.0.0.1', args.port), make_handler(backend))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(route, body):
        req = urllib.request.Request(f'http://127.0.0.1:{args.port}'+route,
                                     data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with client.open(req, timeout=60) as response:
            return json.load(response)
    try:
        assert request('/api/auth/local-session', {}).get('ok')
        saved = request('/api/backend', {'command':'onboarding_save_command','payload':{'dismissed':True}})
        assert saved.get('ok'), saved
        state = request('/api/backend', {'command':'onboarding_state_command','payload':{}})
        data = state.get('data', state)
        assert data['state']['dismissed'] is True, state
        (args.root/'setup-preparation.json').write_text(json.dumps({'ok':True,'state':data['state'],
            'boundary':'Actual authenticated setup dismissal; no sidebar/list observation before cold seed copy.'}, indent=2)+'\n')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
elif args.mode == 'fixture':
    from verify_fix_sidebar import fixture
    fixture(args.root)
else:
    # Replace discovery with only the real native adapter, as in the HTTP proof.
    # All frontend calls still traverse the actual CLI backend/owners/IPC.
    from grant_agent import neyvia_ui_api
    from grant_agent.connected_sessions.broker import broker_for
    from grant_agent.connected_sessions.neyvia import NeyviaAdapter
    if os.environ.get('FIX_SIDEBAR_UI_TRACE') == '1':
        import functools
        import json
        import time
        from grant_agent import web_backend
        from grant_agent import neyvia_workspace_tools
        trace_lock = __import__('threading').Lock()
        def trace(name, original):
            @functools.wraps(original)
            def measured(*positional, **named):
                started = time.perf_counter()
                at = time.time_ns()
                try:
                    return original(*positional, **named)
                finally:
                    row = {'name': name, 'startNs': at, 'durationMs': (time.perf_counter()-started)*1000}
                    with trace_lock, (args.root/'owner-timings.jsonl').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(row)+'\n')
            return measured
        NeyviaAdapter.available = trace('native.available', NeyviaAdapter.available)
        NeyviaAdapter.list_sessions = trace('native.list_sessions', NeyviaAdapter.list_sessions)
        NeyviaAdapter._context = trace('native.context', NeyviaAdapter._context)
        from grant_agent.connected_sessions.broker import ConnectedBroker
        from grant_agent.connected_sessions.seen import SeenStore
        from grant_agent.connected_sessions.sidebar_cleanup import SidebarSafetyObserver
        totals = {}
        def aggregate(name, original):
            @functools.wraps(original)
            def measured(*positional, **named):
                started = time.perf_counter()
                try:
                    return original(*positional, **named)
                finally:
                    elapsed = (time.perf_counter()-started)*1000
                    with trace_lock:
                        row = totals.setdefault(name, {'count': 0, 'durationMs': 0, 'maxMs': 0})
                        row['count'] += 1
                        row['durationMs'] += elapsed
                        row['maxMs'] = max(row['maxMs'], elapsed)
            return measured
        for name, owner, method in [('broker.latest_run', ConnectedBroker, 'latest_run'),
                                     ('broker.decorate', ConnectedBroker, '_decorate'),
                                     ('broker.sidebar_observation', ConnectedBroker, 'sidebar_observation'),
                                     ('seen.baseline', SeenStore, 'baseline'),
                                     ('safety.observe_cached', SidebarSafetyObserver, 'observe_cached')]:
            setattr(owner, method, aggregate(name, getattr(owner, method)))
        original_dispatch = web_backend.FluxioWebBackend.dispatch
        @functools.wraps(original_dispatch)
        def dispatch(self, command, payload=None):
            if command == 'connected_sessions_list_command':
                try:
                    return trace('backend.connected_list', original_dispatch)(self, command, payload)
                finally:
                    with trace_lock, (args.root/'owner-phases.json').open('w', encoding='utf-8') as stream:
                        json.dump(totals, stream, indent=2)
            return original_dispatch(self, command, payload)
        web_backend.FluxioWebBackend.dispatch = dispatch
        neyvia_workspace_tools.workspace_for = trace('workspace_for', neyvia_workspace_tools.workspace_for)
    if os.environ.get('FIX_SIDEBAR_UI_PROFILE') == '1':
        import cProfile
        import time
        original_list = NeyviaAdapter.list_sessions
        def profiled_list(self, *positional, **named):
            profile = cProfile.Profile()
            try:
                return profile.runcall(original_list, self, *positional, **named)
            finally:
                profile.dump_stats(str(args.root / ('native-list-' + str(time.time_ns()) + '.prof')))
        NeyviaAdapter.list_sessions = profiled_list
    original = neyvia_ui_api.bind_backend
    def bind(backend):
        original(backend)
        broker = broker_for(args.root, backend)
        broker.registry._load_defaults = False
        broker.registry._adapters['neyvia'] = NeyviaAdapter(backend)
    neyvia_ui_api.bind_backend = bind
    if os.environ.get('FIX_SIDEBAR_UI_PROFILE') == '1':
        from grant_agent import web_backend
        import json
        original_factory = web_backend.make_handler
        def profiled_factory(backend):
            parent = original_factory(backend)
            class ProfiledHandler(parent):
                def do_POST(self):
                    if self.path != '/api/backend':
                        return super().do_POST()
                    profile = cProfile.Profile()
                    try:
                        return profile.runcall(super().do_POST)
                    finally:
                        profile.dump_stats(str(args.root / ('http-backend-' + str(time.time_ns()) + '.prof')))
            return ProfiledHandler
        web_backend.make_handler = profiled_factory
    if os.environ.get('FIX_SIDEBAR_UI_BODY_TIMING') == '1' or os.environ.get('FIX_SIDEBAR_UI_PROFILE') == '1':
        from grant_agent import web_backend
        import json
        import time
        import socket
        original_write = web_backend._write_response_body
        def timed_write(handler, body, **kwargs):
            no_delay = handler.connection.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
            started = time.perf_counter()
            try:
                return original_write(handler, body, **kwargs)
            finally:
                row = {'path': handler.path, 'bytes': len(body), 'noDelay': no_delay,
                       'writeMs': (time.perf_counter()-started)*1000}
                with (args.root / 'body-timings.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(row)+'\n')
        web_backend._write_response_body = timed_write
    sys.argv = ['run_web_backend.py', '--host', '127.0.0.1', '--port', str(args.port),
                '--root', str(args.root), '--static-root', str(args.static_root),
                '--skip-runtime-auto-update', '--skip-proof-self-check']
    runpy.run_path(str(REPO / 'scripts/run_web_backend.py'), run_name='__main__')
