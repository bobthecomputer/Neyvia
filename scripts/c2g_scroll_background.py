"""Actual screenshot regression: ordinary scroll versus same-document fragment."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from PIL import Image

repo=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(repo/'src'))
from grant_agent.browser_obscura import ObscuraEngine
os.environ['NEYVIA_BROWSER_PROOF_PORTS']='48725,48726'
executable=Path(sys.argv[1]).resolve()
phase=sys.argv[2]
if phase not in {'before','after'}:raise ValueError('Explicit before or after phase required')
stem='C2g-scroll-background-'+phase
report={'schema':'neyvia.C2g.scroll-background@1','engine':'Obscura','stealth':False,'phase':phase,'executable':str(executable.relative_to(repo)),'engineSha256':hashlib.sha256(executable.read_bytes()).hexdigest(),'ports':[48725,48726],'startedAt':time.time(),'captures':{},'checks':[]}
html=b'''<!doctype html><html><head><style>body{font:24px sans-serif;background:white;color:black}@media(prefers-color-scheme:dark){body{background:rgb(16,32,48);color:white}}#target{margin-top:1800px}</style></head><body><h1>Retained dark canvas</h1><a href=#target>Jump to retained target</a><h2 id=target>Retained target</h2><script>window.sameDocumentToken='retained';</script></body></html>'''
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(html)));self.end_headers();self.wfile.write(html)
server=ThreadingHTTPServer(('127.0.0.1',48725),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
engine=None
def check(name,ok,detail=None):
    report['checks'].append({'name':name,'ok':bool(ok),'detail':detail})
    if not ok:raise AssertionError(name)
try:
    engine=ObscuraEngine(repo/'.agent_control/C2g'/stem,executable,port=48726,fixtures=True,color_scheme='dark',reduced_motion='reduce')
    engine.run('render','open','canvas','http://127.0.0.1:48725/')
    worker=engine.profiles['render']
    def evaluate(code):return worker.executor.submit(lambda:worker.pages['canvas']['page'].evaluate(code)).result(timeout=30)
    def capture(label):
        frame=engine.run('render','frame','canvas');data=base64.b64decode(frame['dataUrl'].split(',')[1]);file=repo/'scripts/evidence'/(stem+'-'+label+'.png');file.write_bytes(data)
        image=Image.open(io.BytesIO(data)).convert('RGBA');width,height=image.size
        pixels=[list(image.getpixel((x,y))) for x,y in [(width-10,10),(width-10,height//2),(width-10,height-10),(width//2,height//2)]]
        state=evaluate('() => ({hash:location.hash,token:sameDocumentToken,scrollY,background:getComputedStyle(document.body).backgroundColor,color:getComputedStyle(document.body).color})')
        report['captures'][label]={'path':str(file.relative_to(repo)),'sha256':hashlib.sha256(data).hexdigest(),'samples':pixels,'state':state}
        return pixels,state
    pixels,state=capture('initial');check('Initial viewport uses real dark canvas pixels',all(pixel==[16,32,48,255] for pixel in pixels),state)
    evaluate('() => scrollTo(0,1800)');pixels,state=capture('ordinary-scroll');check('Ordinary large scroll keeps dark canvas pixels',state['scrollY']>1000 and all(pixel==[16,32,48,255] for pixel in pixels),state)
    evaluate('() => scrollTo(0,0)');observation=engine.run('render','observe','canvas');link=next(e for e in observation['elements'] if e['name']=='Jump to retained target')
    linked=engine.run('render','action','canvas',{'revision':observation['revision'],'element':link['id'],'action':'click','expect':{'path':'/url','contains':'#target'}})
    pixels,state=capture('fragment');check('Fragment stays in actual original document with dark computed CSS',linked['ok'] and state['token']=='retained' and state['hash']=='#target' and state['background']=='rgb(16, 32, 48)',state)
    expected=[255,255,255,255] if phase=='before' else [16,32,48,255]
    check('Original fragment capture reproduces light fallback' if phase=='before' else 'Fragment capture retains dark canvas pixels across whole viewport',all(pixel==expected for pixel in pixels),pixels)
except BaseException as error:
    report['error']=repr(error);raise
finally:
    if engine:engine.close()
    server.shutdown();server.server_close();report['finishedAt']=time.time();report['cleanup']={'engineStopped':engine is None or engine.process.poll() is not None,'fixtureClosed':True}
    (repo/'scripts/evidence'/(stem+'.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'phase':phase,'checks':report['checks'],'error':report.get('error'),'cleanup':report['cleanup']}))
