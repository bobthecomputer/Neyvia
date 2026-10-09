import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=process.cwd(), root=mkdtempSync(path.join(tmpdir(),'neyvia-innovation-'));
try {
 const run=spawnSync(resolveNeyviaPython(repo).python,['-c',String.raw`
import asyncio,json,hashlib,sys
from pathlib import Path
from PIL import Image
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.execution_ownership import run_owned,ExecutionOwnership
from grant_agent.workspace_intelligence import WorkspaceIntelligence
from grant_agent.experimental_quality import ExperimentalQuality
root=Path(sys.argv[1]); registry=NativeToolRegistry(root)
WorkspaceIntelligence(root,'mission').configure_collaboration({'evaluation':True},expected_revision=0,operator_identity='fixture')
def call(name,args):
 result=registry.call(name,{'workId':'mission','arguments':args})
 assert result['ok'],result
 return result['result']['result']
source=root/'baseline.json'; source.write_text('{"latency":10,"contract":"one start"}')
candidate=root/'candidate.json'; candidate.write_text('{"latency":25,"contract":"one start"}')
digest=hashlib.sha256(source.read_bytes()).hexdigest()
call('intelligence.rationale',{'element_id':'start','purpose':'Keep one familiar start','protected_decisions':['one-start']})
call('intelligence.obligate',{'artifact':'baseline.json','sha256':digest,'criterion':{'type':'json_path','path':'contract','equals':'one start'}})
assert call('intelligence.check',{})[0]['status']=='verified'
handoff=call('intelligence.handoff',{'objective':'Keep familiar workflow','protected_decisions':['one-start'],'answers':{'one-start':'same composer'}})
assert call('intelligence.resume',{'handoff':handoff['handoffId'],'objective':'Keep familiar workflow','answers':{'one-start':'same composer'}})['ok']
assert not call('intelligence.resume',{'handoff':handoff['handoffId'],'objective':'Keep familiar workflow','answers':{'one-start':'new screen'}})['ok']
forged={**handoff,'objective':'fake'}
assert not registry.call('intelligence.resume',{'workId':'mission','arguments':{'handoff':forged,'objective':'fake','answers':{'one-start':'same composer'}}})['ok']
call('quality.instrument',{'i':'latency','spec':{'kind':'json_numeric','key':'latency','max':20}})
comparison=call('quality.compare',{'instrument':'latency','baseline':'baseline.json','candidate':'candidate.json'})
assert comparison['status']=='rejected' and Path(comparison['receiptPath']).is_file()
Image.new('RGB',(9,7),'white').save(root/'image.png')
call('quality.instrument',{'i':'image','spec':{'kind':'image','minWidth':10}})
image=call('quality.measure',{'instrument':'image','target':'image.png'})
assert image['dimensions']=={'width':9,'height':7} and not image['withinLimit']
call('quality.holdout',{'i':'protected','spec':{'instruments':['latency']}})
assert not call('quality.examine',{'holdout':'protected','targets':['baseline.json','candidate.json']})['passed']
proposal=call('quality.challenge',{'holdout':'protected','proposal':{'condition':'slower connection'}})
assert proposal['status']=='pending_operator_promotion'
assert not registry.call('quality.challenge',{'workId':'mission','arguments':{'holdout':'protected','proposal':{},'trusted_operator':True}})['ok']
correction=call('taste.correction',{'context':'landing-page','before_path':'baseline.json','after_path':'candidate.json','correction':'Keep shorter copy'})
assert correction['status']=='provisional'
call('taste.correction',{'context':'landing-page','before_path':'baseline.json','after_path':'candidate.json','correction':'Same pair differently worded'})
assert call('taste.history',{'context':'landing-page'})['uniquePairCount']==1
assert call('taste.history',{'context':'game'})['uncertainty']=='no_evidence'
call('attention.create',{'experiment_id':'focus','baseline_input':'task','variant_input':'task with context','acceptance':{'kind':'response_contains','text':'constraint'},'requested_route':{'runtime':'api','model':'fixture'},'budget':{'maxCalls':2}})
for variant,response in [('baseline','task'),('variant','task constraint')]:
 call('attention.observe',{'experiment_id':'focus','variant':variant,'response':response,'actual_route':{'runtime':'api','model':'fixture'}})
selection=call('attention.select',{'experiment_id':'focus','protected_constraints':['same composer']})
assert selection['recommendation']=='variant' and not selection['autoPromote'] and selection['protectedConstraints']==['same composer']
# Quality checks survive harmless byte changes; immutable handoff detects them.
source.write_text('{"latency":11,"contract":"one start"}')
assert call('intelligence.check',{})[0]['status']=='verified'
assert not call('intelligence.resume',{'handoff':handoff['handoffId'],'objective':'Keep familiar workflow','answers':{'one-start':'same composer'}})['ok']
quality=ExperimentalQuality(root,'mission'); definition=quality.base/'instrument-latency.json'
interrupted=quality.challenge('protected',{'spec':{'instruments':['latency']}})
quality._seal('holdout',interrupted['id'],{'instruments':['latency']})
try:
 quality.examine(interrupted['id'],['baseline.json'])
 raise AssertionError('incomplete promotion executed')
except PermissionError:pass
quality.review_challenge(interrupted['id'],approve=True,operator_identity='fixture-operator')
assert quality.examine(interrupted['id'],['baseline.json'])['passed']
quality.define_instrument('timing',{'kind':'trace_timing','maxMeanMs':20})
(root/'trace.json').write_text(json.dumps([{'durationMs':10}]*5000))
timing=quality.measure('timing','trace.json')
assert timing['sampleCount']==5000 and timing['meanMs']==10 and timing['omittedSamples']==4900 and len(timing['durationsMs'])==100
from grant_agent.context_engine import DurableContextEngine
wi=WorkspaceIntelligence(root,'many-obligations')
for i in range(31):wi.attach_obligation('baseline.json',hashlib.sha256(source.read_bytes()).hexdigest(),{'type':'json_path','path':'contract','equals':'one start'})
context=DurableContextEngine(root,'many-obligations',max_context_tokens=6000).build_bundle(token_budget=2000)
assert context['qualityObligations']['omittedCount']==1 and context['qualityObligations']['needsReview']
promotable=quality.challenge('protected',{'spec':{'instruments':['latency']}})
promoted=quality.review_challenge(promotable['id'],approve=True,operator_identity='fixture-operator')
assert not quality.examine(promoted['promotedHoldoutId'],['candidate.json'])['passed']
from grant_agent.contextual_learning import ContextualLearningStore
learning=ContextualLearningStore(root/'.agent_control'/'contextual_learning'/'mission.json',scope_root=root)
try:
 learning.record_preference(correction['correctionId'],preference=True,source='operator')
 raise AssertionError('changed artifact accepted as original preference')
except ValueError:pass
bad=json.loads(definition.read_text());bad['spec']['max']=999;definition.write_text(json.dumps(bad))
assert not registry.call('quality.measure',{'workId':'mission','arguments':{'instrument':'latency','target':'candidate.json'}})['ok']
# Real async ownership prevents overlapping execution and survives viewer cancellation.
events=[]
async def effect(label):
 events.append(label+'start');await asyncio.sleep(.15);events.append(label+'end');return label
async def exercise():
 await asyncio.gather(run_owned(root,'same-task',lambda:effect('a')),run_owned(root,'same-task',lambda:effect('b')))
 assert events in [['astart','aend','bstart','bend'],['bstart','bend','astart','aend']],events
 task=asyncio.create_task(run_owned(root,'detached',lambda:effect('c')))
 while 'cstart' not in events:await asyncio.sleep(.01)
 task.cancel()
 try:await task
 except asyncio.CancelledError:pass
 assert 'cend' in events
 assert ExecutionOwnership(root,'detached').snapshot()['status']=='viewer_detached_execution_finished'
asyncio.run(exercise())
print(json.dumps({'passed':True,'checks':['native-catalog','rationale','obligations','immutable-handoff','real-image-measurement','counterfactual-rejection','protected-examination','challenge-authority','contextual-deduplication','attention-comparison','execution-concurrency','viewer-disconnect']}))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:60000});
 assert.equal(run.status,0,run.stderr||run.stdout||run.error?.message);
 console.log(run.stdout.trim());
} finally {rmSync(root,{recursive:true,force:true});}
