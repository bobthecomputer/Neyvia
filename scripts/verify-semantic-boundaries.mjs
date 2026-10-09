import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-semantic-boundaries-'));
try {
  const run = spawnSync(resolveNeyviaPython().python, ['-c', String.raw`
import json,sys
from pathlib import Path
from grant_agent.semantic_tools import SemanticToolRuntime
from grant_agent.living_applications import SupervisedAutonomy
from grant_agent.working_memory import WorkingMemoryStore
root=Path(sys.argv[1]); runtime=SemanticToolRuntime(root)
rejections=[]
for identity in ['../escape','/absolute','a/b','..']:
    try: runtime.application_register({'applicationId':identity})
    except ValueError: rejections.append(identity)
runtime.application_register({'applicationId':'fixture','source':{'revision':'local'}})
reload=SemanticToolRuntime(root).application_read({'applicationId':'fixture'})
policy=root/'.agent_control/autonomy/fixture.json';policy.parent.mkdir(parents=True,exist_ok=True)
p=SupervisedAutonomy(objective='bounded fixture',permitted_actions={'inspect'},budget=2,evidence_threshold=1)
policy.write_text(json.dumps({**p.as_dict(),'operatorAuthority':True}))
admissions=[SemanticToolRuntime(root).autonomy_admit({'policyId':'fixture','action':'inspect','cost':1,'evidenceCount':1}) for _ in range(3)]
SemanticToolRuntime(root).autonomy_revoke({'policyId':'fixture','reason':'fixture complete'})
revoked=SemanticToolRuntime(root).autonomy_admit({'policyId':'fixture','action':'inspect','cost':0,'evidenceCount':1})
missing=SemanticToolRuntime(root).autonomy_admit({'policyId':'unknown','action':'inspect','operatorAuthority':True})
m=WorkingMemoryStore(root,'bounded');m.set_objective('objective '*1000,source='user')
for i in range(30):m.record_observation('sample-'+str(i),'observation '*100,source='runtime')
projection=m.project(token_budget=220)
print(json.dumps({'rejections':rejections,'reloaded':reload,'admissions':[a['decision']['allowed'] for a in admissions],'revoked':revoked['decision'],'missing':missing['status'],'projectionChars':len(json.dumps(projection,separators=(',',':'))),'retrieval':bool(projection.get('retrieval'))}))
`, root], {encoding:'utf8', env:{...process.env, PYTHONPATH:path.join(process.cwd(),'src')}, timeout:30000});
  assert.equal(run.status, 0, run.stderr);
  const result=JSON.parse(run.stdout);
  assert.equal(result.rejections.length,4);
  assert.equal(result.reloaded.application.applicationId,'fixture');
  assert.deepEqual(result.admissions,[true,true,false]);
  assert.equal(result.revoked.allowed,false);
  assert.ok(result.revoked.reasons.includes('autonomy_revoked'));
  assert.equal(result.missing,'authority_required');
  assert.ok(result.projectionChars<=880,`Projection exceeded budget: ${result.projectionChars}`);
  assert.equal(result.retrieval,true);
  console.log('SEMANTIC_BOUNDARIES_VERIFIED: confined paths, application restart, durable budget/revocation, self-grant refusal, bounded full memory projection');
} finally {rmSync(root,{recursive:true,force:true});}
