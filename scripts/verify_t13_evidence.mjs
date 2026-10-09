// Independently inspect the preserved real-run bytes and production database.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
const repo=path.resolve(import.meta.dirname,'..');
const proof=JSON.parse(fs.readFileSync(path.join(repo,'scripts/evidence/T13.json'),'utf8'));
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
for(const row of [...proof.sources,...proof.artifacts]){
  const file=path.resolve(repo,row.path);assert.ok(file.startsWith(repo+path.sep));
  const bytes=fs.readFileSync(file);assert.equal(sha(bytes),row.sha256,row.path);
  if(row.bytes!==undefined)assert.equal(bytes.length,row.bytes,row.path);
}
const stateBytes=fs.readFileSync(path.join(repo,proof.fullState));assert.equal(sha(stateBytes),proof.fullStateSha256);
const exported=JSON.parse(stateBytes);
assert.ok(exported.state.domains.every(domain=>domain.frozen_lock.ok&&!domain.active_trial));
for(const genomes of Object.values(exported.genomes))for(const [id,genome] of Object.entries(genomes))assert.equal(sha(JSON.stringify({kind:genome.kind,text:genome.text})),id);
const snapshot=new DatabaseSync(path.join(repo,'scripts/evidence/T13-runs/evolver.sqlite3'),{readOnly:true});
for(const domain of exported.state.domains){
  const row=snapshot.prepare('SELECT incumbent,trials,evaluations,spec_hash FROM domains WHERE id=?').get(domain.id);
  assert.deepEqual({...row},{incumbent:domain.incumbent,trials:domain.trials,evaluations:domain.evaluations,spec_hash:domain.manifest_hash});
  assert.equal(snapshot.prepare('SELECT COUNT(*) AS n FROM trials WHERE domain=?').get(domain.id).n,domain.trials);
}
assert.equal(snapshot.prepare('SELECT COUNT(*) AS n FROM observations').get().n,exported.observations.length);snapshot.close();
const manual=exported.state.domains.find(domain=>domain.id==='manual_compression_v2');
const accepted=manual.receipts.find(receipt=>receipt.promoted);assert.ok(accepted&&accepted.state==='accepted');
assert.equal(accepted.stages.length,3);assert.equal(new Set(accepted.stages.map(stage=>stage.panel)).size,3);
assert.equal(accepted.stages[1].purpose,'rotating_held_out');assert.equal(accepted.stages[2].purpose,'fresh_reconfirmation');
assert.equal(accepted.stages.slice(1).reduce((sum,stage)=>sum+stage.sample_count,0),20);
for(const stage of accepted.stages){assert.ok(stage.eligible&&stage.hard_gates_passed);for(const pair of stage.pairs){
  assert.equal(pair.incumbent.receipt.seed,pair.seed);assert.equal(pair.candidate.receipt.seed,pair.seed);
  assert.equal(pair.incumbent.objectives.success,1);assert.equal(pair.candidate.objectives.success,1);
  assert.equal(pair.incumbent.objectives.tokens,1255);assert.equal(pair.candidate.objectives.tokens,936);
}}
assert.equal(manual.incumbent,accepted.candidate);
const cl=exported.state.domains.find(domain=>domain.id==='cl_skill_v3');const rejected=cl.receipts[0];
assert.equal(rejected.state,'rejected');assert.equal(rejected.promoted,false);assert.equal(cl.incumbent,rejected.incumbent);
assert.equal(rejected.stages.length,2);assert.equal(rejected.stages[1].statistics.success.noninferior,false);
for(const row of exported.observations.filter(row=>row.domain==='cl_skill_v3')){
  const result=JSON.parse(row.result);assert.deepEqual(result.receipt.model.unexpectedToolEvents,[]);
  assert.ok(result.receipt.model.command.includes('gpt-6-luna'));
  assert.ok(Object.values(result.hard_gates).every(Boolean));
}
const restart=JSON.parse(fs.readFileSync(path.join(repo,'scripts/evidence/T13-runs/restart-proof.json'),'utf8'));assert.deepEqual(restart.after,restart.before);
const http=JSON.parse(fs.readFileSync(path.join(repo,'scripts/evidence/T13-runs/http-proof-v3.json'),'utf8'));assert.ok(http.finishedAt&&!http.error);
console.log(JSON.stringify({artifactsVerified:proof.artifacts.length,sourcesVerified:proof.sources.length,domains:exported.state.domains.length,trials:proof.cumulativeTrials,manualHeldoutPairs:20,clHeldoutPairs:10,clPromotion:false,restart:true,httpChecks:http.checks.length}));
