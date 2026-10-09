/* Seal measured boundaries, including failed goals. No service calls. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
process.chdir(path.resolve(__dirname,'..'));
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const pin=p=>({path:p,sha256:sha(p),bytes:fs.statSync(p).size});
const quantile=(values,p)=>{const a=values.filter(Number.isFinite).sort((a,b)=>a-b);if(!a.length)return null;const x=(a.length-1)*p,i=Math.floor(x);return a[i]+(a[Math.min(i+1,a.length-1)]-a[i])*(x-i);};
const arg=(flag,fallback)=>process.argv.includes(flag)?process.argv[process.argv.indexOf(flag)+1]:fallback;
const inputs={run:arg('--run','scripts/evidence/C2f-frozen36-sealed.json'),grades:arg('--grades','scripts/evidence/C2f-grades.json'),
 profile:arg('--profile','scripts/evidence/C2f-profile-sealed.json'),script:'scripts/evidence/C2f-script-proof.json',pane:'scripts/evidence/C2f-pane-proof.json',
 laya:'scripts/evidence/C2f-laya-topic-fork.json',engine:'scripts/evidence/C2f-engine-admission.json',engineBuild:'scripts/evidence/C2f-engine-source-build.json',
 causal:'scripts/evidence/C2f-engine-fetch-proof.json',compiledSearch:'scripts/evidence/C2f-bbc-compiled-sealed.json',siteCauses:'scripts/evidence/C2f-site-cause-audit.json',
 preservation:'scripts/evidence/C2f-preservation-note.json',runtimeFreeze:'scripts/evidence/C2f-runtime-source-freeze.json',cleanup:'scripts/evidence/C2f-cleanup.json',checks:'scripts/evidence/C2f-checks.json',tasks:'scripts/evidence/C2-webvoyager-tasks.json',baseline:'scripts/evidence/C2d.json'};
const data=Object.fromEntries(Object.entries(inputs).map(([key,p])=>[key,read(p)]));
const {run,grades,profile,script,pane,laya,engine,engineBuild,cleanup,checks,tasks,baseline}=data;
assert.equal(sha(inputs.tasks),'f66cd0713f3634e4db44164bc940e3f2d79e564a98dd0ad05ccc0d7ba1fe2be4');
assert.equal(run.taskSetSha256,sha(inputs.tasks));assert.equal(grades.run.sha256,sha(inputs.run));
assert.equal(grades.grader.source.sha256,sha(grades.grader.source.path));assert.equal(grades.grader.review.sha256,sha(grades.grader.review.path));
assert.equal(grades.summary.ungraded,0);assert.equal(grades.draft,false);assert.equal(run.stealth,false);
assert.equal(run.tasks.length,36);assert.equal(grades.grades.length,36);assert.equal(new Set(run.tasks.map(t=>t.id)).size,36);
const definitions=new Map(tasks.tasks.map(t=>[t.id,t])),scored=new Map(grades.grades.map(t=>[t.id,t]));let snapshots=0;
const perTask=run.tasks.map(task=>{
 const definition=definitions.get(task.id);assert(definition);assert.equal(task.goal,definition.goal);assert.equal(task.startUrl,definition.startUrl);
 assert(task.steps<=definition.maxActions,task.id+' action budget');assert(task.finishedAt);assert(Number.isFinite(task.elapsedMs));
 for(const ref of task.observations){assert.equal(sha(ref.path),ref.sha256);snapshots++;}
 const grade=scored.get(task.id);assert(grade);if(grade.success)assert(grade.clauses.length&&grade.clauses.every(c=>c.met&&c.evidence.length));
 const norm=value=>String(value??'').replace(/\s+/gu,' ').trim();
 for(const clause of grade.clauses)for(const e of clause.evidence){
   const ref=task.observations.find(ref=>ref.path===e.path);assert(ref,task.id+' citation belongs to task');
   assert.equal(ref.sha256,e.sha256);const observed=read(e.path),field=observed[e.field??'text'];
   assert(norm(typeof field==='object'?JSON.stringify(field):field).includes(norm(e.quote)),task.id+' citation quote');
 }
 const calls=run.calls.filter(c=>c.taskId===task.id);
 return {id:task.id,goal:task.goal,outcome:grade.outcome,success:grade.success,elapsedMs:task.elapsedMs,
   endToEndGoalElapsedMs:grade.success?task.elapsedMs:null,steps:task.steps,timing:task.timing,browserCalls:calls.length,
   tokens:task.tokens,paidProviderCostUSD:task.paidModelCostUSD,engineeringTokens:null,totalDollarCostUSD:null,
   laya:task.laya||null,reason:grade.reason,answer:task.answer||null,observations:task.observations};
});
for(const proof of [script,pane]){assert.equal(proof.ok,true);assert(proof.checks.every(c=>c.ok));for(const [p,h] of Object.entries(proof.sources))assert.equal(sha(p),h,p);}
for(const t of profile.tasks)if(t.observation)assert.equal(sha(t.observation.path),t.observation.sha256);
for(const binary of [engine.engineBinary,engine.workerBinary]){assert.equal(sha(binary.path),binary.sha256);assert.equal(fs.statSync(binary.path).size,binary.bytes);}
assert.equal(engine.stealth,false);assert.equal(cleanup.ownedListenersRemaining.length,0);assert.equal(checks.ok,true);
assert.equal(engineBuild.exitCode,0);assert.equal(data.causal.ok,true);assert(data.causal.checks.every(c=>c.ok));
assert.equal(engine.runtimeProof.sha256,sha(inputs.causal));assert.equal(laya.ok,true);
assert.equal(sha(data.siteCauses.sourceRun.path),data.siteCauses.sourceRun.sha256);
assert.equal(sha(data.siteCauses.bbcRepairProof.path),data.siteCauses.bbcRepairProof.sha256);
assert.equal(sha('scripts/evidence/C2f-site-engine-audit.log'),data.siteCauses.engineLog.sha256);
for(const row of data.causal.runs){assert.equal(sha(row.engineLog),row.engineLogSha256);assert.equal(sha('scripts/evidence/C2f-loader-'+row.name+'.log'),row.engineLogSha256);}
assert.equal(data.compiledSearch.ok,true);assert.equal(data.compiledSearch.replay.tokens,0);assert.equal(data.compiledSearch.replay.modelCalls,0);
for(const proof of [script,pane])for(const key of ['engineBinary','workerBinary'])assert.equal(proof.engineAdmission[key].sha256,engine[key].sha256);
for(const [p,h] of Object.entries(data.runtimeFreeze.sources))assert.equal(sha(p),h,p+' changed after runtime freeze');
for(const [p,h] of Object.entries(checks.sources))assert.equal(sha(p),h,p+' check source changed');
const passed=perTask.filter(t=>t.success),six=['Apple--2','BBC News--1','BBC News--2','ESPN--2','GitHub--0','GitHub--1'];
const metrics={tasks:36,passed:grades.summary.passed,failed:grades.summary.failed,needsOwner:grades.summary.needs_owner,
 successOverAll:grades.summary.passed/36,taskLatencyP50Ms:quantile(perTask.map(t=>t.elapsedMs),.5),taskLatencyP95Ms:quantile(perTask.map(t=>t.elapsedMs),.95),
 gradeNearestRankP95Ms:grades.metrics.deterministicTaskLatencyP95NearestRankMs??grades.metrics.deterministicTaskLatencyP95Ms,completeGoalLatencyP50Ms:quantile(passed.map(t=>t.elapsedMs),.5),
 completeGoalLatencyP95Ms:quantile(passed.map(t=>t.elapsedMs),.95),completeGoalTimingSamples:passed.length,
 tokensPerTask:0,paidProviderCostPerTaskUSD:0,totalDollarCostPerTaskUSD:null,
 quantileMethod:'Linear interpolation for seal/ledger; grader p95 separately retains its nearest-rank definition',verifiedSnapshots:snapshots};
assert(perTask.every(t=>t.tokens===0&&t.paidProviderCostUSD===0));
const sourcePaths=['scripts/seal_c2f.cjs','scripts/c2f_replay.cjs','scripts/c2f_answers.cjs','scripts/c2f_site_flows.cjs','scripts/c2f_profile.cjs',
 'scripts/c2f_script_proof.cjs','scripts/c2f_pane_proof.cjs','scripts/c2f_search_compile.cjs','scripts/c2f_engine_fetch_proof.cjs','scripts/c2f_build_obscura.cjs','scripts/obscura-v024-fetch-retention.patch',
 'scripts/build_c2f_browser_manual.py','src/grant_agent/browser_scripts.py','src/grant_agent/browser_dom.js','src/grant_agent/browser_site_manuals.py',
 'src/grant_agent/browser_obscura.py','src/grant_agent/neyvia_browser.py','src/grant_agent/neyvia_panes.py','src/grant_agent/neyvia_workspace_tools.py',
 'web/src/neyvia/next/NxBrowser.jsx','web/src/neyvia/next/NxBrowserParts.jsx','web/src/neyvia/next/NxPanes.jsx','web/src/neyvia/next/nxBrowserApi.js',
 'manuals/cl/browser.cl','manuals/browser.manual.json','config/browser.manual.contract.json','docs/manuals/browser-side-pane.md'];
const limitations=[
 'Frozen tasks are unchanged; this is a warm learned-route replay plus observed-control repairs, not a cold unseen-site benchmark or paired comparator.',
 'Only independently passed returned answers have complete-goal latency. Fast failed or owner-needed attempts are not successful tasks.',
 'The harness schedules three isolated profile/space tasks concurrently through separate CDP profile workers; native calls within each profile serialize and share the managed engine resources.',
 'Execution uses zero provider tokens and no paid provider calls. Codex engineering/adviser tokens, subscription dollars, CPU/electricity and operator time are unmetered.',
 'LAYA proof is one bounded frozen CPU title choice with a native postcheck; readiness choices in failed tasks often escalate. General planning remains unproven.',
 'Managed runtime uses task-local hash-admitted binaries. Another checkout needs the admitted pair or the recorded source build prerequisites; no global installation was made.',
 'The pane proof uses the real full shell/event bus and headless UI renderer with a disposable page. Public desktop, login, microphone and release behavior are outside this proof.',
 'CAPTCHA/login walls stay owner-needed; Google News was not opened or attempted. No stealth, public service restart, credentials or NAS operations.',
 'Original baseline timing did not separately instrument model thinking versus operator idle. Its unexplained remainder is explicitly unattributed.'
 ,'Two pre-capacity-fix profile observations were accidentally overwritten on rerun; their timing/receipt history remains but their original full-observation hashes are not reproducible. The final profile and frozen36 hashes are independently valid.'
];
const old=read('scripts/evidence/C2d-webvoyager-final.json'),slow=old.tasks.find(t=>t.id==='ArXiv--0');
const slowCalls=old.calls.filter(c=>c.taskId===slow.id);const serviceMs=slowCalls.reduce((sum,c)=>sum+(c.ms||0),0);
const receipt={schema:'neyvia.C2f.complete-everything@1',sealedAt:new Date().toISOString(),status:metrics.passed===36&&metrics.taskLatencyP50Ms<30000?'complete':'target_unmet',
 mechanism:'First-success parameterized CL scripts with fresh goal checks and quarantine; event-driven verified action batches; independent profile/tab work; frozen CPU LAYA advisory choices; managed non-stealth Obscura frames/input with renderer acknowledgement',
 metrics,perTask,gates:{all36Passed:metrics.passed===36,attemptMedianUnder30Seconds:metrics.taskLatencyP50Ms<30000,
   completeGoalMedianUnder30Seconds:passed.length===36&&metrics.completeGoalLatencyP50Ms<30000,
   sixEngineeringGoalsPassed:six.every(id=>scored.get(id).success),nativeCompiledCL:true,fullShellFramesInputAndAcknowledgement:true,frozenTasksUnchanged:true,
   requestedOutcomeComplete:metrics.passed===36&&metrics.taskLatencyP50Ms<30000},
 profiling:{baselineTask:{id:slow.id,elapsedMs:slow.elapsedMs,recordedToolMs:serviceMs,unattributedMs:slow.elapsedMs-serviceMs,
   modelThinkingMs:null,operatorIdleMs:null,receipt:pin('scripts/evidence/C2d-webvoyager-final.json')},current:profile},
 baseline:{commit:'8f6c9ab2',passed:baseline.metrics.passed,taskLatencyP50Ms:baseline.metrics.taskLatencyP50Ms,
   comparableBoundary:'Earlier operator-driven timers include manual scheduling; present warm scripts are a different execution arm, with strict all-clause grading.'},
 engineeringGoals:six.map(id=>({id,outcome:scored.get(id).outcome,reason:scored.get(id).reason})),
 siteCauses:{classification:data.siteCauses.classification,retainedAuditLog:pin('scripts/evidence/C2f-site-engine-audit.log'),retainedFinalLog:pin('scripts/evidence/C2f-site-engine-final.log')},
 engine:{admission:engine,build:engineBuild,causalProof:data.causal,retainedLogs:data.causal.runs.map(row=>pin('scripts/evidence/C2f-loader-'+row.name+'.log'))},compiledSearch:data.compiledSearch,
 laya:{accepted:laya.accepted??laya.decision?.accepted_decision,proofBoundary:'Actual frozen CPU inference and fresh native title postcheck; no training'},
 renderedProof:{screenshot:pin(pane.screenshot),leadViewed:true,checks:pane.checks.map(c=>({name:c.name,ok:c.ok}))},
 receipts:Object.fromEntries(Object.entries(inputs).map(([key,p])=>[key,pin(p)])),sources:Object.fromEntries(sourcePaths.map(p=>[p,sha(p)])),cleanup,limitations,
 needsPaul:perTask.filter(t=>t.outcome==='needs_owner').map(t=>({id:t.id,reason:t.reason,action:'Normal owner access if desired; no challenge bypass'}))};
fs.writeFileSync(arg('--out','scripts/evidence/C2f.json'),JSON.stringify(receipt,null,2)+'\n');
const ci={method:'not-estimable',reason:'One correlated frozen warm replay panel without matched comparator or independent deployment repetitions'};
const result={schema:'neyvia.efficiency-result.v1',id:'C2f-final-warm-replay',study:'C2f frozen36 warm browser scripts and observed-control repairs',
 method:'Fresh public pages, retained previous successful observed routes, deterministic returned extraction, independent every-clause review; failed attempts and owner walls included',
 models:['none for compiled execution; frozen local LAYA g3-c2 advisory CPU head; Codex engineering and independent reviewer unmetered'],
 tasks:{description:'36 frozen WebVoyager tasks across12sites',repetitions:1,independent_unit:'site/task group'},evidence_status:'raw-verified',limitations,
 receipts:[{id:'seal',...pin(arg('--out','scripts/evidence/C2f.json')),kind:'raw'}],
 metrics:[['success','count','passed'],['failed','count','failed'],['owner_needed','count','needsOwner'],['success_over_all','fraction','successOverAll'],
   ['attempt_p50','ms','taskLatencyP50Ms'],['attempt_p95','ms','taskLatencyP95Ms'],['provider_tokens_per_task','tokens','tokensPerTask'],['provider_dollars_per_task','USD','paidProviderCostPerTaskUSD']]
   .map(([name,unit,key])=>({name,unit,calculation:{receipt:'seal',pointer:'/metrics/'+key},ci_request:ci}))};
fs.writeFileSync('scripts/evidence/C2f-efficiency-result.json',JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify({metrics,gates:receipt.gates}));
