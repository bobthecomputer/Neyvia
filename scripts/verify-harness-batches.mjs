import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const root=mkdtempSync(path.join(tmpdir(),'neyvia-batches-'));
try {
  const result=spawnSync(resolveNeyviaPython().python,['-c',String.raw`
import json,sys
from pathlib import Path
from grant_agent.harness_batches import HarnessBatchStore
from grant_agent.harness_jobs import HarnessJobStore,_atomic_write_json
from grant_agent.harness_registry import HARNESS_SPECS,runtime_picker_choices
from grant_agent.harness_job_worker import _hard_runtime_budget_seconds
from grant_agent.runtimes import runtime_adapter_map
root=Path(sys.argv[1]); b=HarnessBatchStore(root); checks={}
p={'requestId':'audit-case-1','runtime':'neyvia-agent','model':'gpt-5.6-luna','provider':'openai-codex','prompts':['alpha','beta','alpha'],'maxParallel':2,'runtimeBudgetSeconds':60}
r=b.create(p);bid=r['id'];checks['prepareHasNoJobs']=not list(b.jobs.jobs_root.glob('harness-job-*.json'))
checks['stablePreparation']=b.create(p)['id']==bid
try:b.create({**p,'prompts':['different']})
except ValueError:checks['changedIntentRefused']=True
for label,patch in [('security',{'runtime':'rook'}),('unknown',{'runtime':'imaginary'}),('unbounded',{'maxParallel':50}),('missingModel',{'model':''}),('invalidPrompts',{'prompts':['']})]:
 try:b.create({**p,**patch,'requestId':'badcase-'+label})
 except ValueError:checks[label+'Refused']=True
checks['deadlineWired']=_hard_runtime_budget_seconds(r['request'])==60
checks['exactRouteAndReadOnly']=r['request']['exactRoute'] and not r['request']['allowRuntimeFallback'] and r['request']['readOnly']
checks['distinctSessionsForDuplicatePrompts']=len({i['jobId'] for i in r['items']})==3
checks['allAdaptersDiscoverable']={i['value'] for i in runtime_picker_choices()}==set(runtime_adapter_map())
checks['hermesSeparateFromHybrid']={'hermes','openclaw','fluxio-hybrid'}<= {s.harness_id for s in HARNESS_SPECS}
# Execution is a disposable deterministic adapter; durable job, batch,
# reconciliation and admission code below is production code.
class FixtureJobs(HarnessJobStore):
 def load(self,jid,**kw):return super().load(jid,reconcile=False)
 def start(self,jid):
  job=self.load(jid); job['status']='running'; _atomic_write_json(self.job_path(jid),job);return job
b.jobs=FixtureJobs(root)
r['status']='running';_atomic_write_json(b.path(bid),r)
first=b.advance(bid);checks['parallelBound']=first['counts']=={'running':2,'pending':1}
again=b.advance(bid);checks['noDuplicateDispatch']=len(list(b.jobs.jobs_root.glob('harness-job-*.json')))==2
job0=first['items'][0]['jobId'];job1=first['items'][1]['jobId']
b.jobs.finish(job0,result={'status':'completed','reply':'alpha result'})
wave=b.advance(bid);checks['nextWaveUsesFreedSlot']=wave['counts']=={'completed':1,'running':2}
b.jobs.finish(job1,error='fixture model unavailable')
b.jobs.finish(wave['items'][2]['jobId'],result={'status':'completed','reply':'third result'})
done=b.advance(bid);checks['failureRetainedWithoutRetry']=done['status']=='failed' and len(list(b.jobs.jobs_root.glob('harness-job-*.json')))==3
checks['resultsAndReceiptsRetained']=all(i.get('receiptPath') for i in done['items']) and done['items'][0]['result']['reply']=='alpha result'
checks['finishedStartDoesNotRepeat']=b.start(bid)['status']=='failed'
# Lost create response reconciles a queued deterministic child rather than recreating it.
s=b.create({**p,'requestId':'crash-case','prompts':['one']});s['status']='running';item=s['items'][0];item['status']='reserved'
req={**s['request'],'message':item['prompt'],'objective':item['prompt'],'batchId':s['id'],'sessionId':item['jobId']}
b.jobs.create(req,job_id=item['jobId']);_atomic_write_json(b.path(s['id']),s)
recovered=b.advance(s['id']);checks['lostCreateResponseReconciles']=recovered['counts']=={'running':1}
before=b.jobs.load(item['jobId']);checks['reservedIdentityReused']=b.jobs.create(req,job_id=item['jobId'])['id']==before['id']
try:b.jobs.create({**req,'message':'different'},job_id=item['jobId'])
except ValueError:checks['jobIdentityConflictRefused']=True
# A missing reserved child is uncertain, never blindly repeated.
u=b.create({**p,'requestId':'missing-case','prompts':['one']});u['status']='running';u['items'][0]['status']='reserved';_atomic_write_json(b.path(u['id']),u)
uncertain=b.advance(u['id']);checks['missingReceiptIsUncertain']=uncertain['status']=='blocked' and uncertain['counts']=={'uncertain':1}
# Cancellation before launch uses a real supervisor process and no model calls.
import os
# A parent started with -B has no environment flag for its children to inherit.
# Use a fresh cache prefix so an accidental child write is observable without
# touching the source tree (including a sealed NAS candidate).
sys.dont_write_bytecode=True
os.environ.pop('PYTHONDONTWRITEBYTECODE',None)
cache=root/'forbidden-worker-cache';os.environ['PYTHONPYCACHEPREFIX']=str(cache)
c=b.create({**p,'requestId':'cancel-case','prompts':['one','two']});b.cancel(c['id'])
import time
for _ in range(100):
 cancelled=b.load(c['id'])
 if cancelled['status']=='cancelled':break
 time.sleep(.05)
checks['realSupervisorCancelBeforeLaunch']=cancelled['status']=='cancelled' and cancelled['counts']=={'cancelled':2}
checks['supervisorPreservesNoBytecodeWrites']=not list(cache.rglob('*.pyc'))
checks['historySummariesAreCompact']=all('items' not in row for row in b.list())
print(json.dumps(checks))
`,root],{env:{...process.env,PYTHONPATH:path.resolve('src')},encoding:'utf8',timeout:30000});
  assert.equal(result.status,0,result.stderr||result.stdout);
  const checks=JSON.parse(result.stdout);for(const [key,value] of Object.entries(checks))assert.equal(value,true,key);
  assert.ok(Object.keys(checks).length>=23,'Expected every failure check to execute');
  console.log(JSON.stringify({status:'verified',checks,boundary:'Production durable stores and a real cancellation supervisor; deterministic disposable execution fixture, no paid model or Hermes dataset export claim.'},null,2));
}finally{rmSync(root,{recursive:true,force:true});}
