"""Real owner HTTP CL mutations and renderer-protocol adverse journeys.

The ACK sender here is an explicit contract client, not a rendered UI witness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import threading
import time
import urllib.request
import urllib.error

from fixcl_verify import REPO, guards, environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    args = parser.parse_args()
    if args.port not in range(48821,48830):
        parser.error('Assigned explicit loopback port required')
    root = REPO/'.agent_control/proofs'/('FIXCL2-authority-'+str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root); environment(root,args.port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.web_backend import FluxioWebBackend, make_handler, _HandshakeSafeThreadingHTTPServer, SESSION_COOKIE_NAME
    from grant_agent.neyvia_workspace_tools import workspace_for
    from grant_agent.neyvia_cl import owner_protocol
    from grant_agent.neyvia_manuals import unwrap
    from grant_agent.neyvia_notes_tools import call_notes
    from grant_agent.cl.protocol import Protocol
    prepare_broker_fixture(root)
    backend = FluxioWebBackend(root,root/'static')
    backend.admin_config = {**backend.admin_config, 'users':backend.admin_users +
        [{'username':'fixture-member','displayName':'Fixture member','role':'account','password':{'synthetic':True}}]}
    owner = backend._create_session_for_user({'username':backend.username,'role':'admin'})
    other_owner = backend._create_session_for_user({'username':backend.username,'role':'admin'})
    member = backend._create_session_for_user({'username':'fixture-member','role':'account'})
    service = workspace_for(root,backend)
    call_notes(root,'folder',{'folder':str(root/'notes')})
    call_notes(root,'write',{'path':'audit.md','body':'original'})
    (root/'pane.txt').write_text('Actual pane content\n',encoding='utf-8',newline='\n')
    proof = {'schema':'neyvia.FIXCL2.authority.v1','root':str(root),'port':args.port,
        'boundary':'Real authenticated HTTP/backend/native CL calls. Renderer acknowledgements are a synthetic protocol client; no rendered mount proof claimed.',
        'transcripts':{},'checks':{},'sourceHashesAtStart':sources()}
    class OwnedServer(_HandshakeSafeThreadingHTTPServer):
        allow_reuse_address = False

        def server_bind(self):
            if os.name == 'nt':
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    server = OwnedServer(('127.0.0.1',args.port),make_handler(backend))
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    proof['checks']['issuedOwnerSessionValidBeforeHTTP'] = backend.web_auth_sessions.lookup(owner) is not None
    def request(path,body,token=owner,origin=None):
        headers = {'Content-Type':'application/json'}
        if origin:
            headers['Origin'] = origin
        if token:
            headers['Cookie'] = SESSION_COOKIE_NAME+'='+token
        req = urllib.request.Request(f'http://127.0.0.1:{args.port}'+path,
            data=json.dumps(body).encode(),headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=120) as response:
                return {'httpStatus':response.status,'value':json.load(response)}
        except urllib.error.HTTPError as exc:
            return {'httpStatus':exc.code,'value':json.load(exc)}
    def cl(key,lines,token=owner,**selectors):
        answer = request('/api/ui/tools/call',{'tool':'neyvia.cl','arguments':{'lines':lines,'actionId':key},**selectors},token)
        proof['transcripts'][key] = answer
        return answer['value'].get('data',answer['value'])
    try:
        lines = 'G: notes.read(path="audit.md").body == "HTTP owner bytes" and notes.read(path="audit.md").pinned == True\nrun notes.write-and-pin(path="audit.md",body="HTTP owner bytes",replace_note="replace")\ndone()'
        answer = cl('owner-write-pin',lines)
        proof['checks']['ownerMutationExactBytesAndPin'] = answer.get('ok') is True and answer.get('doneStatus') == 'ok' and (root/'notes/audit.md').read_bytes() == b'HTTP owner bytes' and call_notes(root,'read',{'path':'audit.md'})['pinned'] is True
        proof['checks']['guestForbidden'] = request('/api/ui/tools/call',{'tool':'neyvia.cl','arguments':{'lines':lines}},member)['httpStatus'] == 403
        proof['checks']['unsignedForbidden'] = request('/api/ui/tools/call',{'tool':'neyvia.cl','arguments':{'lines':lines}},None)['httpStatus'] == 401
        proof['checks']['crossOriginCLForbidden'] = request('/api/ui/tools/call',{'tool':'neyvia.cl','arguments':{'lines':lines}},origin='https://outside.invalid')['httpStatus'] == 403
        proof['checks']['workspaceSelectorConflict'] = request('/api/ui/tools/call',{'tool':'neyvia.cl','_expectedStateRoot':str(root.parent),'arguments':{'lines':lines}})['httpStatus'] == 409
        different = cl('other-owner-done','done()',other_owner)
        proof['checks']['separateSessionHasNoInheritedGoal'] = different.get('ok') is False
        raw = request('/api/ui/tools/call',{'tool':'neyvia.notes.write','arguments':{'path':'audit.md','body':'raw bypass'}})
        proof['transcripts']['rawMutation'] = raw
        proof['checks']['rawMutationCannotBypassCL'] = raw['value'].get('data',{}).get('status') == 'cl_goal_required' and (root/'notes/audit.md').read_bytes() == b'HTTP owner bytes'
        autopilot = request('/api/ui/tools/call',{'tool':'neyvia.autopilot.start','arguments':{'prompt':'must not launch'}})
        proof['transcripts']['rawAutopilot'] = autopilot
        proof['checks']['autopilotHasNoWeakerHTTPBypass'] = autopilot['value'].get('data',{}).get('status') == 'cl_goal_required'
        outside = cl('workspace-escape','G: time.now()["unixSeconds"] > 0\nworkspace.write(path="../escape.txt",content="outside")\ndone()',root=str(root.parent),permissionMode='full-access',sessionId='invented')
        proof['checks']['clientAuthorityAndPathEscapeRefused'] = outside.get('ok') is False and not (root.parent/'escape.txt').exists()
        no_g = cl('missing-goal','notes.write(path="audit.md",body="no goal")',other_owner)
        proof['checks']['mutationRequiresAuthoredGoal'] = no_g.get('ok') is False and (root/'notes/audit.md').read_bytes() == b'HTTP owner bytes'
        # Use a third independent real owner session for the pane intent.
        pane_owner = backend._create_session_for_user({'username':backend.username,'role':'admin'})
        target = str(root/'pane.txt')
        pending = cl('pane-request','G: pane.observe().visible == True\npane.show(kind="file",target='+json.dumps(target)+')',pane_owner)
        proof['checks']['missingAckIncomplete'] = pending.get('ok') is False and pending.get('status') == 'unknown'
        events = service.bus.since(0)
        if not any(row['action'] == 'pane.show' for row in events):
            print(json.dumps({'pendingPane':pending},ensure_ascii=False),flush=True)
        event = next(row for row in reversed(events) if row['action'] == 'pane.show')
        generic = request('/api/ui/ack',{'id':event['id'],'ok':True,'clientId':'contract-client'},pane_owner)
        proof['transcripts']['genericAck'] = generic
        proof['checks']['deliveryAckDoesNotComplete'] = cl('generic-ack-done','done()',pane_owner).get('ok') is False
        report = {'paneId':event['payload']['paneId'],'runtimeId':'fixture-file-editor-runtime',
            'kind':'file','target':target,'contentHash':hashlib.sha256((root/'pane.txt').read_bytes()).hexdigest(),'mounted':True,'visible':True}
        for key,value in (('paneId','wrong-pane'),('contentHash','0'*64)):
            invalid = request('/api/ui/ack',{'id':event['id'],'ok':True,'clientId':'contract-client','observation':{**report,key:value}},pane_owner)
            proof['transcripts']['wrong-'+key] = invalid
            proof['checks']['wrong-'+key+'-refused'] = invalid['httpStatus'] == 400
        request('/api/ui/ack',{'id':event['id'],'ok':True,'clientId':'contract-client','observation':report},pane_owner)
        done = cl('observed-pane-done','done()',pane_owner)
        proof['checks']['contentAckAllowsExplicitDone'] = done.get('ok') is True
        proof['checks']['resumeNeverRedispatchesPane'] = len([e for e in service.bus.since(0) if e['action']=='pane.show']) == 1
        session = backend.web_auth_sessions.lookup(pane_owner)
        protocol = owner_protocol(service,session,backend.username)
        saved = protocol._completion_snapshot()
        restored = Protocol(protocol.gateway)
        proof['checks']['restoredEffectCompletesWithFreshReport'] = restored.completion(saved=saved)['status'] == 'completed'
        for key,value in (('runtimeId','changed-runtime'),('visible',False),('mounted',False)):
            request('/api/ui/ack',{'id':event['id'],'ok':True,'clientId':'contract-client','observation':{**report,key:value}},pane_owner)
            proof['checks'][key+'ChangeRefusesCompletion'] = restored.completion(saved=saved)['status'] == 'incomplete'
        request('/api/ui/ack',{'id':event['id'],'ok':True,'clientId':'contract-client','observation':report},pane_owner)
        state_key = 'renderer:pane:'+event['id']
        service.bus.put(state_key,{**service.bus.get(state_key),'observedAt':time.time()-31})
        proof['checks']['expiredObservationRefusesCompletion'] = restored.completion(saved=saved)['status'] == 'incomplete'
        request('/api/ui/ack',{'id':event['id'],'ok':True,'clientId':'contract-client','observation':report},pane_owner)
        (root/'pane.txt').write_bytes(b'Changed independently\n')
        proof['checks']['independentContentChangeRefusesCompletion'] = restored.completion(saved=saved)['status'] == 'incomplete'
        # Recoverably move the disposable file away: absence cannot relax the
        # content hash that was required when the pane action was admitted.
        (root/'pane.txt').rename(root/'pane-away.txt')
        proof['checks']['missingFileRefusesCompletion'] = restored.completion(saved=saved)['status'] == 'incomplete'
        proof['manualUses'] = [row['payload'] for row in service.bus.since(0) if row['action']=='cl.manual.use']
        proof['checks']['ownerAndPaneCurrentManualReceipts'] = all(row.get('sourceSha256') and row.get('procedure') and row.get('effectSourceBindings') for row in proof['manualUses']) and len(proof['manualUses']) >= 3
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5); service.close()
        (REPO/'scripts/evidence/FIXCL2-authority.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
    proof['checks']['ownedHTTPServerClosed'] = not thread.is_alive()
    proof['sourceHashesAtEnd'] = sources()
    proof['checks']['sourceUnchanged'] = proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
    output = REPO/'scripts/evidence/FIXCL2-authority.json'
    output.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'receipt':str(output),'checks':proof['checks']}))
    return 0 if all(proof['checks'].values()) else 1


def sources():
    paths = list((REPO/'src/grant_agent/cl').glob('*.py'))
    paths += [REPO/'src/grant_agent'/name for name in ('neyvia_cl.py','neyvia_ui_api.py','neyvia_workspace_tools.py','ui_command_bus.py','neyvia_panes.py')]
    paths += [REPO/'manuals/cl/neyvia-reference.cl',REPO/'manuals/neyvia-reference.manual.json']
    return {str(path.relative_to(REPO)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


if __name__ == '__main__':
    raise SystemExit(main())
