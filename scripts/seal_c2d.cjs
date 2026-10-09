/* Seal exact live evidence; unmet gates remain unmet. No service calls. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const repo=path.resolve(__dirname,'..');process.chdir(repo);
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const pin=p=>({path:p,sha256:sha(p),bytes:fs.statSync(p).size});
const quantile=(values,p)=>{const a=[...values].sort((a,b)=>a-b),x=(a.length-1)*p,i=Math.floor(x);return a[i]+(a[Math.min(i+1,a.length-1)]-a[i])*(x-i);};
const inputs={run:'scripts/evidence/C2d-webvoyager-final.json',grades:'scripts/evidence/C2d-webvoyager-grades.json',frozen:'scripts/evidence/C2-webvoyager-tasks.json',baseline:'scripts/evidence/C2c-webvoyager-grades.json',audit:'scripts/evidence/C2d-failure-audit.json',native:'scripts/evidence/C2d-native-receipt-proof.json',site:'scripts/evidence/C2d-site-proof.json',resource:'scripts/evidence/C2d-resource-proof.json',build:'scripts/evidence/C2d-native-build.json',tokens:'scripts/evidence/C2d-token-usage.json',baselineTokens:'scripts/evidence/C2d-baseline-token-usage.json',cleanup:'scripts/evidence/C2d-cleanup.json'};
const data=Object.fromEntries(Object.entries(inputs).map(([key,p])=>[key,read(p)]));
const {run,grades,frozen,native,site,resource,build,tokens,cleanup}=data;
assert.equal(sha(inputs.frozen),'f66cd0713f3634e4db44164bc940e3f2d79e564a98dd0ad05ccc0d7ba1fe2be4');
assert.equal(run.taskSetSha256,sha(inputs.frozen));assert.equal(grades.run.sha256,sha(inputs.run));
assert.equal(grades.grader.source.sha256,sha(grades.grader.source.path));
assert.equal(tokens.run.sha256,sha(tokens.run.path));assert.equal(tokens.meterSource.sha256,sha(tokens.meterSource.path));
assert.equal(data.baselineTokens.run.sha256,sha(data.baselineTokens.run.path));assert.equal(data.baselineTokens.meterSource.sha256,sha(data.baselineTokens.meterSource.path));
assert.equal(run.tasks.length,36);assert.equal(grades.grades.length,36);assert.equal(new Set(run.tasks.map(t=>t.id)).size,36);
assert.equal(grades.summary.ungraded,0);assert.equal(run.stealth,false);assert.equal(frozen.stealth,false);
const definitions=new Map(frozen.tasks.map(t=>[t.id,t])),scored=new Map(grades.grades.map(t=>[t.id,t]));let snapshots=0;
for(const task of run.tasks){
 const definition=definitions.get(task.id);assert(definition);assert.equal(task.goal,definition.goal);assert.equal(task.startUrl,definition.startUrl);
 assert(['answered','failed','skipped'].includes(task.status));assert(task.steps<=definition.maxActions);
 for(const ref of task.observations){assert.equal(sha(ref.path),ref.sha256);snapshots++;}
 const grade=scored.get(task.id);assert(grade);if(grade.success)assert(grade.clauses.length&&grade.clauses.every(c=>c.met&&c.evidence.length));
}
for(const proof of [native,site,resource]){assert(!proof.error);assert(Object.entries(proof.sources).every(([p,h])=>sha(p)===h));}
assert(native.checks.every(c=>c.ok)&&site.checks.every(c=>c.ok));assert.equal(resource.verdict,'deny_verified');assert.equal(resource.crossOriginHits,0);assert.equal(resource.controlHits,1);
assert.equal(native.native.sha256,sha(build.exe));assert.equal(build.sha256,sha(build.exe));assert(Object.entries(build.sources).every(([p,h])=>sha(p)===h));
assert.equal(native.capture.jpeg.sha256,sha(native.capture.jpeg.path));assert(native.capture.jpeg.bytes<500000);
assert.equal(cleanup.listenersInOwnedRange.length,0);assert(cleanup.baselineBinaryExists);
const latency=run.tasks.map(t=>Date.parse(t.finishedAt)-Date.parse(t.startedAt));assert(latency.every(n=>Number.isFinite(n)&&n>=0));
const failures=grades.grades.filter(g=>!g.success).map(g=>({id:g.id,primary:g.primary,secondary:g.secondary,reason:g.reason,missingClauses:g.missingClauses}));
const requested=['planning','search_box','filters','pagination','table_reading','timing','extraction','answer_formatting','grader_disagreement'];
const causeCounts=Object.fromEntries([...new Set([...requested,...failures.map(f=>f.primary)])].map(c=>[c,{primary:failures.filter(f=>f.primary===c).length,secondary:failures.filter(f=>f.secondary?.includes(c)).length}]));
const previousSkips=data.baseline.grades.filter(g=>g.outcome==='skipped').map(g=>({id:g.id,baselineReason:g.reason,currentOutcome:scored.get(g.id).outcome,success:scored.get(g.id).success}));
const manualDir=path.join(run.root,'.neyvia/browser/site-manuals');
const manualFiles=fs.existsSync(manualDir)?fs.readdirSync(manualDir).filter(n=>n.endsWith('.json')).map(n=>pin(path.join(manualDir,n))):[];
const history=read('scripts/evidence/C2d-history-archives.json');
const zlib=require('node:zlib');for(const archive of history.archives){assert.equal(sha(archive.path),archive.sha256);assert.equal(crypto.createHash('sha256').update(zlib.gunzipSync(fs.readFileSync(archive.path))).digest('hex'),archive.originalSha256);}
function size(p){if(!fs.existsSync(p))return 0;const stat=fs.lstatSync(p);if(stat.isSymbolicLink())return 0;return stat.isDirectory()?fs.readdirSync(p).reduce((n,f)=>n+size(path.join(p,f)),0):stat.size;}
const retained={runtimeProfilesAndProofs:size('.agent_control/proofs/C2d'),taskEngineAndCandidate:size('.agent_control/C2d'),evidence:fs.readdirSync('scripts/evidence').filter(n=>n.startsWith('C2d')||n==='--backend-port').reduce((n,f)=>n+size(path.join('scripts/evidence',f)),0)};
retained.total=Object.values(retained).reduce((a,b)=>a+b,0);assert(retained.total<2*1024**3);
const decisions=run.calls.filter(c=>c.op==='decide');
const metrics={tasks:36,passed:grades.summary.passed,failed:grades.summary.failed,skipped:grades.summary.skipped,successOverAll:grades.summary.passed/36,taskLatencyP50Ms:quantile(latency,.5),taskLatencyP95Ms:quantile(latency,.95),stepsP50:quantile(run.tasks.map(t=>t.steps),.5),verifiedSnapshots:snapshots,nativeChecks:native.checks.length,siteChecks:site.checks.length,coreChecks:native.checks.length+site.checks.length};
// The independent grade uses nearest-rank percentiles; use the conventional
// average of the two middle samples for the requested median and comparison.
assert.equal([...latency].sort((a,b)=>a-b)[17],grades.metrics.taskLatencyP50Ms);
metrics.quantileMethod='Linear interpolation; p50 is the median of all36 original timers';
metrics.gradeNearestRankP50Ms=grades.metrics.taskLatencyP50Ms;
const limitations=[
 'The 36/36 and median-under30s targets are not achieved. Failed clauses and causes remain explicit.',
 'This is an iterative operator-assisted live panel across repaired source versions, engines and restarts. Original timers include all intervening work; no clean fixed-version unattended performance claim.',
 'Clause review prompted evidence extraction and answer-format corrections; their original answers/attempts remain retained. This is not an untouched fully blinded comparative arm.',
 'Native batching can stop between steps on a fresh stale revision. Current native form proof uses separately refreshed actions; successful Obscura batching and fail-closed native receipts have separate proof.',
 'LAYA is still a bounded frozen named-click adviser. Current real accept/reject decisions do not establish general planning coverage or repeat the older339/339 calibration benchmark.',
 'Codex windows overlap tasks and include review/repair overhead. Numeric token usage is real; exact causal per-task allocation and dollar/subscription costs are unmeasured.',
 'Existing Obscura binary was copied to task-local storage after the earlier path disappeared. Current identity is pinned; equivalence to the vanished original bytes is unproven.',
 'Chrome surfaces were unavailable. Real native WebView2 and Obscura pages, compressed native screenshot and actual effect receipts are the verified boundaries.',
 'Cumulative OS write volume was not instrumented. Retained task artifacts are measured separately; own temporary binary/PDB outputs were removed, shared dependencies and baseline keepers preserved.'
];
const receipt={schema:'neyvia.C2d.complete-everything@1',sealedAt:new Date().toISOString(),mechanism:'Fresh observed site CL learning/reuse, search-first form controls, bounded semantic batches, fail-closed effect receipts, writable calendar roles, pointer activation and late actionable-control projection; existing frozen LAYA gate',status:'target_unmet',metrics,gates:{all36Passed:metrics.passed===36,medianUnder30Seconds:metrics.taskLatencyP50Ms<30000,allPreviouslySkippedPassed:previousSkips.every(t=>t.success),frozenTasksUnchanged:true,coreLiveProofPassed:true,requestedOutcomeComplete:false},baseline:{passed:12,failed:21,skipped:3,taskLatencyP50Ms:135521.01545000012,receipt:pin(inputs.baseline)},previousSkips,failures,causeCounts,requestedCategoriesWithoutCurrentFailure:requested.filter(c=>!causeCounts[c].primary&&!causeCounts[c].secondary),receipts:Object.fromEntries(Object.entries(inputs).map(([k,p])=>[k,pin(p)])),sources:Object.fromEntries(['scripts/seal_c2d.cjs','src/grant_agent/browser_dom.js','src/grant_agent/browser_site_manuals.py','src/grant_agent/browser_obscura.py','src/grant_agent/neyvia_browser.py','scripts/c2d_webvoyager.cjs','scripts/c2d_token_meter.cjs','scripts/build_c2_browser_manual.py','manuals/browser.manual.json','manuals/cl/browser.cl'].map(p=>[p,sha(p)])),currentNative:pin(build.exe),renderedProof:{path:native.capture.jpeg.path,sha256:native.capture.jpeg.sha256,leadViewed:true,observed:'Pointer opened; Clicks1; Submitted native receipt; selected October5'},runtimeSegments:run.runtimeSegments,siteManuals:{files:manualFiles,taskUses:run.tasks.map(t=>({id:t.id,uses:t.manualUses||[]})),proofBoundary:'Fresh fixture demonstrates learn/reuse/quarantine and no query/result persistence. Live task uses remain individually recorded.'},laya:{liveCalls:decisions.map(c=>({taskId:c.taskId,startedAt:c.startedAt,response:c.response})),coverageClaim:null,proofBoundary:'Accepted adviser selection is not task completion; every executed effect needs its own action receipt.'},cost:{unionTokens:tokens.unionTokens,sources:tokens.sources.length,tasks:tokens.tasks.length,ambiguousTasks:tokens.tasks.filter(t=>t.attribution==='ambiguous_overlap').length,estimatedUSD:null,boundary:tokens.costBoundary},cleanup,limitations,remainingWork:'Repair stable semantic revision/atomic native batches, historical and date-scoped search/filter coverage, exhaustive negative-set checks, and unattended scheduling. Google News unusual-traffic CAPTCHA requires the normal owner path; no bypass.'};
receipt.artifactInventory={retainedBytes:retained,boundary:'Current logical artifact sizes, excluding preserved shared dependency/incremental cache; cumulative writes are unmeasured'};
receipt.historyArchives={receipt:pin('scripts/evidence/C2d-history-archives.json'),verified:history.archives.length};
const output='scripts/evidence/C2d.json';fs.writeFileSync(output,JSON.stringify(receipt,null,2)+'\n');
const ci={method:'not-estimable',reason:'Descriptive correlated iterative live panel, not a blinded comparative or population estimate.'};
const row={schema:'neyvia.efficiency-result.v1',id:'C2d-webvoyager',study:'C2d repaired browser CL mechanism and frozen36 live rerun',method:'Independently reviewed all frozen clauses against SHA-verified actual observations. Original wall timers include recovery, repair and explicit answer corrections. Public tasks and native failure checks share existing browser APIs.',models:['Codex lead and GPT-6.1 Sol high workers/reviewer','Frozen CPU LAYA g3-c2 explicit named-click head'],tasks:{description:'Same36 public WebVoyager goals across12 sites; all originally skipped Cambridge tasks retried through a normal native path',repetitions:1,independent_unit:'public task/site group'},limitations,receipts:[{id:'seal',...pin(output),kind:'raw'}],metrics:[['passed','count','passed'],['failed','count','failed'],['skipped','count','skipped'],['success_over_all','fraction','successOverAll'],['task_latency_p50','ms','taskLatencyP50Ms'],['task_latency_p95','ms','taskLatencyP95Ms'],['steps_p50','steps','stepsP50'],['core_live_checks','count','coreChecks']].map(([name,unit,key])=>({name,unit,calculation:{receipt:'seal',pointer:'/metrics/'+key},ci_request:ci})),evidence_status:'raw-verified'};
fs.writeFileSync('scripts/evidence/C2d-efficiency-result.json',JSON.stringify(row,null,2)+'\n');
console.log(JSON.stringify({output,metrics,gates:receipt.gates,failedTasks:failures.map(f=>f.id)}));
