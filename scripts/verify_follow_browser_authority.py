"""Owned installed-Chrome journeys plus actual HTTP origin/authority gates."""
from __future__ import annotations
import ast
import hashlib
import http.cookiejar
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import uuid
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
SCRATCH = REPO/".agent_control/follow-browser-authority"
OUTPUT = REPO/"scripts/evidence/FOLLOW-browser-authority.json"
BASE = "6985353d"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

def owned_socketpair(*args, **kwargs):
    listener=socket.socket(); listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    listener.bind(("127.0.0.1",48448)); listener.listen(1)
    writer=socket.socket()
    try:
        writer.connect(("127.0.0.1",48448)); reader,_=listener.accept(); return reader,writer
    except BaseException: writer.close(); raise
    finally: listener.close()

def isolate():
    import verify_follow_failures as proof
    proof.SCRATCH=SCRATCH; proof.isolate()
    os.environ.update(TEMP=str(SCRATCH/"temporary"),TMP=str(SCRATCH/"temporary"),
                      PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=str(CHROME))
    socket.socketpair=owned_socketpair
    # Select the already-installed executable without an ambient `--version`
    # probe. The following real worker launch proves this executable works.
    from grant_agent import neyvia_extension_worker
    neyvia_extension_worker.build_browser_dependency_preflight=lambda root:{"chromeExecutable":str(CHROME)}

def load(name):
    spec=importlib.util.spec_from_file_location("follow_"+name,REPO/"tests"/(name+".py"))
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

def preservation_and_replay():
    rows=[r for r in json.loads((REPO/"scripts/evidence/FOLLOW-failures.json").read_text())["cases"] if r["rootCauseGroup"]=="local-browser-authority"]
    assert len(rows)==4
    result=[]
    for row in rows:
        file,name=row["id"].split("::"); module=load(Path(file).stem)
        old=ast.parse(subprocess.check_output(["git","show",BASE+":"+file],cwd=REPO).decode())
        new=ast.parse((REPO/file).read_text())
        def assertions(tree):
            fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            return [ast.dump(n,include_attributes=False) for n in ast.walk(fn) if isinstance(n,ast.Assert)]
        before,after=assertions(old),assertions(new)
        assert all(a in after for a in before),"Original authority/residency assertion removed"
        with tempfile.TemporaryDirectory(prefix="browser-case-") as directory:
            import inspect
            fn=getattr(module,name)
            values={"tmp_path":Path(directory)}
            fn(**{k:values[k] for k in inspect.signature(fn).parameters})
        result.append({"id":row["id"],"passed":True,"originalAssertNodesPreserved":len(before),
                       "realChrome":file.endswith("test_neyvia_extensions.py"),"boundary":"Owned local Chrome worker" if file.endswith("test_neyvia_extensions.py") else "Original resident-page fixture uses current exact locator seam"})
        print(name+": passed",flush=True)
    return result

