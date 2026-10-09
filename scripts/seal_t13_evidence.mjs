// Export only this task's model outputs and production state; never credentials.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';

const repo=path.resolve(import.meta.dirname,'..');
const root=path.join(repo,'.agent_control/t13/runtime');
const target=path.join(repo,'scripts/evidence/T13-runs');
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const relative=value=>path.relative(repo,value).replaceAll('\\','/');
fs.mkdirSync(target,{recursive:true});
const python='C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const exported=spawnSync(python,['-c',String.raw`
import json,sys,sqlite3
from pathlib import Path
from grant_agent.evolver_core import EvolverEngine
engine=EvolverEngine(Path(sys.argv[1])/'.neyvia/evolver.sqlite3')
state=engine.status()
if any(domain['active_trial'] for domain in state['domains']):
    raise RuntimeError('Cannot preserve an active trial')
genomes={domain['id']:{row['genome']:engine._genome(domain['id'],row['genome']) for row in domain['lineage']} for domain in state['domains']}
with engine._db() as db:
    observations=[dict(row) for row in db.execute('SELECT * FROM observations')]
    manifests=[dict(row) for row in db.execute('SELECT id,spec,spec_hash FROM domains')]
for source,name in [(engine.store_path,'evolver.sqlite3'),(Path(sys.argv[1])/'.neyvia/evolver-jobs/jobs.sqlite3','jobs.sqlite3')]:
    source_db=sqlite3.connect(source)
    destination_db=sqlite3.connect(Path(sys.argv[2])/name)
    try:
        source_db.backup(destination_db)
    finally:
        source_db.close();destination_db.close()
