"""Matched ordinary page-load/fetch probe; no extrapolation to public-task latency."""
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

repo=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(repo/'src'))
from grant_agent.browser_obscura import ObscuraEngine
os.environ['NEYVIA_BROWSER_PROOF_PORTS']='48725,48726'
report={'schema':'neyvia.C2g.ordinary-latency@1','boundary':'Local matched ordinary HTML, external script and JSON fetch only; excludes public sites, models and native startup','ports':[48725,48726],'stealth':False,'rows':[],'requests':[],'startedAt':time.time()}
html=b'''<!doctype html><html><head><title>Ordinary loading</title><script src=/ordinary.js></script></head><body><h1 id=result>Loading ordinary payload</h1><script>fetch('/ordinary.json').then(r=>r.json()).then(v=>{document.getElementById('result').textContent=v.label+': '+externalScript;});</script></body></html>'''
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        if self.path=='/ordinary.js':content=b'window.externalScript="real ordinary script";';kind='text/javascript'
        elif self.path=='/ordinary.json':content=json.dumps({'label':'Real ordinary payload','padding':'x'*10000}).encode();kind='application/json'
        else:content=html;kind='text/html'
        report['requests'].append({'path':self.path,'mime':kind,'bytes':len(content)});self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
server=ThreadingHTTPServer(('127.0.0.1',48725),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
engine=None
try:
    for label,executable in zip(['C2f','C2g','C2f-repeat','C2g-repeat'],[sys.argv[1],sys.argv[2],sys.argv[1],sys.argv[2]]):
        executable=Path(executable).resolve();entry={'engine':label,'executable':str(executable.relative_to(repo)),'sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),'milliseconds':[]};report['rows'].append(entry)
        engine=ObscuraEngine(repo/'.agent_control/C2g/ordinary-latency'/label,executable,port=48726,fixtures=True)
        for index in range(6):
            started=time.perf_counter();tab='ordinary-'+str(index);observation=engine.run('timing','open',tab,'http://127.0.0.1:48725/')
            deadline=time.monotonic()+10
            while 'Real ordinary payload: real ordinary script' not in observation['text'] and time.monotonic()<deadline:
                observation=engine.run('timing','observe',tab);time.sleep(.01)
            if 'Real ordinary payload: real ordinary script' not in observation['text']:raise AssertionError('Actual external script and ordinary JSON fetch missing')
            entry['milliseconds'].append(round((time.perf_counter()-started)*1000,3));engine.run('timing','close',tab)
        entry['warmMedianMs']=statistics.median(entry['milliseconds'][1:]);engine.close();engine=None
    report['medianByEngine']={name:statistics.median([value for row in report['rows'] if row['engine'].startswith(name) for value in row['milliseconds'][1:]]) for name in ['C2f','C2g']}
    report['requestsAreOrdinary']=all(row['mime']!='text/event-stream' for row in report['requests'])
except BaseException as error:
    report['error']=repr(error);raise
finally:
    if engine:engine.close()
    server.shutdown();server.server_close();report['finishedAt']=time.time();report['cleanup']={'engineStopped':engine is None or engine.process.poll() is not None,'fixtureClosed':True}
    (repo/'scripts/evidence/C2g-engine-ordinary-latency.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'medianByEngine':report.get('medianByEngine'),'error':report.get('error'),'cleanup':report['cleanup']}))
