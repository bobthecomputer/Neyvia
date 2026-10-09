"""Real checked capability model calls on generated, supplied snapshots.

The fixtures prove the frontend model boundary: exact lineage, digest and
receipt identities, inactive candidates, explicit review admission, documented
bounds and preserved caller objects. They do not claim browser rendering,
cryptographic authentication of synthetic receipts or backend activation.
"""
from __future__ import annotations
from .subprocess_utils import hidden_windows_subprocess_kwargs

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

NAMES = {
    "selectCapabilityRecommendation", "capabilityActionLabel", "selectCapabilityRecovery",
    "buildCapabilityRecoveryPayload", "buildCapabilityTrialPayload", "isCapabilityRunBundle",
    "buildCapabilityRunImportPayload", "synthesisCanEnterLearning", "eligibleReceiptCandidates",
    "receiptOptionLabel", "buildReceiptComparisonPayload", "buildCapabilityAppPrompt",
    "counterfactualReplayCandidates", "counterfactualCaseLabel", "buildCounterfactualForgePayload",
    "counterfactualForgeCanApprove", "skillCandidateRequiresSeal", "skillCandidateCanCompare",
    "buildSkillCandidateMarkdown", "buildSkillCandidateSealPayload", "skillCandidateIsSealed",
    "selectSkillMaterializationReview", "buildSkillMaterializationPayload",
    "buildSkillMaterializationRollbackPayload", "proofLeaseDependencyPaths",
    "buildProofLeaseEstablishPayload", "proofLeaseReceiptCandidates", "buildProofLeaseRenewalPayload",
    "buildProofLeaseDispositionPayload", "capabilityCommands",
}
IDS = {"capability." + name for name in NAMES}
TEXT_CATEGORIES = {"empty", "huge", "unicode"}
REVIEW_GATES = {
    "buildCapabilityRunImportPayload", "buildSkillCandidateSealPayload", "buildReceiptComparisonPayload",
    "buildCounterfactualForgePayload", "counterfactualForgeCanApprove", "buildSkillMaterializationPayload",
    "buildSkillMaterializationRollbackPayload", "buildProofLeaseEstablishPayload", "buildProofLeaseRenewalPayload",
    "buildProofLeaseDispositionPayload",
}
STALE_GATES = {
    "selectCapabilityRecommendation", "selectCapabilityRecovery", "buildCapabilityRecoveryPayload",
    "isCapabilityRunBundle", "buildCapabilityRunImportPayload", "skillCandidateRequiresSeal",
    "skillCandidateIsSealed", "skillCandidateCanCompare", "buildSkillCandidateSealPayload",
    "synthesisCanEnterLearning", "eligibleReceiptCandidates", "proofLeaseReceiptCandidates",
    "buildReceiptComparisonPayload", "counterfactualReplayCandidates", "buildCounterfactualForgePayload",
    "counterfactualForgeCanApprove", "selectSkillMaterializationReview", "buildSkillMaterializationPayload",
    "buildSkillMaterializationRollbackPayload", "buildProofLeaseEstablishPayload", "buildProofLeaseRenewalPayload",
    "buildProofLeaseDispositionPayload",
}
SOURCES = ["src/grant_agent/edge_fixture_capability_models.py",
           "web/src/neyvia/neyviaCapabilityEvolutionModel.js", "web/src/neyvia/neyviaCapabilityContracts.js",
           "web/src/neyvia/neyviaFrontendContracts.js", "web/src/neyvia/neyviaChatContracts.js"]