print(json.dumps({'state':state,'genomes':genomes,'observations':observations,'manifests':manifests},ensure_ascii=False))
`,root,target],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src'),PYTHONIOENCODING:'utf-8'},encoding:'utf8',maxBuffer:64*1024*1024,windowsHide:true});
assert.equal(exported.status,0,exported.stderr);
const state=JSON.parse(exported.stdout);
assert.ok(state.state.domains.length>=4,'All preserved and corrected domains must be exported');
assert.ok(state.state.domains.every(domain=>domain.frozen_lock.ok),'Cannot seal a broken judge lock');
assert.ok(state.state.domains.every(domain=>!domain.active_trial),'Cannot seal an active trial');
fs.writeFileSync(path.join(target,'state.json'),JSON.stringify(state,null,2));
const artifacts=[];
for(const name of ['evolver.sqlite3','jobs.sqlite3']){const bytes=fs.readFileSync(path.join(target,name));artifacts.push({path:relative(path.join(target,name)),sha256:sha(bytes),bytes:bytes.length,sourceBoundary:'SQLite online backup of owned task state; contains no authentication database'});}
function copy(source,destination){const bytes=fs.readFileSync(source);fs.mkdirSync(path.dirname(destination),{recursive:true});fs.writeFileSync(destination,bytes);assert.equal(sha(fs.readFileSync(destination)),sha(bytes));artifacts.push({source:relative(source),path:relative(destination),sha256:sha(bytes),bytes:bytes.length});}
for(const entry of fs.readdirSync(path.join(root,'.neyvia/evolver-model-runs'),{withFileTypes:true})){
  if(entry.isFile()&&/\.(stdout\.jsonl|stderr\.txt|prompt\.txt|receipt\.json|schema\.json|failure\.json)$/.test(entry.name))copy(path.join(root,'.neyvia/evolver-model-runs',entry.name),path.join(target,'model',entry.name));
}
for(const name of ['http-proof-v1-failed.json','http-proof-v2-failed.json','http-proof-cl-v2-failed.json','http-proof-v2.json','http-proof-v3-buffer-failed.json','http-proof-v3.json','restart-proof.json']){
  const source=path.join(repo,'.agent_control/t13',name);if(fs.existsSync(source))copy(source,path.join(target,name));
}
for(const entry of fs.readdirSync(path.join(root,'.neyvia/evolver-jobs'),{withFileTypes:true})){
  if(entry.isFile()&&/^[a-f0-9]{64}\.(log|result\.json)$/.test(entry.name))copy(path.join(root,'.neyvia/evolver-jobs',entry.name),path.join(target,'jobs',entry.name));
}
const average=values=>values.length?values.reduce((a,b)=>a+b,0)/values.length:null;
const domains=state.state.domains.map(domain=>({id:domain.id,incumbent:domain.incumbent,trials:domain.trials,evaluations:domain.evaluations,manifestHash:domain.manifest_hash,frozenLock:domain.frozen_lock,
  results:domain.receipts.map(receipt=>({id:receipt.id,candidate:receipt.candidate,parent:receipt.incumbent,state:receipt.state,promoted:receipt.promoted,error:receipt.error,
    panels:receipt.stages.map(stage=>({id:stage.panel,hash:stage.panel_hash,purpose:stage.purpose??stage.role,samples:stage.sample_count,eligible:stage.eligible,hardGates:stage.hard_gates_passed,statistics:stage.statistics,
      baselineAllPass:stage.pairs.filter(pair=>pair.incumbent.objectives.success===1).length,candidateAllPass:stage.pairs.filter(pair=>pair.candidate.objectives.success===1).length,
      baselineAdherence:average(stage.pairs.map(pair=>pair.incumbent.receipt.judge?.adherence?.adherence).filter(value=>typeof value==='number')),
      candidateAdherence:average(stage.pairs.map(pair=>pair.candidate.receipt.judge?.adherence?.adherence).filter(value=>typeof value==='number')),
      baselineQuality:average(stage.pairs.map(pair=>pair.incumbent.receipt.judge?.quality).filter(value=>typeof value==='number')),
      candidateQuality:average(stage.pairs.map(pair=>pair.candidate.receipt.judge?.quality).filter(value=>typeof value==='number'))}))}))}));
const modelReceipts=artifacts.filter(row=>row.path.endsWith('.receipt.json')).map(row=>JSON.parse(fs.readFileSync(path.join(repo,row.path),'utf8')));
const usage=modelReceipts.reduce((total,row)=>{for(const key of ['input_tokens','cached_input_tokens','output_tokens'])total[key]+=row.usage?.[key]??0;return total;},{input_tokens:0,cached_input_tokens:0,output_tokens:0});
const sourceFiles=['src/grant_agent/evolver_core.py','src/grant_agent/evolver_domains.py','src/grant_agent/evolver_domains_v2.py','src/grant_agent/evolver_domains_v3.py','src/grant_agent/neyvia_evolver.py','src/grant_agent/neyvia_lab_board.py','src/grant_agent/neyvia_workspace_tools.py','src/grant_agent/neyvia_ui_api.py','src/grant_agent/web_backend.py','src/grant_agent/desktop_bridge.py','scripts/run_t13_evolution.py','manuals/hill-climb.manual.json','rust/evolver-core/src/main.rs','rust/evolver-core/Cargo.toml','rust/evolver-core/Cargo.lock'];
sourceFiles.push('src/grant_agent/evolver_transport_v3.py',...fs.readdirSync(path.join(repo,'config/evolver')).map(name=>'config/evolver/'+name));
const revision=spawnSync('git',['rev-parse','HEAD'],{cwd:repo,encoding:'utf8',windowsHide:true});assert.equal(revision.status,0);
const proof={schema:'neyvia.T13.evolver-proof.v1',sealedAt:new Date().toISOString(),root,branch:'track/t13-evolver',sourceCommit:revision.stdout.trim(),model:'gpt-6-luna',domains,
  acceptance:{definingBackendMechanism:true,manualCompressionPromoted:true,clSkillPromoted:false,clFreshReconfirmation:false,renderedHillClimbUI:false,fullPlan01:false},
  cumulativeTrials:{manualCompression:domains.filter(domain=>domain.id.startsWith('manual_compression')).reduce((total,domain)=>total+domain.trials,0),clSkill:domains.filter(domain=>domain.id.startsWith('cl_skill')).reduce((total,domain)=>total+domain.trials,0)},
  modelCalls:modelReceipts.length,usage,artifacts,fullState:'scripts/evidence/T13-runs/state.json',fullStateSha256:sha(fs.readFileSync(path.join(target,'state.json'))),sources:sourceFiles.map(file=>({path:file,sha256:sha(fs.readFileSync(path.join(repo,file)))})),
  definingMechanism:{typedGenome:'Rust L0 validation + newline rendering equivalence, global SQLite CAS',frozenJudges:'Source/binary/panel/promotion manifest hash checked before and after every evaluation',paired:'Independent provider calls, same frozen item and task seed, randomized pair order',promotion:'Paired noise intervals + trial/objective/stage-corrected sign test; discovery + rotating held-out + distinct fresh reconfirmation',lineage:'Persisted parent/operator/proposal usage and actual per-case executable outcomes',authority:'Workspace incumbent only; original installed manuals/skills and public release unchanged'},
  registrations:{tools:['state','lineage','receipt','genome','run','job'].map(op=>({native:'neyvia.evolver.'+op,command:'evolver_'+op+'_command'})),surfaces:['WorkspaceTools/NativeToolRegistry','MCP PORTED','owner HTTP /api/ui/evolver','FluxioWebBackend dispatch /api/backend','desktop bridge allow-list and selected-root forwarding','existing generic Tauri call_desktop_backend_command'],manual:'manuals/hill-climb.manual.json chapter evolver'},
  limitations:['No available Chrome/IAB surface; Claude-owned Hill climbing UI and rendered lineage journey remain missing.','Provider sampling cannot be seeded by the CLI; seeds fix paired task data and order only.','Fitness denominator is o200k_base reference instruction tokens; real CLI usage above includes substantial harness overhead.','CL domain measures 15 original source checks, judgement journal, compilation/SSR/callback outcome; no visual aesthetic quality claim.','Text/newline equivalence is not unrestricted egg equality saturation. Calibrated L2 filters, generic nogoods/bandit/motifs/meta-evolution, idle daemon and L5 field programme remain unimplemented.','Failed and rejected trials remain counted and archived; adapter/transport repairs use separately frozen v2 panels.','Stage/trial/objective correction is verified for the frozen two-trial domains; broader default budgets have not been statistically validated.','Restart proof covers completed jobs and exact observation state; automatic crash recovery remains unavailable.']};
const output=path.join(repo,'scripts/evidence/T13.json');fs.writeFileSync(output,JSON.stringify(proof,null,2));
console.log(JSON.stringify({proof:relative(output),domains:domains.map(domain=>({id:domain.id,results:domain.results.map(result=>({state:result.state,promoted:result.promoted,panels:result.panels.map(panel=>({id:panel.id,purpose:panel.purpose,allPass:[panel.baselineAllPass,panel.candidateAllPass],tokens:[panel.statistics.tokens.incumbent_mean,panel.statistics.tokens.candidate_mean],fitness:[panel.statistics.fitness.incumbent_mean,panel.statistics.fitness.candidate_mean]}))}))})),modelCalls:proof.modelCalls,usage,artifactBytes:artifacts.reduce((total,row)=>total+row.bytes,0)}));
