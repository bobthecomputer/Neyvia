"""Real FIXCL CL-host, HTTP/plugin and spawned stdio journeys on disposable state."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import runpy
import subprocess
import sys
import threading
import time
import traceback

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def guards(root):
    from grant_agent.proof_credential_guard import install
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(root)
    install_hidden_subprocess_default()
    def guard(event, args):
        if event in {'socket.connect', 'socket.bind'}:
            address = args[1]
            if isinstance(address, tuple) and (address[0] not in {'127.0.0.1', 'localhost', '::1'} or address[1] not in {*range(48781, 48790), *range(48821, 48830)}):
                raise PermissionError('FIXCL: assigned loopback ports only')
        if event == 'subprocess.Popen':
            command = args[1]
            text = command if isinstance(command, str) else subprocess.list2cmdline(command)
            if not any(marker in text for marker in ('fixcl_verify.py', 'import pypdf', 'git.exe --version', 'scripts/build_app_sdk_runtime.mjs')):
                raise PermissionError('FIXCL: refuses unowned application launches')
    sys.addaudithook(guard)


def environment(root, port):
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_RUNTIME_AUTO_UPDATE='0',
        PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
        NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0', NEYVIA_PROOF_CREDENTIAL_GUARD='1',
        FLUXIO_WORKSPACE_ROOT=str(root), NEYVIA_REMOTE_PROOF_PORTS=str(port),
        NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{port}')


def percentile(values, q):
    import math
    return sorted(values)[max(0, math.ceil(len(values)*q)-1)]


def source_hashes():
    paths = list((REPO/'src/grant_agent/cl').glob('*.py'))
    paths += [REPO/'scripts/fixcl_verify.py', REPO/'scripts/fixcl_effect_journeys.py',
              REPO/'src/grant_agent/neyvia_impact.py', REPO/'src/grant_agent/neyvia_agent.py',
              REPO/'src/grant_agent/neyvia_mcp_stdio.py', REPO/'src/grant_agent/app_sdk.py',
              REPO/'src/grant_agent/neyvia_app_sdk.py', REPO/'plugins/neyvia/mcp/neyvia_mcp.py']
    paths += [REPO/'src/grant_agent/web_backend.py', REPO/'src/grant_agent/harness_jobs.py',
              REPO/'src/grant_agent/connected_sessions/broker.py', REPO/'src/grant_agent/connected_sessions/runs.py']
    paths += list((REPO/'manuals/cl').glob('*.cl'))
    return {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def select_cases(cases, requested):
    if not requested:
        return cases
    selected = set(requested.split(','))
    known = {case['id'] for case in cases}
    if selected - known:
        raise ValueError('Unknown --only case IDs: ' + ', '.join(sorted(selected-known)))
    dependencies = {'files-move-undo': {'workspace-patch'}, 'artifact-publish': {'workspace-patch'},
                    'image-export': {'image-crop'}}
    for key in list(selected):
        selected.update(dependencies.get(key, set()))
    return [case for case in cases if case['id'] in selected]


def fixture_approval(root, expected, proof, prefix):
    from grant_agent.neyvia_workspace_tools import workspace_for
    service = workspace_for(root)
    with service.bus.connect() as db:
        pending = [(row['key'], json.loads(row['value'])) for row in db.execute(
            "SELECT key,value FROM state WHERE key LIKE 'approval:%'")]
    patch = expected.get('approvalPatch')
    if patch:
        exact = [(key, row) for key, row in pending if row.get('details') ==
                 {'patch':patch,'expectedRevision':expected['observedRevision']}]
    else:
        exact = [(key, row) for key, row in pending if row.get('details', {}).get('path') == expected['file']]
    if len(exact) != 1:
        raise RuntimeError('Exact disposable fixture approval missing')
    if patch:
        from grant_agent.neyvia_settings import get
        proof['checks'][prefix+'_settings_refused_before_approval'] = get(service) == expected['beforeSettings']
    else:
        proof['checks'][prefix+'_export_refused_before_approval'] = not Path(expected['file']).exists()
    proof.setdefault('fixtureApprovals', []).append({'transport': prefix, 'pending': exact[0][1],
        **({'exactPatch':patch,'exactRevision':expected['observedRevision']} if patch else {'exactPath':expected['file']})})
    service.approve(exact[0][0].split(':', 1)[1])


def case_lines(case, registry=None):
    # Work inventories share this root across transports. Bind the G to this
    # case's actual files rather than asserting a global singleton board.
    if case['expected'].get('frontier'):
        from grant_agent.neyvia_manuals import unwrap
        case['expected']['setupBefore'] = unwrap(registry.call('neyvia.settings.get', {}))['setup']
        case['expected']['setupOpenEventsBefore'] = setup_open_count(registry.root)
    if case['id'] == 'work-claim':
        return case['lines'].replace('work.list()["count"]',
            'work.list(files='+json.dumps(case['expected']['files'])+')["count"]')
    if 'OBSERVED_REVISION' in case['lines']:
        from grant_agent.neyvia_manuals import unwrap
        observed = unwrap(registry.call('neyvia.settings.get', {}))
        case['expected']['beforeSettings'] = {key:observed[key] for key in ('revision','settings','network','setup')}
        case['expected']['observedRevision'] = observed['revision']
        return case['lines'].replace('OBSERVED_REVISION', str(observed['revision']))
    return case['lines']


def setup_open_count(root):
    from grant_agent.ui_command_bus import bus_for
    with bus_for(root).connect() as db:
        return db.execute("SELECT count(*) FROM events WHERE action='setup.open'").fetchone()[0]


def continuation(case, registry):
    if not case['expected'].get('releaseClaimFor'):
        return None
    from grant_agent.neyvia_manuals import unwrap
    claims = unwrap(registry.call('neyvia.work.list', {'files':case['expected']['releaseClaimFor']}))['claims']
    if len(claims) != 1:
        raise RuntimeError('Fresh release fixture claim is not unique')
    case['expected']['releasedClaimId'] = claims[0]['id']
    return 'work.release(id='+json.dumps(claims[0]['id'])+')\ndone()'


def bind_fixture_broker(root):
    """Bind the actual local backend; construct no listener or provider run."""
    from grant_agent.web_backend import FluxioWebBackend
    from grant_agent.neyvia_workspace_tools import workspace_for
    backend = FluxioWebBackend(root, root/'static')
    workspace_for(root, backend)
    return backend


def prepare_case(case, root, proof, registry):
    identity = case['expected'].get('queuedRunFixture')
    if identity:
        from grant_agent.connected_sessions.runs import iso
        from grant_agent.neyvia_workspace_tools import workspace_for
        bind_fixture_broker(root)
        broker = workspace_for(root).broker()
        value = {'runId':identity,'app':'codex','state':'queued','startedAt':iso(time.time()),
                 'updatedAt':iso(time.time()),'permissionMode':'read-only','promptCharacters':0}
        # Use the actual durable admission API. No worker is registered, so
        # ordinary recovery truthfully marks the retained run interrupted.
        broker.store.claim(value, hashlib.sha256(identity.encode()).hexdigest(), None,
            is_free=lambda _:True, register=lambda:None, unregister=lambda:None)
        observed = broker.get_run(identity)
        proof.setdefault('fixtureSetup', []).append({'case':case['id'],'actualStoredAdmission':value,
            'freshBrokerRead':observed,'boundary':'actual RunStore admission and no-worker recovery only; no provider execution or completion claimed'})


def typed_projection(text):
    """Inspect actual wire rows: each E value is a scalar or stable ref."""
    decoder = json.JSONDecoder()
    rows = [line for line in text.splitlines() if line.startswith('E ')]
    if not rows or not any(line.startswith('S ') and '[type ref parent field value]' in line
                           for line in text.splitlines()):
        return False
    for row in rows:
        tokens = row.split(' ', 4)
        if len(tokens) != 5 or tokens[1].startswith('generic'):
            return False
        try:
            field, end = decoder.raw_decode(tokens[4])
            cell = tokens[4][end:].strip()
            if not isinstance(field, str) or not cell:
                return False
            try:
                value, end = decoder.raw_decode(cell)
                if cell[end:].strip() or isinstance(value, (dict, list)):
                    return False
            except ValueError:
                # Semantic cells may refer to another typed row.
                if not cell[0].isalpha() or not cell[1:].isdigit():
                    return False
        except ValueError:
            return False
    return True


def manual_uses(root):
    from grant_agent.ui_command_bus import bus_for
    cursor, uses = 0, []
    for _ in range(20):
        page = bus_for(root).since(cursor)
        uses.extend(event['payload'] for event in page if event['action'] == 'cl.manual.use')
        if len(page) < 200:
            return uses
        cursor = int(page[-1]['id'])
    raise RuntimeError('Fixture manual-use event inventory exceeds 4000 events')


def case_passed(value, expected, registry):
    from grant_agent.neyvia_manuals import unwrap
    if expected.get('frontier'):
        return (expected.get('frontierObserved') is True
            and value.get('ok') is False and value.get('doneStatus') == 'refused'
            and setup_open_count(registry.root) == expected['setupOpenEventsBefore']
            and unwrap(registry.call('neyvia.settings.get', {}))['setup'] == expected['setupBefore'])
    if value.get('ok') is not True or value.get('doneStatus') != 'ok' or not typed_projection(value.get('text', '')):
        return False
    if any('R '+name+' ok +G' not in value['text'] for name in expected.get('compiledProcedures', [])):
        return False
    if expected.get('manualOwner'):
        direct = next((row for row in value['results'] if row.get('name') == 'workspace.patch'), {})
        identity = direct.get('manualUse', {}).get('actionIdentity', '').rsplit(':',1)[0]
        uses = [row for row in manual_uses(registry.root) if row.get('tool') == 'workspace.patch'
                and row.get('actionIdentity', '').startswith(identity+':')]
        if not identity or len(uses) != 2 or any(row['manual'] != expected['manualOwner'] for row in uses):
            return False
        if 'R tools-depth.verify-effect-workspace-patch ok +G' not in value['text']:
            return False
    if expected.get('file') and 'bytes' in expected:
        if Path(expected['file']).read_bytes() != expected['bytes'].encode():
            return False
    if expected.get('absent') and Path(expected['absent']).exists():
        return False
    if any(Path(path).read_bytes() != content.encode() for path,content in expected.get('filesBytes', {}).items()):
        return False
    if expected.get('notesFolder') and unwrap(registry.call('neyvia.notes.folder', {}))['folder'] != expected['notesFolder']:
        return False
    if expected.get('source') and hashlib.sha256(Path(expected['source']).read_bytes()).hexdigest() != expected['sourceSha256']:
        return False
    if expected.get('dimensions'):
        asset = unwrap(registry.call('neyvia.image.state', {}))['requested']
        if [asset['dimensions']['width'], asset['dimensions']['height']] != expected['dimensions']:
            return False
    if expected.get('exactCurrentImageBytes'):
        asset = unwrap(registry.call('neyvia.image.state', {}))['requested']
        if Path(expected['file']).read_bytes() != Path(asset['path']).read_bytes():
            return False
    if expected.get('compositeEdit'):
        from PIL import Image, ImageChops
        asset = unwrap(registry.call('neyvia.image.state', {}))['requested']
        with Image.open(expected['source']) as source, Image.open(expected['compositeEdit']) as edit, Image.open(asset['path']) as actual:
            intended = source.resize(tuple(expected['dimensions']), Image.Resampling.LANCZOS).convert('RGBA')
            region = expected['compositeRegion']
            box = (region['x'],region['y'],region['x']+region['width'],region['y']+region['height'])
            intended.paste(edit.convert('RGBA').crop(box), box)
            if ImageChops.difference(actual.convert('RGBA'), intended).getbbox(alpha_only=False) is not None:
                return False
    if 'density' in expected or 'settingsPatch' in expected:
        settings = unwrap(registry.call('neyvia.settings.get', {}))['settings']
        if any(settings.get(key) != value for key,value in expected.get('settingsPatch', {}).items()):
            return False
        if expected.get('density') and settings['density'] != expected['density']:
            return False
    if expected.get('transparency') and unwrap(registry.call('neyvia.view.transparency.state', {}))['transparency'] != expected['transparency']:
        return False
    if 'ambient' in expected:
        from grant_agent.ui_command_bus import bus_for
        if bus_for(registry.root).get('ambient') is not expected['ambient']:
            return False
    if expected.get('releasedClaimId'):
        work = unwrap(registry.call('neyvia.work.list', {}))
        identity = expected['releasedClaimId']
        if any(row['id'] == identity for row in work['claims']) or not any(row['id'] == identity for row in work['recentlyReleased']):
            return False
    if expected.get('watch'):
        watches = unwrap(registry.call('neyvia.watch.list', {'limit':100}))['watches']
        schedules = unwrap(registry.call('neyvia.schedule.list', {}))['schedules']
        if not any(row['id'] == expected['watch'] and row['status'] == 'cancelled' and row['runId'] == expected['queuedRunFixture'] for row in watches):
            return False
        if not any(row['id'] == expected['schedule'] and row['status'] == 'cancelled' and row['when'] == expected['when'] for row in schedules):
            return False
    if expected.get('verifyBuildArtifactSha256'):
        described = unwrap(registry.call('neyvia.app_sdk.describe', {'project': expected['project']}))
        built = described['receipts']['build']
        if hashlib.sha256(Path(built['artifact']).read_bytes()).hexdigest() != built['artifactSha256']:
            return False
    return True


def spawned_case(root, port, case, proof, capture, registry):
    """One real stdio process owns one task; approval retries retain that process."""
    log = root/('stdio-'+case['id']+'.log')
    responses = queue.Queue()
    child = None
    requests = []
    answers = []
    def rpc(method, params):
        request = {'jsonrpc': '2.0', 'id': len(requests)+1, 'method': method, 'params': params}
        requests.append(request)
        child.stdin.write(json.dumps(request)+'\n')
        child.stdin.flush()
        line = responses.get(timeout=60)
        if line is None:
            raise RuntimeError('MCP child closed stdout before responding')
        answer = json.loads(line)
        if answer.get('id') != request['id'] or answer.get('jsonrpc') != '2.0':
            raise RuntimeError('MCP response identity/protocol mismatch')
        answers.append(answer)
        return answer
    with log.open('w', encoding='utf-8') as errors:
        try:
            command = [sys.executable, str(Path(__file__).resolve()), '--stdio', '--layers',
                '--port', str(port), '--root', str(root)]
            if case['expected'].get('queuedRunFixture'):
                command.append('--fixture-broker')
            child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=errors, text=True, encoding='utf-8', bufsize=1)
            def read_stdout():
                for line in child.stdout:
                    responses.put(line)
                responses.put(None)
            threading.Thread(target=read_stdout, daemon=True).start()
            initialized = rpc('initialize', {})
            catalog = rpc('tools/list', {})
            arguments = {'lines': case_lines(case, registry), 'actionId': 'mcp-fixture-'+case['id']}
            call = lambda: rpc('tools/call', {'name': 'neyvia.cl', 'arguments': arguments})
            response = capture('mcp_layer_'+case['id'], call)
            value = response.get('result', {}).get('structuredContent', {})
            if case['expected'].get('frontier'):
                case['expected']['frontierObserved'] = (value.get('ok') is False
                    and value.get('status') == 'frontier' and response.get('result', {}).get('isError') is True)
                arguments = {'lines':'done()', 'actionId':'mcp-fixture-'+case['id']}
                response = capture('mcp_layer_'+case['id']+'_done_refused', call)
                value = response.get('result', {}).get('structuredContent', {})
            if value.get('status') == 'ask' and case['expected'].get('requiresFixtureApproval'):
                fixture_approval(root, case['expected'], proof, 'mcp')
                response = capture('mcp_layer_'+case['id']+'_approved', call)
                value = response.get('result', {}).get('structuredContent', {})
            if value.get('ok') is True and case['expected'].get('releaseClaimFor'):
                arguments = {'lines':continuation(case,registry),'actionId':'mcp-fixture-'+case['id']+'-release'}
                response = capture('mcp_layer_'+case['id']+'_release', call)
                value = response.get('result', {}).get('structuredContent', {})
            child.stdin.close()
            child.wait(timeout=10)
            passed = child.returncode == 0 and 'result' in initialized and 'result' in catalog
            result_error = response.get('result', {}).get('isError')
            passed = passed and (result_error is True if case['expected'].get('frontier') else result_error is not True)
            return passed and case_passed(value, case['expected'], registry)
        finally:
            if child and child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            proof.setdefault('spawnedMCP', {})[case['id']] = {'pid': child.pid if child else None,
                'exitCode': child.returncode if child else None, 'requests': requests, 'responses': answers,
                'stderr': log.read_text(encoding='utf-8')[-4000:]}


def read_transports(root, port, proof, capture, registry):
    """Authenticated HTTP/plugin observations preserve the existing read grant."""
    from grant_agent.neyvia_manuals import unwrap
    spec = importlib.util.spec_from_file_location('fixcl_plugin_layers', REPO/'plugins/neyvia/mcp/neyvia_mcp.py')
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    backend = plugin.Backend(f'http://127.0.0.1:{port}')
    proc = None
    log = root/'transports-backend.log'
    try:
        with log.open('w', encoding='utf-8') as stream:
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--backend',
                '--port', str(port), '--root', str(root)], stdout=stream, stderr=subprocess.STDOUT)
        for _ in range(50):
            if proc.poll() is not None:
                break
            try:
                if backend.request('/api/health', timeout=2).get('ok'):
                    break
            except OSError:
                time.sleep(.3)
        health = capture('transports_http_health', lambda: backend.request('/api/health', timeout=3))
        proof['checks']['transports_http_health'] = health.get('ok') is True
        server = plugin.Server(backend)
        catalog = capture('transports_plugin_catalog', lambda: server.handle(
            {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}))
        proof['checks']['transports_plugin_catalog'] = bool(catalog.get('result', {}).get('tools'))
        observations = {'time': 'time.now()', 'settings': 'settings.get()', 'pdf': 'pdf.state()',
            'image': 'image.state()', 'artifact': 'artifact.list()', 'timer': 'timer.list()',
            'schedule': 'schedule.list()', 'watch': 'watch.list()', 'work': 'work.list()'}
        for family, lines in observations.items():
            response = capture('transports_plugin_'+family, lambda lines=lines: server.handle({
                'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'cl', 'arguments': {'lines': lines}}}))
            body = response.get('result', {})
            proof['checks']['plugin_read_'+family] = bool(body.get('content')) and body.get('isError') is not True and not response.get('error')
            wire = '\n'.join(row.get('text', '') for row in body.get('content', []) if row.get('type') == 'text')
            proof['checks']['plugin_typed_'+family] = typed_projection(wire)
            answer = capture('transports_http_'+family, lambda lines=lines: backend.request('/api/ui/tools/call',
                {'tool': 'neyvia.cl', 'arguments': {'lines': lines}}, timeout=30))
            value = answer.get('data', {}).get('result', {})
            proof['checks']['http_read_'+family] = value.get('ok') is True
            proof['checks']['http_typed_'+family] = typed_projection(value.get('text', ''))
        before = unwrap(registry.call('neyvia.settings.get', {}))['settings']
        paths = {
            'false_goal': 'G: time.now()["unixSeconds"] < 0\ndone()',
            'gated_mutation': 'G: time.now()["unixSeconds"] > 0\nview.theme(theme="night")\ndone()',
        }
        for key, lines in paths.items():
            response = capture('transports_plugin_'+key, lambda lines=lines: server.handle({
                'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'cl', 'arguments': {'lines': lines}}}))
            proof['checks']['plugin_'+key+'_refused'] = response.get('result', {}).get('isError') is True
            answer = capture('transports_http_'+key, lambda lines=lines: backend.request('/api/ui/tools/call',
                {'tool': 'neyvia.cl', 'arguments': {'lines': lines}}, timeout=30))
            value = answer.get('data', {}).get('result', {})
            proof['checks']['http_'+key+'_refused'] = value.get('ok') is False and value.get('status') in {'ask', 'refused', 'frontier'}
        scope = capture('transports_plugin_scope_denied', lambda: server.call('cl', {
            'lines': 'workspace.read(path="notes/audit.md")'}))
        proof['checks']['plugin_scope_preserved'] = scope.get('isError') is True
        after = unwrap(registry.call('neyvia.settings.get', {}))['settings']
        proof['checks']['http_plugin_mutation_grant_preserved'] = after == before
        proof['limitations'].append('HTTP/plugin exercised actual read observations and refusals; existing read-only authority was not widened to replay mutations.')
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=15)
        proof['transportsBackendStopped'] = bool(proc and proc.poll() is not None)
        proof['transportsBackendLog'] = log.read_text(encoding='utf-8')[-5000:] if log.exists() else ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--backend', action='store_true')
    parser.add_argument('--stdio', action='store_true')
    parser.add_argument('--fixture-broker', action='store_true', help='Bind actual local backend for retained watch fixtures')
    parser.add_argument('--layers', action='store_true')
    parser.add_argument('--only', help='Comma-separated independent layer case IDs')
    parser.add_argument('--phase', default='integration')
    parser.add_argument('--samples', type=int, default=5)
    args = parser.parse_args()
    if args.port not in range(48821,48830): parser.error('Assigned ports only')
    if args.only and not args.layers: parser.error('--only requires --layers')
    root = (args.root or REPO/'.agent_control/proofs'/('FIXCL-'+str(time.time_ns()))).resolve()
    if not root.is_relative_to(REPO/'.agent_control/proofs'): parser.error('Disposable root required')
    root.mkdir(parents=True,exist_ok=True)
    guards(root)
    environment(root,args.port)
    if args.backend:
        sys.argv = [str(REPO/'scripts/run_web_backend.py'),'--host','127.0.0.1','--port',str(args.port),
            '--root',str(root),'--static-root',str(root/'static'),'--skip-runtime-auto-update','--skip-proof-self-check']
        runpy.run_path(str(REPO/'scripts/run_web_backend.py'),run_name='__main__')
        return 0
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    if not args.stdio:
        prepare_broker_fixture(root)
    if args.stdio:
        os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
        if args.fixture_broker:
            bind_fixture_broker(root)
        from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
        server = CompactNeyviaMCPServer(root,session_id='FIXCL-stdio',permission_mode='workspace',
            native_mutation_tools=None if args.layers else ['neyvia.notes.write','neyvia.notes.pin'])
        if args.layers:
            # This controlled child is explicitly granted the same exact owned
            # fixture actions as the parent, never terminal/browser/provider use.
            from grant_agent.cl.effects import SUPPORTED
            server.native_mutation_tools = set(SUPPORTED)
        for line in sys.stdin:
            try: response = server.handle(json.loads(line))
            except Exception as exc: response = {'error':str(exc)}
            print(json.dumps(response,ensure_ascii=False),flush=True)
        return 0
    os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
    dest = REPO/'scripts/evidence'
    dest.mkdir(exist_ok=True)
    proof = {'schema':'neyvia.FIXCL.v1','phase':args.phase,'root':str(root),'port':args.port,
        'transcripts':{},'checks':{},'limitations':[], 'startedUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'sourceHashesAtStart': source_hashes()}
    output = dest/('FIXCL-'+args.phase+'.json')
    def save(): output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    def capture(key,fn):
        started=time.perf_counter()
        try: value=fn()
        except Exception as exc: value={'error':str(exc),'trace':traceback.format_exc(limit=4)}
        proof['transcripts'][key]={'elapsedMs':round((time.perf_counter()-started)*1000,3),'value':value}
        save()
        print(json.dumps({'key':key,'elapsedMs':proof['transcripts'][key]['elapsedMs'],'ok':value.get('ok') if isinstance(value,dict) else None}),flush=True)
        return value
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.neyvia_manuals import unwrap
    from grant_agent.ui_command_bus import bus_for
    gateway=NeyviaToolGateway(root,allow_mutations=True,action_scope='FIXCL-host',permission_mode='workspace')
    registry=gateway.native
    notes=root/'notes'
    registry.call('neyvia.notes.folder',{'folder':str(notes)})
    registry.call('neyvia.notes.write',{'path':'audit.md','body':'FIXCL original\n'})
    # Protocol objects are runtime state, not JSON receipts.
    started=time.perf_counter(); protocol=Protocol(gateway)
    proof['transcripts']['host_admission']={'elapsedMs':round((time.perf_counter()-started)*1000,3),'value':{'ok':True,'contracts':len(protocol.contracts)}}
    if not isinstance(protocol,Protocol): return 1
    def cl(lines): return protocol.run(lines)
    if args.layers:
        from fixcl_effect_journeys import journeys, supplemental_journeys
        def matrix(suffix):
            rows = journeys(root, suffix)
            if args.only:
                rows += supplemental_journeys(root, suffix)
            return select_cases(rows, args.only)
        try:
            cases=matrix('-native')
        except ValueError as exc:
            parser.error(str(exc))
        proof['selectedCases'] = [case['id'] for case in cases]
        # Each task has independent goals; its native data persists for later
        # conservation checks, while a prior task's G cannot authorize this one.
        for case in cases:
            prepare_case(case, root, proof, registry)
            protocol=Protocol(gateway)
            original_action=protocol.host._action
            def traced_action(*values, **options):
                try: return original_action(*values, **options)
                except Exception:
                    proof.setdefault('actionErrors',[]).append({'case':case['id'],'trace':traceback.format_exc(limit=14)})
                    raise
            protocol.host._action=traced_action
            source = case_lines(case, registry)
            value=capture('layer_'+case['id'],lambda case=case:protocol.run(source,action_id='fixture-'+case['id']))
            expected=case['expected']
            if expected.get('frontier'):
                expected['frontierObserved'] = value.get('ok') is False and value.get('status') == 'frontier'
                value=capture('layer_'+case['id']+'_done_refused',lambda:protocol.run('done()',action_id='fixture-'+case['id']))
            if value.get('status') == 'ask' and expected.get('requiresFixtureApproval'):
                fixture_approval(root, expected, proof, 'native')
                value=capture('layer_'+case['id']+'_approved',lambda case=case:protocol.run(source,action_id='fixture-'+case['id']))
            if value.get('ok') is True and expected.get('releaseClaimFor'):
                source = continuation(case, registry)
                value=capture('layer_'+case['id']+'_release',lambda:protocol.run(source,action_id='fixture-'+case['id']+'-release'))
            proof['checks'][case['id']]=case_passed(value, expected, registry)
        for case in matrix('-mcp'):
            try:
                prepare_case(case, root, proof, registry)
                proof['checks']['spawned_mcp_'+case['id']] = spawned_case(root, args.port, case, proof, capture, registry)
            except Exception as exc:
                proof['checks']['spawned_mcp_'+case['id']] = False
                proof['limitations'].append({'mcpCase':case['id'], 'error':str(exc), 'trace':traceback.format_exc(limit=5)})
            save()
        read_transports(root, args.port, proof, capture, registry)
        from grant_agent.cl.effects import inventory
        proof['effectInventory'] = inventory(protocol)
        proof['inventoryBoundary'] = 'Current registered action classification; introspection is not execution proof'
        proof['manualUses'] = manual_uses(root)
        mutations = [row for row in proof['manualUses'] if row.get('effectChecks')]
        effect_hash = hashlib.sha256((REPO/'src/grant_agent/cl/effects.py').read_bytes()).hexdigest()
        proof['checks']['mutation_manual_uses_bound'] = bool(mutations) and all(
            row.get('procedure') and row.get('actionIdentity') and row.get('effectSourceSha256') == effect_hash
            and hashlib.sha256((REPO/row['source']).read_bytes()).hexdigest() == row.get('sourceSha256')
            and all(check['name'] in row.get('checkIds', []) for check in row['effectChecks']) for row in mutations)
        proof['checks']['owning_manual_sources_current'] = bool(mutations) and all(
            row.get('owningManual') and hashlib.sha256((REPO/row['owningManual']['source']).read_bytes()).hexdigest()
            == row['owningManual']['sourceSha256'] for row in mutations)
        proof['limitations'].append('Renderer-dependent SDK action and Windows Recycle Bin trash/restore were not exercised in these supplemental fixtures.')
        proof['sourceHashesAtEnd'] = source_hashes()
        proof['checks']['sources_unchanged_during_run'] = proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
        save()
        print(json.dumps({'receipt':str(output),'checks':proof['checks']}),flush=True)
        return 0 if all(proof['checks'].values()) else 1
    capture('cl_notes_read',lambda:cl('notes.read(path="audit.md")'))
    body='FIXCL checked\n'
    lines='G: notes.read(path="audit.md").body == "FIXCL checked\\n" and notes.read(path="audit.md").pinned == True\nrun notes.write-and-pin(path="audit.md", body="FIXCL checked\\n", replace_note="replace")\ndone()'
    procedure=capture('cl_notes_procedure',lambda:cl(lines))
    readback=capture('notes_independent_readback',lambda:registry.call('neyvia.notes.read',{'path':'audit.md'}))
    proof['checks']['notes_body_pin_raw_bytes']=procedure.get('ok') is True and unwrap(readback).get('pinned') is True and (notes/'audit.md').read_bytes()==body.encode()
    uses=[e for e in bus_for(root).since(0) if e['action']=='cl.manual.use']
    proof['manualUses']=uses
    proof['checks']['manual_use_bound']=bool(uses) and all(e['payload'].get('sourceSha256') and e['payload'].get('action') for e in uses)
    capture('cl_false_goal',lambda:cl('G: notes.read(path="audit.md").body == "wrong"\ndone()'))
    stale=capture('notes_stale_write',lambda:registry.call('neyvia.notes.write',{'path':'audit.md','body':'wrong','expectedModified':'stale'}))
    proof['checks']['stale_preserves_bytes']=stale.get('status')=='conflict' and (notes/'audit.md').read_bytes()==body.encode()
    for key,source in {'files':'files.list(path='+json.dumps(str(notes))+')','workspace':'workspace.read(path="notes/audit.md")',
        'settings':'settings.get()','pdf':'pdf.state()','image':'image.state()','artifacts':'artifact.list()',
        'agents':'agents.state()','perception_file':'perception.observe(layer="file", source={"path":"notes/audit.md"})',
        'mobile':'mobile.status(project='+json.dumps(str(root))+')','gamedev':'gamedev.status()'}.items():
        capture('cl_'+key,lambda source=source:cl(source))
    # Fresh protocol samples retain source validation, authorization and observers;
    # warm samples reuse that same live protocol, never cached action identities.
    cold=[]; warm=[]
    protocol=Protocol(gateway)
    for n in range(args.samples):
        started=time.perf_counter()
        current=Protocol(gateway)
        value=current.run(lines,action_id='cold-'+str(n))
        cold.append(round((time.perf_counter()-started)*1000,3))
        if not value['ok']: proof['limitations'].append({'coldFailed':n,'value':value})
    for n in range(args.samples*2):
        started=time.perf_counter(); value=cl(lines); warm.append(round((time.perf_counter()-started)*1000,3))
        if not value['ok']: proof['limitations'].append({'warmFailed':n,'value':value})
    proof['latency']={key:{'samplesMs':values,'n':len(values),'p50Ms':percentile(values,.5),'p95Ms':percentile(values,.95)} for key,values in [('coldProtocol',cold),('warmProtocol',warm)]}
    # Spawn an actual line-delimited JSON-RPC MCP child; stdout is the transport.
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--stdio','--port',str(args.port),'--root',str(root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    try:
        requests=[{'jsonrpc':'2.0','id':n,'method':method,'params':params} for n,(method,params) in enumerate([
            ('initialize',{}),('tools/list',{}),('tools/call',{'name':'neyvia.cl','arguments':{'lines':lines}})],1)]
        stdout,stderr=child.communicate('\n'.join(json.dumps(x) for x in requests)+'\n',timeout=120)
        responses=[json.loads(line) for line in stdout.splitlines()]
        proof['stdio']={'exitCode':child.returncode,'responses':responses,'stderr':stderr[-4000:]}
        useful=responses[-1].get('result',{}) if responses else {}
        proof['checks']['spawned_stdio']=child.returncode==0 and len(responses)==3 and useful.get('structuredContent',{}).get('ok') is True and useful.get('isError') is not True
    finally:
        if child.poll() is None: child.terminate(); child.wait(timeout=10)
    spec=importlib.util.spec_from_file_location('fixcl_plugin',REPO/'plugins/neyvia/mcp/neyvia_mcp.py')
    plugin=importlib.util.module_from_spec(spec); spec.loader.exec_module(plugin)
    backend=plugin.Backend(f'http://127.0.0.1:{args.port}')
    proc=None; log=root/'backend.log'
    try:
        with log.open('w',encoding='utf-8') as stream:
            proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--backend','--port',str(args.port),'--root',str(root)],stdout=stream,stderr=subprocess.STDOUT)
        for _ in range(50):
            if proc.poll() is not None: break
            try:
                if backend.request('/api/health',timeout=2).get('ok'): break
            except OSError: time.sleep(.3)
        capture('http_health',lambda:backend.request('/api/health',timeout=3))
        server=plugin.Server(backend)
        capture('plugin_catalog',lambda:server.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'}))
        for key,source in [('time','time.now()'),('settings','settings.get()'),('pdf','pdf.state()'),('image','image.state()'),('artifacts','artifact.list()')]:
            capture('plugin_cl_'+key,lambda source=source:server.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'cl','arguments':{'lines':source}}}))
        capture('plugin_scope_denied',lambda:server.call('cl',{'lines':'workspace.read(path="notes/audit.md")'}))
        capture('http_cl_notes_procedure',lambda:backend.request('/api/ui/tools/call',{'tool':'neyvia.cl','arguments':{'lines':lines}},timeout=60))
        capture('http_false_goal',lambda:backend.request('/api/ui/tools/call',{'tool':'neyvia.cl','arguments':{'lines':'G: notes.read(path="audit.md").body == "wrong"\ndone()'}},timeout=15))
    finally:
        if proc and proc.poll() is None: proc.terminate(); proc.wait(timeout=15)
        proof['backendStopped']=bool(proc and proc.poll() is not None)
        proof['backendLog']=log.read_text(encoding='utf-8')[-5000:] if log.exists() else ''
    proof['sourceHashes']=source_hashes()
    proof['checks']['sources_unchanged_during_run'] = proof['sourceHashesAtStart'] == proof['sourceHashes']
    save()
    print(json.dumps({'receipt':str(output),'checks':proof['checks'],'latency':proof['latency'],'limitations':len(proof['limitations'])}),flush=True)
    return 0 if all(proof['checks'].values()) else 1


if __name__=='__main__': raise SystemExit(main())
