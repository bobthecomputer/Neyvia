"""Real HTTP bytes and actual owned Obscura PNG through positive CL/manual gates."""
from __future__ import annotations
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--engine-port',type=int,required=True)
    parser.add_argument('--fixture-port',type=int,required=True)
    parser.add_argument('--ipc-port',type=int,required=True)
    parser.add_argument('--obscura',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if (args.engine_port,args.fixture_port,args.ipc_port)!=(48827,48828,48826): parser.error('Explicit assigned ports48827,48828,48826 required')
    executable=args.obscura.resolve()
    if not executable.is_file() or any(executable.is_relative_to(Path(r'C:\Users\user\Projects')/name) for name in ('Neyvia','Neyvia-next')):
        parser.error('Use an existing owned Obscura binary outside protected trees')
    root=REPO/'.agent_control/proofs'/('FIXCL3-capture-'+str(time.time_ns()))
    root.mkdir(parents=True)
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    from fixcl_verify import environment
    install(root); install_hidden_subprocess_default(); environment(root,args.fixture_port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
    os.environ['NEYVIA_OBSCURA_EXE']=str(executable)
    os.environ['NEYVIA_BROWSER_PROOF_PORTS']='48826,48827,48828'
    from playwright._impl._driver import compute_driver_executable
    driver_node,driver_cli=compute_driver_executable()
    allowed_prefixes=[subprocess.list2cmdline([str(executable)])+' serve ',
        subprocess.list2cmdline([str(driver_node),str(driver_cli),'run-driver'])]
    def guard(event, values):
        if event in {'socket.connect','socket.bind'}:
            address=values[1]
            if isinstance(address,tuple) and (address[0] not in {'127.0.0.1','localhost','::1'} or address[1] not in {48826,48827,48828}):
                raise PermissionError('Capture proof allows only explicit assigned loopback ports')
        if event=='subprocess.Popen':
            command=values[1]
            text=subprocess.list2cmdline(command) if isinstance(command,(list,tuple)) else str(command)
            allowed=any(text.startswith(prefix) for prefix in allowed_prefixes)
            if not allowed: raise PermissionError('Capture proof permits only existing hidden Obscura')
    sys.addaudithook(guard)
    if sys.platform=='win32':
        def pair(family=socket.AF_INET,type=socket.SOCK_STREAM,proto=0):
            with socket.socket(family,type,proto) as listener:
                listener.bind(('127.0.0.1',args.ipc_port)); listener.listen(1)
                client=socket.socket(family,type,proto); client.connect(listener.getsockname())
                server,_=listener.accept(); return server,client
        socket.socketpair=pair
    prepare_broker_fixture(root)
    source_body=b'<!DOCTYPE html><html><head><title>Owned Capture Fixture</title></head><body style="background:#102030;color:white"><h1>FIXCL3 seventeen widgets</h1><div style="width:160px;height:100px;background:#ef3340">Original HTTP body</div><p>Exact fresh fixture phrase.</p><button onclick="document.body.style.background=\'#228b22\';document.querySelector(\'h1\').textContent=\'FIXCL3 changed twenty widgets\'">Change page</button></body></html>'
    fixture={'body':source_body,'gets':0}
    class Peer(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def do_GET(self):
            if self.path not in {'/document','/page'}: self.send_error(404); return
            fixture['gets']+=1; body=fixture['body']
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',args.fixture_port),Peer)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol, unwrap
    from grant_agent.cl import document_effects, browser_effects
    from grant_agent.neyvia_browser import service_for
    from grant_agent.ui_command_bus import bus_for
    from grant_agent.web_documents import WebDocuments
    gateway=NeyviaToolGateway(root,allow_mutations=True,permission_mode='workspace')
    service=service_for(root); bus=bus_for(root)
    paths=[Path(__file__),REPO/'scripts/fixcl3_capture_manual.py']+[REPO/'src/grant_agent'/name for name in
        ('web_documents.py','browser_obscura.py','neyvia_browser.py','cl/document_effects.py','cl/browser_effects.py')]
    paths += [REPO/'manuals'/name for layer in ('tools-depth','browser') for name in (layer+'.manual.json','cl/'+layer+'.cl')]
    hashes=lambda:{p.relative_to(REPO).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    proof={'schema':'neyvia.fixcl3-capture.v1','root':str(root),'ports':{'engine':args.engine_port,'fixture':args.fixture_port,'ipc':args.ipc_port},
        'checks':{},'transcripts':{},'witnesses':[],'sourceHashesAtStart':hashes(),
        'limitations':['HTTP proof binds the bounded bytes actually fetched; it does not claim the remote URL is still unchanged later.',
            'PNG proof binds this existing native page, fresh DOM revision and process identity; it does not establish PDF canvas correctness or WebView2 acknowledgement.']}
    checks=proof['checks']
    def invoke(case,tool,arguments,procedure=None):
        source=('run '+procedure if procedure else tool.removeprefix('neyvia.'))+'('+','.join(key+'='+json.dumps(value) for key,value in arguments.items())+')'
        protocol=Protocol(gateway,lazy_manuals=True)
        existing_receipts=set(gateway.native.receipt_root.glob('*.json'))
        observed=('browser.observe(tabId='+json.dumps(arguments['tabId'])+')\n') if tool=='neyvia.browser.action' else ''
        result=protocol.run('G fresh: time.now()["unixSeconds"] > 0\n'+observed+source+'\ndone()',action_id='fixcl3-capture-'+case)
        proof['transcripts'][case]=result
        print(json.dumps({'case':case,'ok':result.get('ok'),'status':result.get('status'),'error':result.get('error')}),flush=True)
        rows=[row for row in result.get('results',[]) if row.get('name') in {tool,tool.removeprefix('neyvia.')} or row.get('tool')==tool]
        value=unwrap(protocol.action_output(tool,rows[-1]['result'])) if rows and rows[-1].get('result') else {}
        if procedure and result.get('ok'):
            native=[json.loads(path.read_bytes()) for path in gateway.native.receipt_root.glob('*.json') if path not in existing_receipts]
            native=[row for row in native if row.get('tool')==tool]
            if len(native)!=1: raise RuntimeError('Procedure did not emit one exact native subject receipt')
            value=unwrap(protocol.action_output(tool,native[0]))
            rows=result.get('results',[])
        checks[case+'_positive_cl']=result.get('ok') is True and 'R done ok' in result.get('text','')
        checks[case+'_fresh_effect']=any(c.get('name','').startswith('effect-') and c.get('passed') is True for row in rows for c in row.get('checks',[]))
        proof['witnesses'].append({'case':case,'tool':tool,'arguments':arguments,'value':value,'effectChecks':[c for row in rows for c in row.get('checks',[])],'procedure':procedure})
        return value
    try:
        fetchargs={'url':f'http://127.0.0.1:{args.fixture_port}/document','refresh':True,'maxChars':4000,'maxAgeSeconds':300}
        protocol=Protocol(gateway,lazy_manuals=True)
        before=document_effects.snapshot_for(protocol,'web.fetch',fetchargs)
        fetched=invoke('fetch-manual','web.fetch',fetchargs,'tools-depth.fetch-owned-http-body')
        owner=WebDocuments(root); identity=fetched['document']; bodypath=owner.path.parent/'web_document_bodies'/(identity+'.bin')
        checks['retained_actual_response_bytes']=owner.body(identity)==source_body and fetched['contentSha256']==hashlib.sha256(source_body).hexdigest()
        text,metadata=owner.get(identity)
        checks['actual_parsed_text']=text=='Owned Capture Fixture FIXCL3 seventeen widgets Original HTTP body Exact fresh fixture phrase. Change page' and fetched['title']=='Owned Capture Fixture'
        verify=document_effects.checks_for(protocol,'web.fetch',fetchargs)[0]['check']
        checks['fresh_fetch_owner_accepts_exact']=verify(fetchargs,fetched,before) is True
        bodypath.write_bytes(b'Tampered actual body')
        checks['fresh_fetch_owner_refuses_body_tamper']=verify(fetchargs,fetched,before) is False
        bodypath.write_bytes(source_body)
        with owner.connect() as db: db.execute('UPDATE documents SET text=? WHERE id=?',('Tampered cached text',identity))
        checks['fresh_fetch_owner_refuses_text_tamper']=verify(fetchargs,fetched,before) is False
        with owner.connect() as db: db.execute('UPDATE documents SET text=? WHERE id=?',(text,identity))
        cacheargs={**fetchargs,'refresh':False}; gets=fixture['gets']
        cached=invoke('fetch-cached','web.fetch',cacheargs)
        checks['cache_reuses_exact_immutable_bytes_without_http']=cached['document']==identity and cached['cacheHit'] is True and fixture['gets']==gets
        fixture['body']=source_body.replace(b'seventeen',b'eighteen')
        changed=invoke('fetch-changed','web.fetch',fetchargs)
        checks['changed_actual_http_body_new_identity']=changed['document']!=identity and owner.body(changed['document'])==fixture['body'] and owner.get(identity)==(text,metadata)
        checks['body_temporary_files_cleaned']=not list(bodypath.parent.glob('*.tmp'))
        fixture['body']=source_body
        proof['engine']=service.request('headless.start',{'port':args.engine_port,'allowLocalFixtures':True},owner=True)
        opened=invoke('browser-open','neyvia.browser.open',{'url':f'http://127.0.0.1:{args.fixture_port}/page','engine':'obscura'})
        tab_id=opened['tabId']; capargs={'tabId':tab_id}
        proof['fixtureGrant']=service.request('tab.grant',{'tabId':tab_id,'enabled':True},owner=True)
        protocol=Protocol(gateway,lazy_manuals=True)
        before=browser_effects.snapshot_for(protocol,'neyvia.browser.capture',capargs)
        captured=invoke('capture-manual','neyvia.browser.capture',capargs,'browser.capture-owned-native-page')
        from PIL import Image
        imagepath=Path(captured['path'])
        actual=imagepath.read_bytes()
        with Image.open(imagepath) as png:
            dimensions=png.size; colors=png.convert('RGB').getcolors(maxcolors=1_000_000)
        checks['actual_native_png_bytes']=actual.startswith(b'\x89PNG\r\n\x1a\n') and hashlib.sha256(actual).hexdigest()==captured['sha256']
        checks['actual_native_render_nonuniform']=dimensions[0]>200 and dimensions[1]>100 and colors is not None and len(colors)>10
        proof['freshPng']={'path':str(imagepath),'sha256':hashlib.sha256(actual).hexdigest(),'bytes':len(actual),'dimensions':dimensions,'colorCount':len(colors or [])}
        verify=browser_effects.checks_for(protocol,'neyvia.browser.capture',capargs)[0]['check']
        checks['fresh_capture_owner_accepts_exact']=verify(capargs,captured,before) is True
        imagepath.write_bytes(actual[:-8])
        checks['fresh_capture_owner_refuses_png_tamper']=verify(capargs,captured,before) is False
        imagepath.write_bytes(actual)
        checks['fresh_capture_owner_refuses_wrong_native_identity']=verify(capargs,{**captured,'pageIdentity':'another-page'},before) is False
        projected=service.projection(tab_id)
        button=next(row for row in projected['elements'] if row.get('name')=='Change page')
        proof['fixturePageChange']=service.request('action',{'tabId':tab_id,'action':'click','revision':projected['revision'],'element':button['id']},owner=True)
        checks['real_owner_fixture_click_changes_dom']=proof['fixturePageChange'].get('ok') is True and 'changed twenty widgets' in service.projection(tab_id)['text']
        checks['fresh_capture_owner_refuses_page_drift']=verify(capargs,captured,before) is False
        changed_png=invoke('capture-changed','neyvia.browser.capture',capargs,'browser.capture-owned-native-page')
        changed_pixels=Path(changed_png['path']).read_bytes()
        checks['real_page_change_changes_native_png']=changed_png['sha256']!=captured['sha256'] and changed_pixels!=actual and 'changed twenty widgets' in service.projection(tab_id)['text']
        proof['changedPng']={'path':changed_png['path'],'sha256':changed_png['sha256'],'sourceRevision':changed_png['sourceRevision']}
        checks['capture_temporary_files_cleaned']=not list(imagepath.parent.glob('*.tmp'))
        manuals=[row['payload'] for row in bus.since() if row['action']=='cl.manual.use']
        proof['manualReceipts']=manuals
        checks['every_new_adapter_positive_manual_witness']=all(any(r.get('tool')==tool for r in manuals) for tool in ('web.fetch','neyvia.browser.capture'))
    except Exception as error:
        import traceback
        proof['failure']={'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()}
        checks['journey_completed']=False
    finally:
        if service.headless: service.request('headless.stop',{},owner=True)
        server.shutdown(); server.server_close(); thread.join(timeout=3)
    proof['sourceHashesAtEnd']=hashes(); checks['source_unchanged_during_run']=proof['sourceHashesAtStart']==hashes()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'ok':all(checks.values()),'checks':checks,'failure':proof.get('failure'),'receipt':str(args.output)}))
    raise SystemExit(0 if all(checks.values()) else 1)

if __name__=='__main__': main()
