"""Real service observations and native contracts, confined to FIXCL ports."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from fixcl_verify import REPO, environment, bind_fixture_broker
from fixcl4_service_source_hashes import service_source_hashes


def run(port, native=True):
    source_start = service_source_hashes()
    if port not in range(48821, 48830):
        raise ValueError('Assigned FIXCL ports only')
    root = REPO / '.agent_control/proofs' / ('FIXCL4-services-' + str(time.time_ns()))
    root.mkdir(parents=True)
    environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    os.environ['NEYVIA_WEB_PORT'] = str(port)
    os.environ['NEYVIA_NETWORK_CHECK_PORT'] = str(port)
    os.environ['NEYVIA_GAMEDEV_WS_PORT'] = str(port + 1 if port < 48829 else port)
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(root)
    install_hidden_subprocess_default()
    def socket_guard(event, args):
        if event in {'socket.connect', 'socket.bind'}:
            address = args[1]
            if isinstance(address, tuple) and (address[0] not in {'127.0.0.1', 'localhost', '::1'} or address[1] not in range(48821, 48830)):
                # Network refusal proof never reaches this hook: policy must deny
                # first. A escaped outbound attempt is a proof failure.
                raise PermissionError('FIXCL4 service proof: assigned loopback ports only')
    sys.addaudithook(socket_guard)
    from grant_agent.proof_ports import INT3_PORT_MAP, PORT_ENV, ALLOWED_ENV
    roles = {48652:48821,48654:48822,48655:48823,48656:48824,48657:48828,48658:48827}
    mapping = {str(key):roles[value] for key,value in INT3_PORT_MAP.items()}
    mapping['48497'] = port
    os.environ.update({PORT_ENV:json.dumps(mapping),
                       ALLOWED_ENV:json.dumps(list(range(48821,48830)))})
    prepare_broker_fixture(root)
    bind_fixture_broker(root)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.neyvia_manuals import unwrap
    from grant_agent.neyvia_workspace_tools import workspace_for
    gateway = NeyviaToolGateway(root, allow_mutations=True, action_scope='FIXCL4-services', permission_mode='workspace')
    service = workspace_for(root)
    result = {'schema':'neyvia.FIXCL4.services.v1','root':str(root),'journeys':{},'checks':{},'boundaries':[]}
    def action(key, name, args, goal):
        p = Protocol(gateway, lazy_manuals=True)
        text = 'G: ' + goal + '\n' + name + '(' + ','.join(k+'='+json.dumps(v) for k,v in args.items()) + ')\ndone()'
        observed = p.run(text, action_id=key)
        result['journeys'][key] = observed
        result['checks'][key] = bool(observed['ok'] and p.completion()['status']=='completed')
        return p
    setup = action('setup-reenter','settings.setup',{},'settings.get()["setup"]["requestedAt"] != ""')
    service.bus.put('settings.setup', {'requestedAt':'changed'})
    result['checks']['setup-drift-refuses'] = setup.completion()['status']=='incomplete'
    action('gamedev-sessions','gamedev.sessions',{},'gamedev.sessions()["sessions"] == []')
    asset = root/'valid.gltf'
    asset.write_text(json.dumps({'asset':{'version':'2.0'},'nodes':[{'name':'actual-node'}],'scenes':[{'nodes':[0]}],'scene':0}), encoding='utf-8')
    action('gltf-khronos-validation','gamedev.asset_validate',{'path':str(asset)},'gamedev.asset_validate(path='+json.dumps(str(asset))+')["valid"] == true')
    from grant_agent import neyvia_gamedev
    result['checks']['fresh-gamedev-observers-no-directory-or-owner'] = not (root/'.neyvia/gamedev').exists() and str(root) not in neyvia_gamedev._services
    # This is explicitly persisted bridge state for the adverse restart path,
    # not a native editor or a simulated successful engine operation.
    import sqlite3
    saved = root/'.neyvia/gamedev/bridges.sqlite3'
    saved.parent.mkdir(parents=True)
    with sqlite3.connect(saved) as db:
        db.executescript('CREATE TABLE sessions(id TEXT PRIMARY KEY,data TEXT,token TEXT,last REAL); CREATE TABLE requests(id TEXT PRIMARY KEY,fingerprint TEXT,data TEXT);')
        db.execute('INSERT INTO sessions VALUES(?,?,?,?)', ('retained-session',json.dumps({'id':'retained-session','engine':'godot','projectPath':str(root),'context':'Edit','requiresInspection':False}), 'synthetic-capability',time.time()))
        db.execute('INSERT INTO requests VALUES(?,?,?)', ('pending-adverse', 'synthetic',json.dumps({'requestId':'pending-adverse','status':'queued'})))
    saved_hash = hashlib.sha256(saved.read_bytes()).hexdigest()
    action('gamedev-retained-sessions-read-only','gamedev.sessions',{},'gamedev.sessions()["sessions"][0]["status"] == "disconnected"')
    result['checks']['retained-bridge-db-and-queued-request-conserved'] = saved_hash == hashlib.sha256(saved.read_bytes()).hexdigest() and str(root) not in neyvia_gamedev._services
    # Actual detector uses the empty disposable provider seam, not saved accounts.
    action('onboarding-runtimes','onboarding.runtimes',{},'onboarding.runtimes()["schema"] == "neyvia.onboarding-runtimes/v1"')
    if native:
        p = action('native-runtime-self-check','native.runtime.self-check',{},'time.now()["unixSeconds"] > 0')
        result['nativeCompletion'] = p.completion()
        if result['checks']['native-runtime-self-check']:
            # Read its retained result directly from the exact owner receipt.
            receipt = next((root/'.agent_control/proofs/native-self-check').glob('native-*/self-check-receipt.json'))
            retained = json.loads(receipt.read_bytes())
            selected = next(iter(retained['fileHashes']))
            target = Path(retained['scratchRoot'])/selected
            target.write_bytes(target.read_bytes()+b'\nchanged proof')
            result['checks']['native-retained-evidence-drift-refuses'] = p.completion()['status']=='incomplete'
    # Real local-only denial engine exercises TCP/UDP/DNS/HTTP and child spawn.
    from grant_agent.neyvia_settings import update, get
    # Forbidden addresses in the implementation are never contacted; these
    # denied operations are blocked before their socket system calls.
    update(service, {'localOnly':True}, get(service)['revision'])
    # Windows' default socketpair binds an ephemeral port for asyncio's wake
    # pipe. Preserve its real TCP pair while making its fixture port explicit.
    import socket
    original_pair = socket.socketpair
    def assigned_pair(*args, **kwargs):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(('127.0.0.1', port))
            listener.listen(1)
            client.connect(('127.0.0.1', port))
            accepted, _ = listener.accept()
            return accepted, client
        except BaseException:
            client.close()
            raise
        finally:
            listener.close()
    socket.socketpair = assigned_pair
    try:
        action('local-only-network-refusals','settings.network_check',{},'settings.network_check()["ok"] == true')
    finally:
        socket.socketpair = original_pair
    update(service, {'localOnly':False}, get(service)['revision'])
    result['boundaries'] += [
        {'action':'autopilot.start/resume','needs':'Actual selected GPT-6 Luna transport and sufficient bounded wall-time for intent planning; no direct credential-file access','proof':'New multi-ask run through manual actions, each fresh acceptance and durable usage/receipts, then stop/resume without duplicate effects'},
        {'action':'conductor.plan/control','needs':'Configured authenticated planner/executor/verifier providers; saved credential access is outside task authorization','proof':'Real plan saved, explicit start, task DAG writes an inspected artifact, independent acceptance verifier passes, reconnect and stop the owned worker'}]
    # Run the real admission paths to retain their actual boundary failures.
    for name, arguments in (
        ('neyvia.autopilot.start', {'requestId':'fixcl4-real-provider-attempt',
          'text':'Inspect the exact local file valid.gltf and report its version.',
          'scopeTools':['workspace.read'],'efficiency':False,'maxModelCalls':1,'maxSeconds':10}),
        ('neyvia.conductor.plan', {'requestId':'fixcl4-real-plan-attempt',
          'goal':'Inspect valid.gltf and independently verify its version.',
          'folder':str(root),'acceptanceChecks':['The actual asset version is 2.0.'],'maxRuntimeSeconds':30})):
        receipt = gateway.native.call(name, arguments)
        result.setdefault('providerBoundaryCalls', {})[name] = receipt
    result['sourceHashesAtStart'] = source_start
    result['sourceHashesAtEnd'] = service_source_hashes()
    result['checks']['sourceUnchanged'] = result['sourceHashesAtEnd'] == source_start
    result['ok'] = all(result['checks'].values())
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--skip-native',action='store_true')
    args=parser.parse_args()
    result=run(args.port, native=not args.skip_native)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'ok':result['ok'],'checks':result['checks']}))
    sys.exit(0 if result['ok'] else 1)