NODE = r'''
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [repo, category] = process.argv.slice(2);
const m = await import(pathToFileURL(path.join(repo,'web/src/neyvia/neyviaCapabilityEvolutionModel.js')));
const {checkCapabilityAction} = await import(pathToFileURL(path.join(repo,'web/src/neyvia/neyviaCapabilityContracts.js')));
const text = category === 'empty' ? '' : category === 'huge' ? 'generated capability evidence '.repeat(2048) : '雪🙂 café é العربية \u0000 "quoted" \\';
// Large leaf strings and declared 100/101, 6/7 and 12/13 bounds are generated
// separately, avoiding a wasteful multi-gigabyte Cartesian-product fixture.
const size = category === 'huge' ? 128 : 4;
const digest = createHash('sha256').update('owned-skill-package/'+text).digest('hex');
const otherDigest = createHash('sha256').update('different owned package/'+text).digest('hex');
const cid = 'capability-'+text, trialId='trial-'+text, lineageId='lineage-'+text, runPrefix='run-'+text;
const json = value=>JSON.stringify(value);
const hash = value=>createHash('sha256').update(json(value) ?? 'undefined').digest('hex');
const copy = value=>structuredClone(value);
let calls=0, refusals=0, outputs=[];
function call(name,...args) {
  const before=json(args);
  const result=m[name](...args);
  assert.equal(json(args),before,`${name} changed its supplied snapshot or options`);
  calls++; outputs.push(hash(result));
  return result;
}
function equal(name,args,expected) { const result=call(name,...args); assert.deepEqual(result,expected); return result; }
function reject(name,args) { equal(name,args,null); refusals++; }
const rows=[];
function record(name,action) {
  calls=0;refusals=0;outputs=[];
  try {
    action();
    rows.push({contract:'capability.'+name,status:'passed',detail:{checkedModelCalls:calls,explicitRefusals:refusals,
      inputCharacters:text.length,generatedRows:size,outputSetSha256:hash(outputs)}});
  } catch(error) {
    rows.push({contract:'capability.'+name,status:'failed',error:String(error.stack||error).slice(0,1800),
      detail:{checkedModelCalls:calls,explicitRefusals:refusals,inputCharacters:text.length}});
  }
}

// A real catalog call anchors this pipeline's command identities, but its zero
// argument API has no text/size boundary and receives no semantic pair binding.
const commands = call('capabilityCommands');
assert.equal(Object.isFrozen(commands),true);
assert.deepEqual(commands,{
  snapshot:'get_capability_evolution_command',createTrial:'create_capability_evolution_trial_command',
  sealCandidate:'seal_capability_skill_candidate_command',recordEvidence:'record_capability_evolution_evidence_command',
  buildForge:'build_capability_counterfactual_forge_command',decideTrial:'decide_capability_evolution_trial_command',
  materializeSkill:'materialize_capability_skill_command',establishProofLease:'establish_capability_proof_lease_command',
  renewProofLease:'renew_capability_proof_lease_command',recordProofLeaseDisposition:'record_capability_proof_lease_disposition_command',
  rollbackSkill:'rollback_capability_skill_materialization_command',acceptOutcome:'accept_constellation_outcome_command',
  importAppOutcomes:'import_capability_run_bundle_command'});

const candidate = {schema:'neyvia.sealed_skill_candidate.v1',state:'sealed',packageDigest:digest,
  targetSkillId:'owned-skill',displayName:'Owned skill '+text,skillMarkdown:'# Owned skill\n'+text,
  openaiYaml:'interface:\n  display_name: Owned skill\n',activated:false};
const trial = {trialId,capabilityId:cid,lineageId,capabilityKind:'skill',action:'repair',label:'Owned skill '+text,
  state:'evidence_ready',candidate,successContract:{requiredComparableRuns:2},evidence:[]};
const materialization = {materializationId:'materialization-'+text,candidateDigest:digest,state:'materialized_inactive'};
const review = {trialId,candidateDigest:digest,state:'review_required',canMaterialize:true,
  materialization,proofLease:{state:'unestablished',canEstablish:true,canRenew:true}};
const recommendation = {capabilityId:cid,lineageId,capabilityKind:'skill',label:'Owned skill '+text,
  origin:'owned-fixture',action:'repair',title:'Repair '+text,reason:text,mutationBrief:text,
  evidenceSummary:{feedbackCount:3,proofArtifacts:['artifact-'+text]},successContract:{requiredComparableRuns:2}};
const recovery = {schema:'neyvia.capability_recovery_mission.v1',recoveryId:'recovery-'+text,title:'Recover '+text,
  state:'review_required',humanApprovalRequired:true,candidateActivated:false,published:false,
  prompt:'Review bounded prior work '+text,recommendedLaneId:'owned-'+text,
  recommendedRoute:{runtime:'owned-runtime',provider:'owned-provider',model:text,effort:'high',availability:{state:'ready'}}};
function comparison(index) {
  return {runId:runPrefix+'-'+index,transcriptsIncluded:false,candidatePackageDigest:digest,
    receiptPair:{schema:'neyvia.receipt_comparison.v1',sameContractConfirmed:true,transcriptsIncluded:false,
      candidatePackageDigest:digest,baseline:{turnId:'baseline-'+index,authorityRecorded:true,authority:{recorded:true}},
      candidate:{turnId:'candidate-'+index,authorityRecorded:true,authority:{recorded:true}}},deltas:{outcomeLift:0.25}};
}
const evidence=Array.from({length:category==='huge'?20:4},(_,index)=>comparison(index));
const measured = index=>({schema:'neyvia.receipt_measurement.v1',eligible:true,turnId:'turn-'+text+'-'+index,
  verificationStatus:'passed',authorityRecorded:true,runtime:'owned',model:text,proofArtifactCount:1});

record('capabilityActionLabel',()=>{
  equal('capabilityActionLabel',[text],'Review');
  for(const [value,label] of Object.entries({prove:'Prove',branch:'Branch',repair:'Repair',merge:'Merge',quarantine:'Quarantine',retire:'Retire',promote_to_app:'Make app'}))equal('capabilityActionLabel',[value],label);
});
record('selectCapabilityRecommendation',()=>{
  if(category==='empty')equal('selectCapabilityRecommendation',[{recommendations:[],appOutcomeLearning:{proposals:[]}}],null);
  const proposals=Array.from({length:size},(_,i)=>({...recommendation,title:text+'-'+i,priority:8,status:'proposed',action:'prove'}));
  const priorityWinner={...recommendation,status:'trial_active',priority:2,action:'merge',evidenceSummary:{usageCount:1}};
  const actionWinner={...recommendation,status:'trial_active',priority:2,action:'repair',evidenceSummary:{usageCount:2}};
  const usageWinner={...actionWinner,title:'usage-winner'+text,evidenceSummary:{frictionCount:8}};
  const activeLoser={...recommendation,status:'trial_active',priority:3,action:'repair'};
  equal('selectCapabilityRecommendation',[{recommendations:[...proposals,priorityWinner,actionWinner,activeLoser],appOutcomeLearning:{proposals:[usageWinner]}}],usageWinner);
});
record('selectCapabilityRecovery',()=>{
  if(category==='empty')equal('selectCapabilityRecovery',[{}],null);
  const valid={...recovery,priority:1,evidenceCount:9};
  const lower={...recovery,recoveryId:'less-'+text,priority:1,evidenceCount:2};
  const malformed=Array.from({length:size},(_,index)=>({...recovery,recoveryId:'bad-'+index,priority:0,candidateActivated:true}));
  equal('selectCapabilityRecovery',[{capabilityTreasury:{recoveries:[...malformed,lower,valid,{...recovery,humanApprovalRequired:false,priority:0}]}}],valid);
  for(const change of [{state:'completed'},{published:true},{candidateActivated:true},{humanApprovalRequired:false},{prompt:''},{schema:'different'}])
    equal('selectCapabilityRecovery',[{capabilityTreasury:{recoveries:[{...recovery,...change}]}}],null);
});
record('buildCapabilityRecoveryPayload',()=>{
  if(category==='empty')reject('buildCapabilityRecoveryPayload',[{}]);
  equal('buildCapabilityRecoveryPayload',[recovery],{recoveryId:recovery.recoveryId,title:recovery.title,prompt:recovery.prompt,
    recommendedLaneId:recovery.recommendedLaneId,route:{runtime:'owned-runtime',provider:'owned-provider',model:text,effort:'high',availability:'ready'}});
  for(const change of [{published:true},{candidateActivated:true},{humanApprovalRequired:false},{recoveryId:''},{prompt:''},{state:'completed'}])reject('buildCapabilityRecoveryPayload',[{...recovery,...change}]);
});
record('buildCapabilityTrialPayload',()=>{
  if(category==='empty')reject('buildCapabilityTrialPayload',[{}]);
  const payload=equal('buildCapabilityTrialPayload',[recommendation,{conversationId:'conversation-'+text,missionId:'mission-'+text}],{
    lineageId,capabilityId:cid,capabilityKind:'skill',label:recommendation.label,origin:'owned-fixture',action:'repair',
    title:recommendation.title,reason:text,context:{conversationId:'conversation-'+text,missionId:'mission-'+text,
      intent:'bounded_baseline_candidate_comparison',discoverySource:'owned-fixture',mutationBrief:text},
    baseline:{source:'current_lineage',feedbackCount:3,proofArtifacts:['artifact-'+text]},
    candidate:{status:'mutation_brief',intent:text||recommendation.title,activated:false},successContract:{requiredComparableRuns:2},createdBy:'operator'});
  assert.equal(payload.candidate.activated,false);
  assert.throws(()=>checkCapabilityAction('buildCapabilityTrialPayload',[recommendation,{conversationId:'conversation-'+text,missionId:'mission-'+text}],
    {...payload,candidate:{...payload.candidate,activated:true}}),error=>error.contract==='capability.buildCapabilityTrialPayload');
});
function bundle(count=2) {
  return {schema:'neyvia.capability-run-bundle/v2',appFactoryJobId:'job-'+text,appId:'app-'+text,
    candidateActivated:false,transcriptsIncluded:false,runs:Array.from({length:count},(_,i)=>({schema:'neyvia.capability-run/v2',status:'sealed',
      receiptDigest:createHash('sha256').update('receipt-'+i+text).digest('hex'),candidateActivated:false,transcriptsIncluded:false}))};
}
record('isCapabilityRunBundle',()=>{
  if(category==='empty')equal('isCapabilityRunBundle',[bundle(0)],false);
  equal('isCapabilityRunBundle',[bundle(category==='huge'?100:2)],true);
  equal('isCapabilityRunBundle',[bundle(101)],false);
  const valid=bundle();
  for(const change of [{candidateActivated:true},{transcriptsIncluded:true},{appFactoryJobId:''},{appId:''},{schema:'unknown'}])equal('isCapabilityRunBundle',[{...valid,...change}],false);
  for(const change of [{receiptDigest:text},{status:'pending'},{candidateActivated:true},{transcriptsIncluded:true}])equal('isCapabilityRunBundle',[{...valid,runs:[{...valid.runs[0],...change}]}],false);
});
record('buildCapabilityRunImportPayload',()=>{
  const valid=bundle(category==='huge'?100:2);
  if(category==='empty')reject('buildCapabilityRunImportPayload',[bundle(0),{reviewConfirmed:true}]);
  equal('buildCapabilityRunImportPayload',[valid,{reviewConfirmed:true,importedBy:'person-'+text}],{bundle:valid,reviewConfirmed:true,importedBy:'person-'+text});
  for(const value of [false,undefined,'true',1])reject('buildCapabilityRunImportPayload',[valid,{reviewConfirmed:value}]);
  reject('buildCapabilityRunImportPayload',[{...valid,candidateActivated:true},{reviewConfirmed:true}]);
  reject('buildCapabilityRunImportPayload',[bundle(101),{reviewConfirmed:true}]);
});
record('skillCandidateRequiresSeal',()=>{
  equal('skillCandidateRequiresSeal',[{capabilityKind:text,action:'repair'}],false);
  for(const action of ['branch','repair','merge'])equal('skillCandidateRequiresSeal',[{capabilityKind:'skill',action}],true);
  for(const action of ['',text,'prove','promote_to_app'])equal('skillCandidateRequiresSeal',[{capabilityKind:'skill',action}],false);
});
record('skillCandidateIsSealed',()=>{
  if(category==='empty')equal('skillCandidateIsSealed',[{}],false);
  equal('skillCandidateIsSealed',[trial],true);
  for(const change of [{activated:true},{state:'draft'},{schema:text},{packageDigest:''},{skillMarkdown:''},{openaiYaml:''}])equal('skillCandidateIsSealed',[{...trial,candidate:{...candidate,...change}}],false);
});
record('skillCandidateCanCompare',()=>{
  equal('skillCandidateCanCompare',[{...trial,candidate:{...candidate,skillMarkdown:category==='empty'?'':'# '+text}}],category!=='empty');
  equal('skillCandidateCanCompare',[trial],true);
  for(const change of [{activated:true},{packageDigest:''},{state:'unsealed'}])equal('skillCandidateCanCompare',[{...trial,candidate:{...candidate,...change}}],false);
  equal('skillCandidateCanCompare',[{...trial,action:'prove',candidate:{}}],true);
});
const description='Reviewed bounded workflow'+(text?' '+text:'');
const instructions='Observe the actual source.\nPreserve the selected scope.'+(text?'\n'+text:'');
const markdown=['---','name: owned-skill','description: '+JSON.stringify(description.replace(/\s+/g,' ').trim()),'---','',
  '# '+candidate.displayName.trim(),'','## Goal','',description.replace(/\s+/g,' ').trim(),'','## Workflow','',instructions.trim(),''].join('\n');
record('buildSkillCandidateMarkdown',()=>{
  if(category==='empty')equal('buildSkillCandidateMarkdown',[trial,{description:'',instructions:''}],'');
  equal('buildSkillCandidateMarkdown',[trial,{description,instructions}],markdown);
  equal('buildSkillCandidateMarkdown',[{...trial,candidate:{...candidate,targetSkillId:''}},{description,instructions}],'');
});
record('buildSkillCandidateSealPayload',()=>{
  const draft={...trial,state:'trial_active',candidate:{targetSkillId:'owned-skill',displayName:candidate.displayName,activated:false},evidence:[]};
  const options={description,instructions,reviewConfirmed:true,sealedBy:'person-'+text};
  if(category==='empty')reject('buildSkillCandidateSealPayload',[draft,{...options,description:''}]);
  equal('buildSkillCandidateSealPayload',[draft,options],{trialId,skillMarkdown:markdown,displayName:candidate.displayName.trim(),
    defaultPrompt:'Use $owned-skill to '+description.replace(/\s+/g,' ').trim().replace(/^R/,'r')+'.',reviewConfirmed:true,sealedBy:'person-'+text});
  for(const change of [{reviewConfirmed:false},{reviewConfirmed:'true'},{instructions:''}])reject('buildSkillCandidateSealPayload',[draft,{...options,...change}]);
  reject('buildSkillCandidateSealPayload',[{...draft,evidence:[{runId:runPrefix}]},options]);
  reject('buildSkillCandidateSealPayload',[trial,options]);
});
record('synthesisCanEnterLearning',()=>{
  if(category==='empty')equal('synthesisCanEnterLearning',[{}],false);
  const synthesis={synthesisId:'synthesis-'+text,status:'ready',evidence:{_contract:{ready:true},description:text}};
  equal('synthesisCanEnterLearning',[{synthesis}],true);
  for(const change of [{synthesisId:''},{status:text},{evidence:{_contract:{ready:false}}}])equal('synthesisCanEnterLearning',[{synthesis:{...synthesis,...change}}],false);
});
record('eligibleReceiptCandidates',()=>{
  if(category==='empty')equal('eligibleReceiptCandidates',[{receiptComparisons:{candidates:[]}}],[]);
  const good=Array.from({length:size},(_,i)=>measured(i));
  equal('eligibleReceiptCandidates',[{receiptComparisons:{candidates:[{...measured(-1),eligible:false},...good,{...measured(-2),schema:'unknown'},{...measured(-3),turnId:''}]}}],good);
});
record('proofLeaseReceiptCandidates',()=>{
  if(category==='empty')equal('proofLeaseReceiptCandidates',[{}],[]);
  const good=Array.from({length:size},(_,i)=>measured(i));
  equal('proofLeaseReceiptCandidates',[{receiptComparisons:{candidates:[...good,{...measured(-1),authorityRecorded:false},{...measured(-2),verificationStatus:'failed'},{...measured(-3),eligible:false}]}}],good);
});
record('receiptOptionLabel',()=>{
  if(category==='empty')equal('receiptOptionLabel',[{}],'Unknown receipt');
  equal('receiptOptionLabel',[measured(0)],'owned'+(text?' · '+text:'')+' · passed · 1 proof artifact');
  equal('receiptOptionLabel',[{turnId:'turn-'+text,runtime:text,model:text,status:'needs_review',proofArtifactCount:category==='huge'?1000000:2}],
    (text?text+' · '+text:'Recorded run')+' · needs review · '+(category==='huge'?1000000:2)+' proof artifacts');
});
const comparisonOptions={conversationId:'conversation-'+text,missionId:'mission-'+text,baselineTurnId:'baseline-'+text,
  candidateTurnId:'candidate-'+text,sameContractConfirmed:true,operatorValue:'candidate_better',operatorNote:'  '+text+'  '};
record('buildReceiptComparisonPayload',()=>{
  if(category==='empty')reject('buildReceiptComparisonPayload',[trial,{...comparisonOptions,baselineTurnId:''}]);
  equal('buildReceiptComparisonPayload',[trial,comparisonOptions],{trialId,conversationId:comparisonOptions.conversationId,
    missionId:comparisonOptions.missionId,baselineTurnId:comparisonOptions.baselineTurnId,candidateTurnId:comparisonOptions.candidateTurnId,
    sameContractConfirmed:true,operatorValue:'candidate_better',operatorNote:text.trim(),recordedBy:'operator'});
  for(const change of [{sameContractConfirmed:false},{sameContractConfirmed:'true'},{operatorValue:text},{candidateTurnId:comparisonOptions.baselineTurnId},{conversationId:''}])reject('buildReceiptComparisonPayload',[trial,{...comparisonOptions,...change}]);
  reject('buildReceiptComparisonPayload',[{...trial,candidate:{...candidate,activated:true}},comparisonOptions]);
});
record('counterfactualReplayCandidates',()=>{
  if(category==='empty')equal('counterfactualReplayCandidates',[{...trial,evidence:[]}],[]);
  const invalid=[{...comparison(-1),candidatePackageDigest:otherDigest},
    {...comparison(-2),receiptPair:{...comparison(-2).receiptPair,candidatePackageDigest:otherDigest}},
    {...comparison(-3),transcriptsIncluded:true},
    {...comparison(-4),receiptPair:{...comparison(-4).receiptPair,baseline:{authorityRecorded:true,authority:{recorded:false}}}}];
  equal('counterfactualReplayCandidates',[{...trial,evidence:[...evidence,...invalid]}],evidence.slice(-6));
  equal('counterfactualReplayCandidates',[{...trial,candidate:{...candidate,activated:true},evidence}],[]);
});
record('counterfactualCaseLabel',()=>{
  if(category==='empty')equal('counterfactualCaseLabel',[{}],'baseline → candidate · lift unmeasured');
  equal('counterfactualCaseLabel',[{receiptPair:{baseline:{turnId:'before-'+text},candidate:{turnId:'after-'+text}},deltas:{outcomeLift:0.25}}],
    'before-'+text+' → after-'+text+' · 25% lift');
  equal('counterfactualCaseLabel',[{deltas:{outcomeLift:text||'not-measured'}}],'baseline → candidate · lift unmeasured');
});
record('buildCounterfactualForgePayload',()=>{
  const observed={...trial,evidence};
  if(category==='empty')reject('buildCounterfactualForgePayload',[{...trial,evidence:[]},{reviewConfirmed:true}]);
  const cases=evidence.slice(-6).map(r=>r.runId);
  equal('buildCounterfactualForgePayload',[observed,{reviewConfirmed:true,reviewedBy:'person-'+text}],{trialId,caseRunIds:cases,reviewConfirmed:true,reviewedBy:'person-'+text});
  equal('buildCounterfactualForgePayload',[observed,{reviewConfirmed:true,caseRunIds:[cases[0],cases[0],cases[1]]}],{trialId,caseRunIds:cases.slice(0,2),reviewConfirmed:true,reviewedBy:'operator'});
  for(const options of [{reviewConfirmed:false},{reviewConfirmed:'true'},{reviewConfirmed:true,caseRunIds:['not-a-bound-receipt',cases[0]]},{reviewConfirmed:true,caseRunIds:[cases[0]]}])reject('buildCounterfactualForgePayload',[observed,options]);
  reject('buildCounterfactualForgePayload',[{...observed,successContract:{requiredComparableRuns:7}},{reviewConfirmed:true}]);
});
const forge={schema:'neyvia.counterfactual_skill_forge.v1',reviewConfirmed:true,reviewGatePassed:true,recommendedDecision:'accept',
  candidateActivated:false,candidatePackageDigest:digest};
record('counterfactualForgeCanApprove',()=>{
  const approved={...trial,verdict:{counterfactualForge:forge}};
  if(category==='empty')equal('counterfactualForgeCanApprove',[{}],false);
  equal('counterfactualForgeCanApprove',[approved],true);
  for(const change of [{reviewConfirmed:false},{reviewGatePassed:false},{candidateActivated:true},{candidatePackageDigest:otherDigest},{schema:text},{recommendedDecision:'reject'}])
    equal('counterfactualForgeCanApprove',[{...approved,verdict:{counterfactualForge:{...forge,...change}}}],false);
  equal('counterfactualForgeCanApprove',[{...approved,candidate:{...candidate,activated:true}}],false);
});
record('selectSkillMaterializationReview',()=>{
  if(category==='empty')equal('selectSkillMaterializationReview',[{}],null);
  const held={...review,proofLease:{state:'held'}};
  const noise=Array.from({length:size},(_,i)=>({...review,trialId:'noise-'+i,state:'materialized_inactive',proofLease:{state:'held'}}));
  equal('selectSkillMaterializationReview',[{skillMaterializationReviews:[...noise,{...review,proofLease:{state:'reproof_required'}},held]}],held);
});
record('buildSkillMaterializationPayload',()=>{
  if(category==='empty')reject('buildSkillMaterializationPayload',[{...review,candidateDigest:''},{reviewConfirmed:true}]);
  equal('buildSkillMaterializationPayload',[review,{reviewConfirmed:true,materializedBy:'person-'+text}],{trialId,candidateDigest:digest,reviewConfirmed:true,materializedBy:'person-'+text});
  for(const change of [{candidateDigest:''},{state:'accepted'},{canMaterialize:false},{trialId:''}])reject('buildSkillMaterializationPayload',[{...review,...change},{reviewConfirmed:true}]);
  for(const value of [false,'true',1])reject('buildSkillMaterializationPayload',[review,{reviewConfirmed:value}]);
});
record('buildSkillMaterializationRollbackPayload',()=>{
  if(category==='empty')reject('buildSkillMaterializationRollbackPayload',[{...review,materialization:{...materialization,materializationId:''}},{reviewConfirmed:true}]);
  const options={reviewConfirmed:true,rolledBackBy:'person-'+text,reason:'  '+text+'  '};
  equal('buildSkillMaterializationRollbackPayload',[review,options],{materializationId:materialization.materializationId,candidateDigest:digest,reviewConfirmed:true,rolledBackBy:'person-'+text,reason:text.trim()});
  for(const change of [{candidateDigest:''},{state:'active'},{materializationId:''}])reject('buildSkillMaterializationRollbackPayload',[{...review,materialization:{...materialization,...change}},options]);
  reject('buildSkillMaterializationRollbackPayload',[review,{...options,reviewConfirmed:false}]);
});
const pathText=text.split(String.fromCharCode(92)).join('/');
const pathValues=Array.from({length:category==='huge'?14:3},(_,i)=>'owned/'+pathText+'/dependency-'+i+'.md');
const pathInput=pathValues.map(v=>'  '+v.replaceAll('/','\\')+'  ').concat([pathValues[0]]).join('\r\n');
record('proofLeaseDependencyPaths',()=>{
  if(category==='empty')equal('proofLeaseDependencyPaths',[''],[]);
  equal('proofLeaseDependencyPaths',[pathInput],pathValues.slice(0,12));
  equal('proofLeaseDependencyPaths',[Array.from({length:13},(_,i)=>'p'+i).join('\n')],Array.from({length:12},(_,i)=>'p'+i));
});
const goal='Preserve the bounded owned workflow'+(text?' '+text:'');
record('buildProofLeaseEstablishPayload',()=>{
  const options={goalStatement:goal,dependencyPaths:pathInput,reviewAfterDays:365,reviewConfirmed:true,issuedBy:'person-'+text};
  if(category==='empty')reject('buildProofLeaseEstablishPayload',[review,{...options,goalStatement:''}]);
  equal('buildProofLeaseEstablishPayload',[review,options],{materializationId:materialization.materializationId,
    goalStatement:goal.replace(/\s+/g,' ').trim(),dependencyPaths:pathValues.slice(0,12),reviewAfterDays:365,reviewConfirmed:true,issuedBy:'person-'+text});
  for(const days of [0,366,1.5])reject('buildProofLeaseEstablishPayload',[review,{...options,reviewAfterDays:days}]);
  reject('buildProofLeaseEstablishPayload',[review,{...options,goalStatement:'short'}]);
  reject('buildProofLeaseEstablishPayload',[review,{...options,reviewConfirmed:false}]);
  reject('buildProofLeaseEstablishPayload',[{...review,proofLease:{state:'current',canEstablish:true}},options]);
});
record('buildProofLeaseRenewalPayload',()=>{
  const options={conversationId:'conversation-'+text,turnId:'receipt-turn-'+text,goalStillMatches:true,operatorValue:'still_useful',reviewConfirmed:true,renewedBy:'person-'+text};
  if(category==='empty')reject('buildProofLeaseRenewalPayload',[review,{...options,turnId:''}]);
  equal('buildProofLeaseRenewalPayload',[review,options],{materializationId:materialization.materializationId,candidateDigest:digest,
    conversationId:options.conversationId,turnId:options.turnId,goalStillMatches:true,operatorValue:'still_useful',reviewConfirmed:true,renewedBy:'person-'+text});
  for(const change of [{reviewConfirmed:false},{goalStillMatches:false},{goalStillMatches:'true'},{operatorValue:text},{conversationId:''},{turnId:''}])reject('buildProofLeaseRenewalPayload',[review,{...options,...change}]);
  reject('buildProofLeaseRenewalPayload',[{...review,materialization:{...materialization,state:'active'}},options]);
  reject('buildProofLeaseRenewalPayload',[{...review,proofLease:{state:'current',canRenew:false}},options]);
});
record('buildProofLeaseDispositionPayload',()=>{
  const current={...review,proofLease:{state:'review_due'}};
  const options={disposition:'needs_repair',note:'  '+text+'  ',reviewConfirmed:true,recordedBy:'person-'+text};
  if(category==='empty')reject('buildProofLeaseDispositionPayload',[current,{...options,disposition:''}]);
  equal('buildProofLeaseDispositionPayload',[current,options],{materializationId:materialization.materializationId,disposition:'needs_repair',note:text.trim(),reviewConfirmed:true,recordedBy:'person-'+text});
  reject('buildProofLeaseDispositionPayload',[current,{...options,reviewConfirmed:false}]);
  reject('buildProofLeaseDispositionPayload',[current,{...options,disposition:'activate'}]);
  for(const state of ['unestablished','withdrawn',''])reject('buildProofLeaseDispositionPayload',[{...current,proofLease:{state}},options]);
});
record('buildCapabilityAppPrompt',()=>{
  if(category==='empty')equal('buildCapabilityAppPrompt',[{}],'');
  const start='Build an optional Neyvia ecosystem app from the approved capability lineage “'+recommendation.label+'”. Preserve capability ID '+cid+' and the human-reviewed evolution lineage. ';
  const finish=' Keep installation review-gated, expose rollback, and return App Factory proof.';
  equal('buildCapabilityAppPrompt',[recommendation,{verdict:{comparableRunCount:2}}],start+'Use 2 comparable evidence runs as the product baseline.'+finish);
  equal('buildCapabilityAppPrompt',[{...recommendation,evidenceSummary:{feedbackCount:0}}],start+'Do not claim the flow is proven until its comparison evidence is attached.'+finish);
});
if(category==='permissions') {
  rows.length=0;
  const draft={...trial,state:'trial_active',candidate:{targetSkillId:'owned-skill',displayName:candidate.displayName,activated:false},evidence:[]};
  function reviewRemoval(name,input,options,field='reviewConfirmed') {
    assert.notEqual(call(name,input,options),null);
    for(const value of [false,undefined,'true',1])reject(name,[input,{...options,[field]:value}]);
  }
  record('buildCapabilityRunImportPayload',()=>reviewRemoval('buildCapabilityRunImportPayload',bundle(),{reviewConfirmed:true}));
  record('buildSkillCandidateSealPayload',()=>reviewRemoval('buildSkillCandidateSealPayload',draft,{description,instructions,reviewConfirmed:true}));
  record('buildReceiptComparisonPayload',()=>reviewRemoval('buildReceiptComparisonPayload',trial,comparisonOptions,'sameContractConfirmed'));
  record('buildCounterfactualForgePayload',()=>reviewRemoval('buildCounterfactualForgePayload',{...trial,evidence},{reviewConfirmed:true}));
  record('counterfactualForgeCanApprove',()=>{
    equal('counterfactualForgeCanApprove',[{...trial,verdict:{counterfactualForge:forge}}],true);
    for(const field of ['reviewConfirmed','reviewGatePassed'])for(const value of [false,undefined,'true',1])
      equal('counterfactualForgeCanApprove',[{...trial,verdict:{counterfactualForge:{...forge,[field]:value}}}],false);
  });
  record('buildSkillMaterializationPayload',()=>reviewRemoval('buildSkillMaterializationPayload',review,{reviewConfirmed:true}));
  record('buildSkillMaterializationRollbackPayload',()=>reviewRemoval('buildSkillMaterializationRollbackPayload',review,{reviewConfirmed:true}));
  record('buildProofLeaseEstablishPayload',()=>reviewRemoval('buildProofLeaseEstablishPayload',review,{goalStatement:goal,reviewConfirmed:true}));
  record('buildProofLeaseRenewalPayload',()=>reviewRemoval('buildProofLeaseRenewalPayload',review,{conversationId:'conversation-owned',turnId:'receipt-owned',goalStillMatches:true,operatorValue:'still_useful',reviewConfirmed:true}));
  record('buildProofLeaseDispositionPayload',()=>reviewRemoval('buildProofLeaseDispositionPayload',{...review,proofLease:{state:'current'}},{disposition:'needs_repair',reviewConfirmed:true}));
  for(const row of rows)row.detail.adverseBoundary='Explicit frontend review/contract confirmation removed; strict true required; no backend authority grant claimed';
}
if(category==='stale') {
  rows.length=0;
  function invalidate(name,oldArgs,currentArgs,expected) {
    assert.notEqual(call(name,...oldArgs),null);
    equal(name,currentArgs,expected);
  }
  const newCandidate={...candidate,packageDigest:otherDigest,skillMarkdown:'# New reviewed revision'};
  const oldObserved={...trial,evidence}, newObserved={...oldObserved,candidate:newCandidate};
  const draft={...trial,state:'trial_active',candidate:{targetSkillId:'owned-skill',displayName:candidate.displayName,activated:false},evidence:[]};
  record('selectCapabilityRecommendation',()=>{
    const a={...recommendation,capabilityId:'same-a',status:'trial_active',priority:0};
    const b={...recommendation,capabilityId:'same-b',status:'proposed',priority:99};
    equal('selectCapabilityRecommendation',[{recommendations:[a,b]}],a);
    const freshA={...a,status:'review_required'},freshB={...b,status:'trial_active'};
    equal('selectCapabilityRecommendation',[{recommendations:[freshA,freshB]}],freshB);
  });
  record('selectCapabilityRecovery',()=>invalidate('selectCapabilityRecovery',[{capabilityTreasury:{recoveries:[recovery]}}],[{capabilityTreasury:{recoveries:[{...recovery,state:'completed'}]}}],null));
  record('buildCapabilityRecoveryPayload',()=>invalidate('buildCapabilityRecoveryPayload',[recovery],[{...recovery,state:'completed'}],null));
  record('isCapabilityRunBundle',()=>{const prior=bundle();equal('isCapabilityRunBundle',[prior],true);equal('isCapabilityRunBundle',[{...prior,runs:prior.runs.map((run,i)=>i?run:{...run,status:'pending'})}],false);});
  record('buildCapabilityRunImportPayload',()=>invalidate('buildCapabilityRunImportPayload',[bundle(),{reviewConfirmed:true}],[{...bundle(),candidateActivated:true},{reviewConfirmed:true}],null));
  record('skillCandidateRequiresSeal',()=>{const prior={...trial,action:'prove',candidate:{}};equal('skillCandidateRequiresSeal',[prior],false);equal('skillCandidateRequiresSeal',[{...prior,action:'repair'}],true);});
  record('skillCandidateIsSealed',()=>{equal('skillCandidateIsSealed',[trial],true);equal('skillCandidateIsSealed',[{...trial,candidate:{...candidate,state:'unsealed'}}],false);});
  record('skillCandidateCanCompare',()=>{equal('skillCandidateCanCompare',[trial],true);equal('skillCandidateCanCompare',[{...trial,candidate:{...candidate,activated:true}}],false);});
  record('buildSkillCandidateSealPayload',()=>{const options={description,instructions,reviewConfirmed:true};invalidate('buildSkillCandidateSealPayload',[draft,options],[{...draft,evidence:[{runId:'already-measured'}]},options],null);});
  record('synthesisCanEnterLearning',()=>{const prior={synthesisId:'same-synthesis',status:'ready',evidence:{_contract:{ready:true}}};equal('synthesisCanEnterLearning',[{synthesis:prior}],true);equal('synthesisCanEnterLearning',[{synthesis:{...prior,evidence:{_contract:{ready:false}}}}],false);});
  record('eligibleReceiptCandidates',()=>{const prior=measured(0);equal('eligibleReceiptCandidates',[{receiptComparisons:{candidates:[prior]}}],[prior]);equal('eligibleReceiptCandidates',[{receiptComparisons:{candidates:[{...prior,eligible:false}]}}],[]);});
  record('proofLeaseReceiptCandidates',()=>{const prior=measured(0);equal('proofLeaseReceiptCandidates',[{receiptComparisons:{candidates:[prior]}}],[prior]);equal('proofLeaseReceiptCandidates',[{receiptComparisons:{candidates:[{...prior,authorityRecorded:false}]}}],[]);});
  record('buildReceiptComparisonPayload',()=>invalidate('buildReceiptComparisonPayload',[trial,comparisonOptions],[{...trial,candidate:{...candidate,activated:true}},comparisonOptions],null));
  record('counterfactualReplayCandidates',()=>{equal('counterfactualReplayCandidates',[oldObserved],evidence.slice(-6));equal('counterfactualReplayCandidates',[newObserved],[]);});
  record('buildCounterfactualForgePayload',()=>{const options={reviewConfirmed:true,caseRunIds:evidence.slice(-6).map(row=>row.runId)};invalidate('buildCounterfactualForgePayload',[oldObserved,options],[newObserved,options],null);});
  record('counterfactualForgeCanApprove',()=>{equal('counterfactualForgeCanApprove',[{...trial,verdict:{counterfactualForge:forge}}],true);equal('counterfactualForgeCanApprove',[{...trial,candidate:newCandidate,verdict:{counterfactualForge:forge}}],false);});
  record('selectSkillMaterializationReview',()=>{
    const prior={...review,trialId:'old-review',proofLease:{state:'held'}},next={...review,trialId:'next-review',proofLease:{state:'current'}};
    equal('selectSkillMaterializationReview',[{skillMaterializationReviews:[prior,next]}],prior);
    equal('selectSkillMaterializationReview',[{skillMaterializationReviews:[{...prior,state:'materialized_inactive'},next]}],next);
  });
  record('buildSkillMaterializationPayload',()=>invalidate('buildSkillMaterializationPayload',[review,{reviewConfirmed:true}],[{...review,canMaterialize:false},{reviewConfirmed:true}],null));
  record('buildSkillMaterializationRollbackPayload',()=>invalidate('buildSkillMaterializationRollbackPayload',[review,{reviewConfirmed:true}],[{...review,materialization:{...materialization,state:'active'}},{reviewConfirmed:true}],null));
  record('buildProofLeaseEstablishPayload',()=>{const options={goalStatement:goal,reviewConfirmed:true};invalidate('buildProofLeaseEstablishPayload',[review,options],[{...review,proofLease:{state:'current',canEstablish:false}},options],null);});
  record('buildProofLeaseRenewalPayload',()=>{const options={conversationId:'same-conversation',turnId:'old-receipt',goalStillMatches:true,operatorValue:'still_useful',reviewConfirmed:true};invalidate('buildProofLeaseRenewalPayload',[review,options],[{...review,proofLease:{state:'withdrawn',canRenew:false}},options],null);});
  record('buildProofLeaseDispositionPayload',()=>{const options={disposition:'needs_repair',reviewConfirmed:true};invalidate('buildProofLeaseDispositionPayload',[{...review,proofLease:{state:'current'}},options],[{...review,proofLease:{state:'withdrawn'}},options],null);});
  for(const row of rows)row.detail.adverseBoundary='Original identities, receipt selections and review options reused after changing current supplied candidate/evidence/lease status; no backend revision authentication claimed';
}
console.log(JSON.stringify({rows,catalogFrozen:true,catalogSha256:hash(commands),boundary:'synthetic supplied snapshots; real checked model calls; no backend activation or rendered UI'}));
'''


