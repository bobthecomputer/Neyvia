"""Local MCP bootstrap when Neyvia is absent from the caller's tool inventory.

Uses the production MCP/gateway and GameDev queue; the tiny HTTP listener is only
the bridge transport. Native editors remain private child processes.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import faulthandler
import uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0',FLUXIO_WATCHDOG_AUTOSTART='0',NEYVIA_COORDINATOR_AUTOSTART='0',
                  NEYVIA_WEB_PORT='49101',NEYVIA_GAMEDEV_WS_PORT='49102')


OWNED_PAIRS=(49101,49105,49107,49111,49113,49115,49117)


def owned_pair(port=None):
    """Historical owned pairs unless a block is assigned explicitly (grant_agent.assigned_ports)."""
    from grant_agent.assigned_ports import check_ports,choose_port
    port=choose_port(port,49101)
    check_ports((port,port+1),lambda p:p[0] in OWNED_PAIRS,'Use an owned task port pair')
    return port


class Harness:
    def __init__(self,root,port=None):
        from grant_agent.assigned_ports import state
        port=owned_pair(port)
        os.environ.update(NEYVIA_WEB_PORT=str(port),NEYVIA_GAMEDEV_WS_PORT=str(port+1))
        from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
        from grant_agent.neyvia_gamedev import service_for
        self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        self.state=state('laya3d/'+self.root.name)
        self.state.mkdir(parents=True,exist_ok=True)
        os.environ['NEYVIA_GAMEDEV_WORKSPACE']=str(self.root)
        os.environ['NEYVIA_UI_STATE_ROOT']=str(self.state)
        self.mcp=CompactNeyviaMCPServer(self.state,permission_mode='full-access',
            native_mutation_tools=['neyvia.gamedev.setup','neyvia.gamedev.action',
                                  'neyvia.scene.improve','neyvia.scene.episode'])
        # Repeating all-thread traceback dumps can crash CPython (exit 139) under load; opt in only.
        if os.environ.get('LAYA3D_TRACEBACK_WATCHDOG'): faulthandler.dump_traceback_later(90,repeat=True)
        self.service=service_for(self.state); self.children=[]; self.calls=[]; self.run_id=uuid.uuid4().hex
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                try:
                    if not self.path.startswith('/api/gamedev/bridge/'): raise ValueError('Unknown bridge route')
                    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    result=owner.service.bridge(self.path.rsplit('/',1)[-1],body,self.headers.get('Authorization','').removeprefix('Bearer '))
                    data={'ok':True,'data':result}
                except Exception as exc:
                    data={'ok':False,'error':str(exc)}
                    print('Native bridge refused:',str(exc),flush=True)
                payload=json.dumps(data).encode(); self.send_response(200); self.end_headers(); self.wfile.write(payload)
        self.http=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.service.start_websocket()

    def tool(self,name,args):
        if name != 'neyvia.cl':
            # Same native gateway, without constructing the legacy full catalog.
            value=self.mcp._gateway().call_native(name,args,action_id='laya3d-'+self.run_id+'-'+str(len(self.calls)+1))
            self.calls.append({'tool':name,'args':args,'response':value})
            if not value.get('ok',True): raise RuntimeError(str(value)[-1800:])
            from grant_agent.neyvia_manuals import unwrap
            return unwrap(value)
        response=self.mcp.handle({'jsonrpc':'2.0','id':len(self.calls)+1,'method':'tools/call','params':{'name':name,'arguments':args}})
        self.calls.append({'tool':name,'args':args,'response':response})
        if 'error' in response: raise RuntimeError(str(response['error']))
        result=response['result']
        if result.get('isError'): raise RuntimeError(str(result)[-1800:])
        value=result.get('structuredContent')
        if value is None:
            value=json.loads(result['content'][0]['text'])
        from grant_agent.neyvia_manuals import unwrap
        return unwrap(value)

    def native(self,name,args):
        return self.tool('neyvia.gamedev.'+name,args)

    def action(self,session,action,args):
        identity=uuid.uuid4().hex
        self.native('action',{'sessionId':session,'action':action,'args':args,'requestId':identity})
        receipt=self.native('receipt',{'requestId':identity})
        while receipt['status'] in ('queued','running'):
            time.sleep(.1); receipt=self.native('receipt',{'requestId':receipt['requestId']})
        if receipt['status']!='succeeded': raise RuntimeError(str(receipt))
        self.last_receipt=identity
        return receipt['result']

    def launch(self,engine,project,arguments):
        from grant_agent.neyvia_gamedev import installed_editor
        project=Path(project); project.mkdir(parents=True,exist_ok=True)
        project.resolve().relative_to(self.root)
        # Only this disposable harness owns these generated bridge copies.
        # Preserve old versions before setup; production setup stays conservative.
        destination={'blender':project/'.neyvia/blender','godot':project,
                     'unity':project/'Packages/com.neyvia.bridge'}[engine]
        package=REPO/'scripts/gamedev'/engine
        for source in package.rglob('*'):
            if not source.is_file() or source.suffix=='.pyc' or '__pycache__' in source.parts: continue
            relative=source.relative_to(package)
            if engine=='godot' and relative.parts[0]!='addons': continue
            if engine=='unity' and relative.parts[0]=='OptionalTests': continue
            target=destination/relative
            target.resolve().relative_to(project.resolve())
            if target.exists() and target.read_bytes()!=source.read_bytes():
                backup=project/'.neyvia/bridge-history'/self.run_id/relative
                backup.parent.mkdir(parents=True,exist_ok=True)
                target.rename(backup)
        self.native('setup',{'engine':engine,'projectPath':str(project)})
        log=open(project/'native.log','w',encoding='utf-8')
        child=subprocess.Popen([installed_editor(engine),*arguments],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        self.children.append((child,log))
        until=time.time()+(600 if engine=='unity' else 180)
        while time.time()<until:
            if child.poll() is not None: raise RuntimeError('Editor stopped: '+str(project/'native.log'))
            rows=self.native('sessions',{'engine':engine,'projectPath':str(project),'context':'Edit'})['sessions']
            live=[r for r in rows if r['status']=='connected']
            if len(live)==1: return live[0]['sessionId']
            time.sleep(.3)
        raise RuntimeError('Editor registration deadline: '+str(project/'native.log'))

    def prove_repeated_receipt(self):
        """Compile and replay the owning manual only after two checked native receipts."""
        inputs={'requestId':self.last_receipt}
        args={'id':'game-dev','chapter':'bridges','procedure':'review-completed-action','inputs':inputs}
        for _ in range(2): self.tool('neyvia.manual.run',args)
        compiled=self.tool('neyvia.manual.compile',{**args,'minRuns':2})
        return self.tool('neyvia.manual.script.run',{'scriptId':compiled['scriptId'],'inputs':inputs})

    def close(self):
        faulthandler.cancel_dump_traceback_later()
        for child,log in self.children:
            if child.poll() is None: child.terminate(); child.wait(timeout=30)
            log.close()
        self.http.shutdown(); self.http.server_close()
        (self.root/'mcp-receipts.json').write_text(json.dumps(self.calls,indent=2),encoding='utf-8')
