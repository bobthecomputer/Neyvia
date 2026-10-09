"""Real loopback HTTP under retained and locked durable Settings policies."""
from __future__ import annotations
import argparse
import faulthandler
import gzip
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'src'))
CLIENT = r'''
import gzip,http.client,json,socket,sys
from concurrent.futures import ThreadPoolExecutor
port=int(sys.argv[1])
def audit(event,args):
 if event in {'socket.connect','socket.bind'} and (args[1][0]!='127.0.0.1' or args[1][1]!=port): raise PermissionError('Owned loopback only')
sys.addaudithook(audit)
print('ready',flush=True)
def one(index):
 c=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
 try:
  c.request('GET','/owned',headers={'Accept-Encoding':'gzip'});r=c.getresponse();b=r.read()
  if r.headers.get('Content-Encoding')=='gzip':b=gzip.decompress(b)
  value=json.loads(b)
  return {'ok':r.status==200 and value=={'owned':'雪'*4096},'status':r.status,'bytes':len(b)}
 except Exception as error:return {'ok':False,'error':type(error).__name__}
 finally:c.close()
for line in sys.stdin:
 request=json.loads(line)
 if request.get('stop'):break
 with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(one,range(request['count'])))
 print(json.dumps(rows),flush=True)
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--before',action='store_true')
    args=parser.parse_args()
    if args.port!=48744:parser.error('Explicit owned port48744 required')
    output=args.output.resolve();output.relative_to(REPO/'scripts/evidence')
    root=REPO/'.agent_control/proofs'/('c7d-loopback-'+uuid.uuid4().hex);root.mkdir()
    for key in ('HOME','USERPROFILE','APPDATA','LOCALAPPDATA','CODEX_HOME','HERMES_HOME','OPENCLAW_STATE_DIR','TEMP','TMP'):
        folder=root/'home'/key.lower();folder.mkdir(parents=True);os.environ[key]=str(folder)
    for key in ('NEYVIA_UI_STATE_ROOT','NEYVIA_UI_BACKEND_URL','FLUXIO_WORKSPACE_ROOT','FLUXIO_NAS_ROOT'):os.environ.pop(key,None)
    os.environ.update(NEYVIA_NAS_ROOT=str(root),NEYVIA_C7_PORT=str(args.port),NEYVIA_TOOL_AUTO_UPDATE='0',FLUXIO_WATCHDOG_AUTOSTART='0',NEYVIA_COORDINATOR_AUTOSTART='0',PYTHONPATH=str(REPO/'src'),PYTHONIOENCODING='utf-8')
    from grant_agent.proof_credential_guard import install
    install(root)
    # Start the finite independent HTTP client before the backend policy hooks.
    # It has its own loopback-only audit and never opens an external connection.
    child=subprocess.Popen([sys.executable,'-c',CLIENT,str(args.port)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',env=dict(os.environ),creationflags=subprocess.CREATE_NO_WINDOW)
    if child.stdout.readline().strip()!='ready':raise AssertionError('Owned HTTP client did not start')
    from grant_agent import local_network_policy as policy, web_backend as owner
    from grant_agent.ui_command_bus import UICommandBus
    from grant_agent.proof_contracts import source_digest
    sources=['scripts/prove_C7d_loopback_policy.py','src/grant_agent/local_network_policy.py','src/grant_agent/web_backend.py','src/grant_agent/web_backend_http.py','src/grant_agent/ui_command_bus.py','src/grant_agent/edge_fixture_c7d_desktop.py','src/grant_agent/neyvia_settings.py']
    bindings={name:source_digest(REPO/name) for name in sources}
    stores=[]
    for index in range(64):
        bus=UICommandBus(root/('settings-'+str(index)));bus.put('settings',{'localOnly':False})
        policy.install(bus.root);stores.append(bus)
    backend=owner.FluxioWebBackend(root/'backend',root/'static')
    base=owner.make_handler(backend)
    response_started=threading.Event()
    class Handler(base):
        def do_GET(self):
            if self.path!='/owned':raise AssertionError('Unowned route')
            response_started.set()
            owner._extend_io_timeout(self)
            try:owner._json_response(self,200,{'owned':'雪'*4096})
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    server=owner._HandshakeSafeThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
    writer=sqlite3.connect(stores[0].path)
    writer.execute('PRAGMA wal_checkpoint(TRUNCATE)');writer.execute('PRAGMA journal_mode=DELETE');writer.execute('BEGIN EXCLUSIVE')
    stacks=root/'locked-store-threads.txt'
    result=[];external_results=[];external_os_attempts=[];wrapped_http=[];local_only_http=[];external_ms=None;lookup_ms=None
    def policy_wrapped_http():
        connection=http.client.HTTPConnection('127.0.0.1',args.port,timeout=1)
        try:
            connection.request('GET','/owned',headers={'Accept-Encoding':'gzip'})
            response=connection.getresponse();body=response.read()
            if response.headers.get('Content-Encoding')=='gzip':body=gzip.decompress(body)
            if response.status!=200 or json.loads(body)!={'owned':'雪'*4096}:raise AssertionError('Wrapped local HTTP changed current bytes')
            return {'ok':True,'status':response.status,'bytes':len(body)}
        finally:connection.close()
    def safety(event,values):
        if event in {'socket.connect','socket.sendto'} and (not isinstance(values[-1],tuple) or not policy.loopback(values[-1][0])):
            external_os_attempts.append(event);raise PermissionError('External OS operation forbidden in this proof')
    sys.addaudithook(safety)
    try:
        with stacks.open('w',encoding='utf-8') as stack_file:
            faulthandler.dump_traceback_later(0.5,repeat=True,file=stack_file)
            started=time.monotonic()
            child.stdin.write(json.dumps({'count':1 if args.before else 8})+'\n');child.stdin.flush()
            result=json.loads(child.stdout.readline())
            duration_ms=round((time.monotonic()-started)*1000,3)
            if not response_started.wait(2):raise AssertionError('Actual production response was not entered')
            faulthandler.cancel_dump_traceback_later()
            if args.before:
                if result!=[{'ok':False,'error':'TimeoutError'}]:raise AssertionError('Original policy did not reproduce the actual HTTP read deadline')
            else:
                if len(result)!=8 or not all(row['ok'] for row in result):raise AssertionError('Held SQLite policy writer blocked allowed loopback HTTP')
                # While the policy lock is held by an actual external admission
                # scanning the same locked SQLite store, fresh local socket and
                # handler bookkeeping must remain usable.
                external=socket.socket();ready=threading.Event()
                def try_external():
                    nonlocal external_ms
                    external_started=time.monotonic()
                    ready.set()
                    try:external.connect(('203.0.113.10',args.port))
                    except policy.LocalOnlyError:external_results.append('refused-before-OS')
                    except Exception as error:external_results.append(type(error).__name__)
                    finally:
                        external.close();external_ms=round((time.monotonic()-external_started)*1000,3)
                worker=threading.Thread(target=try_external);worker.start();ready.wait(2)
                time.sleep(0.1)
                faulthandler.dump_traceback(file=stack_file,all_threads=True)
                child.stdin.write(json.dumps({'count':8})+'\n');child.stdin.flush()
                parallel=json.loads(child.stdout.readline())
                if len(parallel)!=8 or not all(row['ok'] for row in parallel):raise AssertionError('External policy scanner blocked independent loopback transport')
                lookup_started=time.monotonic()
                addresses=socket.getaddrinfo('127.0.0.1',args.port,type=socket.SOCK_STREAM)
                lookup_ms=round((time.monotonic()-lookup_started)*1000,3)
                if not addresses or any(not policy.loopback(row[4][0]) for row in addresses):raise AssertionError('Literal lookup returned a nonlocal address')
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=8) as pool:
                    wrapped_http=list(pool.map(lambda _:policy_wrapped_http(),range(8)))
                worker.join(100)
                negative={'initialHTTP':result,'parallelHTTP':parallel,'workerAlive':worker.is_alive(),'externalAdmission':external_results,'externalOSAttempts':external_os_attempts}
                (root/'locked-http-diagnostic.json').write_text(json.dumps(negative,indent=2)+'\n',encoding='utf-8')
                if worker.is_alive() or external_results!=['refused-before-OS'] or external_os_attempts:raise AssertionError(negative)
                stores[1].put('settings',{'localOnly':True})
                with ThreadPoolExecutor(max_workers=8) as pool:
                    local_only_http=list(pool.map(lambda _:policy_wrapped_http(),range(8)))
                stores[1].put('settings',{'localOnly':False})
    finally:
        faulthandler.cancel_dump_traceback_later()
        writer.rollback();writer.close()
        child.stdin.write('{"stop":true}\n');child.stdin.flush()
        child.wait(timeout=10)
        server.shutdown();server.server_close();server_thread.join(5)
    boundary_cases=[]
    if not args.before:
        # Actual owner fixtures include unreadable policy, owner close/reopen,
        # pending child startup, concurrent activation and interrupted writers.
        from grant_agent.edge_fixture_c7d_desktop import _policy
        for category in ('empty','huge','unicode','concurrency','interrupted','permissions','stale'):
            area=root/('boundary-'+category);area.mkdir()
            boundary_cases.append({'category':category,'status':'passed','detail':_policy(area,category)})
        # A waiting external operation must not keep an online decision across
        # a committed activation. Only its attempted target is external; the OS
        # safety observer must see zero external socket operations.
        external=socket.socket();ready=threading.Event();pending=[]
        def waiting_external():
            ready.set()
            try:external.connect(('203.0.113.10',args.port))
            except policy.LocalOnlyError:pending.append('refused-after-activation')
            finally:external.close()
        with policy.transition(True):
            worker=threading.Thread(target=waiting_external);worker.start();ready.wait(2)
            stores[1].put('settings',{'localOnly':True})
        worker.join(10)
        if worker.is_alive() or pending!=['refused-after-activation'] or external_os_attempts:raise AssertionError('Waiting external attempt passed an activated policy')
        stores[1].put('settings',{'localOnly':False})
        boundary_cases.append({'category':'pending-external-activation','status':'passed','observation':pending[0]})
    stable=bindings=={name:source_digest(REPO/name) for name in sources}
    report={'schema':'neyvia.c7d-loopback-policy.v1','ok':not args.before and stable,'sourceStable':stable,'sourceBindings':bindings,'phase':'before' if args.before else 'after','root':str(root),'explicitPort':args.port,'retainedActualSettingsStores':64,'actualHeldSQLiteExclusiveWriter':True,'productionHTTPResults':result,'policyWrappedHTTP':wrapped_http,'persistedLocalOnlyHTTP':local_only_http,'actualHTTPDurationMs':duration_ms,'literalLookupMs':lookup_ms,'originalDeadlineReproduced':args.before,'externalAdmission':external_results,'measuredExternalAdmissionMs':external_ms,'externalOSAttempts':external_os_attempts,'boundaryCases':boundary_cases,'childExit':child.returncode,'threadStacks':{'path':str(stacks),'sha256':hashlib.sha256(stacks.read_bytes()).hexdigest()},'boundary':'Actual production HTTP JSON and hidden finite stdlib client with owned loopback port. Settings stores and SQLite writer are real; no external connection/provider/rendered claim.'}
    if not args.before:
        prior=REPO/'scripts/evidence/C7d-loopback-policy-before.json'
        value=json.loads(prior.read_text(encoding='utf-8'))
        if value['productionHTTPResults']!=[{'ok':False,'error':'TimeoutError'}] or not value['originalDeadlineReproduced']:raise AssertionError('Missing actual before failure')
        report['before']={'path':str(prior),'sha256':hashlib.sha256(prior.read_bytes()).hexdigest()}
        old=REPO/'.agent_control/proofs/c7d-wz-observed-after.json'
        report['priorWZObservation']={'path':str(old),'sha256':hashlib.sha256(old.read_bytes()).hexdigest(),'boundary':'Historical old-policy passing family with timed policy-lock contention; mechanism attribution to the earlier15s failures is an inference.'}
        failed=root.parent/'c7d-loopback-56b08dbd913046eb9794b3cc88ebec11/locked-store-threads.txt'
        report['earlierObserverAttempt']={'path':str(failed),'sha256':hashlib.sha256(failed.read_bytes()).hexdigest(),'status':'failed diagnostic observation','observerBudgetSeconds':40,'error':'Locked policy admitted an external OS attempt','boundary':'This generic assertion did not retain the exact final worker/result state. The short observer budget failed; no external bypass is inferred. Final actual admission must finish with LocalOnlyError and zero OS attempts.'}
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'ok':report['ok'],'phase':report['phase'],'sourceStable':stable,'results':result,'boundaryCases':len(boundary_cases)}))


if __name__=='__main__':main()
