"""Actual loopback peer transport and fresh durable CL provider effect witnesses.

The peer stores the received input; it never invents an LLM response. The
adapter is supplied at the broker's public constructor dependency seam.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from fixcl_verify import guards, environment


def run(root, port):
    if port not in range(48824, 48827):
        raise ValueError('Use an explicit assigned provider port 48824-48826')
    root.mkdir(parents=True, exist_ok=False)
    guards(root)
    environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    peer_root = root / 'peer'
    peer_root.mkdir()
    counters = {'posts': 0}
    class Peer(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path != '/session' or body.get('model') != 'local-transport-witness':
                self.send_error(400)
                return
            counters['posts'] += 1
            key = hashlib.sha256(body['requestId'].encode()).hexdigest()
            payload = {'id': key, **body}
            (peer_root / (key + '.json')).write_text(json.dumps(payload, sort_keys=True), encoding='utf-8')
            encoded = json.dumps({'id': key}).encode()
            self.send_response(201)
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
    server = ThreadingHTTPServer(('127.0.0.1', port), Peer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    from grant_agent.connected_sessions.model import SessionSummary, Capabilities
    from grant_agent.connected_sessions import broker as bm
    class PeerAdapter:
        def available(self): return True, None
        def list_sessions(self, **_):
            return [SessionSummary(id=bm.make_session_id('codex', broker.host['deviceId'], row['id']),
                app='codex', title='Local transport input', cwd=row['cwd'], model=row['model'],
                capabilities=Capabilities(new_session=True))
                for path in peer_root.glob('*.json') for row in [json.loads(path.read_bytes())]]
        def live_status(self): return {}
        def options(self, session_id=None): return {'models':[{'id':'local-transport-witness'}]}
        def read(self, *args, **kwargs): raise NotImplementedError('Peer has no model output')
        def interrupt(self, *_): return False
        def answer(self, *_): raise NotImplementedError('Peer has no interactive questions')
        def can_start_new(self): return True, None
        def start_turn(self, session_id, message, options, *, cwd, run_id, emit):
            body = {'requestId':run_id,'prompt':message,'cwd':cwd,'model':options.model,
                'permissionMode':options.permission_mode}
            request = Request(f'http://127.0.0.1:{port}/session', data=json.dumps(body).encode(),
                headers={'Content-Type':'application/json'}, method='POST')
            with urlopen(request, timeout=5) as response:
                if response.status != 201:
                    raise RuntimeError('Peer did not create the durable subject')
                row = json.load(response)
            identity = bm.make_session_id('codex', broker.host['deviceId'], row['id'])
            emit({'type':'session.created','sessionId':identity})
            return identity
    from grant_agent.web_backend import FluxioWebBackend
    from grant_agent.neyvia_workspace_tools import workspace_for
    backend = FluxioWebBackend(root, root / 'static')
    workspace_for(root, backend)
    broker = bm.ConnectedBroker(root, backend=backend, adapters={'codex':PeerAdapter()},
        load_defaults=False, autostart=False)
    # Preserve the existing singleton seam, scoped to this never-used root.
    key = os.path.normcase(str(root.resolve()))
    if key in bm._BROKERS:
        raise RuntimeError('Disposable broker root was unexpectedly already owned')
    bm._BROKERS[key] = broker
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.cl import provider_effects
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace')
    bus = workspace_for(root).bus
    source_paths = [Path(provider_effects.__file__), Path(__file__), REPO/'manuals/runtime-provider.manual.json', REPO/'manuals/cl/runtime-provider.cl']
    hashes = lambda: {str(path.relative_to(REPO)):hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    before_hashes = hashes()
    results, checks = {}, {}
    def invoke(key, text):
        result = Protocol(gateway, lazy_manuals=True).run(text, action_id='fixcl3-provider-' + key)
        results[key] = result
        print(json.dumps({'case':key,'ok':result.get('ok'),'status':result.get('status')}),flush=True)
        return result
    try:
        prompt = 'Retain this exact locally supplied input: 17 widgets.'
        args = {'app':'codex','folder':str(root),'prompt':prompt,'requestId':'local-peer-session',
            'model':'local-transport-witness','permissionMode':'read-only'}
        inputs = ','.join(key+'='+json.dumps(value) for key,value in args.items())
        source = 'G local: time.now()["unixSeconds"] > 0\nrun runtime-provider.create-provider-session(' + inputs + ')\ndone()'
        created = invoke('session-create', source)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and broker.store.load(args['requestId']).get('state') not in {'completed','failed'}:
            time.sleep(.01)
        durable = broker.store.load(args['requestId'])
        peer_key = hashlib.sha256(args['requestId'].encode()).hexdigest()
        peer_file = peer_root / (peer_key + '.json')
        peer = json.loads(peer_file.read_bytes()) if peer_file.exists() else {}
        checks['session_cl_completed'] = 'R done ok' in created.get('text','') and created.get('ok') is True
        checks['actual_peer_exact_input'] = peer == {'id':peer_key,'requestId':args['requestId'],
            'prompt':prompt,'cwd':str(root),'model':args['model'],'permissionMode':'ask'}
        checks['broker_durable_completed'] = durable.get('state') == 'completed'
        replay = invoke('session-replay', source)
        checks['same_request_does_not_resend'] = replay.get('ok') is True and counters['posts'] == 1
        conflict = invoke('session-conflict', source.replace(prompt, 'Changed local input'))
        checks['conflicting_request_refused_before_peer'] = conflict.get('ok') is False and counters['posts'] == 1
        for enabled in (False, True):
            result = invoke('mods-' + str(enabled).lower(), 'G local: time.now()["unixSeconds"] > 0\nrun runtime-provider.set-claude-mods(enabled=' + str(enabled).lower() + ')\ndone()')
            checks['mods_saved_' + str(enabled).lower()] = result.get('ok') is True and bus.get('claudeCodeMods')['enabled'] is enabled
        home = root / 'reviewed-source'
        skill = home/'skills/input-witness'
        skill.mkdir(parents=True)
        (skill/'SKILL.md').write_text('---\nname: input-witness\ndescription: Retain exact input\n---\nRead the selected input file.\n',encoding='utf-8')
        (skill/'example.txt').write_text('17 widgets\n',encoding='utf-8')
        (home/'AGENTS.md').write_text('Use selected local files.\n',encoding='utf-8')
        result = invoke('assets-import', 'G local: time.now()["unixSeconds"] > 0\nrun runtime-provider.import-reviewed-assets(codexHome=' + json.dumps(str(home)) + ')\ndone()')
        checks['asset_import_cl_completed'] = result.get('ok') is True and 'R done ok' in result.get('text','')
        rows = [row for row in result.get('results',[]) if row.get('name') == 'codex.assets.import' or row.get('tool') == 'codex.assets.import']
        # Independently re-open the catalog pointer rather than selecting a host envelope.
        pointer_path = root/'.agent_control/imports/codex/latest.json'
        pointer = json.loads(pointer_path.read_bytes()) if pointer_path.exists() else {}
        catalog_path = Path(pointer.get('catalogPath') or root/'missing-catalog')
        catalog = json.loads(catalog_path.read_bytes()) if catalog_path.is_file() else {}
        imported = catalog.get('importedSkills',[])
        checks['imported_exact_skill_bytes_disabled'] = bool(imported and imported[0].get('enabled') is False and
            Path(imported[0]['source']['path']).read_bytes() == (skill/'SKILL.md').read_bytes() and
            (Path(imported[0]['source']['path']).parent/'example.txt').read_bytes() == (skill/'example.txt').read_bytes())
        protocol = Protocol(gateway, lazy_manuals=True)
        snap = provider_effects.snapshot_for(protocol,'codex.assets.import',{'codexHome':str(home)})
        receipt = json.loads((catalog_path.parent/'import-receipt.json').read_bytes()) if catalog_path.is_file() else {}
        if imported:
            Path(imported[0]['source']['path']).write_text('Tampered imported subject',encoding='utf-8')
        verify = provider_effects.checks_for(protocol,'codex.assets.import',{'codexHome':str(home)})[0]['check']
        checks['fresh_import_observer_refuses_tamper'] = verify({'codexHome':str(home)},receipt,snap) is False
        for name, call in [('image','image.generate(requestId="unavailable-image",request={"prompt":"local witness"})'),
                           ('scroll','scroll.generate(pack="unavailable-pack",requestId="unavailable-cards")')]:
            denied = invoke(name+'-model-frontier',call)
            checks[name+'_model_frontier_denied'] = denied.get('ok') is False
        manual_receipts = [row['payload'] for row in bus.since() if row['action']=='cl.manual.use']
        cases = {'session-create':'neyvia.session.new','mods-false':'neyvia.claude.mods','assets-import':'codex.assets.import'}
        checks['every_adapter_retains_positive_effect_manual_witness'] = all(
            any(receipt.get('tool') == tool for receipt in manual_receipts) and
            any(check.get('name','').startswith('effect-') and check.get('passed') is True
                for row in results[case].get('results',[]) for check in row.get('checks',[]))
            for case,tool in cases.items())
        checks['source_unchanged_during_run'] = before_hashes == hashes()
        return {'schema':'neyvia.fixcl3-provider.v1','root':str(root),'port':port,'results':results,
            'checks':checks,'peerPosts':counters['posts'],'freshPeerInput':peer,'durableRun':durable,'manualReceipts':manual_receipts,
            'sourceHashesAtStart':before_hashes,'sourceHashesAtEnd':hashes(),
            'limitations':['Local loopback adapter proves actual broker transport and saved input/session, not model generation or account authentication.',
                'Image generation needs approved configured Codex subscription, actual completed output bytes and image publication.',
                'Study generation needs configured Luna CLI and validated generated cards; no saved account access is authorized.',
                'Generic plugin mutations require plugin-specific independently observed effects; codex.plugins.call remains frontier.']}
    finally:
        broker.close()
        bm._BROKERS.pop(key,None)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = run(args.root.resolve(),args.port)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'ok':all(result['checks'].values()),'checks':result['checks'],'receipt':str(args.output)}))
    raise SystemExit(0 if all(result['checks'].values()) else 1)


if __name__ == '__main__': main()
