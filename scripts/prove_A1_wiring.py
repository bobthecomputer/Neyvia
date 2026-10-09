import json, threading, uuid, time
from pathlib import Path
import os, sys
REPO = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(REPO / 'src'))
os.chdir(REPO)
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import Request,urlopen
from grant_agent.web_backend import FluxioWebBackend
from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent.neyvia_mobile_studio import serve_preview
from grant_agent.desktop_bridge import dispatch_desktop_command, ALLOWED_DESKTOP_COMMANDS
from grant_agent.neyvia_app_sdk import COMMANDS
from grant_agent.neyvia_awareness import board_list
from grant_agent.neyvia_autopilot import verify_app_goal
root=Path('.agent_control/a1-sdk-wiring/runtime-'+uuid.uuid4().hex[:8]).resolve(); root.mkdir(parents=True)
backend=FluxioWebBackend.__new__(FluxioWebBackend);backend.root=root
created=backend.dispatch('app_sdk_new_command',{'path':'counter','kind':'web','name':'Wiring Counter'})
project=created['project']; service=workspace_for(root,backend)
build=backend.dispatch('app_sdk_build_command',{'project':project,'platform':'web'})
preview=backend.dispatch('app_sdk_preview_command',{'project':project,'port':48549,'device':'pixel-9'})
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):serve_preview(root,self,urlparse(self.path),'GET')
    def do_POST(self):serve_preview(root,self,urlparse(self.path),'POST')
    def do_OPTIONS(self):serve_preview(root,self,urlparse(self.path),'OPTIONS')
server=ThreadingHTTPServer(('127.0.0.1',48549),Handler); threading.Thread(target=server.serve_forever,daemon=True).start()
result={'commands':sorted(COMMANDS),'desktopAllowed':COMMANDS.issubset(ALLOWED_DESKTOP_COMMANDS),'created':created,'build':build,'preview':preview}
try:
    url=preview['url']; api=url+'__neyvia/state'
    with urlopen(api,timeout=5) as r:result['initialMobileState']=json.load(r)
    req=Request(url+'__neyvia/commit',data=json.dumps({'state':{'count':4},'expectedRevision':0,'actionId':'proof-api','fingerprint':'wire'}).encode(),headers={'Content-Type':'application/json','X-Neyvia-App':'1'})
    with urlopen(req,timeout=5) as r:result['mobileCommit']=json.load(r)
    result['botStateAfterMobileCommit']=backend.dispatch('app_sdk_state_command',{'project':project})
    result['desktopStateAfterMobileCommit']=dispatch_desktop_command(root,'app_sdk_state_command',{'project':project})
    req=Request(url+'__neyvia/commit',method='OPTIONS',headers={'Origin':'null','Access-Control-Request-Headers':'content-type,x-neyvia-app','Access-Control-Request-Method':'POST'})
    with urlopen(req,timeout=5) as r:result['sandboxCors']={'status':r.status,'origin':r.headers['Access-Control-Allow-Origin'],'headers':r.headers['Access-Control-Allow-Headers']}
    result['agentAction']=backend.dispatch('app_sdk_action_command',{'project':project,'url':url,'name':'increment'})
    result['botStateAfterAction']=backend.dispatch('app_sdk_state_command',{'project':project})
    goal={'project':project,'url':url,'clSource':r'C:\Users\user\Projects\nx-integrate-cl'}
    result['mobileRealGoal']=backend.dispatch('app_sdk_verify_command',goal)
    run={'appGoal':goal,'scopeTools':['neyvia.app_sdk.verify']}
    verify_app_goal(service,run,lambda tool,args,action_id='':service.call(tool.removeprefix('neyvia.'),args))
    result['autopilotFreshGate']=run['appGoalVerification']
    # Seed a typed preselected plan, then execute the actual durable Autopilot
    # executor/gateway/manual runner without a provider call or mock dispatcher.
    from grant_agent.neyvia_autopilot import save, execute, load, completed_response
    from grant_agent.neyvia_agent import NeyviaToolGateway
    gateway=NeyviaToolGateway(root,allow_mutations=True,permission_mode='workspace',allowed_mutation_tools={'neyvia.app_sdk.verify'})
    identity=uuid.uuid4().hex
    scope=['neyvia.app_sdk.describe','neyvia.app_sdk.state','neyvia.app_sdk.verify']
    selected={'id':'app-sdk','chapter':'overview','procedure':'inspect','inputs':{'project':project},'verify':{'tool':'neyvia.app_sdk.state','args':{'project':project},'expect':{'path':'state.count','op':'exists'}}}
    plan={'schema':'neyvia.autopilot.v1','runId':identity,'requestId':'sdk-wiring-'+identity,'fingerprint':'fixture-explicit-selection','text':'Inspect and prove this running SDK app','scopeTools':scope,'appGoal':goal,'sessionId':'','efficiency':False,'status':'running','startedAt':time.time(),'maxSeconds':240,'maxModelCalls':1,'models':[],'tokens':{},'cascade':[],'needsPaul':[],'items':[{'ask':'Inspect and prove this app','doneWhen':'Configured runtime app goals pass','selection':selected,'status':'pending','modelReasons':[],'route':'manual'}]}
    save(service,plan)
    result['autopilotExecution']=execute(service,identity,gateway.native,gateway.call_native)
    assert result['autopilotExecution']['run']['status']=='completed',result['autopilotExecution']
    model=Path(project)/'www/model.js';source=model.read_text();broken=source.replace('state.count+1','state.count+0');assert broken!=source
    model.write_text(broken)
    try:
        result['autopilotBrokenExecution']=completed_response(service,load(service,identity),gateway.call_native)
        assert result['autopilotBrokenExecution']['run']['status']=='blocked',result['autopilotBrokenExecution']
        assert result['autopilotBrokenExecution']['run']['appGoalVerification']['ok'] is False
    finally:model.write_text(source)
    result['repairedAppGoal']=backend.dispatch('app_sdk_verify_command',goal)
    assert result['repairedAppGoal']['ok']
    result['mobileNativeAdmission']={platform:backend.dispatch('app_sdk_build_command',{'project':project,'platform':platform}) for platform in ['ios','android']}
    result['activeClaims']=board_list(root,{})
    assert result['desktopAllowed'] and build['ok'] and preview['ok'] and result['mobileRealGoal']['ok']
    assert result['botStateAfterMobileCommit']['state']['count']==4 and result['desktopStateAfterMobileCommit']['state']['count']==4
    assert result['agentAction']['state']['count']==5 and result['botStateAfterAction']['state']['count']==5
    assert result['sandboxCors']['status']==204 and 'x-neyvia-app' in result['sandboxCors']['headers']
    result['ok']=True
finally:
    server.shutdown();server.server_close();service.close()
    Path('scripts/evidence/A1-wiring.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'ok':result.get('ok'), 'project':project,'receipt':'.agent_control/a1-sdk-wiring/proof.json','goal':result.get('mobileRealGoal',{}).get('completion')}))
