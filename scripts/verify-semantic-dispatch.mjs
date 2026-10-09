import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=process.cwd(), root=mkdtempSync(path.join(tmpdir(),'neyvia-dispatch-'));
try {
 const r=spawnSync(resolveNeyviaPython(repo).python,['-c',String.raw`
from pathlib import Path
import json,sys
from grant_agent.neyvia_stage_scheduler import build_progressive_step_handler
root=Path(sys.argv[1]); policy=root/'policy.json'
policy.write_text(json.dumps({'objective':'bounded fixture','permittedActions':['fixture.write'],'evidenceThreshold':0,'budget':1,'operatorAuthority':True}))
class Surface:
 def describe(self,name): return {'annotations':{'readOnlyHint':False}}
 def call(self,name,args):
  p=root/'effect.txt'; p.write_text(p.read_text()+'x' if p.exists() else 'x'); return {'ok':True}
handler=build_progressive_step_handler(root,progressive=Surface(),approved_mutations=True,autonomy_policy_path=policy)
ctx={'planHash':'plan','mission_id':'mission'}
step={'action':'tool','tool':'fixture.write','step_id':'one'}
first=handler(step,ctx); repeat=handler(step,ctx); exhausted=handler({**step,'step_id':'two'},ctx)
data=json.loads(policy.read_text()); data['budget']=5;data['revoked']=True;policy.write_text(json.dumps(data))
revoked=handler({**step,'step_id':'three'},ctx)
class Broken(Surface):
 def call(self,name,args): raise RuntimeError('transport lost')
failed=build_progressive_step_handler(root,progressive=Broken(),approved_mutations=True)({**step,'step_id':'failure'},ctx)
print(json.dumps({'first':first,'repeat':repeat,'exhausted':exhausted,'revoked':revoked,'failed':failed,'bytes':(root/'effect.txt').read_text()}))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8'});
 assert.equal(r.status,0,r.stderr); const out=JSON.parse(r.stdout);
 assert.equal(out.first.ok,true); assert.equal(out.first.metadata.operationStatus,'unverified');
 assert.equal(out.repeat.metadata.duplicateSuppressed,true); assert.equal(out.bytes,'x');
 assert.equal(out.exhausted.ok,false); assert.equal(out.revoked.ok,false);
 assert.equal(out.failed.ok,false); assert.ok(out.failed.metadata.recoveryRef);
 console.log('SEMANTIC_DISPATCH_VERIFIED: scheduler production dispatch, replay suppression, durable budget/revocation, honest verification, recovery');
} finally {rmSync(root,{recursive:true,force:true});}