def run(root, contracts, categories):
    repo = Path(__file__).resolve().parents[2]
    rows = []
    for category in categories:
        if category not in TEXT_CATEGORIES | {"permissions", "stale"}:
            continue
        started = time.monotonic()
        completed = subprocess.run(["node", "--input-type=module", "-", str(repo), category], input=NODE,
                                   cwd=repo, capture_output=True, text=True, encoding="utf8", timeout=60, **hidden_windows_subprocess_kwargs())
        if completed.returncode:
            raise RuntimeError("Capability model fixture worker failed: " + completed.stderr[-1600:])
        result = json.loads(completed.stdout)
        for case in result["rows"]:
            if case["contract"] not in contracts:
                raise ValueError("Unknown capability model contract: " + case["contract"])
            rows.append({"id": f"capability-models:{case['contract']}:{category}", "category": category,
                         "contracts": [case["contract"]], "status": case["status"],
                         "detail": case.get("detail", {}), **({"error": case["error"]} if case.get("error") else {}),
                         "boundary": result["boundary"], "catalogFrozen": result["catalogFrozen"],
                         "catalogSha256": result["catalogSha256"],
                         "durationMs": round((time.monotonic() - started) * 1000, 2)})
    return rows


def blocker(contract, category):
    identity = contract["id"]
    if identity not in IDS:
        return None
    owner = "web/src/neyvia/neyviaCapabilityEvolutionModel.js:" + identity.split(".", 1)[1]
    if identity == "capability.capabilityCommands":
        return {"kind": "not_applicable", "reason": f"Audited {owner} accepts zero arguments and returns one frozen command catalog. No input collection/string, I/O, grant, worker or mutable revision exists for {category}; actual catalog contents/frozen state are independently checked in every model campaign."}
    name = identity.split(".", 1)[1]
    if category == "permissions":
        if name in REVIEW_GATES:
            return None
        return {"kind": "not_applicable", "reason": f"Audited {owner} has no explicit review confirmation, principal or target-grant argument: it ranks, labels or projects supplied values. Strict caller review removal is exercised on the ten request/approval helpers that actually read it; backend authorization is a separate boundary."}
    if category == "stale":
        if name in STALE_GATES:
            return None
        return {"kind": "not_applicable", "reason": f"Audited {owner} formats supplied text/paths/labels or constructs a draft lineage and compares no current receipt, package, review, lease or revision claims. Current supplied identity/readiness mutations are exercised on all 22 helpers that read those claims; no backend revision authentication is inferred."}
    if category not in TEXT_CATEGORIES:
        return {"kind": "not_applicable", "reason": f"Audited {owner} synchronously projects caller-supplied snapshots or builds an explicit review request. It owns no network, filesystem, asynchronous worker or shared mutation for {category}. Caller review and current supplied-state mutations are separately exercised wherever read; durable transactions and rendered UI are separate boundaries."}
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from .proof_ports import C7_PORTS
    if args.port not in C7_PORTS:
        parser.error("Explicit assigned port 48741-48749 required")
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("HOME", "USERPROFILE", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        directory = root / "home" / name.lower()
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(directory)
    for name in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT", "NEYVIA_NAS_ROOT", "FLUXIO_NAS_ROOT"):
        os.environ.pop(name, None)
    os.environ.update(NEYVIA_C7_PORT=str(args.port), NEYVIA_COORDINATOR_AUTOSTART="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_TOOL_AUTO_UPDATE="0")
    from .proof_credential_guard import install
    install(root)
    def audit(event, values):
        if event in {"socket.connect", "socket.bind"}:
            raise PermissionError("Capability model fixture has no network authority")
    sys.addaudithook(audit)
    from .edge_contracts import inventory
    _, contracts = inventory()
    repo = Path(__file__).resolve().parents[2]
    before = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in SOURCES}
    started = time.monotonic()
    rows = run(root, contracts, ("empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale"))
    stable = before == {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in SOURCES}
    report = {"schema": "neyvia.c7c.capability-model-fixtures.v1", "ok": stable and all(r["status"] == "passed" for r in rows),
              "sourceStable": stable, "sourceBindings": before, "rows": rows,
              "passedPairs": sum(r["status"] == "passed" for r in rows), "explicitPort": args.port,
              "auditedNotApplicablePairs": [{"contract": identity, "category": category, **reason}
                  for identity in sorted(IDS) for category in ("empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale")
                  if (reason := blocker({"id": identity}, category))],
              "durationMs": round((time.monotonic() - started) * 1000, 2),
              "boundary": "Real checked frontend model calls on synthetic generated snapshots; no rendered UI/backend cryptographic receipt authenticity or activation proof."}
    args.output.resolve().relative_to(repo)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf8")
    print(json.dumps({"ok": report["ok"], "passedPairs": report["passedPairs"],
                      "failed": [r for r in rows if r["status"] == "failed"], "durationMs": report["durationMs"]}))
    return int(not report["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
