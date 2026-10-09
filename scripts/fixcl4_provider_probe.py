"""Real selected-provider Autopilot and Conductor journeys, no model fixtures."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from fixcl_verify import REPO, environment, bind_fixture_broker
from fixcl4_service_source_hashes import service_source_hashes


def run(port, conductor=False):
    if port not in range(48821,48830):
        raise ValueError('FIXCL assigned port required')
    os.environ['NEYVIA_AUTOPILOT_SMALL_MODEL']='gpt-6.1-sol'
    source_start=service_source_hashes()
    root=REPO/'.agent_control/proofs'/('FIXCL4-provider-'+str(time.time_ns()))
    root.mkdir(parents=True)
    environment(root,port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
    os.environ['NEYVIA_WEB_PORT']=str(port)
    from grant_agent.proof_credential_guard import install,prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(root)
    install_hidden_subprocess_default()
    # Register only each selected real judgement's complete argv. The guard
    # continues to deny every other Node-hosted/provider command string.
    from grant_agent import autopilot_model
    from grant_agent.proof_credential_guard import authorize_provider_transport
    original_popen = autopilot_model.subprocess.Popen
    selected_command = autopilot_model._command()
    class SelectedPopen(original_popen):
        def __init__(self, command, *positional, **keyword):
            if (isinstance(command,list) and command[:len(selected_command)] == selected_command and
                    command[len(selected_command):len(selected_command)+2] == ['exec','--json'] and
                    '--ignore-user-config' in command and '--ignore-rules' in command and
                    command[command.index('--sandbox')+1] == 'read-only' and
                    command[command.index('--model')+1] == 'gpt-6.1-sol'):
                authorize_provider_transport(root,command)
            super().__init__(command,*positional,**keyword)
    autopilot_model.subprocess.Popen = SelectedPopen
    prepare_broker_fixture(root)
    backend=bind_fixture_broker(root)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.neyvia_manuals import unwrap
    from grant_agent.neyvia_workspace_tools import workspace_for
    gateway=NeyviaToolGateway(root,allow_mutations=True,action_scope='FIXCL4-provider',permission_mode='workspace')
    service=workspace_for(root)
    for name in ('alpha','beta'):
        (root/(name+'.txt')).write_text('FIXCL4 '+name+'\n',encoding='utf-8')
    proof={'schema':'neyvia.FIXCL4.provider.v1','root':str(root),'checks':{},'journeys':{},'models':[], 'sourceHashesAtStart':source_start}
    def action(key,name,args,goal):
        p=Protocol(gateway,lazy_manuals=True)
        lines='G: '+goal+'\n'+name+'('+','.join(k+'='+json.dumps(v) for k,v in args.items())+')\ndone()'
        started=time.perf_counter()
        result=p.run(lines,action_id=key)
        proof['journeys'][key]={'result':result,'completion':p.completion(),'elapsedMs':round((time.perf_counter()-started)*1000,3)}
        proof['checks'][key]=bool(result['ok'] and p.completion()['status']=='completed')
        return p
    args={'requestId':'fixcl4-real-multi-ask','text':'Read '+str(root/'alpha.txt')+' and verify the exact contents include FIXCL4 alpha. Also read '+str(root/'beta.txt')+' and verify the exact contents include FIXCL4 beta. Keep both asks as separate checklist items; use existing read-file procedures.',
          'scopeTools':['workspace.read'],'efficiency':False,'maxModelCalls':3,'maxSeconds':60}
    identity=hashlib.sha256(args['requestId'].encode()).hexdigest()[:32]
    start=action('real-autopilot-start','autopilot.start',args,'autopilot.get(runId='+json.dumps(identity)+')["run"]["status"] == "completed"')
    from grant_agent.neyvia_autopilot import state_path, load
    observed=load(service,identity) if state_path(service,identity).exists() else {}
    proof['models']=observed.get('models',[])
    proof['retainedRun']=observed
    if proof['checks']['real-autopilot-start']:
        beforeItems=json.dumps(observed['items'],sort_keys=True)
        beforeModels=json.dumps(observed['models'],sort_keys=True)
        resume=action('real-autopilot-resume-completed','autopilot.resume',{'runId':identity},'autopilot.get(runId='+json.dumps(identity)+')["run"]["status"] == "completed"')
        fresh=unwrap(gateway.native.call('neyvia.autopilot.get',{'runId':identity}))['run']
        proof['checks']['resume-preserves-effects-and-model-count']=(beforeItems==json.dumps(fresh['items'],sort_keys=True) and beforeModels==json.dumps(fresh['models'],sort_keys=True))
        (root/'beta.txt').write_text('Changed after successful actual run\n',encoding='utf-8')
        proof['checks']['autopilot-fresh-source-drift-refuses']=resume.completion()['status']=='incomplete'
    if conductor:
        from grant_agent.neyvia_runtime import request
        options=service.broker().provider_options('codex')
        proof['conductorOptions']={key:options.get(key) for key in ('models','permissionModes','errors')}
        for role in ('planner','executor','verifier'):
            request(service,{'action':'profile','name':role,'route':{'app':'codex','model':'gpt-6.1-sol','effort':'low','permissionMode':'read-only'}},'POST')
        output=gateway.native.call('neyvia.conductor.plan',{'requestId':'fixcl4-real-conductor','goal':'Read alpha.txt and report its contents. Do not modify files.',
            'folder':str(root),'acceptanceChecks':['alpha.txt contains FIXCL4 alpha.'],'maxRuntimeSeconds':120})
        proof['conductorInitial']=output
        if output.get('ok'):
            job=unwrap(output)['job'];deadline=time.monotonic()+80
            while time.monotonic()<deadline and job.get('conductor',{}).get('phase') not in {'ready','failed'} and job['status'] not in {'failed','completed','cancelled'}:
                time.sleep(.3)
                job=unwrap(gateway.native.call('neyvia.conductor.get',{'id':job['id']}))['job']
            proof['conductorPlanned']=job
            if job.get('conductor',{}).get('phase')=='ready':
                proof['conductorStart']=gateway.native.call('neyvia.conductor.control',{'id':job['id'],'action':'start'})
                deadline=time.monotonic()+100
                while time.monotonic()<deadline and job['status'] not in {'failed','completed','cancelled'}:
                    time.sleep(.3)
                    job=unwrap(gateway.native.call('neyvia.conductor.get',{'id':job['id']}))['job']
                proof['conductorTerminal']=job
                proof['checks']['real-conductor-completed']=job['status']=='completed' and job.get('conductor',{}).get('phase')=='completed'
            if job['status'] not in {'failed','completed','cancelled'}:
                proof['conductorOwnedCleanup']=gateway.native.call('neyvia.conductor.control',{'id':job['id'],'action':'stop'})
    service.close()
    autopilot_model.subprocess.Popen = original_popen
    proof['sourceHashesAtEnd']=service_source_hashes()
    proof['checks']['sourceUnchanged']=proof['sourceHashesAtEnd']==source_start
    proof['ok']=all(proof['checks'].values())
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--conductor',action='store_true')
    args=parser.parse_args(); result=run(args.port,args.conductor)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'ok':result['ok'],'checks':result['checks'],'models':[{key:row.get(key) for key in ('model','status','tokens','elapsedMs')} for row in result['models']]}))
    sys.exit(0 if result['ok'] else 1)
