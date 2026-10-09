"""Supplemental live layer coverage: T16 OS/UIA, video, cache and restart."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
os.environ['PYTHONDONTWRITEBYTECODE']='1'
from prove_t18_perception import PYTHON,T16,native_fixture,write
from t18_eval_mcp import Bridge
from grant_agent.neyvia_perception import call,browsers
from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent import manual_state
ROOT=REPO/'scripts/evidence/.t18-layers'
ROOT.mkdir(parents=True,exist_ok=True)
rows=[]


def gate(name,passed,details):
    rows.append({'name':name,'passed':bool(passed),'details':details})


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        raw=b'<html><title>Video sample</title><body style="font:32px Arial"><h1>Video receipt</h1><p>Frame sample 42</p><label>Password<input type="password" value="synthetic-canary-t18"></label></body></html>'
        self.send_response(200); self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def log_message(self,*_):pass


server=ThreadingHTTPServer(('127.0.0.1',48203),Page)
threading.Thread(target=server.serve_forever,daemon=True).start()
fixture=None; bridge=None; browser=None
try:
    fixture,hwnd=native_fixture(ROOT)
    bridge=Bridge({'root':str(ROOT),'task':'native','lane':'text','window_id':hwnd,'t16Source':str(T16/'src')})
    w=bridge.workspace
    native=call(w,'perception.observe',{'layer':'window','source':bridge.source,'reset':True})
    native_value=manual_state.read(ROOT/'.neyvia/perception',native['handle'])['value']['state']
    gate('native-exact-uia-and-passive-text',any(e.get('value')=='initial' for e in native_value['elements']) and 'Text "Waiting"' in native_value['textTree'],native)
    os_state=call(w,'perception.observe',{'layer':'os','source':{'sessionId':bridge.source['sessionId']},'reset':True})
    windows=manual_state.read(ROOT/'.neyvia/perception',os_state['handle'])['value']['state']['windows']
    gate('os-t16-authorized-windows',any(int(r['window_id'])==hwnd for r in windows),{'count':len(windows),'target':hwnd,'observation':os_state})
    proc=w.call('manual.run',{'id':'perception','chapter':'window','procedure':'read-layer','inputs':{'source':bridge.source}})
    gate('native-executable-manual',proc.get('status')=='completed' and all(c['passed'] for c in proc['checks']),proc)
    # A fresh process projects an existing handle through the production module.
    fresh=subprocess.run([PYTHON,'-c',"import json,sys; from pathlib import Path; from grant_agent.neyvia_workspace_tools import workspace_for; from grant_agent.neyvia_perception import call; print(json.dumps(call(workspace_for(Path(sys.argv[1])),'perception.project',{'handle':sys.argv[2],'path':'/state/elements/0/value'})))",str(ROOT),native['handle']],
        env={**os.environ,'PYTHONPATH':str(REPO/'src')},capture_output=True,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
    projected=json.loads(fresh.stdout)
    gate('handle-survives-process-restart',projected['value']=='initial',projected)
    b=call(w,'perception.browser.open',{'url':'http://127.0.0.1:48203/'})['browserId']
    observed=call(w,'perception.observe',{'layer':'browser','source':{'browserId':b},'reset':True})
    value=manual_state.read(ROOT/'.neyvia/perception',observed['handle'])['value']
    gate('password-value-redacted','synthetic-canary-t18' not in json.dumps(value),{'redacted':any(e.get('value')=='[redacted]' for e in value['state']['elements'])})
    browser=browsers(w)
    def record():
        context=browser.browser.new_context(record_video_dir=str(ROOT/'recorded'),record_video_size={'width':640,'height':480})
        page=context.new_page();page.goto('http://127.0.0.1:48203/');page.wait_for_timeout(1400)
        video=page.video;context.close();return video.path()
    clip=browser.worker.submit(record).result(timeout=30)
    shutil.copy2(clip,ROOT/'sample.webm')
    video=call(w,'perception.observe',{'layer':'video','source':{'path':'sample.webm','frame':15},'reset':True})
    decoded=manual_state.read(ROOT/'.neyvia/perception',video['handle'])['value']['state']
    gate('real-recorded-video-frame',decoded.get('video',{}).get('frame')==15 and any('Video receipt' in t['text'] for t in decoded['text']),video)
    call(w,'perception.browser.close',{'browserId':b})
    shutil.copy2(REPO/'scripts/evidence/.t18-runtime/chart.png',ROOT/'chart.png')
    # Carry forward the real schema-checked cache, not a fabricated transcript.
    shutil.copytree(REPO/'scripts/evidence/.t18-runtime/.neyvia/perception-visual/cache',ROOT/'.neyvia/perception-visual/cache',dirs_exist_ok=True)
    first=call(w,'perception.observe',{'layer':'image','source':{'path':'chart.png'},'reset':True})
    second=call(w,'perception.observe',{'layer':'image','source':{'path':'chart.png'}})
    gate('visual-cache-explicit-zero-current-tokens',first['extraction']['cacheHit'] and first['extraction']['currentUsage']['input_tokens']==0 and second.get('diff')==[],{'first':first,'second':second})
    try:
        call(w,'perception.observe',{'layer':'file','source':{'path':'chart.png'}})
        gate('binary-file-explicit-failure',False,{})
    except UnicodeDecodeError:
        gate('binary-file-explicit-failure',True,'Binary was not presented as text')
finally:
    if bridge:bridge.close()
    if fixture:fixture.terminate();fixture.wait(timeout=15)
    server.shutdown();server.server_close()
    write(REPO/'scripts/evidence/T18-layers.json',{'ports':[48203],'gates':rows,'allPassed':bool(rows) and all(r['passed'] for r in rows)})
print(json.dumps({'passed':sum(r['passed'] for r in rows),'total':len(rows)}))
raise SystemExit(0 if rows and all(r['passed'] for r in rows) else 1)
