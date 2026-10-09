import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';
const {root:repo, python} = resolveNeyviaPython();
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-creative-'));
try {
  const run = spawnSync(python, ['-c', String.raw`
import json,sys
from pathlib import Path
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.adaptive_work import AdaptiveWorkStore
from grant_agent.workspace_intelligence import WorkspaceIntelligence
root=Path(sys.argv[1]); (root/'app').mkdir(); (root/'app'/'main.txt').write_text('source v1'); (root/'app'/'.env').write_text('disposable excluded fixture')
r=NativeToolRegistry(root)
WorkspaceIntelligence(root,'journey').configure_collaboration({'evaluation':True},expected_revision=0,operator_identity='fixture')
focus=r.call('work.focus',{'workId':'journey','text':'Improve landing-page copy'})
problem=r.call('work.problem',{'workId':'journey','text':'Heading is unclear'})
store=AdaptiveWorkStore(root,'journey'); pid=store.snapshot()['problems'][0]['id']; actions=[]
for need in ['compare','generate','implement','test','retrieve','reflect','inspect']:
 store.update_problem(pid,need=need); actions.append(store.next_action()['kind'])
store.update_problem(pid,status='resolved')
restoredState=NativeToolRegistry(root).call('work.state',{'workId':'journey'})
created=r.call('experiment.create',{'experimentId':'trial','source':'app'})
restored=r.call('experiment.restore',{'experimentId':'trial','restoreId':'trial-copy'})
duplicate=r.call('experiment.restore',{'experimentId':'trial','restoreId':'trial-copy'})
escape=r.call('experiment.create',{'experimentId':'escape','source':'../'})
rootSnapshot=r.call('experiment.create',{'experimentId':'root','source':'.'})
(root/'.agent_control'/'experiments'/'trial'/'source'/'main.txt').write_text('tampered')
tamper=r.call('experiment.restore',{'experimentId':'trial','restoreId':'tampered-copy'})
long=AdaptiveWorkStore(root,'long');long.record_constraint('x'*20000); long.change_focus('z'*20000)
packet=long.packet(token_budget=300)
first=AdaptiveWorkStore(root,'a/b'); second=AdaptiveWorkStore(root,'a?b')
definition={'experimentId':'context-probe','baselineInput':'Summarize task','variantInput':'Summarize task with saved constraints','acceptance':{'kind':'response_contains','text':'constraint'},'requestedRoute':{'model':'test-route','runtime':'api'},'budget':{'maxCalls':2}}
definition['workId']='journey'
assert r.call('behavior.create',definition)['ok']
for variant,response in [('baseline','task'),('variant','task constraint')]:
 assert r.call('behavior.observe',{'workId':'journey','experimentId':'context-probe','variant':variant,'response':response,'actualRoute':{'model':'test-route','runtime':'api'}})['ok']
comparison=r.call('behavior.compare',{'experimentId':'context-probe'})
assert comparison['ok'] and comparison['result']['experiment']['criterionPassed']
assert comparison['result']['experiment']['evidenceVerified'] is False
assert not r.call('behavior.create',definition)['ok']
print(json.dumps({'focus':focus,'state':restoredState,'actions':actions,'created':created['ok'],'restored':restored['ok'],'restoredText':(root/'.agent_control'/'experiment_restores'/'trial-copy'/'main.txt').read_text(),'excluded':not (root/'.agent_control'/'experiment_restores'/'trial-copy'/'.env').exists(),'duplicate':duplicate['ok'],'escape':escape['ok'],'rootSnapshot':rootSnapshot['ok'],'tamper':tamper['ok'],'packetSize':len(json.dumps(packet,separators=(',',':'))),'distinctIds':first.work_id!=second.work_id}))
`, root], {cwd:repo, env:{...process.env,PYTHONPATH:path.join(repo,'src')}, encoding:'utf8', timeout:60000});
  assert.equal(run.status,0,run.stderr || run.error?.message);
  const out=JSON.parse(run.stdout);
  assert.equal(out.focus.ok,true); assert.equal(out.state.result.state.focus.text,'Improve landing-page copy');
  assert.equal(out.state.result.state.problems[0].status,'resolved');
  assert.deepEqual(out.actions,['compare','generate','implement','test','retrieve','reflect','inspect']);
  for(const key of ['created','restored','excluded','distinctIds','rootSnapshot']) assert.equal(out[key],true,key);
  for(const key of ['duplicate','escape','tamper']) assert.equal(out[key],false,key);
  assert.equal(out.restoredText,'source v1'); assert(out.packetSize<=1200, `packet too large: ${out.packetSize}`);
  console.log('CREATIVE_TOOLS_VERIFIED: production registry, adaptive focus, persisted problem lifecycle, isolated restore, escape/tamper refusal, bounded recovery packet');
} finally {rmSync(root,{recursive:true,force:true});}
