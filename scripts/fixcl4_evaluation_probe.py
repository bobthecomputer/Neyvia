"""Actual CL task evidence, trace, pixel, curriculum and managed rehearsal journeys."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from fixcl_verify import REPO, environment


def generate_manuals():
    from grant_agent.cl.fixcl4_evaluation_effects import SUPPORTED
    from grant_agent.innovation_tools import innovation_tool_definitions
    from grant_agent.improvement_tools import improvement_tool_definitions
    from grant_agent.cl.manuals import manual_to_cl, cl_to_manual
    definitions = {row[0]:row for row in innovation_tool_definitions()+improvement_tool_definitions()}
    chapter = {'title':'Evidence-backed task reasoning and local evaluation', 'state':{}, 'actions':{}, 'checks':{},
        'procedures':{}, 'judge':{}, 'pitfalls':[
            {'failure':'A reported answer, trial or trace is presented as independent model quality proof',
             'recovery':'Keep its declared provenance and prove the actual artifact criterion separately.'},
            {'failure':'A saved witness becomes stale after artifact changes',
             'recovery':'Re-read current bytes and definitions; completion is refused until the evidence is restored.'}],
        'frontier':['Semantic correctness of reported answers, trials and traces needs a separate evaluator.',
                    'Model training and promotion require separate real evaluation and authorization.'],
        'guidance':['Use saved obligation IDs and the current question or brief revision.',
                    'Frozen curricula exclude holdout bytes from lesson packets and reject cross-split family leakage.',
                    'Rehearsal runs an existing scoped snapshot script and requires an actual successful managed process.']}
    data = {'schema':'neyvia.manual.v1','id':'local-evaluations','kind':'workflow','schemas':{},'chapters':{'evaluation':chapter}}
    metadata={}
    for name in sorted(SUPPORTED):
        _,description,mutation,properties,required = definitions[name]
        schema={'type':'object','properties':properties,'required':required}
        data['schemas'][name]=schema
        key=name.replace('.','-')
        chapter['actions'][key]={'tool':name,'schema':name,'returns':{'type':'object'},
            'pre':'Scoped intact input artifacts, current task revisions and enabled task evaluation/rehearsal preferences where required',
            'effect':description,'reversible':False}
        chapter['procedures']['verify-'+key]={'goal':description,'inputs':schema,
            'steps':[{'action':key,'args':{k:{'$input':k} for k in properties},'save':'saved'}]}
        metadata[name]={'mutability_class':mutation}
    source=manual_to_cl(data,metadata)
    if cl_to_manual(source)!=data: raise ValueError('Manual roundtrip changed authored semantics')
    (REPO/'manuals/local-evaluations.manual.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8',newline='\n')
    (REPO/'manuals/cl/local-evaluations.cl').write_text(source,encoding='utf-8',newline='\n')
    path=REPO/'config/neyvia_manuals.json'
    index=json.loads(path.read_text(encoding='utf-8'))
    if not any(r['id']=='local-evaluations' for r in index['manuals']):
        index['manuals'].append({'id':'local-evaluations','path':'manuals/local-evaluations.manual.json',
            'clSource':'manuals/cl/local-evaluations.cl','description':'Fresh questions, artifact obligations, frozen curricula, trace and pixel evaluations, managed rehearsal'})
        path.write_text(json.dumps(index,indent=2)+'\n',encoding='utf-8',newline='\r\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--generate-manuals',action='store_true')
    args=parser.parse_args()
    if args.port not in range(48821,48830): parser.error('Explicit assigned port required')
    if args.generate_manuals:
        generate_manuals(); return 0
    root=REPO/'.agent_control/proofs'/('FIXCL4-evaluations-'+str(time.time_ns())); root.mkdir(parents=True)
    environment(root,args.port); os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
    from grant_agent.proof_credential_guard import install,prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(root); install_hidden_subprocess_default(); prepare_broker_fixture(root)
    def guard(event,fields):
        if event in {'socket.connect','socket.bind'}:
            address=fields[1]
            if isinstance(address,tuple) and (address[0] not in {'127.0.0.1','localhost','::1'} or address[1] not in range(48821,48830)):
                raise PermissionError('Assigned loopback ports only')
        if event=='subprocess.Popen':
            command=fields[1]; text=command if isinstance(command,str) else subprocess.list2cmdline(command)
            if 'grant_agent.installed_programs' not in text: raise PermissionError('Only owned hidden rehearsal worker is authorized')
    sys.addaudithook(guard)
    from grant_agent.neyvia_gateway import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.cl.fixcl4_evaluation_effects import SUPPORTED,snapshot_for
    from grant_agent.workspace_intelligence import WorkspaceIntelligence
    from grant_agent.improvement_lab import ImprovementLab
    from grant_agent.experiment_studio import ExperimentStudio
    from grant_agent.ui_command_bus import bus_for
    from PIL import Image
    work='evaluation-fixture'
    store=WorkspaceIntelligence(root,work)
    store.configure_collaboration({'evaluation':True,'rehearsal':True},expected_revision=0,operator_identity='FIXCL4 scoped fixture owner')
    gateway=NeyviaToolGateway(root,allow_mutations=True,permission_mode='full-access',action_scope=work)
    (root/'answer.json').write_text('{"score":3,"ready":true}',encoding='utf-8')
    (root/'train.txt').write_text('Training evidence exact bytes',encoding='utf-8')
    (root/'holdout.txt').write_text('Protected unseen examination bytes',encoding='utf-8')
    write=lambda name,value:(root/name).write_text(json.dumps(value),encoding='utf-8')
    write('baseline.json',{'conditions':{'size':2,'seed':7},'outcomes':[10,12]})
    write('variant.json',{'conditions':{'size':3,'seed':7},'outcomes':[8,9]})
    digest=hashlib.sha256(b'actual-state').hexdigest()
    write('journey.json',[{'kind':'input','id':'read','atMs':0},{'kind':'response','inputId':'read','atMs':30},
        {'kind':'checkpoint','checkpointId':'saved','stateHash':digest,'atMs':31},{'kind':'disconnect','atMs':32},
        {'kind':'reconnect','atMs':40},{'kind':'resume','checkpointId':'saved','stateHash':digest,'atMs':41}])
    Image.new('RGBA',(8,8),(25,50,75,255)).save(root/'before.png')
    candidate=Image.new('RGBA',(8,8),(25,50,75,255)); candidate.putpixel((7,7),(25,50,75,0)); candidate.save(root/'after.png')
    source=root/'source'; source.mkdir()
    (source/'rehearse.py').write_text('from pathlib import Path\nPath("executed.txt").write_text("Actual isolated script executed",encoding="utf-8")\nprint("FIXCL4_REHEARSED")\n',encoding='utf-8')
    ExperimentStudio(root).create('rehearsal',source=str(source))
    lab=ImprovementLab(root)
    lab.quality.define_instrument('limit',{'kind':'json_numeric','key':'score','max':5})
    proof={'schema':'neyvia.FIXCL4.evaluations.v1','root':str(root),'port':args.port,
        'boundary':'Actual bounded artifact mechanisms; reported semantics and model improvement are not independently evaluated.',
        'checks':{},'transcripts':{},'witnesses':[]}
    paths=[REPO/p for p in ('src/grant_agent/cl/fixcl4_evaluation_effects.py','src/grant_agent/workspace_intelligence.py',
        'src/grant_agent/improvement_lab.py','src/grant_agent/improvement_tools.py','src/grant_agent/innovation_tools.py',
        'src/grant_agent/installed_programs.py','manuals/local-evaluations.manual.json','manuals/cl/local-evaluations.cl',
        'scripts/fixcl4_evaluation_probe.py')]
    hashes=lambda:{p.relative_to(REPO).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    proof['sourceHashesAtStart']=hashes()
    cases=[
        ('intelligence.ask_self',{'question':'Does the actual artifact satisfy the ready criterion?','decision':'Use the artifact only after evidence is current'}),
        ('intelligence.obligate',{'artifact':'answer.json','sha256':hashlib.sha256((root/'answer.json').read_bytes()).hexdigest(),
            'criterion':{'type':'json_path','path':'ready','equals':True}}),
        ('intelligence.answer_self',None),
        ('intelligence.brief',{'understanding':'Prove fresh artifact criteria','expected_revision':0,'assumptions':['Evidence can go stale']}),
        ('intelligence.rationale',{'element_id':'criterion','purpose':'Protect evidence freshness','protected_decisions':['freshness'],'evidence_refs':['answer.json']}),
        ('intelligence.handoff',{'objective':'Preserve current evidence','protected_decisions':['freshness'],'answers':{'freshness':'Require the current hash'}}),
        ('lab.uncertainty',{'identity':'uncertain','assumptions':[{'claim':'Artifact is eligible','experiment':'Measure score','probabilityWrong':.3,'impact':10,'cost':2},
            {'claim':'Pixels protected','experiment':'Compare exact pixels','probabilityWrong':.5,'impact':4,'cost':1}]}),
        ('lab.resolve_uncertainty',{'identity':'uncertain','assumption':0,'instrument':'limit','target':'answer.json'}),
        ('lab.causal',{'workId':work,'baseline':'baseline.json','variant':'variant.json','factor':'size'}),
        ('lab.journey',{'path':'journey.json'}),
        ('lab.curriculum',{'identity':'lessons','examples':[{'path':'train.txt','family':'training','split':'train'},
            {'path':'holdout.txt','family':'exam','split':'holdout'}]}),
        ('lab.visual_guard',{'baseline':'before.png','candidate':'after.png','regions':[{'x':0,'y':0,'width':4,'height':4}]}),
        ('lab.rehearse',{'workId':work,'experiment_id':'rehearsal','script':'rehearse.py'})]
    if {n for n,_ in cases}!=SUPPORTED: raise ValueError('Every admitted action requires a positive witness')
    for index,(name,payload) in enumerate(cases):
        if name=='intelligence.answer_self':
            state=store.snapshot(); payload={'question_id':state['selfQuestions'][0]['id'],'answer':'Ready is true in the exact current artifact',
                'checks':[state['obligations'][0]['id']],'expected_revision':0}
        if name.startswith('intelligence.'): payload={'workId':work,'arguments':payload}
        protocol=Protocol(gateway)
        before=snapshot_for(protocol,name,payload)
        identity='FIXCL4-evaluations-'+str(index)
        inputs=','.join(k+'='+json.dumps(v) for k,v in payload.items())
        lines='G local: time.now()["unixSeconds"] > 0\nrun local-evaluations.verify-'+name.replace('.','-')+'('+inputs+')\ndone()'
        action_started=time.perf_counter_ns()
        result=protocol.run(lines,action_id=identity)
        action_duration_ms=(time.perf_counter_ns()-action_started)/1_000_000
        if name=='intelligence.ask_self' and result.get('ok') is True:
            # This trace is recorded from an actual admitted CL action, rather
            # than hand-authored delays claimed as a product interaction.
            write('journey.json',[{'kind':'input','id':identity,'atMs':0},
                {'kind':'response','inputId':identity,'atMs':action_duration_ms},
                {'kind':'checkpoint','checkpointId':'saved-question',
                 'stateHash':hashlib.sha256(store.path.read_bytes()).hexdigest(),'atMs':action_duration_ms}])
            proof['observedJourneyAction']={'actionIdentity':identity,'durationMs':action_duration_ms,
                'stateSha256':hashlib.sha256(store.path.read_bytes()).hexdigest()}
        proof['transcripts'][name]=result; proof['checks'][name+'-CLDone']=result.get('ok') is True
        uses=[e['payload'] for e in bus_for(root).since(0) if e['action']=='cl.manual.use']
        admitted=[u for u in uses if u.get('tool')==name and u.get('manual')=='local-evaluations' and u.get('status')=='admitted' and u.get('effectChecks') and u.get('actionIdentity','').startswith(identity+':')]
        proof['checks'][name+'-manualReceipt']=len(admitted)==1
        proof['checks'][name+'-freshCompletion']=protocol.run('done()',action_id=identity).get('ok') is True
        print(json.dumps({'tool':name,'ok':result.get('ok'),'status':result.get('status'),'error':result.get('error')}),flush=True)
        if not result.get('ok'): continue
        if name.startswith('intelligence.'):
            if name=='intelligence.handoff':
                target=next(p for p in store.base.glob('*handoff*.json') if str(p) not in before['files'])
            elif name in {'intelligence.obligate','intelligence.answer_self'}: target=root/'answer.json'
            else: target=store.path
        elif name=='lab.rehearse':
            from grant_agent.installed_programs import InstalledPrograms
            session=InstalledPrograms(root).list_sessions()['sessions'][0]
            target=Path(session['sourceRecipe']['arguments'][0])
            proof['checks']['rehearsalActualOutput']=session['exitCode']==0 and 'FIXCL4_REHEARSED' in session['stdout'] and (Path(session['workingDirectory'])/'executed.txt').read_text()=='Actual isolated script executed'
        elif before['sources']: target=Path(next(iter(before['sources'])))
        else: target=next(p for p in lab.base.glob('*.json') if str(p) not in before['files'])
        clean=target.read_bytes(); target.write_bytes(b'changed actual witness artifact')
        drift=protocol.run('done()',action_id=identity); target.write_bytes(clean)
        proof['checks'][name+'-freshDriftRefused']=drift.get('ok') is False
        proof['transcripts'][name+'-drift']=drift
        proof['witnesses'].append({'tool':name,'actionIdentity':identity,'positiveCL':result,'manualReceipt':admitted,
            'freshDriftRefused':drift.get('ok') is False,'driftSubject':str(target)})
    # Exercise the defining refusal paths with fresh CL identities.
    def negative(label,name,payload):
        inputs=','.join(k+'='+json.dumps(v) for k,v in payload.items())
        result=Protocol(gateway).run('G local: time.now()["unixSeconds"] > 0\nrun local-evaluations.verify-'+name.replace('.','-')+'('+inputs+')\ndone()',action_id='FIXCL4-negative-'+label)
        proof['transcripts'][label]=result; return result
    rejected=negative('heldout-family-leak','lab.curriculum',{'identity':'bad-lessons','examples':[{'path':'train.txt','family':'same','split':'train'},{'path':'holdout.txt','family':'same','split':'holdout'}]})
    proof['checks']['holdoutFamilyLeakRefused']=rejected.get('ok') is False
    proof['checks']['holdoutNeverDisclosed']='Protected unseen' not in json.dumps(lab.lesson_packet('lessons'))
    write('variant.json',{'conditions':{'size':3,'seed':8},'outcomes':[8,9]})
    confounded=negative('confounded','lab.causal',{'workId':work,'baseline':'baseline.json','variant':'variant.json','factor':'size'})
    saved=[json.loads(p.read_bytes()) for p in lab.base.glob('receipt-*.json')]
    proof['checks']['confoundingExposedWithoutCausalityClaim']=confounded.get('ok') is True and any(r.get('kind')=='causal_comparison' and r.get('status')=='confounded' and r['pairedDeltas']==[] and r['causalityProven'] is False for r in saved)
    changed=negative('alpha-change','lab.visual_guard',{'baseline':'before.png','candidate':'after.png','regions':[{'x':7,'y':7,'width':1,'height':1}]})
    saved=[json.loads(p.read_bytes()) for p in lab.base.glob('receipt-*.json')]
    proof['checks']['alphaChangeDetected']=changed.get('ok') is True and any(r.get('kind')=='visual_guard' and r['protectedPixelsUnchanged'] is False for r in saved)
    write('bad-continuity.json',[{'kind':'input','id':'read','atMs':0},{'kind':'response','inputId':'read','atMs':1},
        {'kind':'checkpoint','checkpointId':'saved','stateHash':digest,'atMs':2},
        {'kind':'resume','checkpointId':'saved','stateHash':'0'*64,'atMs':3}])
    continuity=negative('continuity-mismatch','lab.journey',{'path':'bad-continuity.json'})
    saved=[json.loads(p.read_bytes()) for p in lab.base.glob('receipt-*.json')]
    proof['checks']['continuityMismatchPreventsSuccessfulJourney']=continuity.get('ok') is True and any(r.get('kind')=='journey' and r['continuityMismatches']==['saved'] and r['journeySuccessful'] is False for r in saved)
    state=store.snapshot(); question=state['selfQuestions'][0]
    original=(root/'answer.json').read_bytes(); write('answer.json',{'score':3,'ready':False})
    unsupported=negative('stale-answer','intelligence.answer_self',{'workId':work,'arguments':{'question_id':question['id'],'answer':'The stale claim remains unproven',
        'checks':question['checks'],'expected_revision':question['revision']}})
    proof['checks']['staleAnswerNeverMarkedSupported']=unsupported.get('ok') is True and store.self_questions()['questions'][0]['status']=='needs_recheck'
    (root/'answer.json').write_bytes(original)
    proof['sourceHashesAtEnd']=hashes(); proof['checks']['sourceUnchanged']=proof['sourceHashesAtStart']==proof['sourceHashesAtEnd']
    proof['ok']=all(proof['checks'].values())
    output=REPO/'scripts/evidence/FIXCL4-evaluations.json'; output.write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'ok':proof['ok'],'witnesses':len(proof['witnesses']),'failed':[k for k,v in proof['checks'].items() if not v],'receipt':str(output)}))
    return 0 if proof['ok'] else 1


if __name__=='__main__': raise SystemExit(main())
