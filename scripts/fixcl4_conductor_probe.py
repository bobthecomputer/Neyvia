"""Real advertised Codex routes and owned detached Conductor provider turns."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time

from fixcl_verify import REPO, environment, bind_fixture_broker
from fixcl4_service_source_hashes import service_source_hashes


def inspect_retained(port, output):
    """Fresh replay and adverse drift checks on a real terminal provider job."""
    if port not in range(48821,48830):
        raise ValueError('FIXCL assigned port required')
    import sqlite3
    from grant_agent.proof_credential_guard import install
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.harness_jobs import HarnessJobStore, _atomic_write_json
    from grant_agent.neyvia_workspace_tools import workspace_for
    proof=json.loads(output.read_bytes());root=Path(proof['root']);environment(root,port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL',None);os.environ['NEYVIA_WEB_PORT']=str(port);install(root)
    job=next(row['observation'] for row in reversed(proof['journeys']) if 'observation' in row)
    identity=job['id'];store=HarnessJobStore(root);path=store.job_path(identity);original=path.read_bytes()
    args={'requestId':'fixcl4-real-conductor',**job['request']['intent']}
    gateway=NeyviaToolGateway(root,allow_mutations=True,action_scope='FIXCL4-conductor-retained',permission_mode='workspace')
    p=Protocol(gateway,lazy_manuals=True)
    database=root/'.agent_control/connected_chats.sqlite3'
    with sqlite3.connect(database) as db:
        count=db.execute('SELECT count(*) FROM connected_session_runs').fetchone()[0]
    result=p.run('G: conductor.get(id='+json.dumps(identity)+')["job"]["id"] == '+json.dumps(identity)+'\nconductor.plan('+','.join(k+'='+json.dumps(v) for k,v in args.items())+')\ndone()',action_id='real-plan-retained-replay')
    proof['retainedReplay']={'result':result,'completion':p.completion()}
    proof['checks']['retained-real-plan-replay-cl']=result['ok'] and p.completion()['status']=='completed'
    try:
        changed=json.loads(original);changed['conductor']['tasks'][0]['prompt']='Changed after actual terminal model run'
        _atomic_write_json(path,changed)
        proof['checks']['fresh-plan-task-drift-refused']=p.completion()['status']=='incomplete'
    finally:
        path.write_bytes(original)
    with sqlite3.connect(database) as db:
        run_id=identity+'-plan';saved=db.execute('SELECT data FROM connected_session_runs WHERE run_id=?',(run_id,)).fetchone()[0]
        try:
            changed=json.loads(saved);changed['model']='changed-after-real-run'
            db.execute('UPDATE connected_session_runs SET data=? WHERE run_id=?',(json.dumps(changed),run_id));db.commit()
            proof['checks']['fresh-plan-provider-identity-drift-refused']=p.completion()['status']=='incomplete'
        finally:
            db.execute('UPDATE connected_session_runs SET data=? WHERE run_id=?',(saved,run_id));db.commit()
        proof['checks']['replay-no-provider-turn-duplication']=db.execute('SELECT count(*) FROM connected_session_runs').fetchone()[0]==count
    proof['retainedRestoreDone']=p.run('done()')
    proof['checks']['retained-job-exact-restoration']=path.read_bytes()==original and p.completion()['status']=='completed'
    workspace_for(root).close();proof['ok']=all(proof['checks'].values())
    output.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return proof


def run(port, output):
    if port not in range(48821,48830):
        raise ValueError('FIXCL assigned port required')
    source_start=service_source_hashes()
    root=REPO/'.agent_control/proofs'/('FIXCL4-conductor-'+str(time.time_ns()))
    root.mkdir(parents=True)
    environment(root,port);os.environ.pop('NEYVIA_UI_BACKEND_URL',None);os.environ['NEYVIA_WEB_PORT']=str(port)
    from grant_agent.proof_credential_guard import install,prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(root);install_hidden_subprocess_default();prepare_broker_fixture(root);bind_fixture_broker(root)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.neyvia_workspace_tools import workspace_for
    from grant_agent.neyvia_manuals import unwrap
    from grant_agent.neyvia_runtime import request
    from grant_agent.cl.protocol import Protocol
    gateway=NeyviaToolGateway(root,allow_mutations=True,action_scope='FIXCL4-conductor',permission_mode='workspace')
    service=workspace_for(root)
    (root/'alpha.txt').write_bytes(b'FIXCL4 alpha\n')
    proof={'schema':'neyvia.FIXCL4.conductor.v1','root':str(root),'checks':{},'journeys':[], 'sourceHashesAtStart':source_start,
           'artifactBefore':{'betaExists':(root/'beta.txt').exists()}}
    from grant_agent.connected_sessions.codex_rpc import resolve_command
    from grant_agent.proof_credential_guard import authorize_provider_transport
    proof['transportAuthorization'] = authorize_provider_transport(root, resolve_command())
    from grant_agent.proof_credential_guard import self_check, check_process
    import subprocess
    proof['guard'] = self_check(root)
    proof['checks']['all-saved-credential-denials'] = proof['guard']['ok']
    command = resolve_command()
    for label, denied in (('quoted-provider-string', subprocess.list2cmdline([*command, '--altered'])),
                          ('altered-provider-argv', [*command, '--altered'])):
        try:
            check_process(denied)
        except PermissionError:
            proof['checks'][label] = True
        else:
            proof['checks'][label] = False
    try:
        authorize_provider_transport(REPO, command)
    except ValueError:
        proof['checks']['wrong-root-authorization-denied'] = True
    else:
        proof['checks']['wrong-root-authorization-denied'] = False
    def save():
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    job=None
    def begin(key, name, args, goal):
        protocol = Protocol(gateway,lazy_manuals=True)
        result = protocol.run('G: '+goal+'\n'+name+'('+','.join(k+'='+json.dumps(v) for k,v in args.items())+')',action_id=key)
        proof['journeys'].append({'action':key,'result':result});save()
        return protocol
    def finish(key, protocol):
        result=protocol.run('done()')
        completed=protocol.completion()
        proof['journeys'].append({'action':key+'-done','result':result,'completion':completed})
        proof['checks'][key]=result['ok'] and completed['status']=='completed';save()
    try:
        options=service.broker().provider_options('codex')
        proof['advertisedRoutes']={key:options.get(key) for key in ('models','permissionModes','errors')};save()
        for role in ('planner','executor','verifier'):
            observed=request(service,{'action':'profile','name':role,'route':{'app':'codex','model':'gpt-6.1-sol','effort':'low','permissionMode':'auto'}},'POST')
            proof['journeys'].append({'profile':role,'observed':observed});save()
        identity='harness-job-conductor-'+__import__('hashlib').sha256(b'fixcl4-real-conductor').hexdigest()[:32]
        planned=begin('real-plan-cl','conductor.plan',{'requestId':'fixcl4-real-conductor','goal':'Use an available command execution tool to read alpha.txt byte-wise and create beta.txt as its byte-identical copy, then report the copied contents. Perform the work, rather than describing it. Only beta.txt may be created or modified. Stay within this folder. Do not read credentials, account files, the NAS runbook, other repositories or call any local port; never install/download, create visible windows or delegate.',
            'folder':str(root),'acceptanceChecks':['alpha.txt is exactly 13 bytes with hexadecimal 464958434c3420616c7068610a (ASCII FIXCL4 alpha followed by one LF byte)','beta.txt exists and is a byte-identical copy of alpha.txt'],'maxRuntimeSeconds':360},'conductor.get(id='+json.dumps(identity)+')["job"]["conductor"]["phase"] == "ready"')
        job=unwrap(gateway.native.call('neyvia.conductor.get',{'id':identity}))['job']
        def wait_for(terminal,seconds):
            nonlocal job
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline and not terminal(job):
                time.sleep(.3);job=unwrap(gateway.native.call('neyvia.conductor.get',{'id':job['id']}))['job']
            proof['journeys'].append({'observation':job});save()
        wait_for(lambda row:row.get('conductor',{}).get('phase') in {'ready','failed'} or row['status'] in {'failed','completed','cancelled'},90)
        proof['checks']['real-generated-plan-ready']=job.get('conductor',{}).get('phase')=='ready' and bool(job['conductor']['tasks']);save()
        if proof['checks']['real-generated-plan-ready']:
            finish('real-plan-cl',planned)
            for control in ('pause','resume','start'):
                key='real-control-'+control+'-cl'
                controlled=begin(key,'conductor.control',{'id':job['id'],'action':control},'conductor.get(id='+json.dumps(identity)+')["job"]["conductorControl"]["paused"] == '+('true' if control=='pause' else 'false'))
                wait_for(lambda row:row.get('conductor',{}).get('phase')=='paused' if control=='pause' else row.get('conductor',{}).get('phase')=='running',10)
                finish(key,controlled)
            wait_for(lambda row:row['status'] in {'failed','completed','cancelled'},360)
            proof['checks']['real-conductor-completed']=job['status']=='completed' and job.get('conductor',{}).get('phase')=='completed';save()
            proof['checks']['real-executor-created-exact-artifact']=not proof['artifactBefore']['betaExists'] and (root/'beta.txt').exists() and (root/'beta.txt').read_bytes()==(root/'alpha.txt').read_bytes()==b'FIXCL4 alpha\n'
            if (root/'beta.txt').exists():
                proof['artifactAfter']={'path':str(root/'beta.txt'),'sha256':__import__('hashlib').sha256((root/'beta.txt').read_bytes()).hexdigest(),'bytes':(root/'beta.txt').stat().st_size}
            save()
    except Exception as exc:
        proof['error']={'type':type(exc).__name__,'message':str(exc)};proof['checks']['actual-conductor-journey']=False
    finally:
        if job and job['status'] not in {'failed','completed','cancelled'}:
            proof['ownedCleanup']=gateway.native.call('neyvia.conductor.control',{'id':job['id'],'action':'stop'})
        service.close();proof['sourceHashesAtEnd']=service_source_hashes()
        proof['checks']['sourceUnchanged']=proof['sourceHashesAtEnd']==source_start
        proof['ok']=bool(proof['checks']) and all(proof['checks'].values());save()
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--inspect-retained',action='store_true');args=parser.parse_args()
    result=inspect_retained(args.port,args.output) if args.inspect_retained else run(args.port,args.output)
    print(json.dumps({'ok':result['ok'],'checks':result['checks'],'error':result.get('error')}));sys.exit(0 if result['ok'] else 1)
