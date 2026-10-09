"""Real hidden Claude stdio admission, queued output and deadline observations."""
from __future__ import annotations
import argparse
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
PEER = r'''
import json,os,sys,time
mode=os.environ['C7D_IDLE_MODE'];sid='owned-'+str(os.getpid())
def emit(value):print(json.dumps(value),flush=True)
for line in sys.stdin:
 value=json.loads(line)
 if value.get('type')=='user':break
emit({'type':'system','subtype':'init','session_id':sid,'model':'owned-protocol'})
if mode=='pending':
 emit({'type':'control_request','request_id':'owned-approval','request':{'subtype':'can_use_tool','tool_name':'Bash','input':{'command':'owned'},'tool_use_id':'owned-tool'}})
elif mode=='complete':
 emit({'type':'assistant','session_id':sid,'message':{'id':'owned-assistant','model':'owned-protocol','content':[{'type':'text','text':'雪 exact completion'}]}})
 emit({'type':'result','subtype':'success','is_error':False,'session_id':sid,'result':'雪 exact completion','usage':{'input_tokens':1,'output_tokens':1}})
else:time.sleep(60)
for line in sys.stdin:
 value=json.loads(line)
 if value.get('type')=='control_request' and value.get('request',{}).get('subtype')=='interrupt':break
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--phase',choices=('before','startup','after'),required=True)
    args=parser.parse_args()
    if args.port!=48743:parser.error('Explicit owned port 48743 required')
    output=args.output.resolve();output.relative_to(REPO/'scripts/evidence')
    root=REPO/'.agent_control/proofs'/('c7d-claude-idle-'+uuid.uuid4().hex);root.mkdir()
    for key in ('HOME','USERPROFILE','APPDATA','LOCALAPPDATA','CODEX_HOME','HERMES_HOME','OPENCLAW_STATE_DIR','TEMP','TMP'):
        folder=root/'home'/key.lower();folder.mkdir(parents=True);os.environ[key]=str(folder)
    for key in ('NEYVIA_UI_STATE_ROOT','NEYVIA_UI_BACKEND_URL','FLUXIO_WORKSPACE_ROOT','FLUXIO_NAS_ROOT'):os.environ.pop(key,None)
    os.environ.update(NEYVIA_NAS_ROOT=str(root),NEYVIA_C7_PORT=str(args.port),NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{args.port}',NEYVIA_TOOL_AUTO_UPDATE='0',FLUXIO_WATCHDOG_AUTOSTART='0',NEYVIA_COORDINATOR_AUTOSTART='0',PYTHONPATH=str(REPO/'src'),PYTHONIOENCODING='utf-8')
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent import local_network_policy as policy
    from grant_agent.connected_sessions.claude_stream import ClaudeRun
    from grant_agent.connected_sessions.model import TurnOptions
    from grant_agent.proof_contracts import source_digest
    sources=['scripts/prove_C7d_claude_idle.py','src/grant_agent/connected_sessions/claude_stream.py','src/grant_agent/connected_sessions/claude.py','src/grant_agent/edge_fixture_c7d_control.py','src/grant_agent/local_network_policy.py']
    bindings={name:source_digest(REPO/name) for name in sources}
    policy.install(root)
    peer=root/'owned-peer.py';peer.write_text(PEER,encoding='utf-8')
    rows=[]
    def observe(name,mode='complete',startup=False,callback=False,idle=8,pending=8):
        area=root/name;area.mkdir();events=[];times={};ready=threading.Event();blocker=None;queued_types=[]
        if startup:
            def hold():
                with policy._lock:
                    ready.set();time.sleep(9)
            blocker=threading.Thread(target=hold);blocker.start();ready.wait(2)
        database=area/'callback.sqlite'
        if callback:
            connection=sqlite3.connect(database);connection.execute('create table observed(value text)');connection.commit();connection.close()
        def on_session(sid,started):
            if not started or not callback:return
            ready.clear()
            def writer():
                connection=sqlite3.connect(database);connection.execute('BEGIN EXCLUSIVE');ready.set();time.sleep(9);connection.rollback();connection.close()
            worker=threading.Thread(target=writer);worker.start();ready.wait(2)
            times['callbackStarted']=time.monotonic()
            connection=sqlite3.connect(database,timeout=12)
            try:connection.execute('select * from observed').fetchall()
            finally:connection.close();worker.join(2)
            times['callbackFinished']=time.monotonic()
            with run._inbox.mutex:
                queued_types.extend(entry[1].get('type') for entry in run._inbox.queue if entry[0]=='msg')
        def emit(event):
            events.append(event)
            if event.get('type')=='run.state':times.setdefault(event['state'],time.monotonic())
        class ObservedRun(ClaudeRun):
            def interrupt(self,reason=None):
                times.setdefault('interruptRequested',time.monotonic())
                return super().interrupt(reason)
        run=ObservedRun(cli=[sys.executable,str(peer)],run_id=name,session_id=None,message='owned request',options=TurnOptions(),cwd=str(area),emit=emit,extra_env={'C7D_IDLE_MODE':mode},idle_timeout=idle,pending_timeout=pending,interrupt_grace=.1,shutdown_grace=.5,context_probe=False,on_session=on_session,state_root=root)
        start=time.monotonic();stacks=area/'threads.txt'
        error=None
        with stacks.open('w',encoding='utf-8') as stream:
            faulthandler.dump_traceback_later(1,repeat=True,file=stream)
            try:session=run.run()
            except Exception as exc:error={'type':type(exc).__name__,'error':str(exc)};session=run.session_id
            finally:faulthandler.cancel_dump_traceback_later()
        if blocker:blocker.join(2)
        finals=[event for event in events if event.get('type')=='run.state' and event.get('state') in ('completed','failed','interrupted')]
        typed=[event for event in events if event.get('type') in ('item.added','item.updated')]
        identity=all(event['runId']==name and event['sessionId']==session and event['item']['id'] and isinstance(event['item']['seq'],int) for event in typed)
        row={'name':name,'idleSeconds':idle,'pendingSeconds':pending,'states':[{'state':e['state'],'error':e.get('error')} for e in events if e.get('type')=='run.state'],'oneTerminal':len(finals)==1,'terminal':finals[0]['state'] if len(finals)==1 else None,'typedEvents':len(typed),'typedIdentity':identity,'sessionId':session,'pid':run.pid,'childExit':run.process.poll() if run.process else None,'durationMs':round((time.monotonic()-start)*1000),'timingsMs':{k:round((v-start)*1000) for k,v in times.items()},'queuedProtocolAfterCallback':queued_types,'error':error,'stacks':{'path':str(stacks),'sha256':hashlib.sha256(stacks.read_bytes()).hexdigest()}}
        rows.append(row);print(json.dumps(row),flush=True)
        if run.process is None or run.process.poll() is None or not row['oneTerminal'] or not identity:raise AssertionError('Owned child/terminal/identity was not closed exactly')
        return row
    admission=observe('startup-policy-lock',startup=True)
    queued=observe('queued-output-callback',callback=True)
    expected=('interrupted','interrupted') if args.phase=='before' else ('completed','interrupted') if args.phase=='startup' else ('completed','completed')
    if (admission['terminal'],queued['terminal'])!=expected:raise AssertionError('Actual admission/queued-output reproduction changed: '+repr(rows))
    if args.phase=='after':
        if queued['queuedProtocolAfterCallback']!=['assistant','result']:raise AssertionError('Delayed callback had no actual queued completion protocol')
        silent=observe('silent-child',mode='silent',idle=1.2,pending=2.5)
        pending=observe('pending-person-answer',mode='pending',idle=.3,pending=1.2)
        if silent['terminal']!='interrupted' or pending['terminal']!='interrupted':raise AssertionError('Silent or unanswered child escaped configured deadline')
        for row,origin,limit in ((silent,'running',1.2),(pending,'waiting_approval',1.2)):
            elapsed=(row['timingsMs']['interruptRequested']-row['timingsMs'][origin])/1000
            if not limit<=elapsed<limit+.75:raise AssertionError('Configured deadline was extended or fired early')
        from grant_agent.edge_fixture_c7d_control import _provider_turn
        from grant_agent.edge_contracts import CATEGORIES
        for identity in ('providers.claude.events','providers.claude.lifecycle','providers.claude.reply'):
            for category in CATEGORIES:
                area=root/(identity+'-'+category);area.mkdir()
                blocker=None
                if category=='concurrency' and not identity.endswith('reply'):
                    ready=threading.Event()
                    def hold_launches():
                        with policy._lock:ready.set();time.sleep(9)
                    blocker=threading.Thread(target=hold_launches);blocker.start();ready.wait(2)
                try:detail=_provider_turn(area,category,identity)
                finally:
                    if blocker:blocker.join(2)
                if blocker:detail['actualPolicyLaunchWaitSeconds']=9
                rows.append({'name':identity+'.'+category,'status':'passed','detail':detail})
                print(json.dumps({'name':rows[-1]['name'],'status':'passed'}),flush=True)
    stable=bindings=={name:source_digest(REPO/name) for name in sources}
    prior=REPO/'scripts/evidence/C7d-claude-idle-before.json'
    diagnostic=REPO/'.agent_control/proofs/c7/c7b4c6e22ef4475b8a62538bd08241e2/semantic-fixtures/c7d-control/case-progress.jsonl'
    diagnostics=[json.loads(line) for line in diagnostic.read_text(encoding='utf-8').splitlines()]
    failed=[row for row in diagnostics if row.get('case',{}).get('status')=='failed']
    report={'schema':'neyvia.c7d-claude-idle.v1','ok':args.phase=='after' and stable,'sourceStable':stable,'sourceBindings':bindings,'phase':args.phase,'explicitPort':args.port,'root':str(root),'rows':rows,'campaignBefore':{'path':str(diagnostic),'sha256':hashlib.sha256(diagnostic.read_bytes()).hexdigest(),'failedCases':failed,'completionReceipt':False},'boundary':'Production Claude adapter with real hidden finite local stdio children, actual held policy lock and SQLite writer. No actual Claude provider, account, credentials, rendered or public authority. Original campaign attribution is an inference; fresh full campaign remains required.'}
    if args.phase=='after':report['before']={'path':str(prior),'sha256':hashlib.sha256(prior.read_bytes()).hexdigest()}
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'phase':args.phase,'ok':report['ok'],'sourceStable':stable,'rows':len(rows)}))
    return int(not stable)

if __name__=='__main__':raise SystemExit(main())
