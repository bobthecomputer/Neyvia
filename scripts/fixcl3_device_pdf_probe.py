"""Actual paired file copies and remote refusals over disposable local HTTP peers."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import subprocess
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))

SOURCES = ['src/grant_agent/cl/device_effects.py', 'src/grant_agent/cl/remote_effects.py',
           'src/grant_agent/neyvia_devices.py', 'src/grant_agent/neyvia_remote.py',
           'config/neyvia_remote.json', 'scripts/fixcl3_device_pdf_probe.py',
           'manuals/cl/cross-pc.cl', 'manuals/cross-pc.manual.json',
           'manuals/cl/remote.cl', 'manuals/remote.manual.json']


def sources():
    return {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in SOURCES}


def prepare_manual():
    from grant_agent.cl.manuals import cl_to_manual, manual_to_cl
    for manual in ('cross-pc', 'remote'):
        canonical = REPO / 'manuals/cl' / (manual + '.cl')
        artifact = REPO / 'manuals' / (manual + '.manual.json')
        old_text = canonical.read_text(encoding='utf-8')
        data = cl_to_manual(old_text)
        if data != json.loads(artifact.read_bytes()):
            raise ValueError('Existing manual source disagrees with artifact: ' + manual)
        metadata = json.loads(next(line.removeprefix('-- @manual ') for line in old_text.splitlines()
                                   if line.startswith('-- @manual ')))['tool_metadata']
        chapter = data['chapters']['overview']
        if manual == 'cross-pc':
            inputs = {'type': 'object', 'properties': {key: {'type': 'string'} for key in ('device', 'from', 'to')},
                      'required': ['device', 'from', 'to'], 'additionalProperties': False}
            for verb in ('fetch', 'send'):
                saved = 'copied'
                check = 'fresh-' + verb + '-complete'
                # Saved-ID checks must be statically typed, not a reference
                # through the legacy opaque object return schema.
                chapter['actions']['devices.files.' + verb]['returns'] = {
                    'type': 'object', 'properties': {'transfer': {
                        'type': 'object', 'properties': {
                            'id': {'type': 'string'}, 'status': {'type': 'string'},
                            'sha256': {'type': 'string'}, 'device': {'type': 'string'},
                            'from': {'type': 'string'}, 'to': {'type': 'string'},
                            'size': {'type': 'integer'}, 'done': {'type': 'integer'}},
                        'required': ['id', 'status', 'sha256', 'device', 'from', 'to', 'size', 'done']}},
                    'required': ['transfer']}
                chapter['checks'][check] = {'tool': 'neyvia.devices.transfers',
                    'args': {'id': {'$result': saved + '.transfer.id'}},
                    'expect': {'op': 'eq', 'path': 'transfers.0.status', 'value': 'done'}}
                chapter['procedures']['copy-file-' + verb + '-verified'] = {
                    'goal': 'Copy an already paired explicitly requested regular file <=64 MiB into an explicit folder; conserve source, refuse overwrite, and verify fresh bytes at both endpoints',
                    'inputs': inputs,
                    'steps': [{'action': 'devices.files.' + verb,
                               'args': {**{key: {'$input': key} for key in ('device', 'from', 'to')}, 'wait': 30},
                               'save': saved, 'check': check}]}
            chapter['guidance'].append('CL paired-file copy effects require an explicit destination folder and regular file <=64 MiB; directory/large copies remain native-only frontier; queued status never means complete.') if 'CL paired-file copy effects require an explicit destination folder and regular file <=64 MiB; directory/large copies remain native-only frontier; queued status never means complete.' not in chapter.get('guidance', []) else None
        else:
            note = 'The remote bot API only observes existing owner connections; snapshot is a fresh protected read, never an input/grant effect. Real remote native window/input and the visible host indicator require an outside allowed device or agent desktop.'
            if note not in chapter.get('guidance', []):
                chapter.setdefault('guidance', []).append(note)
        text = manual_to_cl(data, metadata)
        if cl_to_manual(text) != data:
            raise ValueError('Updated manual must compile losslessly: ' + manual)
        canonical.write_text(text, encoding='utf-8', newline='\n')
        artifact.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ports', type=int, nargs=2, required=True)
    parser.add_argument('--prepare-manual', action='store_true')
    args = parser.parse_args()
    if args.ports != [48827, 48828]:
        parser.error('Device peer proof owns only explicit ports 48827 and 48828')
    if args.prepare_manual:
        prepare_manual()
        print('Cross-PC and remote canonical manuals prepared')
        return 0
    stamp = str(time.time_ns())
    root = REPO / '.agent_control/proofs' / ('FIXCL3-device-' + stamp)
    root.mkdir(parents=True)
    # File paths must be outside protected control state. All file fixtures
    # stay in this worktree's ignored disposable agent-run directory.
    files = REPO / '.agent_runs' / ('FIXCL3-device-' + stamp)
    files.mkdir(parents=True)
    from fixcl_verify import environment
    environment(root, args.ports[0])
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    os.environ.update(NEYVIA_PEER_ALLOW_LOOPBACK='1', NEYVIA_REMOTE_PROOF_LOOPBACK='1', NEYVIA_PDF_PYTHON=sys.executable,
                      NEYVIA_REMOTE_PROOF_PORTS=','.join(map(str, args.ports)))
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    install(root)
    prepare_broker_fixture(root)
    def audit(event, arguments):
        if event == 'subprocess.Popen':
            permitted = [[sys.executable, '-c', 'import pypdf'],
                         [sys.executable, str(REPO / 'src/grant_agent/pdf_document_worker.py')]]
            command = arguments[1]
            if command not in permitted and command not in [subprocess.list2cmdline(value) for value in permitted]:
                raise PermissionError('Device peer proof admits only the installed hidden PDF reader')
        if event in {'socket.bind', 'socket.connect'}:
            address = arguments[1]
            if isinstance(address, tuple) and (address[0] not in {'127.0.0.1', 'localhost', '::1'} or address[1] not in args.ports):
                raise PermissionError('Device proof admits only its explicit local peer ports')
    sys.addaudithook(audit)
    from grant_agent.neyvia_devices import devices_for, serve_peer, call_devices, PeerError
    from grant_agent.neyvia_remote import serve_http, service_for as remote_for, RemoteError, _url
    from grant_agent.neyvia_workspace_tools import workspace_for
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.cl import device_effects
    from grant_agent.neyvia_manuals import unwrap

    peer_roots = [root / 'left', root / 'right']
    endpoints, services, servers, threads = [], [], [], []
    traffic = []
    for index, port in enumerate(args.ports):
        peer_root = peer_roots[index]
        peer_root.mkdir()
        service = devices_for(peer_root)
        services.append(service)
        backend = SimpleNamespace(root=peer_root)
        def handler_for(selected_backend):
            class Handler(BaseHTTPRequestHandler):
                protocol_version = 'HTTP/1.1'
                def dispatch(self):
                    parsed = urlsplit(self.path)
                    traffic.append({'port': self.server.server_port, 'method': self.command, 'route': parsed.path})
                    if parsed.path.startswith('/api/ui/remote/peer/'):
                        serve_http(selected_backend, self, parsed, self.command)
                    elif not serve_peer(selected_backend, self, parsed, self.command):
                        self.send_error(404)
                do_GET = dispatch
                do_POST = dispatch
                do_PUT = dispatch
                def log_message(self, *arguments):
                    pass
            return Handler
        server = ThreadingHTTPServer(('127.0.0.1', port), handler_for(backend))
        servers.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        threads.append(thread)
        thread.start()
        url = f'http://127.0.0.1:{port}'
        endpoints.append(url)
        with service.state() as state:
            state['url'] = url
    proof = {'schema': 'neyvia.FIXCL3.device-pdf.v1', 'root': str(root), 'fileFixtures': str(files),
             'ports': args.ports, 'checks': {}, 'transcripts': {}, 'sourceHashesAtStart': sources(),
             'boundary': 'Actual production pairing, DPAPI capabilities, authenticated HTTP peer ranges/uploads and real copied files; no remote/native/renderer mock success',
             'outsideRequirements': ['Second physical paired PC/tailnet and device roster discovery remain unproven; no Tailscale process/config touched',
                 'Remote allowed native window, host indicator, fresh frame/tree and input need an outside allowed device or agent desktop; no visible window was opened',
                 'PDF visible page/search/zoom/highlight need the real Neyvia PDF renderer; independent owner text extraction is proved locally and unmounted effects must refuse',
                 'CL file-copy effect admission is explicit destination + regular file <=64 MiB; directories and larger files remain an explicit boundary']}
    try:
        shared = [files / 'left-shared', files / 'right-shared']
        inboxes = [files / 'left-inbox', files / 'right-inbox']
        for directory in shared + inboxes:
            directory.mkdir()
        os.environ.update(NEYVIA_PEER_DEFAULT_SHARE=str(shared[0]), NEYVIA_PEER_DEFAULT_INBOX=str(inboxes[0]))
        pairing = services[0].pair({'url': endpoints[1], 'name': 'disposable-right'})
        request = services[1].snapshot()['requests'][0]
        services[1].approve({'request': request['id'], 'folders': [{'path': str(shared[1]), 'write': False}], 'inbox': str(inboxes[1])})
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and services[0].snapshot()['devices'][0]['status'] != 'paired':
            time.sleep(.05)
        device = services[0].snapshot()['devices'][0]['id']
        proof['checks']['actualOwnerPairingAndDpapi'] = services[0].snapshot()['devices'][0]['status'] == 'paired'
        print('Actual disposable peers paired', flush=True)
        # Pairing receipt only public identity/permissions; never capabilities.
        proof['pairing'] = {'peer': device, 'status': services[0].snapshot()['devices'][0]['status'],
                            'ownerApprovedDisposableScope': {'shared': str(shared[1]), 'inbox': str(inboxes[1])}}
        prepare_broker_fixture(peer_roots[0])
        gateway = NeyviaToolGateway(peer_roots[0], allow_mutations=True, action_scope='FIXCL3-device', permission_mode='full-access')
        remote_source = shared[1] / 'take.txt'
        remote_source.write_bytes(b'Actual remote range bytes\nFresh fixture source\n')
        local_source = shared[0] / 'send.txt'
        local_source.write_bytes(b'Actual upload bytes\nPair-protected send\n')
        out = files / 'received'
        out.mkdir()
        proof['sourceFixtures'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (remote_source, local_source)}

        def cl(case, lines):
            protocol = Protocol(gateway)
            answer = protocol.run(lines, action_id='FIXCL3-' + case)
            proof['transcripts'][case] = answer
            return protocol, answer

        dest = out / remote_source.name
        # Existing sibling demonstrates the native collision path conserves bytes.
        dest.write_bytes(b'keeper')
        take_line = 'devices.files.fetch(device=' + json.dumps(device) + ',from=' + json.dumps(str(remote_source)) + ',to=' + json.dumps(str(out)) + ',wait=30)'
        take_goal = 'G: devices.files.stat(device=' + json.dumps(device) + ',path=' + json.dumps(str(remote_source)) + ',hash=true).sha256 == ' + json.dumps(hashlib.sha256(remote_source.read_bytes()).hexdigest())
        take_protocol, take = cl('fetch', take_goal + '\n' + take_line + '\ndone()')
        fetched = sorted(out.glob('take*'))
        proof['checks']['fetchPositiveClWitness'] = take.get('ok') is True and len(fetched) == 2 and dest.read_bytes() == b'keeper' and any(path != dest and path.read_bytes() == remote_source.read_bytes() for path in fetched)
        copies = call_devices(peer_roots[0], 'transfers', {})['transfers']
        take_row = next(row for row in copies if row['direction'] == 'take')
        take_copy = Path(take_row['to'])
        original = take_copy.read_bytes()
        take_copy.write_bytes(b'wrong current effect')
        proof['checks']['changedFetchedBytesInvalidateDone'] = take_protocol.completion().get('status') == 'incomplete'
        take_copy.write_bytes(original)
        proof['checks']['restoredFetchedBytesRevalidateDone'] = take_protocol.run('done()').get('ok') is True and take_protocol.completion().get('status') == 'completed'

        send_line = 'devices.files.send(device=' + json.dumps(device) + ',from=' + json.dumps(str(local_source)) + ',to=' + json.dumps(str(inboxes[1])) + ',wait=30)'
        send_goal = 'G: devices.files.stat(device=' + json.dumps(device) + ',path=' + json.dumps(str(inboxes[1] / local_source.name)) + ',hash=true).sha256 == ' + json.dumps(hashlib.sha256(local_source.read_bytes()).hexdigest())
        _, denied = cl('send-without-owner-grant', send_goal + '\n' + send_line + '\ndone()')
        print(json.dumps({'stage': 'send-before-grant', 'status': denied.get('status')}), flush=True)
        proof['checks']['sendNeedsOwnerGrantBeforeUpload'] = denied.get('ok') is False and not (inboxes[1] / local_source.name).exists()
        ws = workspace_for(peer_roots[0])
        with ws.bus.connect() as db:
            approvals = [(row['key'], json.loads(row['value'])) for row in db.execute("SELECT key,value FROM state WHERE key LIKE 'approval:%'")]
        matches = [(key, row) for key, row in approvals if row.get('details') == {'device': device}]
        if len(matches) != 1:
            raise ValueError('Expected one exact disposable send approval')
        ws.approve(matches[0][0].split(':', 1)[1])
        proof['fixtureOwnerGrant'] = {'device': device, 'pendingApprovalId': matches[0][0], 'scope': 'Only this disposable paired peer'}
        send_protocol, sent = cl('send', send_goal + '\n' + send_line + '\ndone()')
        received = inboxes[1] / local_source.name
        proof['checks']['sendPositiveClWitness'] = sent.get('ok') is True and received.read_bytes() == local_source.read_bytes()
        transfer_read = Protocol(gateway).run('devices.transfers()', action_id='FIXCL3-read-transfers')
        proof['transcripts']['transfers-read'] = transfer_read
        proof['checks']['transfersTypedReadonlyCl'] = transfer_read.get('ok') is True and 'E transfer ' in transfer_read.get('text', '')
        # Preserve size+mtime to defeat the native peer's metadata digest cache;
        # the effect gate independently reads the actual remote bytes.
        stamp_before = received.stat()
        bytes_before = received.read_bytes()
        received.write_bytes(b'X' * len(bytes_before))
        os.utime(received, ns=(stamp_before.st_atime_ns, stamp_before.st_mtime_ns))
        proof['checks']['sameMetadataChangedRemoteBytesInvalidateDone'] = send_protocol.completion().get('status') == 'incomplete'
        received.write_bytes(bytes_before)
        os.utime(received, ns=(stamp_before.st_atime_ns, stamp_before.st_mtime_ns))
        proof['checks']['restoredRemoteBytesRevalidateDone'] = send_protocol.run('done()').get('ok') is True and send_protocol.completion().get('status') == 'completed'
        print(json.dumps({'stage': 'copies', 'checks': proof['checks']}), flush=True)
        # Actual native receiver denies writing beyond the approved inbox.
        try:
            services[0].remote(services[0].peer(device), 'files/destination', body={'path': str(shared[1]), 'name': 'forbidden.txt', 'kind': 'file'})
        except PeerError as exc:
            proof['checks']['readonlyShareWriteRefused'] = exc.status == 403 and not (shared[1] / 'forbidden.txt').exists()
        else:
            proof['checks']['readonlyShareWriteRefused'] = False
        # Remote transport invokes the actual peer endpoint. Invalid invite
        # refusal needs no native window, grant, token or visible host indicator.
        remote_service = remote_for(peer_roots[0])
        try:
            remote_service.request('connect', {'url': endpoints[1], 'invite': 'invalid-disposable-invite'})
        except RemoteError as exc:
            proof['checks']['realRemotePeerInvalidInviteRefused'] = exc.code == 'invite_invalid' and exc.status == 401
            proof['transcripts']['remote-invalid-invite'] = {'code': exc.code, 'status': exc.status}
        else:
            proof['checks']['realRemotePeerInvalidInviteRefused'] = False
        remote_read = Protocol(gateway).run('remote.snapshot(connectionId="missing-owned-connection",windowId=1)', action_id='FIXCL3-missing-remote')
        proof['transcripts']['remote-missing-connection'] = remote_read
        try:
            remote_service.request('snapshot', {'connectionId': 'missing-owned-connection', 'windowId': 1})
        except RemoteError as exc:
            proof['transcripts']['remote-missing-owner'] = {'code': exc.code, 'status': exc.status}
            missing = exc.code == 'connection_missing'
        else:
            missing = False
        proof['checks']['remoteSnapshotNoFrontierFalseSuccess'] = (not remote_read.get('ok') and missing
            and 'has no grounded observer' not in remote_read.get('text', ''))
        remote_state = Protocol(gateway).run('remote.state()', action_id='FIXCL3-read-remote-state')
        proof['transcripts']['remote-state'] = remote_state
        proof['checks']['remoteStateActualReadonlyCl'] = remote_state.get('ok') is True
        try:
            _url('https://example.com')
        except RemoteError as exc:
            proof['checks']['remotePublicUrlRefusedBeforeNetwork'] = exc.code == 'tailnet_address_required'
        else:
            proof['checks']['remotePublicUrlRefusedBeforeNetwork'] = False
        # Metadata/text proof is local. Without a real PDF renderer, its CL
        # effect must remain incomplete even though the PDF owner emitted open.
        pdf = peer_roots[0] / 'sample.pdf'
        pdf.write_bytes((REPO / 'web/public/tour/sample-notes.pdf').read_bytes())
        from grant_agent.cl import pdf_effects
        p = Protocol(gateway)
        pdf_args = {'source': str(pdf), 'page': 1}
        before = pdf_effects.snapshot_for(p, 'neyvia.pdf.open', pdf_args)
        opened = unwrap(p.action_output('neyvia.pdf.open', gateway.call_native('neyvia.pdf.open', pdf_args, action_id='FIXCL3-pdf-open-owner')))
        extracted = Protocol(gateway).run('pdf.extract_text(page=1)', action_id='FIXCL3-pdf-extract')
        proof['transcripts']['pdf-extract'] = extracted
        proof['checks']['actualDisposablePdfTextExtracted'] = opened.get('pages', 0) > 0 and extracted.get('ok') is True and 'E ' in extracted.get('text', '')
        proof['checks']['unmountedPdfEffectRefused'] = not pdf_effects.checks_for(p, 'neyvia.pdf.open', pdf_args)[0]['check'](pdf_args, opened, before)
        proof['checks']['pdfBytesConserved'] = hashlib.sha256(pdf.read_bytes()).hexdigest() == before['source']['sha256']
        print(json.dumps({'stage': 'remote-pdf', 'checks': proof['checks']}), flush=True)
        from grant_agent.cl.manuals import cl_to_manual
        proof['checks']['canonicalManualsEqualArtifacts'] = all(cl_to_manual((REPO / 'manuals/cl' / (name + '.cl')).read_text(encoding='utf-8')) == json.loads((REPO / 'manuals' / (name + '.manual.json')).read_bytes()) for name in ('cross-pc', 'remote'))
        for name in ('copy-file-fetch-verified', 'copy-file-send-verified'):
            source = remote_source if 'fetch' in name else local_source
            to = out if 'fetch' in name else inboxes[1]
            result = unwrap(gateway.call_native('neyvia.manual.run', {'id': 'cross-pc', 'procedure': name, 'inputs': {'device': device, 'from': str(source), 'to': str(to)}}))
            proof['transcripts']['manual-' + name] = result
            proof['checks']['manual-' + name] = result.get('ok') is True and result.get('status') == 'completed'
        services[0].revoke(device)
        _, revoked = cl('revoked-peer', take_goal + '\n' + take_line + '\ndone()')
        proof['checks']['revokedPairRefusesNewCopy'] = not revoked.get('ok') and not services[0].snapshot()['devices']
        proof['checks']['actualHttpRangeAndUploadRoutes'] = all(any(row['route'] == route for row in traffic) for route in ('/api/peer/v1/pair/request', '/api/peer/v1/pair/status', '/api/peer/v1/files/raw', '/api/peer/v1/files/upload', '/api/peer/v1/files/upload/finish', '/api/ui/remote/peer/redeem'))
    except Exception as exc:
        proof['checks']['journeyReturnedWithoutUnhandledFailure'] = False
        proof['unhandledFailure'] = {'type': type(exc).__name__, 'message': str(exc)}
        print(json.dumps({'unhandledFailure': proof['unhandledFailure']}), flush=True)
    finally:
        for service in list(__import__('grant_agent.neyvia_remote', fromlist=['_SERVICES'])._SERVICES.values()):
            if service.root.is_relative_to(root):
                service.close()
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)
    proof['httpTraffic'] = traffic
    proof['sourceHashesAtEnd'] = sources()
    proof['checks']['ownedSourcesUnchangedDuringRun'] = proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
    output = REPO / 'scripts/evidence/FIXCL3-device-pdf.json'
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'receipt': str(output), 'checks': proof['checks'], 'passed': all(proof['checks'].values())}))
    return 0 if all(proof['checks'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