def http_proof():
    from grant_agent import web_backend
    from grant_agent.local_browser_authority import approved_browser_url
    from grant_agent.neyvia_browser import service_for
    root=SCRATCH/"http"; root.mkdir(parents=True,exist_ok=True)
    config=root/"config"; config.mkdir(exist_ok=True)
    (config/"neyvia_browser_authority.json").write_text(json.dumps({"schema":"neyvia.browser-authority.v1","proofPorts":[48446]}))
    html=b'''<title>Owned authority proof</title><main><label>Email <input aria-label="Email"></label><button onclick="document.getElementById('result').textContent='Saved'">Save</button><p id="result">Ready</p></main>'''
    fetched_untrusted=[]
    class FixturePage(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path=="/forbidden/redirect-target":fetched_untrusted.append(self.path)
            if self.path=="/control/redirect-route":
                self.send_response(302); self.send_header("Location","http://127.0.0.1:48446/forbidden/redirect-target"); self.send_header("Content-Length","0"); self.end_headers(); return
            if self.path=="/control/redirect":
                self.send_response(302); self.send_header("Location","http://127.0.0.1:48447/control/untrusted"); self.send_header("Content-Length","0"); self.end_headers(); return
            self.send_response(200); self.send_header("Content-Type","text/html"); self.send_header("Content-Length",str(len(html))); self.end_headers(); self.wfile.write(html)
        def log_message(self,*_): pass
    fixture=ThreadingHTTPServer(("127.0.0.1",48446),FixturePage)
    fixture_thread=threading.Thread(target=fixture.serve_forever,daemon=True); fixture_thread.start()
    backend=web_backend.FluxioWebBackend(root,root/"static")
    parent=web_backend.make_handler(backend)
    metadata={}
    class Handler(parent):
        def do_POST(self):
            if self.path=="/__owned_resource_redirect":
                assert backend.is_authenticated(self)
                page=backend.neyvia_mcp.ui_tools.attached_page
                refused=page.evaluate("fetch('/control/redirect-route').then(() => false).catch(() => true)")
                web_backend._json_response(self,200,{"refused":refused,"forbiddenRequests":len(fetched_untrusted)}); return
            if self.path=="/__owned_inspect":
                assert backend.is_authenticated(self)
                page=backend.neyvia_mcp.ui_tools.attached_page
                shot=SCRATCH/"authority.png"; page.screenshot(path=str(shot))
                metadata.update(screenshotSha256=hashlib.sha256(shot.read_bytes()).hexdigest(),
                    filledSha256=hashlib.sha256(page.get_by_role("textbox",name="Email",exact=True).input_value().encode()).hexdigest(),
                    saved=page.locator("#result").inner_text()=="Saved")
                web_backend._json_response(self,200,metadata); return
            if self.path=="/__owned_close":
                assert backend.is_authenticated(self)
                backend.neyvia_mcp.ui_tools.close()
                web_backend._json_response(self,200,{"ok":True}); return
            if self.path=="/__owned_close_page":
                assert backend.is_authenticated(self)
                backend.neyvia_mcp.ui_tools.attached_page.close()
                web_backend._json_response(self,200,{"ok":True}); return
            super().do_POST()
    # The serial fixture server keeps the Playwright resident page on one owner
    # thread; the separate fixture origin serves navigation concurrently.
    server=HTTPServer(("127.0.0.1",48445),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path,payload):
        req=urllib.request.Request("http://127.0.0.1:48445"+path,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","Connection":"close"})
        try: response=opener.open(req,timeout=45)
        except urllib.error.HTTPError as exc: response=exc
        with response:return response.status,json.load(response)
    checks=[]
    run_id="owned-browser-"+uuid.uuid4().hex
    def check(name,value):
        assert value,name; checks.append({"name":name,"passed":True})
    def mcp(args):
        status,value=request("/mcp",{"jsonrpc":"2.0","id":len(checks)+1,"method":"tools/call","params":{"name":"neyvia.workspace.browser","arguments":args}})
        assert status==200; return value
    def native(args):
        status,value=request("/mcp",{"jsonrpc":"2.0","id":len(checks)+1,"method":"tools/call","params":{"name":"neyvia.browser.tab","arguments":args}})
        assert status==200; return value
    try:
        check("HTTP session required",request("/mcp",{"jsonrpc":"2.0","id":1,"method":"tools/list"})[0]==401)
        check("owned local login admitted",request("/api/auth/local-session",{})[0]==200)
        url="http://127.0.0.1:48446/control/proof"
        value=mcp({"operation":"inspect","url":url})
        check("real Chrome approved-origin observation through MCP HTTP","error" not in value and value["result"]["isError"] is False)
        for denied in ["http://example.invalid/control","http://127.0.0.1:48447/control","data:text/html,untrusted","http://fixture:fixture@127.0.0.1:48446/control","http://127.0.0.1:48446/control-evil","http://127.0.0.1:48446/control/%2e%2e/forbidden"]:
            check("untrusted navigation denied before browser call: "+denied,mcp({"operation":"inspect","url":denied}).get("error") is not None)
        value=mcp({"operation":"fill","url":url,"missionId":run_id,"actionId":"fill-once","arguments":{"query":'textbox[name="Email"]',"value":"fixture@example.invalid"}})
        check("real resident Chrome fill through revision-aware action",value.get("result",{}).get("isError") is False)
        check("contradictory attached-page target denied",mcp({"operation":"click","url":url+"-other","missionId":run_id,"actionId":"wrong-target","arguments":{"query":'button[name="Save"]'}}).get("error") is not None)
        value=mcp({"operation":"click","url":url,"missionId":run_id,"actionId":"save-once","arguments":{"query":'button[name="Save"]'}})
        check("real resident Chrome click through durable gateway",value.get("result",{}).get("isError") is False)
        status,value=request("/__owned_inspect",{})
        check("actual DOM reflects fill and click",status==200 and value["saved"] and value["filledSha256"]==hashlib.sha256(b"fixture@example.invalid").hexdigest())
        status,value=request("/__owned_resource_redirect",{})
        check("redirected resource refused before target fetch",status==200 and value["refused"] and value["forbiddenRequests"]==0)
        capture={"operation":"screenshot","url":url,"arguments":{"waitFor":"body","delayMs":0}}
        value=mcp(capture)
        check("scoped native screenshot uses guarded temporary page",value.get("result",{}).get("isError") is False and value["result"]["structuredContent"]["ok"] is True)
        capture["url"]="http://127.0.0.1:48446/control/redirect-route"
        value=mcp(capture)
        check("screenshot redirect fails before target fetch without unguarded fallback",not fetched_untrusted and (value.get("error") is not None or value.get("result",{}).get("structuredContent",{}).get("ok") is False))
        check("contradictory screenshot target refused",mcp({"operation":"screenshot","url":url,"arguments":{"url":url+"-other"}}).get("error") is not None)
        value=mcp({"operation":"inspect","url":"http://127.0.0.1:48446/control/redirect-route"})
        check("MCP redirected untrusted route refused before fetch",value.get("error") is not None and not fetched_untrusted)
        value=mcp({"operation":"inspect","url":url})
        check("resident browser recovers through approved inspect after redirect refusal",value.get("result",{}).get("isError") is False)
        check("owned resident page closed",request("/__owned_close_page",{})[0]==200)
        value=mcp({"operation":"inspect","url":url})
        check("closed resident page recreated with navigation guard",value.get("result",{}).get("isError") is False)
        # The integrated native controller's owner grant is separate from this
        # real Chrome journey. Exercise admission only; no runtime effect fiction.
        status,value=request("/api/ui/browser",{"op":"tab.open","args":{"url":url}}); tab=value["tab"]["id"]
        value=native({"tabId":tab,"op":"navigate","url":url})
        check("agent cannot take over owner-ungranted tab","must grant" in json.dumps(value) and (value.get("error") is not None or value.get("result",{}).get("isError") is True))
        status,value=request("/api/ui/browser",{"op":"tab.grant","args":{"tabId":tab,"enabled":True}})
        check("owner grant accepted",status==200 and value["tab"]["agentGranted"])
        value=native({"tabId":tab,"op":"navigate","url":url})
        check("granted navigation admits queued operation without claiming native effect",value.get("result",{}).get("structuredContent",{}).get("status")=="queued")
        status,value=request("/api/ui/browser",{"op":"tab.grant","args":{"tabId":tab,"enabled":False}})
        value=native({"tabId":tab,"op":"navigate","url":url})
        check("owner revocation restores takeover refusal","must grant" in json.dumps(value) and (value.get("error") is not None or value.get("result",{}).get("isError") is True))
        from grant_agent.crashproof import CrashProofStore
        from grant_agent.neyvia_extension_worker import run_extension_task
        store=CrashProofStore(root)
        for name,target in [("untrusted-start","http://127.0.0.1:48447/control"),("blocked-redirect","http://127.0.0.1:48446/control/redirect"),("live-untrusted-redirect","http://127.0.0.1:48446/control/redirect-route")]:
            task=store.submit_task(mission_id=run_id,kind="extension.browser",idempotency_key=name+run_id,payload={"startUrl":target})
            try:run_extension_task(root,task["taskId"])
            except Exception: pass
            else:raise AssertionError("Untrusted worker navigation completed")
            check("extension "+name+" rejected and failure persisted",store.get_task(task["taskId"])["status"]=="failed")
        check("live forbidden redirect endpoint never fetched by MCP or extension worker",not fetched_untrusted)
        check("unconfigured workspace cannot inherit another workspace's proof origin",_denied(lambda:approved_browser_url(SCRATCH/"no-grant",url,legacy_ports={4173,47908})))
        from grant_agent.local_browser_authority import guard_browser_page
        check("unguardable browser transport refused",_denied(lambda:guard_browser_page(root,object(),url,legacy_ports={4173,47908})))
        invalid=SCRATCH/"invalid-grant"/"config"; invalid.mkdir(parents=True,exist_ok=True)
        for ports in [[47881],[48440],[48450],[True],["48446"]]:
            (invalid/"neyvia_browser_authority.json").write_text(json.dumps({"schema":"neyvia.browser-authority.v1","proofPorts":ports}))
            check("invalid proof grant refused without any network call: "+str(ports),_denied(lambda:approved_browser_url(invalid.parent,url,legacy_ports={4173,47908})))
        return {"passed":True,"checks":checks,"ports":{"http":48445,"fixture":48446,"asyncioWake":48448},"screenshot":str(SCRATCH/"authority.png"),"metadata":metadata,
                "nativeControllerBoundary":"Admission and queued/refused operations only; no WebView2 runtime connected or native effect claimed.",
                "redirectBoundary":"Automatic navigation redirects are refused before follow-up fetch. Inspect an explicitly approved target URL instead.","forbiddenRedirectTargetRequests":len(fetched_untrusted)}
    finally:
        try:request("/__owned_close",{})
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)
            fixture.shutdown();fixture.server_close();fixture_thread.join(timeout=3)
            assert not thread.is_alive() and not fixture_thread.is_alive()

def _denied(call):
    try:call()
    except ValueError:return True
    return False

def main():
    isolate(); assert CHROME.is_file(),"Installed Chrome is unavailable; no download permitted"
    evidence={"schema":"neyvia.FOLLOW.browser-authority.v1","replay":preservation_and_replay(),"http":http_proof(),
              "ownedServersClosed":True,"browser":"Installed Chrome, headless pipe, unique disposable profiles under task temporary directory; no personal profile","testRunner":"none"}
    OUTPUT.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
    print("Browser authority real Chrome/HTTP proof complete",flush=True)

if __name__=="__main__":main()
