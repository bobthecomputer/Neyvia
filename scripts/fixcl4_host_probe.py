"""Real managed hidden processes and an actual workspace-writing MCP plugin."""
from __future__ import annotations
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sys
import time
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def peer(port):
    if port not in {*range(48781, 48790), *range(48821, 48830)}:
        raise ValueError('Assigned explicit port required')
    class Page(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            raw = b'<title>FIXCL4 managed real process</title><p>Exact live owned bytes</p>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    HTTPServer(('127.0.0.1', port), Page).serve_forever()


def mcp(root):
    root = Path(root).resolve()
    for line in sys.stdin:
        request = json.loads(line)
        if 'id' not in request:
            continue
        method = request['method']
        if method == 'initialize':
            value = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'owned-byte-writer', 'version': '1'}}
        elif method == 'tools/list':
            value = {'tools': [{'name': 'write', 'description': 'Write exact bytes into this owned workspace', 'annotations': {'readOnlyHint': False}, 'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['path', 'content'], 'additionalProperties': False}}]}
        elif method == 'tools/call':
            args = request['params']['arguments']
            path = (root / args['path']).resolve()
            path.relative_to(root)
            path.write_text(args['content'], encoding='utf-8', newline='\n')
            value = {'content': [{'type': 'text', 'text': 'Written'}], 'isError': False}
        else:
            value = {}
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': value}), flush=True)


def manual():
    from grant_agent.native_tools import NativeToolRegistry
    from grant_agent.cl.manuals import manual_to_cl, cl_to_manual
    from grant_agent.cl.fixcl4_host_effects import SUPPORTED
    registry = NativeToolRegistry(REPO / '.agent_control/fixcl4-host-schema')
    schemas = {name: registry.describe(name)['inputSchema'] for name in sorted(SUPPORTED)}
    actions, procedures = {}, {}
    for name, schema in schemas.items():
        key = name.replace('.', '-')
        inputs = json.loads(json.dumps(schema))
        if name == 'codex.plugins.call':
            inputs['required'] = list(dict.fromkeys([*inputs['required'], 'effect']))
        actions[key] = {'tool': name, 'schema': name, 'returns': {'type': 'object'}, 'pre': 'Owned managed session or explicitly configured reviewed workspace plugin', 'effect': 'Fresh exact kernel process and owner state or independently observed requested file bytes', 'reversible': name != 'host.stop'}
        procedures[key] = {'goal': actions[key]['effect'], 'inputs': inputs, 'steps': [{'action': key, 'args': {field: {'$input': field} for field in inputs['properties']}, 'save': 'effect'}]}
    data = {'schema': 'neyvia.manual.v1', 'id': 'local-host', 'kind': 'workflow', 'schemas': schemas, 'chapters': {'host': {'title': 'Owned process and plugin effects', 'state': {}, 'checks': {}, 'judge': {}, 'guidance': ['Launch only approved headless programs for background journeys.'], 'pitfalls': [], 'frontier': ['A responding preview URL does not establish which process owns its socket.', 'Plugin effects are limited to the explicitly declared guarded file byte postcondition; other plugin effects stay unproven.'], 'actions': actions, 'procedures': procedures}}}
    source = manual_to_cl(data)
    if cl_to_manual(source) != data: raise ValueError('Manual roundtrip failed')
    (REPO / 'manuals/local-host.manual.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
    (REPO / 'manuals/cl/local-host.cl').write_text(source, encoding='utf-8', newline='\n')
    path = REPO / 'config/neyvia_manuals.json'
    index = json.loads(path.read_bytes())
    if not any(row['id'] == 'local-host' for row in index['manuals']):
        index['manuals'].append({'id': 'local-host', 'path': 'manuals/local-host.manual.json', 'clSource': 'manuals/cl/local-host.cl', 'description': 'Fresh owned managed-process and explicit plugin byte effects'})
        path.write_text(json.dumps(index, indent=2) + '\n', encoding='utf-8', newline='\n')


def run(port, output):
    if port not in {*range(48781, 48790), *range(48821, 48830)}: raise ValueError('Assigned explicit port required')
    from fixcl_verify import environment, bind_fixture_broker
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    root = REPO / '.agent_control/proofs' / ('FIXCL4-host-' + str(time.time_ns()))
    root.mkdir(parents=True)
    install(root); install_hidden_subprocess_default(); environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    prepare_broker_fixture(root); bind_fixture_broker(root)
    def guard(event, args):
        if event in {'socket.connect', 'socket.bind'} and isinstance(args[1], tuple):
            if args[1][0] not in {'127.0.0.1', 'localhost', '::1'} or args[1][1] != port:
                raise PermissionError('Owned host probe explicit port only')
    sys.addaudithook(guard)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol, unwrap
    from grant_agent.installed_programs import InstalledPrograms
    from grant_agent.ui_command_bus import bus_for
    from grant_agent.cl.fixcl4_host_effects import process_identity
    codex = root / 'codex-home'
    codex.mkdir()
    command = json.dumps(sys.executable.replace('\\', '/'))
    arguments = json.dumps([str(Path(__file__).resolve()).replace('\\', '/'), '--mcp-peer', str(root).replace('\\', '/')])
    (codex / 'config.toml').write_text('[mcp_servers.owned]\ncommand = ' + command + '\nargs = ' + arguments + '\n', encoding='utf-8')
    os.environ['CODEX_HOME'] = str(codex)
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace')
    owner = InstalledPrograms(root)
    proof = {'schema': 'neyvia.FIXCL4.host.v1', 'port': port, 'root': str(root), 'checks': {}, 'journeys': {}, 'boundary': 'Real hidden Python processes, fetched preview bytes and local filesystem-writing MCP peer; no arbitrary GUI or public plugin/account effects inferred.'}
    paths = [Path(__file__), REPO / 'src/grant_agent/cl/fixcl4_host_effects.py', REPO / 'src/grant_agent/installed_programs.py', REPO / 'src/grant_agent/native_tools.py', REPO / 'manuals/local-host.manual.json', REPO / 'manuals/cl/local-host.cl']
    hashes = lambda: {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    proof['sourceHashesAtStart'] = hashes()
    protocols = []
    def invoke(key, name, args, procedure=False):
        p = Protocol(gateway, lazy_manuals=True); protocols.append(p)
        call = ('run local-host.' + name.replace('.', '-')) if procedure else name
        observe = 'host.sessions()\n' if name in {'host.status', 'host.stop', 'host.inspect_preview'} else ''
        exposed_args = {k: v for k, v in args.items() if k != 'sessionId'}
        source = 'G: time.now()["unixSeconds"] > 0\n' + observe + call + '(' + ','.join(k + '=' + json.dumps(v) for k, v in exposed_args.items()) + ')\ndone()'
        result = p.run(source, action_id='fixcl4-host-' + key)
        proof['journeys'][key] = result
        proof['checks'][key + '-positiveCL'] = result.get('ok') is True
        proof['checks'][key + '-freshDone'] = p.completion().get('status') == 'completed'
        output.write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8', newline='\n')
        print(json.dumps({'case': key, 'ok': result.get('ok'), 'status': result.get('status')}), flush=True)
        return p, result
    sessions = []
    try:
        args = {'executable': sys.executable, 'arguments': [str(Path(__file__).resolve()), '--managed-peer', str(port)], 'timeoutSeconds': 120}
        p, result = invoke('launch', 'host.launch', args)
        sessions = [row['sessionId'] for row in owner.list_sessions()['sessions']]
        if len(sessions) != 1: raise RuntimeError('Expected one exact owned launched process')
        identity = sessions[0]
        live = owner.status(identity)
        proof['checks']['actualKernelProcessLive'] = process_identity(live.get('pid')) is not None
        invoke('preview', 'host.inspect_preview', {'sessionId': identity, 'url': f'http://127.0.0.1:{port}/'})
        invoke('stop', 'host.stop', {'sessionId': identity, 'expectedRevision': 0})
        proof['checks']['stoppedLaunchCannotComplete'] = p.completion().get('status') == 'incomplete'
        script = root / 'actual-work.py'
        script.write_text('from pathlib import Path\nPath(' + repr(str(root / 'actual-effect.txt')) + ').write_text("real launched file effect")\n', encoding='utf-8')
        p, result = invoke('launch-file', 'host.launch_file', {'path': str(script), 'arguments': [], 'timeoutSeconds': 60}, True)
        deadline = time.monotonic() + 12
        while not (root / 'actual-effect.txt').is_file() and time.monotonic() < deadline: time.sleep(.05)
        proof['checks']['launchedFileEffectBytes'] = (root / 'actual-effect.txt').is_file() and (root / 'actual-effect.txt').read_bytes() == b'real launched file effect'
        inventory = unwrap(gateway.native.call('codex.plugins.list', {}))
        server = inventory['servers'][0]['server']
        expected = hashlib.sha256(b'# Exact real MCP bytes').hexdigest()
        args = {'server': server, 'tool': 'write', 'arguments': {'path': 'plugin.txt', 'content': '# Exact real MCP bytes'}, 'effect': {'path': 'plugin.txt', 'sha256': expected}}
        p, result = invoke('plugin-write', 'codex.plugins.call', args, True)
        if not (root / 'plugin.txt').is_file():
            print(json.dumps({'pluginFailure': result}), flush=True)
            output.write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8', newline='\n')
            raise RuntimeError('Actual plugin did not produce its requested file; failure receipt preserved')
        proof['checks']['actualPluginBytes'] = (root / 'plugin.txt').read_bytes() == b'# Exact real MCP bytes'
        (root / 'plugin.txt').write_text('drift', encoding='utf-8')
        proof['checks']['pluginDriftRefused'] = p.completion().get('status') == 'incomplete'
        p, result = invoke('plugin-wrong-effect', 'codex.plugins.call', {**args, 'effect': {'path': 'plugin.txt', 'sha256': '0' * 64}})
        proof['checks']['plugin-wrong-effect-positiveCL'] = result.get('ok') is False
        proof['checks']['plugin-wrong-effect-freshDone'] = p.completion().get('status') == 'incomplete'
    finally:
        for row in owner.list_sessions()['sessions']:
            if row['status'] in {'queued', 'starting', 'running'}:
                owner.stop(row['sessionId'], expectedRevision=row['control']['revision'])
        if hasattr(gateway.native, '_codex_plugins'): gateway.native._codex_plugins.close()
    proof['manualReceipts'] = [row['payload'] for row in bus_for(root).since(0) if row['action'] == 'cl.manual.use']
    proof['sourceHashesAtEnd'] = hashes()
    proof['checks']['sourceUnchanged'] = proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
    proof['ok'] = all(proof['checks'].values())
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'ok': proof['ok'], 'checks': proof['checks'], 'receipt': str(output)}))
    return 0 if proof['ok'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int)
    parser.add_argument('--output', type=Path, default=REPO / 'scripts/evidence/FIXCL4-host.json')
    parser.add_argument('--write-manual', action='store_true')
    parser.add_argument('--managed-peer', type=int)
    parser.add_argument('--mcp-peer', type=Path)
    args = parser.parse_args()
    if args.managed_peer is not None: peer(args.managed_peer)
    elif args.mcp_peer is not None: mcp(args.mcp_peer)
    elif args.write_manual: manual()
    elif args.port is None: parser.error('--port is required')
    else: raise SystemExit(run(args.port, args.output))
