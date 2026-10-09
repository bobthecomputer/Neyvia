import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const {root:repo,python}=resolveNeyviaPython();
const root=mkdtempSync(path.join(tmpdir(),'neyvia-work-scope-'));
try {
 const r=spawnSync(python,['-c',String.raw`
import json,sys
from pathlib import Path
from grant_agent.neyvia_agent import NeyviaToolGateway
root=Path(sys.argv[1]); a=root/'first-device'; b=root/'second-device'; a.mkdir();b.mkdir()
first=NeyviaToolGateway(a,allow_mutations=True,action_scope='shared-mission',action_root=root,allowed_mutation_tools={'work.focus','work.problem'})
saved=first.call_native('work.focus',{'text':'Finish the original acceptance gates'},action_id='focus-1')
problem=first.call_native('work.problem',{'text':'Browser journey remains unproven'},action_id='problem-1')
second=NeyviaToolGateway(b,allow_mutations=False,action_scope='shared-mission',action_root=root)
state=second.call_native('work.state',{})
wrong=second.call_native('work.state',{'workId':'other-mission'})
print(json.dumps({'saved':saved,'problem':problem,'state':state,'wrong':wrong,'canonicalExists':(root/'.agent_control/adaptive_work/shared-mission.json').is_file(),'childCopy':(a/'.agent_control/adaptive_work/shared-mission.json').exists()}))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:60000});
 assert.equal(r.status,0,r.stderr||r.error?.message);
 const o=JSON.parse(r.stdout);assert.equal(o.saved.operationStatus,'verified');assert.equal(o.problem.operationStatus,'verified');
 assert.equal(o.state.result.state.focus.text,'Finish the original acceptance gates');
 assert.equal(o.state.result.state.problems[0].text,'Browser journey remains unproven');
 assert.equal(o.wrong.status,'work_scope_mismatch');assert(o.canonicalExists);assert.equal(o.childCopy,false);
 console.log('WORK_SCOPE_CONTINUATION_VERIFIED: separate execution roots resume canonical mission state; exact scope and persisted-operation proof');
} finally {rmSync(root,{recursive:true,force:true});}
