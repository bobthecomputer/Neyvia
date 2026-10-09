// Observe the same real completed jobs on either side of an owned backend restart.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const repo=path.resolve(import.meta.dirname,'..');
const destination=path.join(repo,'.agent_control/t13/restart-proof.json');
const base='http://127.0.0.1:48421';
const login=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
assert.ok(login.ok);
const cookie=login.headers.getSetCookie().map(row=>row.split(';')[0]).join(';');
async function request(route,body){
  const response=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{cookie,'content-type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data=await response.json();assert.ok(response.ok,JSON.stringify(data));assert.notEqual(data.ok,false);return data.data??data;
}
const state=await request('/api/ui/evolver');
const snapshot={domains:state.domains.map(row=>({id:row.id,incumbent:row.incumbent,trials:row.trials,evaluations:row.evaluations,manifest:row.manifest_hash,lineage:row.lineage,receipts:row.receipts,front:row.pareto_front})),jobs:[]};
for(const row of state.domains){assert.ok(row.frozen_lock.ok);assert.equal(row.active_trial,null);}
for(const [domain,requestId] of [['manual_compression_v2','t13-live-manual_compression_v2-v1-retry'],['cl_skill_v3','t13-live-cl_skill_v3-trial1']]){
  const result=await request('/api/backend',{command:'evolver_run_command',payload:{domain,requestId,maxTrials:1}});
  assert.equal(result.replayed,true);assert.equal(result.job.state,'completed');snapshot.jobs.push(result.job);
}
if(process.argv.includes('--capture')){
  fs.writeFileSync(destination,JSON.stringify({schema:'neyvia.T13.restart-proof.v1',capturedAt:new Date().toISOString(),base,before:snapshot},null,2));
  console.log('Captured real persisted state before owned backend restart');
}else{
  const proof=JSON.parse(fs.readFileSync(destination,'utf8'));assert.deepEqual(snapshot,proof.before);
  proof.after=snapshot;proof.verifiedAt=new Date().toISOString();proof.checks=['Incumbents, counts, manifests, lineage, receipts and Pareto fronts unchanged','Same completed job IDs and PIDs replayed without duplicate execution','All frozen source locks remain healthy'];
  fs.writeFileSync(destination,JSON.stringify(proof,null,2));console.log('Real backend restart preserved exact state and idempotent completed jobs');
}
