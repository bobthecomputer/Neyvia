"""Actual CL media journeys in Neyvia's own headless browser and FFmpeg.

The disposable skill home is the sole skill target. No saved account, public
service, browser fallback, downloaded runtime or desktop window is used.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time

from fixcl_verify import REPO, environment, bind_fixture_broker


def run(args):
    ports = {args.port, args.browser_port, args.ipc_port}
    if len(ports) != 3 or not ports.issubset(set(range(48821, 48830))):
        raise ValueError('Distinct explicitly assigned FIXCL ports required')
    root = REPO / '.agent_control/proofs' / ('FIXCL4-media-' + str(time.time_ns()))
    root.mkdir(parents=True)
    environment(root, args.port)
    os.environ.update(CODEX_HOME=str(root / 'codex-home'), NEYVIA_BROWSER_PROOF_PORTS=','.join(map(str, ports)))
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(root); install_hidden_subprocess_default()
    prepare_broker_fixture(root); bind_fixture_broker(root)
    import playwright
    allowed_processes = {args.obscura.resolve(), (Path(playwright.__file__).parent/'driver/node.exe').resolve()}
    ffmpeg = shutil.which('ffmpeg'); ffprobe = shutil.which('ffprobe')
    if ffmpeg: allowed_processes.add(Path(ffmpeg).resolve())
    if ffprobe: allowed_processes.add(Path(ffprobe).resolve())
    def guard(event, values):
        if event in {'socket.bind', 'socket.connect'}:
            address = values[1]
            if isinstance(address, tuple) and (address[0] not in {'127.0.0.1','localhost','::1'} or address[1] not in ports):
                raise PermissionError('Media proof confines all sockets to assigned loopback ports')
        if event == 'subprocess.Popen':
            command = values[1]
            if isinstance(command,(list,tuple)):
                executable=command[0]
            else:
                text=command.strip()
                executable=text[1:].split('"',1)[0] if text.startswith('"') else text.split(' ',1)[0]
            allowed=Path(executable).resolve() in allowed_processes
            if not allowed:
                raise PermissionError('Media proof refuses an unowned executable')
    sys.addaudithook(guard)
    if sys.platform == 'win32':
        def assigned_pair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
            listener=socket.socket(family,type,proto); client=socket.socket(family,type,proto)
            try:
                listener.bind(('127.0.0.1',args.ipc_port)); listener.listen(1)
                client.connect(('127.0.0.1',args.ipc_port)); accepted,_=listener.accept()
                return accepted,client
            except BaseException:
                client.close(); raise
            finally:
                listener.close()
        socket.socketpair=assigned_pair
    html = b'<!doctype html><html><head><title>FIXCL4 actual media</title><style>body{background:#102230;color:white;font:18px Arial;margin:24px}h1{font-size:32px}.shape{background:#a63249;width:120px;height:120px}button{background:#fff;color:#102230;padding:16px}</style></head><body><h1 data-ready>Actual retained media</h1><p>Fresh rendering and owner bytes.</p><div class="shape"></div><button aria-label="Verify">Verify</button></body></html>'
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/missing':
                self.send_response(404); self.end_headers(); return
            self.send_response(200); self.send_header('Content-Type','text/html'); self.send_header('Content-Length',str(len(html))); self.end_headers(); self.wfile.write(html)
        def log_message(self,*values):
            pass
    server=None
    if not args.local_only:
        server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
    from grant_agent.browser_obscura import ObscuraEngine, ProfileWorker
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.neyvia_manuals import unwrap
    engine=worker=None
    if not args.local_only:
        engine=ObscuraEngine(root/'browser',args.obscura,port=args.browser_port,fixtures=True)
        worker=ProfileWorker(engine.endpoint,engine.token,True,root/'browser/owner')
    result={'schema':'neyvia.FIXCL4.media.v1','root':str(root),'journeys':{},'checks':{},
            'boundary':'Actual explicit non-stealth Neyvia Obscura renderer, actual FFmpeg, disposable CODEX_HOME; visual measurements are not aesthetic certification.'}
    class Runtime:
        browser_starts=1
        contexts_created=1
        @contextmanager
        def page(self,*,width,height):
            worker._connect()
            page=worker.context.new_page(); page.set_viewport_size({'width':width,'height':height})
            try:
                yield page,True
            finally:
                page.close()
        def snapshot(self,*,reused):
            return {**engine.status(),'browserReused':reused,'executable':str(args.obscura)}
    gateway=NeyviaToolGateway(root,allow_mutations=True,action_scope='FIXCL4-media',permission_mode='workspace')
    gateway.native.browser_runtime=Runtime()
    def real(key,name,arguments,goal):
        p=Protocol(gateway,lazy_manuals=True)
        defaults={
            'preview.screenshot':{'fullPage':True,'width':1440,'height':1000,'waitFor':'','delayMs':350,'waitUntil':'domcontentloaded'},
            'preview.annotate':{'comment':'Selected UI region','viewport':{},'delayMs':350},
            'preview.taste':{'goal':'','viewports':['desktop','phone'],'colorScheme':'dark','waitFor':'','delayMs':900,'includeImageData':False,'journey':{}},
            'video.digest':{'maxFrames':12,'maxSceneFrames':8,'sceneThreshold':0.32,'sceneScanSeconds':600,'extractAudio':True,'transcribe':'none','whisperModel':'turbo','timeoutSeconds':1800},
            'skill.live.iterate':{'skillId':'disposable','request':''},
        }
        payload={**defaults.get(name,{}),**arguments}
        # Explicit manual ownership remains unambiguous when design and media
        # workflows both describe the same native capture actions.
        source='G: '+goal+'\nrun local-media.'+name.replace('.','-')+'('+','.join(k+'='+json.dumps(v) for k,v in payload.items())+')\ndone()'
        returned=p.run(source,action_id=key)
        result['journeys'][key]={'source':source,'run':returned}
        result['checks'][key+'.positiveCL']=returned.get('ok') is True and p.completion()['status']=='completed'
        return p
    def drift(key,p,path):
        path=Path(path); original=path.read_bytes(); path.write_bytes(original+b'\nFIXCL4 actual byte drift')
        result['checks'][key+'.artifactDriftRefused']=p.completion()['status']=='incomplete'
        path.write_bytes(original)
        restored=p.run('done()',action_id=key+'-restored')
        result['checks'][key+'.restorationRevalidates']=restored.get('ok') is True and p.completion()['status']=='completed'
        result['journeys'].setdefault(key,{})['restored']=restored
    def previews():
        url=f'http://127.0.0.1:{args.port}/'
        screenshot=root/'proof.png'
        p=real('preview-screenshot','preview.screenshot',{'url':url,'outputPath':str(screenshot),'width':640,'height':480,'fullPage':False,'waitFor':'[data-ready]','delayMs':0}, 'time.now()["unixSeconds"] > 0')
        if result['checks']['preview-screenshot.positiveCL']: drift('preview-screenshot',p,screenshot)
        annotation=root/'annotation'
        p=real('preview-annotate','preview.annotate',{'url':url,'outputDir':str(annotation),'rectangle':{'x':2,'y':25,'width':30,'height':40},'comment':'Actual bounded region','viewport':{'width':640,'height':480},'delayMs':0}, 'time.now()["unixSeconds"] > 0')
        if result['checks']['preview-annotate.positiveCL']: drift('preview-annotate',p,annotation/'region.png')
        taste=root/'taste'
        p=real('preview-taste','preview.taste',{'url':url,'outputDir':str(taste),'viewports':['desktop','phone'],'colorScheme':'dark','waitFor':'[data-ready]','delayMs':0}, 'time.now()["unixSeconds"] > 0')
        if result['checks']['preview-taste.positiveCL']: drift('preview-taste',p,taste/'taste-report.json')
        # Existing bytes do not turn a failed selector wait into a screenshot.
        old=screenshot.read_bytes() if screenshot.exists() else None
        try:
            gateway.native._preview_screenshot({'url':url,'outputPath':str(screenshot),'waitFor':'[absent-real-selector]','delayMs':0})
            refused=False
        except (RuntimeError, PermissionError):
            refused=True
        result['checks']['preview-screenshot.failedRenderPreservesOldBytes']=refused and old is not None and screenshot.exists() and screenshot.read_bytes()==old
    try:
        if not args.local_only:
            worker.executor.submit(previews).result(timeout=210)
        video=root/'source.mp4'
        if ffmpeg and ffprobe:
            subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=320x180:rate=5','-t','2','-c:v','mpeg4','-y',str(video)],check=True,timeout=40,capture_output=True)
            p=real('video-digest','video.digest',{'path':str(video),'outputDir':str(root/'digest'),'maxFrames':3,'maxSceneFrames':0,'extractAudio':False,'transcribe':'none','timeoutSeconds':90},'time.now()["unixSeconds"] > 0')
            if result['checks']['video-digest.positiveCL']:
                drift('video-digest',p,root/'digest/video-digest.json')
                drift('video-input',p,video)
        else:
            result['checks']['video-digest.available']=False
        skill=root/'codex-home/skills/disposable/SKILL.md'; skill.parent.mkdir(parents=True)
        skill.write_text('---\nname: disposable\ndescription: Disposable actual skill revision proof.\n---\nCheck original bytes.\n',encoding='utf-8')
        before=hashlib.sha256(skill.read_bytes()).hexdigest()
        revised='---\nname: disposable\ndescription: Disposable actual skill revision proof.\n---\nCheck exact revised bytes and preserve the original.\n'
        p=real('skill-live-iterate','skill.live.iterate',{'path':str(skill),'content':revised,'expectedSha256':before,'request':'Improve exact retained evidence check'},'skill.live.read(path='+json.dumps(str(skill))+')["content"] == '+json.dumps(revised))
        if result['checks']['skill-live-iterate.positiveCL']:
            drift('skill-live-iterate',p,skill)
            backup=next((root/'.agent_control/skill_revisions/disposable').glob('*-before.md'))
            drift('skill-backup',p,backup)
        conflict=real('skill-conflict','skill.live.iterate',{'path':str(skill),'content':revised+'More.\n','expectedSha256':before},'time.now()["unixSeconds"] > 0')
        result['checks']['skill-conflict.positiveCL']=not result['journeys']['skill-conflict']['run'].get('ok') and skill.read_text(encoding='utf-8')==revised
    finally:
        if worker: worker.close()
        if engine: engine.close()
        if server: server.shutdown(); server.server_close()
    result['ok']=all(result['checks'].values())
    result['sourceHashes']={str(p.relative_to(REPO)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        (Path(__file__),REPO/'src/grant_agent/cl/fixcl4_media_effects.py',REPO/'src/grant_agent/native_tools.py',REPO/'src/grant_agent/skill_iteration.py',REPO/'src/grant_agent/video_tools.py',REPO/'manuals/local-media.manual.json',REPO/'manuals/cl/local-media.cl')}
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--browser-port',type=int,required=True)
    parser.add_argument('--ipc-port',type=int,required=True)
    parser.add_argument('--obscura',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--local-only',action='store_true',help='Run actual video/skill owners without launching the browser')
    args=parser.parse_args()
    source_paths=(Path(__file__),REPO/'src/grant_agent/cl/fixcl4_media_effects.py',REPO/'src/grant_agent/native_tools.py',REPO/'src/grant_agent/skill_iteration.py',REPO/'src/grant_agent/video_tools.py',REPO/'manuals/local-media.manual.json',REPO/'manuals/cl/local-media.cl')
    source_start={str(path.relative_to(REPO)):hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    observed=run(args)
    observed['sourceHashesAtStart']=source_start
    observed['sourceHashesAtEnd']=observed['sourceHashes']
    observed['checks']['sourceUnchanged']=source_start==observed['sourceHashesAtEnd']
    observed['ok']=all(observed['checks'].values())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(observed,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'ok':observed['ok'],'checks':observed['checks']}))
    raise SystemExit(0 if observed['ok'] else 1)
