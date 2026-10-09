import os, sys, secrets, json, threading, uuid, http.cookiejar, urllib.request, urllib.error
from pathlib import Path
REPO=Path.cwd();sys.path.insert(0,str(REPO/'src'));sys.path.insert(0,str(REPO/'scripts'))
import fix2_scope
fix2_scope.install()
ROOT=REPO/'.agent_control/proofs/FIX2-http'/uuid.uuid4().hex
ROOT.mkdir(parents=True)
from grant_agent.proof_credential_guard import install,prepare_broker_fixture
install(ROOT);prepare_broker_fixture(ROOT)
base='http://127.0.0.1:48689'
os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0',NEYVIA_COORDINATOR_AUTOSTART='0',FLUXIO_WATCHDOG_AUTOSTART='0',FLUXIO_RUNTIME_AUTO_UPDATE='0',NEYVIA_UI_STATE_ROOT=str(ROOT),FLUXIO_WORKSPACE_ROOT=str(ROOT),NEYVIA_UI_BACKEND_URL=base,FLUXIO_WEB_BACKEND_URL=base,SYNTELOS_ACCOUNT_USER='fix2-owner',SYNTELOS_ACCOUNT_PASSWORD=secrets.token_urlsafe(40),NEYVIA_PROOF_CREDENTIAL_GUARD='1')
from grant_agent.web_backend import FluxioWebBackend,_HandshakeSafeThreadingHTTPServer,make_handler
backend=FluxioWebBackend(ROOT,REPO/'.agent_control/FIX2/build')
server=_HandshakeSafeThreadingHTTPServer(('127.0.0.1',48689),make_handler(backend))
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
http=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
rows=[]
def request(route,body=None,keep=True):
 req=urllib.request.Request(base+route,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
 try:
  with http.open(req,timeout=60) as response:status=response.status;value=json.load(response)
 except urllib.error.HTTPError as error:status=error.code;value=json.load(error)
 rows.append({'route':route,'status':status,**({'response':value} if keep else {})})
 assert status==200,(status,value)
 return value

def tool(name,args={}):
 value=request('/api/ui/tools/call',{'tool':name,'arguments':args,'_expectedStateRoot':str(ROOT)})
 receipt=value.get('data',value)
 assert receipt['ok'],receipt.get('error')
 return receipt['result']
try:
 request('/api/auth/local-session',{},False)
 state=tool('neyvia.browser.state')
 assert type(state['revision']) is int
 # Owner settings command uses the exact production state, not a tool proposal.
 value=request('/api/backend',{'command':'settings_get_command','payload':{'_expectedStateRoot':str(ROOT)}})
 settings=value.get('data',value)
 (ROOT/'http-search.txt').write_text('FIX2 offline needle\n',encoding='utf-8')
 value=request('/api/backend',{'command':'settings_update_command','payload':{'_expectedStateRoot':str(ROOT),'patch':{'localOnly':True},'expectedRevision':settings['revision']}})
 search=request('/api/backend',{'command':'call_native_tool_command','payload':{'_expectedStateRoot':str(ROOT),'tool':'workspace.search','arguments':{'query':'offline needle','includeGlob':'http-search.txt'}}})
 receipt=search.get('data',search);assert receipt['ok'],receipt.get('error');result=receipt['result']
 assert result['engine']=='python-inprocess' and result['count']==1
 request('/api/health')
 report={'schema':'neyvia.FIX2.http.v1','ok':True,'port':48689,'root':str(ROOT),'calls':rows,'localSearch':result,'boundary':'Authenticated production make_handler; ephemeral in-memory owner; saved credentials refused; startup full self-check separate'}
 (REPO/'scripts/evidence/fix2-http.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'ok':True,'httpCalls':len(rows),'revision':state['revision'],'searchEngine':result['engine']}))
finally:
 server.shutdown();server.server_close();thread.join(timeout=3)
 for name in ('_cua_service','_neyvia_cua_service'):
  service=getattr(backend,name,None)
  if service:service.shutdown()
