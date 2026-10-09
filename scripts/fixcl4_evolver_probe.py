"""Real CL evolution with locked judges, actual paired manuals and adverse loss."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from fixcl_verify import REPO,environment


def generate():
    from grant_agent.neyvia_evolver import DEFINITIONS
    from grant_agent.cl.manuals import manual_to_cl,cl_to_manual
    _,description,properties,required=next(row for row in DEFINITIONS if row[0]=='evolver.run')
    schema={'type':'object','properties':properties,'required':required}
    name='neyvia.evolver.run'
    chapter={'title':'Frozen local manual compression','state':{},'actions':{'run':{'tool':name,'schema':name,
        'returns':{'type':'object'},'pre':'Owned root and request identity; installed offline Rust engine; actual frozen manual files; current policy permits managed child processes',
        'effect':'Run real manual_json_local_v1 parse, compiler, roundtrip and token measurements on matched seeded cases',
        'reversible':False}},'checks':{},'procedures':{'verify-local-manual-evolution':{
            'goal':'Finish a real frozen paired lossless compression trial, reconfirm on two fresh heldout panels, and update the local Pareto front',
            'inputs':schema,'steps':[{'action':'run','args':{k:{'$input':k} for k in required}|{'maxTrials':1},'save':'saved'}]}},
        'judge':{},'pitfalls':[{'failure':'A queued job or synthetic score is called an evaluated improvement',
            'recovery':'Wait for actual parse/compiled artifacts; compare current bytes, paired seeds, frozen panels and counted engine trials.'},
            {'failure':'Compression removes instructions or protected checks','recovery':'Retain the rejected candidate; exact semantic and compiler roundtrip gates prevent promotion.'}],
        'frontier':['manual_json_local_v1 measures lossless JSON compression, not model task accuracy.',
                    'Other domain routes retain their named GPT-6 Luna transport and need separate matched provider evaluations.'],
        'guidance':['No models or downloads are used in this named local domain.',
                    'Reuse requestId after interruptions; frozen judges and manual inputs cannot be changed inside an established domain.',
                    'Local-only blocks all managed children, including this offline Rust engine; preserve that policy.']}
    # maxTrials is bound to one real candidate and is not an unused procedure input.
    chapter['procedures']['verify-local-manual-evolution']['inputs']={'type':'object','properties':{k:properties[k] for k in required},'required':required}
    data={'schema':'neyvia.manual.v1','id':'local-evolver','kind':'workflow','schemas':{name:schema},'chapters':{'evolution':chapter}}
    metadata={name:{'mutability_class':'external_action'}}
    source=manual_to_cl(data,metadata)
    if cl_to_manual(source)!=data: raise ValueError('Manual roundtrip drift')
    (REPO/'manuals/local-evolver.manual.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8',newline='\n')
    (REPO/'manuals/cl/local-evolver.cl').write_text(source,encoding='utf-8',newline='\n')
    path=REPO/'manuals/hill-climb.manual.json'; old=json.loads(path.read_text(encoding='utf-8'))
    old['schemas'][name]=schema
    old['chapters']['evolver']['actions']['evolver.run']['effect']='Start a bounded named frozen domain; local compression uses no model; the other domains use GPT-6 Luna'
    from grant_agent.native_tools import NativeToolRegistry
    registry=NativeToolRegistry(REPO/'.agent_control/proofs/FIXCL4-evolver-manual-schema')
    full_metadata={name:{'mutability_class':spec.mutability_class} for name,spec in registry._specs.items()}
    source=manual_to_cl(old,full_metadata)
    if cl_to_manual(source)!=old: raise ValueError('Hill-climb schema roundtrip drift')
    path.write_text(json.dumps(old,indent=2)+'\n',encoding='utf-8',newline='\n')
    (REPO/'manuals/cl/hill-climb.cl').write_text(source,encoding='utf-8',newline='\n')
    path=REPO/'config/neyvia_manuals.json'; index=json.loads(path.read_text(encoding='utf-8'))
    if not any(row['id']=='local-evolver' for row in index['manuals']):
        index['manuals'].append({'id':'local-evolver','path':'manuals/local-evolver.manual.json',
            'clSource':'manuals/cl/local-evolver.cl','description':'Real frozen paired manual compiler compression, seeded cases and independent heldout reconfirmation'})
        path.write_text(json.dumps(index,indent=2)+'\n',encoding='utf-8',newline='\r\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--port',type=int,required=True); parser.add_argument('--generate-manuals',action='store_true')
    args=parser.parse_args()
    if args.port not in range(48821,48830): parser.error('Explicit assigned loopback port required')
    root=REPO/'.agent_control/proofs'/('FIXCL4-evolver-'+str(time.time_ns())); root.mkdir(parents=True)
    environment(root,args.port); os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
    from grant_agent.proof_credential_guard import install,prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(root); install_hidden_subprocess_default(); prepare_broker_fixture(root)
    if args.generate_manuals: generate(); return 0
    def guard(event,fields):
        if event in {'socket.connect','socket.bind'}: raise PermissionError('Local deterministic evolution needs no network')
        if event=='subprocess.Popen':
            command=fields[1]; text=command if isinstance(command,str) else subprocess.list2cmdline(command)
            if not any(marker in text for marker in ('grant_agent.neyvia_evolver','evolver-text-core.exe')): raise PermissionError('Only owned hidden engine workers allowed')
    sys.addaudithook(guard)
    from grant_agent.neyvia_gateway import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.ui_command_bus import bus_for
    from grant_agent.evolver_manual_local import DOMAIN,domain_spec,INVALID,ManualCompressionEvaluator
    from grant_agent.evolver_core import EvolverEngine,FrozenJudgeError
    from grant_agent.neyvia_evolver import job,start
    from grant_agent.neyvia_workspace_tools import workspace_for
    from grant_agent.neyvia_settings import _state
    service=workspace_for(root)
    gateway=NeyviaToolGateway(root,allow_mutations=True,permission_mode='full-access',action_scope='FIXCL4-evolver')
    protocol=Protocol(gateway)
    proof={'schema':'neyvia.FIXCL4.evolver.v1','root':str(root),'port':args.port,'checks':{},'transcripts':{},'witnesses':[],
        'boundary':'Real local compression of actual manual files; no model accuracy or public-release promotion claim'}
    with service.bus.connect() as db: proof['checks']['managedChildPolicyAllowsLocalWorker']=_state(db)[1]['localOnly'] is False
    paths=[REPO/p for p in ('src/grant_agent/evolver_manual_local.py','src/grant_agent/evolver_core.py','src/grant_agent/neyvia_evolver.py',
        'src/grant_agent/cl/fixcl4_evolver_effects.py','scripts/run_t13_evolution.py','scripts/fixcl4_evolver_probe.py',
        'manuals/local-evolver.manual.json','manuals/cl/local-evolver.cl','manuals/hill-climb.manual.json','manuals/cl/hill-climb.cl')]
    paths+=list(map(Path,domain_spec()['judges']))
    paths=list(dict.fromkeys(paths))
    hashes=lambda:{p.relative_to(REPO).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    proof['sourceHashesAtStart']=hashes()
    identity='FIXCL4-evolver-owned-request'
    lines='G local: time.now()["unixSeconds"] > 0\nrun local-evolver.verify-local-manual-evolution(domain="'+DOMAIN+'",requestId="'+identity+'")\ndone()'
    result=protocol.run(lines,action_id=identity)
    print(json.dumps({'phase':'positiveCL','ok':result.get('ok'),'status':result.get('status'),'error':result.get('error')}),flush=True)
    proof['transcripts']['evolver.run']=result; proof['checks']['evolver.run-CLDone']=result.get('ok') is True
    uses=[e['payload'] for e in bus_for(root).since(0) if e['action']=='cl.manual.use']
    admitted=[u for u in uses if u.get('tool')=='neyvia.evolver.run' and u.get('manual')=='local-evolver' and u.get('status')=='admitted' and u.get('effectChecks') and u.get('actionIdentity','').startswith(identity+':')]
    proof['checks']['evolver.run-manualReceipt']=len(admitted)==1
    proof['checks']['evolver.run-freshCompletion']=protocol.run('done()',action_id=identity).get('ok') is True
    saved=job(root,identity)['job']; proof['actualJob']=saved
    if result.get('ok'):
        engine=EvolverEngine(root/'.neyvia/evolver.sqlite3')
        current=engine.status(DOMAIN)['domains'][0]; trial=current['receipts'][0]
        artifact=Path(trial['stages'][1]['pairs'][0]['candidate']['receipt']['artifact'])
        clean=artifact.read_bytes(); artifact.write_text('{"lost":"protected criterion"}',encoding='utf-8')
        drift=protocol.run('done()',action_id=identity); artifact.write_bytes(clean)
        proof['checks']['evolver.run-freshDriftRefused']=drift.get('ok') is False
        proof['transcripts']['artifact-drift']=drift
        proof['witnesses'].append({'tool':'neyvia.evolver.run','actionIdentity':identity,'positiveCL':result,
            'manualReceipt':admitted,'freshDriftRefused':drift.get('ok') is False,'driftSubject':str(artifact)})
        replay=start(root,{'domain':DOMAIN,'requestId':identity,'maxTrials':1})
        proof['checks']['sameRequestDoesNotDuplicateTrial']=replay.get('replayed') is True and engine.status(DOMAIN)['domains'][0]['trials']==1
        proof['checks']['actualLocalIncumbentAndPareto']=trial['promoted'] is True and current['incumbent']==trial['candidate'] and len(current['pareto_front'])>0
        proof['checks']['twoFreshDisjointHeldoutPanels']=len(set(current['held_out_used']))==2 and len(trial['stages'])==3
        pairs=[pair for stage in trial['stages'] for pair in stage['pairs']]
        proof['checks']['all36PairsMeasuredActualBytePreservation']=len(pairs)==36 and all(all(pair[side]['hard_gates'].values()) for pair in pairs for side in ('incumbent','candidate'))
        proof['observedTokens']={'incumbent':sum(p['incumbent']['receipt']['tokens'] for p in pairs),'candidate':sum(p['candidate']['receipt']['tokens'] for p in pairs),
            'cases':len(pairs),'encoding':'exact o200k_base, text only'}
        # Actual semantic loss is a separate counted trial, preserved as rejected.
        bad=engine.register_genome(DOMAIN,{'kind':'text','text':INVALID},parent_id=current['incumbent'],operator='adverse-semantic-loss',provenance={'purpose':'controlled refusal fixture'})
        rejected=engine.evaluate_candidate(DOMAIN,bad['id'],ManualCompressionEvaluator(root))
        proof['adverseTrial']=rejected
        after=engine.status(DOMAIN)['domains'][0]
        proof['checks']['semanticLossCountedAndNeverPromoted']=rejected['state']=='rejected' and rejected['promoted'] is False and after['trials']==2 and after['incumbent']==current['incumbent'] and not rejected['stages'][0]['hard_gates_passed']
        with engine._db() as db:
            original=db.execute('SELECT spec FROM domains WHERE id=?',(DOMAIN,)).fetchone()['spec']
            changed=json.loads(original); changed['promotion']['seed']+=1
            db.execute('UPDATE domains SET spec=? WHERE id=?',(json.dumps(changed),DOMAIN))
        try:
            engine._verify_frozen(DOMAIN); refused=False
        except FrozenJudgeError: refused=True
        finally:
            with engine._db() as db: db.execute('UPDATE domains SET spec=? WHERE id=?',(original,DOMAIN))
        proof['checks']['tamperedFrozenPanelPolicyRefused']=refused
    proof['sourceHashesAtEnd']=hashes(); proof['checks']['sourceUnchanged']=proof['sourceHashesAtStart']==proof['sourceHashesAtEnd']
    proof['ok']=all(proof['checks'].values())
    output=REPO/'scripts/evidence/FIXCL4-evolver.json'; output.write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'ok':proof['ok'],'failed':[k for k,v in proof['checks'].items() if not v],'tokens':proof.get('observedTokens'),'receipt':str(output)}))
    return 0 if proof['ok'] else 1


if __name__=='__main__': raise SystemExit(main())
