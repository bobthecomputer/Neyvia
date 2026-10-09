"""Actual generated vote pages, persistence and refusal in isolated Neyvia WebView2."""
import argparse
import ctypes
from ctypes import wintypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.durability import atomic_write_json
from c9c_native import NativeProcess

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backend-port", type=int, required=True)
    p.add_argument("--fixture-port", type=int, required=True)
    p.add_argument("--native", type=Path, required=True)
    args = p.parse_args()
    if len({args.backend_port,args.fixture_port}) != 2 or not {args.backend_port,args.fixture_port} <= set(range(48761,48770)):
        raise ValueError("Distinct explicit C9c ports required")
    output = REPO / "scripts/evidence/C9c-voting-native.json"
    build = REPO / "scripts/evidence/C9c-voting-builds"
    reports = {}
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*a,**kw): super().__init__(*a,directory=str(build),**kw)
        def do_GET(self):
            if self.path in {"/r5/index.html","/r6/index.html"}:
                round_name = self.path.split('/')[1]
                raw = (build / round_name / "index.html").read_text(encoding="utf-8")
                diagnostic = "<script>setInterval(()=>fetch('/report?"+round_name+"',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({saved:localStorage.getItem('"+round_name+"votes')})}).catch(()=>{}),150)</script>"
                body = (raw + diagnostic).encode()
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
                self.send_header("Content-Security-Policy", "default-src 'self' data: blob: 'unsafe-inline'; connect-src 'self'")
                self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
            else: super().do_GET()
        def do_POST(self):
            key=self.path.split('?')[-1]
            if key not in {"r5","r6"}: self.send_error(400); return
            value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            reports[key] = json.loads(value['saved'] or '{}')
            self.send_response(200); self.end_headers()
        def log_message(self,*_): pass
    fixture=ThreadingHTTPServer(('127.0.0.1',args.fixture_port),Handler)
    thread=threading.Thread(target=fixture.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{args.backend_port}'; cookie=''
    def req(path,value):
        request=Request(base+path,json.dumps(value).encode(),{'Content-Type':'application/json',**({'Cookie':cookie} if cookie else {})})
        with urlopen(request,timeout=35) as response:return json.load(response),response.headers
    data,headers=req('/api/auth/local-session',{});assert data['ok'];cookie=headers['Set-Cookie'].split(';')[0]
    def browser(op,value=None):
        data,_=req('/api/ui/browser',{'op':op,'args':value or {}});assert data.get('ok') is not False,data
        return data
    def wait(value):
        if 'actionId' not in value:return value
        until=time.monotonic()+35
        while time.monotonic()<until:
            row=browser('action.get',{'actionId':value['actionId']})
            if row['status']=='failed':raise ValueError(str(row.get('error')))
            if row['status']=='done':return row
            time.sleep(.1)
        raise TimeoutError('Native voting action did not return')
    def observe(tab):return wait(browser('observe',{'tabId':tab}))['result']['observation']
    grant=browser('runtime.connect')
    native=NativeProcess(args.native,REPO,{**os.environ,'NEYVIA_BROWSER_BASE':base,'NEYVIA_BROWSER_TOKEN':grant['token'],'NEYVIA_BROWSER_PROOF_SCOPE':'C9c'})
    receipt={'schema':'neyvia.C9c-voting-native.v1','rounds':[],'agentDesktop':native.verified_name,
             'boundary':'Actual generated pages and ordinary native localStorage; shared cloud deliberately blocked; no page state reinserted'}
    try:
        for round_name in ('r5','r6'):
            tab=browser('tab.open',{'url':f'http://127.0.0.1:{args.fixture_port}/{round_name}/index.html','engine':'webview2'})['tabId']
            wait(browser('layout',{'tabs':[{'tabId':tab,'x':0,'y':0,'width':1280,'height':1500,'visible':True}]}))
            time.sleep(.6)
            before=observe(tab)
            choices=[e for e in before['elements'] if e['role']=='combobox' and e['name']=='Which is better?']
            assert len(choices)>=2
            assert all(not e['enabled'] for e in before['elements'] if e['name'] in ('A is Claude','B is Claude'))
            browser('tab.grant',{'tabId':tab,'enabled':True})
            def action(name,role,verb,value=None,index=0):
                for _ in range(8):
                    obs=observe(tab);element=[e for e in obs['elements'] if e['name']==name and e['role']==role][index]
                    try:
                        result=wait(browser('action',{'tabId':tab,'revision':obs['revision'],'element':element['id'],'action':verb,**({'value':value} if value is not None else {})}))
                        assert result['result'].get('ok') is not False,result
                        return
                    except Exception as exc:
                        if 'stale' not in str(exc).lower():raise
                        time.sleep(.15)
                raise ValueError('Voting state never settled')
            action('Which is better?','combobox','select','B')
            action('A is Claude','button','click')
            action('Which is better?','combobox','select','tie',index=1)
            action('B is Claude','button','click',index=1)
            time.sleep(.5)
            saved=reports[round_name]
            assert len(saved)==2 and {v['preference'] for v in saved.values()}=={'B','tie'}
            assert all(v['preferenceCollectedBlind'] and v['schema']=='neyvia.preference-vote.v2' for v in saved.values())
            before_reload=observe(tab)
            wait(browser('tab.reload',{'tabId':tab}));time.sleep(.8)
            after=observe(tab)
            assert reports[round_name]==saved
            assert 'You preferred B.' in after['text'] and 'You preferred neither: about equal.' in after['text']
            assert all(not e['enabled'] for e in after['elements'] if e['name'] in ('A is Claude','B is Claude'))
            captured=wait(browser('capture',{'tabId':tab}))
            source=Path(captured['result']['path']);dest=REPO/'scripts/evidence/C9c-runs/voting-images'/f'{round_name}-reloaded.png'
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(source.read_bytes())
            receipt['rounds'].append({'round':round_name,'savedVotes':saved,'beforeReload':before_reload,'afterReload':after,
                                      'screenshot':str(dest.relative_to(REPO)),'passed':True})
            browser('tab.close',{'tabId':tab})
            atomic_write_json(output,receipt)
        receipt['passed']=True
    finally:
        native.terminate();native.wait(15);receipt['desktopHandleClosed']=native.close()
        fixture.shutdown();fixture.server_close();thread.join(timeout=2)
        receipt['fixtureStopped']=not thread.is_alive()
        atomic_write_json(output,receipt)
    print(json.dumps({'nativeVotingReload':receipt.get('passed',False),'rounds':len(receipt['rounds'])}))

if __name__=='__main__':main()
