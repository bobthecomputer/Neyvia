import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const root=mkdtempSync(path.join(tmpdir(),'neyvia-improvement-lab-'));
try {
 const run=spawnSync(resolveNeyviaPython(process.cwd()).python,['-c',String.raw`
import json,sys,time
from pathlib import Path
from PIL import Image
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.improvement_lab import ImprovementLab
from grant_agent.installed_programs import InstalledPrograms,_load
from grant_agent.contextual_learning import ContextualLearningStore
from grant_agent.resource_admission import ProcessAdmission
from grant_agent.workspace_intelligence import WorkspaceIntelligence,COLLABORATION_FEATURE_TOOLS
from grant_agent.neyvia_agent import NeyviaToolGateway,NeyviaAgentConfig,_codex_neyvia_mcp_args
root=Path(sys.argv[1]);lab=ImprovementLab(root);r=NativeToolRegistry(root)
WorkspaceIntelligence(root,'lab-proof').configure_collaboration({'evaluation':True,'rehearsal':True},expected_revision=0,operator_identity='fixture')
def call(name,**args):
 if name in COLLABORATION_FEATURE_TOOLS:args['workId']='lab-proof'
 v=r.call(name,args)
 if not v['ok']:raise RuntimeError(json.dumps(v))
 return v['result']
def denied(fn):
 try:fn();return False
 except (ValueError,FileNotFoundError,PermissionError):return True
source=root/'app';source.mkdir();(source/'run.js').write_text("require('fs').writeFileSync(require('path').join(__dirname,'score.json'),JSON.stringify({score:2}));")
call('lab.instrument',identity='score',spec={'kind':'json_numeric','key':'score','max':3})
comp=call('lab.competition',identity='compare-app',source='app',candidates=['a','b'],instruments=['score'])
second=Path(comp['candidates'][1]['path'])/'run.js';second.write_text(second.read_text().replace('score:2','score:4'))
sessions=[call('lab.rehearse',experiment_id=c['experimentId'],script='run.js')['session']['sessionId'] for c in comp['candidates']]
host=InstalledPrograms(root)
for i in range(120):
 states=[host.status(s) for s in sessions]
 if all(s['status'] in {'completed','failed','timed_out','unknown'} for s in states):break
 time.sleep(.1)
result=call('lab.compare',identity='compare-app',targets={'a':'score.json','b':'score.json'})
incomplete=denied(lambda:lab.compare('compare-app',{'a':'score.json'}))
uncertainty=call('lab.uncertainty',identity='risks',assumptions=[{'claim':'cheap','experiment':'probe','probabilityWrong':.5,'impact':10,'cost':1},{'claim':'expensive','experiment':'probe','probabilityWrong':.9,'impact':10,'cost':100}])
measurement=root/'measurement.json';measurement.write_text('{"score":2}')
call('lab.resolve_uncertainty',identity='risks',assumption=0,instrument='score',target='measurement.json')
next_observed=call('lab.next_experiment',identity='risks')
measurement.write_text('{"score":5}')
next_stale=call('lab.next_experiment',identity='risks')
for name,body in [('baseline',{'conditions':{'model':'small','context':'a'},'outcomes':[1,2]}),('variant',{'conditions':{'model':'small','context':'b'},'outcomes':[3,4]}),('confounded',{'conditions':{'model':'big','context':'b'},'outcomes':[3,4]})]:
 (root/(name+'.json')).write_text(json.dumps(body))
matched=call('lab.causal',baseline='baseline.json',variant='variant.json',factor='context')
confounded=call('lab.causal',baseline='baseline.json',variant='confounded.json',factor='context')
Image.new('RGBA',(8,8),'red').save(root/'a.png');im=Image.open(root/'a.png');im.putpixel((7,7),(0,255,0,255));im.save(root/'b.png')
protected=call('lab.visual_guard',baseline='a.png',candidate='b.png',regions=[{'x':0,'y':0,'width':4,'height':4}])
violated=call('lab.visual_guard',baseline='a.png',candidate='b.png',regions=[{'x':0,'y':0,'width':8,'height':8}])
trace=[{'kind':'input','id':'click','atMs':0},{'kind':'response','inputId':'click','atMs':45},{'kind':'input','id':'lost','atMs':46},{'kind':'error','atMs':50,'message':'disconnected'}]
(root/'trace.json').write_text(json.dumps(trace));journey=call('lab.journey',path='trace.json')
continuity_trace=trace[:2]+[{'kind':'checkpoint','checkpointId':'save','stateHash':'a'*64,'atMs':50},{'kind':'disconnect','atMs':55},{'kind':'reconnect','atMs':60},{'kind':'resume','checkpointId':'save','stateHash':'b'*64,'atMs':65}]
(root/'continuity.json').write_text(json.dumps(continuity_trace));continuity=call('lab.journey',path='continuity.json')
for name in ['training','holdout']:(root/(name+'.txt')).write_text(name+' lesson')
examples=[{'path':'training.txt','family':'landing','split':'train'},{'path':'holdout.txt','family':'game','split':'holdout'}]
call('lab.curriculum',identity='lessons',examples=examples)
packet=call('lab.lesson_packet',identity='lessons')
leak=denied(lambda:lab.curriculum('leak',[examples[0],{**examples[0],'split':'holdout'}]))
store=ContextualLearningStore(root/'.agent_control'/'contextual_learning'/'taste.json',scope_root=root)
correction=store.record_correction('landing-page',before_path='a.png',after_path='b.png',correction='Keep text contrast')
provisional=call('lab.taste_packet',work_id='taste',context='landing-page')
store.record_preference(correction['correctionId'],preference=True,source='operator')
taste=call('lab.taste_packet',work_id='taste',context='landing-page')
(root/'b.png').write_bytes(b'changed');stale=call('lab.taste_packet',work_id='taste',context='landing-page')
slots=[ProcessAdmission(root) for _ in range(4)]
try: admission=[slots[0].acquire('agent'),slots[1].acquire('agent'),slots[2].acquire('agent'),slots[3].acquire('operator')]
finally:
 for s in slots:s.release()
slots[0].acquire('agent');slots[1].acquire('agent')
try:
 import shutil
 queued=host.launch(shutil.which('node'),['-e','setInterval(()=>{},1000)'],timeoutSeconds=10)
 for i in range(60):
  state=host.status(queued['sessionId'])
  if state.get('admissionStatus')=='waiting_for_slot':break
  time.sleep(.1)
 host.stop(queued['sessionId'],_actor='operator')
 for i in range(60):
  cancelled=host.status(queued['sessionId'])
  if cancelled['status']=='stopped':break
  time.sleep(.1)
finally:
 for s in slots:s.release()
class TransientRead:
 count=0
 def read_text(self,**kwargs):
  self.count+=1
  if self.count==1:raise PermissionError('transient replacement')
  return '{"status":"running"}'
transient=TransientRead();recovered=_load(transient)
complexity=call('lab.complexity')
gateway=NeyviaToolGateway(root,allow_mutations=True,action_scope='lab-gateway',allowed_mutation_tools={'lab.uncertainty'})
config=NeyviaAgentConfig(root=root,session_id='grant-check',native_mutation_tools=('lab.uncertainty',)).validated()
grant_args=_codex_neyvia_mcp_args(root,native_mutation_tools=config.native_mutation_tools)
request={'identity':'gateway-risk','assumptions':[{'claim':'x','experiment':'probe','probabilityWrong':.5,'impact':2,'cost':1}]}
g1=gateway.call_native('lab.uncertainty',request,action_id='save-risk')
g2=gateway.call_native('lab.uncertainty',request,action_id='save-risk')
outside_grant=gateway.call_native('lab.rehearse',{'experiment_id':comp['candidates'][0]['experimentId'],'script':'run.js'},action_id='outside-grant')
print(json.dumps({'grantArgs':grant_args,'grants':config.native_mutation_tools,'continuity':continuity,'gateway':[g1,g2],'outsideGrant':outside_grant,'nextObserved':next_observed,'nextStale':next_stale,'cancelled':cancelled,'readAttempts':transient.count,'states':[s['status'] for s in states],'result':result,'sourceUnchanged':not (source/'score.json').exists(),'incomplete':incomplete,'uncertainty':uncertainty,'matched':matched,'confounded':confounded,'protected':protected,'violated':violated,'journey':journey,'packet':packet,'leak':leak,'provisional':provisional,'taste':taste,'stale':stale,'admission':admission,'complexity':complexity,'status':call('lab.status')}))
`,root],{encoding:'utf8',timeout:90000,env:{...process.env,PYTHONPATH:path.resolve('src')}});
 assert.equal(run.status,0,run.stderr || run.stdout);
 const v=JSON.parse(run.stdout);
 assert.deepEqual(v.states,['completed','completed']);
 assert.equal(v.sourceUnchanged,true);
 assert.deepEqual(v.result.candidates.map(c=>c.eligible),[true,false]);
 assert.equal(v.incomplete,true);
 assert.equal(v.uncertainty.ranked[0].claim,'cheap');
 assert.equal(v.nextObserved.next.claim,'expensive');
 assert.equal(v.nextStale.next.claim,'cheap');
 assert.equal(v.cancelled.status,'stopped');
 assert.equal(v.cancelled.pid,undefined);
 assert.equal(v.readAttempts,2);
 assert.equal(v.gateway[0].ok,true);
 assert.equal(v.gateway[1].ok,true);
 assert.deepEqual(v.gateway[0].toolResult,v.gateway[1].toolResult);
 assert.equal(v.outsideGrant.status,'mutation_outside_contract');
 assert.deepEqual(v.grants,['lab.uncertainty']);
 assert(JSON.stringify(v.grantArgs).includes('lab.uncertainty'));
 assert(!JSON.stringify(v.grantArgs).includes('host.launch'));
 assert.deepEqual(v.matched.pairedDeltas,[2,2]);
 assert.equal(v.confounded.status,'confounded');
 assert.equal(v.matched.causalityProven,false);
 assert.equal(v.protected.protectedPixelsUnchanged,true);
 assert.equal(v.violated.protectedPixelsUnchanged,false);
 assert.deepEqual(v.journey.unansweredInputs,['lost']);
 assert.deepEqual(v.journey.responseDelaysMs,[45]);
 assert.equal(v.journey.journeySuccessful,false);
 assert.deepEqual(v.continuity.continuityMismatches,['save']);
 assert.equal(v.continuity.journeySuccessful,false);
 assert.equal(v.packet.examples.length,1);
 assert.equal(v.packet.holdoutDisclosed,false);
 assert.equal(v.leak,true);
 assert.equal(v.provisional.preferences.length,0);
 assert.equal(v.taste.preferences.length,1);
 assert.equal(v.stale.preferences.length,0);
 assert.equal(v.stale.staleComparisons.length,1);
 assert.deepEqual(v.admission,[true,true,false,true]);
 assert.equal(v.complexity.retirementPerformed,false);
 assert(v.status.records.length>0);
 console.log('PASS: real isolated candidate rehearsal and matched measurements; uncertainty ranking; confounding rejection; protected pixels; journey errors; curriculum leakage; taste approval/staleness; process slots and operator reserve; non-destructive complexity audit');
} finally {rmSync(root,{recursive:true,force:true});}
