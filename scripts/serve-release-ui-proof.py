"""Disposable authenticated release backend. Arguments: candidate directory, new proof workspace.
Uses the production HTTP server so connection limits and timeouts match deployment.
No model calls or background workers; stops after 15 minutes."""
import json,sys,threading,ssl
from pathlib import Path
candidate=Path(sys.argv[1]);root=Path(sys.argv[2])
if root.exists() and any(root.iterdir()):
 raise SystemExit('Use a new disposable proof workspace; existing task data is preserved.')
root.mkdir(parents=True,exist_ok=True)
sys.dont_write_bytecode=True;sys.path.insert(0,str(candidate/'src'))
from grant_agent.web_backend import FluxioWebBackend,make_handler,_HandshakeSafeThreadingHTTPServer
from grant_agent.workspace_intelligence import WorkspaceIntelligence
backend=FluxioWebBackend(root,candidate/'web/dist')
identity='release-system-improvement'
store=backend.neyvia_mcp.conversations
try:store.get_conversation(identity)
except KeyError:
 store.create_conversation(conversation_id=identity,title='Release verification: task continuation',metadata={'releaseVerification':True,'modelCall':False})
 store.append_turn(identity,role='user',content='Release verification fixture: preserve the selected direction and draft between browsers.',source='release-verification',metadata={'runtime':'neyvia-agent','model':'gpt-5.6-luna','provider':'openai-codex','effort':'medium','modelCall':False})
 w=WorkspaceIntelligence(root,identity)
 w.propose_brief('A verification fixture for choosing and continuing an implementation direction.',directions=[{'id':'compact','title':'Compact workspace','approach':'Keep relevant decisions next to the conversation.','tradeoff':'Details open on demand.'},{'id':'expanded','title':'Expanded workspace','approach':'Keep evidence and decisions visible.','tradeoff':'Less room for the conversation.'}])
tls=None
if len(sys.argv)>3:
 if len(sys.argv)!=5:raise SystemExit('Supply both certificate and key paths after the workspace.')
 tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(sys.argv[3],sys.argv[4])
server=_HandshakeSafeThreadingHTTPServer(('127.0.0.1',0),make_handler(backend),ssl_context=tls)
ready={'scheme':'https' if tls else 'http','serverClass':type(server).__name__,'port':server.server_address[1],'conversationId':identity,'candidate':str(candidate),'source':json.loads((candidate/'NEYVIA_SOURCE_REVISION.json').read_text())}
(root/'ready.json').write_text(json.dumps(ready),encoding='utf8');print(json.dumps(ready),flush=True)
timer=threading.Timer(900,server.shutdown);timer.daemon=True;timer.start()
try:server.serve_forever()
finally:timer.cancel();server.server_close()
