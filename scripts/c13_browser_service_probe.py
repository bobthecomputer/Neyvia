"""Exercise actual production Obscura capture and touch-input routes, hidden only."""
from __future__ import annotations
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

WT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(WT/'src'))
from grant_agent.subprocess_utils import install_hidden_subprocess_default
from grant_agent.neyvia_browser import BrowserService
import os

FONT=Path('C:/Windows/Fonts/comic.ttf').read_bytes()
HTML=b'''<!doctype html><html><head><style>@font-face{font-family:Proof;src:url('/font.ttf')}body{background:white;color:black}@media(prefers-color-scheme:dark){body{background:rgb(1,2,3);color:white}}@media(prefers-reduced-motion:reduce){#glyphs{animation:none}}p{font:40px Proof}button{width:200px;height:100px}a{display:block}#target{margin-top:1200px}</style></head><body><button id="button" onclick="counter.textContent=String(Number(counter.textContent)+1)">Increment</button><output id="counter">0</output><p id="glyphs">Font glyphs WMWMMi</p><a href="#target">Jump</a><div id="target">Target</div><script>window.dragged=false;button.addEventListener('pointerdown',e=>button.setPointerCapture(e.pointerId));button.addEventListener('pointermove',e=>{if(button.hasPointerCapture(e.pointerId)){dragged=true;counter.textContent='dragged';}});</script></body></html>'''


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        data=FONT if self.path=='/font.ttf' else HTML
        self.send_response(200)
        self.send_header('Content-Type','font/ttf' if self.path=='/font.ttf' else 'text/html')
        self.end_headers();self.wfile.write(data)
    def log_message(self,*args):
        pass


def main():
    install_hidden_subprocess_default()
    os.environ['NEYVIA_OBSCURA_EXE']=str(WT/'scripts/evidence/c13-runtime/obscura-v0.2.4/obscura.exe')
    output=WT/'scripts/evidence/c13-browser-probe/service'
    service=BrowserService(output)
    server=ThreadingHTTPServer(('127.0.0.1',48808),Fixture)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    evidence={}
    try:
        evidence['start']=service.request('headless.start',{'port':48809,'allowLocalFixtures':True,
            'renderProfile':{'theme':'dark','reducedMotion':True,'allowPublicSubresources':True}},owner=True)
        tab=service.request('tab.open',{'url':'http://127.0.0.1:48808/','engine':'obscura'},owner=True)
        evidence['open']=tab
        tid=tab['tabId']
        evidence['capture']=service.request('capture',{'tabId':tid},owner=True)
        capture=evidence['capture']
        assert hashlib.sha256(Path(capture['path']).read_bytes()).hexdigest()==capture['sha256']
        for name,params in [('touchstart',{'type':'touchStart','touchPoints':[{'x':100,'y':50}]}),
                            ('drag',{'type':'touchMove','touchPoints':[{'x':450,'y':200}]}),
                            ('touchend',{'type':'touchEnd','touchPoints':[]})]:
            evidence[name]=service.request('input',{'tabId':tid,'input':params},owner=True)
            assert evidence[name]['ok']
        observation=service.request('observe',{'tabId':tid},owner=True)
        evidence['observed_drag_effect']='dragged' in observation['text']
        evidence['render_profile']=observation['renderProfile']
        assert evidence['observed_drag_effect']
        evidence['capture_after']=service.request('capture',{'tabId':tid},owner=True)
        evidence['before_after_pixels_differ']=capture['sha256']!=evidence['capture_after']['sha256']
        assert evidence['before_after_pixels_differ']
        link=next(element for element in observation['elements'] if element['name']=='Jump')
        navigation=service.request('action',{'tabId':tid,'element':link['id'],
            'revision':observation['revision'],'action':'click'},owner=True)
        evidence['fragment_navigation']={'url':navigation['observation']['url'],
            'scrollY':navigation['observation']['renderProfile']['scrollY']}
        assert evidence['fragment_navigation']['url'].endswith('#target') and evidence['fragment_navigation']['scrollY']>100
        evidence['passed']=True
    finally:
        service.request('headless.stop',owner=True)
        server.shutdown()
        (WT/'scripts/evidence/C13-browser-service.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':evidence.get('passed',False),'receipt':'scripts/evidence/C13-browser-service.json'}))


if __name__=='__main__':
    main()
