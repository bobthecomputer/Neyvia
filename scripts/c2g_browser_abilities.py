"""Actual owned Obscura network/render/DOM browser abilities, no mock result."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

repo=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(repo/'src'))
from grant_agent.browser_obscura import ObscuraEngine
from grant_agent.perception_browser import DOM

os.environ['NEYVIA_BROWSER_PROOF_PORTS']='48725,48726'
executable=Path(sys.argv[1]).resolve()
out=repo/'scripts/evidence'/(sys.argv[2] if len(sys.argv)>2 else 'C2g-browser-abilities.json')
if out.parent.resolve()!= (repo/'scripts/evidence').resolve():raise ValueError('Feature receipts stay in scripts/evidence')
preference_capture_name='C2g-browser-preferences.png' if out.name=='C2g-browser-abilities.json' else out.stem+'-preferences.png'
capture_name='C2g-browser-abilities.png' if out.name=='C2g-browser-abilities.json' else out.stem+'.png'
report={'schema':'neyvia.C2g.browser-abilities@1','engine':'Obscura','stealth':False,'executable':str(executable.relative_to(repo)),
        'engineSha256':hashlib.sha256(executable.read_bytes()).hexdigest(),'startedAt':time.time(),'ports':[48725,48726],'checks':[],'requests':[]}
font=next((repo/'.agent_control/C2f/build/assets').glob('geist-latin-wght-normal-*.woff2')).read_bytes()
html='''<!doctype html><html><head><title>Actual browser abilities</title><style>
@font-face{font-family:C2gProof;src:url('/proof.woff2')}body{font:20px C2gProof;background:white;color:black}
#mode{width:100px}@media(prefers-color-scheme:dark){body{background:rgb(16,32,48);color:white}#mode{width:240px}}
#motion{width:100px}@media(prefers-reduced-motion:reduce){#motion{width:40px}}
#target{margin-top:1800px}</style></head><body><h1>Actual browser abilities</h1><div id=mode>Color scheme</div><div id=motion>Motion</div>
<p id=events>Events pending</p><span id=glyphs style="display:inline-block">MWMWMWiiiiii</span><span id=fallback style="display:inline-block;font-family:serif">MWMWMWiiiiii</span><div draggable=true id=source ondragstart="event.dataTransfer.setData('text/plain','actual drag payload')">Drag this</div>
<div role=button id=drop ondragover="event.preventDefault()" ondrop="document.getElementById('dragresult').textContent=event.dataTransfer.getData('text/plain')">Drop here</div><p id=dragresult>No drop</p>
<a href=#target>Jump in page</a><h2 id=target>In-page target</h2><script>
window.sameDocumentToken='kept';window.featureState={events:[],firstEventAt:null,font:'pending',badMimeError:false,badMimeOpened:false,cancelEvents:[]};
const source=new EventSource('/events');source.onmessage=e=>{featureState.events.push(e.data);if(!featureState.firstEventAt)featureState.firstEventAt=Date.now();document.getElementById('events').textContent=featureState.events.join('|');if(featureState.events.length===2)source.close();};
document.fonts.load('20px C2gProof').then(f=>{featureState.font=f.map(x=>x.status).join(',');document.getElementById('events').setAttribute('data-font',featureState.font);});
const invalid=new EventSource('/bad-events');invalid.onopen=()=>{featureState.badMimeOpened=true;invalid.close();};invalid.onerror=()=>{featureState.badMimeError=true;invalid.close();};
const cancelled=new EventSource('/cancel-events');cancelled.onmessage=e=>{featureState.cancelEvents.push(e.data);cancelled.close();};
</script></body></html>'''
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        report['requests'].append({'path':self.path,'at':time.time()})
        self.send_response(200)
        if self.path in {'/events','/cancel-events'}:
            self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-cache');self.end_headers()
            try:
                time.sleep(.15);self.wfile.write(b'id: 1\ndata: first real streamed message\n\n');self.wfile.flush()
                if self.path=='/events':report['firstChunkSentAt']=time.time()
                time.sleep(2);self.wfile.write(b'id: 2\ndata: second real streamed message\n\n');self.wfile.flush()
                if self.path=='/events':report['secondChunkSentAt']=time.time()
                time.sleep(2)
                if self.path=='/events':report['streamClosedAt']=time.time()
            except (ConnectionError,OSError):report['streamClientClosed']=True
        elif self.path=='/bad-events':
            content=b'Not an event stream';self.send_header('Content-Type','text/plain');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
        elif self.path=='/proof.woff2':
            self.send_header('Content-Type','font/woff2');self.send_header('Content-Length',str(len(font)));self.end_headers();self.wfile.write(font)
        else:
            content=html.encode();self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)

def save():out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
def check(name,ok,detail=None):
    report['checks'].append({'name':name,'ok':bool(ok),'detail':detail});save()
    if not ok:raise AssertionError(name)

server=ThreadingHTTPServer(('127.0.0.1',48725),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
engine=None
try:
    engine=ObscuraEngine(repo/'.agent_control/C2g/ability-engine',executable,port=48726,fixtures=True,color_scheme='dark',reduced_motion='reduce')
    observation=engine.run('features','open','abilities','http://127.0.0.1:48725/')
    worker=engine.profiles['features']
    def evaluate(script):return worker.executor.submit(lambda:worker.pages['abilities']['page'].evaluate(script)).result(timeout=30)
    deadline=time.monotonic()+12;state={}
    while time.monotonic()<deadline:
        state=evaluate('() => ({...featureState,dark:matchMedia("(prefers-color-scheme: dark)").matches,reduce:matchMedia("(prefers-reduced-motion: reduce)").matches,mode:getComputedStyle(document.getElementById("mode")).width,motion:getComputedStyle(document.getElementById("motion")).width,bg:getComputedStyle(document.body).backgroundColor})')
        if state['events']:break
        time.sleep(.05)
    check('SSE first message delivered while response still open',bool(state.get('events')) and not report.get('secondChunkSentAt') and not report.get('streamClosedAt'),state)
    check('Dark preference matches rendered CSS',state['dark'] and state['mode']=='240px',state)
    check('Reduced motion preference matches rendered CSS',state['reduce'] and state['motion']=='40px',state)
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        state=evaluate('() => ({...featureState,fontCheck:document.fonts.check("20px C2gProof"),glyphWidth:document.getElementById("glyphs").getBoundingClientRect().width,fallbackWidth:document.getElementById("fallback").getBoundingClientRect().width})')
        if len(state['events'])==2 and state['font']=='loaded':break
        time.sleep(.05)
    check('SSE second chunk independently delivered in order',state['events']==['first real streamed message','second real streamed message'],state)
    check('Invalid SSE content type refuses fake open and emits error',state['badMimeError'] and not state['badMimeOpened'],state)
    check('EventSource close cancels later chunks without reconnect',state['cancelEvents']==['first real streamed message'] and len([row for row in report['requests'] if row['path']=='/cancel-events'])==1,state)
    check('Web font bytes fetched and FontFace load completed',state['font']=='loaded' and any(x['path']=='/proof.woff2' for x in report['requests']),state)
    check('Loaded web font changes real glyph layout versus serif fallback',abs(state['glyphWidth']-state['fallbackWidth'])>1,state)
    frame=engine.run('features','frame','abilities');png=repo/'scripts/evidence'/preference_capture_name;png.write_bytes(base64.b64decode(frame['dataUrl'].split(',')[1]));report['preferenceCapture']={'path':str(png.relative_to(repo)),'sha256':hashlib.sha256(png.read_bytes()).hexdigest(),'bytes':png.stat().st_size}
    observation=engine.run('features','observe','abilities')
    source=next(e for e in observation['elements'] if e['name']=='Drag this')
    drop=next(e for e in observation['elements'] if e['name']=='Drop here')
    dragged=engine.run('features','action','abilities',{'revision':observation['revision'],'element':source['id'],'destination':drop['id'],'action':'drag','expect':{'path':'/text','contains':'actual drag payload'}})
    check('Observed DOM drag transfers actual data to drop handler',dragged['ok'],dragged)
    observation=engine.run('features','observe','abilities')
    link=next(e for e in observation['elements'] if e['name']=='Jump in page')
    linked=engine.run('features','action','abilities',{'revision':observation['revision'],'element':link['id'],'action':'click','expect':{'path':'/url','contains':'#target'}})
    fragment=evaluate('() => ({hash:location.hash,token:window.sameDocumentToken,targetY:document.getElementById("target").getBoundingClientRect().top,targetHeight:document.getElementById("target").getBoundingClientRect().height,viewportHeight:innerHeight,scrollY})')
    check('In-page link retains document and scrolls whole target into viewport',linked['ok'] and fragment['token']=='kept' and fragment['targetY']>=0 and fragment['targetY']+fragment['targetHeight']<=fragment['viewportHeight'],fragment)
    frame=engine.run('features','frame','abilities');png=repo/'scripts/evidence'/capture_name;png.write_bytes(base64.b64decode(frame['dataUrl'].split(',')[1]));report['capture']={'path':str(png.relative_to(repo)),'sha256':hashlib.sha256(png.read_bytes()).hexdigest(),'bytes':png.stat().st_size}
except BaseException as error:
    report['error']=repr(error);raise
finally:
    if engine:engine.close()
    server.shutdown();server.server_close();report['finishedAt']=time.time();report['cleanup']={'engineStopped':engine is None or engine.process.poll() is not None,'fixtureClosed':True};save()
    print(json.dumps({'checks':report['checks'],'error':report.get('error'),'cleanup':report['cleanup']}))
