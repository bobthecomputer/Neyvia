"""Finite child-process transport for confined owner proof adapters."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import uuid


class LocalTransport:
    def __init__(self,root,app='codex'):
        self.root,self.app=Path(root),app
        self.sessions={};self.calls=[];self.interrupts=[]

    def available(self): return True,None
    def options(self,*args): return {}
    def live_status(self): return {}
    def interrupt(self,run_id): self.interrupts.append(run_id)
    def answer(self,*args): return None

    def list_sessions(self,**kwargs): return list(self.sessions.values())

    def read(self,identity,**kwargs):
        from .connected_sessions.model import ItemsPage,ContextUsage
        return ItemsPage(self.sessions[identity],[],ContextUsage())

    def start_turn(self,session_id,message,options,*,cwd,run_id,emit):
        from .connected_sessions.model import SessionSummary,Capabilities
        from .connected_sessions.registry import make_session_id
        from .external_chat_inventory import _host
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        identity=session_id or make_session_id(self.app,_host()['deviceId'],uuid.uuid4().hex)
        self.calls.append((identity,message,run_id))
        self.sessions[identity]=SessionSummary(id=identity,app=self.app,title='Local transport fixture',cwd=cwd,
                                                capabilities=Capabilities(continue_session=True,stop=True))
        # This stdlib-only fixture executes no repository code. Parent broker
        # calls remain traced; do not make this print helper lease a trace slot.
        process=subprocess.run([sys.executable,'-I','-c',"print('Local receipt accepted')"],cwd=cwd,
                               capture_output=True,text=True,check=True,**hidden_windows_subprocess_kwargs())
        emit({'type':'item.added','sessionId':identity,'item':{'id':'user','seq':1,'kind':'user','data':{'text':message}}})
        emit({'type':'item.added','sessionId':identity,'item':{'id':'assistant','seq':2,'kind':'assistant','data':{'text':process.stdout.strip()}}})
        return identity


def service_for(root):
    from .connected_sessions.broker import ConnectedBroker
    from .neyvia_workspace_tools import WorkspaceTools
    transport=LocalTransport(root)
    broker=ConnectedBroker(root,adapters={'codex':transport},load_defaults=False,autostart=False)
    service=WorkspaceTools(root)
    service.broker=lambda:broker
    return service,broker,transport
